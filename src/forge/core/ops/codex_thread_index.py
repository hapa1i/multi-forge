"""Codex thread-to-index synchronization."""

from __future__ import annotations

from forge.session.index import IndexStore


def sync_codex_thread_to_index(
    name: str,
    thread_id: str | None,
    forge_root: str,
    *,
    expected_instance_id: str,
    warnings: list[str],
) -> None:
    """Reconcile the index column when the turn produced a thread.

    Skips the no-thread case; see ``IndexStore.update_codex_thread`` for the
    drift, collision, and best-effort contract.
    """
    if thread_id:
        if not IndexStore().update_codex_thread(name, thread_id, forge_root, expected_instance_id=expected_instance_id):
            warnings.append(
                f"Could not publish Codex thread for session '{name}'; "
                "the captured instance is no longer writable or index synchronization failed."
            )
