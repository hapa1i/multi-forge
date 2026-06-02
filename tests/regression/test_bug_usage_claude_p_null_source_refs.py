"""Regression: claude -p usage events must carry null source_refs (Phase 4c).

Forge is NOT the HTTP client for a ``claude -p`` subprocess (Claude is), so it
cannot know the proxy ``request_id`` at emit time. ``emit_usage_for_session_result``
must therefore leave ``source_refs`` null -- a back-reference to a cost record Forge
can't identify would be a dangling/wrong join. Exact per-request correlation for
claude -p is the deferred 4g slice; the event stays useful without it (the verb
snapshot still gives an estimated cost/token figure).

Root cause guard: ``src/forge/core/usage/emit.py::emit_usage_for_session_result``
hardcodes ``source_refs=None``.
"""

from __future__ import annotations

import pytest

from forge.core.reactive.cost_tracking import VerbCostResult
from forge.core.reactive.session_runner import SessionResult
from forge.core.usage.emit import emit_usage_for_session_result
from forge.core.usage.ledger import read_usage_events

pytestmark = pytest.mark.regression


def test_claude_p_verb_event_has_null_source_refs() -> None:
    result = SessionResult(
        stdout="", stderr="", returncode=0, run_id="run_c", parent_run_id="run_par", root_run_id="run_root"
    )
    cost = VerbCostResult(
        verb="memory-writer", total_cost_micros=2500, input_tokens=12, output_tokens=8, measured=True
    )
    emit_usage_for_session_result(
        result, command="memory-writer", session="s", cost=cost, base_url="http://localhost:8084"
    )

    events = read_usage_events()
    assert len(events) == 1
    e = events[0]
    # The estimated cost figure is present; the exact wire back-reference is not.
    assert e.cost_micro_usd == 2500
    assert e.measurement_source == "verb_snapshot_estimated"
    assert e.source_refs is None
