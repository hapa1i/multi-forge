"""Focused CLI tests for session model pin behavior."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

import forge.cli.session as session_cli
from forge.cli.main import main
from forge.session import SessionStore, create_session_state


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
    monkeypatch.setenv("COLUMNS", "500")

    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    (project / ".forge").mkdir()
    monkeypatch.chdir(project)

    return project


def _anthropic_proxy_cfg():
    from forge.config.schema import ProxyInstanceConfig, TierModels

    return ProxyInstanceConfig(
        proxy_format=1,
        template="openrouter-anthropic",
        template_digest="abc",
        provider="openrouter",
        proxy_endpoint="http://localhost:8095",
        port=8095,
        upstream_base_url="https://openrouter.ai/api/v1",
        tiers=TierModels(haiku="h", sonnet="s", opus="anthropic/claude-opus-4.6"),
        model_alternatives={"opus": {"claude-opus-4-7": "anthropic/claude-opus-4.7"}},
    )


def _anthropic_routing() -> session_cli.ResolvedRouting:
    return session_cli.ResolvedRouting(
        template="openrouter-anthropic",
        base_url="http://localhost:8095",
        proxy_id="test-or-proxy",
    )


def test_persist_direct_model_override_warns_on_lock_failure(
    temp_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A failed --model manifest write should be visible instead of silently lost."""
    from forge.cli import session_lifecycle
    from forge.core.state import FileLockTimeoutError

    state = create_session_state("persist-warning", worktree_path=str(temp_env))
    SessionStore(str(temp_env), "persist-warning").write(state)

    with patch(
        "forge.cli.session_lifecycle.SessionStore.update",
        side_effect=FileLockTimeoutError(lock_path=temp_env / "forge.session.json.lock", timeout_s=5.0),
    ):
        session_lifecycle._persist_direct_model_override(
            forge_root=temp_env,
            session_name="persist-warning",
            direct_model="claude-opus-4-6",
        )

    output = capsys.readouterr().out
    assert "Could not persist --model override" in output
    assert "future resumes may use the previous stored model" in output


def test_incognito_with_model(runner: CliRunner, temp_env: Path) -> None:
    """The incognito shortcut should expose the same --model pin as session start."""
    with patch("forge.cli.session.invoke_claude", return_value=0) as mock_invoke:
        result = runner.invoke(main, ["session", "incognito", "incog-model", "--model", "sonnet-4-6"])

    assert result.exit_code == 0, result.output
    kwargs = mock_invoke.call_args.kwargs
    assert kwargs["model"] is None
    assert kwargs["env_vars"]["ANTHROPIC_MODEL"] == "sonnet"
    assert kwargs["env_vars"]["ANTHROPIC_DEFAULT_SONNET_MODEL"] == "claude-sonnet-4-6"


