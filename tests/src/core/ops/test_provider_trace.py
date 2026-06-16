"""Unit tests for the Phase 4 provider-trace command-core ops."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from forge.core.ops import (
    ForgeOpError,
    explain_provider_trace,
    list_provider_traces,
    render_explanation_lines,
    show_provider_trace,
)
from forge.core.ops.context import ExecutionContext
from forge.core.run_id import derive_provider_session_id
from forge.proxy import cost_logger
from forge.proxy import provider_trace_logger as ptl


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    # Fresh FORGE_HOME per test so trace + cost shards never leak across tests.
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    ptl._warned_newer_schema = False
    cost_logger._warned_newer_schema = False
    yield
    ptl._warned_newer_schema = False
    cost_logger._warned_newer_schema = False


def _ctx() -> ExecutionContext:
    return ExecutionContext.from_cwd()


def _record(**kw: Any) -> None:
    params: dict[str, Any] = dict(
        provider_name="openrouter",
        request_mode="streaming",
        request_id="req-1",
        proxy_id="crimson-apricot",
        mapped_model="openai/gpt-5.5",
        forge_run_id="run_abc",
        forge_root_run_id="run_root",
        provider_session_id="forge_sess_abc_supervisor",
        provider_command="supervisor",
        provider_meta={"provider": "openrouter", "selected_provider": "Azure", "provider_generation_id": "gen-xyz"},
        stream_started=True,
        first_chunk_seen=True,
        final_usage_seen=True,
        client_disconnected=False,
        reported_cost_micros=1234,
        latency_ms=42.0,
    )
    params.update(kw)
    ptl.record_provider_trace(**params)


class TestList:
    def test_returns_records(self):
        _record(request_id="req-1")
        _record(request_id="req-2")
        result = list_provider_traces(ctx=_ctx())
        assert {r.request_id for r in result.traces} == {"req-1", "req-2"}

    def test_session_label_prefix_match_and_fallback_nonmatch(self):
        # A label-derived id matches the session name; a no-label fallback id does NOT.
        labeled = derive_provider_session_id("alpha", root_run_id="x", role="supervisor")
        fallback = derive_provider_session_id(None, root_run_id="run_zzz", role="review")
        _record(request_id="req-a", provider_session_id=labeled)
        _record(request_id="req-b", provider_session_id=fallback)
        result = list_provider_traces(ctx=_ctx(), session="alpha")
        assert [r.request_id for r in result.traces] == ["req-a"]

    def test_root_run_id_filter_is_exact(self):
        _record(request_id="req-a", forge_root_run_id="run_one")
        _record(request_id="req-b", forge_root_run_id="run_two")
        result = list_provider_traces(ctx=_ctx(), root_run_id="run_two")
        assert [r.request_id for r in result.traces] == ["req-b"]

    def test_limit_caps_results(self):
        for i in range(5):
            _record(request_id=f"req-{i}")
        result = list_provider_traces(ctx=_ctx(), limit=2)
        assert len(result.traces) == 2


class TestShow:
    def test_returns_record(self):
        _record(request_id="req-1")
        result = show_provider_trace(ctx=_ctx(), request_id="req-1")
        assert result.record.request_id == "req-1"

    def test_missing_raises(self):
        with pytest.raises(ForgeOpError):
            show_provider_trace(ctx=_ctx(), request_id="nope")


class TestExplain:
    def test_incident_narrative(self):
        _record(request_id="req-incident", final_usage_seen=False, client_disconnected=True, reported_cost_micros=None)
        exp = explain_provider_trace(ctx=_ctx(), request_id="req-incident")
        assert exp.left_forge is True
        assert exp.remote_lookup_performed is False
        lines = render_explanation_lines(exp)
        text = "\n".join(lines)
        assert "left Forge via proxy crimson-apricot" in text
        assert "unavailable, not zero" in text
        assert lines[-1] == "No remote lookup was performed."

    def test_missing_raises(self):
        with pytest.raises(ForgeOpError):
            explain_provider_trace(ctx=_ctx(), request_id="nope")

    def test_cost_confidence_enriched_in_window(self):
        _record(request_id="req-cost", final_usage_seen=True, reported_cost_micros=1500)
        cost_logger.log_request_cost(
            proxy_id="crimson-apricot",
            model="openai/gpt-5.5",
            tier="opus",
            input_tokens=10,
            output_tokens=20,
            cached_tokens=0,
            cost_micros=1500,
            latency_ms=42.0,
            failed=False,
            request_id="req-cost",
            confidence="reported",
        )
        exp = explain_provider_trace(ctx=_ctx(), request_id="req-cost")
        assert exp.cost_confidence == "reported"
        assert exp.reported_cost_micros == 1500

    def test_cost_confidence_ignores_other_request_id(self):
        _record(request_id="req-x", reported_cost_micros=1500)
        cost_logger.log_request_cost(
            proxy_id="crimson-apricot",
            model="openai/gpt-5.5",
            tier="opus",
            input_tokens=10,
            output_tokens=20,
            cached_tokens=0,
            cost_micros=999,
            latency_ms=1.0,
            failed=False,
            request_id="DIFFERENT",
            confidence="reported",
        )
        exp = explain_provider_trace(ctx=_ctx(), request_id="req-x")
        assert exp.cost_confidence is None

    def test_cost_confidence_ignores_out_of_window(self, tmp_path):
        # Same request_id but the cost record is 2h before the trace -> outside ±5m -> ignored.
        _record(request_id="req-old", reported_cost_micros=1500)
        old_ts = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        costs_dir = Path(tmp_path) / "costs" / "requests"
        costs_dir.mkdir(parents=True, exist_ok=True)
        stale = {
            "schema_version": 1,
            "ts": old_ts,
            "request_id": "req-old",
            "confidence": "reported",
            "cost_micros": 1500,
        }
        (costs_dir / "2000-01_stale.jsonl").write_text(json.dumps(stale) + "\n")
        exp = explain_provider_trace(ctx=_ctx(), request_id="req-old")
        assert exp.cost_confidence is None
