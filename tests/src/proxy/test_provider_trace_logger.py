"""Unit tests for the Phase 3 provider-trace plane (write/read/gate/prune/perms)."""

from __future__ import annotations

import json
import os
import time
from dataclasses import fields
from typing import Any

import pytest

from forge.core.telemetry import downstream as downstream_telemetry
from forge.core.telemetry.downstream import DownstreamRecord
from forge.proxy import provider_trace_logger as ptl


@pytest.fixture(autouse=True)
def _isolated_traces_home(tmp_path, monkeypatch):
    # Fresh FORGE_HOME per test so trace shards never leak across tests.
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    ptl._warned_newer_schema = False
    downstream_telemetry._warned_newer_schema = False
    yield
    ptl._warned_newer_schema = False
    downstream_telemetry._warned_newer_schema = False


def _record(provider_name: str = "openrouter", **kw: Any) -> None:
    # dict[str, Any] so the **splat into record_provider_trace's typed kwargs typechecks.
    params: dict[str, Any] = dict(
        request_mode="streaming",
        request_id="req-1",
        proxy_id="crimson-apricot",
        mapped_model="openai/gpt-5.5",
        forge_run_id="run_abc",
        forge_root_run_id="run_root",
        provider_session_id="forge_sess_abc_supervisor",
        provider_command="supervisor",
        provider_meta={"provider": "openrouter", "provider_generation_id": "gen-xyz"},
        stream_started=True,
        first_chunk_seen=True,
        final_usage_seen=True,
        client_disconnected=False,
        reported_cost_micros=1234,
        latency_ms=42.0,
    )
    params.update(kw)
    ptl.record_provider_trace(provider_name=provider_name, **params)


def _downstream_dir():
    return downstream_telemetry._downstream_dir()


def _downstream_path():
    return downstream_telemetry._current_log_path()


class TestGateAndRoundTrip:
    def test_openrouter_record_round_trips_typed(self):
        _record()
        recs = ptl.read_provider_traces()
        assert len(recs) == 1
        rec = recs[0]
        assert isinstance(rec, ptl.ProviderTraceRecord)
        assert rec.request_id == "req-1"
        assert rec.proxy_id == "crimson-apricot"
        assert rec.mapped_model == "openai/gpt-5.5"
        assert rec.provider_generation_id == "gen-xyz"
        assert rec.provider_session_id == "forge_sess_abc_supervisor"
        assert rec.request_mode == "streaming"
        assert rec.timeout_seen is False  # never proxy-populated

    def test_litellm_gateway_route_writes_no_trace_by_design(self):
        # Direct-OpenRouter-only is intentional scope for this card: gateway-routed OpenRouter
        # (LiteLLM -> OpenRouter) and any non-OpenRouter route write NOTHING. This is a
        # deliberate gate, not an accidental miss.
        _record(provider_name="litellm")
        _record(provider_name="unknown")
        assert ptl.read_provider_traces() == []
        assert not _downstream_dir().is_dir() or not list(_downstream_dir().glob("*.jsonl"))

    def test_local_usage_status_available_from_final_usage(self):
        _record(final_usage_seen=True, reported_cost_micros=None)
        assert ptl.read_provider_traces()[0].local_usage_status == "available"

    def test_local_usage_status_available_from_cost(self):
        _record(final_usage_seen=False, reported_cost_micros=900)
        assert ptl.read_provider_traces()[0].local_usage_status == "available"

    def test_local_usage_status_unavailable_is_the_incident(self):
        # Stream cancelled before final usage and no cost reported -> honestly unavailable.
        _record(final_usage_seen=False, reported_cost_micros=None, client_disconnected=True)
        rec = ptl.read_provider_traces()[0]
        assert rec.local_usage_status == "unavailable"
        assert rec.client_disconnected is True

    def test_filters_by_request_and_run(self):
        _record(request_id="a", forge_root_run_id="root-a")
        _record(request_id="b", forge_root_run_id="root-b")
        assert {r.request_id for r in ptl.read_provider_traces(request_id="a")} == {"a"}
        assert {r.request_id for r in ptl.read_provider_traces(forge_root_run_id="root-b")} == {"b"}


class TestHeaderBypassGuard:
    def test_writer_refilters_headers_even_if_caller_bypasses_allowlist(self):
        # A future caller hands raw headers including secrets; the writer re-applies the
        # Phase 2 allowlist, so only allowlisted names+values can persist.
        _record(
            provider_meta={
                "provider": "openrouter",
                "headers": {
                    "x-request-id": "req-allow",
                    "authorization": "Bearer sk-secret",
                    "set-cookie": "session=abc",
                    "x-api-key": "k-secret",
                },
            }
        )
        rec = ptl.read_provider_traces()[0]
        assert rec.headers == {"x-request-id": "req-allow"}

    def test_no_secret_key_in_raw_persisted_line(self):
        _record(provider_meta={"headers": {"authorization": "Bearer s", "x-generation-id": "gen-9"}})
        line = _downstream_path().read_text()
        assert "authorization" not in line.lower()
        assert "Bearer" not in line
        assert "x-generation-id" in line  # the allowlisted one survived


