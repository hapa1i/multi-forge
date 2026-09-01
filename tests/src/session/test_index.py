"""Tests for IndexStore."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import pytest

from forge.core.paths import FORGE_DIR, get_forge_home
from forge.core.state import now_iso
from forge.session.active import ACTIVE_FILENAME, ActiveSessionStore
from forge.session.config import LAUNCH_MODE_HOST
from forge.session.exceptions import (
    IndexCorruptedError,
    InvalidSessionNameError,
    SessionNotFoundError,
    UuidAlreadyBoundError,
)
from forge.session.identity import make_scoped_key
from forge.session.index import (
    INDEX_DIR,
    INDEX_FILENAME,
    IndexStore,
    get_index_path,
)
from forge.session.models import (
    INDEX_VERSION,
    SessionIndex,
    create_session_state,
)
from tests.fixtures.session_state import (
    publish_session,
    publish_session_from_fields,
    seed_row_only_session,
)


@pytest.fixture
def temp_forge_home(tmp_path: Path) -> Path:
    """Create a temporary ~/.forge directory."""
    forge_home = tmp_path / FORGE_DIR
    forge_home.mkdir()
    (forge_home / INDEX_DIR).mkdir()
    return forge_home


@pytest.fixture
def index_path(temp_forge_home: Path) -> Path:
    """Get the index path in the temp forge home."""
    return temp_forge_home / INDEX_DIR / INDEX_FILENAME


@pytest.fixture
def store(index_path: Path) -> IndexStore:
    """Create an IndexStore with temp path."""
    return IndexStore(index_path)


class TestHelperFunctions:
    """Test module helper functions."""

    def test_get_forge_home(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_forge_home should return ~/.forge when FORGE_HOME is unset."""
        monkeypatch.delenv("FORGE_HOME", raising=False)
        home = get_forge_home()
        assert home == Path.home() / FORGE_DIR

    def test_get_index_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_index_path should return ~/.forge/sessions/index.json when FORGE_HOME is unset."""
        monkeypatch.delenv("FORGE_HOME", raising=False)
        path = get_index_path()
        assert path == Path.home() / FORGE_DIR / INDEX_DIR / INDEX_FILENAME


class TestIndexStoreProperties:
    """Test IndexStore properties."""

    def test_index_path(self, store: IndexStore, index_path: Path) -> None:
        """index_path should return the configured path."""
        assert store.index_path == index_path

    def test_exists_false_initially(self, store: IndexStore) -> None:
        """exists() should return False when no index."""
        assert store.exists() is False


class TestIndexStoreRead:
    """Test IndexStore.read()."""

    def test_read_missing_returns_empty(self, store: IndexStore) -> None:
        """read() should return empty index when file missing."""
        index = store.read()
        assert index.version == INDEX_VERSION
        assert index.sessions == {}

    def test_read_valid_index(self, store: IndexStore, index_path: Path) -> None:
        """read() should parse valid v1 index with scoped keys."""
        from forge.session.identity import make_scoped_key

        scoped_key = make_scoped_key("test-session", "/path/to/worktree")
        data = {
            "version": INDEX_VERSION,
            "sessions": {
                scoped_key: {
                    "worktree_path": "/path/to/worktree",
                    "project_root": "/path/to/project",
                    "last_accessed_at": "2024-12-17T10:00:00",
                    "is_fork": False,
                    "is_incognito": False,
                    "parent_session": None,
                    "forge_root": "/path/to/worktree",
                    "checkout_root": "/path/to/worktree",
                    "relative_path": ".",
                }
            },
        }
        index_path.write_text(json.dumps(data))

        index = store.read()
        assert scoped_key in index.sessions
        entry = index.sessions[scoped_key]
        assert entry.worktree_path == "/path/to/worktree"
        assert entry.forge_root == "/path/to/worktree"

    def test_read_invalid_json(self, store: IndexStore, index_path: Path) -> None:
        """read() should raise IndexCorruptedError for invalid JSON."""
        index_path.write_text("not valid json {{{")

        with pytest.raises(IndexCorruptedError) as exc_info:
            store.read()
        assert "invalid JSON" in str(exc_info.value)

    def test_read_missing_version(self, store: IndexStore, index_path: Path) -> None:
        """read() should raise IndexCorruptedError for missing version."""
        data: dict[str, object] = {"sessions": {}}
        index_path.write_text(json.dumps(data))

        with pytest.raises(IndexCorruptedError) as exc_info:
            store.read()
        assert "missing version" in str(exc_info.value)

    def test_read_wrong_version(self, store: IndexStore, index_path: Path) -> None:
        """read() should raise IndexCorruptedError for wrong version."""
        data = {"version": 999, "sessions": {}}
        index_path.write_text(json.dumps(data))

        with pytest.raises(IndexCorruptedError) as exc_info:
            store.read()
        assert "incompatible version" in str(exc_info.value)


class TestIndexStoreWrite:
    """Test IndexStore.write()."""

    def test_write_creates_file(self, store: IndexStore) -> None:
        """write() should create the index file."""
        index = SessionIndex()
        store.write(index)
        assert store.exists() is True

    def test_write_valid_json(self, store: IndexStore, index_path: Path) -> None:
        """write() should produce valid JSON."""
        index = SessionIndex()
        store.write(index)

        with open(index_path) as f:
            data = json.load(f)
        assert data["version"] == INDEX_VERSION
        assert data["sessions"] == {}


class TestIndexStoreGetSession:
    """Test IndexStore.get_session()."""

    def test_get_session_existing(self, store: IndexStore) -> None:
        """get_session() should return existing session."""
        wt = Path(store.index_path).parent.parent / "wt_test_session"
        publish_session_from_fields(store, "test-session", wt, "/path")

        entry = store.get_session("test-session")
        assert entry.worktree_path == str(wt)

    def test_get_session_not_found(self, store: IndexStore) -> None:
        """get_session() should raise SessionNotFoundError for missing session."""
        with pytest.raises(SessionNotFoundError) as exc_info:
            store.get_session("nonexistent")
        assert "nonexistent" in str(exc_info.value)

    def test_get_session_invalid_name(self, store: IndexStore) -> None:
        """get_session() should validate session name."""
        with pytest.raises(InvalidSessionNameError):
            store.get_session("INVALID")


class TestIndexStoreListSessions:
    """Test IndexStore.list_sessions()."""

    def test_list_sessions_empty(self, store: IndexStore) -> None:
        """list_sessions() should return empty list when no sessions."""
        sessions = store.list_sessions()
        assert sessions == []

    def test_filtered_read_prunes_stale_incompatible_other_root_without_touching_live_pair(
        self,
        store: IndexStore,
        index_path: Path,
    ) -> None:
        """Global index repair is exempt, but it must not mutate project or active state."""
        compatible_root = index_path.parent.parent / "compatible-project"
        incompatible_root = index_path.parent.parent / "incompatible-project"
        compatible_root.mkdir()
        incompatible_root.mkdir()
        incompatible_state = incompatible_root / ".forge"
        incompatible_state.mkdir()
        pin = incompatible_state / "project.toml"
        pin.write_text('schema_version = 1\nrequired_forge = ">=9999"\n', encoding="utf-8")
        pin_before = pin.read_bytes()

        publish_session_from_fields(
            store,
            "visible",
            compatible_root,
            compatible_root,
            forge_root=str(compatible_root),
        )
        stale = create_session_state("stale-other-root", worktree_path=str(incompatible_root))
        # Deliberately seed crash residue so list_sessions must prune the row
        # without touching the incompatible project or active registry.
        seed_row_only_session(
            store,
            stale,
            incompatible_root,
            forge_root=str(incompatible_root),
        )
        active_store = ActiveSessionStore(index_path.parent / ACTIVE_FILENAME)
        active_store.upsert_session(
            "stale-other-root",
            worktree_path=str(incompatible_root),
            launch_mode=LAUNCH_MODE_HOST,
            launcher_pid=os.getpid(),
            forge_root=str(incompatible_root),
        )

        sessions = store.list_sessions(project_root_filter=str(compatible_root))

        assert [name for name, _entry in sessions] == ["visible"]
        assert make_scoped_key("stale-other-root", str(incompatible_root)) not in store.read().sessions
        assert active_store.get_session("stale-other-root", forge_root=str(incompatible_root)) is not None
        assert pin.read_bytes() == pin_before

    def test_peek_sessions_filters_stale_rows_without_pruning(self, store: IndexStore, index_path: Path) -> None:
        live_root = index_path.parent.parent / "live-project"
        stale_root = index_path.parent.parent / "stale-project"
        live_root.mkdir()
        stale_root.mkdir()
        publish_session_from_fields(store, "visible", live_root, live_root, forge_root=live_root)
        stale = create_session_state("stale", worktree_path=str(stale_root))
        # Deliberately model row-first publication residue: previews must ignore it
        # without taking ownership of the repair.
        seed_row_only_session(store, stale, stale_root, forge_root=stale_root)
        before = index_path.read_bytes()

        sessions = store.peek_sessions()

        assert [name for name, _entry in sessions] == ["visible"]
        assert index_path.read_bytes() == before

    def test_list_sessions_sorted_by_last_accessed(self, store: IndexStore) -> None:
        """list_sessions() should sort by last_accessed_at DESC."""
        # Add sessions with different timestamps
        wt1 = Path(store.index_path).parent.parent / "wt1"
        wt2 = Path(store.index_path).parent.parent / "wt2"
        wt3 = Path(store.index_path).parent.parent / "wt3"

        publish_session_from_fields(store, "old-session", wt1, "/path")
        store.update_session("old-session", "2024-12-17T10:00:00+00:00")

        publish_session_from_fields(store, "new-session", wt2, "/path")
        store.update_session("new-session", "2024-12-17T12:00:00+00:00")

        publish_session_from_fields(store, "mid-session", wt3, "/path")
        store.update_session("mid-session", "2024-12-17T11:00:00+00:00")

        sessions = store.list_sessions()
        names = [name for name, _ in sessions]

        # Most recent first
        assert names == ["new-session", "mid-session", "old-session"]

    def test_list_sessions_tiebreaker_by_name(self, store: IndexStore) -> None:
        """list_sessions() should use name as tiebreaker when timestamps equal."""
        timestamp = "2024-12-17T10:00:00+00:00"

        wt1 = Path(store.index_path).parent.parent / "wt_zebra"
        wt2 = Path(store.index_path).parent.parent / "wt_apple"
        wt3 = Path(store.index_path).parent.parent / "wt_banana"

        publish_session_from_fields(store, "zebra", wt1, "/path")
        store.update_session("zebra", timestamp)

        publish_session_from_fields(store, "apple", wt2, "/path")
        store.update_session("apple", timestamp)

        publish_session_from_fields(store, "banana", wt3, "/path")
        store.update_session("banana", timestamp)

        sessions = store.list_sessions()
        names = [name for name, _ in sessions]

        # Same timestamp, sorted alphabetically
        assert names == ["apple", "banana", "zebra"]

    def test_list_sessions_excludes_incognito(self, store: IndexStore) -> None:
        """list_sessions() can exclude incognito sessions."""
        wt1 = Path(store.index_path).parent.parent / "wt_normal"
        wt2 = Path(store.index_path).parent.parent / "wt_incognito"

        publish_session_from_fields(store, "normal", wt1, "/path")
        publish_session_from_fields(store, "incognito", wt2, "/path", is_incognito=True)

        all_sessions = store.list_sessions(include_incognito=True)
        assert len(all_sessions) == 2

        non_incognito = store.list_sessions(include_incognito=False)
        assert len(non_incognito) == 1
        assert non_incognito[0][0] == "normal"

    def test_list_sessions_keeps_worktree_session_with_manifest_under_forge_root(self, store: IndexStore) -> None:
        """Worktree sessions should self-heal against forge_root, not worktree_path."""
        forge_root = Path(store.index_path).parent.parent / "repo-root"
        worktree = Path(store.index_path).parent.parent / "repo-worktree"
        forge_root.mkdir(parents=True, exist_ok=True)
        worktree.mkdir(parents=True, exist_ok=True)

        publish_session_from_fields(
            store,
            "worktree-session",
            worktree,
            forge_root,
            forge_root=str(forge_root),
            checkout_root=str(worktree),
            relative_path=".",
        )

        sessions = store.list_sessions()
        assert [name for name, _ in sessions] == ["worktree-session"]


class TestIndexStoreUpdateSession:
    """Test IndexStore.update_session()."""

    def test_update_session_timestamp(self, store: IndexStore) -> None:
        """update_session() should update timestamp."""
        wt = Path(store.index_path).parent.parent / "wt_update_session"
        publish_session_from_fields(store, "test-session", wt, "/path")

        new_timestamp = "2024-12-17T15:00:00"
        entry = store.update_session("test-session", new_timestamp)

        assert entry.last_accessed_at == new_timestamp

        # Verify persisted
        loaded = store.get_session("test-session")
        assert loaded.last_accessed_at == new_timestamp

    def test_update_session_defaults_to_now(self, store: IndexStore) -> None:
        """update_session() should default to now() if no timestamp."""
        wt = Path(store.index_path).parent.parent / "wt_update_now"
        publish_session_from_fields(store, "test-session", wt, "/path")
        before = now_iso()

        entry = store.update_session("test-session")

        after = now_iso()
        assert before <= entry.last_accessed_at <= after

    def test_update_session_not_found(self, store: IndexStore) -> None:
        """update_session() should raise SessionNotFoundError for missing session."""
        with pytest.raises(SessionNotFoundError):
            store.update_session("nonexistent")


class TestIndexStoreSessionExists:
    """Test IndexStore.session_exists()."""

    def test_session_exists_true(self, store: IndexStore) -> None:
        """session_exists() should return True for existing session."""
        wt = Path(store.index_path).parent.parent / "wt_exists"
        publish_session_from_fields(store, "test-session", wt, "/path")
        assert store.session_exists("test-session") is True

    def test_session_exists_false(self, store: IndexStore) -> None:
        """session_exists() should return False for missing session."""
        assert store.session_exists("nonexistent") is False

    def test_session_exists_invalid_name(self, store: IndexStore) -> None:
        """session_exists() should return False for invalid name."""
        assert store.session_exists("INVALID") is False


class TestIndexStoreUuidFields:
    """Test UUID fields in SessionIndexEntry."""

    # Default proxy values for tests
    DEFAULT_PROXY_TEMPLATE = "test-family"
    DEFAULT_PROXY_URL = "http://localhost:8080"

    def test_new_entry_has_empty_uuid_fields(self, store: IndexStore) -> None:
        """New index entries should have empty UUID fields."""
        wt = Path(store.index_path).parent.parent / "wt_uuid_empty"
        publish_session_from_fields(store, "test-session", wt, "/path")
        entry = store.get_session("test-session")

        assert entry.claude_session_id is None

    def test_uuid_fields_roundtrip(self, store: IndexStore, index_path: Path) -> None:
        """UUID fields should serialize and deserialize correctly."""
        wt = Path(store.index_path).parent.parent / "wt_uuid_roundtrip"
        publish_session_from_fields(store, "test-session", wt, "/path", claude_session_id="abc-123")

        # Re-read and verify
        reloaded = store.get_session("test-session")
        assert reloaded.claude_session_id == "abc-123"

    def test_v2_index_rejected(self, store: IndexStore, index_path: Path) -> None:
        """v2 index is rejected (no migration in OSS release)."""
        old_index = {
            "version": 2,
            "sessions": {},
        }
        index_path.write_text(json.dumps(old_index))

        with pytest.raises(IndexCorruptedError) as exc_info:
            store.read()
        assert "incompatible version" in str(exc_info.value)


class TestIndexStoreFindByUuid:
    """Test IndexStore.find_session_by_uuid()."""

    def test_find_by_current_uuid(self, store: IndexStore) -> None:
        """find_session_by_uuid() should find session by current UUID."""
        wt = Path(store.index_path).parent.parent / "wt_find_current"
        publish_session_from_fields(store, "test-session", wt, "/path", claude_session_id="uuid-123")

        result = store.find_session_by_uuid("uuid-123")
        assert result is not None
        assert result[0] == "test-session"

    def test_find_by_uuid_not_found(self, store: IndexStore) -> None:
        """find_session_by_uuid() should return None if UUID not found."""
        wt = Path(store.index_path).parent.parent / "wt_find_none"
        publish_session_from_fields(store, "test-session", wt, "/path")

        result = store.find_session_by_uuid("nonexistent-uuid")
        assert result is None

    def test_find_by_uuid_multiple_sessions(self, store: IndexStore) -> None:
        """find_session_by_uuid() should find correct session among multiple."""
        wt1 = Path(store.index_path).parent.parent / "wt_multi_a"
        wt2 = Path(store.index_path).parent.parent / "wt_multi_b"
        wt3 = Path(store.index_path).parent.parent / "wt_multi_c"

        publish_session_from_fields(store, "session-a", wt1, "/path", claude_session_id="uuid-a")
        publish_session_from_fields(store, "session-b", wt2, "/path", claude_session_id="uuid-b")
        publish_session_from_fields(store, "session-c", wt3, "/path", claude_session_id="uuid-c")

        result_a = store.find_session_by_uuid("uuid-a")
        result_b = store.find_session_by_uuid("uuid-b")
        result_c = store.find_session_by_uuid("uuid-c")
        assert result_a is not None and result_a[0] == "session-a"
        assert result_b is not None and result_b[0] == "session-b"
        assert result_c is not None and result_c[0] == "session-c"

    def test_find_by_uuid_empty_index(self, store: IndexStore) -> None:
        """find_session_by_uuid() should return None for empty index."""
        result = store.find_session_by_uuid("any-uuid")
        assert result is None


class TestIndexStoreSyncUuidFromManifest:
    """Test IndexStore.sync_uuid_from_state()."""

    # Default proxy values for tests
    DEFAULT_PROXY_TEMPLATE = "test-family"
    DEFAULT_PROXY_URL = "http://localhost:8080"

    def test_sync_uuid_basic(self, store: IndexStore) -> None:
        """sync_uuid_from_state() should copy UUID field from manifest."""
        wt = Path(store.index_path).parent.parent / "wt_sync_basic"
        publish_session_from_fields(store, "test-session", wt, "/path")

        manifest = create_session_state(
            "test-session",
            proxy_template=self.DEFAULT_PROXY_TEMPLATE,
            proxy_base_url=self.DEFAULT_PROXY_URL,
        )
        manifest.confirmed.claude_session_id = "synced-uuid"

        entry = store.sync_uuid_from_state("test-session", manifest)

        assert entry.claude_session_id == "synced-uuid"

        # Verify persisted
        reloaded = store.get_session("test-session")
        assert reloaded.claude_session_id == "synced-uuid"

    def test_sync_uuid_skips_none(self, store: IndexStore) -> None:
        """sync_uuid_from_state() should not overwrite with None."""
        wt = Path(store.index_path).parent.parent / "wt_sync_skip"
        publish_session_from_fields(store, "test-session", wt, "/path", claude_session_id="existing-uuid")

        # Sync with manifest that has no confirmed info
        manifest = create_session_state(
            "test-session",
            proxy_template=self.DEFAULT_PROXY_TEMPLATE,
            proxy_base_url=self.DEFAULT_PROXY_URL,
        )
        # manifest.confirmed.claude_session_id is None by default

        entry = store.sync_uuid_from_state("test-session", manifest)

        # Should keep existing UUID
        assert entry.claude_session_id == "existing-uuid"

    def test_sync_uuid_session_not_found(self, store: IndexStore) -> None:
        """sync_uuid_from_state() should raise SessionNotFoundError."""
        manifest = create_session_state(
            "nonexistent",
            proxy_template=self.DEFAULT_PROXY_TEMPLATE,
            proxy_base_url=self.DEFAULT_PROXY_URL,
        )

        with pytest.raises(SessionNotFoundError):
            store.sync_uuid_from_state("nonexistent", manifest)


class TestProjectIdentityFields:
    """Tests for project identity field propagation."""

    DEFAULT_PROXY_TEMPLATE = "test-family"
    DEFAULT_PROXY_URL = "http://localhost:8080"

    def test_published_entry_stores_identity_fields(self, store: IndexStore, tmp_path: Path) -> None:
        """Published rows persist forge_root, checkout_root, and relative_path."""
        worktree = tmp_path / "checkout"
        worktree.mkdir()
        forge = worktree / "sub" / "project"
        forge.mkdir(parents=True)
        (forge / ".forge").mkdir()

        state = create_session_state("test-identity", worktree_path=str(worktree))
        state.forge_root = str(forge)
        entry = publish_session(
            store,
            state,
            tmp_path,
            forge_root=str(forge),
            checkout_root=str(worktree),
            relative_path="sub/project",
        )
        assert entry.forge_root == str(forge)
        assert entry.checkout_root == str(worktree)
        assert entry.relative_path == "sub/project"

        # Verify roundtrip via get_session (validates filesystem + index)
        loaded = store.get_session("test-identity")
        assert loaded.forge_root == str(forge)
        assert loaded.checkout_root == str(worktree)
        assert loaded.relative_path == "sub/project"

    def test_identity_fields_fall_back_to_worktree_path(self, store: IndexStore, tmp_path: Path) -> None:
        """Identity fields fall back to worktree_path when not provided."""
        worktree = tmp_path / "worktree"
        entry = publish_session_from_fields(
            store,
            "legacy-session",
            worktree,
            tmp_path,
        )
        assert entry.forge_root == str(worktree)
        assert entry.checkout_root == str(worktree)
        assert entry.relative_path == "."

    def test_publish_session_passes_identity_fields(self, store: IndexStore, tmp_path: Path) -> None:
        """Publishing passes caller-provided identity fields to the index."""
        worktree = tmp_path / "wt"
        worktree.mkdir()
        (worktree / ".forge").mkdir()

        state = create_session_state(
            "from-state",
            proxy_template=self.DEFAULT_PROXY_TEMPLATE,
            proxy_base_url=self.DEFAULT_PROXY_URL,
            worktree_path=str(worktree),
        )
        state.forge_root = str(worktree)

        entry = publish_session(
            store,
            state,
            str(tmp_path),
            checkout_root=str(worktree),
            forge_root=str(worktree),
            relative_path=".",
        )
        assert entry.forge_root == str(worktree)
        assert entry.checkout_root == str(worktree)
        assert entry.relative_path == "."

    def test_publish_session_falls_back_to_state_forge_root(self, store: IndexStore, tmp_path: Path) -> None:
        """Publishing uses state.forge_root when the caller omits forge_root."""
        worktree = tmp_path / "wt"
        worktree.mkdir()

        state = create_session_state(
            "fallback-test",
            proxy_template=self.DEFAULT_PROXY_TEMPLATE,
            proxy_base_url=self.DEFAULT_PROXY_URL,
            worktree_path=str(worktree),
        )
        state.forge_root = str(worktree)

        entry = publish_session(store, state, tmp_path)
        assert entry.forge_root == str(worktree)

    def test_read_v1_index_with_identity_fields(self, store: IndexStore, index_path: Path) -> None:
        """Reading a v1 index with identity fields works correctly."""
        from forge.session.identity import make_scoped_key

        scoped_key = make_scoped_key("my-session", "/project/path")
        data = {
            "version": 1,
            "sessions": {
                scoped_key: {
                    "worktree_path": "/project/path",
                    "project_root": "/project/repo",
                    "last_accessed_at": "2024-01-01T00:00:00",
                    "is_fork": False,
                    "is_incognito": False,
                    "parent_session": None,
                    "forge_root": "/project/path",
                    "checkout_root": "/project/path",
                    "relative_path": ".",
                }
            },
        }
        index_path.write_text(json.dumps(data))

        index = store.read()
        entry = index.sessions[scoped_key]
        assert entry.forge_root == "/project/path"
        assert entry.checkout_root == "/project/path"
        assert entry.relative_path == "."

    def test_read_pre_oss_v1_bare_keys_rejected(self, store: IndexStore, index_path: Path) -> None:
        """Pre-OSS v1 index shape is rejected instead of migrated."""
        data = {
            "version": 1,
            "sessions": {
                "old-session": {
                    "worktree_path": "/old/path",
                    "project_root": "/old/repo",
                    "last_accessed_at": "2024-01-01T00:00:00",
                    "forge_root": "/old/path",
                    "checkout_root": "/old/path",
                    "relative_path": ".",
                }
            },
        }
        index_path.write_text(json.dumps(data))

        with pytest.raises(IndexCorruptedError) as exc_info:
            store.read()
        assert "pre-OSS session index shape" in str(exc_info.value)

    def test_read_future_version_raises(self, store: IndexStore, index_path: Path) -> None:
        """Reading a future version raises IndexCorruptedError."""
        data = {"version": 2, "sessions": {}}
        index_path.write_text(json.dumps(data))

        with pytest.raises(IndexCorruptedError) as exc_info:
            store.read()
        assert "incompatible version" in str(exc_info.value)

    def test_read_rejects_extra_fields(self, store: IndexStore, index_path: Path) -> None:
        """Strict deserialization rejects unknown fields in index entries."""
        from forge.session.identity import make_scoped_key

        scoped_key = make_scoped_key("has-extra", "/path")
        data = {
            "version": 1,
            "sessions": {
                scoped_key: {
                    "worktree_path": "/path",
                    "project_root": "/repo",
                    "last_accessed_at": "2024-01-01T00:00:00",
                    "forge_root": "/path",
                    "checkout_root": "/path",
                    "relative_path": ".",
                    "unknown_future_field": "should cause error",
                }
            },
        }
        index_path.write_text(json.dumps(data))

        with pytest.raises(IndexCorruptedError) as exc_info:
            store.read()
        assert "deserialization error" in str(exc_info.value)


class TestProjectScopedNames:
    """Test same session name in different projects (project-scoped keys)."""

    def test_same_name_different_forge_root_coexist(self, store: IndexStore) -> None:
        """Two projects can have sessions named 'planner'."""
        wt_a = Path(store.index_path).parent.parent / "project-a"
        wt_b = Path(store.index_path).parent.parent / "project-b"

        publish_session_from_fields(store, "planner", wt_a, wt_a, forge_root=wt_a)
        publish_session_from_fields(store, "planner", wt_b, wt_b, forge_root=wt_b)

        # Both exist when scoped
        assert store.session_exists("planner", forge_root=str(wt_a))
        assert store.session_exists("planner", forge_root=str(wt_b))

    def test_get_session_scoped_returns_correct_entry(self, store: IndexStore) -> None:
        """Scoped get_session returns the correct project's entry."""
        wt_a = Path(store.index_path).parent.parent / "project-a"
        wt_b = Path(store.index_path).parent.parent / "project-b"

        publish_session_from_fields(store, "planner", wt_a, wt_a, forge_root=wt_a)
        publish_session_from_fields(store, "planner", wt_b, wt_b, forge_root=wt_b)

        entry_a = store.get_session("planner", forge_root=str(wt_a))
        entry_b = store.get_session("planner", forge_root=str(wt_b))

        assert entry_a.forge_root == str(wt_a)
        assert entry_b.forge_root == str(wt_b)

    def test_session_exists_scoped_isolates_projects(self, store: IndexStore) -> None:
        """Session in project A is invisible from project B's scope."""
        wt_a = Path(store.index_path).parent.parent / "project-a"
        wt_c = Path(store.index_path).parent.parent / "project-c"

        publish_session_from_fields(store, "planner", wt_a, wt_a, forge_root=wt_a)

        assert store.session_exists("planner", forge_root=str(wt_a))
        assert not store.session_exists("planner", forge_root=str(wt_c))

    def test_list_sessions_returns_display_names(self, store: IndexStore) -> None:
        """list_sessions returns display names, not scoped keys."""
        wt_a = Path(store.index_path).parent.parent / "project-a"

        publish_session_from_fields(store, "my-session", wt_a, wt_a, forge_root=wt_a)

        sessions = store.list_sessions()
        names = [n for n, _ in sessions]
        assert "my-session" in names
        assert not any("|" in n for n in names)

    def test_unscoped_ambiguous_raises(self, store: IndexStore) -> None:
        """Unscoped lookup of duplicate name raises AmbiguousSessionError."""
        from forge.session.exceptions import AmbiguousSessionError

        wt_a = Path(store.index_path).parent.parent / "project-a"
        wt_b = Path(store.index_path).parent.parent / "project-b"

        publish_session_from_fields(store, "planner", wt_a, wt_a, forge_root=wt_a)
        publish_session_from_fields(store, "planner", wt_b, wt_b, forge_root=wt_b)

        with pytest.raises(AmbiguousSessionError):
            store.get_session("planner")

    def test_find_by_uuid_returns_display_name_and_forge_root(self, store: IndexStore) -> None:
        """find_session_by_uuid returns (display_name, forge_root) tuple."""
        wt_a = Path(store.index_path).parent.parent / "project-a"

        publish_session_from_fields(
            store,
            "planner",
            wt_a,
            wt_a,
            forge_root=wt_a,
            claude_session_id="uuid-abc",
        )

        result = store.find_session_by_uuid("uuid-abc")
        assert result is not None
        assert result[0] == "planner"
        assert result[1] == str(wt_a)

    def test_scoping_uses_forge_root_not_worktree_path(self, store: IndexStore) -> None:
        """Scoping must use forge_root, not worktree_path.

        Nested projects and root-level worktree sessions have
        worktree_path != forge_root. If the index accidentally keyed by
        worktree_path, this test would fail.
        """
        base = Path(store.index_path).parent.parent
        # Nested project: forge_root is a subdirectory of the checkout
        checkout = base / "repo"
        forge_root_nested = checkout / "packages" / "app"

        publish_session_from_fields(
            store,
            "planner",
            checkout,
            checkout,
            forge_root=str(forge_root_nested),  # nested .forge/ location
        )

        # Lookup by forge_root succeeds
        assert store.session_exists("planner", forge_root=str(forge_root_nested))

        # Lookup by worktree_path (which differs) fails
        assert not store.session_exists("planner", forge_root=str(checkout))

    def test_duplicate_names_nested_vs_root(self, store: IndexStore) -> None:
        """Same name in a root project and a nested project coexist."""
        base = Path(store.index_path).parent.parent
        root_project = base / "root-repo"
        nested_forge = root_project / "packages" / "sub"

        publish_session_from_fields(
            store,
            "planner",
            root_project,
            root_project,
            forge_root=str(root_project),
        )
        publish_session_from_fields(
            store,
            "planner",
            root_project,
            root_project,
            forge_root=str(nested_forge),
        )

        root_entry = store.get_session("planner", forge_root=str(root_project))
        nested_entry = store.get_session("planner", forge_root=str(nested_forge))
        assert root_entry.forge_root == str(root_project)
        assert nested_entry.forge_root == str(nested_forge)
        # Both share the same worktree_path but are distinct sessions
        assert root_entry.worktree_path == nested_entry.worktree_path

    def test_session_exists_unscoped_ambiguous_raises(self, store: IndexStore) -> None:
        """session_exists() with forge_root=None raises on duplicates."""
        from forge.session.exceptions import AmbiguousSessionError

        wt_a = Path(store.index_path).parent.parent / "project-a"
        wt_b = Path(store.index_path).parent.parent / "project-b"

        publish_session_from_fields(store, "planner", wt_a, wt_a, forge_root=wt_a)
        publish_session_from_fields(store, "planner", wt_b, wt_b, forge_root=wt_b)

        with pytest.raises(AmbiguousSessionError):
            store.session_exists("planner")

    def test_update_session_unscoped_ambiguous_raises(self, store: IndexStore) -> None:
        """update_session() with forge_root=None raises on duplicates."""
        from forge.session.exceptions import AmbiguousSessionError

        wt_a = Path(store.index_path).parent.parent / "project-a"
        wt_b = Path(store.index_path).parent.parent / "project-b"

        publish_session_from_fields(store, "planner", wt_a, wt_a, forge_root=wt_a)
        publish_session_from_fields(store, "planner", wt_b, wt_b, forge_root=wt_b)

        with pytest.raises(AmbiguousSessionError):
            store.update_session("planner")


