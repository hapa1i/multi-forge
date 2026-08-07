"""Derived session launchability and checkout-required operation guards."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from .exceptions import SessionWorktreeMissingError

Launchability = Literal["launchable", "missing_worktree", "unknown"]


def derive_launchability(worktree_path: str | Path | None) -> Launchability:
    """Derive launchability from the recorded checkout without persisting a second truth."""
    if worktree_path is None:
        return "unknown"
    return "launchable" if Path(worktree_path).is_dir() else "missing_worktree"


def require_session_worktree(name: str, worktree_path: str | Path | None, *, action: str) -> Path:
    """Return an available recorded checkout or refuse an operation before mutation."""
    if worktree_path is None:
        # Legacy manifests can omit the worktree block and retain the established
        # current-directory fallback. D009 governs recorded paths that vanished.
        return Path.cwd()
    path = Path(worktree_path)
    if not path.is_dir():
        raise SessionWorktreeMissingError(name, str(path), action)
    return path
