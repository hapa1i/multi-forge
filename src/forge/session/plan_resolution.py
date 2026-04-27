"""Resolve plan info for a derived session, with one-level parent fallback.

v1 walks only the immediate parent. Extend via ``derivation.lineage`` with a
loop guard if deeper walks become necessary.

Parent sources (in order of preference):

1. ``confirmed.derivation`` — set by ``forge session resume`` and
   ``forge session fork`` (carries ``parent_forge_root`` for cross-project
   pointers).
2. ``state.parent_session`` top-level — legacy fallback for older fork
   manifests that predate fork derivation metadata.

When only the top-level field is present, the parent's ``forge_root`` is looked
up via ``IndexStore``. Same-dir forks can still fall back to the caller's
``current_forge_root`` when the parent manifest is physically present there.

Authority rule: approved plan snapshots (``confirmed.artifacts["plans"]``) are
preferred over ``latest_plan_path`` drafts — same ordering as
``forge.session.handoff._resolve_plan_content``. Callers should render the
snapshot path when present and fall through to the draft only if absent.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal

from .exceptions import (
    ManifestCorruptedError,
    ManifestValidationError,
    SessionFileNotFoundError,
)
from .models import SessionState
from .store import SessionStore

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlanInfo:
    """What plan info applies to a session, and where it came from.

    ``draft_path`` is Claude-launch-root-relative (nested projects launch from
    ``forge_root``; root-level worktrees launch from ``worktree.path``).
    ``snapshot_path`` entries in ``approved_snapshots`` are forge-root-relative
    (see artifacts.py:7-11). The ``parent_*_root`` fields carry the roots that
    make those paths resolvable for inherited plans.
    """

    draft_path: str | None = None
    approved_snapshots: list[dict[str, Any]] = field(default_factory=list)
    source: Literal["self", "parent"] | None = None
    parent_session: str | None = None
    parent_forge_root: str | None = None
    parent_launch_root: str | None = None


@dataclass(frozen=True)
class DisplayedPath:
    """Absolute plan path plus on-disk existence status, for user-facing display."""

    path: str
    exists: bool


def resolve_plan_info(state: SessionState, *, current_forge_root: str) -> PlanInfo:
    """Return plan info for the given session, falling back to the immediate parent."""

    confirmed = state.confirmed
    self_snapshots = _plan_snapshots(confirmed.artifacts)

    if confirmed.latest_plan_path or self_snapshots:
        return PlanInfo(
            draft_path=confirmed.latest_plan_path,
            approved_snapshots=self_snapshots,
            source="self",
        )

    parent_name, parent_fr = _resolve_parent_pointer(state, current_forge_root)
    if parent_name is None or parent_fr is None:
        return PlanInfo()

    try:
        parent_state = SessionStore(parent_fr, parent_name).read()
    except (SessionFileNotFoundError, ManifestCorruptedError, ManifestValidationError) as exc:
        _log.debug("Parent manifest unreadable for %s at %s: %s", parent_name, parent_fr, exc)
        return PlanInfo()
    except Exception as exc:  # pragma: no cover - defense-in-depth for unexpected IO/permission
        _log.debug("Unexpected error reading parent %s at %s: %s", parent_name, parent_fr, exc)
        return PlanInfo()

    parent_confirmed = parent_state.confirmed
    parent_snapshots = _plan_snapshots(parent_confirmed.artifacts)
    if not parent_confirmed.latest_plan_path and not parent_snapshots:
        return PlanInfo()

    return PlanInfo(
        draft_path=parent_confirmed.latest_plan_path,
        approved_snapshots=parent_snapshots,
        source="parent",
        parent_session=parent_name,
        parent_forge_root=parent_fr,
        parent_launch_root=resolve_plan_launch_root(parent_state),
    )


def latest_snapshot_path(snapshots: list[dict[str, Any]]) -> str | None:
    """Return the `snapshot_path` of the last approved snapshot, or None."""
    if not snapshots:
        return None
    last = snapshots[-1]
    path = last.get("snapshot_path")
    return path if isinstance(path, str) else None


def preferred_plan_path(info: PlanInfo) -> str | None:
    """Return the best plan path to show the user (approved snapshot > draft)."""
    return latest_snapshot_path(info.approved_snapshots) or info.draft_path


def resolve_displayed_plan_path(
    info: PlanInfo,
    *,
    current_forge_root: str,
    current_launch_root: str | None = None,
    current_worktree: str | None = None,
) -> DisplayedPath | None:
    """Resolve an absolute on-disk path for the preferred plan path, with existence check.

    Returns ``None`` when no plan path is recorded. Otherwise returns the
    absolute path (or the raw relative string if no resolution base is
    available) and whether the file exists on disk.
    """

    snap_rel = latest_snapshot_path(info.approved_snapshots)
    if snap_rel is not None:
        # Snapshot is forge-root-relative (artifacts.py:7-11).
        base = info.parent_forge_root if info.source == "parent" else current_forge_root
        return _resolve_against(snap_rel, base)

    if info.draft_path:
        # Draft is Claude-launch-root-relative. Keep ``current_worktree`` as a
        # backward-compatible fallback for older callers/tests.
        launch_root = current_launch_root or current_worktree
        base = info.parent_launch_root if info.source == "parent" else launch_root
        return _resolve_against(info.draft_path, base)

    return None


def resolve_plan_launch_root(state: SessionState) -> str | None:
    """Return the root against which ``latest_plan_path`` should be resolved."""
    if state.confirmed.claude_project_root:
        return state.confirmed.claude_project_root

    if not state.worktree and not state.forge_root:
        return None

    try:
        from .claude.paths import resolve_claude_project_root

        return resolve_claude_project_root(state)
    except Exception:  # pragma: no cover - defensive fallback for malformed state
        return state.forge_root or (state.worktree.path if state.worktree else None)


def resolve_path_against(rel_or_abs: str, base: str | None) -> DisplayedPath:
    """Join ``rel_or_abs`` against ``base`` unless it's already absolute; probe existence."""
    from pathlib import Path

    candidate = Path(rel_or_abs).expanduser()
    if not candidate.is_absolute():
        if base is None:
            # No root to resolve against — return the bare string. Existence undecidable.
            return DisplayedPath(path=rel_or_abs, exists=False)
        candidate = Path(base) / candidate
    try:
        resolved = candidate.resolve()
    except OSError:
        return DisplayedPath(path=str(candidate), exists=False)
    return DisplayedPath(path=str(resolved), exists=resolved.is_file())