class TestMetadataOnly:
    def test_record_carries_no_body_or_prompt_fields(self):
        _record()
        rec_keys = set(json.loads(_downstream_path().read_text().splitlines()[0]))
        forbidden = {
            "messages",
            "prompt",
            "completion",
            "content",
            "request_body",
            "response_body",
            "tool_calls",
            "tool_input",
            "system",
            "text",
        }
        assert rec_keys.isdisjoint(forbidden)
        # The persisted key set belongs to the unified downstream schema (no surprise payload).
        assert rec_keys <= {f.name for f in fields(DownstreamRecord)}


class TestPlaneRobustness:
    def test_newer_schema_skipped_with_one_warning(self, caplog):
        _record()  # a valid v1 record
        path = _downstream_path()
        with open(path, "a") as f:
            f.write(json.dumps({"schema_version": 99, "kind": "attempt", "downstream_event_id": "ds_future"}) + "\n")
        with caplog.at_level("WARNING"):
            recs = ptl.read_provider_traces()
        assert all(r.schema_version == 1 for r in recs)
        assert "future" not in {r.request_id for r in recs}
        assert sum("newer Forge" in m for m in caplog.messages) == 1

    def test_unknown_field_is_corruption(self):
        _record()
        path = _downstream_path()
        good = json.loads(path.read_text().splitlines()[0])
        bad = {**good, "unexpected_field": 1, "request_id": "corrupt"}
        with open(path, "a") as f:
            f.write(json.dumps(bad) + "\n")
        recs = ptl.read_provider_traces()
        # strict dacite rejects the unknown-field row; the clean row still loads.
        assert {r.request_id for r in recs} == {"req-1"}

    def test_bad_literal_value_is_corruption(self):
        _record()
        path = _downstream_path()
        good = json.loads(path.read_text().splitlines()[0])
        bad = {**good, "local_usage_status": "bogus", "request_id": "badenum"}
        with open(path, "a") as f:
            f.write(json.dumps(bad) + "\n")
        assert {r.request_id for r in ptl.read_provider_traces()} == {"req-1"}

    def test_non_object_line_skipped(self):
        _record()
        path = _downstream_path()
        with open(path, "a") as f:
            f.write("[1, 2, 3]\n")
            f.write("not json at all\n")
        assert len(ptl.read_provider_traces()) == 1

    def test_best_effort_never_raises(self, monkeypatch):
        def _boom(*a, **k):
            raise OSError("disk full")

        monkeypatch.setattr("forge.core.state.open_secure_append", _boom)
        _record()  # must not raise

    def test_file_and_three_dir_levels_are_owner_only(self):
        _record()
        files = list(_downstream_dir().glob("*.jsonl"))
        assert files
        assert oct(files[0].stat().st_mode)[-3:] == "600"
        traces = _downstream_dir()
        for d in (traces, traces.parent):  # downstream/, telemetry/
            assert oct(d.stat().st_mode)[-3:] == "700"


class TestPrune:
    def test_prune_by_age_deletes_old_downstream_shard(self):
        _record()
        shard = list(_downstream_dir().glob("*.jsonl"))[0]
        shard = shard.rename(shard.with_name("2000-01_1.jsonl"))
        old = time.time() - 30 * 86400
        os.utime(shard, (old, old))
        ptl.prune_provider_traces(retention_days=14, max_total_mb=512)
        assert not shard.exists()

    def test_prune_keeps_recent(self):
        _record()
        ptl.prune_provider_traces(retention_days=14, max_total_mb=512)
        assert list(_downstream_dir().glob("*.jsonl"))

    def test_prune_by_total_size_deletes_oldest_downstream_shards(self):
        traces_dir = _downstream_dir()
        traces_dir.mkdir(parents=True, exist_ok=True)
        shards = []
        for i in range(3):  # 0.5 MiB each -> 1.5 MiB total
            path = traces_dir / f"2026-0{i + 1}_{i}.jsonl"
            path.write_text("x" * (512 * 1024))
            stamp = time.time() - (3 - i) * 86400  # shard 0 = oldest
            os.utime(path, (stamp, stamp))
            shards.append(path)

        ptl.prune_provider_traces(retention_days=0, max_total_mb=1)  # cap 1 MiB

        assert not shards[0].exists()
        assert shards[1].exists()
        assert shards[2].exists()
