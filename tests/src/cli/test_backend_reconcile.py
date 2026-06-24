"""Unit tests for the `forge model backend reconcile` CLI leaf (op mocked; no network)."""

from __future__ import annotations

import json
from typing import Any

from click.testing import CliRunner

from forge.cli.main import main
from forge.core.ops import ForgeOpError, ReconcileEntry, ReconcileResult


def _result(**overrides: Any) -> ReconcileResult:
    entry = ReconcileEntry(
        bucket="joined",
        remote_outcome="found",
        request_id="req-1",
        remote_id="gen-x",
        local_cost_micros=1234,
        local_input_tokens=10,
        local_output_tokens=20,
        local_proxy_id="crimson-apricot",
        remote_cost_micros=9999,
        remote_input_tokens=11,
        remote_output_tokens=19,
        remote_provider="Azure",
        remote_cancelled=False,
        remote_http_status=200,
    )
    base = dict(source_id="openrouter", mode="request-id", entries=[entry], counts={"joined": 1})
    base.update(overrides)
    return ReconcileResult(**base)  # type: ignore[arg-type]


def _patch_op(monkeypatch, *, result: ReconcileResult | None = None, exc: Exception | None = None) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def _fake(**kwargs: Any) -> ReconcileResult:
        captured.update(kwargs)
        if exc is not None:
            raise exc
        return result if result is not None else _result()

    monkeypatch.setattr("forge.cli.backend.reconcile_generation", _fake)
    return captured


def _backend_args(*args: str) -> list[str]:
    return ["model", "backend", *args]


def test_request_id_text_renders(monkeypatch):
    _patch_op(monkeypatch)
    res = CliRunner().invoke(main, _backend_args("reconcile", "openrouter", "--request-id", "req-1"))
    assert res.exit_code == 0
    assert "joined" in res.output and "openrouter" in res.output


def test_json_shape_has_counts_and_entries_no_secrets(monkeypatch):
    _patch_op(monkeypatch)
    res = CliRunner().invoke(main, _backend_args("reconcile", "openrouter", "--request-id", "req-1", "--json"))
    assert res.exit_code == 0
    data = json.loads(res.output)
    assert data["source_id"] == "openrouter"
    assert isinstance(data["entries"], list) and data["counts"] == {"joined": 1}
    assert "sk-" not in res.output and "Bearer" not in res.output
    for forbidden in ("messages", "prompt", "completion", "content"):
        assert forbidden not in res.output


def test_timeout_and_ids_forwarded(monkeypatch):
    captured = _patch_op(monkeypatch)
    res = CliRunner().invoke(
        main, _backend_args("reconcile", "openrouter", "--request-id", "req-1", "--timeout", "2.5")
    )
    assert res.exit_code == 0
    assert captured["source_id"] == "openrouter"
    assert captured["request_id"] == "req-1"
    assert captured["remote_id"] is None
    assert captured["timeout_s"] == 2.5


def test_remote_id_forwarded(monkeypatch):
    captured = _patch_op(monkeypatch, result=_result(mode="remote-id"))
    res = CliRunner().invoke(main, _backend_args("reconcile", "openrouter", "--remote-id", "gen-x"))
    assert res.exit_code == 0
    assert captured["remote_id"] == "gen-x" and captured["request_id"] is None


def test_mutually_exclusive_ids_exit_1(monkeypatch):
    _patch_op(monkeypatch)
    res = CliRunner().invoke(main, _backend_args("reconcile", "openrouter", "--request-id", "a", "--remote-id", "b"))
    assert res.exit_code == 1
    assert "only one" in res.output.lower()


def test_no_id_prints_tip_exit_1(monkeypatch):
    _patch_op(monkeypatch)
    res = CliRunner().invoke(main, _backend_args("reconcile", "openrouter"))
    assert res.exit_code == 1
    assert "Tip:" in res.output


def test_forge_op_error_exits_1_with_backend_list_tip(monkeypatch):
    _patch_op(monkeypatch, exc=ForgeOpError("Unknown backend source 'nope'"))
    res = CliRunner().invoke(main, _backend_args("reconcile", "nope", "--remote-id", "gen-x"))
    assert res.exit_code == 1
    assert "Unknown backend source" in res.output
    assert "forge model backend list" in res.output


def test_remote_adapter_error_exits_1_clean(monkeypatch):
    from forge.backend.remote.base import RemoteAdapterError

    _patch_op(monkeypatch, exc=RemoteAdapterError("no base url configured"))
    res = CliRunner().invoke(main, _backend_args("reconcile", "openrouter", "--remote-id", "gen-x"))
    assert res.exit_code == 1
    assert "Remote adapter error" in res.output and "no base url" in res.output


def test_not_authorized_renders_credential_hint(monkeypatch):
    entry = ReconcileEntry(
        bucket="not-queryable", remote_outcome="not_authorized", remote_id="gen-x", remote_http_status=401
    )
    result = ReconcileResult(
        source_id="openrouter",
        mode="remote-id",
        entries=[entry],
        counts={"not-queryable": 1},
        needs_credential_id="openrouter",
        needs_key_class="normal",
    )
    _patch_op(monkeypatch, result=result)
    res = CliRunner().invoke(main, _backend_args("reconcile", "openrouter", "--remote-id", "gen-x"))
    assert res.exit_code == 0
    assert "credential 'openrouter'" in res.output
    assert "sk-" not in res.output
