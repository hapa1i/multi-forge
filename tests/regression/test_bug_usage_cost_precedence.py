"""Regression: verb-level cost-provenance precedence (anti-double-count, Phase 5c).

The non-negotiable guardrail: EXACTLY ONE reporter attributes cost per run --
``forge_proxy`` (proxied) XOR ``claude_code`` (direct self-report) XOR none
(``unavailable``). Two failure modes this pins:

1. Double-count: a proxied run must take the proxy snapshot cost (Anthropic-priced
   self-report ignored), never both.
2. Mixed provenance: a ``verb_snapshot_estimated`` event must carry SNAPSHOT tokens,
   never the exact in-band tokens from the envelope (#4) -- tokens follow the cost
   source so one event never blends two measurement sources.

Sits beside ``test_bug_usage_workflow_double_count.py``.
Affected: ``src/forge/core/usage/emit.py`` (``emit_usage_for_session_result``).
"""

from __future__ import annotations

import pytest

from forge.core.reactive.cost_tracking import VerbCostResult
from forge.core.reactive.session_runner import SessionResult
from forge.core.usage.emit import emit_usage_for_session_result
from forge.core.usage.ledger import read_usage_events

pytestmark = pytest.mark.regression


def _result(**overrides: object) -> SessionResult:
    base: dict[str, object] = {
        "stdout": "t",
        "stderr": "",
        "returncode": 0,
        "run_id": "r",
        "root_run_id": "r",
    }
    base.update(overrides)
    return SessionResult(**base)  # type: ignore[arg-type]


def _proxy_cost() -> VerbCostResult:
    return VerbCostResult(
        verb="memory-writer",
        total_cost_micros=50_000,
        input_tokens=300,
        output_tokens=80,
        cached_tokens=40,
        measured=True,
        cost_measured=True,
    )


def _one_event():
    events = read_usage_events()
    assert len(events) == 1, f"expected exactly one event, got {len(events)}"
    return events[0]


def test_proxied_run_uses_proxy_cost_and_snapshot_tokens() -> None:
    # Proxied AND the self-report present: the proxy figure wins, the Anthropic-priced
    # self-report is ignored, and tokens come from the SNAPSHOT (not the envelope).
    result = _result(
        envelope_parsed=True,
        cost_micro_usd=999_999,  # self-reported $ -- must be IGNORED
        input_tokens=111,  # in-band tokens -- must be IGNORED (no mixed provenance)
        output_tokens=22,
        cached_tokens=3,
    )
    emit_usage_for_session_result(
        result, command="memory-writer", cost=_proxy_cost(), session="s1", base_url="http://localhost:8084"
    )

    ev = _one_event()
    assert ev.reporter == "forge_proxy"
    assert ev.confidence == "reported"
    assert ev.measurement_source == "verb_snapshot_estimated"
    assert ev.cost_micro_usd == 50_000  # proxy snapshot, NOT 999_999
    # #4: snapshot tokens, never the exact in-band tokens.
    assert ev.input_tokens == 300
    assert ev.output_tokens == 80
    assert ev.cached_tokens == 40


def test_proxied_token_only_snapshot_is_verb_snapshot_estimated() -> None:
    # A proxied window can move tokens but report no cost (measured=True,
    # cost_measured=False). The snapshot tokens are emitted, so the event MUST read
    # as verb_snapshot_estimated (the figure source) -- never "unattributed", which
    # claims no figure while carrying token figures. Cost stays unavailable.
    token_only = VerbCostResult(
        verb="memory-writer",
        total_cost_micros=0,
        input_tokens=300,
        output_tokens=80,
        cached_tokens=40,
        measured=True,
        cost_measured=False,
    )
    emit_usage_for_session_result(
        _result(), command="memory-writer", cost=token_only, session="s1", base_url="http://localhost:8084"
    )
    ev = _one_event()
    assert ev.measurement_source == "verb_snapshot_estimated"  # NOT unattributed
    assert ev.input_tokens == 300  # snapshot tokens carried
    assert ev.output_tokens == 80
    assert ev.cached_tokens == 40
    assert ev.cost_micro_usd is None  # no dollar figure reported
    assert ev.reporter is None
    assert ev.confidence == "unavailable"


def test_proxied_run_without_proxy_cost_is_unavailable() -> None:
    # Proxied but no reported-cost window: cost unavailable, tokens null (the proxy
    # plane has no figure to attribute, and we never fabricate one).
    emit_usage_for_session_result(
        _result(), command="supervisor", cost=None, session="s1", base_url="http://localhost:8084"
    )
    ev = _one_event()
    assert ev.reporter is None
    assert ev.confidence == "unavailable"
    assert ev.measurement_source == "unattributed"
    assert ev.cost_micro_usd is None
    assert ev.input_tokens is None


def test_direct_run_self_reports_cost_runtime_native() -> None:
    # Direct (no proxy) + parsed envelope with a dollar figure: the runtime
    # self-reports -- the first emission of claude_code / runtime_native.
    result = _result(envelope_parsed=True, cost_micro_usd=4_200, input_tokens=200, output_tokens=50, cached_tokens=10)
    emit_usage_for_session_result(result, command="memory-writer", cost=None, session="s1", base_url=None, direct=True)

    ev = _one_event()
    assert ev.reporter == "claude_code"
    assert ev.confidence == "reported"
    assert ev.measurement_source == "runtime_native"
    assert ev.cost_micro_usd == 4_200
    assert ev.input_tokens == 200  # exact in-band tokens belong to the runtime-sourced event


def test_direct_run_neither_cost_nor_envelope_is_unavailable() -> None:
    emit_usage_for_session_result(
        _result(envelope_parsed=False), command="memory-writer", cost=None, session="s1", base_url=None, direct=True
    )
    ev = _one_event()
    assert ev.reporter is None
    assert ev.confidence == "unavailable"
    assert ev.measurement_source == "unattributed"
    assert ev.cost_micro_usd is None
    assert ev.input_tokens is None


def test_exactly_one_reporter_across_the_matrix() -> None:
    # Drive all four branches; every emitted event has at most one cost reporter,
    # and a reported cost always pairs with a reporter (never an orphaned figure).
    emit_usage_for_session_result(
        _result(envelope_parsed=True, cost_micro_usd=7_000, input_tokens=1),
        command="c-direct-self", cost=None, session="s1", base_url=None, direct=True,
    )
    emit_usage_for_session_result(
        _result(envelope_parsed=True, cost_micro_usd=None, input_tokens=9),
        command="c-direct-tokens", cost=None, session="s1", base_url=None, direct=True,
    )
    emit_usage_for_session_result(
        _result(), command="c-proxy-cost", cost=_proxy_cost(), session="s1", base_url="http://x",
    )
    emit_usage_for_session_result(
        _result(), command="c-none", cost=None, session="s1", base_url=None, direct=True,
    )

    events = read_usage_events()
    assert len(events) == 4
    for ev in events:
        assert ev.reporter in (None, "forge_proxy", "claude_code")
        # A reported cost must have a reporter; an unavailable cost must not.
        if ev.cost_micro_usd is not None:
            assert ev.confidence == "reported" and ev.reporter is not None
        else:
            assert ev.confidence == "unavailable" and ev.reporter is None
