"""Pytest fixtures for CLI session command tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner


@pytest.fixture
def runner() -> CliRunner:
    """Create a CLI runner."""
    return CliRunner()


@pytest.fixture
def temp_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Set up temporary environment for tests."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    # Widen Rich's console so long absolute paths don't wrap mid-string
    # (breaks substring assertions; macOS tmp paths are long).
    monkeypatch.setenv("COLUMNS", "500")

    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    (project / ".forge").mkdir()

    monkeypatch.chdir(project)

    return project