# Internal alias retained for backward-compat within the module.
_resolve_against = resolve_path_against


def _resolve_parent_pointer(state: SessionState, current_forge_root: str) -> tuple[str | None, str | None]:
    """Find the (parent_name, parent_forge_root) tuple from whichever field is set."""
    derivation = state.confirmed.derivation
    if derivation is not None and derivation.parent_session:
        return derivation.parent_session, (derivation.parent_forge_root or current_forge_root)

    if state.parent_session:
        name = state.parent_session
        resolved_root = _lookup_parent_forge_root(state, name, current_forge_root)
        if resolved_root is not None:
            return name, resolved_root

        # Same-dir forks are allowed to fall back to the child's forge_root only
        # when the parent manifest is actually present there.
        try:
            if SessionStore(current_forge_root, name).exists():
                return name, current_forge_root
        except Exception:  # pragma: no cover - invalid path / unexpected FS failure
            pass

        _log.debug(
            "Parent session %s referenced by %s could not be resolved from index or current forge_root %s",
            name,
            state.name,
            current_forge_root,
        )
        return None, None

    return None, None


def _lookup_parent_forge_root(
    state: SessionState,
    parent_name: str,
    current_forge_root: str,
) -> str | None:
    """Resolve the parent's forge_root, scoped by the child's ``project_root``.

    Forks never cross logical repos (design.md §3), so siblings in the same
    ``project_root`` are the correct search space. Unscoped lookups raise
    ``AmbiguousSessionError`` when the same session name exists in multiple
    Forge projects, which silently falls back to ``current_forge_root`` — the
    wrong answer for ``--worktree`` / ``--into`` forks.
    """
    try:
        from .index import IndexStore

        store = IndexStore()
        child_entry = _child_index_entry(store, state, current_forge_root)
        if child_entry is None or not child_entry.project_root:
            return None

        siblings = [
            entry
            for name, entry in store.list_sessions(
                include_incognito=True,
                project_root_filter=child_entry.project_root,
            )
            if name == parent_name
        ]

        # Distinguish sibling Forge projects within the same logical repo by
        # preserving relative_path across worktree forks.
        child_relative_path = child_entry.relative_path or "."
        matching_relative_path = [entry for entry in siblings if (entry.relative_path or ".") == child_relative_path]
        if len(matching_relative_path) == 1:
            entry = matching_relative_path[0]
            return entry.forge_root or entry.worktree_path

        if len(siblings) == 1:
            # If there is only one same-name session left in the logical repo,
            # prefer it even when relative_path metadata doesn't line up exactly.
            entry = siblings[0]
            return entry.forge_root or entry.worktree_path

        return None
    except Exception as exc:
        _log.debug("Scoped parent forge_root lookup failed for %s: %s", parent_name, exc)
        return None


def _child_index_entry(store: Any, state: SessionState, current_forge_root: str) -> Any:
    """Best-effort lookup of the child's own session index entry."""
    scope = state.forge_root or current_forge_root
    try:
        return store.get_session(state.name, forge_root=scope)
    except Exception as exc:
        _log.debug("Child index lookup failed for %s: %s", state.name, exc)
        return None


def _plan_snapshots(artifacts: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract approved plan snapshots from the untyped artifacts dict."""
    raw = artifacts.get("plans")
    if not isinstance(raw, list):
        return []
    return [entry for entry in raw if isinstance(entry, dict) and entry.get("kind") == "approved"]
