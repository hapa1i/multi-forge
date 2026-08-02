"""Discover and re-index manifest-only session orphans (`forge session repair`).

A session manifest with no index row is invisible to `forge session list` yet
still owns its name and its conversation binding (design.md §3.2). The scan
classifies every unindexed manifest under one Forge project; apply re-publishes
repairable ones through the same creation transaction ordinary session creation
uses, so a repaired row is indistinguishable from a natively created one.

Classification and identity follow the ratified decisions on the board card
(docs/board/doing/session_orphan_manifest_repair/checklist.md, D1-D6):

- Identity derives from the manifest's **recorded** worktree metadata; the
  manifest's on-disk location supplies only ``forge_root``. A root-level
  worktree session keeps its manifest under the main checkout while its
  session checkout is the recorded linked worktree, so deriving from location
  would silently repoint it (D1).
- A missing recorded worktree is report-only for worktree-backed shapes
  (``is_worktree=True``); only the ordinary shape may re-derive from the
  actual location -- its manifest travels inside its own checkout by
  construction -- correcting the stale recorded path (D2).
- Collisions refuse, not bind: ``create_session_txn(require_uuid_unbound=True)``
  re-checks both conversation ids under the index lock (D3).
- Corrupt manifests belong to ``forge clean``; unreadable ones to neither and
  are never deleted by either surface (D4).
- Apply verifies the manifest is byte-identical to the scanned copy instead of
  writing one (``SessionStore.update_if_unchanged``); a mismatch makes the
  transaction compensate the row away (D6).

Repair takes no conversation lock: the orphan manifest itself already owns the
binding, so a concurrent adopt's fail-closed manifest scan refuses the id, and
the transaction's in-lock column check covers live rows.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from forge.core.ops.session_context import manifest_dirs
from forge.core.state.exceptions import StateCorruptedError, StateUnreadableError
from forge.install.project_compat import enforce_project_compatibility
from forge.session import IndexStore, SessionManager
from forge.session.exceptions import (
    ForgeSessionError,
    ManifestChangedError,
    SessionExistsError,
    SessionFileNotFoundError,
    UuidAlreadyBoundError,
)
from forge.session.identity import make_scoped_key, session_name_from_key
from forge.session.store import CLI_LOCK_TIMEOUT_S, SessionStore, get_manifest_path
from forge.session.worktree import get_repo_root

logger = logging.getLogger(__name__)

Classification = Literal[
    "repairable",
    "missing-worktree",
    "collision",
    "corrupt",
    "unreadable",
    "unrepairable",
]


@dataclass(frozen=True)
class RepairIdentity:
    """Identity fields a repaired index row will carry (D1)."""

    worktree_path: str
    checkout_root: str
    project_root: str
    relative_path: str
    # Set when the moved-checkout rule applied (D2): the manifest's recorded
    # worktree path is stale and apply also corrects it on disk.
    corrected_worktree_path: str | None = None


@dataclass(frozen=True)
class OrphanRecord:
    """One unindexed manifest and what repair may do with it."""

    name: str
    manifest_dir: str
    classification: Classification
    detail: str
    claude_session_id: str | None = None
    codex_thread_id: str | None = None
    collision_holder: str | None = None
    manifest_sha256: str | None = None
    identity: RepairIdentity | None = None


@dataclass(frozen=True)
class RepairScanReport:
    """Read-only classification of every unindexed manifest under one project."""

    forge_root: str
    records: tuple[OrphanRecord, ...] = ()

    def by_classification(self, classification: Classification) -> tuple[OrphanRecord, ...]:
        return tuple(r for r in self.records if r.classification == classification)


@dataclass(frozen=True)
class ApplyItem:
    name: str
    reason: str


@dataclass(frozen=True)
class RepairApplyResult:
    """Per-item apply outcomes; refusals and failures never abort the batch."""

    repaired: tuple[str, ...] = ()
    refused: tuple[ApplyItem, ...] = ()
    failed: tuple[ApplyItem, ...] = ()

    @property
    def clean(self) -> bool:
        return not self.refused and not self.failed


def scan_repairable_orphans(forge_root: str | Path) -> RepairScanReport:
    """Classify every manifest under ``forge_root`` that has no index row.

    Read-only: no index write, no prune, no manifest write. Healthy sessions
    (row present) are excluded; a bare row without a manifest is prunable
    residue and is not this surface's concern.

    Raises:
        IndexCorruptedError / IndexUnreadableError: If the index cannot be read.
        BindingLookupError: If the sessions directory cannot be listed.
    """
    root = Path(forge_root).resolve()
    root_str = str(root)
    index_store = IndexStore()
    rows = index_store.read().sessions

    uuid_holders: dict[str, str] = {}
    thread_holders: dict[str, str] = {}
    for key, entry in rows.items():
        holder = f"{session_name_from_key(key)} ({entry.root})"
        if entry.claude_session_id:
            uuid_holders.setdefault(entry.claude_session_id, holder)
        if entry.codex_thread_id:
            thread_holders.setdefault(entry.codex_thread_id, holder)

    manager = SessionManager(index_store=index_store)
    records: list[OrphanRecord] = []
    for manifest_dir in manifest_dirs(root_str):
        name = manifest_dir.name
        if make_scoped_key(name, root_str) in rows:
            continue  # healthy: row and manifest both present
        manifest_path = get_manifest_path(root, name)
        if not manifest_path.is_file():
            continue  # session dir without a manifest: nothing to index

        def record(classification: Classification, detail: str, **kwargs: object) -> None:
            records.append(
                OrphanRecord(
                    name=name,
                    manifest_dir=str(manifest_dir),
                    classification=classification,
                    detail=detail,
                    **kwargs,  # type: ignore[arg-type]
                )
            )

        try:
            raw = manifest_path.read_bytes()
        except OSError as e:
            record("unreadable", f"read error: {e}")
            continue
        digest = hashlib.sha256(raw).hexdigest()

        try:
            state = SessionStore(root_str, name).read()
        except StateUnreadableError as e:
            record("unreadable", str(e))
            continue
        except StateCorruptedError as e:
            record("corrupt", str(e), manifest_sha256=digest)
            continue
        except SessionFileNotFoundError:
            continue  # vanished mid-scan

        claude_id = state.confirmed.claude_session_id
        codex = state.confirmed.codex
        thread_id = codex.thread_id if codex else None
        ids = {"claude_session_id": claude_id, "codex_thread_id": thread_id}

        bound_holder: str | None = None
        if claude_id and claude_id in uuid_holders:
            bound_holder = uuid_holders[claude_id]
        elif thread_id and thread_id in thread_holders:
            bound_holder = thread_holders[thread_id]
        if bound_holder:
            record(
                "collision",
                f"conversation already bound to live session {bound_holder}",
                collision_holder=bound_holder,
                manifest_sha256=digest,
                **ids,
            )
            continue

        worktree = state.worktree
        if worktree is None:
            record("unrepairable", "manifest records no worktree block", manifest_sha256=digest, **ids)
            continue

        recorded = Path(worktree.path)
        if recorded.exists():
            identity = _derive_identity(recorded, root, manager)
            record(
                "repairable",
                "recorded checkout present",
                identity=identity,
                manifest_sha256=digest,
                **ids,
            )
        elif worktree.is_worktree:
            record(
                "missing-worktree",
                f"recorded worktree is gone: {worktree.path}",
                manifest_sha256=digest,
                **ids,
            )
        else:
            # Ordinary shape: the manifest lives inside its own checkout, so the
            # checkout provably moved here and the recorded absolute path went
            # stale with the move (D2). Re-derive from the actual location and
            # correct the recorded path at apply.
            identity = replace(_derive_identity(root, root, manager), corrected_worktree_path=root_str)
            record(
                "repairable",
                f"checkout moved; stale recorded path {worktree.path} will be corrected",
                identity=identity,
                manifest_sha256=digest,
                **ids,
            )

    return RepairScanReport(forge_root=root_str, records=tuple(records))


def repair_orphans(
    forge_root: str | Path,
    records: tuple[OrphanRecord, ...],
) -> RepairApplyResult:
    """Re-index the ``repairable`` records through the creation transaction.

    Fails closed on an incompatible project pin before any write. Collisions
    are refused without an attempt; report-only classifications (corrupt,
    unreadable, missing-worktree, unrepairable) are not apply targets and are
    skipped silently -- the scan report already carries their guidance.

    Raises:
        ProjectCompatibilityError: If the project pin refuses mutation (D5).
    """
    root = Path(forge_root).resolve()
    root_str = str(root)
    enforce_project_compatibility(root)

    index_store = IndexStore()
    repaired: list[str] = []
    refused: list[ApplyItem] = []
    failed: list[ApplyItem] = []

    for rec in records:
        if rec.classification == "collision":
            refused.append(ApplyItem(rec.name, rec.detail))
            continue
        if rec.classification != "repairable":
            continue
        identity = rec.identity
        if identity is None or rec.manifest_sha256 is None:
            failed.append(ApplyItem(rec.name, "repairable record missing identity or hash"))
            continue
        # Prune stability (D2): never publish a row the list_sessions prune
        # would immediately delete.
        if not Path(identity.worktree_path).exists():
            refused.append(
                ApplyItem(rec.name, f"recorded checkout vanished between scan and apply: {identity.worktree_path}")
            )
            continue

        store = SessionStore(root_str, rec.name)
        try:
            raw = store.manifest_path.read_bytes()
        except OSError as e:
            refused.append(ApplyItem(rec.name, f"manifest no longer readable: {e}"))
            continue
        if hashlib.sha256(raw).hexdigest() != rec.manifest_sha256:
            refused.append(ApplyItem(rec.name, "manifest changed since it was scanned"))
            continue
        try:
            state = store.read()
        except ForgeSessionError as e:
            refused.append(ApplyItem(rec.name, f"manifest changed since it was scanned: {e}"))
            continue

        corrected = identity.corrected_worktree_path
        if corrected and state.worktree:
            # The row must carry the corrected path; the callback persists the
            # same correction to the manifest after the hash proof (D6).
            state.worktree.path = corrected

        def write_manifest(s: SessionStore = store, r: OrphanRecord = rec, fix: str | None = corrected) -> None:
            def _correct(manifest_state: object) -> None:
                worktree = getattr(manifest_state, "worktree", None)
                if worktree is not None and fix is not None:
                    worktree.path = fix

            assert r.manifest_sha256 is not None
            s.update_if_unchanged(
                r.manifest_sha256,
                timeout_s=CLI_LOCK_TIMEOUT_S,
                mutate=_correct if fix else None,
            )

        try:
            index_store.create_session_txn(
                state,
                identity.project_root,
                checkout_root=identity.checkout_root,
                forge_root=root_str,
                relative_path=identity.relative_path,
                require_uuid_unbound=True,
                write_manifest=write_manifest,
            )
        except UuidAlreadyBoundError as e:
            refused.append(ApplyItem(rec.name, f"conversation bound to a live session: {e}"))
        except SessionExistsError:
            refused.append(ApplyItem(rec.name, "name claimed by a live session since the scan"))
        except (ManifestChangedError, SessionFileNotFoundError) as e:
            refused.append(ApplyItem(rec.name, f"manifest changed or vanished during apply: {e}"))
        except Exception as e:
            logger.debug("Repair of session %r failed", rec.name, exc_info=True)
            failed.append(ApplyItem(rec.name, str(e)))
        else:
            repaired.append(rec.name)

    return RepairApplyResult(repaired=tuple(repaired), refused=tuple(refused), failed=tuple(failed))


def _derive_identity(anchor: Path, forge_root: Path, manager: SessionManager) -> RepairIdentity:
    """Recompute row identity from ``anchor`` with creation's own helpers (D1).

    Mirrors ``SessionManager.start_session``'s derivation, including its
    fallbacks: a non-git anchor falls back to itself for ``checkout_root``,
    and a ``forge_root`` outside ``checkout_root`` (the root-level worktree
    shape) defaults ``relative_path`` to ``"."``.
    """
    worktree_path = str(anchor)
    try:
        checkout_root = str(get_repo_root(anchor))
    except Exception:
        checkout_root = worktree_path
    project_root = manager.resolve_project_root(worktree_path)
    try:
        relative_path = str(forge_root.relative_to(checkout_root))
    except ValueError:
        relative_path = "."
    return RepairIdentity(
        worktree_path=worktree_path,
        checkout_root=checkout_root,
        project_root=project_root,
        relative_path=relative_path,
    )
