"""Regression: per-worker cost-provenance precedence (anti-double-count, Phase 5c).

``emit_worker_usage`` mirrors the verb precedence for fan-out leaves:

- Direct worker + self-reported cost -> ``claude_code`` / ``reported`` /
  ``runtime_native`` with its exact in-band tokens.
- Direct worker, tokens-only -> ``provider_usage_exact`` / ``unavailable``.
- Proxied worker -> cost ``None`` / ``unavailable`` with NULL tokens: the verb
  aggregate (``emit_verb_usage``) already holds the estimated proxied total, so
  attributing per-worker cost here would double-count.

Affected: ``src/forge/core/usage/emit.py`` (``emit_worker_usage``).
"""

from __future__ import annotations

import pytest

from forge.core.usage.emit import emit_worker_usage
from forge.core.usage.ledger import read_usage_events

pytestmark = pytest.mark.regression


def _one_event():
    events = read_usage_events()
    assert len(events) == 1, f"expected exactly one event, got {len(events)}"
    return events[0]


def test_direct_worker_self_cost_is_claude_code_runtime_native() -> None:
    emit_worker_usage(
        run_id="w1",
        command="panel",
        status="success",
        session="s1",
        base_url=None,  # direct
        envelope_parsed=True,
        cost_micro_usd=3_000,
        input_tokens=120,
        output_tokens=30,
        cached_tokens=10,
    )
    ev = _one_event()
    assert ev.attribution_granularity == "worker"
    assert ev.reporter == "claude_code"
    assert ev.confidence == "reported"
    assert ev.measurement_source == "runtime_native"
    assert ev.cost_micro_usd == 3_000
    assert ev.input_tokens == 120


def test_direct_worker_tokens_only_is_provider_usage_exact() -> None:
    emit_worker_usage(
        run_id="w2",
        command="panel",
        status="success",
        session="s1",
        base_url=None,
        envelope_parsed=True,
        cost_micro_usd=None,  # OAuth: tokens but no $
        input_tokens=80,
        output_tokens=20,
    )
    ev = _one_event()
    assert ev.reporter is None
    assert ev.confidence == "unavailable"
    assert ev.measurement_source == "provider_usage_exact"
    assert ev.cost_micro_usd is None
    assert ev.input_tokens == 80  # tokens kept


def test_proxied_worker_cost_and_tokens_are_null() -> None:
    # Even if the worker self-reported a cost, a proxied worker attributes NOTHING
    # here -- the verb aggregate owns the proxied total (double-count guard).
    emit_worker_usage(
        run_id="w3",
        command="panel",
        status="success",
        session="s1",
        base_url="http://localhost:8084",  # proxied
        envelope_parsed=True,
        cost_micro_usd=999_999,  # Anthropic-priced self-report -- ignored
        input_tokens=500,
        output_tokens=120,
    )
    ev = _one_event()
    assert ev.reporter is None
    assert ev.confidence == "unavailable"
    assert ev.measurement_source == "unattributed"
    assert ev.cost_micro_usd is None
    assert ev.input_tokens is None  # per-worker proxied tokens left to the aggregate


def test_worker_no_envelope_is_unattributed() -> None:
    # No parsed envelope (e.g. raw-text fallback) -> nothing to attribute.
    emit_worker_usage(
        run_id="w4", command="panel", status="success", session="s1", base_url=None, envelope_parsed=False
    )
    ev = _one_event()
    assert ev.reporter is None
    assert ev.measurement_source == "unattributed"
    assert ev.cost_micro_usd is None