def test_fork_with_model_overrides_persisted_model_pin(runner: CliRunner, temp_env: Path) -> None:
    """--model on fork should let a child switch Claude versions immediately."""
    runner.invoke(main, ["session", "start", "planner", "--model", "claude-opus-4.7", "--no-launch"])
    store = SessionStore(str(temp_env), "planner")
    store.update(timeout_s=5.0, mutate=lambda m: setattr(m.confirmed, "claude_session_id", "parent-uuid"))

    with patch("forge.cli.session.invoke_claude", return_value=0) as mock_invoke:
        result = runner.invoke(
            main,
            ["session", "fork", "planner", "--name", "executor", "--model", "claude-opus-4.6"],
        )

    assert result.exit_code == 0, result.output
    kwargs = mock_invoke.call_args.kwargs
    assert kwargs["model"] is None
    assert kwargs["env_vars"]["ANTHROPIC_MODEL"] == "opus"
    assert kwargs["env_vars"]["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "claude-opus-4-6"

    state = SessionStore(str(temp_env), "executor").read()
    assert state.intent.launch is not None
    assert state.intent.launch.direct_model == "claude-opus-4-6"


def test_fork_with_proxy_model_allows_proxy_default_tier(runner: CliRunner, temp_env: Path) -> None:
    """--model on proxy fork should support the proxy tier default, not only alternatives."""
    runner.invoke(main, ["session", "start", "proxy-planner", "--model", "claude-opus-4.7", "--no-launch"])
    store = SessionStore(str(temp_env), "proxy-planner")
    store.update(timeout_s=5.0, mutate=lambda m: setattr(m.confirmed, "claude_session_id", "parent-uuid"))

    with (
        patch("forge.cli.session._resolve_routing_from_cli", return_value=_anthropic_routing()),
        patch("forge.config.loader.load_proxy_instance_config", return_value=_anthropic_proxy_cfg()),
        patch("forge.cli.session.invoke_claude", return_value=0) as mock_invoke,
    ):
        result = runner.invoke(
            main,
            [
                "session",
                "fork",
                "proxy-planner",
                "--name",
                "proxy-executor",
                "--proxy",
                "test-or-proxy",
                "--model",
                "claude-opus-4.6",
            ],
        )

    assert result.exit_code == 0, result.output
    env_vars = mock_invoke.call_args.kwargs["env_vars"]
    assert env_vars["ANTHROPIC_BASE_URL"] == "http://localhost:8095"
    assert env_vars["ANTHROPIC_MODEL"] == "opus"
    assert env_vars["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "claude-opus-4-6"

    state = SessionStore(str(temp_env), "proxy-executor").read()
    assert state.intent.launch is not None
    assert state.intent.launch.direct_model == "claude-opus-4-6"


def test_fork_with_model_requires_proxy_id_for_inherited_proxy_routing(
    runner: CliRunner,
    temp_env: Path,
) -> None:
    """Fork matches resume: inherited proxy base_url needs explicit --proxy for --model validation."""
    with patch("forge.cli.session._resolve_routing_from_cli", return_value=_anthropic_routing()):
        start_result = runner.invoke(
            main,
            ["session", "start", "proxy-planner", "--proxy", "test-or-proxy", "--no-launch"],
        )

    assert start_result.exit_code == 0, start_result.output

    with patch("forge.cli.session.invoke_claude") as mock_invoke:
        result = runner.invoke(
            main,
            ["session", "fork", "proxy-planner", "--name", "proxy-executor", "--model", "claude-opus-4.6"],
        )

    assert result.exit_code == 1
    assert "requires an active proxy id for fork" in result.output
    assert "Pass --proxy <proxy_id>" in result.output
    assert not SessionStore(str(temp_env), "proxy-executor").exists()
    mock_invoke.assert_not_called()


def test_resume_with_model_overrides_persisted_model_pin(runner: CliRunner, temp_env: Path) -> None:
    """--model on resume should let a session move between Claude versions."""
    runner.invoke(main, ["session", "start", "planner", "--model", "claude-opus-4.7", "--no-launch"])

    with patch("forge.cli.session.invoke_claude", return_value=0) as mock_invoke:
        result = runner.invoke(main, ["session", "resume", "planner", "--model", "claude-opus-4.6"])

    assert result.exit_code == 0, result.output
    kwargs = mock_invoke.call_args.kwargs
    assert kwargs["model"] is None
    assert kwargs["env_vars"]["ANTHROPIC_MODEL"] == "opus"
    assert kwargs["env_vars"]["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "claude-opus-4-6"

    state = SessionStore(str(temp_env), "planner").read()
    assert state.intent.launch is not None
    assert state.intent.launch.direct_model == "claude-opus-4-6"


def test_resume_with_proxy_model_allows_proxy_default_tier(runner: CliRunner, temp_env: Path) -> None:
    """--model on proxy resume should support the proxy tier default, not only alternatives."""
    runner.invoke(main, ["session", "start", "proxy-planner", "--model", "claude-opus-4.7", "--no-launch"])

    with (
        patch("forge.cli.session._resolve_routing_from_cli", return_value=_anthropic_routing()),
        patch("forge.config.loader.load_proxy_instance_config", return_value=_anthropic_proxy_cfg()),
        patch("forge.cli.session.invoke_claude", return_value=0) as mock_invoke,
    ):
        result = runner.invoke(
            main,
            [
                "session",
                "resume",
                "proxy-planner",
                "--proxy",
                "test-or-proxy",
                "--model",
                "claude-opus-4.6",
            ],
        )

    assert result.exit_code == 0, result.output
    env_vars = mock_invoke.call_args.kwargs["env_vars"]
    assert env_vars["ANTHROPIC_BASE_URL"] == "http://localhost:8095"
    assert env_vars["ANTHROPIC_MODEL"] == "opus"
    assert env_vars["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "claude-opus-4-6"

    state = SessionStore(str(temp_env), "proxy-planner").read()
    assert state.intent.launch is not None
    assert state.intent.launch.direct_model == "claude-opus-4-6"


def test_resume_with_model_requires_proxy_id_for_inherited_proxy_routing(
    runner: CliRunner,
    temp_env: Path,
) -> None:
    """Inherited proxy base_url without a proxy_id cannot validate a --model override."""
    with patch("forge.cli.session._resolve_routing_from_cli", return_value=_anthropic_routing()):
        start_result = runner.invoke(
            main,
            ["session", "start", "proxy-planner", "--proxy", "test-or-proxy", "--no-launch"],
        )

    assert start_result.exit_code == 0, start_result.output

    with patch("forge.cli.session.invoke_claude") as mock_invoke:
        result = runner.invoke(
            main,
            ["session", "resume", "proxy-planner", "--model", "claude-opus-4.6"],
        )

    assert result.exit_code == 1
    assert "requires an active proxy id for resume" in result.output
    assert "Pass --proxy <proxy_id>" in result.output
    mock_invoke.assert_not_called()
