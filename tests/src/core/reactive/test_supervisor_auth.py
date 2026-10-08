"""Explicit subscription routing never inherits the parent's paid credentials."""

import json
import os
import subprocess
from unittest.mock import patch

import pytest

from forge.core.reactive.session_runner import run_claude_session
from forge.core.reactive.supervisor_auth import (
    subscription_environment,
    validate_subscription_location,
)


@pytest.fixture
def personal_login(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("FORGE_SIDECAR", raising=False)
    monkeypatch.delenv("FORGE_LAUNCH_MODE", raising=False)
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude/remote-settings.json").write_text("{}")
    (tmp_path / ".claude.json").write_text(json.dumps({"oauthAccount": {"organizationType": "claude_max"}}))
    return tmp_path


def test_skip_hydration_after_dotenv_and_remove_competing_routes(personal_login, monkeypatch):
    variables = {
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_PROFILE",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_FEDERATION_RULE_ID",
        "ANTHROPIC_ORGANIZATION_ID",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "CLAUDE_CODE_USE_BEDROCK",
        "CLAUDE_CODE_USE_VERTEX",
        "CLAUDE_CODE_USE_FOUNDRY",
        "FORGE_SUBPROCESS_PROXY",
        "FORGE_SUBPROCESS_BASE_URL",
        "HTTPS_PROXY",
        "NODE_OPTIONS",
    }
    for key in variables:
        monkeypatch.setenv(key, "synthetic-competing-selector")
    with patch("forge.core.reactive.env._hydrate_credentials", side_effect=AssertionError("must not hydrate")):
        env = subscription_environment()
    assert variables.isdisjoint(env)
    assert variables.issubset(os.environ)
    validate_subscription_location(env)


@pytest.mark.parametrize(
    "relative,content",
    [
        (".config/anthropic/active_config", "production"),
        (".config/anthropic/configs/default.json", "{}"),
        (".claude/remote-settings.json", '{"env":{"ANTHROPIC_API_KEY":"synthetic"}}'),
        (".claude/remote-settings.json", "not-json"),
    ],
)
def test_unverified_profile_or_managed_settings_refuse(personal_login, relative, content):
    path = personal_login / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    with pytest.raises(ValueError):
        validate_subscription_location(subscription_environment())


@pytest.mark.parametrize(
    "status,accepted",
    [
        ({"loggedIn": True, "authMethod": "claude.ai", "apiProvider": "firstParty"}, True),
        ({"loggedIn": False}, False),
        (
            {"loggedIn": True, "authMethod": "api_key", "apiProvider": "firstParty", "apiKeySource": "environment"},
            False,
        ),
        ({"loggedIn": True, "authMethod": "claude.ai", "apiProvider": "bedrock"}, False),
        (
            {
                "loggedIn": True,
                "authMethod": "claude.ai",
                "apiProvider": "firstParty",
                "subscriptionType": "enterprise",
            },
            False,
        ),
    ],
)
def test_preflight_and_dispatch_share_one_final_environment(personal_login, monkeypatch, status, accepted):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-parent-key")
    calls = []

    def guarded(argv, **kwargs):
        calls.append((argv, kwargs))
        output = "2.1.291 (Claude Code)" if "--version" in argv else json.dumps(status) if "auth" in argv else "verdict"
        return subprocess.CompletedProcess(argv, 0, output, "")

    with (
        patch("forge.core.reactive.supervisor_auth.require_reviewer_runtime", return_value="/verified/claude"),
        patch("forge.core.reactive.watchdog.run_guarded", side_effect=guarded),
        patch("forge.core.reactive.supervisor_auth.run_guarded", side_effect=guarded),
        patch(
            "forge.core.reactive.session_runner.prepare_json_argv", side_effect=lambda cmd, *args, **kw: (cmd, False)
        ),
    ):
        result = run_claude_session(
            "review", direct=True, read_only=True, subscription_only=True, cwd=str(personal_login), timeout_seconds=10
        )
    assert result.dispatched is accepted
    assert len(calls) == (2 if accepted else 1)
    assert all("ANTHROPIC_API_KEY" not in kwargs["env"] for _, kwargs in calls)
    assert len({id(kwargs["env"]) for _, kwargs in calls}) == 1
    if accepted:
        assert result.child_billing_mode == "subscription_quota"
        assert calls[-1][0][0] == "/verified/claude"
        assert "--bare" not in calls[-1][0]
    else:
        assert result.child_billing_mode is None
        assert result.error
