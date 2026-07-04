"""Regression: the proxy auth-retry success path must WRITE a readable provider-trace record.

Bug (accidental_complexity_cleanup, Defect B): ``create_message``'s auth-retry branch
(``except AuthenticationError:`` -> ``client_factory.invalidate_and_retry``) makes a real
provider call and records cost + metrics, but never called ``record_provider_trace`` --
the only two trace call-sites were the non-retry success paths. A 401 -> credential
refresh -> 200-on-retry therefore produced cost/metrics with NO provider-trace record,
the exact "what happened to this request?" gap the plane exists to close (origin: a
supervised fork routed through OpenRouter).

These tests drive ``create_message`` through the retry branch with the **real**
``record_provider_trace`` helper (not a spy) and read the result back via
``read_provider_traces(request_id=...)``, so they prove the retry path (a) writes a
readable downstream provider-trace record on a provider-trace-capable backend, and
(b) writes none on a non-capable backend (the capability gate holds). Root cause + fix:
``src/forge/proxy/server.py``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from forge.backend.sources import get_model_source
from forge.proxy import provider_trace_logger as ptl

pytestmark = pytest.mark.regression


class _DummyRequestState:
    def __init__(self, request_id: str) -> None:
        self.request_id = request_id


class _DummyRawRequest:
    def __init__(self, request_id: str) -> None:
        self.state = _DummyRequestState(request_id)


class _DummyAnthropicResponse:
    def model_dump(self) -> dict:
        return {"content": [], "usage": {"input_tokens": 0, "output_tokens": 0}}


def _make_request_data() -> Any:
    """Minimal non-streaming request_data stub for create_message."""
    return type(
        "Req",
        (),
        {
            "has_explicit_tier": True,
            "tier": "sonnet",
            "stream": False,
            "messages": [],
            "tools": None,
            "system": None,
            "temperature": None,
            "max_tokens": 1,
            "top_p": None,
            "stop_sequences": None,
            "original_model_name": "claude-sonnet",
            "model": "claude-sonnet",
            "model_dump": lambda self=None: {},
        },
    )()


def _stub_server(monkeypatch, server, *, backend: str) -> None:
    """Stub the server's side-effect seams; `backend` drives the provider-trace gate.

    Leaves the real ``record_provider_trace`` in place so the write path runs end to end.
    """
    monkeypatch.setattr(server, "reload", lambda: None)
    monkeypatch.setattr(server, "log_request_response", AsyncMock())
    monkeypatch.setattr(server, "log_request_beautifully", lambda *a, **k: None)
    monkeypatch.setattr(server, "log_tool_event", lambda *a, **k: None)
    monkeypatch.setattr(server, "_check_client_tool_failures", AsyncMock())
    monkeypatch.setattr(server, "map_model_name", lambda v: v)
    monkeypatch.setattr(server, "convert_anthropic_to_openai", lambda *a, **k: {"messages": []})
    monkeypatch.setattr(server, "convert_openai_to_anthropic", lambda *a, **k: _DummyAnthropicResponse())
    monkeypatch.setattr(
        server.client_factory,
        "detect_provider_for_model",
        lambda *_: type("E", (), {"value": "openai"})(),
    )

    class ProxyCfg:
        default_tier = "sonnet"
        preferred_provider = "openai"
        backend = ""  # _backend_instance_id() reads config.proxy.backend

        @staticmethod
        def get_model_for_tier(_tier: str) -> str:
            return "openai/gpt-5.5"

    cfg = ProxyCfg()
    cfg.backend = backend
    monkeypatch.setattr(server.config, "proxy", cfg)


def _wire_auth_retry(monkeypatch, server) -> None:
    """First create_completion 401s; invalidate_and_retry returns a succeeding client."""
    from forge.core.llm.errors import AuthenticationError

    async def _auth_failing_get_client(*args, **kwargs):
        client = AsyncMock()
        client.create_completion = AsyncMock(side_effect=AuthenticationError("openai", "token expired"))
        return client

    async def _retry_client(*args, **kwargs):
        client = AsyncMock()
        client.create_completion = AsyncMock(
            return_value={
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 300, "completion_tokens": 75, "total_tokens": 375, "cached_tokens": 100},
            }
        )
        return client

    monkeypatch.setattr(server.client_factory, "get_client", _auth_failing_get_client)
    monkeypatch.setattr(server.client_factory, "invalidate_and_retry", _retry_client)


@pytest.mark.asyncio
async def test_auth_retry_capable_backend_writes_readable_trace(monkeypatch, tmp_path):
    """Capable backend: the retry path writes exactly one readable provider-trace record."""
    import forge.proxy.server as server
    from forge.proxy.metrics import proxy_metrics

    # Premise: openrouter is provider-trace capable (fail loudly if the catalog changes).
    assert get_model_source("openrouter").capabilities.provider_trace is True

    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    ptl._warned_newer_schema = False
    proxy_metrics.reset()
    try:
        _stub_server(monkeypatch, server, backend="openrouter")
        _wire_auth_retry(monkeypatch, server)

        resp = await server.create_message(_make_request_data(), _DummyRawRequest("req_retry_cap"))
        assert resp.status_code == 200

        # Read the real downstream plane back: the retry wrote a retrievable trace record.
        traces = ptl.read_provider_traces(request_id="req_retry_cap")
        assert len(traces) == 1, f"expected one readable provider-trace on the retry path, got {len(traces)}"
        rec = traces[0]
        assert rec.request_id == "req_retry_cap"
        assert rec.request_mode == "non_streaming"
        assert rec.latency_ms is not None
    finally:
        proxy_metrics.reset()


@pytest.mark.asyncio
async def test_auth_retry_non_capable_backend_writes_no_trace(monkeypatch, tmp_path):
    """Non-capable backend: the retry path writes no provider-trace record (gate holds)."""
    import forge.proxy.server as server
    from forge.proxy.metrics import proxy_metrics

    # Premise: anthropic-passthrough resolves and is NOT provider-trace capable -- so a
    # zero result proves the capability gate, not an unknown-backend fallthrough.
    assert get_model_source("anthropic-passthrough").capabilities.provider_trace is False

    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    ptl._warned_newer_schema = False
    proxy_metrics.reset()
    try:
        _stub_server(monkeypatch, server, backend="anthropic-passthrough")
        _wire_auth_retry(monkeypatch, server)

        resp = await server.create_message(_make_request_data(), _DummyRawRequest("req_retry_noncap"))
        assert resp.status_code == 200

        # The retry's cost record (no provider-trace fields) is filtered out by the read,
        # so a non-capable backend yields no provider-trace record.
        assert ptl.read_provider_traces(request_id="req_retry_noncap") == []
    finally:
        proxy_metrics.reset()
