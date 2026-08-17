"""Codex thread-to-index synchronization."""

from __future__ import annotations

from forge.session.index import IndexStore


def sync_codex_thread_to_index(name: str, thread_id: str | None, forge_root: str | None) -> None:
    """Reconcile the index column when the turn produced a thread.

    Skips the no-thread case; see ``IndexStore.update_codex_thread`` for the
    drift, collision, and best-effort contract.
    """
    if thread_id:
        IndexStore().update_codex_thread(name, thread_id, forge_root)
