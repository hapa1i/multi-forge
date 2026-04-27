"""Session identity helpers for project-scoped session names.

The session index and active-session registry use compound keys to allow
the same session name in different projects. The key format is:

    {name}|{sha256(forge_root)[:12]}

Both IndexStore and ActiveSessionStore share these helpers to avoid
duplicating compound-key logic.
"""

from __future__ import annotations

import hashlib
from typing import Any, Mapping

from forge.session.exceptions import AmbiguousSessionError

_KEY_SEP = "|"
_HASH_LEN = 12


def session_name_from_key(key: str) -> str:
    """Extract the display name from a compound index key.

    ``planner|a1b2c3d4e5f6`` -> ``planner``
    """
    return key.split(_KEY_SEP, 1)[0]


def make_scoped_key(name: str, forge_root: str) -> str:
    """Build a deterministic compound key for a (name, forge_root) pair."""
    h = hashlib.sha256(forge_root.encode()).hexdigest()[:_HASH_LEN]
    return f"{name}{_KEY_SEP}{h}"


def resolve_key_strict(
    sessions: Mapping[str, Any],
    name: str,
    forge_root: str | None,
) -> str | None:
    """Resolve a session key for user-facing commands.

    When ``forge_root`` is provided, returns the deterministic scoped key
    if it exists (O(1)). When ``forge_root`` is None, scans for any matching
    prefix and raises ``AmbiguousSessionError`` if multiple matches exist.
    """
    if forge_root is not None:
        key = make_scoped_key(name, forge_root)
        return key if key in sessions else None

    prefix = f"{name}{_KEY_SEP}"
    matches = [k for k in sessions if k.startswith(prefix)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        roots = []
        for k in matches:
            entry = sessions[k]
            root = getattr(entry, "forge_root", None) or getattr(entry, "worktree_path", "?")
            roots.append(str(root))
        raise AmbiguousSessionError(name, roots)
    return None


def resolve_key_best_effort(
    sessions: Mapping[str, Any],
    name: str,
    forge_root: str | None,
) -> str | None:
    """Resolve a session key for hooks and cleanup paths (fail-open).

    When ``forge_root`` is provided, O(1) lookup. When None, returns the
    first prefix match without raising on ambiguity.
    """
    if forge_root is not None:
        key = make_scoped_key(name, forge_root)
        return key if key in sessions else None

    prefix = f"{name}{_KEY_SEP}"
    for k in sessions:
        if k.startswith(prefix):
            return k
    return None
