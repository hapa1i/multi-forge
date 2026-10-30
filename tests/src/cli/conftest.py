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
def wide_session_console(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make content assertions independent of COLUMNS at console import time."""
    from forge.cli.output import console

    # Restore the original explicit width, including None; the public getter computes a fallback.
    monkeypatch.setattr(console, "_width", 500)


@pytest.fixture
def temp_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, wide_session_console: None) -> Path:
    """Set up temporary environment for tests."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    # Also widen consoles constructed inside the command.
    monkeypatch.setenv("COLUMNS", "500")

    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    (project / ".forge").mkdir()

    monkeypatch.chdir(project)

    return project
