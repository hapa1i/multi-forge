"""Tests for usage-ledger emission helpers (Phase 4c).

``emit_usage_for_session_result`` (claude -p verbs) attributes from the
SessionResult and the track_verb_cost holder, with null source_refs. An
unmeasured holder yields ``unattributed`` + null cost, never a fabricated $0.
``emit_direct_llm_usage`` (direct core.llm) attributes from the ambient run
identity, with provider-reported tokens. Both no-op without a run identity.
"""

from __future__ import annotations

from typing import Any

from forge.backend.sources import get_model_source
from forge.core.reactive.cost_tracking import VerbCostResult
from forge.core.reactive.session_runner import SessionResult
from forge.core.telemetry.downstream import read_downstream_records
from forge.core.usage.emit import (
    _backend_id_for_direct_usage,
    emit_direct_llm_usage,
    emit_usage_for_session_result,
    emit_verb_usage,
    emit_worker_usage,
)
from forge.core.usage.ledger import read_usage_events
from forge.core.usage.measurement import direct_cost_provenance


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


def test_direct_usage_backend_ids_resolve_to_catalog_sources() -> None:
    """Direct usage attribution must not emit dangling model-source ids."""

    backend_ids = [
        _backend_id_for_direct_usage(provider=None, reporter="claude_code"),
        _backend_id_for_direct_usage(provider="anthropic", reporter="provider"),
        _backend_id_for_direct_usage(provider="openrouter", reporter="provider"),
        _backend_id_for_direct_usage(provider="openai", reporter="codex_jsonl"),
    ]

    for backend_id in backend_ids:
        if backend_id is not None:
            assert get_model_source(backend_id).id == backend_id


