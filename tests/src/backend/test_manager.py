"""Tests for backend manager."""

from pathlib import Path

import pytest

from forge.backend import (
    BackendAdapter,
    BackendEnsureResult,
    BackendManager,
    BackendStartError,
)
from forge.backend.registry import (
    BackendInstance,
    BackendRegistry,
    BackendRegistryStore,
)


class MockAdapter(BackendAdapter):
    """Mock adapter for testing."""

    def __init__(self) -> None:
        self.start_called = False
        self.stop_called = False
        self.health_check_result = True

    def start(self, backend_id: str, config_path: Path, port: int) -> BackendInstance:
        self.start_called = True
        return BackendInstance(
            backend_id=backend_id,
            adapter_type="mock",
            port=port,
            pid=12345,
            status="healthy",
            created_at="2026-02-03T10:00:00Z",
        )

    def stop(self, instance: BackendInstance) -> None:
        self.stop_called = True

    def health_check(self, instance: BackendInstance) -> bool:
        return self.health_check_result


class TestBackendManager:
    """Tests for BackendManager."""

    def test_register_adapter(self, tmp_path: Path) -> None:
        """Verify adapter registration works."""
        store = BackendRegistryStore(tmp_path / "backends" / "index.json")
        manager = BackendManager(store)
        adapter = MockAdapter()

        manager.register_adapter("mock", adapter)

        assert "mock" in manager.adapters
        assert manager.adapters["mock"] is adapter

    def test_ensure_backend_starts_new(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify ensure_backend starts new backend when none exists."""
        monkeypatch.setenv("FORGE_HOME", str(tmp_path))

        # Create config file
        config_dir = tmp_path / "backends" / "mock"
        config_dir.mkdir(parents=True)
        (config_dir / "config.yaml").write_text("test: config")

        store = BackendRegistryStore(tmp_path / "backends" / "index.json")
        manager = BackendManager(store)
        adapter = MockAdapter()
        manager.register_adapter("mock", adapter)

        result = manager.ensure_backend("mock-4000", "mock", 4000)

        assert isinstance(result, BackendEnsureResult)
        assert result.source == "start"
        assert result.instance.backend_id == "mock-4000"
        assert adapter.start_called

        # Verify registered
        registry = store.read()
        assert "mock-4000" in registry.backends

    def test_ensure_backend_reuses_healthy(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify ensure_backend reuses existing healthy backend."""
        monkeypatch.setenv("FORGE_HOME", str(tmp_path))

        store = BackendRegistryStore(tmp_path / "backends" / "index.json")

        # Pre-register backend
        existing = BackendInstance(
            backend_id="mock-4000",
            adapter_type="mock",
            port=4000,
            pid=12345,
            status="healthy",
        )
        registry = BackendRegistry(backends={"mock-4000": existing})
        store.write(registry)

        manager = BackendManager(store)
        adapter = MockAdapter()
        adapter.health_check_result = True
        manager.register_adapter("mock", adapter)

        result = manager.ensure_backend("mock-4000", "mock", 4000)

        assert result.source == "reuse"
        assert result.instance.backend_id == "mock-4000"
        assert not adapter.start_called  # Should NOT have started

    def test_ensure_backend_restarts_dead(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify ensure_backend restarts dead backend."""
        monkeypatch.setenv("FORGE_HOME", str(tmp_path))

        # Create config file
        config_dir = tmp_path / "backends" / "mock"
        config_dir.mkdir(parents=True)
        (config_dir / "config.yaml").write_text("test: config")

        store = BackendRegistryStore(tmp_path / "backends" / "index.json")

        # Pre-register backend
        existing = BackendInstance(
            backend_id="mock-4000",
            adapter_type="mock",
            port=4000,
            pid=12345,
            status="healthy",
        )
        registry = BackendRegistry(backends={"mock-4000": existing})
        store.write(registry)

        manager = BackendManager(store)
        adapter = MockAdapter()
        adapter.health_check_result = False  # Backend is dead
        manager.register_adapter("mock", adapter)

        result = manager.ensure_backend("mock-4000", "mock", 4000)

        assert result.source == "start"
        assert adapter.start_called  # Should have restarted

    def test_ensure_backend_raises_for_missing_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify ensure_backend raises when config is missing."""
        monkeypatch.setenv("FORGE_HOME", str(tmp_path))

        store = BackendRegistryStore(tmp_path / "backends" / "index.json")
        manager = BackendManager(store)
        manager.register_adapter("mock", MockAdapter())

        with pytest.raises(BackendStartError) as exc_info:
            manager.ensure_backend("mock-4000", "mock", 4000)

        assert "config not found" in str(exc_info.value).lower()
        assert "forge backend create" in str(exc_info.value)

    def test_ensure_backend_raises_for_unknown_adapter(self, tmp_path: Path) -> None:
        """Verify ensure_backend raises for unknown adapter type."""
        store = BackendRegistryStore(tmp_path / "backends" / "index.json")
        manager = BackendManager(store)

        with pytest.raises(ValueError) as exc_info:
            manager.ensure_backend("unknown-4000", "unknown", 4000)

        assert "No adapter registered" in str(exc_info.value)

    def test_stop_backend_stops_and_unregisters(self, tmp_path: Path) -> None:
        """Verify stop_backend stops backend and removes from registry."""
        store = BackendRegistryStore(tmp_path / "backends" / "index.json")

        # Pre-register backend
        existing = BackendInstance(
            backend_id="mock-4000",
            adapter_type="mock",
            port=4000,
            pid=12345,
            status="healthy",
        )
        registry = BackendRegistry(backends={"mock-4000": existing})
        store.write(registry)

        manager = BackendManager(store)
        adapter = MockAdapter()
        manager.register_adapter("mock", adapter)

        manager.stop_backend("mock-4000")

        assert adapter.stop_called
        registry = store.read()
        assert "mock-4000" not in registry.backends

    def test_stop_backend_raises_for_unknown(self, tmp_path: Path) -> None:
        """Verify stop_backend raises for unknown backend."""
        store = BackendRegistryStore(tmp_path / "backends" / "index.json")
        manager = BackendManager(store)

        with pytest.raises(ValueError) as exc_info:
            manager.stop_backend("nonexistent")

        assert "not found" in str(exc_info.value).lower()


class TestBackendEnsureResult:
    """Tests for BackendEnsureResult dataclass."""

    def test_create_with_start_source(self) -> None:
        """Verify result can be created with start source."""
        instance = BackendInstance(
            backend_id="litellm-4000",
            adapter_type="litellm",
            port=4000,
        )
        result = BackendEnsureResult(instance=instance, source="start")

        assert result.instance is instance
        assert result.source == "start"

    def test_create_with_reuse_source(self) -> None:
        """Verify result can be created with reuse source."""
        instance = BackendInstance(
            backend_id="litellm-4000",
            adapter_type="litellm",
            port=4000,
        )
        result = BackendEnsureResult(instance=instance, source="reuse")

        assert result.source == "reuse"

    def test_is_frozen(self) -> None:
        """Verify result is immutable (frozen dataclass)."""
        instance = BackendInstance(
            backend_id="litellm-4000",
            adapter_type="litellm",
            port=4000,
        )
        result = BackendEnsureResult(instance=instance, source="start")

        with pytest.raises(AttributeError):
            result.source = "reuse"  # type: ignore
