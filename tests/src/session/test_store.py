"""Tests for SessionStore."""

from __future__ import annotations

import json
import os
import time
from multiprocessing import Event, Process, synchronize
from pathlib import Path

import pytest

from forge.core.state import FileLockTimeoutError, now_iso
from forge.session.exceptions import (
    InvalidSessionNameError,
    ManifestCorruptedError,
    ManifestValidationError,
    SessionFileNotFoundError,
)
from forge.session.models import (
    SessionState,
    create_session_state,
)
from forge.session.store import (
    HOOK_LOCK_TIMEOUT_S,
    MANIFEST_DIR,
    MANIFEST_FILENAME,
    SessionStore,
)


@pytest.fixture
def temp_worktree(tmp_path: Path) -> Path:
    """Create a temporary worktree-like directory."""
    worktree = tmp_path / "my-project"
    worktree.mkdir()
    return worktree


@pytest.fixture
def store(temp_worktree: Path) -> SessionStore:
    """Create a SessionStore for the temp worktree."""
    return SessionStore(str(temp_worktree), "test-session")


@pytest.fixture
def sample_manifest() -> SessionState:
    """Create a sample manifest for testing."""
    return create_session_state(
        "test-session",
        proxy_template="litellm-gemini",
        proxy_base_url="http://localhost:8084",
    )


class TestSessionStoreProperties:
    """Test SessionStore properties."""

    def test_manifest_path(self, store: SessionStore, temp_worktree: Path) -> None:
        """manifest_path should point to per-session directory."""
        expected = temp_worktree / MANIFEST_DIR / "sessions" / "test-session" / MANIFEST_FILENAME
        assert store.manifest_path == expected

    def test_session_name(self, store: SessionStore) -> None:
        """session_name should return the session name."""
        assert store.session_name == "test-session"

    def test_session_dir(self, store: SessionStore, temp_worktree: Path) -> None:
        """session_dir should return the session directory."""
        expected = temp_worktree / MANIFEST_DIR / "sessions" / "test-session"
        assert store.session_dir == expected

    def test_exists_false_initially(self, store: SessionStore) -> None:
        """exists() should return False when no manifest."""
        assert store.exists() is False


class TestSessionStoreWrite:
    """Test SessionStore.write()."""

    def test_write_creates_manifest(self, store: SessionStore, sample_manifest: SessionState) -> None:
        """write() should create the manifest file."""
        store.write(sample_manifest)
        assert store.exists() is True
        assert store.manifest_path.is_file()

    def test_write_creates_claude_directory(self, store: SessionStore, sample_manifest: SessionState) -> None:
        """write() should create .claude directory if missing."""
        assert not (store.forge_root / MANIFEST_DIR).exists()
        store.write(sample_manifest)
        assert (store.forge_root / MANIFEST_DIR).is_dir()

    def test_write_valid_json(self, store: SessionStore, sample_manifest: SessionState) -> None:
        """write() should produce valid JSON."""
        store.write(sample_manifest)
        with open(store.manifest_path) as f:
            data = json.load(f)
        assert data["name"] == "test-session"
        assert data["schema_version"] == 1  # Always writes current version

    def test_write_validates_name(self, store: SessionStore) -> None:
        """write() should reject invalid session names."""
        manifest = create_session_state(
            "valid-name",
            proxy_template="test-family",
            proxy_base_url="http://localhost:8080",
        )
        manifest.name = "INVALID"  # Set invalid name after creation
        with pytest.raises(InvalidSessionNameError):
            store.write(manifest)

    def test_write_overwrites_existing(self, store: SessionStore, sample_manifest: SessionState) -> None:
        """write() should overwrite existing manifest."""
        store.write(sample_manifest)

        # Modify and write again
        sample_manifest.intent.agent = "custom-agent"
        store.write(sample_manifest)

        # Read back and verify
        with open(store.manifest_path) as f:
            data = json.load(f)
        assert data["intent"]["agent"] == "custom-agent"


