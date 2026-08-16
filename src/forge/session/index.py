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
from typing import Callable

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
    UuidAlreadyBoundError,
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

        Also self-heals stale index entries when their authoritative manifest is
        absent. A missing worktree degrades launchability but does not end the
        durable session reservation.

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
            store_root = Path(entry.forge_root or entry.worktree_path)
            manifest_path = get_manifest_path(store_root, display_name)

            if not manifest_path.is_file():
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
                    store_root = Path(latest_entry.forge_root or latest_entry.worktree_path)
                    manifest_path = get_manifest_path(store_root, display_name)
                    if not manifest_path.is_file():
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

    def create_session_txn(
        self,
        state: SessionState,
        project_root: str,
        *,
        checkout_root: str | None = None,
        forge_root: str | None = None,
        relative_path: str | None = None,
        require_uuid_unbound: bool = False,
        write_manifest: Callable[[], None],
    ) -> SessionIndexEntry:
        """Publish a session's index row and manifest under one index-lock acquisition.

        The creation transaction for every path that mints a session. Writes the
        **row first**, then calls ``write_manifest`` while still holding the lock,
        so a process killed mid-creation leaves at most a bare row -- which is
        prunable -- instead of a manifest with no row, which is not (nothing lists
        it, yet it still owns its name and its conversation binding).

        Lock order is **index -> manifest**, never the reverse. ``write_manifest``
        takes the per-session manifest lock, so any caller holding a manifest lock
        while reaching this method would deadlock. Do no work but the manifest
        write inside the callback: this is the global index lock, shared by every
        session-creating command in every project.

        ``file_lock_for_target`` is not reentrant (``flock`` scopes locks to the
        open file description, and each acquisition opens a fresh fd), so neither
        the callback nor the compensation path may call a locking ``IndexStore``
        method. Compensation drops the row in memory and rewrites the index.

        Args:
            state: Session state to publish. Supplies the name and conversation ids.
            project_root: Absolute path to the main repository.
            checkout_root: Git checkout root (``--show-toplevel``).
            forge_root: Forge project root; falls back to ``state.forge_root``.
            relative_path: forge_root relative to checkout_root.
            require_uuid_unbound: Re-check conversation uniqueness inside this
                publication lock so concurrent adopts cannot both bind it.
            write_manifest: Callable that writes the manifest. Runs after the row
                is durable; its exception propagates unchanged after compensation.

        Returns:
            The published SessionIndexEntry.

        Raises:
            InvalidSessionNameError: If the session name is invalid.
            SessionExistsError: If a live session already holds this name.
            UuidAlreadyBoundError: If require_uuid_unbound and the conversation is taken.
        """
        name = state.name
        validate_name(name)

        worktree_path = state.worktree.path if state.worktree else project_root
        # Caller-provided root wins, then the manifest's root, then the worktree.
        effective_forge_root = forge_root or state.forge_root or worktree_path
        codex_thread_id = state.confirmed.codex.thread_id if state.confirmed.codex else None

        with file_lock_for_target(target_path=self._index_path, timeout_s=CLI_LOCK_TIMEOUT_S):
            index = self.read()
            scoped_key = make_scoped_key(name, effective_forge_root)

            existing = index.sessions.get(scoped_key)
            if existing is not None:
                if self._manifest_exists_for_row(scoped_key, existing):
                    raise SessionExistsError(name)
                # Row without a manifest. Two things produce it: a killed
                # transaction, and a delete that has removed the manifest -- or the
                # worktree holding it -- but has not yet removed its row. Reclaiming
                # the name is right for both: the residue reserves nothing, and the
                # session being deleted is on its way out. What makes it safe is not
                # an assumption that only crashes get here, but that the delete side
                # ends in delete_session_txn, which declines once a replacement owns
                # the name and so cannot take this one with it.
                # Deliberately narrower than the list_sessions prune, which also
                # drops rows whose worktree vanished: the manifest is the durable
                # reservation, so a live manifest must still collide here.
                del index.sessions[scoped_key]

            if require_uuid_unbound:
                # After the prune above, so residue never blocks rebinding its own
                # conversation.
                self._require_conversation_unbound(
                    index,
                    claude_session_id=state.confirmed.claude_session_id,
                    codex_thread_id=codex_thread_id,
                )

            entry = self._build_entry(
                worktree_path=worktree_path,
                project_root=project_root,
                is_fork=state.is_fork,
                is_incognito=state.is_incognito,
                parent_session=state.parent_session,
                claude_session_id=state.confirmed.claude_session_id,
                codex_thread_id=codex_thread_id,
                forge_root=effective_forge_root,
                checkout_root=checkout_root,
                relative_path=relative_path,
            )

            # Sampled before the callback, because "a manifest is there" is not the
            # same fact as "this transaction put it there". A pre-existing orphan
            # owns the path in exactly the case create_exclusive rejects, and
            # reading that as ours would leave our row indexing somebody else's
            # session.
            manifest_path = get_manifest_path(Path(effective_forge_root), name)
            manifest_existed_before = manifest_path.is_file()

            index.sessions[scoped_key] = entry
            self.write(index)

            try:
                write_manifest()
            except BaseException:
                # A raised callback does not prove the manifest is absent either:
                # once atomic_write_json reaches os.replace it is durable, and a
                # signal arriving after that -- during the directory fsync, or the
                # manifest lock release -- still unwinds through here. Keep the row
                # only when both halves prove this transaction published: nothing
                # was there before, and something is there now.
                published = not manifest_existed_before and manifest_path.is_file()
                if not published:
                    self._compensate_locked(index, scoped_key)
                raise

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

    def update_codex_thread(self, name: str, thread_id: str, forge_root: str | None = None) -> None:
        """Reconcile a session's ``codex_thread_id`` after the manifest changed.

        Codex can re-bind a thread across a resume ("drift"). The manifest records
        the live id, and this keeps the index column pointing at the same thing --
        otherwise the publication transaction's uniqueness check guards an id the
        session no longer uses, and adoption could publish a second binding for the live one.

        Best-effort, like ``update_uuid``: drift is already a fait accompli by the
        time this runs, so failing here must not break the resume that observed it.
        A collision is logged rather than raised for the same reason; the adoption
        guard still refuses the id, which is the outcome that matters.
        """
        try:
            with file_lock_for_target(target_path=self._index_path, timeout_s=CLI_LOCK_TIMEOUT_S):
                index = self.read()
                key = resolve_key_best_effort(index.sessions, name, forge_root)
                if key is None:
                    return
                for other_key, other in index.sessions.items():
                    if other_key != key and other.codex_thread_id == thread_id:
                        _log.warning(
                            "Codex thread '%s' drifted onto session '%s', which session '%s' already holds",
                            thread_id,
                            name,
                            session_name_from_key(other_key),
                        )
                index.sessions[key].codex_thread_id = thread_id
                self.write(index)
        except Exception as e:
            _log.debug("Codex index sync for '%s' failed (non-critical): %s", name, e)

    def delete_session_txn(
        self,
        name: str,
        forge_root: str | None = None,
        *,
        expect_manifest_absent: bool,
        delete_manifest: Callable[[], None],
    ) -> bool:
        """Remove a session's row and manifest under one index-lock acquisition.

        The deletion counterpart to ``create_session_txn``, and it exists for the
        same reason: the two removals must not be separable by a concurrent
        creator. Deletion drops the manifest -- or the worktree containing it --
        long before it reaches here, so for the whole cleanup the name reads as
        crash residue to ``create_session_txn``, which prunes the row and publishes
        a replacement. Verifying ownership and then deleting outside the lock would
        let a replacement land in between and lose its manifest.

        ``expect_manifest_absent`` must be a fact about what the caller *did*, not
        a probe of what it *sees*: a probe taken after the window opened may
        already be looking at the replacement's manifest and mistake it for the
        caller's own. Timestamps cannot substitute -- ``now_iso`` has second
        granularity, so a replacement created in the same second is
        indistinguishable by ``created_at``.

        **Known residual: a second concurrent delete of the same name.** False
        disables the ownership check entirely, which is right for a delete whose
        manifest is still its own -- it never opened a window, so no creator could
        have reclaimed the name. It is wrong when *another* delete of the same name
        opened one: the second deleter sampled its flag while the manifest was
        still present, so it arrives with False and removes a replacement's row and
        manifest. Closing this needs a per-session identity the deleter can carry
        into the lock and compare, which the row does not have today -- see
        ``docs/board/proposed/session_delete_generation_token``. Reaching it takes
        two concurrent deletes of one name plus a recreate landing between them.

        Args:
            name: Session display name.
            forge_root: Scope to this project. Strict resolution when None.
            expect_manifest_absent: True when this delete has already destroyed the
                manifest, or there never was one -- so a manifest present now can
                only belong to a creator that reclaimed the name.
            delete_manifest: Removes the manifest under its own lock. Runs inside
                the index lock, before the row is removed, so a manifest-lock
                failure leaves the complete session published rather than
                producing an orphan manifest. Keep it to the bounded session
                directory -- manifest, its lock, and up to three Codex handoff
                files. Transcripts (``.forge/artifacts/``), the search index, and
                the worktree all live outside it and must stay outside. A
                ``SessionStore.delete`` callback may wait up to
                ``CLI_LOCK_TIMEOUT_S`` for a live manifest lock while this global
                index lock remains held; that matches creation's lock order and
                prefers completing a user-requested delete over a shorter
                contention failure.

        Returns:
            True if the caller still owned the name; the row and manifest are gone.
            False if a replacement owns it, in which case nothing was removed.
        """
        validate_name(name)

        with file_lock_for_target(target_path=self._index_path, timeout_s=CLI_LOCK_TIMEOUT_S):
            index = self.read()

            key = resolve_key_strict(index.sessions, name, forge_root)
            if key is not None:
                if expect_manifest_absent and self._manifest_exists_for_row(key, index.sessions[key]):
                    return False

            # The held index lock excludes a replacement that is only partway
            # through publication. Under the single-deleter contract above, a
            # surviving row is still the caller's: either its manifest never went
            # absent, or the guard ruled out a completed replacement. Without a
            # row, row-first publication means no replacement can own the path;
            # anything left is caller-owned residue or a pre-existing orphan that
            # this transaction is entitled to clear.

            delete_manifest()
            if key is not None:
                # Manifest first: its deletion takes the manifest lock and can
                # time out. Until it succeeds, keep the row so a failed delete does
                # not manufacture the manifest-only orphan this transaction exists
                # to prevent. A failure after the manifest disappears leaves only a
                # prunable row, the safe residue direction.
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

    def live_session_exists(self, name: str, forge_root: str | None = None) -> bool:
        """Check whether a session has **both** an index row and its manifest.

        The name-collision pre-check for creation paths. ``session_exists`` answers
        the row question alone, which since row-first creation includes residue
        from a killed transaction -- a name that ``create_session_txn`` will prune
        and reuse. Rejecting on that would refuse a direct retry of a session the
        user never got.

        Callers use this only to fail fast before expensive setup (worktree
        creation). It is not authoritative: the answer can go stale the moment the
        lock is released, and ``create_session_txn`` re-decides under its own lock.

        Args:
            name: Session display name.
            forge_root: Scope to this project. Strict resolution when None.

        Returns:
            True only if a row exists and its manifest is on disk.

        Raises:
            AmbiguousSessionError: If forge_root is None and name exists in multiple projects.
        """
        try:
            validate_name(name)
        except InvalidSessionNameError:
            return False

        # One stat, unlike list_sessions' probe over every row -- cheap enough to
        # keep inside the lock, which keeps row and manifest a consistent pair.
        with file_lock_for_target(target_path=self._index_path, timeout_s=CLI_LOCK_TIMEOUT_S):
            index = self.read()
            key = resolve_key_strict(index.sessions, name, forge_root)
            if key is None:
                return False
            return self._manifest_exists_for_row(key, index.sessions[key])

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

    def _manifest_exists_for_row(self, scoped_key: str, entry: SessionIndexEntry) -> bool:
        """Whether the manifest backing an index row is on disk."""
        store_root = Path(entry.forge_root or entry.worktree_path)
        return get_manifest_path(store_root, session_name_from_key(scoped_key)).is_file()

    def _compensate_locked(self, index: SessionIndex, scoped_key: str) -> None:
        """Drop a transaction's own row, inside the lock it already holds.

        Never raises. The caller is unwinding the manifest callback's exception and
        has promised to re-raise it unchanged, so a failure here must not replace
        it -- the row it could not remove is prunable, and every reader self-heals
        it. Cannot call another index-locking method: ``file_lock_for_target`` is
        not reentrant, so re-entering it would deadlock against this transaction.
        """
        index.sessions.pop(scoped_key, None)
        try:
            self.write(index)
        except BaseException as e:
            # BaseException, to keep the never-raises guarantee literally true. It
            # costs a Ctrl-C landing in this narrow window, which is the right
            # trade: the caller's exception still propagates and unwinds, whereas
            # replacing it would lose the reason creation failed.
            _log.warning(
                "Could not remove the index row for '%s' after its manifest write failed; "
                "a stale row remains and will be pruned on the next read: %s",
                session_name_from_key(scoped_key),
                e,
            )

    def _require_conversation_unbound(
        self,
        index: SessionIndex,
        *,
        claude_session_id: str | None,
        codex_thread_id: str | None,
    ) -> None:
        """Raise if either conversation id is already held by a row. Caller holds the lock."""
        for existing_key, existing in index.sessions.items():
            for wanted, held in (
                (claude_session_id, existing.claude_session_id),
                (codex_thread_id, existing.codex_thread_id),
            ):
                if wanted and held == wanted:
                    raise UuidAlreadyBoundError(wanted, session_name_from_key(existing_key))

    @staticmethod
    def _build_entry(
        *,
        worktree_path: str,
        project_root: str,
        is_fork: bool,
        is_incognito: bool,
        parent_session: str | None,
        claude_session_id: str | None,
        codex_thread_id: str | None,
        forge_root: str,
        checkout_root: str | None,
        relative_path: str | None,
    ) -> SessionIndexEntry:
        """Build a row, owning the identity fallbacks shared by both creation paths."""
        return SessionIndexEntry(
            worktree_path=worktree_path,
            project_root=project_root,
            last_accessed_at=now_iso(),
            is_fork=is_fork,
            is_incognito=is_incognito,
            parent_session=parent_session,
            claude_session_id=claude_session_id,
            codex_thread_id=codex_thread_id,
            forge_root=forge_root,
            checkout_root=checkout_root or worktree_path,
            relative_path=relative_path or ".",
        )
