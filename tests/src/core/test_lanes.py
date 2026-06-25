"""Unit tests for the pure lane/consumer resolver (T1a)."""

from __future__ import annotations

import builtins

import pytest

from forge.core.lanes import (
    Consumer,
    Lane,
    LaneError,
    resolve_lane,
    runtime_execution,
    valid_lanes,
)
from forge.core.runtime.registry import RUNTIMES, list_runtimes

# Real ids from the code-defined catalogs. ``model`` is a free non-empty id in
# T1a (no model-catalog dependency).
_AGENT_BACKEND = "anthropic-direct"
_REMOTE_BACKEND = "openrouter"


def _agent_lane(model: str = "m") -> Lane:
    return Lane("claude_code", _AGENT_BACKEND, model)


def _single_shot_lane(model: str = "m") -> Lane:
    return Lane("core_llm", _REMOTE_BACKEND, model)


def _codex_lane(model: str = "m") -> Lane:
    return Lane("codex", _REMOTE_BACKEND, model)


# --- runtime_execution / RUNTIMES integrity ---


def test_runtime_execution_classifies_agents_and_core_llm():
    assert runtime_execution("claude_code") == "tool_agent"
    assert runtime_execution("codex") == "tool_agent"
    assert runtime_execution("gemini") == "tool_agent"
    assert runtime_execution("core_llm") == "single_shot"


def test_runtime_execution_unknown_raises():
    with pytest.raises(LaneError):
        runtime_execution("nope")


def test_runtimes_table_not_polluted_by_core_llm():
    # Regression guard for the option-2 decision: core_llm must never enter the
    # agent runtime registry that list_runtimes()/installed_runtimes() iterate.
    assert "core_llm" not in RUNTIMES
    assert all(spec.id != "core_llm" for spec in list_runtimes())


# --- Lane construction validation ---


def test_lane_rejects_unknown_runtime():
    with pytest.raises(LaneError):
        Lane("nope", _AGENT_BACKEND, "m")


def test_lane_rejects_unknown_backend():
    with pytest.raises(LaneError):
        Lane("claude_code", "no-such-backend", "m")


def test_lane_rejects_empty_model():
    with pytest.raises(LaneError):
        Lane("claude_code", _AGENT_BACKEND, "")


def test_lane_normalizes_backend_alias_to_canonical():
    # resolve_model_source_id accepts template aliases; Lane stores the canonical
    # ModelSource id so alias and canonical lanes are equal and get_model_source
    # resolves downstream.
    aliased = Lane("claude_code", "openrouter-openai", "m")
    assert aliased.backend_id == "openrouter"
    assert aliased == Lane("claude_code", "openrouter", "m")


# --- resolve_lane / valid_lanes ---


def test_default_no_override_returns_default():
    consumer = Consumer("supervisor", "tool_agent", _agent_lane())
    assert resolve_lane(consumer) == _agent_lane()


def test_invalid_default_rejected_at_construction():
    # A tool_agent-floor consumer whose default is a single-shot lane is invalid.
    with pytest.raises(LaneError):
        Consumer("supervisor", "tool_agent", _single_shot_lane())


def test_floor_excludes_single_shot():
    consumer = Consumer(
        "supervisor",
        "tool_agent",
        _agent_lane(),
        allowed_lanes=(_single_shot_lane(),),
    )
    assert _single_shot_lane() not in valid_lanes(consumer)
    with pytest.raises(LaneError):
        resolve_lane(consumer, override=_single_shot_lane())


def test_floor_admits_single_shot():
    consumer = Consumer(
        "tagger",
        "single_shot",
        _single_shot_lane(),
        allowed_lanes=(_agent_lane(),),
    )
    lanes = valid_lanes(consumer)
    assert _single_shot_lane() in lanes
    assert _agent_lane() in lanes


def test_declared_valid_override_resolves():
    consumer = Consumer("supervisor", "tool_agent", _agent_lane(), allowed_lanes=(_codex_lane(),))
    assert resolve_lane(consumer, override=_codex_lane()) == _codex_lane()


def test_valid_lanes_is_declared_set_not_cross_product():
    # Only declared candidates appear -- not every (runtime, backend, model).
    consumer = Consumer("supervisor", "tool_agent", _agent_lane())
    assert valid_lanes(consumer) == (_agent_lane(),)


def test_override_not_in_declared_set_rejected():
    # A floor+reachable lane the consumer did not declare is still rejected:
    # overrides are an allow-list, not "any compatible lane".
    consumer = Consumer("supervisor", "tool_agent", _agent_lane())
    with pytest.raises(LaneError):
        resolve_lane(consumer, override=_codex_lane())


# --- purity ---


def test_resolve_lane_does_no_file_io(monkeypatch):
    consumer = Consumer("supervisor", "tool_agent", _agent_lane(), allowed_lanes=(_codex_lane(),))

    def _boom(*args, **kwargs):
        del args, kwargs  # must match open()'s signature; values are unused
        raise AssertionError("resolve_lane performed file I/O")

    monkeypatch.setattr(builtins, "open", _boom)
    assert resolve_lane(consumer, override=_codex_lane()) == _codex_lane()
    assert resolve_lane(consumer) == _agent_lane()