def _update_latest_plan(worktree_path: str, latest_plan: str) -> None:
    store = SessionStore(worktree_path, "test-session")

    def _mutate(m: SessionState) -> None:
        m.confirmed.latest_plan_path = latest_plan

    store.update(timeout_s=5.0, mutate=_mutate)


def _update_override_agent(worktree_path: str, value: str) -> None:
    store = SessionStore(worktree_path, "test-session")

    def _mutate(m: SessionState) -> None:
        m.overrides["agent"] = value

    store.update(timeout_s=5.0, mutate=_mutate)


def _hold_manifest_lock(lock_path: str, hold_s: float, ready_event: synchronize.Event | None = None) -> None:
    """Hold an exclusive lock on a file for the specified duration.

    Args:
        lock_path: Path to the lock file
        hold_s: How long to hold the lock (seconds)
        ready_event: Optional Event to signal when lock is acquired
    """
    import fcntl

    path = Path(lock_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("a+") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        if ready_event:
            ready_event.set()  # Signal that lock is acquired
        time.sleep(hold_s)


class TestSupervisorConfigCompat:
    """Manifests written before the cascade fields existed load with defaults."""

    def test_old_manifest_without_cascade_fields_loads_defaults(self, tmp_path: Path) -> None:
        from forge.session.models import PolicyIntent, SupervisorConfig

        store = SessionStore(str(tmp_path), "old-session")
        state = create_session_state("old-session", worktree_path=str(tmp_path))
        state.intent.policy = PolicyIntent(enabled=True, supervisor=SupervisorConfig(resume_id="planner"))
        store.write(state)

        # Simulate a manifest written by an older Forge: strip the new keys.
        data = json.loads(store.manifest_path.read_text())
        sup = data["intent"]["policy"]["supervisor"]
        del sup["cascade"]
        del sup["checker_model"]
        del sup["checker_provider"]
        del sup["checker_budget_tokens"]
        store.manifest_path.write_text(json.dumps(data))

        loaded = store.read()
        assert loaded.intent.policy is not None
        assert loaded.intent.policy.supervisor is not None
        assert loaded.intent.policy.supervisor.cascade is False
        assert loaded.intent.policy.supervisor.checker_model is None
        assert loaded.intent.policy.supervisor.checker_provider is None
        assert loaded.intent.policy.supervisor.checker_budget_tokens is None

    def test_new_fields_round_trip(self, tmp_path: Path) -> None:
        from forge.session.models import PolicyIntent, SupervisorConfig

        store = SessionStore(str(tmp_path), "new-session")
        state = create_session_state("new-session", worktree_path=str(tmp_path))
        state.intent.policy = PolicyIntent(
            enabled=True,
            supervisor=SupervisorConfig(
                resume_id="planner",
                cascade=True,
                checker_model="gemini/gemini-3.5-flash",
                checker_provider="litellm_local",
                checker_budget_tokens=64000,
            ),
        )
        store.write(state)

        loaded = store.read()
        assert loaded.intent.policy is not None
        assert loaded.intent.policy.supervisor is not None
        assert loaded.intent.policy.supervisor.cascade is True
        assert loaded.intent.policy.supervisor.checker_model == "gemini/gemini-3.5-flash"
        assert loaded.intent.policy.supervisor.checker_provider == "litellm_local"
        assert loaded.intent.policy.supervisor.checker_budget_tokens == 64000


class TestEffortVocabularyValidation:
    """Effort fields validate against their respective vocabularies in __post_init__.

    Two distinct vocabularies (see forge.core.effort):
    - claude --effort: low/medium/high/xhigh/max (max-only, no 'none')
    - core.llm ReasoningEffort: none/low/medium/high/xhigh ('none'-only, no 'max')
    """

    def test_memory_writer_max_is_valid(self) -> None:
        from forge.session.models import MemoryWriterConfig

        assert MemoryWriterConfig(effort="max").effort == "max"

    def test_memory_writer_none_rejected(self) -> None:
        from forge.session.models import MemoryWriterConfig

        # claude --effort has no "none" level.
        with pytest.raises(ValueError):
            MemoryWriterConfig(effort="none")

    def test_memory_writer_bogus_rejected(self) -> None:
        from forge.session.models import MemoryWriterConfig

        with pytest.raises(ValueError):
            MemoryWriterConfig(effort="bogus")

    def test_supervisor_checker_effort_none_is_valid(self) -> None:
        from forge.session.models import SupervisorConfig

        # checker_effort is a core.llm call; "none" is valid there.
        assert SupervisorConfig(checker_effort="none").checker_effort == "none"

    def test_supervisor_checker_effort_max_rejected(self) -> None:
        from forge.session.models import SupervisorConfig

        # core.llm vocabulary excludes "max".
        with pytest.raises(ValueError):
            SupervisorConfig(checker_effort="max")

    def test_supervisor_effort_max_is_valid(self) -> None:
        from forge.session.models import SupervisorConfig

        # Frontier supervisor runs via claude --effort; "max" is valid there.
        assert SupervisorConfig(supervisor_effort="max").supervisor_effort == "max"

    def test_supervisor_effort_bogus_rejected(self) -> None:
        from forge.session.models import SupervisorConfig

        with pytest.raises(ValueError):
            SupervisorConfig(supervisor_effort="bogus")


class TestSessionStoreUpdate:
    def test_update_merges_concurrent_writes(self, temp_worktree: Path, sample_manifest: SessionState) -> None:
        """update() should prevent lost updates when multiple processes write."""

        store = SessionStore(str(temp_worktree), "test-session")
        store.write(sample_manifest)

        p1 = Process(target=_update_latest_plan, args=(str(temp_worktree), "plans/latest.md"))
        p2 = Process(target=_update_override_agent, args=(str(temp_worktree), "custom-agent"))

        p1.start()
        p2.start()
        p1.join(timeout=5.0)
        p2.join(timeout=5.0)

        assert not p1.is_alive()
        assert not p2.is_alive()

        loaded = store.read()
        assert loaded.confirmed.latest_plan_path == "plans/latest.md"
        assert loaded.overrides.get("agent") == "custom-agent"

    def test_update_releases_lock_when_mutate_raises(self, temp_worktree: Path, sample_manifest: SessionState) -> None:
        """update() should release the lock even if mutate() raises."""

        store = SessionStore(str(temp_worktree), "test-session")
        store.write(sample_manifest)

        def _boom(_: SessionState) -> None:
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            store.update(timeout_s=5.0, mutate=_boom)

        # If the lock leaked, this would time out.
        store.update(timeout_s=HOOK_LOCK_TIMEOUT_S, mutate=lambda m: None)

    def test_update_times_out_under_contention(self, temp_worktree: Path, sample_manifest: SessionState) -> None:
        """update() should raise FileLockTimeoutError when lock cannot be acquired."""

        store = SessionStore(str(temp_worktree), "test-session")
        store.write(sample_manifest)

        lock_path = store.manifest_path.parent / f"{store.manifest_path.name}.lock"

        # Use Event for proper synchronization instead of sleep-and-hope
        ready_event = Event()
        proc = Process(target=_hold_manifest_lock, args=(str(lock_path), 0.5, ready_event))
        proc.start()

        try:
            # Wait for subprocess to actually acquire the lock (deterministic, not racy)
            assert ready_event.wait(timeout=2.0), "Subprocess failed to acquire lock"

            with pytest.raises(FileLockTimeoutError):
                store.update(timeout_s=HOOK_LOCK_TIMEOUT_S, mutate=lambda m: None)
        finally:
            proc.join(timeout=2.0)
            if proc.is_alive():
                proc.terminate()
                proc.join(timeout=2.0)


class TestSessionStoreRead:
    """Test SessionStore.read()."""

    def test_read_roundtrip(self, store: SessionStore, sample_manifest: SessionState) -> None:
        """read() should return equivalent manifest after write."""
        store.write(sample_manifest)
        loaded = store.read()

        assert loaded.schema_version == sample_manifest.schema_version
        assert loaded.name == sample_manifest.name
        assert loaded.created_at == sample_manifest.created_at
        assert loaded.last_accessed_at == sample_manifest.last_accessed_at
        assert loaded.is_fork == sample_manifest.is_fork
        assert loaded.is_incognito == sample_manifest.is_incognito

        # Check intent
        assert loaded.intent.proxy is not None
        assert loaded.intent.proxy.template == "litellm-gemini"
        assert loaded.intent.proxy.base_url == "http://localhost:8084"
        assert loaded.intent.launch is not None
        assert loaded.intent.launch.mode == "host"

    def test_read_roundtrip_with_sidecar_launch_preferences(self, store: SessionStore) -> None:
        """Sidecar launch preferences should persist through manifest storage."""
        manifest = create_session_state(
            "test-session",
            proxy_template="litellm-openai",
            proxy_base_url="http://localhost:8085",
            launch_mode="sidecar",
            sidecar_mounts=["/data:/mnt/data:ro"],
            sidecar_image="forge-sidecar:test",
        )

        store.write(manifest)
        loaded = store.read()

        assert loaded.intent.launch is not None
        assert loaded.intent.launch.mode == "sidecar"
        assert loaded.intent.launch.sidecar is not None
        assert loaded.intent.launch.sidecar.mounts == ["/data:/mnt/data:ro"]
        assert loaded.intent.launch.sidecar.image == "forge-sidecar:test"

    def test_read_missing_file(self, store: SessionStore) -> None:
        """read() should raise SessionFileNotFoundError for missing file."""
        with pytest.raises(SessionFileNotFoundError) as exc_info:
            store.read()
        assert "not found" in str(exc_info.value)

    def test_read_invalid_json(self, store: SessionStore) -> None:
        """read() should raise ManifestCorruptedError for invalid JSON."""
        store.manifest_path.parent.mkdir(parents=True)
        store.manifest_path.write_text("not valid json {{{")

        with pytest.raises(ManifestCorruptedError) as exc_info:
            store.read()
        assert "invalid JSON" in str(exc_info.value)

    def test_read_missing_schema_version(self, store: SessionStore) -> None:
        """read() should raise ManifestValidationError for missing schema_version."""
        store.manifest_path.parent.mkdir(parents=True)
        data = {
            "name": "test",
            "created_at": now_iso(),
            "last_accessed_at": now_iso(),
            "intent": {"proxy": {"template": "test", "base_url": "http://localhost"}},
            "overrides": {},
        }
        store.manifest_path.write_text(json.dumps(data))

        with pytest.raises(ManifestValidationError) as exc_info:
            store.read()
        assert "schema_version" in str(exc_info.value)

    def test_read_wrong_schema_version(self, store: SessionStore) -> None:
        """read() should raise ManifestCorruptedError for wrong schema version."""
        store.manifest_path.parent.mkdir(parents=True)
        data = {
            "schema_version": 999,
            "name": "test",
            "created_at": now_iso(),
            "last_accessed_at": now_iso(),
            "intent": {"proxy": {"template": "test", "base_url": "http://localhost"}},
            "overrides": {},
        }
        store.manifest_path.write_text(json.dumps(data))

        with pytest.raises(ManifestCorruptedError) as exc_info:
            store.read()
        assert "incompatible schema version" in str(exc_info.value)

    def test_read_missing_name(self, store: SessionStore) -> None:
        """read() should raise ManifestValidationError for missing name."""
        store.manifest_path.parent.mkdir(parents=True)
        data = {
            "schema_version": 1,
            "created_at": now_iso(),
            "last_accessed_at": now_iso(),
            "intent": {"proxy": {"template": "test", "base_url": "http://localhost"}},
            "overrides": {},
        }
        store.manifest_path.write_text(json.dumps(data))

        with pytest.raises(ManifestValidationError) as exc_info:
            store.read()
        assert "name" in str(exc_info.value)

    def test_read_started_with_proxy_roundtrip(self, store: SessionStore) -> None:
        """read() should roundtrip confirmed.started_with_proxy when present."""
        store.manifest_path.parent.mkdir(parents=True)

        data = {
            "schema_version": 1,
            "name": "test",
            "created_at": now_iso(),
            "last_accessed_at": now_iso(),
            "intent": {},
            "overrides": {},
            "confirmed": {
                "started_with_proxy": {
                    "base_url": "http://localhost:8084",
                    "proxy_id": "proxy_test",
                    "template": "litellm-openai",
                    "port": 8084,
                }
            },
        }

        store.manifest_path.write_text(json.dumps(data))

        manifest = store.read()
        assert manifest.confirmed.started_with_proxy is not None
        assert manifest.confirmed.started_with_proxy.base_url == "http://localhost:8084"
        assert manifest.confirmed.started_with_proxy.proxy_id == "proxy_test"
        assert manifest.confirmed.started_with_proxy.template == "litellm-openai"
        assert manifest.confirmed.started_with_proxy.port == 8084

    def test_read_missing_proxy_allowed_in_v3(self, store: SessionStore) -> None:
        """read() should allow missing intent.proxy in v3 (no-proxy mode)."""
        store.manifest_path.parent.mkdir(parents=True)
        data = {
            "schema_version": 1,
            "name": "test",
            "created_at": now_iso(),
            "last_accessed_at": now_iso(),
            "intent": {},  # No proxy - allowed in v2
            "overrides": {},
        }
        store.manifest_path.write_text(json.dumps(data))

        # Should not raise - proxy is optional in v2
        manifest = store.read()
        assert manifest.name == "test"
        assert manifest.intent.proxy is None

    def test_read_incomplete_proxy(self, store: SessionStore) -> None:
        """read() should raise ManifestValidationError for incomplete proxy."""
        store.manifest_path.parent.mkdir(parents=True)
        data = {
            "schema_version": 1,
            "name": "test",
            "created_at": now_iso(),
            "last_accessed_at": now_iso(),
            "intent": {"proxy": {"template": "test"}},  # Missing base_url
            "overrides": {},
        }
        store.manifest_path.write_text(json.dumps(data))

        with pytest.raises(ManifestValidationError) as exc_info:
            store.read()
        assert "intent.proxy.base_url" in str(exc_info.value)


class TestSessionStoreDelete:
    """Test SessionStore.delete()."""

    def test_delete_existing(self, store: SessionStore, sample_manifest: SessionState) -> None:
        """delete() should remove existing manifest."""
        store.write(sample_manifest)
        assert store.exists() is True

        result = store.delete()
        assert result is True
        assert store.exists() is False

    def test_delete_nonexistent(self, store: SessionStore) -> None:
        """delete() should return False for missing manifest."""
        result = store.delete()
        assert result is False


class TestSessionStoreUpdateLastAccessed:
    """Test SessionStore.update_last_accessed()."""

    def test_update_last_accessed(self, store: SessionStore, sample_manifest: SessionState) -> None:
        """update_last_accessed() should update timestamp."""
        store.write(sample_manifest)
        original_timestamp = sample_manifest.last_accessed_at

        # Wait a tiny bit and update
        updated = store.update_last_accessed()

        assert updated.last_accessed_at >= original_timestamp
        # Verify persisted
        loaded = store.read()
        assert loaded.last_accessed_at == updated.last_accessed_at


class TestAtomicWrite:
    """Test atomic write behavior."""

    def test_atomic_write_survives_failure(
        self,
        store: SessionStore,
        sample_manifest: SessionState,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Original file remains intact if os.replace fails."""
        # 1. Write initial valid file
        store.write(sample_manifest)
        original_content = store.manifest_path.read_text()

        # 2. Monkeypatch os.replace to raise OSError
        def failing_replace(src: str, dst: str) -> None:
            raise OSError("Simulated failure")

        monkeypatch.setattr(os, "replace", failing_replace)

        # 3. Attempt write (should fail)
        sample_manifest.intent.agent = "custom-agent"
        with pytest.raises(OSError, match="Simulated failure"):
            store.write(sample_manifest)

        # 4. Assert original file unchanged and valid
        assert store.manifest_path.read_text() == original_content
        loaded = store.read()
        assert loaded.intent.agent == "claude-code"  # Original value

    def test_temp_file_cleaned_on_failure(
        self,
        store: SessionStore,
        sample_manifest: SessionState,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Temp file should be cleaned up on failure."""
        store.write(sample_manifest)

        # Count files before
        claude_dir = store.manifest_path.parent
        files_before = set(claude_dir.iterdir())

        # Make replace fail
        def failing_replace(src: str, dst: str) -> None:
            raise OSError("Simulated failure")

        monkeypatch.setattr(os, "replace", failing_replace)

        # Attempt write
        with pytest.raises(OSError):
            store.write(sample_manifest)

        # Count files after - should be same (temp file cleaned up)
        files_after = set(claude_dir.iterdir())
        assert files_before == files_after


class TestDictOverrideValidation:
    """Test that dict-typed intent fields can be set as overrides."""

    def test_dict_override_validation(self, store: SessionStore, sample_manifest: SessionState) -> None:
        """policy.bundle_config can be set as a dict override without error."""
        store.write(sample_manifest)

        def _mutate(m: SessionState) -> None:
            m.overrides["policy"] = {"bundle_config": {"tdd": {"strict": True}}}

        store.update(timeout_s=5.0, mutate=_mutate)
        loaded = store.read()
        assert loaded.overrides["policy"]["bundle_config"] == {"tdd": {"strict": True}}


class TestSchemaStrictness:
    """Test schema strictness for v3 manifests."""

    def test_rejects_unknown_top_level_field(self, store: SessionStore) -> None:
        store.manifest_path.parent.mkdir(parents=True)
        data = {
            "schema_version": 1,
            "name": "test-session",
            "created_at": now_iso(),
            "last_accessed_at": now_iso(),
            "intent": {"proxy": {"template": "test", "base_url": "http://localhost:8080"}},
            "overrides": {},
            "future_field": "some_value",
        }
        store.manifest_path.write_text(json.dumps(data))

        with pytest.raises(ManifestCorruptedError) as exc_info:
            store.read()
        assert "deserialization error" in str(exc_info.value)

    def test_rejects_unknown_nested_intent_field(self, store: SessionStore) -> None:
        store.manifest_path.parent.mkdir(parents=True)
        data = {
            "schema_version": 1,
            "name": "test-session",
            "created_at": now_iso(),
            "last_accessed_at": now_iso(),
            "intent": {
                "proxy": {"template": "test", "base_url": "http://localhost:8080"},
                "future_nested": {"key": "value"},
            },
            "overrides": {},
        }
        store.manifest_path.write_text(json.dumps(data))

        with pytest.raises(ManifestCorruptedError) as exc_info:
            store.read()
        assert "deserialization error" in str(exc_info.value)

    def test_rejects_unknown_override_key(self, store: SessionStore) -> None:
        store.manifest_path.parent.mkdir(parents=True)
        data = {
            "schema_version": 1,
            "name": "test-session",
            "created_at": now_iso(),
            "last_accessed_at": now_iso(),
            "intent": {},
            "overrides": {"custom": {"my_flag": True}},
        }
        store.manifest_path.write_text(json.dumps(data))

        with pytest.raises(ManifestCorruptedError) as exc_info:
            store.read()
        assert "overrides.custom" in str(exc_info.value)
