"""Regression for D032: status-line must fail open at its input boundary."""

from __future__ import annotations

import json
from collections.abc import Iterator
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from forge.cli.status_line import status_line
from forge.runtime_config import reset_runtime_config

pytestmark = pytest.mark.regression


@pytest.fixture(autouse=True)
def _reset_runtime_config() -> Iterator[None]:
    reset_runtime_config()
    yield
    reset_runtime_config()


@pytest.mark.parametrize("payload", ["null", "42", "true", "[]", '"text"'])
def test_non_object_json_is_a_bounded_status_error(payload: str) -> None:
    result = CliRunner().invoke(status_line, input=payload)

    assert result.exit_code == 0
    assert result.exception is None
    assert "[Error: Invalid input]" in result.stdout


@pytest.mark.parametrize("workspace", [None, "bad", 42, []])
def test_wrong_typed_workspace_falls_back_to_missing_workspace(workspace: object) -> None:
    with (
        patch("forge.cli.status_line.detect_proxy", return_value=(False, None, False)),
        patch("forge.cli.status_line.discover_session", return_value=(None, False)),
        patch("forge.cli.status_line.get_git_branch", return_value=None),
    ):
        result = CliRunner().invoke(
            status_line,
            input=json.dumps({"workspace": workspace}),
            env={"FORGE_STATUS_TRUNCATE": "0"},
        )

    assert result.exit_code == 0
    assert result.exception is None
    assert result.stdout.strip()


def test_malformed_proxy_url_falls_back_without_a_traceback() -> None:
    result = CliRunner().invoke(
        status_line,
        input="{}",
        env={"ANTHROPIC_BASE_URL": "http://[", "FORGE_STATUS_TRUNCATE": "0"},
    )

    assert result.exit_code == 0
    assert result.exception is None
    assert result.stdout.strip()


def test_valid_empty_object_still_renders() -> None:
    with (
        patch("forge.cli.status_line.detect_proxy", return_value=(False, None, False)),
        patch("forge.cli.status_line.discover_session", return_value=(None, False)),
        patch("forge.cli.status_line.get_git_branch", return_value=None),
    ):
        result = CliRunner().invoke(status_line, input="{}", env={"FORGE_STATUS_TRUNCATE": "0"})

    assert result.exit_code == 0
    assert result.exception is None
    assert result.stdout.strip()
