"""Workers inherited native delegation and memory settings from their executor."""

import json
import os
import subprocess
from dataclasses import replace
from unittest.mock import patch

import pytest

from forge.core.invoker import HeadlessRequest
from forge.core.reactive.session_runner import run_claude_session
from forge.core.worker_controls import CLAUDE_WORKER_PROFILE
from forge.review.engine import _prepare_worker
from tests.fixtures.review_workers import (
    HOSTILE_ENV,
)
from tests.fixtures.review_workers import (
    assert_claude_worker_controls as _assert_claude_controls,
)
from tests.fixtures.review_workers import make_codex_preflight as _codex_preflight
from tests.fixtures.review_workers import make_codex_spec as _codex_spec
from tests.fixtures.review_workers import make_model_spec as _spec
from tests.fixtures.review_workers import make_routing_result as _routing_result
from tests.fixtures.review_workers import (
    runtime_native_result as _runtime_native_result,
)

pytestmark = pytest.mark.regression


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
    assert "--fork-session" in request.argv


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
    profile = replace(
        CLAUDE_WORKER_PROFILE, settings={**CLAUDE_WORKER_PROFILE.settings, "permissions": {"deny": ["WebFetch"]}}
    )
    with (
        patch("forge.core.reactive.session_runner.CLAUDE_WORKER_PROFILE", profile),
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
            assert json.loads(argv[argv.index("--settings") + 1])["permissions"] == {"deny": ["WebFetch"]}
    assert "--output-format" in calls[0][0]
    assert "--output-format" not in calls[1][0]


def test_shared_claude_runner_preserves_root_native_choices(monkeypatch):
    for name, value in HOSTILE_ENV.items():
        monkeypatch.setenv(name, value)
    with patch("forge.core.reactive.session_runner.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess([], 0, "done", "")
        result = run_claude_session("Root work", worker=False, output_format=None)
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


def test_subscription_checks_the_final_worker_configuration(tmp_path, monkeypatch):
    monkeypatch.setattr(
        os,
        "environ",
        {
            "HOME": str(tmp_path),
            "FORGE_HOME": str(tmp_path / ".forge"),
            "PATH": os.environ["PATH"],
            "PYTHON_DOTENV_DISABLED": "1",
        },
    )
    calls = []

    def guarded(argv, **kwargs):
        calls.append((list(argv), dict(kwargs["env"]), kwargs["cwd"]))
        status = {"loggedIn": True, "authMethod": "claude.ai", "apiProvider": "firstParty", "subscriptionType": "max"}
        return subprocess.CompletedProcess(argv, 0, json.dumps(status) if "auth" in argv else "verdict", "")

    with (
        patch("forge.core.reactive.supervisor_auth.validate_subscription_location", return_value="claude_max"),
        patch("forge.core.reactive.supervisor_auth.require_reviewer_runtime", return_value="/verified/claude"),
        patch("forge.core.reactive.supervisor_auth.run_guarded", side_effect=guarded),
        patch("forge.core.reactive.watchdog.run_guarded", side_effect=guarded),
    ):
        result = run_claude_session(
            "review",
            worker=True,
            direct=True,
            read_only=True,
            subscription_only=True,
            cwd=str(tmp_path),
            output_format=None,
        )
    assert result.success, result.error
    auth, dispatch = calls
    assert auth[1:] == dispatch[1:]
    assert auth[0][1:-3] == dispatch[0][2:]
    _assert_claude_controls(dispatch[0], dispatch[1])
