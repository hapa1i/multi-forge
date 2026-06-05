"""Tests for the usage-attribution ledger (Phase 4b).

Mirrors the audit-logger contract: versioned, PID-sharded, owner-only, strictly read
(unknown fields are corruption), best-effort writes. The autouse ``isolate_forge_home``
fixture gives each test a fresh ``FORGE_HOME``, so counts are exact.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from forge.core.paths import get_forge_home
from forge.core.usage.ledger import (
    USAGE_SCHEMA_VERSION,
    SourceRefs,
    UsageEvent,
    log_usage_event,
    read_usage_events,
)


def _event(**overrides: object) -> UsageEvent:
    base: dict[str, object] = {
        "run_id": "run_a",
        "root_run_id": "run_a",
        "runtime": "claude_code",
        "command": "panel",
        "status": "success",
    }
    base.update(overrides)
    return UsageEvent(**base)  # type: ignore[arg-type]


def _shard_path() -> Path:
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    return get_forge_home() / "usage" / "events" / f"{month}_{os.getpid()}.jsonl"


def _append_raw(record: dict[str, object]) -> None:
    """Append a hand-built JSON line to the current shard (for corruption cases)."""
    path = _shard_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(record) + "\n")


class TestRoundtrip:
    def test_write_then_read_equal(self) -> None:
        log_usage_event(_event(model="claude-opus", input_tokens=10, output_tokens=20, latency_ms=12.5))
        out = read_usage_events()
        assert len(out) == 1
        got = out[0]
        assert (got.run_id, got.model, got.input_tokens, got.output_tokens) == ("run_a", "claude-opus", 10, 20)
        assert got.latency_ms == 12.5
        # PID-sharded under usage/events/, not a single events.jsonl.
        assert _shard_path().is_file()

    def test_schema_version_stamped(self) -> None:
        log_usage_event(_event())
        rec = json.loads(_shard_path().read_text().strip())
        assert rec["schema_version"] == USAGE_SCHEMA_VERSION

    def test_event_id_and_provenance_defaults(self) -> None:
        log_usage_event(_event())
        rec = json.loads(_shard_path().read_text().strip())
        assert rec["event_id"].startswith("evt_")
        assert rec["measurement_source"] == "unattributed"
        assert rec["attribution_granularity"] == "verb"
        assert rec["billing_mode"] == "unknown"


class TestPermissions:
    def test_owner_only_file_and_dirs(self) -> None:
        log_usage_event(_event())
        events_dir = get_forge_home() / "usage" / "events"
        assert (_shard_path().stat().st_mode & 0o777) == 0o600
        assert (events_dir.stat().st_mode & 0o777) == 0o700
        assert (events_dir.parent.stat().st_mode & 0o777) == 0o700


class TestSourceRefs:
    def test_null_source_refs_native_runtime(self) -> None:
        log_usage_event(_event(runtime="codex", source_refs=None))
        got = read_usage_events()[0]
        assert got.runtime == "codex"
        assert got.source_refs is None

    def test_nested_source_refs_roundtrip(self) -> None:
        log_usage_event(_event(source_refs=SourceRefs(cost_request_id="req_x")))
        got = read_usage_events()[0]
        assert got.source_refs is not None
        assert got.source_refs.cost_request_id == "req_x"
        assert got.source_refs.audit_request_id is None


class TestStrictAndVersion:
    def test_newer_version_skipped_warn_once(self, caplog) -> None:
        log_usage_event(_event(command="keep"))
        _append_raw(
            {
                "schema_version": 999,
                "event_id": "evt_future",
                "ts": "2999-01-01T00:00:00Z",
                "run_id": "run_f",
                "root_run_id": "run_f",
                "runtime": "future",
                "command": "drop",
                "status": "success",
            }
        )
        with caplog.at_level(logging.WARNING):
            out = read_usage_events()
        commands = {e.command for e in out}
        assert commands == {"keep"}
        assert sum("newer Forge" in r.message for r in caplog.records) == 1

    def test_unknown_field_is_corruption(self, caplog) -> None:
        log_usage_event(_event(command="good"))
        _append_raw(
            {
                "schema_version": 1,
                "event_id": "evt_bad",
                "ts": "2026-01-01T00:00:00Z",
                "run_id": "run_b",
                "root_run_id": "run_b",
                "runtime": "claude_code",
                "command": "bad",
                "status": "success",
                "bogus_field": 1,
            }
        )
        with caplog.at_level(logging.WARNING):
            out = read_usage_events()
        assert {e.command for e in out} == {"good"}
        assert any("malformed usage event" in r.message for r in caplog.records)

    def test_non_object_json_line_skipped(self) -> None:
        """A valid-JSON-but-non-object line (`[]`, `"x"`, `1`) is skipped, not crash the read."""
        log_usage_event(_event(command="ok"))
        with _shard_path().open("a") as f:
            f.write("[]\n")
            f.write('"hello"\n')
            f.write("1\n")
        assert [e.command for e in read_usage_events()] == ["ok"]

    def test_bad_literal_is_corruption(self) -> None:
        """An invalid Literal value (a bogus measurement_source) is rejected, not loaded."""
        log_usage_event(_event(command="good"))
        _append_raw(
            {
                "schema_version": 1,
                "event_id": "evt_lit",
                "ts": "2026-01-01T00:00:00Z",
                "run_id": "run_l",
                "root_run_id": "run_l",
                "runtime": "claude_code",
                "command": "bad_literal",
                "status": "success",
                "measurement_source": "not_a_source",
            }
        )
        assert {e.command for e in read_usage_events()} == {"good"}

    def test_bad_nested_source_refs_is_corruption(self) -> None:
        """A wrong nested type (a non-str cost_request_id) is rejected, not coerced."""
        log_usage_event(_event(command="good"))
        _append_raw(
            {
                "schema_version": 1,
                "event_id": "evt_sr",
                "ts": "2026-01-01T00:00:00Z",
                "run_id": "run_s",
                "root_run_id": "run_s",
                "runtime": "claude_code",
                "command": "bad_refs",
                "status": "success",
                "source_refs": {"cost_request_id": 42},
            }
        )
        assert {e.command for e in read_usage_events()} == {"good"}

    def test_malformed_json_line_skipped(self) -> None:
        log_usage_event(_event(command="ok"))
        with _shard_path().open("a") as f:
            f.write("{ not json\n")
        assert [e.command for e in read_usage_events()] == ["ok"]


class TestFilters:
    def test_filter_by_run_id_and_command(self) -> None:
        log_usage_event(_event(run_id="run_1", command="panel"))
        log_usage_event(_event(run_id="run_2", command="memory-writer"))
        assert {e.command for e in read_usage_events(run_id="run_1")} == {"panel"}
        assert {e.run_id for e in read_usage_events(command="memory-writer")} == {"run_2"}

    def test_filter_by_ts_window(self) -> None:
        log_usage_event(_event(command="now"))
        future = datetime.now(timezone.utc) + timedelta(days=1)
        past = datetime.now(timezone.utc) - timedelta(days=1)
        assert read_usage_events(period_start=future) == []
        assert len(read_usage_events(period_start=past)) == 1

    def test_filter_by_session(self) -> None:
        log_usage_event(_event(command="supervisor", session="planner"))
        log_usage_event(_event(command="panel", session="executor"))
        log_usage_event(_event(command="tagger", session=None))  # untagged event
        assert {e.command for e in read_usage_events(session="planner")} == {"supervisor"}
        assert {e.command for e in read_usage_events(session="executor")} == {"panel"}
        # An untagged (session=None) event matches no session filter.
        assert read_usage_events(session="nope") == []

    def test_filter_by_session_with_period(self) -> None:
        log_usage_event(_event(command="supervisor", session="planner"))
        past = datetime.now(timezone.utc) - timedelta(days=1)
        future = datetime.now(timezone.utc) + timedelta(days=1)
        assert len(read_usage_events(period_start=past, session="planner")) == 1
        assert read_usage_events(period_start=future, session="planner") == []


class TestBestEffort:
    def test_writer_never_raises(self, monkeypatch) -> None:
        def boom(*_a: object, **_k: object) -> object:
            raise OSError("disk full")

        monkeypatch.setattr("forge.core.state.open_secure_append", boom)
        # Must swallow the error, not propagate it.
        log_usage_event(_event())

    def test_read_missing_dir_returns_empty(self) -> None:
        assert read_usage_events() == []


class TestMetricVocabulary:
    """Phase 1 metric-evidence fields: route/reporter/confidence (additive, schema v1)."""

    def test_v1_record_loads_with_defaults(self) -> None:
        # A pre-Phase-1 record carries none of the new keys; the additive fields fill
        # from their defaults (this is why no schema bump is needed to read old records).
        _append_raw(
            {
                "schema_version": 1,
                "event_id": "evt_v1",
                "ts": "2026-01-01T00:00:00Z",
                "run_id": "run_v1",
                "root_run_id": "run_v1",
                "runtime": "claude_code",
                "command": "panel",
                "status": "success",
            }
        )
        e = read_usage_events()[0]
        assert (e.route, e.reporter, e.confidence) == (None, None, "unknown")

    def test_new_fields_roundtrip(self) -> None:
        log_usage_event(_event(route="claude_p", reporter="forge_proxy", confidence="inferred"))
        e = read_usage_events()[0]
        assert (e.route, e.reporter, e.confidence) == ("claude_p", "forge_proxy", "inferred")

    def test_bad_vocabulary_literals_are_corruption(self) -> None:
        # Strict read rejects an invalid value in any of the three new Literals.
        log_usage_event(_event(command="good"))
        for i, (field, bad) in enumerate(
            [("route", "teleport"), ("reporter", "carrier_pigeon"), ("confidence", "vibes")]
        ):
            _append_raw(
                {
                    "schema_version": 1,
                    "event_id": f"evt_bad_{i}",
                    "ts": "2026-01-01T00:00:00Z",
                    "run_id": f"run_{i}",
                    "root_run_id": f"run_{i}",
                    "runtime": "claude_code",
                    "command": "bad",
                    "status": "success",
                    field: bad,
                }
            )
        assert {e.command for e in read_usage_events()} == {"good"}

    def test_confidence_orthogonal_to_measurement_source(self) -> None:
        # The tagger shape: exact tokens (provider_usage_exact) AND no dollars
        # (confidence="unavailable", cost None) coexist -- two independent provenance axes.
        log_usage_event(
            _event(
                measurement_source="provider_usage_exact",
                confidence="unavailable",
                cost_micro_usd=None,
                input_tokens=7,
            )
        )
        e = read_usage_events()[0]
        assert e.measurement_source == "provider_usage_exact"
        assert e.confidence == "unavailable"
        assert e.cost_micro_usd is None and e.input_tokens == 7
