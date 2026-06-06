"""Regression: a token-only envelope keeps exact tokens with cost unavailable.

The conflation this guards (#1): treating "parsed an envelope" and "has a cost"
as the same fact. A direct OAuth ``claude -p`` reports exact ``usage`` but no
``total_cost_usd``. That run must record its exact in-band tokens
(``measurement_source="provider_usage_exact"``) while cost stays honestly
``unavailable`` (``reporter=None``) -- the tokens are a real win and must NOT be
dropped just because no dollar figure came back.

Affected: ``src/forge/core/usage/emit.py`` (direct branch of
``emit_usage_for_session_result``).
"""

from __future__ import annotations

import pytest

from forge.core.reactive.session_runner import SessionResult
from forge.core.usage.emit import emit_usage_for_session_result
from forge.core.usage.ledger import read_usage_events

pytestmark = pytest.mark.regression


def _direct_token_only_result() -> SessionResult:
    return SessionResult(
        stdout="text",
        stderr="",
        returncode=0,
        run_id="run-tokens",
        root_run_id="run-tokens",
        envelope_parsed=True,
        cost_micro_usd=None,  # direct OAuth: no dollar figure
        input_tokens=150,
        output_tokens=40,
        cached_tokens=20,
    )


def test_token_only_direct_keeps_tokens_cost_unavailable() -> None:
    emit_usage_for_session_result(
        _direct_token_only_result(),
        command="memory-writer",
        cost=None,
        session="s1",
        base_url=None,  # direct
        direct=True,
    )

    events = read_usage_events()
    assert len(events) == 1
    ev = events[0]
    assert ev.measurement_source == "provider_usage_exact"
    assert ev.confidence == "unavailable"
    assert ev.reporter is None
    assert ev.cost_micro_usd is None
    # The tokens are NOT dropped -- they are exact provider evidence.
    assert ev.input_tokens == 150
    assert ev.output_tokens == 40
    assert ev.cached_tokens == 20
    assert ev.route == "claude_p"
