"""Focused CLI tests for session model pin behavior."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

import forge.cli.session as session_cli
from forge.cli.main import main
from forge.session import SessionStore, create_session_state
from tests.src.cli.session_command_support import mocked_model_route_proxy


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


def _anthropic_routing() -> session_cli.ResolvedRouting:
    return session_cli.ResolvedRouting(
        template="openrouter-anthropic",
        base_url="http://localhost:8095",
        proxy_id="test-or-proxy",
    )


@pytest.mark.parametrize("leaf", ["start", "resume", "fork", "incognito"])
def test_interactive_model_leaves_share_model_tier_help(
    runner: CliRunner,
    leaf: str,
) -> None:
    result = runner.invoke(main, ["session", leaf, "--help"], terminal_width=500)

    assert result.exit_code == 0, result.output
    assert "--model TEXT" in result.output
    assert "--model-tier [haiku|sonnet|opus]" in result.output
    assert "Select the proxy tier for --model when more than one tier can serve it" in result.output


@pytest.mark.parametrize("leaf", ["start", "incognito"])
def test_model_tier_requires_model_before_session_creation(
    runner: CliRunner,
    temp_env: Path,
    leaf: str,
) -> None:
    result = runner.invoke(
        main,
        ["session", leaf, "tier-without-model", "--model-tier", "opus"],
    )

    assert result.exit_code == 1
    assert "--model-tier requires --model" in result.output
    assert not SessionStore(str(temp_env), "tier-without-model").exists()


def test_default_direct_model_rejects_non_claude_before_proxy_or_child(
    runner: CliRunner,
    temp_env: Path,
) -> None:
    """A bare managed launch keeps the Claude-only config boundary."""
    from forge.core.paths import get_forge_home
    from forge.runtime_config import reset_runtime_config

    get_forge_home().mkdir(parents=True, exist_ok=True)
    (get_forge_home() / "config.yaml").write_text("default_direct_model: gpt-5.6-sol\n")
    reset_runtime_config()

    try:
        with (
            patch("forge.proxy.proxy_orchestrator.ensure_proxy") as mock_ensure_proxy,
            patch("forge.core.ops.claude_session.invoke_claude") as mock_invoke,
        ):
            result = runner.invoke(main, ["session", "start", "invalid-default"])
    finally:
        reset_runtime_config()

    assert result.exit_code == 1
    assert "Invalid configuration field 'default_direct_model'" in result.output
    assert "only supports Claude models" in result.output
    mock_ensure_proxy.assert_not_called()
    mock_invoke.assert_not_called()


def test_fork_model_override_lock_failure_returns_styled_warning(
    temp_env: Path,
) -> None:
    """A failed --model manifest write should be visible instead of silently lost."""
    from forge.cli.session_fork import _render_fork_execution_event
    from forge.core.ops.session_fork_execution import (
        ForkExecutionEvent,
        ForkModelOverridePersistenceWarning,
        _apply_direct_model_override,
    )
    from forge.core.state import FileLockTimeoutError

    state = create_session_state("persist-warning", worktree_path=str(temp_env))
    SessionStore(str(temp_env), "persist-warning").write(state)
    events: list[ForkExecutionEvent] = []

    with patch(
        "forge.core.ops.session_fork_execution.SessionStore.update",
        side_effect=FileLockTimeoutError(lock_path=temp_env / "forge.session.json.lock", timeout_s=5.0),
    ):
        _apply_direct_model_override(
            manifest=state,
            direct_model="claude-opus-4-6",
            forge_root=temp_env,
            use_sidecar=False,
            events=events,
        )

    assert len(events) == 1
    event = events[0]
    assert isinstance(event, ForkModelOverridePersistenceWarning)
    assert "future resumes may use the previous stored model" in event.continuation
    with (
        patch("forge.cli.session_fork.console.print") as mock_print,
        patch("forge.cli.session_fork.print_tip") as mock_tip,
    ):
        _render_fork_execution_event(event)

    mock_print.assert_called_once_with(
        f"[yellow]Warning:[/yellow] Could not persist --model override for session "
        f"[green]persist-warning[/green]: {event.error}"
    )
    mock_tip.assert_called_once_with(event.continuation, blank_before=False, console=session_cli.console)


def test_apply_direct_model_env_legacy_proxy_returns_error_not_traceback() -> None:
    """A legacy 'provider: gemini' proxy yields a clean error, not a load traceback.

    Regression: _apply_direct_model_env_if_supported loaded the proxy config
    outside a ValueError boundary, so resume/fork paths that reach the apply
    without the _validate_proxy_model_pin gate (persisted --model, no fresh pin)
    surfaced the unsupported-provider ValueError as an unhandled traceback.
    """
    import os

    from forge.session import model_pin

    forge_home = Path(os.environ["FORGE_HOME"])
    proxy_dir = forge_home / "proxies" / "legacy-gemini"
    proxy_dir.mkdir(parents=True, exist_ok=True)
    (proxy_dir / "proxy.yaml").write_text(
        "template: litellm-gemini\n"
        "provider: gemini\n"
        "proxy_endpoint: http://localhost:8084\n"
        "port: 8084\n"
        "upstream_base_url: https://litellm.test.example.com\n"
        "tiers:\n"
        "  haiku: gemini-2.0-flash\n"
        "  sonnet: gemini-2.5-pro\n"
        "  opus: gemini-2.5-pro\n"
    )

    env_vars: dict[str, str] = {}
    application = model_pin._apply_direct_model_env_if_supported(env_vars, "legacy-gemini", "claude-opus-4.6")

    assert application.pin is None
    assert application.error is not None
    assert "Could not load proxy config for 'legacy-gemini'" in application.error
    assert "Unsupported proxy provider" in application.error
    assert env_vars == {}  # No env applied for an unloadable proxy


def test_apply_direct_model_env_bad_shape_returns_error_not_traceback() -> None:
    """A malformed proxy.yaml ('tiers: []') yields a clean error, not a shape traceback.

    Companion to the legacy-provider case: the shape failure raises AttributeError
    from the loader's raw extraction, which the load guard only catches because the
    loader now normalizes shape failures to ValueError.
    """
    import os

    from forge.session import model_pin

    forge_home = Path(os.environ["FORGE_HOME"])
    proxy_dir = forge_home / "proxies" / "bad-shape"
    proxy_dir.mkdir(parents=True, exist_ok=True)
    (proxy_dir / "proxy.yaml").write_text(
        "template: litellm-openai\n"
        "provider: litellm\n"
        "proxy_endpoint: http://localhost:8085\n"
        "port: 8085\n"
        "upstream_base_url: https://litellm.test.example.com\n"
        "tiers: []\n"
    )

    env_vars: dict[str, str] = {}
    application = model_pin._apply_direct_model_env_if_supported(env_vars, "bad-shape", "claude-opus-4.6")

    assert application.pin is None
    assert application.error is not None
    assert "Malformed proxy configuration" in application.error
    assert env_vars == {}


def test_apply_direct_model_env_reports_unsupported_proxy_pin_as_not_applied() -> None:
    from forge.config.schema import ProxyInstanceConfig, TierModels
    from forge.session import model_pin

    config = ProxyInstanceConfig(
        proxy_format=1,
        template="litellm-openai",
        template_digest="abc",
        provider="litellm",
        proxy_endpoint="http://localhost:8085",
        port=8085,
        upstream_base_url="https://api.openai.com/v1",
        tiers=TierModels(haiku="openai/gpt-5.4-mini", sonnet="openai/gpt-5.4", opus="openai/gpt-5.5"),
        model_alternatives={},
    )
    env_vars: dict[str, str] = {}

    with patch("forge.config.loader.load_proxy_instance_config", return_value=config):
        application = model_pin._apply_direct_model_env_if_supported(env_vars, "openai-1", "claude-opus-5")

    assert application.error is None
    assert application.pin is None
    assert env_vars == {}


def test_incognito_with_model(runner: CliRunner, temp_env: Path) -> None:
    """The incognito shortcut should expose the same --model pin as session start."""
    with patch("forge.core.ops.claude_session.invoke_claude", return_value=0) as mock_invoke:
        result = runner.invoke(main, ["session", "incognito", "incog-model", "--model", "sonnet-4-6"])

    assert result.exit_code == 0, result.output
    kwargs = mock_invoke.call_args.kwargs
    assert kwargs["model"] is None
    assert kwargs["env_vars"]["ANTHROPIC_MODEL"] == "sonnet"
    assert kwargs["env_vars"]["ANTHROPIC_DEFAULT_SONNET_MODEL"] == "claude-sonnet-4-6"


def test_incognito_non_claude_model_uses_shared_route_and_cleans_session(
    runner: CliRunner,
    temp_env: Path,
) -> None:
    with (
        mocked_model_route_proxy(
            template="openrouter-openai",
            proxy_id="openrouter-openai-1",
            base_url="http://localhost:8096",
            default_tier="opus",
            tiers={
                "sonnet": "openai/gpt-5.6-sol",
                "opus": "openai/gpt-5.6-sol",
            },
            alternatives={},
        ) as ensure_proxy,
        patch("forge.core.ops.claude_session.invoke_claude", return_value=0) as mock_invoke,
    ):
        result = runner.invoke(
            main,
            ["session", "incognito", "incog-gpt", "--model", "gpt-5.6-sol"],
        )

    assert result.exit_code == 0, result.output
    ensure_proxy.assert_called_once_with("openrouter-openai")
    assert mock_invoke.call_args.kwargs["env_vars"]["ANTHROPIC_MODEL"] == "opus"
    assert result.stderr.count("Route:") == 1
    assert "Cleaning up incognito session" in result.output
    assert not SessionStore(str(temp_env), "incog-gpt").exists()


def test_fork_with_model_overrides_persisted_model_pin(runner: CliRunner, temp_env: Path) -> None:
    """--model on fork should let a child switch Claude versions immediately."""
    runner.invoke(
        main,
        ["session", "start", "planner", "--model", "claude-opus-4.8", "--no-launch"],
    )
    store = SessionStore(str(temp_env), "planner")
    store.update(
        timeout_s=5.0,
        mutate=lambda m: setattr(m.confirmed, "claude_session_id", "parent-uuid"),
    )

    with patch("forge.core.ops.claude_session.invoke_claude", return_value=0) as mock_invoke:
        result = runner.invoke(
            main,
            [
                "session",
                "fork",
                "planner",
                "--name",
                "executor",
                "--model",
                "claude-opus-4.6",
            ],
        )

    assert result.exit_code == 0, result.output
    kwargs = mock_invoke.call_args.kwargs
    assert kwargs["model"] is None
    assert kwargs["env_vars"]["ANTHROPIC_MODEL"] == "opus"
    assert kwargs["env_vars"]["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "claude-opus-4-6"

    state = SessionStore(str(temp_env), "executor").read()
    assert state.intent.launch is not None
    assert state.intent.launch.direct_model == "claude-opus-4-6"


def test_fork_inherits_direct_1m_execution_projection(runner: CliRunner, temp_env: Path) -> None:
    created = runner.invoke(
        main,
        [
            "session",
            "start",
            "one-m-planner",
            "--model",
            "claude-opus-4-6[1m]",
            "--no-launch",
        ],
    )
    assert created.exit_code == 0, created.output
    store = SessionStore(str(temp_env), "one-m-planner")
    store.update(
        timeout_s=5.0,
        mutate=lambda state: setattr(state.confirmed, "claude_session_id", "parent-uuid"),
    )

    with patch("forge.core.ops.claude_session.invoke_claude", return_value=0) as mock_invoke:
        result = runner.invoke(
            main,
            ["session", "fork", "one-m-planner", "--name", "one-m-executor"],
        )

    assert result.exit_code == 0, result.output
    env_vars = mock_invoke.call_args.kwargs["env_vars"]
    assert env_vars["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "claude-opus-4-6[1m]"
    child = SessionStore(str(temp_env), "one-m-executor").read()
    assert child.intent.launch is not None
    assert child.intent.launch.direct_model == "claude-opus-4-6[1m]"


def test_fork_non_claude_model_persists_neutral_route(
    runner: CliRunner,
    temp_env: Path,
) -> None:
    runner.invoke(
        main,
        ["session", "start", "gpt-parent", "--model", "claude-opus-5", "--no-launch"],
    )
    parent_store = SessionStore(str(temp_env), "gpt-parent")
    parent_store.update(
        timeout_s=5.0,
        mutate=lambda state: setattr(state.confirmed, "claude_session_id", "parent-uuid"),
    )

    with (
        mocked_model_route_proxy(
            template="openrouter-openai",
            proxy_id="openrouter-openai-1",
            base_url="http://localhost:8096",
            default_tier="opus",
            tiers={
                "sonnet": "openai/gpt-5.6-sol",
                "opus": "openai/gpt-5.6-sol",
            },
            alternatives={},
        ) as ensure_proxy,
        patch("forge.core.ops.claude_session.invoke_claude", return_value=0) as mock_invoke,
    ):
        result = runner.invoke(
            main,
            [
                "session",
                "fork",
                "gpt-parent",
                "--name",
                "gpt-child",
                "--model",
                "gpt-5.6-sol",
            ],
        )

    assert result.exit_code == 0, result.output
    ensure_proxy.assert_called_once_with("openrouter-openai")
    assert mock_invoke.call_args.kwargs["env_vars"]["ANTHROPIC_MODEL"] == "opus"
    assert result.stderr.count("Route:") == 1
    child = SessionStore(str(temp_env), "gpt-child").read()
    assert child.intent.launch is not None
    assert child.intent.launch.direct_model is None
    assert child.intent.launch.model_route is not None
    assert child.intent.launch.model_route.requested_model == "gpt-5.6-sol"
    assert child.intent.launch.model_route.selected_tier == "opus"


def test_fork_with_proxy_model_allows_proxy_default_tier(runner: CliRunner, temp_env: Path) -> None:
    """--model on proxy fork should support the proxy tier default, not only alternatives."""
    runner.invoke(
        main,
        [
            "session",
            "start",
            "proxy-planner",
            "--model",
            "claude-opus-4.8",
            "--no-launch",
        ],
    )
    store = SessionStore(str(temp_env), "proxy-planner")
    store.update(
        timeout_s=5.0,
        mutate=lambda m: setattr(m.confirmed, "claude_session_id", "parent-uuid"),
    )

    with (
        mocked_model_route_proxy(),
        patch("forge.core.ops.claude_session.invoke_claude", return_value=0) as mock_invoke,
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


def test_proxy_model_tier_overrides_intrinsic_claude_tier_in_child_env(
    runner: CliRunner,
    temp_env: Path,
) -> None:
    tiers = {
        "sonnet": "anthropic/claude-opus-5",
        "opus": "anthropic/claude-opus-5",
    }
    with (
        mocked_model_route_proxy(
            template="openrouter-anthropic",
            proxy_id="openrouter-anthropic-1",
            base_url="http://localhost:8095",
            default_tier="opus",
            tiers=tiers,
            alternatives={},
        ),
        patch("forge.core.ops.claude_session.invoke_claude", return_value=0) as mock_invoke,
    ):
        result = runner.invoke(
            main,
            [
                "session",
                "start",
                "retiered-claude",
                "--model",
                "claude-opus-5",
                "--model-tier",
                "sonnet",
                "--proxy",
                "openrouter-anthropic",
            ],
        )

    assert result.exit_code == 0, result.output
    state = SessionStore(str(temp_env), "retiered-claude").read()
    assert state.intent.launch is not None
    assert state.intent.launch.model_route is not None
    assert state.intent.launch.model_route.selected_tier == "sonnet"
    env_vars = mock_invoke.call_args.kwargs["env_vars"]
    assert env_vars["ANTHROPIC_MODEL"] == "sonnet"
    assert env_vars["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "claude-opus-5"


def test_fork_with_model_requires_proxy_id_for_inherited_proxy_routing(
    runner: CliRunner,
    temp_env: Path,
) -> None:
    """Fork matches resume: inherited proxy base_url needs explicit --proxy for --model validation."""
    with patch(
        "forge.cli.session_lifecycle._resolve_routing_from_cli",
        return_value=_anthropic_routing(),
    ):
        start_result = runner.invoke(
            main,
            [
                "session",
                "start",
                "proxy-planner",
                "--proxy",
                "test-or-proxy",
                "--no-launch",
            ],
        )

    assert start_result.exit_code == 0, start_result.output

    with patch("forge.core.ops.claude_session.invoke_claude") as mock_invoke:
        result = runner.invoke(
            main,
            [
                "session",
                "fork",
                "proxy-planner",
                "--name",
                "proxy-executor",
                "--model",
                "claude-opus-4.6",
            ],
        )

    assert result.exit_code == 1
    assert "cannot be identity-checked without a proxy id" in result.output
    assert "pass --proxy <proxy_id-or-template>" in result.output
    assert not SessionStore(str(temp_env), "proxy-executor").exists()
    mock_invoke.assert_not_called()


def test_resume_with_model_overrides_persisted_model_pin(runner: CliRunner, temp_env: Path) -> None:
    """--model on resume should let a session move between Claude versions."""
    runner.invoke(
        main,
        ["session", "start", "planner", "--model", "claude-opus-4.8", "--no-launch"],
    )

    with patch("forge.core.ops.claude_session.invoke_claude", return_value=0) as mock_invoke:
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
    runner.invoke(
        main,
        [
            "session",
            "start",
            "proxy-planner",
            "--model",
            "claude-opus-4.8",
            "--no-launch",
        ],
    )

    with (
        mocked_model_route_proxy(),
        patch("forge.core.ops.claude_session.invoke_claude", return_value=0) as mock_invoke,
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
    with patch(
        "forge.cli.session_lifecycle._resolve_routing_from_cli",
        return_value=_anthropic_routing(),
    ):
        start_result = runner.invoke(
            main,
            [
                "session",
                "start",
                "proxy-planner",
                "--proxy",
                "test-or-proxy",
                "--no-launch",
            ],
        )

    assert start_result.exit_code == 0, start_result.output

    with patch("forge.core.ops.claude_session.invoke_claude") as mock_invoke:
        result = runner.invoke(
            main,
            ["session", "resume", "proxy-planner", "--model", "claude-opus-4.6"],
        )

    assert result.exit_code == 1
    assert "cannot be identity-checked without a proxy id" in result.output
    assert "pass --proxy <proxy_id-or-template>" in result.output
    mock_invoke.assert_not_called()
