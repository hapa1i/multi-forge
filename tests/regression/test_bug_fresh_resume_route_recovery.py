"""Regression: persisted-route recovery must retain the requested resume lifecycle."""

from __future__ import annotations

import shlex
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.core.ops.session_model_routing import SessionModelRoutingError
from forge.session import SessionManager, SessionStore
from tests.src.cli.session_command_support import mocked_model_route_proxy

pytestmark = pytest.mark.regression


def _prepare_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    (project / ".forge").mkdir()
    monkeypatch.chdir(project)
    monkeypatch.setenv("COLUMNS", "1000")
    return project


def _create_routed_session(runner: CliRunner, name: str) -> None:
    created = runner.invoke(
        main,
        [
            "session",
            "start",
            name,
            "--model",
            "gpt-5.6-sol",
            "--proxy",
            "openrouter-openai",
            "--no-launch",
        ],
    )
    assert created.exit_code == 0, created.output


def _recovery_command(result) -> list[str]:
    lines = result.stderr.splitlines()
    command_starts = [index for index, line in enumerate(lines) if line.strip().startswith("forge session resume")]
    assert len(command_starts) == 1, result.output
    return shlex.split(" ".join(line.strip() for line in lines[command_starts[0] :]))


@pytest.mark.parametrize(
    "failure_target",
    [
        "forge.cli.session_lifecycle.preserved_model_route_request",
        "forge.cli.session_lifecycle._plan_interactive_session_model_route",
        "forge.cli.session_lifecycle._realize_interactive_session_model_route",
    ],
    ids=["replay", "planning", "realization"],
)
def test_fresh_resume_route_failure_preserves_the_complete_explicit_action(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_target: str,
) -> None:
    project = _prepare_project(tmp_path, monkeypatch)
    runner = CliRunner()
    name = "parent-route"
    child_name = "chosen-child"

    with mocked_model_route_proxy(
        template="openrouter-openai",
        proxy_id="openrouter-openai-1",
        base_url="http://localhost:8096",
        default_tier="sonnet",
        tiers={"sonnet": "openai/gpt-5.6-sol"},
        alternatives={},
    ) as ensure_proxy:
        _create_routed_session(runner, name)
        store = SessionStore(str(project), name)
        before = store.manifest_path.read_bytes()
        ensure_proxy.reset_mock()

        with (
            patch(
                failure_target,
                side_effect=SessionModelRoutingError("stored route unavailable"),
            ),
            patch("forge.config.loader.template_exists", return_value=True),
            patch("forge.core.ops.claude_session.invoke_claude") as invoke_claude,
        ):
            result = runner.invoke(
                main,
                [
                    "session",
                    "resume",
                    name,
                    "--fresh",
                    "--child-name",
                    child_name,
                    "--strategy",
                    "full",
                    "--depth",
                    "all",
                    "--resume-mode",
                    "transfer",
                    "--review",
                    "--force",
                    "--memory",
                    "off",
                    "--authority",
                    "advisory",
                    "--authority-tier",
                    "named_tools",
                ],
            )

    assert result.exit_code == 1, result.output
    assert _recovery_command(result) == [
        "forge",
        "session",
        "resume",
        name,
        "--fresh",
        "--child-name",
        child_name,
        "--strategy",
        "full",
        "--depth",
        "all",
        "--resume-mode",
        "transfer",
        "--review",
        "--force",
        "--memory",
        "off",
        "--authority",
        "advisory",
        "--authority-tier",
        "named_tools",
        "--model",
        "gpt-5.6-sol",
        "--proxy",
        "openrouter-openai",
    ]
    invoke_claude.assert_not_called()
    ensure_proxy.assert_not_called()
    assert store.manifest_path.read_bytes() == before
    assert not SessionStore(str(project), child_name).exists()


def test_rewind_recovery_preserves_drop_last_but_omits_unsupplied_defaults(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_project(tmp_path, monkeypatch)
    runner = CliRunner()
    name = "rewind-parent"

    with mocked_model_route_proxy(
        template="openrouter-openai",
        proxy_id="openrouter-openai-1",
        base_url="http://localhost:8096",
        default_tier="sonnet",
        tiers={"sonnet": "openai/gpt-5.6-sol"},
        alternatives={},
    ):
        _create_routed_session(runner, name)
        before_names = {session_name for session_name, _entry in SessionManager().list_sessions()}
        with (
            patch(
                "forge.cli.session_lifecycle._plan_interactive_session_model_route",
                side_effect=SessionModelRoutingError("stored route unavailable"),
            ),
            patch("forge.config.loader.template_exists", return_value=True),
        ):
            result = runner.invoke(
                main,
                [
                    "session",
                    "resume",
                    name,
                    "--fresh",
                    "--strategy",
                    "rewind",
                    "--drop-last",
                    "2",
                ],
            )

    assert result.exit_code == 1, result.output
    command = _recovery_command(result)
    assert command == [
        "forge",
        "session",
        "resume",
        name,
        "--fresh",
        "--strategy",
        "rewind",
        "--drop-last",
        "2",
        "--model",
        "gpt-5.6-sol",
        "--proxy",
        "openrouter-openai",
    ]
    assert "--depth" not in command
    assert "--resume-mode" not in command
    assert {session_name for session_name, _entry in SessionManager().list_sessions()} == before_names


def test_bare_resume_keeps_the_existing_recovery_surface(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_project(tmp_path, monkeypatch)
    runner = CliRunner()
    name = "bare-parent"

    with mocked_model_route_proxy(
        template="openrouter-openai",
        proxy_id="openrouter-openai-1",
        base_url="http://localhost:8096",
        default_tier="sonnet",
        tiers={"sonnet": "openai/gpt-5.6-sol"},
        alternatives={},
    ):
        _create_routed_session(runner, name)
        with (
            patch(
                "forge.cli.session_lifecycle._plan_interactive_session_model_route",
                side_effect=SessionModelRoutingError("stored route unavailable"),
            ),
            patch("forge.config.loader.template_exists", return_value=False),
        ):
            result = runner.invoke(main, ["session", "resume", name])

    assert result.exit_code == 1, result.output
    assert "select a replacement with --model gpt-5.6-sol --proxy <proxy_id-or-template>" in result.stderr
    assert "rerun the intended action" not in result.stderr
