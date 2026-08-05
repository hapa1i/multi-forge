"""Session artifact helpers.

This module implements Forge-project-local artifact storage for sessions.

Artifacts are stored under the **Forge project root** (``forge_root``):

- <forge_root>/.forge/artifacts/<session_name>/plans/
- <forge_root>/.forge/artifacts/<session_name>/transcripts/

The session manifest records artifact paths under ``confirmed.artifacts`` as
**forge-root-relative** paths (e.g., ``.forge/artifacts/...``).
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .claude.paths import find_project_root
from .exceptions import TranscriptArtifactStateError
from .models import CompactionConfirmed, SessionState

logger = logging.getLogger(__name__)


# Transcript-artifact `reason` values. This one lives here rather than with its
# writing op (`core.ops.session_adopt`) because `session.manager` reads it during
# deletion, and the session layer cannot import from core.ops.
ADOPT_ARTIFACT_REASON = "adopt"

_CANONICAL_TRANSCRIPT = "canonical"
_LEGACY_PATH_TRANSCRIPT = "legacy_path"
_LEGACY_PRECOMPACT_SNAPSHOT = "legacy_precompact"


@dataclass(frozen=True)
class ArtifactPaths:
    """Computed artifact roots for a session."""

    forge_root: Path
    artifacts_root_abs: Path
    artifacts_root_rel: Path

    plans_abs: Path
    plans_rel: Path

    transcripts_abs: Path
    transcripts_rel: Path

    shadow_abs: Path
    shadow_rel: Path


def _non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value)


def _invalid_precompact_snapshot_fields(entry: dict[str, Any]) -> list[str]:
    invalid: list[str] = []
    if entry.get("reason") != "pre-compact":
        invalid.append("reason")
    for name in ("captured_at", "source_path", "snapshot_path"):
        if not _non_empty_string(entry.get(name)):
            invalid.append(name)
    if not isinstance(entry.get("copied"), bool):
        invalid.append("copied")
    if "session_id" in entry:
        invalid.append("session_id")
    if "copied_path" in entry:
        invalid.append("copied_path")
    return invalid


def _transcript_entry_kind(entry: object, *, index: int) -> str:
    """Classify one persisted transcript entry without silently skipping bad state."""
    if not isinstance(entry, dict):
        raise TranscriptArtifactStateError(f"entry {index} must be an object, got {type(entry).__name__}")

    copied_path = entry.get("copied_path")
    session_id = entry.get("session_id")
    snapshot_path = entry.get("snapshot_path")

    if _non_empty_string(copied_path):
        if snapshot_path is not None:
            raise TranscriptArtifactStateError(
                f"entry {index} mixes canonical copied_path with compaction snapshot_path"
            )
        if _non_empty_string(session_id):
            return _CANONICAL_TRANSCRIPT
        if "session_id" not in entry:
            # Older path-only entries are an explicit read-compatibility shape. New
            # writes always carry both identity fields and never create this form.
            return _LEGACY_PATH_TRANSCRIPT
        raise TranscriptArtifactStateError(f"entry {index} has a non-string or empty session_id")

    if copied_path is not None:
        raise TranscriptArtifactStateError(f"entry {index} has a non-string or empty copied_path")

    if entry.get("reason") == "pre-compact" and "session_id" not in entry:
        invalid = _invalid_precompact_snapshot_fields(entry)
        if invalid:
            details = ", ".join(invalid)
            raise TranscriptArtifactStateError(f"entry {index} has an invalid legacy PreCompact field: {details}")
        return _LEGACY_PRECOMPACT_SNAPSHOT

    raise TranscriptArtifactStateError(
        f"entry {index} is neither a canonical transcript nor a recognized legacy PreCompact snapshot"
    )


def _validated_transcript_entries(state: SessionState) -> list[tuple[dict[str, Any], str]]:
    artifacts = state.confirmed.artifacts
    if not isinstance(artifacts, dict):
        raise TranscriptArtifactStateError(f"confirmed.artifacts must be an object, got {type(artifacts).__name__}")

    if "transcripts" not in artifacts:
        return []
    raw_entries = artifacts["transcripts"]
    if not isinstance(raw_entries, list):
        raise TranscriptArtifactStateError(f"expected a list, got {type(raw_entries).__name__}")

    entries: list[tuple[dict[str, Any], str]] = []
    for index, raw_entry in enumerate(raw_entries):
        kind = _transcript_entry_kind(raw_entry, index=index)
        assert isinstance(raw_entry, dict)
        entries.append((raw_entry, kind))
    return entries


def _validated_compaction_snapshots(state: SessionState) -> list[dict[str, Any]]:
    compaction = state.confirmed.compaction
    if compaction is None:
        return []
    snapshots = compaction.transcript_snapshots
    if not isinstance(snapshots, list):
        raise TranscriptArtifactStateError(
            f"expected a list, got {type(snapshots).__name__}",
            field="confirmed.compaction.transcript_snapshots",
        )
    for index, snapshot in enumerate(snapshots):
        if not isinstance(snapshot, dict):
            raise TranscriptArtifactStateError(
                f"entry {index} must be an object, got {type(snapshot).__name__}",
                field="confirmed.compaction.transcript_snapshots",
            )
        invalid = _invalid_precompact_snapshot_fields(snapshot)
        if invalid:
            details = ", ".join(invalid)
            raise TranscriptArtifactStateError(
                f"entry {index} has an invalid PreCompact field: {details}",
                field="confirmed.compaction.transcript_snapshots",
            )
    return snapshots


def migrate_legacy_transcript_snapshots(state: SessionState) -> int:
    """Move recognized legacy PreCompact records out of the canonical transcript list.

    Migration is lazy at a transcript-related write seam. Existing compaction
    records are deduplicated by ``snapshot_path`` because the old PreCompact
    writer stored the same record in both collections.
    """
    entries = _validated_transcript_entries(state)
    legacy = [entry for entry, kind in entries if kind == _LEGACY_PRECOMPACT_SNAPSHOT]
    if not legacy:
        return 0

    snapshots = _validated_compaction_snapshots(state)
    migrated_snapshots = list(snapshots)
    existing_paths = {snapshot["snapshot_path"] for snapshot in snapshots}
    for snapshot in legacy:
        snapshot_path = snapshot["snapshot_path"]
        if snapshot_path not in existing_paths:
            migrated_snapshots.append(dict(snapshot))
            existing_paths.add(snapshot_path)

    if state.confirmed.compaction is None:
        state.confirmed.compaction = CompactionConfirmed(transcript_snapshots=migrated_snapshots)
    else:
        state.confirmed.compaction.transcript_snapshots = migrated_snapshots
    state.confirmed.artifacts["transcripts"] = [entry for entry, kind in entries if kind != _LEGACY_PRECOMPACT_SNAPSHOT]
    logger.warning(
        "migrated %d recognized legacy PreCompact snapshot(s) from confirmed.artifacts.transcripts",
        len(legacy),
    )
    return len(legacy)


def reconcile_transcript_artifact(
    state: SessionState,
    entry: dict[str, Any],
    *,
    refresh_existing: bool = True,
) -> int:
    """Replace one canonical transcript identity and preserve every distinct record.

    When ``refresh_existing`` is false, the newest matching record is retained;
    rollover and failed best-effort copies use that path so a skipped copy cannot
    replace successful provenance with ``copied=False``. Returns the number of
    matching records replaced or removed. Invalid durable state raises before the
    store transaction writes, allowing hook callers to apply their established
    fail-open behavior without clobbering the original value.
    """
    if _transcript_entry_kind(entry, index=0) != _CANONICAL_TRANSCRIPT:
        raise TranscriptArtifactStateError("new transcript records require non-empty session_id and copied_path")

    migrate_legacy_transcript_snapshots(state)
    entries = _validated_transcript_entries(state)
    identity = (entry["session_id"], entry["copied_path"])
    reconciled: list[dict[str, Any]] = []
    matching: list[dict[str, Any]] = []
    for existing, kind in entries:
        if kind == _CANONICAL_TRANSCRIPT and (existing["session_id"], existing["copied_path"]) == identity:
            matching.append(existing)
            continue
        reconciled.append(existing)
    if matching and not refresh_existing:
        reconciled.append(matching[-1])
        changed = len(matching) - 1
    else:
        reconciled.append(dict(entry))
        changed = len(matching)
    state.confirmed.artifacts["transcripts"] = reconciled
    return changed


def latest_transcript_artifact_path(state: SessionState) -> str | None:
    """Return the newest canonical copied path after validating the whole collection."""
    entries = _validated_transcript_entries(state)
    latest: str | None = None
    legacy_paths = 0
    legacy_snapshots = 0
    for entry, kind in entries:
        if kind == _LEGACY_PRECOMPACT_SNAPSHOT:
            legacy_snapshots += 1
            continue
        if kind == _LEGACY_PATH_TRANSCRIPT:
            legacy_paths += 1
        latest = entry["copied_path"]

    if legacy_snapshots:
        logger.warning(
            "recognized %d legacy PreCompact snapshot(s) in confirmed.artifacts.transcripts; "
            "the next transcript write will migrate them",
            legacy_snapshots,
        )
    if legacy_paths:
        logger.warning(
            "recognized %d legacy copied_path-only transcript record(s); new writes use complete identity",
            legacy_paths,
        )
    return latest


def resolve_forge_root(cwd: Path) -> Path:
    """Resolve the Forge project root for artifact storage.

    Preference order:
    1) Walk up from *cwd* looking for ``.forge/`` (Forge project anchor)
    2) Fallback to git-aware main-repo detection (worktree safe)
    3) Fallback to walking upwards for a ``.git`` entry
    4) Final fallback to cwd

    In most managed sessions, the caller should prefer the session's
    stored ``forge_root`` over this heuristic.
    """
    # Prefer .forge/ directory as the Forge project anchor
    from forge.core.ops.context import find_forge_root

    forge_root = find_forge_root(cwd)
    if forge_root is not None:
        return forge_root

    try:
        from .worktree import get_main_repo_root

        return get_main_repo_root(cwd)
    except Exception as e:
        logger.debug("get_main_repo_root failed: %s, trying find_project_root", e)
        try:
            return find_project_root(str(cwd))
        except Exception as e2:
            logger.debug("find_project_root failed: %s, falling back to cwd", e2)
            return cwd.resolve()


def get_artifact_paths(forge_root: Path, session_name: str) -> ArtifactPaths:
    """Compute standard artifact directories for a session.

    Args:
        forge_root: Forge project root (where .forge/ lives).
        session_name: Forge session name.

    Returns:
        ArtifactPaths with absolute + forge-root-relative paths.
    """

    forge_root = forge_root.resolve()

    artifacts_root_rel = Path(".forge") / "artifacts" / session_name
    artifacts_root_abs = forge_root / artifacts_root_rel

    plans_rel = artifacts_root_rel / "plans"
    plans_abs = forge_root / plans_rel

    transcripts_rel = artifacts_root_rel / "transcripts"
    transcripts_abs = forge_root / transcripts_rel

    shadow_rel = artifacts_root_rel / "shadow"
    shadow_abs = forge_root / shadow_rel

    return ArtifactPaths(
        forge_root=forge_root,
        artifacts_root_abs=artifacts_root_abs,
        artifacts_root_rel=artifacts_root_rel,
        plans_abs=plans_abs,
        plans_rel=plans_rel,
        transcripts_abs=transcripts_abs,
        transcripts_rel=transcripts_rel,
        shadow_abs=shadow_abs,
        shadow_rel=shadow_rel,
    )


def resolve_artifact_path(forge_root: Path, stored_path: str | Path | None) -> Path | None:
    """Resolve a stored artifact path against the owning Forge project root.

    Artifact paths recorded in manifests are normally forge-root-relative
    (for example ``.forge/artifacts/...``), but this helper also accepts
    absolute paths as a compatibility fallback.
    """
    if stored_path is None:
        return None

    candidate = Path(stored_path).expanduser()
    if candidate.is_absolute():
        return candidate
    return forge_root.resolve() / candidate


def ensure_dirs(paths: ArtifactPaths) -> None:
    """Create artifact directories if needed."""

    paths.plans_abs.mkdir(parents=True, exist_ok=True)
    paths.transcripts_abs.mkdir(parents=True, exist_ok=True)


def safe_copy_file(src: Path, dst: Path, *, overwrite: bool = False) -> bool:
    """Copy a file with idempotent semantics.

    Args:
        src: Source file.
        dst: Destination file.
        overwrite: Whether to overwrite if dst exists.

    Returns:
        True if a copy occurred, False if skipped.

    Raises:
        FileNotFoundError: if src does not exist.
    """

    if not src.is_file():
        raise FileNotFoundError(str(src))

    dst.parent.mkdir(parents=True, exist_ok=True)

    if dst.exists() and not overwrite:
        return False

    shutil.copy2(src, dst)
    return True


def make_timestamp_suffix() -> str:
    """Return a filesystem-friendly UTC timestamp suffix (``YYYYMMDD_HHMMSS``)."""
    from datetime import UTC, datetime

    return datetime.now(UTC).strftime("%Y%m%d_%H%M%S")


def make_content_hash(data: bytes, *, length: int = 12) -> str:
    """Return a short hex digest for content-addressable filenames.

    12 hex chars = 48 bits of entropy — enough that collisions across a single
    user's plan history are not a practical concern.
    """
    import hashlib

    return hashlib.sha256(data).hexdigest()[:length]


def snapshot_plan_approved(
    *,
    paths: ArtifactPaths,
    source_plan_path: Path,
) -> tuple[Path, Path]:
    """Snapshot an approved plan file into a human-readable destination.

    Filename format: ``{stem}-{hash}.md`` where ``stem`` is the source plan's
    filename stem and ``hash`` is a 12-char SHA-256 prefix of the file content.
    Same source file with same content always produces the same path (dedup).
    Different source filenames with identical content produce distinct paths —
    accepted tradeoff for human-readable snapshot names.

    Returns:
        (snapshot_abs_path, snapshot_rel_path)
    """

    ensure_dirs(paths)

    content = source_plan_path.read_bytes()
    digest = make_content_hash(content)
    stem = source_plan_path.stem or digest
    dst_name = f"{stem}-{digest}.md"

    snapshot_abs = paths.plans_abs / dst_name
    snapshot_rel = paths.plans_rel / dst_name

    safe_copy_file(source_plan_path, snapshot_abs, overwrite=False)
    return snapshot_abs, snapshot_rel
