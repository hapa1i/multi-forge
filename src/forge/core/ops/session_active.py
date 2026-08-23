"""Strict non-mutating reads of the runtime active-session registry."""

from __future__ import annotations

from dacite import DaciteError

from forge.core.state import FileLockTimeoutError
from forge.session.active import ActiveSessionEntry, ActiveSessionStore
from forge.session.store import SessionStore

from .session import ForgeOpError


def read_active_session_strict(store: SessionStore) -> ActiveSessionEntry | None:
    """Read one active entry without triggering the registry's repair policy."""
    active_store = ActiveSessionStore()
    try:
        return active_store.peek_session(store.session_name, forge_root=str(store.forge_root))
    except (OSError, ValueError, DaciteError, FileLockTimeoutError) as exc:
        raise ForgeOpError(
            f"could not inspect the active-session registry at {active_store.index_path} without modifying it; "
            "run 'forge session list' to repair runtime-only state, then retry"
        ) from exc
