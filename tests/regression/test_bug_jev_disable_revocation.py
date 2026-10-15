"""C1: every policy disable writer must revoke grants before supervisor setup can enable policy."""

from __future__ import annotations

import json
import re
import shlex
from copy import deepcopy

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.policy.rule_pack.consent import (
    ACKNOWLEDGMENT_KEY,
    BUNDLE_NAME,
    build_acknowledgment,
    has_acknowledgment,
)
from forge.policy.semantic.supervisor import apply_supervisor_to_intent
from forge.session import IndexStore, SessionStore, create_session_state
from forge.session.effective import compute_effective_intent
from forge.session.models import PolicyIntent, SupervisorConfig
from tests.fixtures.session_state import publish_session

pytestmark = pytest.mark.regression


@pytest.fixture
def granted_session(tmp_path, monkeypatch):
    root = tmp_path / "project"
    (root / ".forge").mkdir(parents=True)
    (root / ".git").mkdir()
    monkeypatch.chdir(root)
    monkeypatch.setenv("COLUMNS", "500")
    monkeypatch.setenv("FORGE_SESSION", "jev-test")
    monkeypatch.setenv("FORGE_FORGE_ROOT", str(root))
    state = create_session_state("jev-test", worktree_path=str(root))
    state.forge_root = str(root)
    settings = {"pack_version": "candidate-1", "model": "typesafe/jev-1.13"}
    grant = build_acknowledgment(state, settings, acknowledge_paid_data_sharing=True)
    state.intent.policy = PolicyIntent(
        enabled=True,
        bundles=["tdd", BUNDLE_NAME],
        bundle_config={
            "tdd": {"strict": False},
            BUNDLE_NAME: {**settings, ACKNOWLEDGMENT_KEY: grant},
        },
    )
    state.overrides = {
        "policy": {
            "bundle_config": deepcopy(state.intent.policy.bundle_config),
            "fail_mode": "closed",
        },
        "memory": {"auto_recall": False},
    }
    publish_session(
        IndexStore(),
        state,
        root,
        forge_root=root,
        checkout_root=root,
        relative_path=".",
    )
    return SessionStore(root, state.name)


@pytest.mark.parametrize("enabled_override", [None, False, True])
@pytest.mark.parametrize("surface", ["raw", "raw-parent", "terminal", "direct"])
def test_disable_revokes_both_grants_before_supervisor_setup(granted_session, surface, enabled_override):
    store = granted_session
    if enabled_override is not None:
        state = store.read()
        state.overrides["policy"]["enabled"] = enabled_override
        store.write(state)
    runner = CliRunner()
    if surface == "direct":
        result = runner.invoke(
            main,
            ["hook", "user-prompt-submit"],
            input=json.dumps({"prompt": "%policy disable", "transcript_path": ""}),
        )
        assert json.loads(result.stdout)["reason"] == "Policy enforcement disabled"
    else:
        args = {
            "raw": ["session", "set", "policy.enabled", "false"],
            "raw-parent": ["session", "set", "policy", '{"enabled":false}'],
            "terminal": ["policy", "disable"],
        }[surface]
        result = runner.invoke(main, [*args, "--session", "jev-test"])
    assert result.exit_code == 0, result.output
    disabled = store.read()
    assert not compute_effective_intent(disabled).policy.enabled
    assert not has_acknowledgment(disabled, disabled.intent.policy.bundle_config[BUNDLE_NAME])
    override_config = disabled.overrides["policy"].get("bundle_config", {})
    assert ACKNOWLEDGMENT_KEY not in override_config.get(BUNDLE_NAME, {})
    assert disabled.intent.policy.bundle_config["tdd"] == {"strict": False}
    assert disabled.overrides["memory"] == {"auto_recall": False}
    if surface != "raw-parent":
        assert disabled.overrides["policy"]["fail_mode"] == "closed"

    apply_supervisor_to_intent(disabled, SupervisorConfig())
    effective = compute_effective_intent(disabled)
    assert effective.policy.enabled
    assert BUNDLE_NAME in effective.policy.bundles
    assert not has_acknowledgment(disabled, effective.policy.bundle_config[BUNDLE_NAME])


def test_raw_disable_allows_unrelated_reset_and_advertises_working_full_reset(
    granted_session,
):
    runner = CliRunner()
    disabled = runner.invoke(main, ["session", "set", "policy.enabled", "false", "--session", "jev-test"])
    assert disabled.exit_code == 0, disabled.output

    unrelated = runner.invoke(main, ["session", "reset", "memory.auto_recall", "--session", "jev-test"])
    assert unrelated.exit_code == 0, unrelated.output
    assert not granted_session.read().overrides.get("memory")

    refused = runner.invoke(main, ["session", "reset", "--session", "jev-test"])
    assert refused.exit_code == 1
    assert "activation is not available" in refused.stderr
    commands = [shlex.split(command) for command in re.findall(r"'(forge [^']+)'", refused.stderr)]
    assert commands == [
        ["forge", "policy", "disable", "--session", "jev-test"],
        ["forge", "session", "reset", "--session", "jev-test"],
    ], repr(refused.stderr)
    for command in commands:
        recovered = runner.invoke(main, command[1:])
        assert recovered.exit_code == 0, recovered.output

    state = granted_session.read()
    assert state.overrides == {}
    assert not state.intent.policy.enabled
    assert not has_acknowledgment(state, state.intent.policy.bundle_config[BUNDLE_NAME])
