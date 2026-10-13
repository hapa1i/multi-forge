"""Native reviewer readiness follows the policy and overrides a child inherits."""

from unittest.mock import Mock

import pytest

from forge.policy.semantic.identity import validate_inherited_claude_trigger
from forge.session.models import (
    ConsumerLaneIntent,
    LaneRecord,
    NativeSupervisorSource,
    PolicyIntent,
    SupervisorConfig,
    create_session_state,
)

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("preserve_overrides", [False, True])
@pytest.mark.parametrize(
    "intent_enabled,override_enabled",
    [(False, None), (True, False), (False, True), (True, None)],
)
def test_native_readiness_follows_the_child_policy(monkeypatch, preserve_overrides, intent_enabled, override_enabled):
    state = create_session_state("executor")
    state.intent.policy = PolicyIntent(
        enabled=intent_enabled,
        supervisor=SupervisorConfig(
            native_source=NativeSupervisorSource(
                runtime="codex",
                thread_id="01a12b5c-ce1a-72c2-ad3f-05d75f3fba00",
                home="/unavailable",
                rollout_path="/unavailable/source.jsonl",
                source_cwd="/executor",
                header_digest="a" * 64,
            ),
            auth_mode="subscription-only",
            supervisor_model="gpt-6.1-sol",
            supervisor_effort="low",
        ),
    )
    state.intent.consumer_lanes = ConsumerLaneIntent(supervisor=LaneRecord("codex", "chatgpt", "gpt-6.1-sol"))
    if override_enabled is not None:
        state.overrides = {"policy": {"enabled": override_enabled}}
    unavailable = Mock(side_effect=ValueError("native source unavailable"))
    monkeypatch.setattr("forge.policy.semantic.native_codex.preflight_native", unavailable)
    effective_enabled = intent_enabled if override_enabled is None else override_enabled
    must_preflight = effective_enabled or (not preserve_overrides and intent_enabled)

    if must_preflight:
        with pytest.raises(ValueError, match="native source unavailable"):
            validate_inherited_claude_trigger(state, preserve_overrides=preserve_overrides)
        unavailable.assert_called_once()
    else:
        validate_inherited_claude_trigger(state, preserve_overrides=preserve_overrides)
        unavailable.assert_not_called()
