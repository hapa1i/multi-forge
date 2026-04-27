"""Tests for backend registry."""

import json
from pathlib import Path

import pytest

from forge.backend.registry import (
    BackendInstance,
    BackendRegistry,
    BackendRegistryCorruptedError,
    BackendRegistryStore,
    is_pid_alive,
)


class TestBackendInstance:
    """Tests for BackendInstance dataclass."""

    def test_create_with_required_fields(self) -> None:
        """Verify BackendInstance can be created with required fields."""
        instance = BackendInstance(
            backend_id="litellm-4000",
            adapter_type="litellm",
            port=4000,
        )
        assert instance.backend_id == "litellm-4000"
        assert instance.adapter_type == "litellm"
        assert instance.port == 4000
        assert instance.pid is None
        assert instance.status == "unknown"
        assert instance.created_at is None

    def test_create_with_all_fields(self) -> None:
        """Verify BackendInstance can be created with all fields."""
        instance = BackendInstance(
            backend_id="litellm-4000",
            adapter_type="litellm",
            port=4000,
            pid=12345,
            status="healthy",
            created_at="2026-02-03T10:00:00Z",
        )
        assert instance.pid == 12345
        assert instance.status == "healthy"
        assert instance.created_at == "2026-02-03T10:00:00Z"


class TestBackendRegistry:
    """Tests for BackendRegistry dataclass."""

    def test_empty_registry(self) -> None:
        """Verify empty registry has correct defaults."""
        registry = BackendRegistry()
        assert registry.version == 1
        assert registry.backends == {}

    def test_registry_with_backends(self) -> None:
        """Verify registry can store backends."""
        instance = BackendInstance(
            backend_id="litellm-4000",
            adapter_type="litellm",
            port=4000,
        )
        registry = BackendRegistry(backends={"litellm-4000": instance})
        assert "litellm-4000" in registry.backends
        assert registry.backends["litellm-4000"].port == 4000


