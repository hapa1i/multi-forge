"""Regression for Wave 6 CLI exit-code and diagnostic-stream failures."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import click
import pytest
from click.testing import CliRunner

import forge.cli.session as session_cli
import forge.cli.workflow as workflow_cli
from forge.cli.main import main
from forge.session.exceptions import AmbiguousSessionError

pytestmark = pytest.mark.regression


@click.command()
def _json_preflight_failure() -> None:
    workflow_cli._run_preflight([], as_json=True)


@click.command()
def _cross_project_failure() -> None:
    assert session_cli._hint_cross_project_session("demo", "/current/project") is True
    raise click.exceptions.Exit(1)


def test_bare_root_group_uses_click_no_args_help_contract() -> None:
    result = CliRunner().invoke(main, [])

    assert result.exit_code == 2
    assert result.stdout == ""
    assert "Usage:" in result.stderr


def test_explicit_root_help_remains_successful() -> None:
    result = CliRunner().invoke(main, ["--help"])

    assert result.exit_code == 0
    assert "Usage:" in result.stdout
    assert result.stderr == ""


def test_selectorless_human_session_show_fails_on_stderr() -> None:
    result = CliRunner().invoke(main, ["session", "show"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "No session specified" in result.stderr


def test_selectorless_json_session_show_keeps_ambient_success_shape() -> None:
    result = CliRunner().invoke(main, ["session", "show", "--json"])

    assert result.exit_code == 0
    assert json.loads(result.stdout)["session_name"] == "(unknown)"
    assert result.stderr == ""


def test_json_workflow_preflight_failure_is_stderr_only() -> None:
    with patch("forge.review.engine.preflight_check", return_value=["missing runtime"]):
        result = CliRunner().invoke(_json_preflight_failure)

    assert result.exit_code == 1
    assert result.stdout == ""
    assert json.loads(result.stderr) == {"preflight_errors": ["missing runtime"]}


@pytest.mark.parametrize("ambiguous", [False, True], ids=["unique", "ambiguous"])
def test_cross_project_failure_is_entirely_on_stderr(ambiguous: bool) -> None:
    class IndexStore:
        def get_session(self, *_args: object, **_kwargs: object) -> object:
            if ambiguous:
                raise AmbiguousSessionError("demo", ["/other/one", "/other/two"])
            return SimpleNamespace(forge_root="/other/project", worktree_path="/other/project")

    with patch("forge.session.IndexStore", return_value=IndexStore()):
        result = CliRunner().invoke(_cross_project_failure)

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "not found in current project" in result.stderr
    assert "Run the command from" in result.stderr
