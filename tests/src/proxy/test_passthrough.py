"""Unit tests for Anthropic passthrough forwarding (Phase 2 audit proxy)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from forge.proxy import passthrough


class _FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        content: bytes = b'{"ok":true}',
        headers: dict | None = None,
    ) -> None:
        self.status_code = status_code
        self.content = content
        self.headers = headers or {"content-type": "application/json"}


class _FakeStream:
    def __init__(
        self,
        status_code: int = 200,
        chunks: tuple[bytes, ...] = (b"event: message_start\n\n",),
        headers: dict | None = None,
    ) -> None:
        self.status_code = status_code
        self._chunks = chunks
        self.headers = headers or {"content-type": "application/json"}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def aiter_bytes(self):
        for chunk in self._chunks:
            yield chunk

    async def aread(self) -> bytes:
        return b"".join(self._chunks)


class _FakeAsyncClient:
    """Records the outbound request and returns canned responses."""

    captured: dict = {}

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, headers=None, json=None):
        _FakeAsyncClient.captured = {"url": url, "headers": headers, "json": json}
        return _FakeResponse()

    def stream(self, method, url, headers=None, json=None):
        _FakeAsyncClient.captured = {
            "method": method,
            "url": url,
            "headers": headers,
            "json": json,
        }
        return _FakeStream()


def test_build_upstream_headers_injects_key_and_forwards_flags():
    inbound = {
        "authorization": "Bearer client-secret",
        "x-api-key": "client-key",
        "anthropic-version": "2023-06-01",
        "anthropic-beta": "prompt-caching-2024-07-31",
        "user-agent": "claude-cli/2.1",
    }
    headers = passthrough.build_upstream_headers(inbound, "UPSTREAM-KEY")

    assert headers["x-api-key"] == "UPSTREAM-KEY"  # injected upstream credential
    assert headers["anthropic-version"] == "2023-06-01"
    assert headers["anthropic-beta"] == "prompt-caching-2024-07-31"
    # Client credentials are never forwarded upstream.
    assert "authorization" not in headers


def test_build_upstream_headers_defaults_anthropic_version():
    headers = passthrough.build_upstream_headers({}, "K")
    assert headers["anthropic-version"] == "2023-06-01"


@pytest.mark.asyncio
async def test_forward_sends_raw_body_unchanged(monkeypatch):
    monkeypatch.setattr(passthrough.httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.captured = {}

    raw_body = {
        "model": "claude-opus-4-6",
        "max_tokens": 100,
        "messages": [{"role": "user", "content": "hi"}],
        "future_unknown_field": {"keep": "me"},
    }
    resp = await passthrough.forward(
        raw_body=raw_body,
        inbound_headers={"anthropic-version": "2023-06-01"},
        base_url="https://api.anthropic.com",
        api_key="K",
        request_id="req_1",
    )

    captured = _FakeAsyncClient.captured
    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["json"] == raw_body  # forwarded byte-for-byte, unknown field intact
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_forward_count_tokens_path(monkeypatch):
    monkeypatch.setattr(passthrough.httpx, "AsyncClient", _FakeAsyncClient)
    raw_body = {
        "model": "claude-opus-4-6",
        "messages": [{"role": "user", "content": "hi"}],
    }

    await passthrough.forward(
        raw_body=raw_body,
        inbound_headers={},
        base_url="https://api.anthropic.com/",  # trailing slash normalized
        api_key="K",
        request_id="req_2",
        path="/v1/messages/count_tokens",
    )

    assert _FakeAsyncClient.captured["url"] == "https://api.anthropic.com/v1/messages/count_tokens"


@pytest.mark.asyncio
async def test_forward_streaming_returns_event_stream(monkeypatch):
    monkeypatch.setattr(passthrough.httpx, "AsyncClient", _FakeAsyncClient)
    raw_body = {"model": "m", "max_tokens": 10, "stream": True, "messages": []}

    resp = await passthrough.forward(
        raw_body=raw_body,
        inbound_headers={},
        base_url="https://api.anthropic.com",
        api_key="K",
        request_id="req_3",
    )

    assert resp.media_type == "text/event-stream"
    chunks = [chunk async for chunk in resp.body_iterator]
    assert b"".join(c if isinstance(c, bytes) else c.encode() for c in chunks)


@pytest.mark.asyncio
async def test_forward_streaming_upstream_error_preserves_status(monkeypatch):
    class _StreamingErrorClient(_FakeAsyncClient):
        def stream(self, method, url, headers=None, json=None):
            return _FakeStream(
                status_code=401,
                chunks=(b'{"type":"error","error":{"type":"authentication_error"}}',),
            )

    monkeypatch.setattr(passthrough.httpx, "AsyncClient", _StreamingErrorClient)
    captured: dict = {}

    def _on_complete(usage, body, failed):
        captured.update(usage=usage, body=body, failed=failed)

    resp = await passthrough.forward(
        raw_body={"model": "m", "max_tokens": 10, "stream": True, "messages": []},
        inbound_headers={},
        base_url="https://api.anthropic.com",
        api_key="K",
        request_id="req_401",
        on_complete=_on_complete,
    )

    assert resp.status_code == 401
    assert b"authentication_error" in bytes(resp.body)
    assert captured == {"usage": {}, "body": None, "failed": True}


@pytest.mark.asyncio
async def test_passthrough_handler_forwards_raw_body(monkeypatch, proxy_runtime_ready):
    """_handle_anthropic_passthrough (the middleware's delegate) reads the RAW body and forwards it."""
    server = proxy_runtime_ready

    class _Provider:
        base_url = "https://api.anthropic.com"

    class ProxyCfg:
        wire_shape = "anthropic_passthrough"

        def get_provider(self, name=None):
            return _Provider()

    monkeypatch.setattr(server.config, "proxy", ProxyCfg())
    monkeypatch.setattr(
        "forge.core.auth.template_secrets.resolve_env_or_credential",
        lambda var: "UPSTREAM-KEY" if var == "ANTHROPIC_API_KEY" else None,
    )
    monkeypatch.setattr(passthrough.httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.captured = {}

    raw_body = {
        "model": "claude-opus-4-6",
        "max_tokens": 10,
        "messages": [],
        "extra_field": 1,
    }

    class _RawReq:
        state = type("S", (), {"request_id": "req_pt"})()
        headers = {"anthropic-version": "2023-06-01", "x-api-key": "client-key"}

        async def json(self):
            return raw_body

    resp = await server._handle_anthropic_passthrough(_RawReq(), "req_pt")  # the middleware's delegate

    assert _FakeAsyncClient.captured["json"] == raw_body
    assert _FakeAsyncClient.captured["json"]["extra_field"] == 1  # unknown field survived
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_passthrough_missing_credential_returns_401(monkeypatch, proxy_runtime_ready):
    server = proxy_runtime_ready

    class _Provider:
        base_url = "https://api.anthropic.com"

    class ProxyCfg:
        wire_shape = "anthropic_passthrough"

        def get_provider(self, name=None):
            return _Provider()

    monkeypatch.setattr(server.config, "proxy", ProxyCfg())
    monkeypatch.setattr(
        "forge.core.auth.template_secrets.resolve_env_or_credential",
        lambda var: None,
    )

    class _RawReq:
        state = type("S", (), {"request_id": "req_noauth"})()
        headers: dict = {}

        async def json(self):
            return {"model": "m", "max_tokens": 1, "messages": []}

    resp = await server._handle_anthropic_passthrough(_RawReq(), "req_noauth")
    assert resp.status_code == 401


def _passthrough_config(
    *,
    default_tier="sonnet",
    intercept_mode="passthrough",
    audit_full_body=False,
    augment="",
    guards=None,
    reasoning_effort=None,
):
    """A minimal real (non-MagicMock) config stub so header values stay strings."""
    provider = SimpleNamespace(base_url="https://api.anthropic.com")
    if reasoning_effort:
        # Apply to every tier so the model-derived tier (not just default_tier) is covered.
        provider.tier_overrides = {
            t: SimpleNamespace(reasoning_effort=reasoning_effort) for t in ("haiku", "sonnet", "opus")
        }
    intercept = SimpleNamespace(
        mode=intercept_mode,
        override=SimpleNamespace(system_prompt_augment=augment, system_prompt_guards=guards or []),
    )
    audit = SimpleNamespace(
        audit_full_body=audit_full_body,
        effective_redact_headers=lambda: set(),
        retention_days=30,
        max_total_mb=100,
    )
    proxy = SimpleNamespace(
        wire_shape="anthropic_passthrough",
        default_tier=default_tier,
        active_template="anthropic-passthrough",
        preferred_provider="litellm",
        intercept=intercept,
        audit=audit,
        get_provider=lambda name=None: provider,
    )
    return SimpleNamespace(proxy=proxy)


def test_passthrough_middleware_bypasses_validation_for_unknown_block(monkeypatch, proxy_runtime_ready):
    """Through the real ASGI app, the middleware forwards the raw body BEFORE FastAPI
    binds MessagesRequest — so an unknown/future content block type that the closed
    block union would 422 is forwarded byte-for-byte instead."""
    from forge.proxy.server import app

    server = proxy_runtime_ready
    monkeypatch.setattr(server.config, "proxy", _passthrough_config().proxy)
    monkeypatch.setattr(
        "forge.core.auth.template_secrets.resolve_env_or_credential",
        lambda var: "UPSTREAM-KEY",
    )
    monkeypatch.setattr(passthrough.httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.captured = {}

    # A nested block type absent from data_models.ContentBlock — would 422 on the route.
    raw_body = {
        "model": "claude-opus-4-6",
        "max_tokens": 16,
        "messages": [
            {
                "role": "user",
                "content": [{"type": "future_block_99", "payload": {"keep": "me"}}],
            }
        ],
    }

    from fastapi.testclient import TestClient

    client = TestClient(app)
    resp = client.post("/v1/messages", json=raw_body)

    assert resp.status_code == 200  # NOT 422 — validation was bypassed
    assert _FakeAsyncClient.captured["json"]["messages"][0]["content"][0]["type"] == "future_block_99"
    assert resp.headers["X-Resolved-Model"] == "claude-opus-4-6"  # M7: resolved-model header


@pytest.mark.parametrize(
    ("body", "status_code"),
    [
        ("{not-json", 400),
        ("[]", 422),
        ("null", 422),
    ],
)
def test_passthrough_middleware_rejects_bad_json_body(monkeypatch, proxy_runtime_ready, body, status_code):
    from fastapi.testclient import TestClient

    from forge.proxy.server import app

    server = proxy_runtime_ready
    monkeypatch.setattr(server.config, "proxy", _passthrough_config().proxy)
    monkeypatch.setattr(
        "forge.core.auth.template_secrets.resolve_env_or_credential",
        lambda var: "UPSTREAM-KEY",
    )

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/v1/messages", content=body, headers={"content-type": "application/json"})

    assert resp.status_code == status_code
    assert resp.json()["error"]["type"] == "invalid_request_error"


def test_translated_proxy_not_intercepted_by_passthrough_middleware(monkeypatch, proxy_runtime_ready):
    """A non-passthrough proxy must fall through the middleware to the normal route —
    the passthrough handler is never reached, so default routing is untouched."""
    from fastapi.testclient import TestClient

    from forge.proxy.server import app

    server = proxy_runtime_ready
    monkeypatch.setattr(server.config, "proxy", SimpleNamespace(wire_shape="openai_translated"))

    reached = {"passthrough": False}

    async def _spy(*args, **kwargs):
        reached["passthrough"] = True
        return None

    monkeypatch.setattr(server, "_handle_anthropic_passthrough", _spy)

    # The route itself will error on the bare config; we only assert the middleware
    # did not divert this request into the passthrough handler.
    client = TestClient(app, raise_server_exceptions=False)
    client.post("/v1/messages", json={"model": "x", "max_tokens": 1, "messages": []})

    assert reached["passthrough"] is False


@pytest.mark.asyncio
async def test_passthrough_inspect_mode_writes_audit_metadata(monkeypatch, tmp_path, proxy_runtime_ready):
    """A passthrough proxy in inspect mode writes a metadata audit record (no body)."""
    from forge.proxy import audit_logger

    server = proxy_runtime_ready
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    audit_logger._drift_state.clear()
    monkeypatch.setattr(server, "PROXY_ID", "pt")

    class _Intercept:
        mode = "inspect"

    class _Audit:
        audit_full_body = False

        def effective_redact_headers(self):
            return set()

    class ProxyCfg:
        wire_shape = "anthropic_passthrough"
        active_template = "anthropic-passthrough"
        preferred_provider = "litellm"
        intercept = _Intercept()
        audit = _Audit()

        def get_provider(self, name=None):
            return SimpleNamespace(base_url="https://api.anthropic.com")

    monkeypatch.setattr(server.config, "proxy", ProxyCfg())
    monkeypatch.setattr("forge.core.auth.template_secrets.resolve_env_or_credential", lambda var: "K")
    monkeypatch.setattr(passthrough.httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.captured = {}

    raw_body = {
        "model": "claude-opus-4-6",
        "max_tokens": 10,
        "system": "You are helpful.",
        "messages": [{"role": "user", "content": "hi"}],
        "tools": [{"name": "Bash", "input_schema": {"type": "object"}}],
    }

    class _RawReq:
        state = type("S", (), {"request_id": "req_insp"})()
        headers = {"anthropic-version": "2023-06-01"}

        async def json(self):
            return raw_body

    await server._handle_anthropic_passthrough(_RawReq(), "req_insp")

    recs = audit_logger.read_audit_logs(record_type="request")
    assert len(recs) == 1
    assert recs[0]["mode"] == "inspect"
    assert recs[0]["full_body"] is False
    assert recs[0]["system_prompt_hash"] == audit_logger.hash_system_prompt("You are helpful.")
    assert recs[0]["counts"]["num_tools"] == 1


# --- Usage capture / cost / caps (B2, B3, M7) --------------------------------

# Non-streaming response carrying usage + a secret assistant text block.
_USAGE_RESPONSE = (
    b'{"id":"msg_1","type":"message","role":"assistant",'
    b'"content":[{"type":"text","text":"SECRET-RESPONSE-TEXT"}],'
    b'"usage":{"input_tokens":100,"output_tokens":50,"cache_read_input_tokens":10},'
    b'"stop_reason":"end_turn"}'
)

_SSE_USAGE_CHUNKS = (
    b'event: message_start\ndata: {"type":"message_start","message":'
    b'{"usage":{"input_tokens":200,"cache_read_input_tokens":20,"output_tokens":1}}}\n\n',
    b'event: message_delta\ndata: {"type":"message_delta","usage":{"output_tokens":77}}\n\n',
    b'event: message_stop\ndata: {"type":"message_stop"}\n\n',
)


class _UsageResponseClient(_FakeAsyncClient):
    """Returns a non-streaming response body carrying usage + secret text."""

    async def post(self, url, headers=None, json=None):
        _UsageResponseClient.captured = {"url": url, "headers": headers, "json": json}
        return _FakeResponse(content=_USAGE_RESPONSE)


class _SSEUsageClient(_FakeAsyncClient):
    def stream(self, method, url, headers=None, json=None):
        return _FakeStream(chunks=_SSE_USAGE_CHUNKS)


class _RawReq:
    """Minimal stand-in for a FastAPI Request on the passthrough path."""

    def __init__(self, body, request_id="req_x", headers=None):
        self._body = body
        self.state = type("S", (), {"request_id": request_id})()
        self.headers = headers or {"anthropic-version": "2023-06-01"}

    async def json(self):
        return self._body


def test_usage_accumulator_handles_split_chunks():
    """The SSE side-tap reconstructs final usage even when a line splits across chunks."""
    acc = passthrough._UsageAccumulator()
    acc.feed(b"event: message_start\nda")
    acc.feed(b'ta: {"type":"message_start","message":{"usage":{"input_tokens":5,"output_tokens":1}}}\n\n')
    acc.feed(b'event: message_delta\ndata: {"type":"message_delta","usage":{"output_tokens":9}}\n\n')
    assert acc.usage == {"input_tokens": 5, "output_tokens": 9}


@pytest.mark.asyncio
async def test_forward_streaming_taps_usage(monkeypatch):
    """Streaming forward taps usage from the SSE and reports it via on_complete."""
    monkeypatch.setattr(passthrough.httpx, "AsyncClient", _SSEUsageClient)
    captured: dict = {}

    def _on_complete(usage, body, failed):
        captured.update(usage=usage, body=body, failed=failed)

    resp = await passthrough.forward(
        raw_body={"model": "m", "stream": True, "messages": []},
        inbound_headers={},
        base_url="https://api.anthropic.com",
        api_key="K",
        request_id="req_s",
        on_complete=_on_complete,
    )
    _ = [chunk async for chunk in resp.body_iterator]  # drain → fires on_complete in finally

    assert captured["usage"] == {
        "input_tokens": 200,
        "output_tokens": 77,
        "cached_tokens": 20,
    }
    assert captured["failed"] is False


@pytest.mark.asyncio
async def test_passthrough_logs_cost_from_response_usage(monkeypatch, proxy_runtime_ready):
    """B2: non-streaming usage flows into _calc_and_log_cost (cost is logged, not bypassed)."""
    server = proxy_runtime_ready

    monkeypatch.setattr(server.config, "proxy", _passthrough_config().proxy)
    monkeypatch.setattr("forge.core.auth.template_secrets.resolve_env_or_credential", lambda var: "K")
    monkeypatch.setattr(passthrough.httpx, "AsyncClient", _UsageResponseClient)

    captured_cost: list[dict] = []
    monkeypatch.setattr(server, "_calc_and_log_cost", lambda **kw: captured_cost.append(kw) or 0)

    raw_body = {
        "model": "claude-opus-4-6",
        "max_tokens": 50,
        "messages": [{"role": "user", "content": "hi"}],
    }
    resp = await server._handle_anthropic_passthrough(_RawReq(raw_body, "req_cost"), "req_cost")

    assert resp.status_code == 200
    assert resp.headers["X-Resolved-Model"] == "claude-opus-4-6"  # M7
    assert len(captured_cost) == 1
    assert captured_cost[0]["input_tokens"] == 100
    assert captured_cost[0]["output_tokens"] == 50
    assert captured_cost[0]["cached_tokens"] == 10
    assert captured_cost[0]["model"] == "claude-opus-4-6"


@pytest.mark.asyncio
async def test_passthrough_enforces_spend_cap_reject(monkeypatch, proxy_runtime_ready):
    """B2: a configured cap rejects with 429 instead of silently forwarding."""
    server = proxy_runtime_ready

    monkeypatch.setattr(server.config, "proxy", _passthrough_config().proxy)
    monkeypatch.setattr("forge.core.auth.template_secrets.resolve_env_or_credential", lambda var: "K")

    class _CapResult:
        exceeded = True
        cap_type = "daily"
        current_micros = 11_000_000
        limit_micros = 10_000_000

    class _Tracker:
        has_caps = True
        on_cap_hit = "reject"

        def check_cap(self):
            return _CapResult()

        def record(self, micros):
            pass

    monkeypatch.setattr(server, "cost_tracker", _Tracker())

    async def _boom(**kwargs):  # forward must not be reached when capped
        raise AssertionError("forward should not run when the cap rejects")

    monkeypatch.setattr("forge.proxy.passthrough.forward", _boom)

    raw_body = {"model": "claude-opus-4-6", "max_tokens": 50, "messages": []}
    resp = await server._handle_anthropic_passthrough(_RawReq(raw_body, "req_cap"), "req_cap")

    assert resp.status_code == 429
    assert b"spend_cap_exceeded" in bytes(resp.body)


@pytest.mark.asyncio
async def test_passthrough_full_body_captures_redacted_response(monkeypatch, tmp_path, proxy_runtime_ready):
    """B3/M5: full-body record includes the redacted response + request hashes, no plaintext."""
    from forge.proxy import audit_logger

    server = proxy_runtime_ready
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    audit_logger._drift_state.clear()
    monkeypatch.setattr(server, "PROXY_ID", "pt")
    monkeypatch.setattr(
        server.config,
        "proxy",
        _passthrough_config(intercept_mode="inspect", audit_full_body=True).proxy,
    )
    monkeypatch.setattr("forge.core.auth.template_secrets.resolve_env_or_credential", lambda var: "K")
    monkeypatch.setattr(passthrough.httpx, "AsyncClient", _UsageResponseClient)

    raw_body = {
        "model": "claude-opus-4-6",
        "max_tokens": 50,
        "system": "SECRET-SYSTEM",
        "messages": [{"role": "user", "content": "SECRET-USER-TEXT"}],
        "tools": [{"name": "Bash", "input_schema": {"type": "object"}}],
    }
    await server._handle_anthropic_passthrough(
        _RawReq(raw_body, "req_fb", headers={"authorization": "Bearer SECRET-TOKEN"}),
        "req_fb",
    )

    recs = [r for r in audit_logger.read_audit_logs(record_type="request") if r.get("full_body")]
    assert len(recs) == 1
    rec = recs[0]
    assert rec["response_body"] is not None  # B3: response captured
    assert rec["response_body"].get("usage", {}).get("output_tokens") == 50  # structural usage kept
    assert rec["system_prompt_hash"] == audit_logger.hash_system_prompt("SECRET-SYSTEM")  # M5
    assert rec["counts"]["num_tools"] == 1  # M5
    blob = json.dumps(rec)
    for secret in (
        "SECRET-SYSTEM",
        "SECRET-USER-TEXT",
        "SECRET-RESPONSE-TEXT",
        "SECRET-TOKEN",
    ):
        assert secret not in blob


# --- Override mode (2d) ------------------------------------------------------


@pytest.mark.asyncio
async def test_passthrough_override_mutates_body_and_records(monkeypatch, tmp_path, proxy_runtime_ready):
    """Override augments the system prompt + pins reasoning, forwards the mutated body,
    and writes a redacted mutation record."""
    from forge.proxy import audit_logger

    server = proxy_runtime_ready
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    audit_logger._drift_state.clear()
    monkeypatch.setattr(server, "PROXY_ID", "pt")
    monkeypatch.setattr(
        server.config,
        "proxy",
        _passthrough_config(intercept_mode="override", augment="STAY-FOCUSED", reasoning_effort="high").proxy,
    )
    monkeypatch.setattr("forge.core.auth.template_secrets.resolve_env_or_credential", lambda var: "K")
    monkeypatch.setattr(passthrough.httpx, "AsyncClient", _UsageResponseClient)
    _UsageResponseClient.captured = {}

    raw_body = {
        "model": "claude-opus-4-6",
        "max_tokens": 64000,
        "system": [{"type": "text", "text": "base"}],
        "messages": [{"role": "user", "content": "hi"}],
    }
    await server._handle_anthropic_passthrough(_RawReq(raw_body, "req_ov"), "req_ov")

    sent = _UsageResponseClient.captured["json"]
    assert sent["system"][-1]["text"] == "STAY-FOCUSED"  # augment forwarded
    assert sent["thinking"]["budget_tokens"] == 10000  # reasoning pinned to the 'high' floor

    recs = audit_logger.read_audit_logs(record_type="mutation")
    assert len(recs) == 1
    actions = {m["action"] for m in recs[0]["mutations"]}
    assert {"augment", "reasoning_pin"} <= actions
    assert "STAY-FOCUSED" not in json.dumps(recs[0])  # redacted: only hashes/lengths


@pytest.mark.asyncio
async def test_passthrough_override_guard_block_returns_403(monkeypatch, tmp_path, proxy_runtime_ready):
    """A block guard short-circuits with 403, records the block, and does not forward."""
    from forge.proxy import audit_logger

    server = proxy_runtime_ready
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    audit_logger._drift_state.clear()
    monkeypatch.setattr(server, "PROXY_ID", "pt")
    monkeypatch.setattr(
        server.config,
        "proxy",
        _passthrough_config(
            intercept_mode="override",
            guards=[{"pattern": "FORBIDDEN", "action": "block"}],
        ).proxy,
    )
    monkeypatch.setattr("forge.core.auth.template_secrets.resolve_env_or_credential", lambda var: "K")

    async def _boom(**kwargs):  # forward must not run when a guard blocks
        raise AssertionError("forward should not run on a blocked request")

    monkeypatch.setattr("forge.proxy.passthrough.forward", _boom)

    raw_body = {
        "model": "claude-opus-4-6",
        "max_tokens": 1000,
        "system": [{"type": "text", "text": "this has a FORBIDDEN directive"}],
        "messages": [{"role": "user", "content": "hi"}],
    }
    resp = await server._handle_anthropic_passthrough(_RawReq(raw_body, "req_blk"), "req_blk")

    assert resp.status_code == 403
    assert b"intercept_guard_blocked" in bytes(resp.body)
    recs = audit_logger.read_audit_logs(record_type="mutation")
    assert recs and recs[0]["blocked"] is True


@pytest.mark.asyncio
async def test_passthrough_override_preserves_history_through_server(monkeypatch, tmp_path, proxy_runtime_ready):
    """Through the server path, override leaves historical thinking blocks byte-identical."""
    import copy

    from forge.proxy import audit_logger

    server = proxy_runtime_ready
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    audit_logger._drift_state.clear()
    monkeypatch.setattr(server, "PROXY_ID", "pt")
    monkeypatch.setattr(
        server.config,
        "proxy",
        _passthrough_config(intercept_mode="override", augment="EXTRA").proxy,
    )
    monkeypatch.setattr("forge.core.auth.template_secrets.resolve_env_or_credential", lambda var: "K")
    monkeypatch.setattr(passthrough.httpx, "AsyncClient", _UsageResponseClient)
    _UsageResponseClient.captured = {}

    history = [
        {
            "role": "assistant",
            "content": [{"type": "thinking", "thinking": "x", "signature": "SIG-9"}],
        },
        {"role": "user", "content": "go"},
    ]
    raw_body = {
        "model": "claude-opus-4-6",
        "max_tokens": 8000,
        "system": [{"type": "text", "text": "base"}],
        "messages": copy.deepcopy(history),
    }
    await server._handle_anthropic_passthrough(_RawReq(raw_body, "req_hist"), "req_hist")

    sent = _UsageResponseClient.captured["json"]
    assert sent["messages"] == history  # signed thinking untouched
    assert sent["system"][-1]["text"] == "EXTRA"  # but the control surface was augmented


@pytest.mark.asyncio
async def test_non_override_mode_does_not_apply_override(monkeypatch, tmp_path, proxy_runtime_ready):
    """Override directives are inert unless intercept.mode == 'override' (no mutation)."""
    from forge.proxy import audit_logger

    server = proxy_runtime_ready
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    audit_logger._drift_state.clear()
    monkeypatch.setattr(server, "PROXY_ID", "pt")
    # augment IS configured, but mode is inspect -> it must NOT be applied.
    monkeypatch.setattr(
        server.config,
        "proxy",
        _passthrough_config(intercept_mode="inspect", augment="SHOULD-NOT-APPEAR").proxy,
    )
    monkeypatch.setattr("forge.core.auth.template_secrets.resolve_env_or_credential", lambda var: "K")
    monkeypatch.setattr(passthrough.httpx, "AsyncClient", _UsageResponseClient)
    _UsageResponseClient.captured = {}

    raw_body = {
        "model": "claude-opus-4-6",
        "max_tokens": 8000,
        "system": [{"type": "text", "text": "base"}],
        "messages": [{"role": "user", "content": "hi"}],
    }
    await server._handle_anthropic_passthrough(_RawReq(raw_body, "req_insp2"), "req_insp2")

    sent = _UsageResponseClient.captured["json"]
    assert sent["system"] == [{"type": "text", "text": "base"}]  # body unmutated
    assert "thinking" not in sent
    assert audit_logger.read_audit_logs(record_type="mutation") == []  # no mutation record


@pytest.mark.asyncio
async def test_passthrough_override_uses_model_tier_not_default(monkeypatch, tmp_path, proxy_runtime_ready):
    """Reasoning pin keys off the request's model tier (opus), not proxy default_tier (sonnet)."""
    from forge.proxy import audit_logger

    server = proxy_runtime_ready
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    audit_logger._drift_state.clear()
    monkeypatch.setattr(server, "PROXY_ID", "pt")

    cfg = _passthrough_config(default_tier="sonnet", intercept_mode="override")
    # opus pinned 'high', sonnet pinned 'minimal' -> an opus request must pick HIGH.
    cfg.proxy.get_provider().tier_overrides = {
        "opus": SimpleNamespace(reasoning_effort="high"),
        "sonnet": SimpleNamespace(reasoning_effort="minimal"),
    }
    monkeypatch.setattr(server.config, "proxy", cfg.proxy)
    monkeypatch.setattr("forge.core.auth.template_secrets.resolve_env_or_credential", lambda var: "K")
    monkeypatch.setattr(passthrough.httpx, "AsyncClient", _UsageResponseClient)
    _UsageResponseClient.captured = {}

    raw_body = {
        "model": "claude-opus-4-6",
        "max_tokens": 64000,
        "system": [{"type": "text", "text": "s"}],
        "messages": [{"role": "user", "content": "hi"}],
    }
    await server._handle_anthropic_passthrough(_RawReq(raw_body, "req_t4"), "req_t4")

    sent = _UsageResponseClient.captured["json"]
    assert sent["thinking"]["budget_tokens"] == 10000  # opus 'high' floor, not sonnet 'minimal'


@pytest.mark.asyncio
async def test_passthrough_override_invariant_violation_fails_closed(monkeypatch, proxy_runtime_ready):
    """A mutation-safety fingerprint mismatch raises and never forwards (fail closed)."""
    from forge.proxy import intercept

    server = proxy_runtime_ready
    monkeypatch.setattr(server, "PROXY_ID", "pt")
    monkeypatch.setattr(
        server.config,
        "proxy",
        _passthrough_config(intercept_mode="override", augment="X").proxy,
    )
    monkeypatch.setattr("forge.core.auth.template_secrets.resolve_env_or_credential", lambda var: "K")

    async def _boom(**kwargs):
        raise AssertionError("forward must not run after an invariant violation")

    monkeypatch.setattr("forge.proxy.passthrough.forward", _boom)

    # Force the post-mutation fingerprint to differ -> apply_override raises.
    calls = {"n": 0}
    real_fp = intercept.messages_fingerprint

    def _fp(messages):
        calls["n"] += 1
        return "sha256:tampered" if calls["n"] == 2 else real_fp(messages)

    monkeypatch.setattr(intercept, "messages_fingerprint", _fp)

    raw_body = {
        "model": "claude-opus-4-6",
        "max_tokens": 8000,
        "system": [{"type": "text", "text": "s"}],
        "messages": [{"role": "user", "content": "hi"}],
    }
    with pytest.raises(RuntimeError, match="mutation-safety invariant"):
        await server._handle_anthropic_passthrough(_RawReq(raw_body, "req_inv"), "req_inv")


@pytest.mark.asyncio
async def test_override_full_body_record_is_self_consistent(monkeypatch, tmp_path, proxy_runtime_ready):
    """#6: the full-body record pairs the MUTATED body with a hash recomputed from it."""
    from forge.proxy import audit_logger

    server = proxy_runtime_ready
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    audit_logger._drift_state.clear()
    monkeypatch.setattr(server, "PROXY_ID", "pt")
    monkeypatch.setattr(
        server.config,
        "proxy",
        _passthrough_config(intercept_mode="override", augment="AUGTEXT", audit_full_body=True).proxy,
    )
    monkeypatch.setattr("forge.core.auth.template_secrets.resolve_env_or_credential", lambda var: "K")
    monkeypatch.setattr(passthrough.httpx, "AsyncClient", _UsageResponseClient)
    _UsageResponseClient.captured = {}

    raw_body = {
        "model": "claude-opus-4-6",
        "max_tokens": 8000,
        "system": [{"type": "text", "text": "base"}],
        "messages": [{"role": "user", "content": "hi"}],
    }
    await server._handle_anthropic_passthrough(_RawReq(raw_body, "req_fbc"), "req_fbc")

    sent = _UsageResponseClient.captured["json"]
    fb = [r for r in audit_logger.read_audit_logs(record_type="request") if r.get("full_body")]
    assert len(fb) == 1
    # The record's hash matches the MUTATED (augmented) system, not the pre-mutation one.
    assert fb[0]["system_prompt_hash"] == audit_logger.hash_system_prompt(sent["system"])
    assert fb[0]["system_prompt_hash"] != audit_logger.hash_system_prompt([{"type": "text", "text": "base"}])


# ---------------------------------------------------------------------------
# Provider-trace mirror (forward-wiring)
# ---------------------------------------------------------------------------

_SSE_CONTENT_CHUNKS = (
    b'event: message_start\ndata: {"type":"message_start","message":'
    b'{"usage":{"input_tokens":10,"output_tokens":1}}}\n\n',
    b'event: content_block_start\ndata: {"type":"content_block_start","index":0,'
    b'"content_block":{"type":"text","text":""}}\n\n',
    b'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,'
    b'"delta":{"type":"text_delta","text":"hi"}}\n\n',
    b'event: message_delta\ndata: {"type":"message_delta","usage":{"output_tokens":5}}\n\n',
    b'event: message_stop\ndata: {"type":"message_stop"}\n\n',
)

_PT_CTX = {
    # passthrough source (anthropic-passthrough) has no provider-trace capability -> no write
    "backend_id": "anthropic-passthrough",
    "proxy_id": "crimson-apricot",
    "mapped_model": "claude-opus-4-6",
    "request_id": "req_pt",
    "forge_run_id": "run_abc",
    "forge_root_run_id": "run_root",
    "provider_session_id": "forge_sess_abc",
    "provider_command": "supervisor",
}


class _SSEContentClient(_FakeAsyncClient):
    def stream(self, method, url, headers=None, json=None):
        return _FakeStream(chunks=_SSE_CONTENT_CHUNKS)


@pytest.mark.asyncio
async def test_passthrough_mirror_records_lifecycle_flags(monkeypatch):
    """The relay computes the four lifecycle flags and calls the one shared helper."""
    monkeypatch.setattr(passthrough.httpx, "AsyncClient", _SSEContentClient)
    captured: list[dict] = []
    monkeypatch.setattr(passthrough, "record_provider_trace", lambda **kw: captured.append(kw))

    resp = await passthrough.forward(
        raw_body={"model": "m", "stream": True, "messages": []},
        inbound_headers={},
        base_url="https://api.anthropic.com",
        api_key="K",
        request_id="req_pt",
        provider_trace_ctx=_PT_CTX,
    )
    _ = [chunk async for chunk in resp.body_iterator]  # drain -> fires the mirror in finally

    assert len(captured) == 1
    call = captured[0]
    assert call["request_mode"] == "streaming"
    assert call["provider_meta"] is None  # no provider_meta on the Anthropic-native wire
    assert call["stream_started"] is True
    assert call["first_chunk_seen"] is True  # content_block_start was seen
    assert call["final_usage_seen"] is True  # message_delta carried output_tokens
    assert call["client_disconnected"] is False
    assert call["reported_cost_micros"] is None  # passthrough cost is structurally unavailable
    # Context threaded from the server is carried through verbatim.
    assert call["backend_id"] == "anthropic-passthrough"
    assert call["provider_session_id"] == "forge_sess_abc"


@pytest.mark.asyncio
async def test_passthrough_mirror_is_latent_for_non_capable_source(monkeypatch, tmp_path):
    """End-to-end through the REAL helper: a source without provider-trace capability persists nothing."""
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    monkeypatch.setattr(passthrough.httpx, "AsyncClient", _SSEContentClient)

    resp = await passthrough.forward(
        raw_body={"model": "m", "stream": True, "messages": []},
        inbound_headers={},
        base_url="https://api.anthropic.com",
        api_key="K",
        request_id="req_pt",
        provider_trace_ctx=_PT_CTX,  # backend_id="anthropic-passthrough"
    )
    _ = [chunk async for chunk in resp.body_iterator]

    from forge.proxy import provider_trace_logger as ptl

    assert ptl.read_provider_traces() == []  # gate suppressed the write


class _CancelStream(_FakeStream):
    async def aiter_bytes(self):
        yield (
            b'event: content_block_start\ndata: {"type":"content_block_start","index":0,'
            b'"content_block":{"type":"text","text":""}}\n\n'
        )
        raise asyncio.CancelledError()


@pytest.mark.asyncio
async def test_passthrough_mirror_records_disconnect(monkeypatch):
    """A cancelled relay records client_disconnected and re-raises (not swallowed)."""
    captured: list[dict] = []
    monkeypatch.setattr(passthrough, "record_provider_trace", lambda **kw: captured.append(kw))

    client_cm = SimpleNamespace(__aexit__=_noop_aexit)
    stream_cm = SimpleNamespace(__aexit__=_noop_aexit)

    async def _drain():
        agen = passthrough._stream_opened_upstream(
            client_cm, stream_cm, _CancelStream(), "req_x", provider_trace_ctx=_PT_CTX
        )
        async for _chunk in agen:
            pass

    with pytest.raises(asyncio.CancelledError):
        await _drain()

    assert len(captured) == 1
    assert captured[0]["client_disconnected"] is True
    assert captured[0]["first_chunk_seen"] is True  # content_block_start arrived before the cancel


async def _noop_aexit(*exc):
    return False


def test_passthrough_does_not_import_server():
    """The shared helper lives in the neutral leaf -> passthrough never imports server."""
    src = Path(passthrough.__file__).read_text()
    assert "from forge.proxy.server import" not in src
    assert "import forge.proxy.server" not in src
