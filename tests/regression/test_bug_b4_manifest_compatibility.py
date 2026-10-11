"""Stop intent must be versioned without changing ordinary session serialization."""

import json

import pytest

from forge.session.exceptions import ManifestCorruptedError
from forge.session.models import PolicyIntent, SupervisorConfig, create_session_state
from forge.session.store import SessionStore, manifest_for_write

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("explicit_model, expected", [(None, 2), ("opus", 3)])
def test_default_trigger_keeps_legacy_shape(explicit_model, expected):
    state = create_session_state(name="normal")
    state.intent.policy = PolicyIntent(
        supervisor=SupervisorConfig(resume_id="planner", supervisor_model=explicit_model)
    )
    state.overrides = {"policy": {"supervisor": {"review_trigger": "pre-tool-use"}}}
    written = manifest_for_write(state)
    assert written["schema_version"] == expected
    assert "review_trigger" not in written["intent"]["policy"]["supervisor"]
    assert "review_trigger" not in written["overrides"]["policy"]["supervisor"]


@pytest.mark.parametrize(
    "intent_trigger, override", [("stop", None), ("stop", "pre-tool-use"), ("pre-tool-use", "stop")]
)
def test_nondefault_intent_or_override_requires_v4(intent_trigger, override):
    state = create_session_state(name="stopped", runtime="codex")
    state.intent.policy = PolicyIntent(
        supervisor=SupervisorConfig(plan_override_path="/plan.md", review_trigger=intent_trigger)
    )
    if override:
        state.overrides = {"policy": {"supervisor": {"review_trigger": override}}}
    written = manifest_for_write(state)
    assert written["schema_version"] == 4
    assert written["intent"]["policy"]["supervisor"]["review_trigger"] == intent_trigger
    if override:
        assert written["overrides"]["policy"]["supervisor"]["review_trigger"] == override


def test_old_reader_refuses_version_and_default_restores_v2(tmp_path, monkeypatch):
    import forge.session.store as store_module

    state = create_session_state(name="stopped", runtime="codex")
    state.intent.policy = PolicyIntent(
        supervisor=SupervisorConfig(plan_override_path="/plan.md", review_trigger="stop")
    )
    store = SessionStore(str(tmp_path), state.name)
    store.write(state)
    assert store.read().intent.policy.supervisor.review_trigger == "stop"
    monkeypatch.setattr(store_module, "_SUPPORTED_SCHEMA_VERSIONS", {1, 2, 3})
    with pytest.raises(ManifestCorruptedError, match="schema version"):
        store.read()
    state.intent.policy.supervisor.review_trigger = "pre-tool-use"
    store.write(state)
    assert store.read().intent.policy.supervisor.review_trigger == "pre-tool-use"
    assert json.loads(store.manifest_path.read_text())["schema_version"] == 2


@pytest.mark.parametrize("version", [1, 2, 3])
@pytest.mark.parametrize("location", ["intent", "overrides"])
def test_old_schema_cannot_smuggle_trigger(tmp_path, version, location):
    state = create_session_state(name="bad", runtime="codex")
    state.intent.policy = PolicyIntent(supervisor=SupervisorConfig(resume_id="planner"))
    data = manifest_for_write(state)
    data["schema_version"] = version
    if version == 1:
        data["intent"]["launch"].pop("model_route", None)
    if version == 3:
        data["intent"]["policy"]["supervisor"].update(auth_mode="inherit", supervisor_model=None)
    data[location].setdefault("policy", {}).setdefault("supervisor", {})["review_trigger"] = "stop"
    store = SessionStore(str(tmp_path), state.name)
    store.session_dir.mkdir(parents=True)
    store.manifest_path.write_text(json.dumps(data))
    with pytest.raises(ManifestCorruptedError, match="cannot contain supervisor.review_trigger"):
        store.read()


@pytest.mark.parametrize("field, value", [("cascade", True), ("shadow_sample_rate", 0.5)])
def test_stop_rejects_extra_dispatch_sources(field, value):
    with pytest.raises(ValueError, match="one frontier review"):
        SupervisorConfig(review_trigger="stop", **{field: value})
