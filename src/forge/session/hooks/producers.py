"""Capture the launch-bound owner before a managed hook reads or writes content."""

from __future__ import annotations

import os

from forge.session.index import IndexStore
from forge.session.store import SessionStore
from forge.session.workers import SESSION_INSTANCE_ENV, capture_session_instance


def capture_hook_instance(store: SessionStore, *, index_store: IndexStore | None = None) -> str:
    """Use the launched instance, or admit a legacy hook before its first state read."""
    launched = os.environ.get(SESSION_INSTANCE_ENV)
    if launched:
        return launched
    return capture_session_instance(store.forge_root, store.session_name, index_store=index_store)


def is_managed_hook() -> bool:
    """Distinguish a deleted managed launcher from an unrelated native conversation."""
    return any(os.environ.get(key) for key in ("FORGE_SESSION", "FORGE_FORK_NAME", SESSION_INSTANCE_ENV))
