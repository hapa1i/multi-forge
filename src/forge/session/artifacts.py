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

from .claude.paths import find_project_root

logger = logging.getLogger(__name__)


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

    return ArtifactPaths(
        forge_root=forge_root,
        artifacts_root_abs=artifacts_root_abs,
        artifacts_root_rel=artifacts_root_rel,
        plans_abs=plans_abs,
        plans_rel=plans_rel,
        transcripts_abs=transcripts_abs,
        transcripts_rel=transcripts_rel,
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
