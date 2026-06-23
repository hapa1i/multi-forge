"""Routing tests for the `forge telemetry` namespace."""

from __future__ import annotations

import json

from click.testing import CliRunner

from forge.cli.hooks._group import hooks
from forge.cli.main import main


def test_telemetry_group_lists_moved_surfaces() -> None:
    result = CliRunner().invoke(main, ["telemetry", "--help"])

    assert result.exit_code == 0
    assert "activity" in result.output
    assert "trace" in result.output
    assert "costs" in result.output


def test_old_terminal_paths_are_clean_breaks() -> None:
    runner = CliRunner()

    for args, missing in (
        (["activity"], "activity"),
        (["provider", "trace"], "provider"),
        (["proxy", "costs"], "costs"),
    ):
        result = runner.invoke(main, args)
        assert result.exit_code == 2
        assert f"No such command '{missing}'" in result.output


def test_root_and_proxy_help_do_not_list_old_surfaces() -> None:
    root = CliRunner().invoke(main, ["--help"])
    assert root.exit_code == 0
    assert "\n  activity " not in root.output
    assert "\n  provider " not in root.output

    proxy = CliRunner().invoke(main, ["proxy", "--help"])
    assert proxy.exit_code == 0
    assert "\n  costs " not in proxy.output


def test_direct_command_help_no_longer_advertises_provider_trace() -> None:
    result = CliRunner().invoke(hooks, ["user-prompt-submit"], input=json.dumps({"prompt": "%help"}))

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert "%provider trace" not in payload["reason"]


def test_provider_trace_direct_command_is_retired() -> None:
    result = CliRunner().invoke(hooks, ["user-prompt-submit"], input=json.dumps({"prompt": "%provider trace list"}))

    assert result.exit_code == 0
    assert result.output == ""
