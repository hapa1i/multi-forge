"""Integration tests for backend CLI commands.

These tests verify the forge model backend CLI works end-to-end.
They don't require actual LiteLLM to be running - they test
the config management and registry operations.
"""

import json
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
    return forge_home


class TestBackendCLI:
    """Integration tests for forge model backend commands."""

    def test_backend_list_empty(self, isolated_forge_home: Path) -> None:
        """Verify backend list shows built-in backends when no local backend is running."""
        runner = CliRunner()
        result = runner.invoke(main, ["model", "backend", "list"])

        assert result.exit_code == 0
        assert "Forge Model Backends" in result.output
        assert "openrouter" in result.output
        assert "litellm-remote" in result.output
        assert "No backends found" not in result.output

    def test_backend_create_copies_config(self, isolated_forge_home: Path) -> None:
        """Verify backend create copies config to correct location."""
        runner = CliRunner()
        result = runner.invoke(main, ["model", "backend", "create", "litellm"])

        assert result.exit_code == 0
        assert "Created" in result.output

        # Verify config was created
        config_path = isolated_forge_home / "backends" / "litellm" / "config.yaml"
        assert config_path.exists()

        # Verify content looks like LiteLLM config
        content = config_path.read_text()
        assert "model_list:" in content

    def test_backend_create_already_exists(self, isolated_forge_home: Path) -> None:
        """Verify backend create errors on duplicate with a recovery tip."""
        runner = CliRunner()

        # First create
        result1 = runner.invoke(main, ["model", "backend", "create", "litellm"])
        assert result1.exit_code == 0

        # Second create - should error with tip to start instead
        result2 = runner.invoke(main, ["model", "backend", "create", "litellm"])
        assert result2.exit_code == 1
        assert "already exists" in result2.output
        assert "forge model backend start" in result2.output

    def test_backend_delete_removes_config(self, isolated_forge_home: Path) -> None:
        """Verify backend delete removes config directory."""
        runner = CliRunner()

        # Create first
        runner.invoke(main, ["model", "backend", "create", "litellm"])
        config_dir = isolated_forge_home / "backends" / "litellm"
        assert config_dir.exists()

        # Delete with --yes to skip confirmation
        result = runner.invoke(main, ["model", "backend", "delete", "litellm", "--yes"])
        assert result.exit_code == 0
        assert "Deleted" in result.output
        assert not config_dir.exists()

    def test_backend_delete_nonexistent_errors(self, isolated_forge_home: Path) -> None:
        """Verify backend delete errors for nonexistent backend."""
        runner = CliRunner()
        result = runner.invoke(main, ["model", "backend", "delete", "litellm", "--yes"])

        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_backend_start_requires_config(self, isolated_forge_home: Path) -> None:
        """Verify backend start fails without config."""
        runner = CliRunner()
        result = runner.invoke(main, ["model", "backend", "start", "litellm", "--port", "4000"])

        assert result.exit_code == 1
        assert "config not found" in result.output.lower() or "create it first" in result.output.lower()


class TestBackendRegistry:
    """Integration tests for backend registry persistence."""

    def test_registry_persists_across_commands(
        self, isolated_forge_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify registry state persists across CLI invocations."""
        from forge.backend.registry import (
            BackendInstance,
            BackendRegistry,
            BackendRegistryStore,
        )

        # Manually add a backend to registry (simulating a running backend)
        store = BackendRegistryStore()
        instance = BackendInstance(
            backend_id="litellm-4000",
            adapter_type="litellm",
            port=4000,
            pid=None,  # No PID - won't be pruned
            status="healthy",
            created_at="2026-02-03T10:00:00Z",
        )

        def add_backend(reg: BackendRegistry) -> None:
            reg.backends["litellm-4000"] = instance

        store.update(timeout_s=5.0, mutate=add_backend)

        # Now list should show the backend
        runner = CliRunner()
        result = runner.invoke(main, ["model", "backend", "list"])

        assert result.exit_code == 0
        assert "Unmatched Backend Instances" in result.output
        assert "litellm-4000" in result.output
        assert "4000" in result.output

    def test_registry_file_format(self, isolated_forge_home: Path) -> None:
        """Verify registry file has correct JSON structure."""
        from forge.backend.registry import (
            BackendInstance,
            BackendRegistry,
            BackendRegistryStore,
        )

        store = BackendRegistryStore()
        instance = BackendInstance(
            backend_id="litellm-4000",
            adapter_type="litellm",
            port=4000,
            status="healthy",
        )
        registry = BackendRegistry(backends={"litellm-4000": instance})
        store.write(registry)

        # Read raw JSON
        registry_path = isolated_forge_home / "backends" / "index.json"
        data = json.loads(registry_path.read_text())

        assert data["version"] == 1
        assert "litellm-4000" in data["backends"]
        assert data["backends"]["litellm-4000"]["port"] == 4000
