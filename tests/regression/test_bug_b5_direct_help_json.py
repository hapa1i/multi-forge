"""B5 reused Click parsing must not leak eager help into hook stdout."""

import json

import pytest

from forge.cli.hooks import direct_commands
from tests.src.cli.test_native_supervisor import configure
from tests.src.cli.test_native_supervisor import native_setup as native_setup

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("args", [["--help"], ["set", "--help"], ["set", "--bad-option"], ["set", "--runtime"]])
def test_direct_help_and_parse_errors_emit_exactly_one_json_reply(native_setup, capsys, args):
    before = native_setup.manifest_path.read_bytes()
    direct_commands._handle_policy_supervisor(args)
    captured = capsys.readouterr()
    response = json.loads(captured.out)
    assert response["decision"] == "block" and response["reason"]
    if "--help" in args:
        assert "--source-runtime" in response["reason"] and "Usage:" in response["reason"]
        assert "--session" not in response["reason"]
    assert captured.err == ""
    assert native_setup.manifest_path.read_bytes() == before


@pytest.mark.parametrize("name", ["off", "on", "remove", "reload", "cascade"])
def test_direct_subcommand_help_describes_that_subcommand(native_setup, capsys, name):
    direct_commands._handle_policy_supervisor([name, "--help"])
    reason = json.loads(capsys.readouterr().out)["reason"]
    assert f"%policy supervisor {name}" in reason and "--source-runtime" not in reason
    assert "--session" not in reason and "--from" not in reason and "--checker-" not in reason
    if name == "reload":
        assert "reload [path]" in reason
    elif name == "cascade":
        assert "cascade on|off" in reason


@pytest.mark.parametrize("name", ["off", "on", "remove"])
@pytest.mark.parametrize("extra", [["--session", "other"], ["--session=other"], ["-s", "other"], ["unexpected"]])
def test_direct_lifecycle_rejects_extra_arguments_without_mutating(native_setup, capsys, monkeypatch, name, extra):
    assert configure().exit_code == 0
    before = native_setup.manifest_path.read_bytes()
    monkeypatch.setattr(
        direct_commands.policy_ops,
        f"supervisor_{name}",
        lambda **kwargs: pytest.fail("Invalid direct arguments reached a mutation"),
    )
    direct_commands._handle_policy_supervisor([name, *extra])
    captured = capsys.readouterr()
    reason = json.loads(captured.out)["reason"]
    assert f"Usage: %policy supervisor {name}" in reason
    assert captured.err == "" and native_setup.manifest_path.read_bytes() == before


def test_direct_help_does_not_remove_terminal_session_option(native_setup, capsys):
    from click.testing import CliRunner

    from forge.cli.main import main

    direct_commands._handle_policy_supervisor(["set", "--help"])
    capsys.readouterr()
    terminal = CliRunner().invoke(main, ["policy", "supervisor", "set", "--help"])
    assert terminal.exit_code == 0 and "--session" in terminal.output
