"""Session index operations for ~/.forge/sessions/index.json.

Session names are project-scoped. The index dict uses compound keys
(``name|sha256(forge_root)[:12]``) so the same session name can exist
in different Forge projects. All external APIs accept display names
(``planner``) and resolve internally via the identity helpers.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from pathlib import Path

import dacite

from forge.core.paths import get_forge_home
from forge.core.state import (
    atomic_write_json,
    file_lock_for_target,
    iso_to_timestamp,
    now_iso,
    read_versioned_json_object,
)

from .exceptions import (
    IndexCorruptedError,
    IndexUnreadableError,
    InvalidSessionNameError,
    SessionExistsError,
    SessionNotFoundError,
)
from .identity import (
    make_scoped_key,
    resolve_key_best_effort,
    resolve_key_strict,
    session_name_from_key,
)
from .models import (
    INDEX_VERSION,
    SessionIndex,
    SessionIndexEntry,
    SessionState,
)
from .store import get_manifest_path
from .validation import validate_name

_log = logging.getLogger(__name__)

# Constants
INDEX_DIR = "sessions"
INDEX_FILENAME = "index.json"

CLI_LOCK_TIMEOUT_S = 5.0


def get_index_path() -> Path:
    """Get the full path to the session index file."""
    return get_forge_home() / INDEX_DIR / INDEX_FILENAME


class IndexStore:
    """Manage the global session index at ~/.forge/sessions/index.json.

    The index enables fast session listing without scanning all worktrees.
    It stores minimal metadata for each session, keyed by session name.

    Error handling:
    - Missing file: returns empty index (self-healing)
    - Corrupted file: raises IndexCorruptedError (don't hide data loss)
    """

    def __init__(self, index_path: Path | None = None) -> None:
        """Initialize the index store.

        Args:
            index_path: Override path for testing. Defaults to ~/.forge/sessions/index.json.
        """
        self._index_path = index_path or get_index_path()

    @property
    def index_path(self) -> Path:
        """Return the path to the index file."""
        return self._index_path

    def exists(self) -> bool:
        """Check if the index file exists."""
        return self._index_path.is_file()

    def read(self) -> SessionIndex:
        """Read the session index.

        Returns:
            SessionIndex: The index, or empty index if file doesn't exist.

        Raises:
            IndexCorruptedError: If file exists but cannot be parsed.
        """
        if not self.exists():
            return SessionIndex()

        data = read_versioned_json_object(
            self._index_path,
            version_key="version",
            expected_version=INDEX_VERSION,
            corrupted_error=IndexCorruptedError,
            unreadable_error=IndexUnreadableError,
        )
        self._validate_key_shape(data)

        # Deserialize using dacite
        try:
            index = dacite.from_dict(
                data_class=SessionIndex,
                data=data,
                config=dacite.Config(strict=True),
            )
        except (dacite.DaciteError, TypeError, KeyError) as e:
            raise IndexCorruptedError(str(self._index_path), f"deserialization error: {e}")

        return index

    def _validate_key_shape(self, data: dict[str, object]) -> None:
        """Reject pre-OSS v1 indexes that used bare session-name keys."""
        sessions = data.get("sessions")
        if not isinstance(sessions, dict):
            return

        for key, entry_data in sessions.items():
            if not isinstance(key, str):
                raise IndexCorruptedError(str(self._index_path), "session index keys must be strings")
            if not isinstance(entry_data, dict):
                continue

            root = entry_data.get("forge_root") or entry_data.get("worktree_path")
            if not isinstance(root, str) or not root:
                raise IndexCorruptedError(
                    str(self._index_path),
                    f"invalid session index entry for '{key}': missing forge_root/worktree_path",
                )

            display_name = session_name_from_key(key)
            expected_key = make_scoped_key(display_name, root)
            if key != expected_key:
                raise IndexCorruptedError(
                    str(self._index_path),
                    "unsupported pre-OSS session index shape: "
                    "expected scoped keys; delete ~/.forge/sessions/index.json and rerun Forge",
                )

    def write(self, index: SessionIndex) -> None:
        """Write the session index atomically.

        Args:
            index: The index to write.
        """
        data = asdict(index)
        atomic_write_json(self._index_path, data)

    def list_sessions(
        self,
        include_incognito: bool = True,
        *,
        project_root_filter: str | None = None,
        forge_root_filter: str | None = None,
    ) -> list[tuple[str, SessionIndexEntry]]:
        """List sessions sorted by last_accessed_at DESC, then name ASC.

        Also self-heals stale index entries: if an entry points to a missing worktree
        or missing manifest file, it is pruned.

        Args:
            include_incognito: Whether to include incognito sessions.
            project_root_filter: If set, only return entries matching this project_root.
            forge_root_filter: If set, only return entries matching this forge_root.

        Returns:
            List of (name, entry) tuples sorted deterministically.
        """

        with file_lock_for_target(target_path=self._index_path, timeout_s=CLI_LOCK_TIMEOUT_S):
            index = self.read()

        # Filesystem probes run without the lock to avoid timeout on slow I/O.
        # TOCTOU window: a concurrent writer could modify the index between the
        # read above and the prune below. The re-read at the prune step mitigates
        # this (double-check pattern). Worst case is a false-positive prune that
        # gets re-added on the next session start.
        stale: set[str] = set()  # scoped keys (dict keys)
        for key, entry in index.sessions.items():
            display_name = session_name_from_key(key)
            worktree = Path(entry.worktree_path)
            store_root = Path(entry.forge_root or entry.worktree_path)
            manifest_path = get_manifest_path(store_root, display_name)

            if not worktree.exists() or not manifest_path.is_file():
                stale.add(key)

        if stale:
            with file_lock_for_target(target_path=self._index_path, timeout_s=CLI_LOCK_TIMEOUT_S):
                latest = self.read()

                pruned_any = False
                for key in list(stale):
                    latest_entry = latest.sessions.get(key)
                    if latest_entry is None:
                        continue

                    display_name = session_name_from_key(key)
                    worktree = Path(latest_entry.worktree_path)
                    store_root = Path(latest_entry.forge_root or latest_entry.worktree_path)
                    manifest_path = get_manifest_path(store_root, display_name)
                    if not worktree.exists() or not manifest_path.is_file():
                        del latest.sessions[key]
                        pruned_any = True

                if pruned_any:
                    self.write(latest)

                index = latest

        sessions = [
            (session_name_from_key(key), entry)
            for key, entry in index.sessions.items()
            if include_incognito or not entry.is_incognito
        ]

        # Apply project identity filters (see design.md §3 "session list --scope")
        if project_root_filter is not None:
            sessions = [(n, e) for n, e in sessions if e.project_root == project_root_filter]
        if forge_root_filter is not None:
            sessions = [(n, e) for n, e in sessions if e.forge_root == forge_root_filter]

        # Sort by last_accessed_at DESC, then name ASC for determinism
        sessions.sort(key=lambda x: (-iso_to_timestamp(x[1].last_accessed_at), x[0]))
        return sessions

    def get_session(self, name: str, forge_root: str | None = None) -> SessionIndexEntry:
        """Get a session entry by name, optionally scoped to a forge_root.

        Args:
            name: Session display name.
            forge_root: If set, scope lookup to this project. If None, uses
                strict resolution (raises AmbiguousSessionError on duplicates).

        Returns:
            SessionIndexEntry for the session.

        Raises:
            InvalidSessionNameError: If name is invalid.
            SessionNotFoundError: If session not in index.
            AmbiguousSessionError: If forge_root is None and name exists in multiple projects.
        """
        validate_name(name)

        # Phase 1: read entry under lock.
        with file_lock_for_target(target_path=self._index_path, timeout_s=CLI_LOCK_TIMEOUT_S):
            index = self.read()

            key = resolve_key_strict(index.sessions, name, forge_root)
            if key is None:
                raise SessionNotFoundError(name)

            entry = index.sessions[key]

        # Phase 2: do filesystem checks without holding the index lock.
        store_root = Path(entry.forge_root or entry.worktree_path)
        manifest_path = get_manifest_path(store_root, name)
        if store_root.exists() and manifest_path.is_file():
            return entry

        # Phase 3: re-acquire lock and prune only if still stale.
        with file_lock_for_target(target_path=self._index_path, timeout_s=CLI_LOCK_TIMEOUT_S):
            latest = self.read()
            latest_key = resolve_key_strict(latest.sessions, name, forge_root)
            if latest_key is None:
                raise SessionNotFoundError(name)

            latest_entry = latest.sessions[latest_key]
            store_root = Path(latest_entry.forge_root or latest_entry.worktree_path)
            manifest_path = get_manifest_path(store_root, name)
            if not store_root.exists() or not manifest_path.is_file():
                del latest.sessions[latest_key]
                self.write(latest)
                raise SessionNotFoundError(name)

            return latest_entry

    def add_session(
        self,
        name: str,
        worktree_path: str,
        project_root: str,
        *,
        is_fork: bool = False,
        is_incognito: bool = False,
        parent_session: str | None = None,
        claude_session_id: str | None = None,
        forge_root: str | None = None,
        checkout_root: str | None = None,
        relative_path: str | None = None,
    ) -> SessionIndexEntry:
        """Add a new session to the index.

        Session names are project-scoped: the same name can exist in different
        forge_root projects. The dict key is a deterministic compound key.

        Args:
            name: Session display name (unique within this forge_root).
            worktree_path: Absolute path to worktree.
            project_root: Absolute path to main repository.
            is_fork: Whether this is a forked session.
            is_incognito: Whether this is an incognito session.
            parent_session: Parent session name if this is a fork.
            forge_root: Forge project root (where .forge/ lives).
            checkout_root: Git checkout root (--show-toplevel).
            relative_path: forge_root relative to checkout_root.

        Returns:
            The created SessionIndexEntry.

        Raises:
            InvalidSessionNameError: If name is invalid.
            SessionExistsError: If session already exists in this project.
        """
        validate_name(name)
        effective_forge_root = forge_root or worktree_path

        with file_lock_for_target(target_path=self._index_path, timeout_s=CLI_LOCK_TIMEOUT_S):
            index = self.read()

            scoped_key = make_scoped_key(name, effective_forge_root)
            if scoped_key in index.sessions:
                raise SessionExistsError(name)

            entry = SessionIndexEntry(
                worktree_path=worktree_path,
                project_root=project_root,
                last_accessed_at=now_iso(),
                is_fork=is_fork,
                is_incognito=is_incognito,
                parent_session=parent_session,
                claude_session_id=claude_session_id,
                forge_root=effective_forge_root,
                checkout_root=checkout_root or worktree_path,
                relative_path=relative_path or ".",
            )

            index.sessions[scoped_key] = entry
            self.write(index)
            return entry

    def update_session(
        self, name: str, last_accessed_at: str | None = None, forge_root: str | None = None
    ) -> SessionIndexEntry:
        """Update a session's last_accessed_at timestamp.

        Args:
            name: Session display name.
            last_accessed_at: New timestamp as ISO8601 string (defaults to now).
            forge_root: Scope to this project. Strict resolution when None.

        Returns:
            The updated SessionIndexEntry.

        Raises:
            InvalidSessionNameError: If name is invalid.
            SessionNotFoundError: If session not found.
        """
        validate_name(name)

        with file_lock_for_target(target_path=self._index_path, timeout_s=CLI_LOCK_TIMEOUT_S):
            index = self.read()

            key = resolve_key_strict(index.sessions, name, forge_root)
            if key is None:
                raise SessionNotFoundError(name)

            index.sessions[key].last_accessed_at = last_accessed_at or now_iso()
            self.write(index)
            return index.sessions[key]

    def update_uuid(self, name: str, claude_session_id: str, forge_root: str | None = None) -> None:
        """Update a session's claude_session_id in the index.

        Best-effort: silently no-ops if session not found (fail-open for hooks).
        Uses best-effort resolution when forge_root is None.
        """
        try:
            with file_lock_for_target(target_path=self._index_path, timeout_s=CLI_LOCK_TIMEOUT_S):
                index = self.read()
                key = resolve_key_best_effort(index.sessions, name, forge_root)
                if key is None:
                    return
                index.sessions[key].claude_session_id = claude_session_id
                self.write(index)
        except Exception as e:
            _log.debug("Index sync for '%s' failed (non-critical): %s", name, e)

    def remove_session(self, name: str, forge_root: str | None = None) -> bool:
        """Remove a session from the index.

        Args:
            name: Session display name.
            forge_root: Scope to this project. Strict resolution when None.

        Returns:
            True if removed, False if not found.

        Raises:
            InvalidSessionNameError: If name is invalid.
        """
        validate_name(name)

        with file_lock_for_target(target_path=self._index_path, timeout_s=CLI_LOCK_TIMEOUT_S):
            index = self.read()

            key = resolve_key_strict(index.sessions, name, forge_root)
            if key is None:
                return False

            del index.sessions[key]
            self.write(index)
            return True

    def session_exists(self, name: str, forge_root: str | None = None) -> bool:
        """Check if a session exists in the index.

        Args:
            name: Session display name.
            forge_root: Scope to this project. Strict resolution when None.

        Returns:
            True if session exists in index.

        Raises:
            AmbiguousSessionError: If forge_root is None and name exists in multiple projects.
        """
        try:
            validate_name(name)
        except InvalidSessionNameError:
            return False

        with file_lock_for_target(target_path=self._index_path, timeout_s=CLI_LOCK_TIMEOUT_S):
            index = self.read()
            return resolve_key_strict(index.sessions, name, forge_root) is not None

    def add_from_state(
        self,
        state: SessionState,
        project_root: str,
        *,
        checkout_root: str | None = None,
        forge_root: str | None = None,
        relative_path: str | None = None,
    ) -> SessionIndexEntry:
        """Add session to index from a session state.

        Convenience method that extracts relevant fields from state.
        Identity fields (forge_root, checkout_root, relative_path) are passed
        explicitly by the caller — they are computed from git and filesystem state
        that this method cannot derive from SessionState alone.

        Args:
            state: The session state.
            project_root: Absolute path to main repository.
            checkout_root: Git checkout root (--show-toplevel).
            forge_root: Forge project root (where .forge/ lives).
            relative_path: forge_root relative to checkout_root.

        Returns:
            The created SessionIndexEntry.
        """
        worktree_path = state.worktree.path if state.worktree else project_root
        # Use state.forge_root as fallback if caller didn't pass it
        effective_forge_root = forge_root or state.forge_root

        return self.add_session(
            name=state.name,
            worktree_path=worktree_path,
            project_root=project_root,
            is_fork=state.is_fork,
            is_incognito=state.is_incognito,
            parent_session=state.parent_session,
            claude_session_id=state.confirmed.claude_session_id,
            forge_root=effective_forge_root,
            checkout_root=checkout_root,
            relative_path=relative_path,
        )

    def find_session_by_uuid(
        self, session_uuid: str, *, timeout_s: float = CLI_LOCK_TIMEOUT_S
    ) -> tuple[str, str] | None:
        """Find a session by its Claude session UUID.

        Returns (display_name, forge_root) for exact subsequent lookups,
        or None if not found. Cross-project: scans all entries.

        Args:
            session_uuid: The Claude session UUID to search for.
            timeout_s: How long to wait for index lock acquisition.
        """
        with file_lock_for_target(target_path=self._index_path, timeout_s=timeout_s):
            index = self.read()

            for key, entry in index.sessions.items():
                if entry.claude_session_id == session_uuid:
                    return session_name_from_key(key), entry.forge_root or entry.worktree_path

            return None

    def sync_uuid_from_state(self, name: str, state: SessionState) -> SessionIndexEntry:
        """Sync UUID fields from session state to index entry (lazy reconciliation).

        Uses best-effort resolution: prefers state.forge_root for scoped lookup,
        falls back to unscoped scan.

        Args:
            name: Session display name.
            state: The session state with confirmed UUID info.

        Returns:
            The updated SessionIndexEntry.

        Raises:
            SessionNotFoundError: If session not found in index.
        """
        forge_root = state.forge_root

        with file_lock_for_target(target_path=self._index_path, timeout_s=CLI_LOCK_TIMEOUT_S):
            index = self.read()

            key = resolve_key_best_effort(index.sessions, name, forge_root)
            if key is None:
                raise SessionNotFoundError(name)

            entry = index.sessions[key]
            confirmed = state.confirmed

            if confirmed.claude_session_id is not None:
                entry.claude_session_id = confirmed.claude_session_id

            self.write(index)
            return entry
