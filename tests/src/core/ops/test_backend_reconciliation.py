"""Unit tests for the backend remote-reconciliation op (single-id MVP).

The remote adapter is stubbed (no network); local downstream records are written for real to a
per-test FORGE_HOME so the request-id join and the backend_id scoping go through the real reader.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

import forge.core.ops.backend_reconcile as br
from forge.backend.remote.base import (
    RemoteAdapterNotFoundError,
    RemoteCapability,
    RemoteOutcome,
    RemoteRecord,
)
from forge.core.ops import (
    ForgeOpError,
    ReconcileResult,
    reconcile_generation,
    render_reconcile_lines,
)
from forge.core.ops.context import ExecutionContext
from forge.core.telemetry import downstream
from forge.core.telemetry.downstream import DownstreamRecord, write_downstream_record


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    downstream._warned_newer_schema = False
    yield
    downstream._warned_newer_schema = False


def _ctx() -> ExecutionContext:
    return ExecutionContext.from_cwd()


def _write_local(
    request_id: str,
    *,
    backend_id: str = "openrouter",
    gen_id: str | None = "gen-x",
    cost: int | None = 1234,
    gateway_cost: int | None = None,
    in_tok: int | None = 10,
    out_tok: int | None = 20,
) -> None:
    write_downstream_record(
        DownstreamRecord(
            kind="attempt",
            downstream_event_id=f"ds_{request_id}",
            request_id=request_id,
            backend_id=backend_id,
            proxy_id="crimson-apricot",
            provider_generation_id=gen_id,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_micros=gateway_cost,
            reported_cost_micros=cost,
        )
    )


def _remote(outcome: RemoteOutcome, *, remote_id: str = "gen-x", **kw: Any) -> RemoteRecord:
    return RemoteRecord(remote_id=remote_id, outcome=outcome, endpoint="GET /generation", **kw)


@dataclass
class _FakeAdapter:
    rec: RemoteRecord
    backend_instance_id: str = "openrouter"
    caps: RemoteCapability = field(
        default_factory=lambda: RemoteCapability(single_lookup=True, single_lookup_credential_id="openrouter")
    )
    calls: list[tuple[str, float]] = field(default_factory=list)

    def capabilities(self) -> RemoteCapability:
        return self.caps

    def lookup_remote_record(self, remote_id: str, *, timeout_s: float = 5.0) -> RemoteRecord:
        self.calls.append((remote_id, timeout_s))
        return self.rec

    def fetch_activity(self, **_kw: Any) -> list[RemoteRecord]:
        raise NotImplementedError


@pytest.fixture
def install_adapter(monkeypatch):
    def _install(rec: RemoteRecord, **kw: Any) -> _FakeAdapter:
        fake = _FakeAdapter(rec=rec, **kw)
        monkeypatch.setattr(br, "get_remote_adapter", lambda _sid: fake)
        return fake

    return _install


class TestRequestIdMode:
    def test_found_joins_and_preserves_both_costs(self, install_adapter):
        _write_local("req-1", gen_id="gen-x", cost=1234, in_tok=10, out_tok=20)
        fake = install_adapter(
            _remote(
                "found",
                remote_cost_micros=9999,
                remote_input_tokens=11,
                remote_output_tokens=19,
                remote_provider="Azure",
                cancelled=False,
                http_status=200,
            )
        )
        result = reconcile_generation(ctx=_ctx(), backend_instance_id="openrouter", request_id="req-1")
        e = result.entries[0]
        assert result.mode == "request-id"
        assert e.bucket == "joined"
        assert e.remote_outcome == "found"
        # Local cost is never overwritten by the remote figure; both survive with provenance.
        assert e.local_cost_micros == 1234
        assert e.remote_cost_micros == 9999
        assert e.local_input_tokens == 10 and e.remote_input_tokens == 11
        assert e.remote_provider == "Azure"
        assert result.counts == {"joined": 1}
        assert fake.calls == [("gen-x", 5.0)]  # joined on the generation id, default timeout

    def test_found_cancelled_still_joins(self, install_adapter):
        _write_local("req-c", gen_id="gen-c")
        install_adapter(_remote("found", remote_id="gen-c", cancelled=True, http_status=200))
        e = reconcile_generation(ctx=_ctx(), backend_instance_id="openrouter", request_id="req-c").entries[0]
        assert e.bucket == "joined"  # a cancelled record is still remote evidence
        assert e.remote_cancelled is True

    def test_not_found_is_missing_remote(self, install_adapter):
        _write_local("req-2", gen_id="gen-2")
        install_adapter(_remote("not_found", remote_id="gen-2", http_status=404))
        e = reconcile_generation(ctx=_ctx(), backend_instance_id="openrouter", request_id="req-2").entries[0]
        assert e.bucket == "missing-remote"
        assert e.remote_outcome == "not_found"

    def test_no_generation_id_renders_not_queryable_without_raising(self, install_adapter):
        _write_local("req-3", gen_id=None, cost=777)
        fake = install_adapter(_remote("found"))  # must NOT be called
        result = reconcile_generation(ctx=_ctx(), backend_instance_id="openrouter", request_id="req-3")
        e = result.entries[0]
        assert e.bucket == "not-queryable"
        assert e.remote_outcome is None
        assert e.local_cost_micros == 777  # local evidence still rendered
        assert "generation id" in (e.detail or "")
        assert fake.calls == []  # no remote lookup attempted
        assert render_reconcile_lines(result)  # renders, never raises

    def test_unavailable_is_not_queryable(self, install_adapter):
        _write_local("req-4", gen_id="gen-4")
        install_adapter(_remote("unavailable", remote_id="gen-4", http_status=429, detail="unexpected status 429"))
        e = reconcile_generation(ctx=_ctx(), backend_instance_id="openrouter", request_id="req-4").entries[0]
        assert e.bucket == "not-queryable"
        assert e.remote_outcome == "unavailable"
        assert e.remote_http_status == 429

    def test_not_authorized_sets_credential_hint(self, install_adapter):
        _write_local("req-5", gen_id="gen-5")
        install_adapter(_remote("not_authorized", remote_id="gen-5", http_status=401))
        result = reconcile_generation(ctx=_ctx(), backend_instance_id="openrouter", request_id="req-5")
        assert result.entries[0].bucket == "not-queryable"
        assert result.needs_credential_id == "openrouter"
        assert result.needs_key_class == "normal"

    def test_backend_scoped_record_under_other_backend_raises(self, install_adapter):
        # The record exists, but under a DIFFERENT backend_id; the backend-scoped read must miss it.
        _write_local("req-x", backend_id="litellm-remote", gen_id="gen-x")
        install_adapter(_remote("found"))
        with pytest.raises(ForgeOpError, match="No local downstream record"):
            reconcile_generation(ctx=_ctx(), backend_instance_id="openrouter", request_id="req-x")

    def test_reported_cost_falls_back_to_gateway_cost(self, install_adapter):
        # reported_cost_micros absent but gateway-calculated cost_micros present -> surface the latter.
        _write_local("req-g", gen_id="gen-g", cost=None, gateway_cost=500)
        install_adapter(_remote("found", remote_id="gen-g", http_status=200))
        e = reconcile_generation(ctx=_ctx(), backend_instance_id="openrouter", request_id="req-g").entries[0]
        assert e.local_cost_micros == 500


class TestInputNormalization:
    def test_empty_request_id_routes_to_remote_id(self, install_adapter):
        # --request-id "" must be treated as absent, not enter request-id mode and drop --remote-id.
        fake = install_adapter(_remote("found", remote_id="gen-z", remote_cost_micros=500))
        result = reconcile_generation(ctx=_ctx(), backend_instance_id="openrouter", request_id="", remote_id="gen-z")
        assert result.mode == "remote-id"
        assert result.entries[0].bucket == "remote"
        assert fake.calls == [("gen-z", 5.0)]

    def test_both_empty_ids_raises(self):
        with pytest.raises(ForgeOpError, match="exactly one"):
            reconcile_generation(ctx=_ctx(), backend_instance_id="openrouter", request_id="", remote_id="")

    def test_template_alias_resolves_to_canonical_backend_instance(self, install_adapter):
        # openrouter-anthropic is a template alias of the canonical "openrouter" backend; the record
        # is keyed by the canonical backend_id, so the alias must still join.
        _write_local("req-a", backend_id="openrouter", gen_id="gen-a")
        install_adapter(_remote("found", remote_id="gen-a", http_status=200))
        result = reconcile_generation(ctx=_ctx(), backend_instance_id="openrouter-anthropic", request_id="req-a")
        assert result.backend_instance_id == "openrouter"
        assert result.entries[0].bucket == "joined"


class TestRemoteIdMode:
    def test_found_is_remote(self, install_adapter):
        fake = install_adapter(_remote("found", remote_id="gen-z", remote_cost_micros=500))
        result = reconcile_generation(ctx=_ctx(), backend_instance_id="openrouter", remote_id="gen-z", timeout_s=2.0)
        e = result.entries[0]
        assert result.mode == "remote-id"
        assert e.bucket == "remote"
        assert e.request_id is None and e.local_cost_micros is None  # single-sided: no local side
        assert e.remote_cost_micros == 500
        assert fake.calls == [("gen-z", 2.0)]  # timeout forwarded

    def test_not_found_is_not_queryable(self, install_adapter):
        install_adapter(_remote("not_found", remote_id="gen-z", http_status=404))
        e = reconcile_generation(ctx=_ctx(), backend_instance_id="openrouter", remote_id="gen-z").entries[0]
        assert e.bucket == "not-queryable"  # no local anchor to be "missing" against
        assert e.remote_outcome == "not_found"


class TestGuards:
    def test_both_ids_raises(self):
        with pytest.raises(ForgeOpError, match="exactly one"):
            reconcile_generation(ctx=_ctx(), backend_instance_id="openrouter", request_id="a", remote_id="b")

    def test_neither_id_raises(self):
        with pytest.raises(ForgeOpError, match="exactly one"):
            reconcile_generation(ctx=_ctx(), backend_instance_id="openrouter")

    def test_unknown_backend_raises(self):
        with pytest.raises(ForgeOpError, match="Unknown backend"):
            reconcile_generation(ctx=_ctx(), backend_instance_id="not-a-source", remote_id="gen-x")

    def test_no_adapter_raises(self, monkeypatch):
        def _raise(_sid: str):
            raise RemoteAdapterNotFoundError("none")

        monkeypatch.setattr(br, "get_remote_adapter", _raise)
        with pytest.raises(ForgeOpError, match="no remote reconciliation adapter"):
            reconcile_generation(ctx=_ctx(), backend_instance_id="openrouter", remote_id="gen-x")


def test_render_has_no_secret_or_content_substrings(install_adapter):
    _write_local("req-1", gen_id="gen-x", cost=1234)
    install_adapter(
        _remote("found", remote_cost_micros=9999, remote_provider="Azure", cancelled=False, http_status=200)
    )
    result = reconcile_generation(ctx=_ctx(), backend_instance_id="openrouter", request_id="req-1")
    text = "\n".join(render_reconcile_lines(result))
    assert "backend=openrouter" in text
    assert "source=" not in text
    assert "sk-" not in text and "Bearer" not in text
    for forbidden in ("messages", "prompt", "completion", "content"):
        assert forbidden not in text
    assert isinstance(result, ReconcileResult)


def test_render_shows_output_tokens_only_local_evidence(install_adapter):
    # A local trace with cost/in_tok absent but out_tok present (a partial/aborted stream) must
    # still render its local evidence line -- the predicate gate includes output tokens.
    _write_local("req-o", gen_id=None, cost=None, in_tok=None, out_tok=20)
    install_adapter(_remote("found"))  # not called (no generation id)
    result = reconcile_generation(ctx=_ctx(), backend_instance_id="openrouter", request_id="req-o")
    text = "\n".join(render_reconcile_lines(result))
    assert "out=20" in text and "local" in text
