"""Tests for usage-ledger emission helpers (Phase 4c).

``emit_usage_for_session_result`` (claude -p verbs) attributes from the
SessionResult and the track_verb_cost holder, with null source_refs. An
unmeasured holder yields ``unattributed`` + null cost, never a fabricated $0.
``emit_direct_llm_usage`` (direct core.llm) attributes from the ambient run
identity, with provider-reported tokens. Both no-op without a run identity.
"""

from __future__ import annotations

from typing import Any

from forge.core.reactive.cost_tracking import VerbCostResult
from forge.core.reactive.session_runner import SessionResult
from forge.core.usage.emit import emit_direct_llm_usage, emit_usage_for_session_result
from forge.core.usage.ledger import read_usage_events


def _ok_result(**overrides: Any) -> SessionResult:
    base: dict[str, Any] = {
        "stdout": "",
        "stderr": "",
        "returncode": 0,
        "run_id": "run_w",
        "parent_run_id": "run_p",
        "root_run_id": "run_r",
    }
    base.update(overrides)
    return SessionResult(**base)


class TestEmitForSessionResult:
    def test_measured_proxy_cost(self) -> None:
        cost = VerbCostResult(
            verb="memory-writer",
            total_cost_micros=1500,
            input_tokens=10,
            output_tokens=20,
            duration_ms=1234.5,
            measured=True,
        )
        emit_usage_for_session_result(
            _ok_result(), command="memory-writer", session="s1", cost=cost, base_url="http://localhost:8084"
        )
        out = read_usage_events()
        assert len(out) == 1
        e = out[0]
        assert (e.command, e.session, e.status) == ("memory-writer", "s1", "success")
        assert (e.run_id, e.parent_run_id, e.root_run_id) == ("run_w", "run_p", "run_r")
        assert e.measurement_source == "verb_snapshot_estimated"
        assert (e.cost_micro_usd, e.input_tokens, e.output_tokens) == (1500, 10, 20)
        assert e.latency_ms == 1234.5
        assert e.attribution_granularity == "verb"
        assert e.source_refs is None  # claude -p: proxy request_id unknown (4g)
        assert e.billing_mode == "unknown"  # proxied -> opaque upstream

    def test_unmeasured_no_proxy_is_unattributed(self, monkeypatch) -> None:
        # A direct/no-proxy verb: holder never measured -> null cost, not $0.
        monkeypatch.setattr("forge.core.auth.template_secrets.resolve_env_or_credential", lambda _key: "sk-test")
        emit_usage_for_session_result(
            _ok_result(), command="curation", cost=VerbCostResult(verb="curation"), direct=True
        )
        e = read_usage_events()[0]
        assert e.measurement_source == "unattributed"
        assert e.cost_micro_usd is None and e.input_tokens is None
        assert e.billing_mode == "api"  # direct + key present

    def test_failure_status_and_type(self) -> None:
        emit_usage_for_session_result(_ok_result(returncode=1, error="boom"), command="supervisor")
        e = read_usage_events()[0]
        assert (e.status, e.failure_type) == ("error", "subprocess_error")

    def test_timeout_status_and_type(self) -> None:
        emit_usage_for_session_result(_ok_result(returncode=-1, timed_out=True), command="supervisor")
        e = read_usage_events()[0]
        assert (e.status, e.failure_type) == ("timeout", "timeout")

    def test_no_run_id_is_skipped(self) -> None:
        emit_usage_for_session_result(_ok_result(run_id=None), command="memory-writer")
        assert read_usage_events() == []


class TestEmitDirectLlmUsage:
    def test_emits_with_ambient_identity(self, monkeypatch) -> None:
        monkeypatch.setenv("FORGE_RUN_ID", "run_amb")
        monkeypatch.setenv("FORGE_ROOT_RUN_ID", "run_amb")
        emit_direct_llm_usage(
            command="tagger",
            model="gemini/gemini-2.0-flash",
            provider="gemini",
            usage={"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10, "cached_tokens": 4},
            latency_ms=12.0,
        )
        e = read_usage_events()[0]
        assert (e.command, e.run_id, e.provider) == ("tagger", "run_amb", "gemini")
        assert e.measurement_source == "provider_usage_exact"
        assert (e.input_tokens, e.output_tokens, e.cached_tokens, e.cost_micro_usd) == (7, 3, 4, None)
        assert e.latency_ms == 12.0
        assert e.source_refs is None  # no proven proxy target
        assert e.billing_mode == "unknown"  # never guessed -- caller didn't prove direct+credential

    def test_proxy_target_sets_cost_request_id(self, monkeypatch) -> None:
        monkeypatch.setenv("FORGE_RUN_ID", "run_amb")
        emit_direct_llm_usage(
            command="tagger", usage={"prompt_tokens": 1, "completion_tokens": 1}, cost_request_id="req_join"
        )
        e = read_usage_events()[0]
        assert e.source_refs is not None and e.source_refs.cost_request_id == "req_join"
        assert e.billing_mode == "unknown"  # proxied

    def test_no_ambient_identity_skips(self, monkeypatch) -> None:
        monkeypatch.delenv("FORGE_RUN_ID", raising=False)
        emit_direct_llm_usage(command="tagger", usage={"prompt_tokens": 1, "completion_tokens": 1})
        assert read_usage_events() == []
