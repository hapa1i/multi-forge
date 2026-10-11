"""B4 #13: setup validated a replacement before merging overrides or checking concurrent changes."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from forge.core.ops.policy import SupervisorInputError, supervisor_set
from forge.session import SessionStore
from tests.fixtures.stop_review import context

pytestmark = pytest.mark.regression


def test_conflicting_override_refuses_before_runtime_preflight(tmp_path: Path, monkeypatch) -> None:
    ctx = context(tmp_path)
    store = SessionStore(str(ctx.forge_root), ctx.session)

    def initial(state):
        state.intent.policy.supervisor.review_trigger = "pre-tool-use"
        state.overrides = {"policy": {"supervisor": {"shadow_sample_rate": 0.25}}}

    store.update(timeout_s=1, mutate=initial)
    before = store.manifest_path.read_bytes()
    preflight, enrollment = Mock(), Mock()
    monkeypatch.setattr("forge.core.reactive.reviewer_runtime.preflight_supervisor_runtime", preflight)
    monkeypatch.setattr("forge.core.runtime.codex_turn_enrollment.require_for_launch", enrollment)
    with pytest.raises(SupervisorInputError, match="shadow"):
        supervisor_set(
            store=store,
            manifest=store.read(),
            target=None,
            policy_forge_root=str(ctx.forge_root),
            plan=ctx.config.plan_override_path,
            model="sonnet",
            review_trigger="stop",
        )
    assert store.manifest_path.read_bytes() == before
    preflight.assert_not_called()
    enrollment.assert_not_called()


def test_concurrent_trigger_override_cannot_commit_unvalidated_stop(tmp_path: Path, monkeypatch) -> None:
    ctx = context(tmp_path)
    store = SessionStore(str(ctx.forge_root), ctx.session)

    def initial(state):
        state.intent.policy.supervisor.review_trigger = "pre-tool-use"

    store.update(timeout_s=1, mutate=initial)
    snapshot = store.read()

    def concurrent(*args, **kwargs):
        def change(state):
            state.overrides = {"policy": {"supervisor": {"review_trigger": "stop"}}}

        store.update(timeout_s=1, mutate=change)

    monkeypatch.setattr("forge.core.reactive.reviewer_runtime.preflight_supervisor_runtime", concurrent)
    enrollment = Mock()
    monkeypatch.setattr("forge.core.runtime.codex_turn_enrollment.require_for_launch", enrollment)
    with pytest.raises(SupervisorInputError, match="changed during setup"):
        supervisor_set(
            store=store,
            manifest=snapshot,
            target=None,
            policy_forge_root=str(ctx.forge_root),
            plan=ctx.config.plan_override_path,
            model="sonnet",
        )
    current = store.read().intent.policy
    assert current is not None and snapshot.intent.policy is not None
    assert current.supervisor == snapshot.intent.policy.supervisor
    enrollment.assert_not_called()
