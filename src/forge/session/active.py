"""Runtime active-session registry for live Claude launches.

This registry is separate from session manifests and the global session index.
It stores ephemeral "session is currently launched" state so Forge can warn
before deleting a live session and self-heal stale entries after crashes.
"""

from __future__ import annotations

import json
import logging
import os
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Iterator

import dacite

from forge.core.paths import get_forge_home
from forge.core.process import is_pid_alive
from forge.core.state import atomic_write_json, file_lock_for_target, now_iso

from .config import LAUNCH_MODE_HOST, LAUNCH_MODE_SIDECAR

logger = logging.getLogger(__name__)

ACTIVE_INDEX_VERSION = 1
ACTIVE_DIR = "sessions"
ACTIVE_FILENAME = "active.json"
CLI_LOCK_TIMEOUT_S = 5.0


@dataclass
class ActiveSessionEntry:
    """Ephemeral runtime state for a currently launched session."""

    worktree_path: str
    started_at: str
    launch_mode: str = LAUNCH_MODE_HOST
    launcher_pid: int | None = None
    claude_session_id: str | None = None
    container_name: str | None = None
    forge_root: str | None = None  # Scope axis (matches durable index)


@dataclass
class ActiveSessionIndex:
    """All currently active sessions keyed by session name."""

    version: int = ACTIVE_INDEX_VERSION
    sessions: dict[str, ActiveSessionEntry] = field(default_factory=dict)


def get_active_index_path() -> Path:
    """Return the runtime active-session registry path."""
    return get_forge_home() / ACTIVE_DIR / ACTIVE_FILENAME


class ActiveSessionStore:
    """Manage the runtime active-session registry."""

    def __init__(self, index_path: Path | None = None) -> None:
        self._index_path = index_path or get_active_index_path()

    @property
    def index_path(self) -> Path:
        """Return the active-session registry path."""
        return self._index_path

    def exists(self) -> bool:
        """Return True when the registry file exists."""
        return self._index_path.is_file()

    def read(self) -> ActiveSessionIndex:
        """Read the registry, returning an empty registry when missing."""
        if not self.exists():
            return ActiveSessionIndex()

        with open(self._index_path, encoding="utf-8") as f:
            data = json.load(f)

        version = data.get("version")
        if version != ACTIVE_INDEX_VERSION:
            raise ValueError(
                f"unsupported active-session registry version: {version} "
                f"(expected {ACTIVE_INDEX_VERSION})"
            )

        if not self._has_current_key_shape(data):
            logger.info("Discarding pre-OSS active-session registry shape")
            empty = ActiveSessionIndex()
            self.write(empty)
            return empty

        return dacite.from_dict(
            data_class=ActiveSessionIndex,
            data=data,
            config=dacite.Config(strict=True),
        )

    def _has_current_key_shape(self, data: dict[str, object]) -> bool:
        """Return True when the registry uses scoped session keys."""
        from forge.session.identity import make_scoped_key, session_name_from_key

        sessions = data.get("sessions")
        if not isinstance(sessions, dict):
            return True

        for key, entry_data in sessions.items():
            if not isinstance(key, str) or not isinstance(entry_data, dict):
                return False
            root = entry_data.get("forge_root") or entry_data.get("worktree_path")
            if not isinstance(root, str) or not root:
                return False
            display_name = session_name_from_key(key)
            if key != make_scoped_key(display_name, root):
                return False
        return True

    def write(self, index: ActiveSessionIndex) -> None:
        """Write the registry atomically."""
        atomic_write_json(self._index_path, asdict(index))

    def upsert_session(
        self,
        session_name: str,
        *,
        worktree_path: str,
        launch_mode: str,
        launcher_pid: int | None = None,
        claude_session_id: str | None = None,
        container_name: str | None = None,
        forge_root: str | None = None,
    ) -> ActiveSessionEntry:
        """Create or replace a live-session entry."""
        from forge.session.identity import make_scoped_key

        launcher_pid = os.getpid() if launcher_pid is None else launcher_pid
        effective_forge_root = forge_root or worktree_path

        with file_lock_for_target(target_path=self._index_path, timeout_s=CLI_LOCK_TIMEOUT_S):
            index = self.read()
            entry = ActiveSessionEntry(
                worktree_path=worktree_path,
                started_at=now_iso(),
                launch_mode=launch_mode,
                launcher_pid=launcher_pid,
                claude_session_id=claude_session_id,
                container_name=container_name,
                forge_root=effective_forge_root,
            )
            key = make_scoped_key(session_name, effective_forge_root)
            index.sessions[key] = entry
            self.write(index)
            return entry

    def update_uuid(self, session_name: str, claude_session_id: str, forge_root: str | None = None) -> bool:
        """Update the Claude UUID for an active session if it exists.

        Best-effort: uses best-effort resolver when forge_root is None.
        """
        from forge.session.identity import resolve_key_best_effort

        with file_lock_for_target(target_path=self._index_path, timeout_s=CLI_LOCK_TIMEOUT_S):
            index = self.read()
            key = resolve_key_best_effort(index.sessions, session_name, forge_root)
            if key is None:
                return False
            index.sessions[key].claude_session_id = claude_session_id
            self.write(index)
            return True

    def clear_session(self, session_name: str, forge_root: str | None = None) -> bool:
        """Remove an active-session entry by session name.

        Uses strict resolution when forge_root is None.
        """
        from forge.session.identity import resolve_key_strict

        with file_lock_for_target(target_path=self._index_path, timeout_s=CLI_LOCK_TIMEOUT_S):
            index = self.read()
            key = resolve_key_strict(index.sessions, session_name, forge_root)
            if key is None:
                return False
            del index.sessions[key]
            self.write(index)
            return True

    def clear_by_claude_session_id(self, claude_session_id: str) -> bool:
        """Remove an active-session entry by Claude UUID (scans all)."""
        with file_lock_for_target(target_path=self._index_path, timeout_s=CLI_LOCK_TIMEOUT_S):
            index = self.read()
            removed = False
            for key, entry in list(index.sessions.items()):
                if entry.claude_session_id == claude_session_id:
                    del index.sessions[key]
                    removed = True
            if removed:
                self.write(index)
            return removed

    def get_session(self, session_name: str, forge_root: str | None = None) -> ActiveSessionEntry | None:
        """Return the live entry for a session, pruning stale entries.

        Uses strict resolution when forge_root is None.
        """
        from forge.session.identity import resolve_key_strict

        with file_lock_for_target(target_path=self._index_path, timeout_s=CLI_LOCK_TIMEOUT_S):
            index = self.read()
            key = resolve_key_strict(index.sessions, session_name, forge_root)

        if key is None:
            return None
        entry = index.sessions.get(key)
        if entry is None:
            return None
        if self._entry_is_live(entry):
            return entry

        with file_lock_for_target(target_path=self._index_path, timeout_s=CLI_LOCK_TIMEOUT_S):
            latest = self.read()
            latest_entry = latest.sessions.get(key)
            if latest_entry is None:
                return None
            if self._entry_is_live(latest_entry):
                return latest_entry
            del latest.sessions[key]
            self.write(latest)
            return None

    def list_sessions(self) -> list[tuple[str, ActiveSessionEntry]]:
        """List all live sessions, pruning stale entries on read.

        Returns display names (not compound keys).
        """
        from forge.session.identity import session_name_from_key

        with file_lock_for_target(target_path=self._index_path, timeout_s=CLI_LOCK_TIMEOUT_S):
            index = self.read()

        stale_keys = [key for key, entry in index.sessions.items() if not self._entry_is_live(entry)]
        if stale_keys:
            with file_lock_for_target(target_path=self._index_path, timeout_s=CLI_LOCK_TIMEOUT_S):
                latest = self.read()
                pruned_any = False
                for key in stale_keys:
                    entry = latest.sessions.get(key)
                    if entry is None:
                        continue
                    if not self._entry_is_live(entry):
                        del latest.sessions[key]
                        pruned_any = True
                if pruned_any:
                    self.write(latest)
                index = latest

        return sorted(
            [(session_name_from_key(k), e) for k, e in index.sessions.items()],
            key=lambda item: item[0],
        )

    def is_session_active(self, session_name: str, forge_root: str | None = None) -> bool:
        """Return True when the session still appears to be live.

        Uses strict resolution when forge_root is None.
        """
        return self.get_session(session_name, forge_root=forge_root) is not None

    def _entry_is_live(self, entry: ActiveSessionEntry) -> bool:
        """Return True when the runtime entry still points at a live launch."""
        if entry.launch_mode == LAUNCH_MODE_SIDECAR and entry.container_name:
            try:
                from forge.sidecar.docker import is_container_running

                if is_container_running(entry.container_name):
                    return True
            except Exception:
                logger.debug("Failed to probe sidecar container liveness", exc_info=True)

        if entry.launcher_pid is not None and is_pid_alive(entry.launcher_pid):
            return True

        return False


