"""Workers inherited native delegation and memory settings from their executor."""

import json
import subprocess
from unittest.mock import patch

import pytest

from forge.core.invoker import HeadlessRequest
from forge.core.reactive.session_runner import run_claude_session
from forge.review.engine import _prepare_worker
from tests.src.review.test_engine import (
    _codex_preflight,
    _codex_spec,
    _routing_result,
    _runtime_native_result,
    _spec,
)

pytestmark = pytest.mark.regression

HOSTILE_ENV = {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1",
    "CLAUDE_CODE_FORK_SUBAGENT": "1",
    "CLAUDE_CODE_DISABLE_WORKFLOWS": "0",
    "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "0",
}


def _assert_claude_controls(argv, env):
    assert env["CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"] == "0"
    assert env["CLAUDE_CODE_FORK_SUBAGENT"] == "0"
    assert env["CLAUDE_CODE_DISABLE_WORKFLOWS"] == "1"
    assert env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"
    index = argv.index("--disallowedTools")
    assert argv[index + 1 : index + 4] == ["Agent", "Workflow", "SendMessage"]
    assert "--disable-slash-commands" in argv
    settings = [json.loads(value) for flag, value in zip(argv, argv[1:]) if flag == "--settings"]
    assert settings, "settings.env must not overwrite the process environment's native controls"
    for projected in settings:
        assert projected["env"] == {key: env[key] for key in HOSTILE_ENV}


@pytest.mark.parametrize("api_key", [None, "fixture-key"])
def test_claude_review_worker_overrides_inherited_native_capabilities(monkeypatch, api_key):
    for name, value in HOSTILE_ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    if api_key:
        monkeypatch.setenv("ANTHROPIC_API_KEY", api_key)
    with patch("forge.review.engine.resolve_env_or_credential", return_value=None):
        request = _prepare_worker(
            _spec(),
            _routing_result(),
            prompt="Review this change",
            cwd=None,
            resume_id="existing-worker",
            timeout_seconds=30,
            attribution=None,
        )
    assert isinstance(request, HeadlessRequest)
    _assert_claude_controls(request.argv, request.env)
    assert request.argv[request.argv.index("--resume") + 1] == "existing-worker"


@pytest.mark.parametrize("route", ["subscription", "api", "proxy", "subscription-only", "inherited-helper"])
def test_consumer_profile_survives_overrides_unsets_and_format_retry(monkeypatch, route):
    for name, value in HOSTILE_ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    if route == "api":
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fixture-key")
    calls = []

    def execute(argv, **kwargs):
        calls.append((list(argv), dict(kwargs["env"])))
        if len(calls) == 1:
            return subprocess.CompletedProcess(argv, 2, "", "error: unknown option '--output-format'")
        return subprocess.CompletedProcess(argv, 0, "review complete", "")

    subscription_only = route == "subscription-only"
    with (
        patch("forge.core.reactive.session_runner.subprocess.run", side_effect=execute),
        patch("forge.core.reactive.watchdog.run_guarded", side_effect=execute),
        patch("forge.core.reactive.reviewer_runtime.require_reviewer_runtime", return_value="claude"),
        patch(
            "forge.core.reactive.reviewer_settings.inherited_auth_settings",
            return_value={"apiKeyHelper": "fixture-private-helper"},
        ),
        patch(
            "forge.core.reactive.supervisor_auth.preflight_subscription",
            return_value="claude",
        ),
        patch(
            "forge.core.reactive.session_runner.prepare_json_argv",
            side_effect=lambda cmd, _: (cmd + ["--output-format", "json"], True),
        ),
        patch("forge.core.reactive.session_runner.mark_json_output_unsupported"),
    ):
        result = run_claude_session(
            "Review this change",
            worker=True,
            extra_env=HOSTILE_ENV,
            unset_env_vars=tuple(HOSTILE_ENV),
            resume_id="existing-worker",
            fork_session=True,
            base_url="http://proxy.test:8095" if route == "proxy" else None,
            direct=route != "proxy",
            subscription_only=subscription_only,
            read_only=subscription_only or route == "inherited-helper",
        )
    assert result.success, result.error
    assert len(calls) == 2
    for argv, env in calls:
        _assert_claude_controls(argv, env)
        assert argv[argv.index("--resume") + 1] == "existing-worker"
        assert "--fork-session" in argv
        assert ("--bare" in argv) is (route == "api")
        if route == "proxy":
            assert env["ANTHROPIC_BASE_URL"] == "http://proxy.test:8095"
        if route == "inherited-helper":
            assert env["FORGE_REVIEWER_API_KEY_HELPER"] == "fixture-private-helper"
            assert "fixture-private-helper" not in " ".join(argv)
    assert "--output-format" in calls[0][0]
    assert "--output-format" not in calls[1][0]


def test_shared_claude_runner_preserves_root_native_choices(monkeypatch):
    for name, value in HOSTILE_ENV.items():
        monkeypatch.setenv(name, value)
    with patch("forge.core.reactive.session_runner.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess([], 0, "done", "")
        result = run_claude_session("Root work", output_format=None)
    assert result.success
    assert "--disallowedTools" not in run.call_args.args[0]
    assert "--disable-slash-commands" not in run.call_args.args[0]
    assert {key: run.call_args.kwargs["env"][key] for key in HOSTILE_ENV} == HOSTILE_ENV


def test_codex_review_worker_disables_native_agents_and_memory():
    request = _prepare_worker(
        _codex_spec(),
        _runtime_native_result(),
        prompt="Review this change",
        cwd=None,
        resume_id=None,
        timeout_seconds=30,
        attribution=None,
        codex_preflight=_codex_preflight(),
    )
    assert isinstance(request, HeadlessRequest)
    config = [value for flag, value in zip(request.argv, request.argv[1:]) if flag == "-c"]
    assert "agents.enabled=false" in config
    assert "memories.use_memories=false" in config
    assert "memories.generate_memories=false" in config
