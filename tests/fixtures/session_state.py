"""Invariant-preserving builders for durable session test state.

Ordinary tests should publish and delete sessions through the transaction wrappers
in this module. The row-only helpers exist solely for tests whose subject is a
deliberately incomplete durable state, such as crash residue or an orphan manifest.
"""

from __future__ import annotations

from pathlib import Path

from forge.core.state import file_lock_for_target, now_iso
from forge.session.exceptions import SessionExistsError
from forge.session.identity import make_scoped_key
from forge.session.index import CLI_LOCK_TIMEOUT_S, IndexStore
from forge.session.models import (
    CodexConfirmed,
    SessionIndexEntry,
    SessionState,
    create_session_state,
)
from forge.session.store import SessionStore


def publish_session(
    index_store: IndexStore,
    state: SessionState,
    project_root: str | Path,
    *,
    checkout_root: str | Path | None = None,
    forge_root: str | Path | None = None,
    relative_path: str | None = None,
    require_uuid_unbound: bool = False,
) -> SessionIndexEntry:
    """Publish one coherent row-plus-manifest fixture through the real transaction."""
    effective_forge_root = _coherent_forge_root(state, project_root, forge_root)
    store = SessionStore(effective_forge_root, state.name)
    return index_store.create_session_txn(
        state,
        str(project_root),
        checkout_root=str(checkout_root) if checkout_root is not None else None,
        forge_root=effective_forge_root,
        relative_path=relative_path,
        require_uuid_unbound=require_uuid_unbound,
        write_manifest=lambda: store.create_exclusive(state),
    )


def publish_session_from_fields(
    index_store: IndexStore,
    name: str,
    worktree_path: str | Path,
    project_root: str | Path,
    *,
    is_fork: bool = False,
    is_incognito: bool = False,
    parent_session: str | None = None,
    claude_session_id: str | None = None,
    codex_thread_id: str | None = None,
    forge_root: str | Path | None = None,
    checkout_root: str | Path | None = None,
    relative_path: str | None = None,
    require_uuid_unbound: bool = False,
) -> SessionIndexEntry:
    """Build minimal valid manifest state, then publish both durable halves."""
    state = create_session_state(
        name,
        parent_session=parent_session,
        is_fork=is_fork,
        is_incognito=is_incognito,
        worktree_path=str(worktree_path),
    )
    if forge_root is not None:
        state.forge_root = str(forge_root)
    state.confirmed.claude_session_id = claude_session_id
    if codex_thread_id is not None:
        state.confirmed.codex = CodexConfirmed(thread_id=codex_thread_id)
    return publish_session(
        index_store,
        state,
        project_root,
        checkout_root=checkout_root,
        forge_root=forge_root,
        relative_path=relative_path,
        require_uuid_unbound=require_uuid_unbound,
    )


def delete_published_session(index_store: IndexStore, name: str, forge_root: str | Path) -> bool:
    """Delete both durable halves through the real ownership-aware transaction."""
    root = str(forge_root)
    store = SessionStore(root, name)

    def delete_manifest() -> None:
        store.delete()

    return index_store.delete_session_txn(
        name,
        root,
        expect_manifest_absent=False,
        delete_manifest=delete_manifest,
    )


def seed_row_only_session(
    index_store: IndexStore,
    state: SessionState,
    project_root: str | Path,
    *,
    checkout_root: str | Path | None = None,
    forge_root: str | Path | None = None,
    relative_path: str | None = None,
    worktree_path: str | Path | None = None,
) -> SessionIndexEntry:
    """Write intentional row-only crash residue without manufacturing a manifest.

    Callers must explain why their scenario requires violating the published-session
    invariant. This helper still preserves scoped identity, row shape, and index
    locking so the fixture is invalid in only the dimension named by the test.
    """
    effective_forge_root = _coherent_forge_root(state, project_root, forge_root)
    indexed_worktree_path = str(worktree_path or (state.worktree.path if state.worktree else str(project_root)))
    entry = SessionIndexEntry(
        worktree_path=indexed_worktree_path,
        project_root=str(project_root),
        last_accessed_at=now_iso(),
        is_fork=state.is_fork,
        is_incognito=state.is_incognito,
        parent_session=state.parent_session,
        claude_session_id=state.confirmed.claude_session_id,
        codex_thread_id=state.confirmed.codex.thread_id if state.confirmed.codex else None,
        forge_root=effective_forge_root,
        checkout_root=str(checkout_root) if checkout_root is not None else indexed_worktree_path,
        relative_path=relative_path or ".",
    )
    key = make_scoped_key(state.name, effective_forge_root)
    with file_lock_for_target(target_path=index_store.index_path, timeout_s=CLI_LOCK_TIMEOUT_S):
        index = index_store.read()
        if key in index.sessions:
            raise SessionExistsError(state.name)
        index.sessions[key] = entry
        index_store.write(index)
    return entry


def remove_index_row_only(index_store: IndexStore, name: str, forge_root: str | Path) -> bool:
    """Remove only the named row to construct an intentional orphan manifest."""
    key = make_scoped_key(name, str(forge_root))
    with file_lock_for_target(target_path=index_store.index_path, timeout_s=CLI_LOCK_TIMEOUT_S):
        index = index_store.read()
        if key not in index.sessions:
            return False
        del index.sessions[key]
        index_store.write(index)
    return True


def _coherent_forge_root(
    state: SessionState,
    project_root: str | Path,
    forge_root: str | Path | None,
) -> str:
    worktree_path = state.worktree.path if state.worktree else str(project_root)
    effective = str(forge_root or state.forge_root or worktree_path)
    if state.forge_root is None:
        state.forge_root = effective
    elif Path(state.forge_root).resolve() != Path(effective).resolve():
        raise ValueError(f"manifest forge_root {state.forge_root!r} does not match indexed forge_root {effective!r}")
    return effective
