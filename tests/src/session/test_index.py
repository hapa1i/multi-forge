"""Tests for IndexStore."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from forge.core.paths import FORGE_DIR, get_forge_home
from forge.core.state import now_iso
from forge.session.exceptions import (
    IndexCorruptedError,
    InvalidSessionNameError,
    SessionExistsError,
    SessionNotFoundError,
)
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
from forge.session.store import get_manifest_path


def _create_manifest_stub(worktree: Path, session_name: str) -> None:
    """Create a minimal manifest file at the per-session path."""
    manifest_path = get_manifest_path(worktree, session_name)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text("{}")


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
        assert "unsupported version" in str(exc_info.value)


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


class TestIndexStoreAddSession:
    """Test IndexStore.add_session()."""

    def test_add_session_basic(self, store: IndexStore) -> None:
        """add_session() should add a new session."""
        wt = Path(store.index_path).parent.parent / "wt_add_basic"
        _create_manifest_stub(wt, "test-session")

        entry = store.add_session(
            name="test-session",
            worktree_path=str(wt),
            project_root="/path/to/project",
        )

        assert entry.worktree_path == str(wt)
        assert entry.project_root == "/path/to/project"
        assert entry.is_fork is False
        assert entry.is_incognito is False

        # Verify persisted (scoped key, not bare name)
        assert store.session_exists("test-session")

    def test_add_session_with_flags(self, store: IndexStore) -> None:
        """add_session() should support fork/incognito flags."""
        wt = Path(store.index_path).parent.parent / "wt_flags"
        _create_manifest_stub(wt, "fork-session")

        entry = store.add_session(
            name="fork-session",
            worktree_path=str(wt),
            project_root="/path",
            is_fork=True,
            is_incognito=True,
            parent_session="parent",
        )

        assert entry.is_fork is True
        assert entry.is_incognito is True
        assert entry.parent_session == "parent"

    def test_add_session_duplicate(self, store: IndexStore) -> None:
        """add_session() should raise SessionExistsError for duplicates."""
        wt = Path(store.index_path).parent.parent / "wt_dup"
        _create_manifest_stub(wt, "test-session")

        store.add_session("test-session", str(wt), "/path")

        with pytest.raises(SessionExistsError) as exc_info:
            store.add_session("test-session", str(wt), "/other")
        assert "test-session" in str(exc_info.value)

    def test_add_session_invalid_name(self, store: IndexStore) -> None:
        """add_session() should validate session name."""
        wt = Path(store.index_path).parent.parent / "wt_invalid_name"
        _create_manifest_stub(wt, "valid-name")

        with pytest.raises(InvalidSessionNameError):
            store.add_session("INVALID", str(wt), "/path")


class TestIndexStoreGetSession:
    """Test IndexStore.get_session()."""

    def test_get_session_existing(self, store: IndexStore) -> None:
        """get_session() should return existing session."""
        wt = Path(store.index_path).parent.parent / "wt_test_session"
        _create_manifest_stub(wt, "test-session")

        store.add_session("test-session", str(wt), "/path")

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

    def test_list_sessions_sorted_by_last_accessed(self, store: IndexStore) -> None:
        """list_sessions() should sort by last_accessed_at DESC."""
        # Add sessions with different timestamps
        wt1 = Path(store.index_path).parent.parent / "wt1"
        wt2 = Path(store.index_path).parent.parent / "wt2"
        wt3 = Path(store.index_path).parent.parent / "wt3"
        _create_manifest_stub(wt1, "old-session")
        _create_manifest_stub(wt2, "new-session")
        _create_manifest_stub(wt3, "mid-session")

        store.add_session("old-session", str(wt1), "/path")
        store.update_session("old-session", "2024-12-17T10:00:00+00:00")

        store.add_session("new-session", str(wt2), "/path")
        store.update_session("new-session", "2024-12-17T12:00:00+00:00")

        store.add_session("mid-session", str(wt3), "/path")
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
        _create_manifest_stub(wt1, "zebra")
        _create_manifest_stub(wt2, "apple")
        _create_manifest_stub(wt3, "banana")

        store.add_session("zebra", str(wt1), "/path")
        store.update_session("zebra", timestamp)

        store.add_session("apple", str(wt2), "/path")
        store.update_session("apple", timestamp)

        store.add_session("banana", str(wt3), "/path")
        store.update_session("banana", timestamp)

        sessions = store.list_sessions()
        names = [name for name, _ in sessions]

        # Same timestamp, sorted alphabetically
        assert names == ["apple", "banana", "zebra"]

    def test_list_sessions_excludes_incognito(self, store: IndexStore) -> None:
        """list_sessions() can exclude incognito sessions."""
        wt1 = Path(store.index_path).parent.parent / "wt_normal"
        wt2 = Path(store.index_path).parent.parent / "wt_incognito"
        _create_manifest_stub(wt1, "normal")
        _create_manifest_stub(wt2, "incognito")

        store.add_session("normal", str(wt1), "/path")
        store.add_session("incognito", str(wt2), "/path", is_incognito=True)

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
        _create_manifest_stub(forge_root, "worktree-session")

        store.add_session(
            "worktree-session",
            str(worktree),
            str(forge_root),
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
        _create_manifest_stub(wt, "test-session")

        store.add_session("test-session", str(wt), "/path")

        new_timestamp = "2024-12-17T15:00:00"
        entry = store.update_session("test-session", new_timestamp)

        assert entry.last_accessed_at == new_timestamp

        # Verify persisted
        loaded = store.get_session("test-session")
        assert loaded.last_accessed_at == new_timestamp

    def test_update_session_defaults_to_now(self, store: IndexStore) -> None:
        """update_session() should default to now() if no timestamp."""
        wt = Path(store.index_path).parent.parent / "wt_update_now"
        _create_manifest_stub(wt, "test-session")

        store.add_session("test-session", str(wt), "/path")
        before = now_iso()

        entry = store.update_session("test-session")

        after = now_iso()
        assert before <= entry.last_accessed_at <= after

    def test_update_session_not_found(self, store: IndexStore) -> None:
        """update_session() should raise SessionNotFoundError for missing session."""
        with pytest.raises(SessionNotFoundError):
            store.update_session("nonexistent")


class TestIndexStoreRemoveSession:
    """Test IndexStore.remove_session()."""

    def test_remove_session_existing(self, store: IndexStore) -> None:
        """remove_session() should remove existing session."""
        wt = Path(store.index_path).parent.parent / "wt_remove"
        _create_manifest_stub(wt, "test-session")

        store.add_session("test-session", str(wt), "/path")
        assert store.session_exists("test-session") is True

        result = store.remove_session("test-session")
        assert result is True
        assert store.session_exists("test-session") is False

    def test_remove_session_not_found(self, store: IndexStore) -> None:
        """remove_session() should return False for missing session."""
        result = store.remove_session("nonexistent")
        assert result is False

    def test_remove_session_invalid_name(self, store: IndexStore) -> None:
        """remove_session() should validate session name."""
        with pytest.raises(InvalidSessionNameError):
            store.remove_session("INVALID")


class TestIndexStoreSessionExists:
    """Test IndexStore.session_exists()."""

    def test_session_exists_true(self, store: IndexStore) -> None:
        """session_exists() should return True for existing session."""
        wt = Path(store.index_path).parent.parent / "wt_exists"
        _create_manifest_stub(wt, "test-session")

        store.add_session("test-session", str(wt), "/path")
        assert store.session_exists("test-session") is True

    def test_session_exists_false(self, store: IndexStore) -> None:
        """session_exists() should return False for missing session."""
        assert store.session_exists("nonexistent") is False

    def test_session_exists_invalid_name(self, store: IndexStore) -> None:
        """session_exists() should return False for invalid name."""
        assert store.session_exists("INVALID") is False


class TestIndexStoreAddFromManifest:
    """Test IndexStore.add_from_state()."""

    # Default proxy values for tests (proxy is required in v1 manifests)
    DEFAULT_PROXY_TEMPLATE = "test-family"
    DEFAULT_PROXY_URL = "http://localhost:8080"

    def test_add_from_state_basic(self, store: IndexStore) -> None:
        """add_from_state() should add session from manifest."""
        manifest = create_session_state(
            "test-session",
            proxy_template=self.DEFAULT_PROXY_TEMPLATE,
            proxy_base_url=self.DEFAULT_PROXY_URL,
        )

        entry = store.add_from_state(manifest, "/path/to/project")

        assert store.session_exists("test-session") is True
        assert entry.project_root == "/path/to/project"
        assert entry.worktree_path == "/path/to/project"  # No worktree

    def test_add_from_state_with_worktree(self, store: IndexStore) -> None:
        """add_from_state() should use worktree path if present."""
        wt = Path(store.index_path).parent.parent / "wt_add_from_state"
        _create_manifest_stub(wt, "test-session")

        manifest = create_session_state(
            "test-session",
            proxy_template=self.DEFAULT_PROXY_TEMPLATE,
            proxy_base_url=self.DEFAULT_PROXY_URL,
            worktree_path=str(wt),
            worktree_branch="feature",
        )

        entry = store.add_from_state(manifest, "/path/to/project")

        assert entry.worktree_path == str(wt)
        assert entry.project_root == "/path/to/project"

    def test_add_from_state_with_flags(self, store: IndexStore) -> None:
        """add_from_state() should preserve fork/incognito flags."""
        manifest = create_session_state(
            "fork-session",
            proxy_template=self.DEFAULT_PROXY_TEMPLATE,
            proxy_base_url=self.DEFAULT_PROXY_URL,
            parent_session="parent",
            is_fork=True,
            is_incognito=True,
        )

        entry = store.add_from_state(manifest, "/path")

        assert entry.is_fork is True
        assert entry.is_incognito is True
        assert entry.parent_session == "parent"


class TestIndexStoreUuidFields:
    """Test UUID fields in SessionIndexEntry."""

    # Default proxy values for tests
    DEFAULT_PROXY_TEMPLATE = "test-family"
    DEFAULT_PROXY_URL = "http://localhost:8080"

    def test_new_entry_has_empty_uuid_fields(self, store: IndexStore) -> None:
        """New index entries should have empty UUID fields."""
        wt = Path(store.index_path).parent.parent / "wt_uuid_empty"
        _create_manifest_stub(wt, "test-session")

        store.add_session("test-session", str(wt), "/path")
        entry = store.get_session("test-session")

        assert entry.claude_session_id is None

    def test_uuid_fields_roundtrip(self, store: IndexStore, index_path: Path) -> None:
        """UUID fields should serialize and deserialize correctly."""
        wt = Path(store.index_path).parent.parent / "wt_uuid_roundtrip"
        _create_manifest_stub(wt, "test-session")

        store.add_session("test-session", str(wt), "/path", claude_session_id="abc-123")

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
        assert "unsupported version" in str(exc_info.value)


class TestIndexStoreFindByUuid:
    """Test IndexStore.find_session_by_uuid()."""

    def test_find_by_current_uuid(self, store: IndexStore) -> None:
        """find_session_by_uuid() should find session by current UUID."""
        wt = Path(store.index_path).parent.parent / "wt_find_current"
        _create_manifest_stub(wt, "test-session")

        store.add_session("test-session", str(wt), "/path", claude_session_id="uuid-123")

        result = store.find_session_by_uuid("uuid-123")
        assert result is not None
        assert result[0] == "test-session"

    def test_find_by_uuid_not_found(self, store: IndexStore) -> None:
        """find_session_by_uuid() should return None if UUID not found."""
        wt = Path(store.index_path).parent.parent / "wt_find_none"
        _create_manifest_stub(wt, "test-session")

        store.add_session("test-session", str(wt), "/path")

        result = store.find_session_by_uuid("nonexistent-uuid")
        assert result is None

    def test_find_by_uuid_multiple_sessions(self, store: IndexStore) -> None:
        """find_session_by_uuid() should find correct session among multiple."""
        wt1 = Path(store.index_path).parent.parent / "wt_multi_a"
        wt2 = Path(store.index_path).parent.parent / "wt_multi_b"
        wt3 = Path(store.index_path).parent.parent / "wt_multi_c"
        _create_manifest_stub(wt1, "session-a")
        _create_manifest_stub(wt2, "session-b")
        _create_manifest_stub(wt3, "session-c")

        store.add_session("session-a", str(wt1), "/path", claude_session_id="uuid-a")
        store.add_session("session-b", str(wt2), "/path", claude_session_id="uuid-b")
        store.add_session("session-c", str(wt3), "/path", claude_session_id="uuid-c")

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
        _create_manifest_stub(wt, "test-session")

        store.add_session("test-session", str(wt), "/path")

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
        _create_manifest_stub(wt, "test-session")

        store.add_session("test-session", str(wt), "/path", claude_session_id="existing-uuid")

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

    def test_add_session_stores_identity_fields(self, store: IndexStore, tmp_path: Path) -> None:
        """add_session() persists forge_root, checkout_root, relative_path."""
        worktree = tmp_path / "checkout"
        worktree.mkdir()
        forge = worktree / "sub" / "project"
        forge.mkdir(parents=True)
        (forge / ".forge").mkdir()

        # get_session() validates manifest exists under forge_root
        manifest_dir = forge / ".forge" / "sessions" / "test-identity"
        manifest_dir.mkdir(parents=True)
        (manifest_dir / "forge.session.json").write_text(
            '{"schema_version":1,"name":"test-identity","created_at":"2024-01-01T00:00:00","last_accessed_at":"2024-01-01T00:00:00","intent":{},"overrides":{},"confirmed":{}}'
        )

        entry = store.add_session(
            "test-identity",
            worktree_path=str(worktree),
            project_root=str(tmp_path),
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

    def test_add_session_identity_fields_fallback(self, store: IndexStore) -> None:
        """Identity fields fall back to worktree_path when not provided."""
        entry = store.add_session(
            "legacy-session",
            worktree_path="/some/path",
            project_root="/some/repo",
        )
        assert entry.forge_root == "/some/path"
        assert entry.checkout_root == "/some/path"
        assert entry.relative_path == "."

    def test_add_from_state_passes_identity_fields(self, store: IndexStore, tmp_path: Path) -> None:
        """add_from_state() passes caller-provided identity fields to the index."""
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

        entry = store.add_from_state(
            state,
            str(tmp_path),
            checkout_root=str(worktree),
            forge_root=str(worktree),
            relative_path=".",
        )
        assert entry.forge_root == str(worktree)
        assert entry.checkout_root == str(worktree)
        assert entry.relative_path == "."

    def test_add_from_state_falls_back_to_state_forge_root(self, store: IndexStore, tmp_path: Path) -> None:
        """add_from_state() uses state.forge_root when caller doesn't provide forge_root."""
        worktree = tmp_path / "wt"
        worktree.mkdir()

        state = create_session_state(
            "fallback-test",
            proxy_template=self.DEFAULT_PROXY_TEMPLATE,
            proxy_base_url=self.DEFAULT_PROXY_URL,
            worktree_path=str(worktree),
        )
        state.forge_root = str(worktree)

        entry = store.add_from_state(state, str(tmp_path))
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
        assert "unsupported version" in str(exc_info.value)

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
        _create_manifest_stub(wt_a, "planner")
        _create_manifest_stub(wt_b, "planner")

        store.add_session("planner", str(wt_a), str(wt_a), forge_root=str(wt_a))
        store.add_session("planner", str(wt_b), str(wt_b), forge_root=str(wt_b))

        # Both exist when scoped
        assert store.session_exists("planner", forge_root=str(wt_a))
        assert store.session_exists("planner", forge_root=str(wt_b))

    def test_get_session_scoped_returns_correct_entry(self, store: IndexStore) -> None:
        """Scoped get_session returns the correct project's entry."""
        wt_a = Path(store.index_path).parent.parent / "project-a"
        wt_b = Path(store.index_path).parent.parent / "project-b"
        _create_manifest_stub(wt_a, "planner")
        _create_manifest_stub(wt_b, "planner")

        store.add_session("planner", str(wt_a), str(wt_a), forge_root=str(wt_a))
        store.add_session("planner", str(wt_b), str(wt_b), forge_root=str(wt_b))

        entry_a = store.get_session("planner", forge_root=str(wt_a))
        entry_b = store.get_session("planner", forge_root=str(wt_b))

        assert entry_a.forge_root == str(wt_a)
        assert entry_b.forge_root == str(wt_b)

    def test_session_exists_scoped_isolates_projects(self, store: IndexStore) -> None:
        """Session in project A is invisible from project B's scope."""
        wt_a = Path(store.index_path).parent.parent / "project-a"
        wt_c = Path(store.index_path).parent.parent / "project-c"
        _create_manifest_stub(wt_a, "planner")

        store.add_session("planner", str(wt_a), str(wt_a), forge_root=str(wt_a))

        assert store.session_exists("planner", forge_root=str(wt_a))
        assert not store.session_exists("planner", forge_root=str(wt_c))

    def test_remove_session_scoped(self, store: IndexStore) -> None:
        """Removing a session in project A doesn't affect project B."""
        wt_a = Path(store.index_path).parent.parent / "project-a"
        wt_b = Path(store.index_path).parent.parent / "project-b"
        _create_manifest_stub(wt_a, "planner")
        _create_manifest_stub(wt_b, "planner")

        store.add_session("planner", str(wt_a), str(wt_a), forge_root=str(wt_a))
        store.add_session("planner", str(wt_b), str(wt_b), forge_root=str(wt_b))

        store.remove_session("planner", forge_root=str(wt_a))

        assert not store.session_exists("planner", forge_root=str(wt_a))
        assert store.session_exists("planner", forge_root=str(wt_b))

    def test_list_sessions_returns_display_names(self, store: IndexStore) -> None:
        """list_sessions returns display names, not scoped keys."""
        wt_a = Path(store.index_path).parent.parent / "project-a"
        _create_manifest_stub(wt_a, "my-session")

        store.add_session("my-session", str(wt_a), str(wt_a), forge_root=str(wt_a))

        sessions = store.list_sessions()
        names = [n for n, _ in sessions]
        assert "my-session" in names
        assert not any("|" in n for n in names)

    def test_unscoped_ambiguous_raises(self, store: IndexStore) -> None:
        """Unscoped lookup of duplicate name raises AmbiguousSessionError."""
        from forge.session.exceptions import AmbiguousSessionError

        wt_a = Path(store.index_path).parent.parent / "project-a"
        wt_b = Path(store.index_path).parent.parent / "project-b"
        _create_manifest_stub(wt_a, "planner")
        _create_manifest_stub(wt_b, "planner")

        store.add_session("planner", str(wt_a), str(wt_a), forge_root=str(wt_a))
        store.add_session("planner", str(wt_b), str(wt_b), forge_root=str(wt_b))

        with pytest.raises(AmbiguousSessionError):
            store.get_session("planner")

    def test_find_by_uuid_returns_display_name_and_forge_root(self, store: IndexStore) -> None:
        """find_session_by_uuid returns (display_name, forge_root) tuple."""
        wt_a = Path(store.index_path).parent.parent / "project-a"
        _create_manifest_stub(wt_a, "planner")

        store.add_session("planner", str(wt_a), str(wt_a), forge_root=str(wt_a), claude_session_id="uuid-abc")

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
        _create_manifest_stub(forge_root_nested, "planner")

        store.add_session(
            "planner",
            worktree_path=str(checkout),  # checkout root
            project_root=str(checkout),
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
        _create_manifest_stub(root_project, "planner")
        _create_manifest_stub(nested_forge, "planner")

        store.add_session(
            "planner",
            worktree_path=str(root_project),
            project_root=str(root_project),
            forge_root=str(root_project),
        )
        store.add_session(
            "planner",
            worktree_path=str(root_project),
            project_root=str(root_project),
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
        _create_manifest_stub(wt_a, "planner")
        _create_manifest_stub(wt_b, "planner")

        store.add_session("planner", str(wt_a), str(wt_a), forge_root=str(wt_a))
        store.add_session("planner", str(wt_b), str(wt_b), forge_root=str(wt_b))

        with pytest.raises(AmbiguousSessionError):
            store.session_exists("planner")

    def test_update_session_unscoped_ambiguous_raises(self, store: IndexStore) -> None:
        """update_session() with forge_root=None raises on duplicates."""
        from forge.session.exceptions import AmbiguousSessionError

        wt_a = Path(store.index_path).parent.parent / "project-a"
        wt_b = Path(store.index_path).parent.parent / "project-b"
        _create_manifest_stub(wt_a, "planner")
        _create_manifest_stub(wt_b, "planner")

        store.add_session("planner", str(wt_a), str(wt_a), forge_root=str(wt_a))
        store.add_session("planner", str(wt_b), str(wt_b), forge_root=str(wt_b))

        with pytest.raises(AmbiguousSessionError):
            store.update_session("planner")

    def test_remove_session_unscoped_ambiguous_raises(self, store: IndexStore) -> None:
        """remove_session() with forge_root=None raises on duplicates."""
        from forge.session.exceptions import AmbiguousSessionError

        wt_a = Path(store.index_path).parent.parent / "project-a"
        wt_b = Path(store.index_path).parent.parent / "project-b"
        _create_manifest_stub(wt_a, "planner")
        _create_manifest_stub(wt_b, "planner")

        store.add_session("planner", str(wt_a), str(wt_a), forge_root=str(wt_a))
        store.add_session("planner", str(wt_b), str(wt_b), forge_root=str(wt_b))

        with pytest.raises(AmbiguousSessionError):
            store.remove_session("planner")