@contextmanager
def track_active_session(
    *,
    session_name: str,
    worktree_path: str,
    launch_mode: str,
    forge_root: str | None = None,
    claude_session_id: str | None = None,
    launcher_pid: int | None = None,
    container_name: str | None = None,
) -> Iterator[None]:
    """Track a live Claude launch for the duration of a context manager."""
    store = ActiveSessionStore()
    effective_forge_root = forge_root or worktree_path

    try:
        store.upsert_session(
            session_name,
            worktree_path=worktree_path,
            launch_mode=launch_mode,
            launcher_pid=launcher_pid,
            claude_session_id=claude_session_id,
            container_name=container_name,
            forge_root=effective_forge_root,
        )
    except Exception:
        logger.debug("Failed to register active session '%s'", session_name, exc_info=True)

    try:
        yield
    finally:
        try:
            store.clear_session(session_name, forge_root=effective_forge_root)
        except Exception:
            logger.debug("Failed to clear active session '%s'", session_name, exc_info=True)


def run_with_active_session(
    *,
    session_name: str,
    worktree_path: Path,
    launch_mode: str,
    forge_root: str | None = None,
    claude_session_id: str | None = None,
    runner: Callable[[], int],
) -> int:
    """Track a live session while invoking a Claude launcher callback."""
    container_name = f"forge-{session_name}" if launch_mode == LAUNCH_MODE_SIDECAR else None

    with track_active_session(
        session_name=session_name,
        worktree_path=str(worktree_path),
        launch_mode=launch_mode,
        forge_root=forge_root,
        claude_session_id=claude_session_id,
        container_name=container_name,
    ):
        return runner()
