"""Discover and re-index manifest-only session orphans (`forge session repair`).

A session manifest with no index row is invisible to `forge session list` yet
still owns its name and its conversation binding (design.md §3.2). The scan
classifies every unindexed manifest under one Forge project; apply re-publishes
repairable and valid missing-worktree records through the same creation
transaction ordinary session creation uses, so a repaired row is
indistinguishable from a natively created one.

Classification and identity follow the ratified decisions on the board card
(docs/board/doing/session_orphan_manifest_repair/checklist.md, D1-D6):

- Identity derives from the manifest's **recorded** worktree metadata; the
  manifest's on-disk location supplies only ``forge_root``. A root-level
  worktree session keeps its manifest under the main checkout while its
  session checkout is the recorded linked worktree, so deriving from location
  would silently repoint it (D1).
- A missing recorded worktree remains a live degraded shape for worktree-backed
  sessions (``is_worktree=True``). Repair may publish its existing manifest and
  recorded path without recreating or claiming the checkout. Only the ordinary
  moved-checkout shape re-derives from the manifest's actual location and
  corrects stale ``worktree.path``/``forge_root`` on disk.
  ``confirmed.claude_project_root`` is never touched: it points at Claude Code's
  conversation namespace, which a checkout move does not relocate (D2).
- Collisions refuse, not bind (D3). Live bindings are gathered with the same
  three-source, fail-closed semantics the adoption scans use
  (``collect_bound_uuids`` / ``collect_bound_codex_threads`` without the
  per-root orphan walk: index columns can lag or lead the manifest behind the
  row, so both are read). Sibling orphans sharing one conversation resolve
  deterministically: the first in directory order stays repairable, later ones
  classify ``collision``. ``create_session_txn(require_uuid_unbound=True)``
  re-checks the columns under the index lock as the final race arbiter.
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

from forge.core.ops.session_context import (
    collect_bound_codex_threads,
    collect_bound_uuids,
    manifest_dirs,
)
from forge.core.state.exceptions import StateCorruptedError, StateUnreadableError
from forge.install.project_compat import enforce_project_compatibility
from forge.session import IndexStore, SessionManager, SessionState
from forge.session.exceptions import (
    ForgeSessionError,
    ManifestChangedError,
    SessionExistsError,
    SessionFileNotFoundError,
    UuidAlreadyBoundError,
)
from forge.session.identity import make_scoped_key
from forge.session.launchability import derive_launchability
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

    Collision detection is fail-closed: live bindings come from the index rows
    **and** the manifest behind each row (columns lag or lead manifests), via
    the adoption scans called without a ``forge_root`` so this project's
    orphans -- the very manifests being classified -- are not counted as live
    holders. An unreadable row manifest aborts the scan rather than letting a
    conversation look free.

    Raises:
        IndexCorruptedError / IndexUnreadableError: If the index cannot be read.
        BindingLookupError: If the sessions directory cannot be listed, or a
            live row's manifest cannot be read.
    """
    root = Path(forge_root).resolve()
    root_str = str(root)
    index_store = IndexStore()
    rows = index_store.read().sessions

    uuid_holders = collect_bound_uuids()
    thread_holders = collect_bound_codex_threads()
    # Sibling orphans sharing one conversation: first in directory order wins,
    # later claimants classify collision (the txn column check would refuse the
    # second apply anyway; classifying at scan makes the preview say so).
    orphan_uuid_claims: dict[str, str] = {}
    orphan_thread_claims: dict[str, str] = {}

    manager = SessionManager(index_store=index_store)
    records: list[OrphanRecord] = []
    for manifest_dir in manifest_dirs(root_str):
        name = manifest_dir.name
        if make_scoped_key(name, root_str) in rows:
            continue  # healthy: row and manifest both present
        manifest_path = get_manifest_path(root, name)
        if not manifest_path.is_file():
            continue  # session dir without a manifest: nothing to index

        def record(
            classification: Classification,
            detail: str,
            *,
            claude_session_id: str | None = None,
            codex_thread_id: str | None = None,
            collision_holder: str | None = None,
            manifest_sha256: str | None = None,
            identity: RepairIdentity | None = None,
        ) -> None:
            records.append(
                OrphanRecord(
                    name=name,
                    manifest_dir=str(manifest_dir),
                    classification=classification,
                    detail=detail,
                    claude_session_id=claude_session_id,
                    codex_thread_id=codex_thread_id,
                    collision_holder=collision_holder,
                    manifest_sha256=manifest_sha256,
                    identity=identity,
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
        uuid_key = claude_id.lower() if claude_id else None
        thread_key = thread_id.lower() if thread_id else None
        bound_holder: str | None = None
        if uuid_key:
            bound_holder = uuid_holders.get(uuid_key) or orphan_uuid_claims.get(uuid_key)
        if bound_holder is None and thread_key:
            bound_holder = thread_holders.get(thread_key) or orphan_thread_claims.get(thread_key)
        if bound_holder:
            record(
                "collision",
                f"conversation already bound to session {bound_holder}",
                claude_session_id=claude_id,
                codex_thread_id=thread_id,
                collision_holder=bound_holder,
                manifest_sha256=digest,
            )
            continue
        if uuid_key:
            orphan_uuid_claims[uuid_key] = name
        if thread_key:
            orphan_thread_claims[thread_key] = name

        worktree = state.worktree
        if worktree is None:
            record(
                "unrepairable",
                "manifest records no worktree block",
                claude_session_id=claude_id,
                codex_thread_id=thread_id,
                manifest_sha256=digest,
            )
            continue

        recorded = Path(worktree.path)
        if derive_launchability(recorded) == "launchable":
            identity = _derive_identity(recorded, root, manager)
            record(
                "repairable",
                "recorded checkout present",
                claude_session_id=claude_id,
                codex_thread_id=thread_id,
                identity=identity,
                manifest_sha256=digest,
            )
        elif worktree.is_worktree:
            identity = _derive_missing_worktree_identity(recorded, root, manager)
            record(
                "missing-worktree",
                f"recorded worktree is gone: {worktree.path}",
                claude_session_id=claude_id,
                codex_thread_id=thread_id,
                identity=identity,
                manifest_sha256=digest,
            )
        else:
            # Ordinary shape: the manifest lives inside its own checkout, so the
            # checkout provably moved here and the recorded absolute path went
            # stale with the move (D2). Re-derive from the actual location and
            # correct the recorded path at apply. Worktree.path's contract is
            # the checkout root, not the forge_root, so a nested .forge/ still
            # records the enclosing checkout.
            derived = _derive_identity(root, root, manager)
            identity = replace(
                derived,
                worktree_path=derived.checkout_root,
                corrected_worktree_path=derived.checkout_root,
            )
            record(
                "repairable",
                f"checkout moved; stale recorded path {worktree.path} will be corrected",
                claude_session_id=claude_id,
                codex_thread_id=thread_id,
                identity=identity,
                manifest_sha256=digest,
            )

    return RepairScanReport(forge_root=root_str, records=tuple(records))


def repair_orphans(
    forge_root: str | Path,
    records: tuple[OrphanRecord, ...],
) -> RepairApplyResult:
    """Re-index the ``repairable`` records through the creation transaction.

    Fails closed on an incompatible project pin before any write. Collisions
    are refused without an attempt. ``missing-worktree`` records are publishable
    as degraded rows; corrupt, unreadable, and unrepairable records are skipped.

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
        if rec.classification not in {"repairable", "missing-worktree"}:
            continue
        identity = rec.identity
        if identity is None or rec.manifest_sha256 is None:
            failed.append(ApplyItem(rec.name, "repairable record missing identity or hash"))
            continue
        # A normal repair must not publish a path that vanished after scan. A
        # missing-worktree repair intentionally publishes the degraded row; the
        # surviving manifest, not checkout presence, is the liveness authority.
        if rec.classification == "repairable" and derive_launchability(identity.worktree_path) != "launchable":
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
        if corrected:
            # The row must carry the corrected identity; the callback persists
            # the same correction to the manifest after the hash proof (D6).
            if state.worktree:
                state.worktree.path = corrected
            state.forge_root = root_str

        def write_manifest(s: SessionStore = store, r: OrphanRecord = rec, fix: str | None = corrected) -> None:
            def _correct(manifest_state: SessionState) -> None:
                # Relocate the recorded checkout and forge root. The Claude
                # namespace pointer (confirmed.claude_project_root) is
                # deliberately untouched: it records where Claude Code keeps
                # the conversation (~/.claude/projects/<encoded-cwd>/), which
                # a filesystem move of the checkout does not change.
                if manifest_state.worktree is not None and fix is not None:
                    manifest_state.worktree.path = fix
                manifest_state.forge_root = root_str

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


def _derive_missing_worktree_identity(
    recorded_worktree: Path,
    forge_root: Path,
    manager: SessionManager,
) -> RepairIdentity:
    """Build a row from surviving manifest facts without probing the gone checkout."""
    project_root = Path(manager.resolve_project_root(forge_root))
    try:
        relative_path = str(forge_root.relative_to(project_root))
    except ValueError:
        relative_path = "."
    return RepairIdentity(
        worktree_path=str(recorded_worktree),
        checkout_root=str(recorded_worktree),
        project_root=str(project_root),
        relative_path=relative_path,
    )
