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


def _recovery_command_line(result) -> str:
    """Return the single line carrying the recovery command.

    Deliberately does not join continuation lines: a wrapped command is not
    copy-pasteable, so re-joining here would hide exactly the defect the
    narrow-terminal test below pins.
    """
    lines = [line.strip() for line in result.stderr.splitlines()]
    commands = [line for line in lines if line.startswith("forge session resume")]
    assert len(commands) == 1, result.output
    return commands[0]


def _recovery_command(result) -> list[str]:
    return shlex.split(_recovery_command_line(result))


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


def test_recovery_command_is_not_wrapped_by_the_error_console(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A wrapped command is not copy-pasteable: each fragment runs as its own command.

    ``err_console`` is a fixed-width console, so the wrap threshold is its own
    width rather than the user's terminal -- setting COLUMNS does not move it.
    A fully-specified fresh resume exceeds that width.
    """
    from forge.cli.output import err_console

    _prepare_project(tmp_path, monkeypatch)
    runner = CliRunner()
    name = "narrow-parent"
    child_name = "chosen-child"

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
            patch("forge.config.loader.template_exists", return_value=True),
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
    command = _recovery_command_line(result)
    assert len(command) > err_console.width  # the command really does exceed the wrap point
    assert command.endswith("--proxy openrouter-openai")
    assert shlex.split(command)[:4] == ["forge", "session", "resume", name]


def test_explicitness_is_stated_by_the_producer_not_inferred_from_argv() -> None:
    """A caller action that serializes like the default must still count as explicit."""
    from forge.cli.session_route_recovery import SessionRouteRecoveryAction

    bare = SessionRouteRecoveryAction.resume("s")
    assert bare.has_explicit_options is False
    assert SessionRouteRecoveryAction.resume("s", fresh=True).has_explicit_options is True

    # A future caller whose route-neutral action happens to match the bare resume
    # argv is still a supplied action; argv equality cannot tell the two apart.
    colliding = SessionRouteRecoveryAction(bare.argv, has_explicit_options=True)
    assert colliding.argv == bare.argv
    assert colliding.has_explicit_options is True


def test_explicit_action_that_matches_bare_resume_keeps_intended_action_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Producer provenance, not argv equality, selects the recovery wording."""
    from forge.cli.session_route_recovery import (
        SessionRouteRecoveryAction,
        _render_persisted_proxy_refusal,
    )

    project = _prepare_project(tmp_path, monkeypatch)
    runner = CliRunner()
    name = "colliding-action"

    with mocked_model_route_proxy(
        template="openrouter-openai",
        proxy_id="openrouter-openai-1",
        base_url="http://localhost:8096",
        default_tier="sonnet",
        tiers={"sonnet": "openai/gpt-5.6-sol"},
        alternatives={},
    ):
        _create_routed_session(runner, name)

    manifest = SessionStore(str(project), name).read()
    bare = SessionRouteRecoveryAction.resume(name)
    colliding = SessionRouteRecoveryAction(bare.argv, has_explicit_options=True)
    with (
        patch("forge.config.loader.template_exists", return_value=False),
        patch("forge.cli.session_route_recovery.print_error_with_tip") as print_refusal,
    ):
        _render_persisted_proxy_refusal(
            manifest=manifest,
            error=SessionModelRoutingError("stored route unavailable"),
            template="openrouter-openai",
            base_url=None,
            proxy_id=None,
            allow_restart=False,
            recovery_action=colliding,
        )

    rendered = "\n".join(str(value) for value in print_refusal.call_args.args)
    assert "rerun the intended action" in rendered
    assert "forge session resume colliding-action --model gpt-5.6-sol --proxy" in rendered
