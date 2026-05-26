"""CLI tests for `forge backend` recovery tips and exit codes.

Covers the §3 behavior change (create-on-existing is now a hard error) and the
not-found recovery tips on start/delete.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from forge.cli.main import main


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_create_existing_config_errors_with_tip(runner: CliRunner, tmp_path: Path) -> None:
    """create on an existing config is a hard error (exit 1) with a start tip."""
    cfg = tmp_path / "litellm" / "config.yaml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("model_list: []\n")

    with patch("forge.cli.backend.get_backend_config_path", return_value=cfg):
        result = runner.invoke(main, ["backend", "create", "litellm"])

    assert result.exit_code == 1
    assert "already exists" in result.output
    assert "Tip:" in result.output
    assert "forge backend start litellm" in result.output


def test_start_missing_config_errors_with_create_tip(runner: CliRunner, tmp_path: Path) -> None:
    missing = tmp_path / "litellm" / "config.yaml"

    with patch("forge.cli.backend.get_backend_config_path", return_value=missing):
        result = runner.invoke(main, ["backend", "start", "litellm", "--port", "4000"])

    assert result.exit_code == 1
    assert "not found" in result.output
    assert "Tip:" in result.output
    assert "forge backend create litellm" in result.output


def test_delete_missing_config_errors_with_create_tip(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # delete (no --port) checks get_forge_home()/backends/<adapter>; point it at an empty dir.
    monkeypatch.setattr("forge.cli.backend.get_forge_home", lambda: tmp_path)

    result = runner.invoke(main, ["backend", "delete", "litellm"])

    assert result.exit_code == 1
    assert "not found" in result.output
    assert "Tip:" in result.output
    assert "forge backend create litellm" in result.output