class TestBackendRegistryStore:
    """Tests for BackendRegistryStore."""

    def test_read_missing_file_returns_empty(self, tmp_path: Path) -> None:
        """Verify reading missing file returns empty registry."""
        store = BackendRegistryStore(tmp_path / "backends" / "index.json")
        registry = store.read()
        assert registry.backends == {}
        assert registry.version == 1

    def test_write_and_read_roundtrip(self, tmp_path: Path) -> None:
        """Verify write/read roundtrip preserves data."""
        registry_path = tmp_path / "backends" / "index.json"
        registry_path.parent.mkdir(parents=True)
        store = BackendRegistryStore(registry_path)

        instance = BackendInstance(
            backend_id="litellm-4000",
            adapter_type="litellm",
            port=4000,
            pid=12345,
            status="healthy",
            created_at="2026-02-03T10:00:00Z",
        )
        registry = BackendRegistry(backends={"litellm-4000": instance})
        store.write(registry)

        loaded = store.read()
        assert "litellm-4000" in loaded.backends
        backend = loaded.backends["litellm-4000"]
        assert backend.port == 4000
        assert backend.pid == 12345
        assert backend.status == "healthy"

    def test_read_corrupted_json_raises(self, tmp_path: Path) -> None:
        """Verify corrupted JSON raises BackendRegistryCorruptedError."""
        registry_path = tmp_path / "backends" / "index.json"
        registry_path.parent.mkdir(parents=True)
        registry_path.write_text("not valid json {{{")

        store = BackendRegistryStore(registry_path)
        with pytest.raises(BackendRegistryCorruptedError) as exc_info:
            store.read()
        assert "invalid JSON" in str(exc_info.value)

    def test_read_missing_version_raises(self, tmp_path: Path) -> None:
        """Verify missing version field raises BackendRegistryCorruptedError."""
        registry_path = tmp_path / "backends" / "index.json"
        registry_path.parent.mkdir(parents=True)
        registry_path.write_text(json.dumps({"backends": {}}))

        store = BackendRegistryStore(registry_path)
        with pytest.raises(BackendRegistryCorruptedError) as exc_info:
            store.read()
        assert "missing version" in str(exc_info.value)

    def test_read_unsupported_version_raises(self, tmp_path: Path) -> None:
        """Verify unsupported version raises BackendRegistryCorruptedError."""
        registry_path = tmp_path / "backends" / "index.json"
        registry_path.parent.mkdir(parents=True)
        registry_path.write_text(json.dumps({"version": 999, "backends": {}}))

        store = BackendRegistryStore(registry_path)
        with pytest.raises(BackendRegistryCorruptedError) as exc_info:
            store.read()
        assert "unsupported version" in str(exc_info.value)

    def test_update_applies_mutation(self, tmp_path: Path) -> None:
        """Verify update applies mutation function."""
        registry_path = tmp_path / "backends" / "index.json"
        registry_path.parent.mkdir(parents=True)
        store = BackendRegistryStore(registry_path)

        instance = BackendInstance(
            backend_id="litellm-4000",
            adapter_type="litellm",
            port=4000,
        )

        def add_backend(reg: BackendRegistry) -> None:
            reg.backends["litellm-4000"] = instance

        store.update(timeout_s=5.0, mutate=add_backend)

        loaded = store.read()
        assert "litellm-4000" in loaded.backends

    def test_prune_dead_pids_removes_dead(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify prune_dead_pids removes backends with dead PIDs."""
        registry_path = tmp_path / "backends" / "index.json"
        registry_path.parent.mkdir(parents=True)
        store = BackendRegistryStore(registry_path)

        # Create registry with a backend that has a "dead" PID
        instance = BackendInstance(
            backend_id="litellm-4000",
            adapter_type="litellm",
            port=4000,
            pid=99999999,  # Very unlikely to be a real PID
            status="healthy",
        )
        registry = BackendRegistry(backends={"litellm-4000": instance})
        store.write(registry)

        # Mock is_pid_alive to return False
        monkeypatch.setattr("forge.backend.registry.is_pid_alive", lambda pid: False)

        pruned = store.prune_dead_pids()
        assert "litellm-4000" in pruned

        loaded = store.read()
        assert "litellm-4000" not in loaded.backends

    def test_prune_dead_pids_keeps_none_pid(self, tmp_path: Path) -> None:
        """Verify prune_dead_pids keeps backends with pid=None (adopted)."""
        registry_path = tmp_path / "backends" / "index.json"
        registry_path.parent.mkdir(parents=True)
        store = BackendRegistryStore(registry_path)

        instance = BackendInstance(
            backend_id="litellm-4000",
            adapter_type="litellm",
            port=4000,
            pid=None,  # Adopted backend
            status="healthy",
        )
        registry = BackendRegistry(backends={"litellm-4000": instance})
        store.write(registry)

        pruned = store.prune_dead_pids()
        assert pruned == []

        loaded = store.read()
        assert "litellm-4000" in loaded.backends

    def test_list_backends_returns_sorted(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify list_backends returns backends sorted by created_at."""
        registry_path = tmp_path / "backends" / "index.json"
        registry_path.parent.mkdir(parents=True)
        store = BackendRegistryStore(registry_path)

        # Disable pruning for this test
        monkeypatch.setattr(store, "prune_dead_pids", lambda: [])

        instances = [
            BackendInstance(
                backend_id="litellm-4002",
                adapter_type="litellm",
                port=4002,
                created_at="2026-02-03T12:00:00Z",
            ),
            BackendInstance(
                backend_id="litellm-4000",
                adapter_type="litellm",
                port=4000,
                created_at="2026-02-03T10:00:00Z",
            ),
            BackendInstance(
                backend_id="litellm-4001",
                adapter_type="litellm",
                port=4001,
                created_at="2026-02-03T11:00:00Z",
            ),
        ]
        registry = BackendRegistry(backends={i.backend_id: i for i in instances})
        store.write(registry)

        backends = store.list_backends()
        assert [b.backend_id for b in backends] == [
            "litellm-4000",
            "litellm-4001",
            "litellm-4002",
        ]


class TestIsPidAlive:
    """Tests for is_pid_alive helper."""

    def test_zero_pid_returns_false(self) -> None:
        """Verify pid=0 returns False."""
        assert is_pid_alive(0) is False

    def test_negative_pid_returns_false(self) -> None:
        """Verify negative pid returns False."""
        assert is_pid_alive(-1) is False

    def test_nonexistent_pid_returns_false(self) -> None:
        """Verify nonexistent PID returns False."""
        # Use a very high PID that's unlikely to exist
        assert is_pid_alive(999999999) is False

    def test_current_process_returns_true(self) -> None:
        """Verify current process PID returns True."""
        import os

        assert is_pid_alive(os.getpid()) is True
