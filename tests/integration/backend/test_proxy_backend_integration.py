"""Integration tests for proxy-backend interaction.

These tests verify that proxy commands correctly interact with
the backend management system.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from forge.cli.main import main

pytestmark = pytest.mark.integration


@pytest.fixture
def isolated_forge_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create an isolated FORGE_HOME for testing."""
    forge_home = tmp_path / ".forge"
    forge_home.mkdir()
    monkeypatch.setenv("FORGE_HOME", str(forge_home))
    # Also set GEMINI_API_KEY to avoid env var validation errors
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-for-integration-test")
    return forge_home


class TestProxyCreateNoStart:
    """Tests for proxy create --no-start behavior."""

    def test_no_start_does_not_create_backend_config(self, isolated_forge_home: Path) -> None:
        """Verify --no-start does NOT auto-create backend config.

        Backend management only happens during start_proxy(), not during
        config-only creation with --no-start.
        """
        runner = CliRunner()

        # Create proxy with --no-start
        result = runner.invoke(main, ["proxy", "create", "litellm-gemini-local", "--no-start"])

        # Proxy config should be created (exit 0)
        assert result.exit_code == 0, f"Failed: {result.output}"

        # But backend config should NOT be created
        backend_config = isolated_forge_home / "backends" / "litellm" / "config.yaml"
        assert not backend_config.exists(), "Backend config should NOT be created with --no-start"

        # And no backend registry entry
        backend_registry = isolated_forge_home / "backends" / "index.json"
        assert not backend_registry.exists(), "Backend registry should NOT be created with --no-start"

    def test_no_start_creates_proxy_config(self, isolated_forge_home: Path) -> None:
        """Verify --no-start still creates proxy config file."""
        runner = CliRunner()

        result = runner.invoke(main, ["proxy", "create", "litellm-gemini-local", "--no-start"])

        assert result.exit_code == 0

        # Proxy registry should exist
        proxy_registry = isolated_forge_home / "proxies" / "index.json"
        assert proxy_registry.exists()


class TestProxyListShowsBackends:
    """Tests for proxy list showing backend status."""

    def test_proxy_list_shows_backends_section(self, isolated_forge_home: Path) -> None:
        """Verify proxy list shows backends when they exist."""
        from forge.backend.registry import (
            BackendInstance,
            BackendRegistry,
            BackendRegistryStore,
        )

        # Manually register a backend
        store = BackendRegistryStore()
        instance = BackendInstance(
            backend_id="litellm-4000",
            adapter_type="litellm",
            port=4000,
            pid=None,
            status="healthy",
        )

        def add_backend(reg: BackendRegistry) -> None:
            reg.backends["litellm-4000"] = instance

        store.update(timeout_s=5.0, mutate=add_backend)

        # Create a proxy to list
        runner = CliRunner()
        runner.invoke(main, ["proxy", "create", "litellm-gemini-local", "--no-start"])

        # List should show backends
        result = runner.invoke(main, ["proxy", "list"])

        assert result.exit_code == 0
        assert "Backends:" in result.output
        assert "litellm-4000" in result.output