class TestEmitForSessionResult:
    def test_measured_proxy_cost(self) -> None:
        cost = VerbCostResult(
            verb="memory-writer",
            total_cost_micros=1500,
            input_tokens=10,
            output_tokens=20,
            duration_ms=1234.5,
            measured=True,
            cost_measured=True,  # the window had a reported-cost request
        )
        emit_usage_for_session_result(
            _ok_result(),
            command="memory-writer",
            session="s1",
            cost=cost,
            base_url="http://localhost:8084",
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
        assert (e.route, e.reporter, e.confidence) == (
            "claude_p",
            "forge_proxy",
            "reported",
        )

    def test_measured_tokens_but_unreported_cost_logs_null_cost(self) -> None:
        """Passthrough verb: snapshot measured tokens, but no reported cost → null $.

        Regression for the verb cost-evidence conflation: measured=True (a snapshot
        delta existed) must not fabricate a measured $0 when cost_measured=False.
        Tokens are still attributed; cost is unavailable.
        """
        cost = VerbCostResult(
            verb="memory-writer",
            total_cost_micros=0,
            input_tokens=10,
            output_tokens=20,
            measured=True,
            cost_measured=False,  # no reported-cost request in the window
        )
        emit_usage_for_session_result(
            _ok_result(),
            command="memory-writer",
            session="s1",
            cost=cost,
            base_url="http://localhost:8084",
        )
        e = read_usage_events()[0]
        # Tokens attributed; cost is null (not a fabricated $0).
        assert (e.input_tokens, e.output_tokens) == (10, 20)
        assert e.cost_micro_usd is None
        assert (e.reporter, e.confidence) == (None, "unavailable")

    def test_unmeasured_no_proxy_is_unattributed(self, monkeypatch) -> None:
        # A direct/no-proxy verb: holder never measured -> null cost, not $0.
        monkeypatch.setattr(
            "forge.core.auth.template_secrets.resolve_env_or_credential",
            lambda _key: "sk-test",
        )
        emit_usage_for_session_result(
            _ok_result(),
            command="curation",
            cost=VerbCostResult(verb="curation"),
            direct=True,
        )
        e = read_usage_events()[0]
        assert e.measurement_source == "unattributed"
        assert e.cost_micro_usd is None and e.input_tokens is None
        assert e.billing_mode == "api"  # direct + key present
        assert (e.route, e.reporter, e.confidence) == ("claude_p", None, "unavailable")

    def test_keyless_direct_on_claude_max_is_subscription_quota(self, monkeypatch) -> None:
        # Keyless + direct + bound to the claude-max subscription lane -> subscription_quota
        # (the T0 upgrade). Cost stays null/unavailable (design 3.14): only the label changes.
        monkeypatch.setattr(
            "forge.core.auth.template_secrets.resolve_env_or_credential",
            lambda _key: None,
        )
        emit_usage_for_session_result(
            _ok_result(),
            command="supervisor",
            cost=VerbCostResult(verb="supervisor"),
            direct=True,
            backend_id="claude-max",
        )
        e = read_usage_events()[0]
        assert e.billing_mode == "subscription_quota"
        assert e.cost_micro_usd is None and e.confidence == "unavailable"

    def test_key_present_on_claude_max_is_api(self, monkeypatch) -> None:
        # Precedence: a resolvable key on the same lane is still api, never subscription.
        monkeypatch.setattr(
            "forge.core.auth.template_secrets.resolve_env_or_credential",
            lambda _key: "sk-test",
        )
        emit_usage_for_session_result(
            _ok_result(),
            command="supervisor",
            cost=VerbCostResult(verb="supervisor"),
            direct=True,
            backend_id="claude-max",
        )
        assert read_usage_events()[0].billing_mode == "api"

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
            usage={
                "prompt_tokens": 7,
                "completion_tokens": 3,
                "total_tokens": 10,
                "cached_tokens": 4,
            },
            latency_ms=12.0,
        )
        e = read_usage_events()[0]
        assert (e.command, e.run_id, e.provider) == ("tagger", "run_amb", "gemini")
        assert e.measurement_source == "provider_usage_exact"
        assert (e.input_tokens, e.output_tokens, e.cached_tokens, e.cost_micro_usd) == (
            7,
            3,
            4,
            None,
        )
        assert e.latency_ms == 12.0
        assert e.source_refs is None  # no proven proxy target
        assert e.billing_mode == "unknown"  # never guessed -- caller didn't prove direct+credential
        assert (e.route, e.reporter, e.confidence) == (
            "core_llm",
            "provider",
            "unavailable",
        )

    def test_proxy_target_sets_cost_request_id(self, monkeypatch) -> None:
        monkeypatch.setenv("FORGE_RUN_ID", "run_amb")
        emit_direct_llm_usage(
            command="tagger",
            usage={"prompt_tokens": 1, "completion_tokens": 1},
            cost_request_id="req_join",
        )
        e = read_usage_events()[0]
        assert e.source_refs is not None and e.source_refs.cost_request_id == "req_join"
        assert e.billing_mode == "unknown"  # proxied
        # A joined cost ref must NOT upgrade event-local cost confidence: cost stays None
        # and confidence stays "unavailable" (the $ lives in the cost plane, not here).
        assert e.cost_micro_usd is None and e.confidence == "unavailable"
        assert (e.route, e.reporter) == ("core_llm", "provider")
        downstream = read_downstream_records(kind="attempt")
        assert downstream == []

    def test_no_ambient_identity_skips(self, monkeypatch) -> None:
        monkeypatch.delenv("FORGE_RUN_ID", raising=False)
        emit_direct_llm_usage(command="tagger", usage={"prompt_tokens": 1, "completion_tokens": 1})
        assert read_usage_events() == []

    def test_unmeasured_direct_calls_get_distinct_downstream_ids(self, monkeypatch) -> None:
        monkeypatch.setenv("FORGE_RUN_ID", "run_amb")
        monkeypatch.setenv("FORGE_ROOT_RUN_ID", "run_amb")

        emit_direct_llm_usage(command="tagger", provider="openai", usage=None)
        emit_direct_llm_usage(command="tagger", provider="openai", usage=None)

        downstream = read_downstream_records(kind="attempt")
        assert len(downstream) == 2
        assert len({record.downstream_event_id for record in downstream}) == 2
        assert {record.backend_id for record in downstream} == {None}

    def test_direct_provider_session_id_persists_downstream(self, monkeypatch) -> None:
        monkeypatch.setenv("FORGE_RUN_ID", "run_amb")
        monkeypatch.setenv("FORGE_ROOT_RUN_ID", "run_amb")

        emit_direct_llm_usage(
            command="tagger",
            provider="openrouter",
            usage={"prompt_tokens": 1, "completion_tokens": 1},
            provider_meta={"provider_session_id": "forge_sess_abc_supervisor"},
        )

        downstream = read_downstream_records(kind="attempt")
        assert len(downstream) == 1
        assert downstream[0].provider_session_id == "forge_sess_abc_supervisor"
        assert downstream[0].backend_id == "openrouter"


