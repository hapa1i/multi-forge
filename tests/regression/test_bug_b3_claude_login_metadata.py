"""Current Claude Max logins can omit the old organizationType metadata field."""

import json
import subprocess
from unittest.mock import patch

import pytest

from forge.core.reactive.session_runner import run_claude_session

pytestmark = pytest.mark.regression


@pytest.mark.parametrize(
    "organization,subscription,accepted",
    [
        (None, "max", True),
        (None, "pro", True),
        (None, None, False),
        (None, "team", False),
        ("enterprise", "max", False),
        ("claude_max", None, True),
        ("claude_max", "enterprise", False),
    ],
)
def test_personal_status_can_replace_absent_metadata_only(tmp_path, monkeypatch, organization, subscription, accepted):
    monkeypatch.setenv("HOME", str(tmp_path))
    for key in ("CLAUDE_CONFIG_DIR", "FORGE_SIDECAR", "FORGE_LAUNCH_MODE"):
        monkeypatch.delenv(key, raising=False)
    account = {"billingType": "stripe_subscription"}
    if organization is not None:
        account["organizationType"] = organization
    (tmp_path / ".claude.json").write_text(json.dumps({"oauthAccount": account}))
    status = {
        "loggedIn": True,
        "authMethod": "claude.ai",
        "apiProvider": "firstParty",
        "apiKeySource": None,
        "subscriptionType": subscription,
    }
    dispatched = []

    def guarded(argv, **kwargs):
        if "auth" in argv:
            return subprocess.CompletedProcess(argv, 0, json.dumps(status), "")
        dispatched.append(argv)
        return subprocess.CompletedProcess(argv, 0, "reviewed", "")

    with (
        patch("forge.core.reactive.supervisor_auth.require_reviewer_runtime", return_value="/verified/claude"),
        patch("forge.core.reactive.supervisor_auth.run_guarded", side_effect=guarded),
        patch("forge.core.reactive.watchdog.run_guarded", side_effect=guarded),
        patch("forge.core.reactive.session_runner.prepare_json_argv", side_effect=lambda cmd, *a, **kw: (cmd, False)),
    ):
        result = run_claude_session("review", direct=True, read_only=True, subscription_only=True, timeout_seconds=10)
    assert result.dispatched is accepted
    assert bool(dispatched) is accepted
    assert result.child_billing_mode == ("subscription_quota" if accepted else None)
