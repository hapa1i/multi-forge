"""Regression: current catalog membership must not erase durable model intent."""

from __future__ import annotations

import pytest

from forge.core.ops.session_model import _route_intent
from forge.session.models import ModelRouteIntent, create_session_state

pytestmark = pytest.mark.regression


def test_removed_model_route_intent_remains_reportable() -> None:
    state = create_session_state("removed-model", worktree_path="/tmp")
    assert state.intent.launch is not None
    state.intent.launch.model_route = ModelRouteIntent(
        requested_model="removed-model-v1",
        selected_tier="opus",
        kind="direct",
        source_id=None,
    )
    state.intent.launch.direct_model = None

    assert _route_intent(state)["requested_model"] == "removed-model-v1"
