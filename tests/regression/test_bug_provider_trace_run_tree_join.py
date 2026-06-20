"""Regression: provider traces join by run tree, preserving claude -p semantics.

One proxied ``claude -p`` runtime run produces MANY proxy requests (one per turn/tool hop).
The design invariant (card §4, design.md §3.14) is that the telemetry planes stay physically
separate and join by shared ``request_id`` + run-tree ids. The usage plane's complementary
half — that ``claude -p`` usage events may leave ``source_refs`` null — is guarded separately
by ``test_bug_usage_claude_p_null_source_refs.py``.

This guards that the NEW provider-trace plane upholds the join model:
1. A trace carries ``forge_root_run_id`` (the run-tree key) and a per-request ``request_id``,
   so N traces from one run are correlatable by root run id yet individually addressable.
2. The trace plane has no ``source_refs`` field — it does not duplicate the usage plane's
   attribution concept; the planes stay separate.

Affected files: src/forge/proxy/provider_trace_logger.py.
"""

from __future__ import annotations

from dataclasses import fields

import pytest

from forge.proxy import provider_trace_logger as ptl

pytestmark = pytest.mark.regression


def _record(request_id: str, root: str) -> None:
    ptl.record_provider_trace(
        backend_id="openrouter",
        request_mode="streaming",
        proxy_id="p",
        mapped_model="openai/gpt-5.5",
        request_id=request_id,
        forge_run_id=f"run_{request_id}",
        forge_root_run_id=root,
        provider_session_id="forge_sess_x",
        provider_command="panel",
        provider_meta={"provider": "openrouter", "provider_generation_id": f"gen-{request_id}"},
        stream_started=True,
        first_chunk_seen=True,
        final_usage_seen=True,
        client_disconnected=False,
        reported_cost_micros=100,
        latency_ms=5.0,
    )


def test_many_requests_one_run_join_by_root_run_id(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    ptl._warned_newer_schema = False
    # One claude -p run (root_run_id="run_root") emits three proxy requests.
    for rid in ("req-1", "req-2", "req-3"):
        _record(rid, "run_root")
    # A second, unrelated run.
    _record("req-other", "run_other")

    by_run = ptl.read_provider_traces(forge_root_run_id="run_root")
    assert {r.request_id for r in by_run} == {"req-1", "req-2", "req-3"}  # run-tree join
    assert all(r.forge_root_run_id == "run_root" for r in by_run)
    # Individually addressable too (per-request granularity preserved).
    one = ptl.read_provider_traces(request_id="req-2")
    assert len(one) == 1 and one[0].provider_generation_id == "gen-req-2"


def test_trace_plane_has_no_source_refs_field():
    # source_refs is the usage plane's attribution concept; the trace plane stays separate.
    names = {f.name for f in fields(ptl.ProviderTraceRecord)}
    assert "source_refs" not in names
