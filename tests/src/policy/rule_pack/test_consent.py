"""Paid data-sharing permission belongs to a session instance, not its lineage."""

from copy import deepcopy

import pytest

from forge.policy.rule_pack.consent import (
    ACKNOWLEDGMENT_KEY,
    BUNDLE_NAME,
    build_acknowledgment,
    has_acknowledgment,
    revoke_acknowledgment,
    strip_inherited_activation,
)
from forge.session.models import PolicyIntent, create_session_state
from forge.session.store import SessionStore


@pytest.fixture
def session(tmp_path):
    state = create_session_state("parent", worktree_path=str(tmp_path))
    state.forge_root = str(tmp_path)
    state.intent.policy = PolicyIntent(enabled=True, bundles=["tdd", BUNDLE_NAME])
    settings = {"pack_version": "candidate-1", "model": "typesafe/jev-1.13", "timeout_seconds": 5}
    grant = build_acknowledgment(state, settings, acknowledge_paid_data_sharing=True)
    state.intent.policy.bundle_config = {
        "tdd": {"strict": False},
        BUNDLE_NAME: {**settings, ACKNOWLEDGMENT_KEY: grant},
    }
    return state


def test_same_instance_retains_acknowledgment_through_strict_store_roundtrip(session):
    store = SessionStore(session.forge_root, session.name)
    store.write(session)
    loaded = store.read()
    assert has_acknowledgment(loaded, loaded.intent.policy.bundle_config[BUNDLE_NAME])
    assert loaded.schema_version == 3  # The existing ordinary-session writer needs no schema bump for bundle config.


def test_acknowledgment_does_not_authenticate_arbitrary_local_manifest_writers(session):
    copied = deepcopy(session)
    copied.name = "another-session"
    config = copied.intent.policy.bundle_config[BUNDLE_NAME]
    assert not has_acknowledgment(copied, config)
    settings = {key: value for key, value in config.items() if key != ACKNOWLEDGMENT_KEY}
    config[ACKNOWLEDGMENT_KEY] = build_acknowledgment(copied, settings, acknowledge_paid_data_sharing=True)
    assert has_acknowledgment(copied, config)


@pytest.mark.parametrize("value", [False, None, "true", 1])
def test_grant_requires_explicit_boolean_acknowledgment(session, value):
    with pytest.raises(ValueError, match="Explicit acknowledgment"):
        build_acknowledgment(session, {}, acknowledge_paid_data_sharing=value)


@pytest.mark.parametrize("field", ["name", "created_at", "forge_root", "worktree", "model", "pack_version"])
def test_copied_or_changed_scope_requires_a_new_acknowledgment(session, field):
    copied = deepcopy(session)
    config = copied.intent.policy.bundle_config[BUNDLE_NAME]
    if field == "worktree":
        copied.worktree.path += "/other"
    elif field in {"model", "pack_version"}:
        config[field] += "-changed"
    else:
        setattr(copied, field, getattr(copied, field) + "-changed")
    assert not has_acknowledgment(copied, config)
    assert has_acknowledgment(session, session.intent.policy.bundle_config[BUNDLE_NAME])


@pytest.mark.parametrize(
    "mutation",
    [
        lambda config: config.pop(ACKNOWLEDGMENT_KEY),
        lambda config: config[ACKNOWLEDGMENT_KEY].update(version=True),
        lambda config: config[ACKNOWLEDGMENT_KEY].update(disclosure_version=2),
        lambda config: config[ACKNOWLEDGMENT_KEY].update(zdr_required=1),
        lambda config: config[ACKNOWLEDGMENT_KEY].update(extra="unrecognized"),
        lambda config: config[ACKNOWLEDGMENT_KEY].update(endpoint="https://another.invalid"),
        lambda config: config.update(timeout_seconds=float("nan")),
    ],
)
def test_malformed_acknowledgment_fails_closed(session, mutation):
    config = session.intent.policy.bundle_config[BUNDLE_NAME]
    mutation(config)
    assert not has_acknowledgment(session, config)


def test_revoke_clears_both_layers_without_changing_ordinary_configuration(session):
    session.overrides = {"policy": {"bundle_config": deepcopy(session.intent.policy.bundle_config)}}
    revoke_acknowledgment(session)
    for config in (session.intent.policy.bundle_config, session.overrides["policy"]["bundle_config"]):
        assert ACKNOWLEDGMENT_KEY not in config[BUNDLE_NAME]
        assert config["tdd"] == {"strict": False}
    assert session.intent.policy.bundles == ["tdd", BUNDLE_NAME]


def test_child_removes_selection_and_config_in_both_layers(session):
    session.overrides = {
        "policy": {"enabled": True, "bundles": ["coding_standards", BUNDLE_NAME], "bundle_config": {BUNDLE_NAME: {}}},
        "memory": {"auto_recall": False},
    }
    child = deepcopy(session)
    strip_inherited_activation(child)
    assert child.intent.policy.enabled
    assert child.intent.policy.bundles == ["tdd"]
    assert child.intent.policy.bundle_config == {"tdd": {"strict": False}}
    assert child.overrides == {
        "policy": {"enabled": True, "bundles": ["coding_standards"], "bundle_config": {}},
        "memory": {"auto_recall": False},
    }
    assert has_acknowledgment(session, session.intent.policy.bundle_config[BUNDLE_NAME])
