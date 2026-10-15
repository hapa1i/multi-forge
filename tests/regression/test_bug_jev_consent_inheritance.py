"""A paid policy grant must not become inheritable enforcement configuration."""

from copy import deepcopy

import pytest

from forge.policy.rule_pack.consent import BUNDLE_NAME
from forge.session.manager import _inherit_intent_fields
from forge.session.models import PolicyIntent, SupervisorConfig, create_session_state

pytestmark = pytest.mark.regression


def test_derived_intent_preserves_enforcement_but_drops_paid_bundle():
    parent = create_session_state("parent")
    parent.intent.policy = PolicyIntent(
        enabled=True,
        fail_mode="closed",
        bundles=["tdd", "coding_standards", BUNDLE_NAME],
        bundle_config={"tdd": {"strict": False}, BUNDLE_NAME: {"acknowledgment": {"version": 1}}},
        supervisor=SupervisorConfig(),
    )
    before = deepcopy(parent)
    child = create_session_state("child")
    _inherit_intent_fields(child, parent)
    assert child.intent.policy == PolicyIntent(
        enabled=True,
        fail_mode="closed",
        bundles=["tdd", "coding_standards"],
        bundle_config={"tdd": {"strict": False}},
        supervisor=SupervisorConfig(),
    )
    assert parent == before
