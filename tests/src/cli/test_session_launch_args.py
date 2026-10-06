"""Tests for launch-only ``--effort`` and ``--`` runtime passthrough on session verbs.

The launchers and ops are mocked; these assertions target Click parsing, the
pre-mutation refusals, the recovery commands, and the launch-time clamp warning.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.cli.session_fork import _fork_model_route_recovery_action
from forge.cli.session_launch_args import warn_if_effort_clamped
from forge.cli.session_route_recovery import SessionRouteRecoveryAction
from forge.core.models.model_routes import normalize_model_route_request
from forge.core.ops.session_fork_preflight import ForkPreflightRequest
from forge.core.ops.session_model_routing import ResolvedModelRoute
from forge.core.runtime.launch_args import RuntimeLaunchArgs
from forge.session.models import AuthorityIntent, SessionState, create_session_state


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("COLUMNS", "500")
    monkeypatch.delenv("FORGE_SESSION", raising=False)
    proj = tmp_path / "project"
    (proj / ".git").mkdir(parents=True)
    (proj / ".forge").mkdir()
    monkeypatch.chdir(proj)
    return proj


def _start(runner: CliRunner, args: list[str]) -> tuple[Any, MagicMock]:
    with (
        patch("forge.cli.guards.require_repo_root"),
        patch("forge.cli.session_lifecycle.launch_new_session", return_value=0) as launch,
    ):
        result = runner.invoke(main, ["session", "start", *args])
    return result, launch


class TestStartParsing:
    def test_passthrough_never_binds_the_optional_name(self, runner: CliRunner, project: Path) -> None:
        result, launch = _start(runner, ["--", "--debug"])

        assert result.exit_code == 0, result.output
        kwargs = launch.call_args.kwargs
        assert kwargs["name"] != "--debug"
        assert kwargs["launch_args"] == RuntimeLaunchArgs(passthrough=("--debug",))

    def test_effort_and_passthrough_reach_the_launcher(self, runner: CliRunner, project: Path) -> None:
        result, launch = _start(runner, ["feat", "--effort", "high", "--", "--debug", "--add-dir", "/tmp/x"])

        assert result.exit_code == 0, result.output
        assert launch.call_args.kwargs["name"] == "feat"
        assert launch.call_args.kwargs["launch_args"] == RuntimeLaunchArgs(
            effort="high", passthrough=("--debug", "--add-dir", "/tmp/x")
        )

    def test_tokens_after_the_separator_are_not_forge_options(self, runner: CliRunner, project: Path) -> None:
        # `--proxy` after `--` belongs to Claude, so Forge stays on its default route.
        result, launch = _start(runner, ["feat", "--", "--proxy-like"])

        assert result.exit_code == 0, result.output
        assert launch.call_args.kwargs["template"] is None
        assert launch.call_args.kwargs["launch_args"].passthrough == ("--proxy-like",)

    def test_usage_shows_runtime_args(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["session", "start", "--help"])

        assert "[-- RUNTIME_ARGS]..." in result.output
        assert "--effort" in result.output


class TestStartRefusals:
    @pytest.mark.parametrize(
        ("args", "message"),
        [
            (["feat", "--", "--model", "opus"], "Claude flag '--model' is managed by Forge"),
            (["feat", "--", "--resume=abc"], "Claude flag '--resume' is managed by Forge"),
            (["feat", "--effort", "none"], "--effort for Claude sessions must be one of"),
            (["feat", "--no-launch", "--effort", "high"], "apply only to a launch"),
            (["feat", "--authority", "advisory", "--", "--verbose"], "advisory-authority launches"),
        ],
    )
    def test_refused_before_launch(self, runner: CliRunner, project: Path, args: list[str], message: str) -> None:
        result, launch = _start(runner, args)

        assert result.exit_code == 1
        assert message in result.output
        launch.assert_not_called()

    def test_advisory_launch_keeps_effort(self, runner: CliRunner, project: Path) -> None:
        result, launch = _start(runner, ["feat", "--authority", "advisory", "--effort", "max"])

        assert result.exit_code == 0, result.output
        assert launch.call_args.kwargs["launch_args"] == RuntimeLaunchArgs(effort="max")


def _claude_manifest(tmp_path: Path, *, authority: AuthorityIntent | None) -> SessionState:
    state = create_session_state("planner", worktree_path=str(tmp_path), authority=authority)
    state.forge_root = str(tmp_path)
    return state


class TestResumeRefusals:
    def _resume(self, runner: CliRunner, manifest: SessionState, args: list[str]) -> tuple[Any, MagicMock]:
        with (
            patch("forge.cli.session_lifecycle.SessionManager") as manager_cls,
            patch("forge.cli.guards.enforce_target_project_compatibility"),
        ):
            manager_cls.return_value.get_session.return_value = manifest
            result = runner.invoke(main, ["session", "resume", "planner", *args])
        return result, manager_cls.return_value

    def test_in_place_advisory_session_refuses_passthrough(
        self, runner: CliRunner, project: Path, tmp_path: Path
    ) -> None:
        manifest = _claude_manifest(tmp_path, authority=AuthorityIntent("advisory"))

        result, manager = self._resume(runner, manifest, ["--", "--verbose"])

        assert result.exit_code == 1
        assert "advisory-authority launches" in result.output
        manager.switch_session.assert_not_called()
        manager.relaunch_session.assert_not_called()

    def test_fresh_child_inherits_advisory_refusal_before_creation(
        self, runner: CliRunner, project: Path, tmp_path: Path
    ) -> None:
        manifest = _claude_manifest(tmp_path, authority=AuthorityIntent("advisory"))

        result, manager = self._resume(runner, manifest, ["--fresh", "--", "--verbose"])

        assert result.exit_code == 1
        assert "advisory-authority launches" in result.output
        manager.resume_session.assert_not_called()

    def test_reserved_flag_refused_before_any_mode_runs(self, runner: CliRunner, project: Path, tmp_path: Path) -> None:
        manifest = _claude_manifest(tmp_path, authority=None)

        result, manager = self._resume(runner, manifest, ["--", "--fork-session"])

        assert result.exit_code == 1
        assert "'--fork-session' is managed by Forge" in result.output
        manager.switch_session.assert_not_called()
        manager.relaunch_session.assert_not_called()


class TestForkRefusals:
    def _fork(self, runner: CliRunner, parent: SessionState, args: list[str]) -> tuple[Any, MagicMock]:
        preflight = SimpleNamespace(parent=parent, notices=(), fork_name="child")
        with (
            patch("forge.cli.session_fork.plan_session_fork", return_value=preflight),
            patch("forge.cli.session_fork.execute_session_fork") as execute,
        ):
            result = runner.invoke(main, ["session", "fork", "planner", *args])
        return result, execute

    def test_fork_inherits_advisory_refusal_before_execution(
        self, runner: CliRunner, project: Path, tmp_path: Path
    ) -> None:
        parent = _claude_manifest(tmp_path, authority=AuthorityIntent("advisory"))

        result, execute = self._fork(runner, parent, ["--", "--verbose"])

        assert result.exit_code == 1
        assert "advisory-authority launches" in result.output
        execute.assert_not_called()

    def test_explicit_producer_authority_allows_passthrough_past_validation(
        self, runner: CliRunner, project: Path, tmp_path: Path
    ) -> None:
        parent = _claude_manifest(tmp_path, authority=AuthorityIntent("advisory"))

        with patch("forge.cli.session_fork.preflight_host_claude_binary", side_effect=SystemExit(7)):
            result, execute = self._fork(runner, parent, ["--authority", "producer", "--", "--verbose"])

        # The next step after launch-arg validation ran, so validation accepted the args.
        assert result.exit_code == 7
        execute.assert_not_called()

    def test_no_launch_refuses_launch_args(self, runner: CliRunner, project: Path, tmp_path: Path) -> None:
        parent = _claude_manifest(tmp_path, authority=None)

        result, execute = self._fork(runner, parent, ["--no-launch", "--effort", "low"])

        assert result.exit_code == 1
        assert "apply only to a launch" in result.output
        execute.assert_not_called()


class TestRecoveryCommands:
    def test_resume_reroute_emits_passthrough_after_every_forge_option(self) -> None:
        action = SessionRouteRecoveryAction.resume(
            "planner",
            fresh=True,
            launch_args=RuntimeLaunchArgs(effort="high", passthrough=("--add-dir", "/tmp/a b")),
        )

        assert action.has_explicit_options
        assert action.with_proxy("openrouter-openai") == (
            "forge session resume planner --fresh --effort high --proxy openrouter-openai -- --add-dir '/tmp/a b'"
        )
        assert action.with_proxy_route(model="gpt-6-astra", model_tier="opus", proxy="p") == (
            "forge session resume planner --fresh --effort high --model gpt-6-astra --model-tier opus --proxy p "
            "-- --add-dir '/tmp/a b'"
        )

    def test_passthrough_alone_counts_as_an_explicit_option(self) -> None:
        action = SessionRouteRecoveryAction.resume("planner", launch_args=RuntimeLaunchArgs(passthrough=("--debug",)))

        assert action.has_explicit_options
        assert action.with_proxy("p") == "forge session resume planner --proxy p -- --debug"

    def test_bare_resume_action_is_unchanged(self) -> None:
        action = SessionRouteRecoveryAction.resume("planner")

        assert not action.has_explicit_options
        assert action.with_proxy("p") == "forge session resume planner --proxy p"

    def test_fork_reroute_keeps_launch_args(self) -> None:
        request = ForkPreflightRequest(parent_name="planner", fork_name=None, cwd=Path("."), forge_root=None)
        action = _fork_model_route_recovery_action(
            request,
            fork_name="child",
            launch_args=RuntimeLaunchArgs(effort="max", passthrough=("--debug",)),
        )

        assert action.with_proxy("p") == "forge session fork planner --name child --effort max --proxy p -- --debug"


def _route(selected_model: str, template: str) -> ResolvedModelRoute:
    return ResolvedModelRoute(
        request=normalize_model_route_request(selected_model.split("/")[-1]),
        kind="proxy",
        selected_tier="opus",
        proxy_template=template,
        proxy_base_url="http://127.0.0.1:65530",
        selected_model=selected_model,
    )


class TestClampWarning:
    def test_warns_when_translated_model_cannot_express_effort(self, capsys: pytest.CaptureFixture[str]) -> None:
        warn_if_effort_clamped(
            RuntimeLaunchArgs(effort="max"), _route("google/gemini-3.7-flash", "openrouter-gemini-flash")
        )

        captured = capsys.readouterr()
        assert captured.out == ""
        out = " ".join(captured.err.split())  # Rich wraps at the test console width
        assert "google/gemini-3.7-flash supports effort low, medium, high" in out
        assert "--effort max will run as high" in out

    def test_silent_when_model_supports_effort(self, capsys: pytest.CaptureFixture[str]) -> None:
        warn_if_effort_clamped(RuntimeLaunchArgs(effort="max"), _route("openai/gpt-6-astra", "openrouter-openai"))

        assert capsys.readouterr().out == ""

    def test_silent_without_effort_or_route(self, capsys: pytest.CaptureFixture[str]) -> None:
        warn_if_effort_clamped(RuntimeLaunchArgs(passthrough=("--debug",)), None)
        warn_if_effort_clamped(RuntimeLaunchArgs(effort="max"), None)

        assert capsys.readouterr().out == ""
