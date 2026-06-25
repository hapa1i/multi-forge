"""Tests for the runtime active-session registry."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from forge.session.active import (
    ACTIVE_FILENAME,
    ACTIVE_INDEX_VERSION,
    ActiveSessionStore,
    get_active_index_path,
    track_active_session,
)
from forge.session.config import LAUNCH_MODE_HOST, LAUNCH_MODE_SIDECAR


@pytest.fixture
def temp_forge_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Provide an isolated FORGE_HOME."""
    forge_home = tmp_path / ".forge"
    monkeypatch.setenv("FORGE_HOME", str(forge_home))
    return forge_home


@pytest.fixture
def store(temp_forge_home: Path) -> ActiveSessionStore:
    """Create an active-session store at the temp path."""
    return ActiveSessionStore(temp_forge_home / "sessions" / ACTIVE_FILENAME)


class TestHelperFunctions:
    def test_get_active_index_path(self, temp_forge_home: Path) -> None:
        """Registry path should live under ~/.forge/sessions/active.json."""
        assert get_active_index_path() == temp_forge_home / "sessions" / ACTIVE_FILENAME


class TestActiveSessionStore:
    def test_upsert_and_get_session_roundtrip(self, store: ActiveSessionStore) -> None:
        """A live host session should round-trip through the registry."""
        store.upsert_session(
            "live-session",
            worktree_path="/tmp/project",
            launch_mode=LAUNCH_MODE_HOST,
            launcher_pid=os.getpid(),
            claude_session_id="uuid-123",
        )

        entry = store.get_session("live-session")

        assert entry is not None
        assert entry.worktree_path == "/tmp/project"
        assert entry.claude_session_id == "uuid-123"
        assert entry.launch_mode == LAUNCH_MODE_HOST

    def test_update_uuid(self, store: ActiveSessionStore) -> None:
        """SessionStart should be able to attach the final Claude UUID."""
        store.upsert_session(
            "uuid-update",
            worktree_path="/tmp/project",
            launch_mode=LAUNCH_MODE_HOST,
            launcher_pid=os.getpid(),
        )

        updated = store.update_uuid("uuid-update", "hook-uuid-456")

        assert updated is True
        entry = store.get_session("uuid-update")
        assert entry is not None
        assert entry.claude_session_id == "hook-uuid-456"

    def test_v2_registry_self_heals(self, store: ActiveSessionStore) -> None:
        """Incompatible version is discarded and recreated (runtime-only state)."""
        store.index_path.parent.mkdir(parents=True, exist_ok=True)
        store.index_path.write_text(json.dumps({"version": 2, "sessions": {"old": {}}}))

        result = store.read()
        assert result.sessions == {}
        assert result.version == ACTIVE_INDEX_VERSION

    def test_pre_oss_v1_bare_keys_are_discarded(self, store: ActiveSessionStore) -> None:
        """Old same-version active registry shape is reset because it is runtime-only."""
        store.index_path.parent.mkdir(parents=True, exist_ok=True)
        store.index_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "sessions": {
                        "old-session": {
                            "worktree_path": "/tmp/project",
                            "started_at": "2024-01-01T00:00:00",
                            "launch_mode": LAUNCH_MODE_HOST,
                            "launcher_pid": os.getpid(),
                            "forge_root": "/tmp/project",
                        }
                    },
                }
            )
        )

        index = store.read()

        assert index.sessions == {}
        assert json.loads(store.index_path.read_text()) == {"version": 1, "sessions": {}}

    def test_truncated_json_self_heals(self, store: ActiveSessionStore) -> None:
        """Unparseable JSON (e.g. crash mid-write) is discarded, not raised as corruption.

        Runtime-only state self-heals: a JSONDecodeError (subclass of ValueError) is
        caught and the registry is recreated empty, so it never reaches the durable
        corrupt-state handler.
        """
        store.index_path.parent.mkdir(parents=True, exist_ok=True)
        store.index_path.write_text('{"version": 1, "sessions": {"x"')  # truncated

        result = store.read()

        assert result.sessions == {}
        assert result.version == ACTIVE_INDEX_VERSION
        assert json.loads(store.index_path.read_text()) == {"version": 1, "sessions": {}}

    def test_get_session_prunes_stale_host_entry(
        self, store: ActiveSessionStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Dead launcher PIDs should be pruned automatically."""
        store.upsert_session(
            "stale-host",
            worktree_path="/tmp/project",
            launch_mode=LAUNCH_MODE_HOST,
            launcher_pid=424242,
        )
        monkeypatch.setattr("forge.session.active.is_pid_alive", lambda pid: False)

        entry = store.get_session("stale-host")

        assert entry is None
        assert store.read().sessions == {}

    def test_list_sessions_keeps_live_sidecar_when_container_running(
        self, store: ActiveSessionStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sidecar liveness should keep the entry even when the launcher PID is gone."""
        store.upsert_session(
            "live-sidecar",
            worktree_path="/tmp/project",
            launch_mode=LAUNCH_MODE_SIDECAR,
            launcher_pid=424242,
            container_name="forge-live-sidecar",
        )
        monkeypatch.setattr("forge.session.active.is_pid_alive", lambda pid: False)
        monkeypatch.setattr("forge.sidecar.docker.is_container_running", lambda name: True)

        sessions = dict(store.list_sessions())

        assert "live-sidecar" in sessions
        assert sessions["live-sidecar"].container_name == "forge-live-sidecar"

    def test_track_active_session_clears_on_exit(self, temp_forge_home: Path) -> None:
        """The launch wrapper should clean up the runtime entry on exit."""
        registry = ActiveSessionStore(temp_forge_home / "sessions" / ACTIVE_FILENAME)

        with track_active_session(
            session_name="tracked",
            worktree_path="/tmp/project",
            launch_mode=LAUNCH_MODE_HOST,
            claude_session_id="uuid-789",
            launcher_pid=os.getpid(),
        ):
            entry = registry.get_session("tracked")
            assert entry is not None
            assert entry.claude_session_id == "uuid-789"

        assert registry.get_session("tracked") is None
