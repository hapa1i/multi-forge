"""Shared fixtures for install tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Generator

import pytest

from forge.install.models import (
    TRACKING_VERSION,
    Installation,
    InstalledFile,
    InstalledManifest,
    InstalledSettingsEntry,
)
from forge.install.tracking import TrackingStore


@pytest.fixture
def temp_forge_home(tmp_path: Path) -> Generator[Path, None, None]:
    """Create a temporary ~/.forge directory structure."""
    forge_home = tmp_path / ".forge"
    forge_home.mkdir()
    yield forge_home


@pytest.fixture
def temp_claude_home(tmp_path: Path) -> Generator[Path, None, None]:
    """Create a temporary ~/.claude directory structure."""
    claude_home = tmp_path / ".claude"
    claude_home.mkdir()
    yield claude_home


@pytest.fixture
def tracking_store(temp_forge_home: Path) -> TrackingStore:
    """Create a TrackingStore pointing to temp directory."""
    return TrackingStore(tracking_path=temp_forge_home / "installed.json")


@pytest.fixture
def sample_installation() -> Installation:
    """Create a sample Installation for testing."""
    return Installation(
        scope="user",
        mode="copy",
        profile="standard",
        modules_enabled=["commands", "agents", "hooks", "permissions"],
        files=[
            InstalledFile(
                target_path="/home/user/.claude/commands/test.md",
                source_path="/path/to/forge/src/commands/test.md",
                checksum="abc123",
                mode="copy",
                installed_at="2024-01-01T00:00:00+00:00",
            )
        ],
        settings_entries=[
            InstalledSettingsEntry(
                key_path="hooks.PreToolUse",
                value={"hooks": [{"command": "/path/to/hook"}]},
                merge_type="append",
                stable_id="/path/to/hook",
            ),
            InstalledSettingsEntry(
                key_path="permissions.allow",
                value="Bash(git:*)",
                merge_type="union",
                stable_id="Bash(git:*)",
            ),
        ],
        settings_backup_path="/home/user/.claude/settings.json.forge-backup",
        installed_at="2024-01-01T00:00:00+00:00",
        updated_at="2024-01-01T00:00:00+00:00",
    )


@pytest.fixture
def sample_manifest(sample_installation: Installation) -> InstalledManifest:
    """Create a sample InstalledManifest for testing (current version format)."""
    return InstalledManifest(
        version=TRACKING_VERSION,
        installations={"user": sample_installation},
    )


@pytest.fixture
def sample_settings() -> dict[str, Any]:
    """Create sample settings dict for testing."""
    return {
        "hooks": {
            "PreToolUse": [
                {
                    "hooks": [{"command": "/existing/hook", "type": "command"}],
                    "matcher": {"tool_name": "Bash"},
                }
            ]
        },
        "permissions": {
            "allow": ["Bash(ls:*)"],
            "deny": [],
        },
    }


@pytest.fixture
def forge_settings() -> dict[str, Any]:
    """Create Forge settings template for testing."""
    return {
        "hooks": {
            "PreToolUse": [
                {
                    "hooks": [{"command": "/forge/hook", "type": "command"}],
                    "matcher": {"tool_name": "Edit"},
                }
            ],
            "PostToolUse": [],
        },
        "permissions": {
            "allow": ["Bash(git:*)", "Read"],
        },
        "statusLine": "/path/to/status-line.sh",
    }


@pytest.fixture
def temp_source_dir(tmp_path: Path) -> Path:
    """Create a temporary source directory with extension files."""
    src = tmp_path / "src"
    src.mkdir()

    # Create commands
    commands = src / "commands"
    commands.mkdir()
    (commands / "test-cmd.md").write_text("# Test Command\n")
    (commands / "another.md").write_text("# Another Command\n")

    # Create agents
    agents = src / "agents"
    agents.mkdir()
    (agents / "test-agent.md").write_text("# Test Agent\n")

    return src