class TestCodexThreadColumn:
    """`codex_thread_id` is what the index write lock guards for Codex adoption."""

    _THREAD = "019f0b65-b51c-7683-99c7-bb48107f7b83"
    _DRIFTED = "019f0b65-b51c-7683-99c7-bb48107fffff"

    def test_uniqueness_is_enforced_for_threads_too(self, tmp_path: Path) -> None:
        store = IndexStore()
        publish_session_from_fields(store, "first", tmp_path, tmp_path, codex_thread_id=self._THREAD)

        with pytest.raises(UuidAlreadyBoundError) as caught:
            publish_session_from_fields(
                store,
                "second",
                tmp_path,
                tmp_path,
                codex_thread_id=self._THREAD,
                require_uuid_unbound=True,
            )

        assert caught.value.owner == "first"

    def test_drift_reconciliation_moves_the_guard_to_the_live_id(self, tmp_path: Path) -> None:
        """Codex can re-bind a thread across a resume; a stale column guards nothing."""
        store = IndexStore()
        publish_session_from_fields(store, "drifter", tmp_path, tmp_path, codex_thread_id=self._THREAD)

        store.update_codex_thread("drifter", self._DRIFTED, str(tmp_path))

        entry = next(iter(store.read().sessions.values()))
        assert entry.codex_thread_id == self._DRIFTED

        # The guard must now refuse the live id, not the abandoned one.
        with pytest.raises(UuidAlreadyBoundError):
            publish_session_from_fields(
                store,
                "adopter",
                tmp_path,
                tmp_path,
                codex_thread_id=self._DRIFTED,
                require_uuid_unbound=True,
            )
        publish_session_from_fields(
            store,
            "reuse-old",
            tmp_path,
            tmp_path,
            codex_thread_id=self._THREAD,
            require_uuid_unbound=True,
        )

    def test_reconciling_an_unknown_session_is_a_no_op(self, tmp_path: Path) -> None:
        """Best-effort by contract: drift already happened, so this must not raise."""
        IndexStore().update_codex_thread("never-added", self._DRIFTED, str(tmp_path))

    def test_drift_collision_is_logged_and_the_live_id_remains_guarded(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        store = IndexStore()
        publish_session_from_fields(store, "first", tmp_path, tmp_path, codex_thread_id=self._THREAD)
        publish_session_from_fields(store, "drifter", tmp_path, tmp_path, codex_thread_id=self._DRIFTED)
        first_key = make_scoped_key("first", str(tmp_path))
        drifter_key = make_scoped_key("drifter", str(tmp_path))
        first_before = store.read().sessions[first_key]

        with caplog.at_level(logging.WARNING, logger="forge.session.index"):
            store.update_codex_thread("drifter", self._THREAD, str(tmp_path))

        sessions = store.read().sessions
        assert sessions[first_key] == first_before
        assert sessions[drifter_key].codex_thread_id == self._THREAD
        assert any("which session 'first' already holds" in message for message in caplog.messages)
        with pytest.raises(UuidAlreadyBoundError):
            publish_session_from_fields(
                store,
                "adopter",
                tmp_path,
                tmp_path,
                codex_thread_id=self._THREAD,
                require_uuid_unbound=True,
            )