class TestEmitVerbAndWorkerVocabulary:
    """route/reporter/confidence on the fan-out aggregate and the per-worker leaf."""

    def test_verb_aggregate_measured(self, monkeypatch) -> None:
        monkeypatch.setenv("FORGE_RUN_ID", "run_v")
        monkeypatch.setenv("FORGE_ROOT_RUN_ID", "run_v")
        emit_verb_usage(
            command="panel",
            cost=VerbCostResult(verb="panel", total_cost_micros=900, measured=True, cost_measured=True),
        )
        e = read_usage_events()[0]
        # Aggregate spans heterogeneous worker routes -> no single route; reported cost.
        assert (e.route, e.reporter, e.confidence) == (None, "forge_proxy", "reported")

    def test_verb_aggregate_measured_tokens_unreported_cost(self, monkeypatch) -> None:
        """A fan-out that moved tokens but reported no cost logs null $, not a fake $0."""
        monkeypatch.setenv("FORGE_RUN_ID", "run_v")
        monkeypatch.setenv("FORGE_ROOT_RUN_ID", "run_v")
        emit_verb_usage(
            command="panel",
            cost=VerbCostResult(
                verb="panel",
                total_cost_micros=0,
                input_tokens=5,
                measured=True,
                cost_measured=False,
            ),
        )
        e = read_usage_events()[0]
        assert e.cost_micro_usd is None
        assert (e.reporter, e.confidence) == (None, "unavailable")

    def test_verb_aggregate_unmeasured(self, monkeypatch) -> None:
        monkeypatch.setenv("FORGE_RUN_ID", "run_v")
        monkeypatch.setenv("FORGE_ROOT_RUN_ID", "run_v")
        emit_verb_usage(command="panel", cost=VerbCostResult(verb="panel"))
        e = read_usage_events()[0]
        assert (e.route, e.reporter, e.confidence) == (None, None, "unavailable")

    def test_worker_leaf(self) -> None:
        emit_worker_usage(run_id="run_leaf", command="panel", status="success")
        e = read_usage_events()[0]
        assert (e.route, e.reporter, e.confidence) == ("claude_p", None, "unavailable")


