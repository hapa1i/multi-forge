"""Workspace-wide session resolution.

Shared two-tier resolver used by session CLI commands and policy CLI.
Resolves a named session with current-project preference, falling back
to a workspace-scoped scan when the session lives in a sibling forge_root.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from forge.core.state.exceptions import StateCorruptedError
from forge.session import SessionIndexEntry, SessionManager, SessionState, SessionStore
from forge.session.exceptions import (
    AmbiguousSessionError,
    ForgeSessionError,
    SessionNotFoundError,
)

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResolvedSession:
    """Result of workspace-wide session resolution."""

    name: str
    entry: SessionIndexEntry
    store: SessionStore
    state: SessionState
    forge_root: str
    is_cross_project: bool


def resolve_session_repo_wide(
    name: str,
    cwd_forge_root: str | None,
    *,
    manager: SessionManager | None = None,
) -> ResolvedSession:
    """Resolve a named session with workspace-wide scope and current-project preference.

    Two-tier resolution (no global fast path to prevent cross-repo jumps):

    1. Tier 1: Try cwd_forge_root (O(1) compound-key index lookup).
    2. Tier 2: Workspace-scoped scan (project_root_filter) for cross-worktree matches.

    Tiebreaker: if multiple matches in the same repo, prefer cwd_forge_root.

    Raises:
        SessionNotFoundError: session not found anywhere in the repo.
        AmbiguousSessionError: multiple matches, none in cwd_forge_root.
    """
    if manager is None:
        manager = SessionManager()

    # Tier 1: same project (O(1) index lookup)
    if cwd_forge_root is not None:
        try:
            entry = manager.get_session_entry(name, forge_root=cwd_forge_root)
            store = SessionStore(entry.root, name)
            return ResolvedSession(
                name=name,
                entry=entry,
                store=store,
                state=store.read(),
                forge_root=entry.root,
                is_cross_project=False,
            )
        except StateCorruptedError:
            raise  # corrupt index/manifest -> top-level reset handler, not Tier 2 fallthrough
        except (ForgeSessionError, FileNotFoundError):
            pass

    # Tier 2: workspace-scoped scan (cross-worktree)
    project_root = _derive_project_root(cwd_forge_root, manager)
    if project_root is None:
        raise SessionNotFoundError(name)

    siblings = manager.list_sessions(project_root_filter=project_root)
    matches = [(n, e) for n, e in siblings if n == name]

    if not matches:
        raise SessionNotFoundError(name)

    if len(matches) == 1:
        e = matches[0][1]
        store = SessionStore(e.root, name)
        return ResolvedSession(
            name=name,
            entry=e,
            store=store,
            state=store.read(),
            forge_root=e.root,
            is_cross_project=e.root != cwd_forge_root,
        )

    # Multiple matches: prefer current forge_root as tiebreaker
    if cwd_forge_root is not None:
        for _, e in matches:
            if e.root == cwd_forge_root:
                store = SessionStore(e.root, name)
                return ResolvedSession(
                    name=name, entry=e, store=store, state=store.read(), forge_root=e.root, is_cross_project=False
                )

    roots = [e.root for _, e in matches]
    raise AmbiguousSessionError(name, roots)


def _derive_project_root(cwd_forge_root: str | None, manager: SessionManager) -> str | None:
    """Derive the logical repo root for Tier 2 scanning.

    Uses manager.resolve_project_root first (git subprocess), then falls
    back to ExecutionContext path walking (handles fake .git dirs in tests
    and directories that aren't real git worktrees).
    """
    if cwd_forge_root is not None:
        try:
            pr = manager.resolve_project_root(cwd_forge_root)
            # resolve_project_root falls back to returning the input path
            # when git fails. That's not useful for workspace-scoped filtering,
            # so fall through to CWD-based derivation.
            if pr != str(Path(cwd_forge_root).resolve()):
                return pr
        except Exception:
            pass

    try:
        from forge.core.ops.context import ExecutionContext

        ctx = ExecutionContext.from_cwd()
        return str(ctx.project_root)
    except Exception:
        _log.debug("Could not derive project_root from CWD or forge_root=%s", cwd_forge_root)
        return None
