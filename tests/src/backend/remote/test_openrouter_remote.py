"""Unit tests for the OpenRouter remote adapter (httpx mocked; status -> outcome mapping)."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import httpx
import pytest

from forge.backend.remote.base import RemoteAdapterError
from forge.backend.remote.openrouter import OpenRouterRemoteAdapter


@pytest.fixture(autouse=True)
def _isolated_home_and_key(tmp_path, monkeypatch):
    # Isolated FORGE_HOME so credential-file resolution is empty; a real env key by default.
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-SECRET")
    monkeypatch.delenv("OPENROUTER_BASE_URL", raising=False)
    yield


class _Resp:
    def __init__(self, status: int, payload: Any = None, *, raise_json: bool = False) -> None:
        self.status_code = status
        self._payload = payload
        self._raise_json = raise_json

    def json(self) -> Any:
        if self._raise_json:
            raise ValueError("not json")
        return self._payload


def _install_client(monkeypatch, *, response: _Resp | None = None, exc: Exception | None = None) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    class _Client:
        def __init__(self, **kwargs: Any) -> None:
            captured["constructed"] = True

        def __enter__(self) -> "_Client":
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def get(self, url: str, params: Any = None, headers: Any = None) -> _Resp:
            captured["url"] = url
            captured["params"] = params
            captured["headers"] = headers
            if exc is not None:
                raise exc
            assert response is not None
            return response

    monkeypatch.setattr(httpx, "Client", _Client)
    return captured


def _adapter() -> OpenRouterRemoteAdapter:
    return OpenRouterRemoteAdapter()


def test_capabilities_single_lookup_only():
    caps = _adapter().capabilities()
    assert caps.single_lookup is True
    assert caps.window_activity is False
    assert caps.single_lookup_credential_id == "openrouter"


def test_found_maps_metadata_and_usd_to_micros(monkeypatch):
    payload = {
        "data": {
            "id": "gen-x",
            "total_cost": 0.0015,
            "cancelled": False,
            "provider_name": "Azure",
            "native_tokens_prompt": 11,
            "native_tokens_completion": 19,
        }
    }
    captured = _install_client(monkeypatch, response=_Resp(200, payload))
    rec = _adapter().lookup_remote_record("gen-x")
    assert rec.outcome == "found"
    assert rec.http_status == 200
    assert rec.remote_cost_micros == 1500  # 0.0015 USD -> micros
    assert rec.remote_input_tokens == 11 and rec.remote_output_tokens == 19
    assert rec.remote_provider == "Azure"
    assert rec.cancelled is False
    # Request shape: /generation?id=<remote-id> with a bearer header.
    assert captured["url"].endswith("/generation")
    assert captured["params"] == {"id": "gen-x"}
    assert captured["headers"]["Authorization"].startswith("Bearer ")


def test_found_falls_back_to_non_native_tokens(monkeypatch):
    payload = {"data": {"id": "gen-x", "tokens_prompt": 5, "tokens_completion": 7}}
    _install_client(monkeypatch, response=_Resp(200, payload))
    rec = _adapter().lookup_remote_record("gen-x")
    assert rec.remote_input_tokens == 5 and rec.remote_output_tokens == 7


def test_found_drops_content_fields(monkeypatch):
    # Even if the body carries prompt/completion content, the metadata-only parse never copies the
    # VALUES into the record. (asdict(rec) keys are the fixed RemoteRecord fields, so check values.)
    payload = {
        "data": {
            "id": "gen-x",
            "messages": [{"role": "user", "content": "SENTINEL_PROMPT"}],
            "prompt": "SENTINEL_PROMPT",
            "completion": "SENTINEL_COMPLETION",
            "native_tokens_prompt": 5,
        }
    }
    _install_client(monkeypatch, response=_Resp(200, payload))
    rec = _adapter().lookup_remote_record("gen-x")
    serialized = str(asdict(rec))
    assert "SENTINEL_PROMPT" not in serialized
    assert "SENTINEL_COMPLETION" not in serialized
    assert rec.remote_input_tokens == 5  # the whitelisted metadata was still read


def test_flat_payload_without_data_wrapper(monkeypatch):
    _install_client(monkeypatch, response=_Resp(200, {"id": "gen-x", "total_cost": 0.0, "provider_name": "Groq"}))
    rec = _adapter().lookup_remote_record("gen-x")
    assert rec.outcome == "found" and rec.remote_provider == "Groq"


@pytest.mark.parametrize(
    "status,expected",
    [(404, "not_found"), (401, "not_authorized"), (403, "not_authorized"), (429, "unavailable"), (500, "unavailable")],
)
def test_status_to_outcome(monkeypatch, status, expected):
    _install_client(monkeypatch, response=_Resp(status, {}))
    rec = _adapter().lookup_remote_record("gen-x")
    assert rec.outcome == expected
    assert rec.http_status == status


def test_timeout_is_unavailable_data(monkeypatch):
    _install_client(monkeypatch, exc=httpx.TimeoutException("slow"))
    rec = _adapter().lookup_remote_record("gen-x")  # must NOT raise
    assert rec.outcome == "unavailable"
    assert "failed" in (rec.detail or "")


def test_connection_error_is_unavailable_data(monkeypatch):
    _install_client(monkeypatch, exc=httpx.ConnectError("down"))
    rec = _adapter().lookup_remote_record("gen-x")
    assert rec.outcome == "unavailable"


def test_malformed_body_is_unavailable(monkeypatch):
    _install_client(monkeypatch, response=_Resp(200, None, raise_json=True))
    rec = _adapter().lookup_remote_record("gen-x")
    assert rec.outcome == "unavailable"
    assert "malformed" in (rec.detail or "")


@pytest.mark.parametrize("cost", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_cost_is_dropped_not_crashed(monkeypatch, cost):
    # json.loads parses bare NaN/Infinity by default; the coercer must drop them, never raise.
    _install_client(monkeypatch, response=_Resp(200, {"data": {"id": "gen-x", "total_cost": cost}}))
    rec = _adapter().lookup_remote_record("gen-x")  # must NOT raise
    assert rec.outcome == "found"
    assert rec.remote_cost_micros is None


@pytest.mark.parametrize("tok", [float("nan"), float("inf")])
def test_non_finite_tokens_are_dropped_not_crashed(monkeypatch, tok):
    _install_client(monkeypatch, response=_Resp(200, {"data": {"id": "gen-x", "native_tokens_prompt": tok}}))
    rec = _adapter().lookup_remote_record("gen-x")  # must NOT raise (no int(inf)/int(nan))
    assert rec.outcome == "found"
    assert rec.remote_input_tokens is None


def test_overflowing_int_cost_is_dropped_not_crashed(monkeypatch):
    # A huge bare integer overflows float(); the coercer returns None instead of raising OverflowError.
    _install_client(monkeypatch, response=_Resp(200, {"data": {"id": "gen-x", "total_cost": 10**400}}))
    rec = _adapter().lookup_remote_record("gen-x")  # must NOT raise
    assert rec.outcome == "found"
    assert rec.remote_cost_micros is None


def test_bool_cost_is_not_treated_as_number(monkeypatch):
    # bool subclasses int, but a JSON boolean is never a real cost (consistent with _as_int).
    _install_client(monkeypatch, response=_Resp(200, {"data": {"id": "gen-x", "total_cost": True}}))
    rec = _adapter().lookup_remote_record("gen-x")
    assert rec.remote_cost_micros is None


def test_200_error_envelope_is_unavailable_not_found(monkeypatch):
    # A gateway that 200-wraps an error must not render as a misleading join, and must not echo the body.
    _install_client(monkeypatch, response=_Resp(200, {"error": {"message": "no credits", "code": 402}}))
    rec = _adapter().lookup_remote_record("gen-x")
    assert rec.outcome == "unavailable"
    assert "no credits" not in str(asdict(rec))


def test_missing_key_is_not_authorized_without_http(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    captured = _install_client(monkeypatch, response=_Resp(200, {}))
    rec = _adapter().lookup_remote_record("gen-x")
    assert rec.outcome == "not_authorized"
    assert "constructed" not in captured  # pre-check short-circuits before any HTTP


def test_no_key_value_echoed_anywhere(monkeypatch):
    _install_client(monkeypatch, response=_Resp(200, {"data": {"id": "gen-x"}}))
    rec = _adapter().lookup_remote_record("gen-x")
    assert "SECRET" not in str(asdict(rec))


def test_fetch_activity_is_follow_on(monkeypatch):
    with pytest.raises(RemoteAdapterError):
        _adapter().fetch_activity(period_start=None, period_end=None)