class TestDirectCostProvenance:
    """The shared one-reporter precedence for a DIRECT (non-proxied) claude -p run.

    Lives once in ``direct_cost_provenance`` so the verb and per-worker emitters
    cannot drift. The proxied path is deliberately NOT here (see the divergence test
    below)."""

    def test_self_reported_cost_is_runtime_native(self) -> None:
        p = direct_cost_provenance(7000, True, 10, 20, 3)
        assert (p.cost_micro_usd, p.reporter, p.confidence, p.measurement_source) == (
            7000,
            "claude_code",
            "reported",
            "runtime_native",
        )
        assert (p.input_tokens, p.output_tokens, p.cached_tokens) == (10, 20, 3)

    def test_tokens_only_is_provider_usage_exact_cost_unavailable(self) -> None:
        # OAuth: usage present, cost absent -> exact tokens kept, cost honestly None.
        p = direct_cost_provenance(None, True, 10, 20, 3)
        assert (p.cost_micro_usd, p.reporter, p.confidence, p.measurement_source) == (
            None,
            None,
            "unavailable",
            "provider_usage_exact",
        )
        assert p.input_tokens == 10

    def test_neither_is_unattributed(self) -> None:
        p = direct_cost_provenance(None, True, None, None, None)
        assert (p.cost_micro_usd, p.confidence, p.measurement_source) == (
            None,
            "unavailable",
            "unattributed",
        )
        assert (p.input_tokens, p.output_tokens, p.cached_tokens) == (None, None, None)

    def test_unparsed_envelope_drops_tokens(self) -> None:
        # envelope_parsed=False -> tokens are not trustworthy as provider-exact.
        p = direct_cost_provenance(None, False, 10, 20, 3)
        assert p.measurement_source == "unattributed"
        assert p.input_tokens is None


class TestVerbWorkerPrecedenceInvariant:
    """Pin the refactor invariant: the DIRECT rule is shared (verb == worker) while
    the PROXIED rule diverges by caller (verb attributes the snapshot; a worker stays
    unattributed so it does not double-count the verb-level aggregate)."""

    def test_direct_path_identical_for_verb_and_worker(self) -> None:
        emit_usage_for_session_result(
            _ok_result(
                cost_micro_usd=7000,
                envelope_parsed=True,
                input_tokens=10,
                output_tokens=20,
                cached_tokens=3,
            ),
            command="memory-writer",
            direct=True,
        )
        emit_worker_usage(
            run_id="run_leaf",
            command="panel",
            status="success",
            cost_micro_usd=7000,
            envelope_parsed=True,
            input_tokens=10,
            output_tokens=20,
            cached_tokens=3,
        )
        events = read_usage_events()
        verb = next(e for e in events if e.attribution_granularity == "verb")
        worker = next(e for e in events if e.attribution_granularity == "worker")

        def prov(e: object) -> tuple:
            return (
                e.reporter,  # type: ignore[attr-defined]
                e.confidence,  # type: ignore[attr-defined]
                e.measurement_source,  # type: ignore[attr-defined]
                e.cost_micro_usd,  # type: ignore[attr-defined]
                e.input_tokens,  # type: ignore[attr-defined]
                e.output_tokens,  # type: ignore[attr-defined]
                e.cached_tokens,  # type: ignore[attr-defined]
            )

        assert prov(verb) == prov(worker) == ("claude_code", "reported", "runtime_native", 7000, 10, 20, 3)
        assert {record.backend_id for record in read_downstream_records(kind="attempt")} == {"anthropic-direct"}

    def test_proxied_worker_stays_unattributed_while_verb_attributes(self) -> None:
        # The no-double-count invariant. Even handed a self-cost, a PROXIED worker must
        # not attribute it: the verb-level aggregate owns the proxied total.
        emit_usage_for_session_result(
            _ok_result(),
            command="panel",
            base_url="http://localhost:8085",
            cost=VerbCostResult(verb="panel", total_cost_micros=900, measured=True, cost_measured=True),
        )
        emit_worker_usage(
            run_id="run_leaf",
            command="panel",
            status="success",
            base_url="http://localhost:8085",
            cost_micro_usd=7000,
            envelope_parsed=True,
            input_tokens=10,
        )
        events = read_usage_events()
        verb = next(e for e in events if e.attribution_granularity == "verb")
        worker = next(e for e in events if e.attribution_granularity == "worker")
        assert (verb.reporter, verb.confidence, verb.cost_micro_usd) == (
            "forge_proxy",
            "reported",
            900,
        )
        assert (
            worker.reporter,
            worker.confidence,
            worker.cost_micro_usd,
            worker.measurement_source,
        ) == (
            None,
            "unavailable",
            None,
            "unattributed",
        )
        assert worker.input_tokens is None  # proxied worker drops tokens too (no mixed provenance)
