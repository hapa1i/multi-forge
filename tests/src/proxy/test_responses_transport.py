"""Unit tests for the OpenAI Responses passthrough transport (Codex-facing ingress).

Covers the wire-shape's three honesty constraints from the card:
- byte-faithful forwarding (method/body/query preserved, no `.json()` on bodyless);
- token telemetry always, dollar cost ONLY when the upstream reports it (USD->micros);
- the capability gate mirrored across the route, GET / advertisement, and preflight.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

import forge.proxy.responses_ingress as ri
import forge.proxy.responses_passthrough as rp
from forge.core.credential_registry import Credential, EnvVar


class _FakeResponse:
    """Stand-in for an httpx non-streaming response (request() return)."""

    def __init__(
        self,
        status_code: int = 200,
        content: bytes = b'{"id":"resp_1","usage":{"input_tokens":11,"output_tokens":7}}',
        headers: dict | None = None,
    ) -> None:
        self.status_code = status_code
        self.content = content
        self.headers = headers or {"content-type": "application/json"}


class _FakeStream:
    """Stand-in for an httpx streaming-response context manager."""

    def __init__(
        self,
        status_code: int = 200,
        chunks: tuple[bytes, ...] = (b"event: response.completed\n\n",),
        headers: dict | None = None,
    ) -> None:
        self.status_code = status_code
        self._chunks = chunks
        self.headers = headers or {"content-type": "text/event-stream"}

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
    """Records the outbound request and returns canned responses.

    Single shared ``captured`` dict so a test can read what crossed the wire
    (method, url, headers, json) regardless of streaming vs non-streaming.
    """

    captured: dict = {}
    response_factory = staticmethod(_FakeResponse)
    stream_factory = staticmethod(_FakeStream)

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def request(self, method, url, headers=None, json=None):
        _FakeAsyncClient.captured = {"method": method, "url": url, "headers": headers, "json": json}
        return type(self).response_factory()

    def stream(self, method, url, headers=None, json=None):
        _FakeAsyncClient.captured = {"method": method, "url": url, "headers": headers, "json": json}
        return type(self).stream_factory()


@pytest.fixture(autouse=True)
def _reset_captured():
    """Isolate the class-level ``_FakeAsyncClient.captured`` between tests.

    The fake records the last outbound request on a shared class attribute; resetting
    it before every test removes the cross-test bleed in one place (module-local state,
    so it lives here rather than in conftest.py).
    """
    _FakeAsyncClient.captured = {}
    yield


# ── Header builder (g) ──────────────────────────────────────────────────────────────


def test_build_upstream_headers_injects_bearer_and_forwards_openai_beta():
    inbound = {
        "authorization": "Bearer client-secret",
        "openai-beta": "responses=v1",
        "user-agent": "codex/0.141",
    }
    headers = rp.build_upstream_headers(inbound, "UPSTREAM-KEY")

    assert headers["authorization"] == "Bearer UPSTREAM-KEY"  # proxy's own credential
    assert headers["openai-beta"] == "responses=v1"  # behavior flag forwarded
    assert headers["content-type"] == "application/json"
    # Client's inbound bearer must never reach upstream as-is (only the injected key).
    assert "Bearer client-secret" not in headers.values()


def test_build_upstream_headers_strips_org_and_project():
    # OpenAI-Organization/OpenAI-Project are auth-like: the proxy's upstream
    # credential owns org/project selection, not the Codex child.
    inbound = {
        "OpenAI-Organization": "org-client",
        "OpenAI-Project": "proj-client",
        "openai-beta": "responses=v1",
    }
    headers = rp.build_upstream_headers(inbound, "K")

    lowered = {k.lower() for k in headers}
    assert "openai-organization" not in lowered
    assert "openai-project" not in lowered
    assert headers["openai-beta"] == "responses=v1"  # the one allowlisted flag survives


def test_relay_response_headers_strips_hop_by_hop_keeps_safe():
    upstream = {
        "content-type": "text/event-stream",
        "transfer-encoding": "chunked",  # hop-by-hop framing -> stripped
        "content-length": "123",  # framing -> stripped
        "set-cookie": "sid=abc",  # security -> stripped
        "x-request-id": "upstream-req",  # proxy-owned -> dropped (no duplicate)
        "openai-processing-ms": "42",  # safe -> forwarded
    }
    out = rp.relay_response_headers(upstream, "req_hdr")

    assert out["X-Request-ID"] == "req_hdr"  # proxy stamps its own id
    assert "x-request-id" not in out  # upstream's is dropped so it can't shadow the proxy's
    assert out["openai-processing-ms"] == "42"
    assert "transfer-encoding" not in out
    assert "content-length" not in out
    assert "set-cookie" not in out


# ── Cost USD->micros (d) ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("header_value", "expected"),
    [
        ("0.000123", 123),  # decimal USD -> micros, rounded
        ("1", 1_000_000),  # whole-dollar string
        (0.5, 500_000),  # numeric value
        ("0", 0),  # a real zero cost is reported, not invented
    ],
)
def test_reported_cost_micros_usd_to_micros(header_value, expected):
    assert rp.reported_cost_micros_from_headers({"x-litellm-response-cost": header_value}) == expected


@pytest.mark.parametrize(
    "headers",
    [
        {},  # absent header -> unavailable
        {"x-litellm-response-cost": "-0.01"},  # negative -> rejected
        {"x-litellm-response-cost": "not-a-number"},  # malformed -> unavailable
        {"x-litellm-response-cost": True},  # bool is not a real cost
        None,  # no headers object at all
    ],
)
def test_reported_cost_micros_rejects_bad_values(headers):
    assert rp.reported_cost_micros_from_headers(headers) is None


# ── Usage side-tap (c) ──────────────────────────────────────────────────────────────


def test_responses_usage_accumulator_parses_completed_event():
    acc = rp._ResponsesUsageAccumulator()
    # A content delta marks first-chunk-seen; the terminal event carries usage.
    acc.feed(b'data: {"type":"response.output_text.delta","delta":"hi"}\n\n')
    assert acc.first_chunk_seen is True
    assert acc.final_usage_seen is False

    acc.feed(
        b'data: {"type":"response.completed","response":{"usage":'
        b'{"input_tokens":12,"output_tokens":34,"input_tokens_details":{"cached_tokens":5}}}}\n\n'
    )
    assert acc.final_usage_seen is True
    assert acc.usage == {"input_tokens": 12, "output_tokens": 34, "cached_tokens": 5}


def test_responses_usage_accumulator_tolerates_split_and_garbage():
    acc = rp._ResponsesUsageAccumulator()
    # Lines split across chunk boundaries + non-data noise must not raise or corrupt.
    acc.feed(b'data: {"type":"response.out')
    acc.feed(b'put_item.added"}\n\n')
    acc.feed(b": keep-alive comment\n")
    acc.feed(b"data: [DONE]\n\n")
    assert acc.first_chunk_seen is True
    assert acc.usage == {}  # no completed event -> no usage, but no crash


def test_extract_usage_from_non_streaming_body():
    body = {"id": "resp_1", "usage": {"input_tokens": 8, "output_tokens": 2}}
    assert rp.extract_usage_from_response(body) == {"input_tokens": 8, "output_tokens": 2}
    assert rp.extract_usage_from_response("not a mapping") == {}


# ── forward(): non-streaming POST (a, c, d) ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_forward_non_streaming_post_relays_and_accounts(monkeypatch):
    monkeypatch.setattr(rp.httpx, "AsyncClient", _FakeAsyncClient)

    class _CostingResponse(_FakeResponse):
        def __init__(self):
            super().__init__(
                content=b'{"usage":{"input_tokens":11,"output_tokens":7}}',
                headers={"content-type": "application/json", "x-litellm-response-cost": "0.000123"},
            )

    monkeypatch.setattr(_FakeAsyncClient, "response_factory", staticmethod(_CostingResponse))
    seen: dict = {}

    def _on_complete(usage, cost_micros, failed, error_type):
        seen.update(usage=usage, cost_micros=cost_micros, failed=failed, error_type=error_type)

    body = {"model": "gpt-5.5-codex", "input": "hi", "stream": False, "unknown_future_field": 1}
    resp = await rp.forward(
        method="POST",
        url_path="/v1/responses",
        body=body,
        query_string="",
        inbound_headers={"openai-beta": "responses=v1"},
        base_url="https://upstream.test",
        api_key="UP",
        request_id="req_ns",
        on_complete=_on_complete,
    )

    captured = _FakeAsyncClient.captured
    assert captured["method"] == "POST"
    assert captured["url"] == "https://upstream.test/v1/responses"
    assert captured["json"] == body  # byte-faithful, unknown field intact
    assert resp.status_code == 200
    # Token telemetry from the body; real dollar cost from the upstream header (USD->micros).
    assert seen == {
        "usage": {"input_tokens": 11, "output_tokens": 7},
        "cost_micros": 123,
        "failed": False,
        "error_type": None,
    }


@pytest.mark.asyncio
async def test_forward_non_streaming_without_cost_header_is_unavailable(monkeypatch):
    monkeypatch.setattr(rp.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(_FakeAsyncClient, "response_factory", staticmethod(_FakeResponse))
    seen: dict = {}

    await rp.forward(
        method="POST",
        url_path="/v1/responses",
        body={"model": "m", "input": "hi"},
        query_string="",
        inbound_headers={},
        base_url="https://upstream.test",
        api_key="UP",
        request_id="req_nocost",
        on_complete=lambda u, c, f, e: seen.update(usage=u, cost=c, failed=f),
    )
    # Token usage present; cost unavailable (no x-litellm-response-cost) -> never invented.
    assert seen["usage"] == {"input_tokens": 11, "output_tokens": 7}
    assert seen["cost"] is None


# ── forward(): streaming POST (a) ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_forward_streaming_post_relays_bytes_and_usage(monkeypatch):
    sse = (
        b'data: {"type":"response.output_text.delta","delta":"he"}\n\n',
        b'data: {"type":"response.completed","response":{"usage":' b'{"input_tokens":20,"output_tokens":9}}}\n\n',
    )

    class _SSEStream(_FakeStream):
        def __init__(self):
            super().__init__(
                chunks=sse,
                headers={"content-type": "text/event-stream", "x-litellm-response-cost": "0.0005"},
            )

    monkeypatch.setattr(rp.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(_FakeAsyncClient, "stream_factory", staticmethod(_SSEStream))
    seen: dict = {}

    resp = await rp.forward(
        method="POST",
        url_path="/v1/responses",
        body={"model": "m", "input": "hi", "stream": True},
        query_string="",
        inbound_headers={},
        base_url="https://upstream.test",
        api_key="UP",
        request_id="req_stream",
        on_complete=lambda u, c, f, e: seen.update(usage=u, cost=c, failed=f, error_type=e),
    )

    assert resp.media_type == "text/event-stream"
    assert _FakeAsyncClient.captured["method"] == "POST"
    streamed = b"".join([c if isinstance(c, bytes) else c.encode() async for c in resp.body_iterator])
    assert streamed == b"".join(sse)  # byte-faithful relay
    # Stream end fires on_complete with usage from response.completed + cost from header.
    assert seen == {
        "usage": {"input_tokens": 20, "output_tokens": 9},
        "cost": 500,
        "failed": False,
        "error_type": None,
    }


# ── forward(): bodyless + non-{id} surface (b) ──────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["GET", "DELETE"])
async def test_forward_bodyless_sends_no_json(monkeypatch, method):
    monkeypatch.setattr(rp.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(_FakeAsyncClient, "response_factory", staticmethod(_FakeResponse))

    await rp.forward(
        method=method,
        url_path="/v1/responses/resp_abc",
        body=None,  # the route never calls .json() on a bodyless request
        query_string="",
        inbound_headers={},
        base_url="https://upstream.test/",  # trailing slash normalized
        api_key="UP",
        request_id="req_bodyless",
    )

    captured = _FakeAsyncClient.captured
    assert captured["method"] == method
    assert captured["url"] == "https://upstream.test/v1/responses/resp_abc"
    assert captured["json"] is None  # bodyless -> no JSON body sent upstream


@pytest.mark.asyncio
async def test_forward_top_level_non_id_path_preserves_query(monkeypatch):
    # A top-level non-{id} Responses path (e.g. input_tokens) must forward through
    # the same catch-all with method + query preserved.
    monkeypatch.setattr(rp.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(_FakeAsyncClient, "response_factory", staticmethod(_FakeResponse))

    await rp.forward(
        method="POST",
        url_path="/v1/responses/input_tokens",
        body={"model": "m", "input": "count me"},
        query_string="include=usage",
        inbound_headers={},
        base_url="https://upstream.test",
        api_key="UP",
        request_id="req_toplevel",
    )

    assert _FakeAsyncClient.captured["url"] == "https://upstream.test/v1/responses/input_tokens?include=usage"
    assert _FakeAsyncClient.captured["method"] == "POST"


@pytest.mark.asyncio
async def test_forward_relays_response_headers_with_allowlist(monkeypatch):
    class _HeaderedResponse(_FakeResponse):
        def __init__(self):
            super().__init__(
                headers={
                    "content-type": "application/json",
                    "transfer-encoding": "chunked",  # stripped
                    "x-request-id": "up-1",  # proxy-owned -> dropped, not duplicated
                    "openai-version": "2020-10-01",  # safe -> forwarded
                }
            )

    monkeypatch.setattr(rp.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(_FakeAsyncClient, "response_factory", staticmethod(_HeaderedResponse))

    resp = await rp.forward(
        method="GET",
        url_path="/v1/responses/resp_1",
        body=None,
        query_string="",
        inbound_headers={},
        base_url="https://upstream.test",
        api_key="UP",
        request_id="req_relayhdr",
    )

    # The proxy owns X-Request-ID; upstream's colliding copy is dropped (exactly one row).
    assert resp.headers["x-request-id"] == "req_relayhdr"
    assert len([1 for k, _ in resp.raw_headers if k == b"x-request-id"]) == 1
    assert resp.headers["openai-version"] == "2020-10-01"  # safe upstream header forwarded
    assert "transfer-encoding" not in {k.lower() for k in resp.headers}


# ── source_bearer_auth_env_var fail-closed (h) ──────────────────────────────────────


def _source_with_credentials(*credentials):
    """A minimal stand-in exposing the .id + .credentials the selector reads."""
    return SimpleNamespace(id="fake-source", credentials=tuple(credentials))


def test_source_bearer_auth_env_var_picks_single_secret():
    from forge.backend.sources import get_model_source, source_bearer_auth_env_var

    # The shipped Codex-Responses source declares exactly one secret bearer var.
    assert source_bearer_auth_env_var(get_model_source("codex-responses-local")) == "OPENAI_API_KEY"


def test_source_bearer_auth_env_var_fails_closed_on_zero():
    from forge.backend.sources import (
        ModelSourceCatalogError,
        source_bearer_auth_env_var,
    )

    only_connection = Credential(
        name="conn-only",
        env_vars=(EnvVar("X_BASE_URL", secret=False, connection_value=True),),
    )
    with pytest.raises(ModelSourceCatalogError, match="exactly one secret bearer"):
        source_bearer_auth_env_var(_source_with_credentials(only_connection))


def test_source_bearer_auth_env_var_fails_closed_on_multiple():
    from forge.backend.sources import (
        ModelSourceCatalogError,
        source_bearer_auth_env_var,
    )

    two_secrets = Credential(
        name="two-secrets",
        env_vars=(EnvVar("FIRST_API_KEY"), EnvVar("SECOND_API_KEY")),
    )
    with pytest.raises(ModelSourceCatalogError, match="found 2"):
        source_bearer_auth_env_var(_source_with_credentials(two_secrets))


# ── Route capability gate -> 501 (e) ────────────────────────────────────────────────


class _RawReq:
    """Minimal stand-in for a FastAPI Request the handler reads."""

    def __init__(self, *, method: str = "POST", body: bytes = b"", query: str = "") -> None:
        self.method = method
        self._body = body
        self.state = SimpleNamespace(request_id="req_gate")
        self.headers: dict[str, str] = {}
        self.url = SimpleNamespace(query=query)

    async def body(self) -> bytes:
        return self._body


def _proxy_cfg(*, wire_shape: str, backend: str):
    provider = SimpleNamespace(base_url="https://upstream.test")
    return SimpleNamespace(
        wire_shape=wire_shape,
        backend=backend,
        default_tier="sonnet",
        get_provider=lambda name=None: provider,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("wire_shape", "backend"),
    [
        ("anthropic_passthrough", "codex-responses-local"),  # right source, wrong wire shape
        ("openai_responses_passthrough", "litellm-gemini-test"),  # right shape, non-ingress source
        ("openai_responses_passthrough", "no-such-source"),  # right shape, unknown source
        ("openai_responses_passthrough", ""),  # right shape, empty source
    ],
)
async def test_responses_route_501_when_not_responses_capable(monkeypatch, proxy_runtime_ready, wire_shape, backend):
    server = proxy_runtime_ready
    monkeypatch.setattr(server.config, "proxy", _proxy_cfg(wire_shape=wire_shape, backend=backend))

    resp = await ri.handle_responses_passthrough(_RawReq(), method="POST", url_path="/v1/responses")

    assert resp.status_code == 501


@pytest.mark.asyncio
async def test_responses_route_forwards_when_capable(monkeypatch, proxy_runtime_ready):
    # wire_shape + responses_ingress source both satisfied -> the gate opens and the
    # handler reaches forward() (stubbed), proving the conjunction is the gate.
    server = proxy_runtime_ready
    monkeypatch.setattr(
        server.config, "proxy", _proxy_cfg(wire_shape="openai_responses_passthrough", backend="codex-responses-local")
    )
    monkeypatch.setattr(
        "forge.core.auth.template_secrets.resolve_env_or_credential",
        lambda var: "UPSTREAM-KEY" if var == "OPENAI_API_KEY" else None,
    )
    forwarded: dict = {}

    async def _fake_forward(**kwargs):
        forwarded.update(kwargs)
        from fastapi.responses import Response

        return Response(status_code=200, content=b"{}", media_type="application/json")

    monkeypatch.setattr("forge.proxy.responses_passthrough.forward", _fake_forward)

    req = _RawReq(method="POST", body=b'{"model":"m","input":"hi"}', query="x=1")
    resp = await ri.handle_responses_passthrough(req, method="POST", url_path="/v1/responses")

    assert resp.status_code == 200
    assert forwarded["method"] == "POST"
    assert forwarded["url_path"] == "/v1/responses"
    assert forwarded["api_key"] == "UPSTREAM-KEY"  # resolved via source_bearer_auth_env_var
    assert forwarded["body"] == {"model": "m", "input": "hi"}  # POST body parsed from raw bytes
    assert forwarded["query_string"] == "x=1"


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [b"[]", b'"oops"', b"123", b"null"])
async def test_responses_route_rejects_non_object_post_json(monkeypatch, proxy_runtime_ready, body):
    """Regression: valid-but-non-object JSON must not be transformed into no body."""
    server = proxy_runtime_ready
    monkeypatch.setattr(
        server.config, "proxy", _proxy_cfg(wire_shape="openai_responses_passthrough", backend="codex-responses-local")
    )
    monkeypatch.setattr("forge.core.auth.template_secrets.resolve_env_or_credential", lambda var: "UPSTREAM-KEY")

    async def _unexpected_forward(**kwargs):
        raise AssertionError("non-object POST JSON must fail before forwarding")

    monkeypatch.setattr("forge.proxy.responses_passthrough.forward", _unexpected_forward)

    resp = await ri.handle_responses_passthrough(
        _RawReq(method="POST", body=body), method="POST", url_path="/v1/responses"
    )

    assert resp.status_code == 400
    assert b"JSON object" in bytes(resp.body)


@pytest.mark.asyncio
async def test_responses_route_bodyless_get_never_reads_json(monkeypatch, proxy_runtime_ready):
    server = proxy_runtime_ready
    monkeypatch.setattr(
        server.config, "proxy", _proxy_cfg(wire_shape="openai_responses_passthrough", backend="codex-responses-local")
    )
    monkeypatch.setattr(
        "forge.core.auth.template_secrets.resolve_env_or_credential",
        lambda var: "UPSTREAM-KEY",
    )
    forwarded: dict = {}

    async def _fake_forward(**kwargs):
        forwarded.update(kwargs)
        from fastapi.responses import Response

        return Response(status_code=200, content=b"{}")

    monkeypatch.setattr("forge.proxy.responses_passthrough.forward", _fake_forward)

    # A GET request whose body() would error if read -- the handler must not touch it.
    class _NoBodyReq(_RawReq):
        async def body(self) -> bytes:
            raise AssertionError("bodyless GET must not read the request body")

    req = _NoBodyReq(method="GET")
    resp = await ri.handle_responses_passthrough(req, method="GET", url_path="/v1/responses/resp_1")

    assert resp.status_code == 200
    assert forwarded["body"] is None  # GET forwards no body


# ── GET / truth table (f) ───────────────────────────────────────────────────────────


def test_intercept_section_responses_passthrough_is_signature_safe_uninspectable():
    section = ri.build_intercept_capability_section(
        "openai_responses_passthrough", intercept_mode="inspect", audit_full_body=True
    )
    # Reasoning preserved byte-for-byte...
    assert section["thinking_blocks_preserved"] is True
    # ...but a byte-faithful passthrough can inspect/override/audit nothing, even
    # with intercept.mode=inspect and audit_full_body=True.
    assert section["can_inspect"] == {
        "system_prompt": False,
        "drift_detection": False,
        "override": False,
        "full_body_audit": False,
    }


def test_intercept_section_anthropic_passthrough_preserves_but_inspect_mode_off():
    section = ri.build_intercept_capability_section(
        "anthropic_passthrough", intercept_mode="passthrough", audit_full_body=False
    )
    assert section["thinking_blocks_preserved"] is True  # also a passthrough
    assert section["can_inspect"]["system_prompt"] is False  # passthrough mode -> no inspect


def test_intercept_section_translated_inspect_mode_can_inspect():
    # The non-passthrough shape with inspect mode CAN inspect -- proves the
    # responses-pt false-everywhere result is the wire shape, not a blanket off.
    section = ri.build_intercept_capability_section("openai_translated", intercept_mode="inspect", audit_full_body=True)
    assert section["thinking_blocks_preserved"] is False
    assert section["can_inspect"]["system_prompt"] is True
    assert section["can_inspect"]["drift_detection"] is True
    assert section["can_inspect"]["full_body_audit"] is True


@pytest.mark.parametrize(
    ("wire_shape", "source_id", "expected"),
    [
        ("openai_responses_passthrough", "codex-responses-local", True),  # both -> advertised
        ("openai_responses_passthrough", "litellm-gemini-test", False),  # capable shape, non-ingress source
        ("openai_responses_passthrough", "no-such", False),  # unknown source
        ("openai_responses_passthrough", "", False),  # empty source
        ("anthropic_passthrough", "codex-responses-local", False),  # wrong wire shape
    ],
)
def test_advertise_responses_ingress_matrix(wire_shape, source_id, expected):
    assert ri.advertise_responses_ingress(wire_shape, source_id) is expected


# ── Accounting gated to the generation endpoint (Issue 1) ───────────────────────────


@pytest.mark.asyncio
async def test_retrieve_with_usage_is_not_accounted(monkeypatch, proxy_runtime_ready):
    """Regression: GET /v1/responses/{id} echoes the original response's usage; the
    server must NOT account it (no on_complete) or it double-counts tokens."""
    server = proxy_runtime_ready
    monkeypatch.setattr(
        server.config, "proxy", _proxy_cfg(wire_shape="openai_responses_passthrough", backend="codex-responses-local")
    )
    monkeypatch.setattr("forge.core.auth.template_secrets.resolve_env_or_credential", lambda var: "K")
    accounted: list = []
    monkeypatch.setattr(server, "_calc_and_log_cost", lambda **kw: accounted.append(kw) or 0)

    captured: dict = {}

    async def _fake_forward(**kwargs):
        captured.update(kwargs)
        # If the server had (wrongly) wired accounting, invoking on_complete with the
        # retrieve's echoed usage would double-count. The fix passes on_complete=None.
        if kwargs.get("on_complete") is not None:
            kwargs["on_complete"]({"input_tokens": 50, "output_tokens": 20}, None, False, None)
        from fastapi.responses import Response

        return Response(status_code=200, content=b"{}")

    monkeypatch.setattr("forge.proxy.responses_passthrough.forward", _fake_forward)

    resp = await ri.handle_responses_passthrough(_RawReq(method="GET"), method="GET", url_path="/v1/responses/resp_abc")

    assert resp.status_code == 200
    assert captured["on_complete"] is None  # no accounting wired for a retrieve
    assert captured["provider_trace_ctx"] is None
    assert accounted == []  # cost/metrics never invoked


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "url_path", "should_account"),
    [
        ("POST", "/v1/responses", True),  # create = the billable generation
        ("GET", "/v1/responses/resp_1", False),  # retrieve
        ("DELETE", "/v1/responses/resp_1", False),  # delete
        ("POST", "/v1/responses/resp_1/cancel", False),  # cancel (POST, but not generation)
        ("POST", "/v1/responses/input_tokens", False),  # token-count, top-level non-{id}
    ],
)
async def test_accounting_only_on_generation_endpoint(
    monkeypatch, proxy_runtime_ready, method, url_path, should_account
):
    server = proxy_runtime_ready
    monkeypatch.setattr(
        server.config, "proxy", _proxy_cfg(wire_shape="openai_responses_passthrough", backend="codex-responses-local")
    )
    monkeypatch.setattr("forge.core.auth.template_secrets.resolve_env_or_credential", lambda var: "K")
    captured: dict = {}

    async def _fake_forward(**kwargs):
        captured.update(kwargs)
        from fastapi.responses import Response

        return Response(status_code=200, content=b"{}")

    monkeypatch.setattr("forge.proxy.responses_passthrough.forward", _fake_forward)

    body = b'{"model":"m","input":"hi"}' if method == "POST" else b""
    await ri.handle_responses_passthrough(_RawReq(method=method, body=body), method=method, url_path=url_path)

    assert (captured["on_complete"] is not None) is should_account
    assert (captured["provider_trace_ctx"] is not None) is should_account


# ── Terminal application status -> failed (Issue 2) ─────────────────────────────────


@pytest.mark.parametrize(
    ("status", "failed", "error_type"),
    [
        ("failed", True, "response_failed"),  # real generation failure on a 200
        ("incomplete", False, None),  # normal early stop (max tokens) -> billed success
        ("completed", False, None),
        (None, False, None),  # no terminal event seen -> fail-open
        ("weird", False, None),  # unknown -> not a failure
    ],
)
def test_failure_from_terminal_status(status, failed, error_type):
    assert rp._failure_from_terminal_status(status) == (failed, error_type)


def test_accumulator_tracks_terminal_status():
    acc = rp._ResponsesUsageAccumulator()
    acc.feed(b'data: {"type":"response.failed","response":{"usage":{"input_tokens":5,"output_tokens":0}}}\n\n')
    assert acc.terminal_status == "failed"
    assert acc.usage == {"input_tokens": 5, "output_tokens": 0}  # usage still captured


async def _drain(resp):
    return b"".join([c if isinstance(c, bytes) else c.encode() async for c in resp.body_iterator])


@pytest.mark.asyncio
async def test_streaming_response_failed_event_is_recorded_as_failure(monkeypatch):
    """Regression: a streamed HTTP 200 ending in response.failed must NOT be recorded
    as a success — transport ok, generation failed."""
    sse = (
        b'data: {"type":"response.output_text.delta","delta":"x"}\n\n',
        b'data: {"type":"response.failed","response":{"usage":{"input_tokens":5,"output_tokens":0},'
        b'"error":{"code":"server_error"}}}\n\n',
    )

    class _FailStream(_FakeStream):
        def __init__(self):
            super().__init__(chunks=sse, headers={"content-type": "text/event-stream"})

    monkeypatch.setattr(rp.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(_FakeAsyncClient, "stream_factory", staticmethod(_FailStream))
    seen: dict = {}

    resp = await rp.forward(
        method="POST",
        url_path="/v1/responses",
        body={"model": "m", "input": "x", "stream": True},
        query_string="",
        inbound_headers={},
        base_url="https://u.test",
        api_key="K",
        request_id="req_streamfail",
        on_complete=lambda u, c, f, e: seen.update(usage=u, failed=f, error_type=e),
    )
    await _drain(resp)  # _on_end fires only after the stream is fully consumed

    assert seen["failed"] is True
    assert seen["error_type"] == "response_failed"
    assert seen["usage"] == {"input_tokens": 5, "output_tokens": 0}


@pytest.mark.asyncio
async def test_streaming_response_incomplete_is_partial_success(monkeypatch):
    sse = (b'data: {"type":"response.incomplete","response":{"usage":{"input_tokens":5,"output_tokens":3}}}\n\n',)

    class _IncStream(_FakeStream):
        def __init__(self):
            super().__init__(chunks=sse, headers={"content-type": "text/event-stream"})

    monkeypatch.setattr(rp.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(_FakeAsyncClient, "stream_factory", staticmethod(_IncStream))
    seen: dict = {}

    resp = await rp.forward(
        method="POST",
        url_path="/v1/responses",
        body={"model": "m", "input": "x", "stream": True},
        query_string="",
        inbound_headers={},
        base_url="https://u.test",
        api_key="K",
        request_id="req_streaminc",
        on_complete=lambda u, c, f, e: seen.update(usage=u, failed=f, error_type=e),
    )
    await _drain(resp)

    # incomplete = early stop (e.g. max_output_tokens): tokens billed, not a failure.
    assert seen["failed"] is False
    assert seen["error_type"] is None
    assert seen["usage"] == {"input_tokens": 5, "output_tokens": 3}


@pytest.mark.asyncio
async def test_non_streaming_status_failed_is_recorded_as_failure(monkeypatch):
    """Regression: a non-streaming 200 whose body carries status=failed is a failure."""

    class _FailedBody(_FakeResponse):
        def __init__(self):
            super().__init__(
                content=b'{"status":"failed","usage":{"input_tokens":5,"output_tokens":0},"error":{"code":"x"}}',
                headers={"content-type": "application/json"},
            )

    monkeypatch.setattr(rp.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(_FakeAsyncClient, "response_factory", staticmethod(_FailedBody))
    seen: dict = {}

    resp = await rp.forward(
        method="POST",
        url_path="/v1/responses",
        body={"model": "m", "input": "x"},
        query_string="",
        inbound_headers={},
        base_url="https://u.test",
        api_key="K",
        request_id="req_nsfail",
        on_complete=lambda u, c, f, e: seen.update(failed=f, error_type=e),
    )

    assert resp.status_code == 200  # transport succeeded...
    assert seen["failed"] is True  # ...but the generation failed
    assert seen["error_type"] == "response_failed"


# ── Issue 3: warn-mode spend caps surface X-Spend-Warning on the Responses path ──────


def _cap_tracker(*, on_cap_hit: str):
    """Fake over-cap cost tracker, mirroring test_passthrough.py's _Tracker/_CapResult."""

    class _CapResult:
        exceeded = True
        cap_type = "daily"
        current_micros = 11_000_000
        limit_micros = 10_000_000

    class _Tracker:
        has_caps = True

        def __init__(self) -> None:
            self.on_cap_hit = on_cap_hit

        def check_cap(self):
            return _CapResult()

    return _Tracker()


@pytest.mark.asyncio
async def test_responses_warn_mode_cap_attaches_spend_warning(monkeypatch, proxy_runtime_ready):
    """Issue 3 regression: warn-mode caps forward the request AND surface the cap message
    in X-Spend-Warning (design.md). The bug forwarded silently with no header."""
    server = proxy_runtime_ready
    monkeypatch.setattr(
        server.config, "proxy", _proxy_cfg(wire_shape="openai_responses_passthrough", backend="codex-responses-local")
    )
    monkeypatch.setattr("forge.core.auth.template_secrets.resolve_env_or_credential", lambda var: "K")
    monkeypatch.setattr(server, "cost_tracker", _cap_tracker(on_cap_hit="warn"))
    forwarded: dict = {}

    async def _fake_forward(**kwargs):
        forwarded.update(kwargs)
        from fastapi.responses import Response

        # forward() merges extra_response_headers onto the relayed response; emulate that
        # here so the test proves the header actually reaches the client.
        headers = {"X-Request-ID": "req"}
        headers.update(kwargs.get("extra_response_headers") or {})
        return Response(status_code=200, content=b"{}", headers=headers)

    monkeypatch.setattr("forge.proxy.responses_passthrough.forward", _fake_forward)

    req = _RawReq(method="POST", body=b'{"model":"m","input":"hi"}')
    resp = await ri.handle_responses_passthrough(req, method="POST", url_path="/v1/responses")

    assert resp.status_code == 200  # warn mode forwards (does not reject)
    warning = forwarded["extra_response_headers"]["X-Spend-Warning"]
    assert "spend cap reached" in warning  # the cap message is passed to forward...
    assert resp.headers["X-Spend-Warning"] == warning  # ...and surfaces on the response


@pytest.mark.asyncio
async def test_responses_reject_mode_cap_returns_429_without_forwarding(monkeypatch, proxy_runtime_ready):
    """Issue 3 companion: reject-mode caps return 429 with X-Spend-Warning, never forward."""
    server = proxy_runtime_ready
    monkeypatch.setattr(
        server.config, "proxy", _proxy_cfg(wire_shape="openai_responses_passthrough", backend="codex-responses-local")
    )
    monkeypatch.setattr("forge.core.auth.template_secrets.resolve_env_or_credential", lambda var: "K")
    monkeypatch.setattr(server, "cost_tracker", _cap_tracker(on_cap_hit="reject"))

    async def _boom(**kwargs):
        raise AssertionError("forward must not run when the cap rejects")

    monkeypatch.setattr("forge.proxy.responses_passthrough.forward", _boom)

    req = _RawReq(method="POST", body=b'{"model":"m","input":"hi"}')
    resp = await ri.handle_responses_passthrough(req, method="POST", url_path="/v1/responses")

    assert resp.status_code == 429
    assert b"spend_cap_exceeded" in bytes(resp.body)
    assert resp.headers["X-Spend-Warning"]  # the cap message rides the 429 too


@pytest.mark.asyncio
async def test_forward_merges_extra_response_headers_non_streaming(monkeypatch):
    """Issue 3 unit: forward() overlays extra_response_headers onto the relayed
    non-streaming response without dropping the relayed ones."""
    monkeypatch.setattr(rp.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(_FakeAsyncClient, "response_factory", staticmethod(_FakeResponse))

    resp = await rp.forward(
        method="POST",
        url_path="/v1/responses",
        body={"model": "m", "input": "hi"},
        query_string="",
        inbound_headers={},
        base_url="https://u.test",
        api_key="K",
        request_id="req_extra",
        extra_response_headers={"X-Spend-Warning": "daily spend cap reached: ..."},
    )

    assert resp.headers["X-Spend-Warning"].startswith("daily spend cap reached")
    assert resp.headers["X-Request-ID"] == "req_extra"  # relayed header preserved alongside


@pytest.mark.asyncio
async def test_forward_merges_extra_response_headers_streaming(monkeypatch):
    """Issue 3 unit: the streaming StreamingResponse also carries extra_response_headers."""
    monkeypatch.setattr(rp.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(_FakeAsyncClient, "stream_factory", staticmethod(_FakeStream))

    resp = await rp.forward(
        method="POST",
        url_path="/v1/responses",
        body={"model": "m", "input": "hi", "stream": True},
        query_string="",
        inbound_headers={},
        base_url="https://u.test",
        api_key="K",
        request_id="req_extra_stream",
        extra_response_headers={"X-Spend-Warning": "monthly spend cap reached: ..."},
    )

    assert resp.headers["X-Spend-Warning"].startswith("monthly spend cap reached")
    assert resp.headers["Cache-Control"] == "no-cache"  # stream-specific header still set
    await _drain(resp)  # consume the generator so its teardown runs cleanly


# ── Issue 4: malformed upstream usage degrades instead of aborting the relay ─────────


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (5, 5),
        (0, 0),
        (5.0, 5),
        (5.9, 5),  # float truncates, matching the prior int() behavior
        ("7", 7),
        ("  7  ", 7),  # surrounding whitespace tolerated
        (None, None),  # absent -> unavailable
        ("bad", None),  # non-numeric string -> unavailable (was: ValueError)
        ("", None),
        (-1, None),  # negative is not a real token count
        (-2.0, None),
        (True, None),  # bool is not a token count even though it's an int subclass
        (False, None),
        (float("inf"), None),  # non-finite -> unavailable
        (float("nan"), None),
        ([], None),  # wrong type
        ({}, None),
    ],
)
def test_coerce_int_degrades_malformed_to_none(value, expected):
    assert rp._coerce_int(value) == expected


def test_normalize_usage_degrades_malformed_field_without_raising():
    # A single bad field must degrade to omitted (unavailable), never raise.
    usage = {"input_tokens": "bad", "output_tokens": 7, "input_tokens_details": {"cached_tokens": "x"}}
    assert rp._normalize_usage(usage) == {"output_tokens": 7}


@pytest.mark.asyncio
async def test_forward_non_streaming_malformed_usage_degrades_not_aborts(monkeypatch):
    """Issue 4 regression: a 200 body with a non-numeric token field must NOT raise
    (which would abort the otherwise-successful response); usage degrades to unavailable."""

    class _MalformedUsage(_FakeResponse):
        def __init__(self):
            super().__init__(content=b'{"id":"r","usage":{"input_tokens":"bad","output_tokens":7}}')

    monkeypatch.setattr(rp.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(_FakeAsyncClient, "response_factory", staticmethod(_MalformedUsage))
    seen: dict = {}

    resp = await rp.forward(
        method="POST",
        url_path="/v1/responses",
        body={"model": "m", "input": "hi"},
        query_string="",
        inbound_headers={},
        base_url="https://u.test",
        api_key="K",
        request_id="req_badusage",
        on_complete=lambda u, c, f, e: seen.update(usage=u, failed=f),
    )

    assert resp.status_code == 200  # the successful response is preserved...
    assert seen["usage"] == {"output_tokens": 7}  # ...the malformed input_tokens degrades away
    assert seen["failed"] is False


@pytest.mark.asyncio
async def test_forward_streaming_malformed_usage_does_not_corrupt_stream(monkeypatch):
    """Issue 4 regression: a response.completed event with a non-numeric token field must
    not raise into the relay -- bytes still flow byte-faithfully, usage degrades."""
    sse = (
        b'data: {"type":"response.output_text.delta","delta":"hi"}\n\n',
        b'data: {"type":"response.completed","response":{"usage":{"input_tokens":"bad","output_tokens":9}}}\n\n',
    )

    class _BadStream(_FakeStream):
        def __init__(self):
            super().__init__(chunks=sse, headers={"content-type": "text/event-stream"})

    monkeypatch.setattr(rp.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(_FakeAsyncClient, "stream_factory", staticmethod(_BadStream))
    seen: dict = {}

    resp = await rp.forward(
        method="POST",
        url_path="/v1/responses",
        body={"model": "m", "input": "hi", "stream": True},
        query_string="",
        inbound_headers={},
        base_url="https://u.test",
        api_key="K",
        request_id="req_badstream",
        on_complete=lambda u, c, f, e: seen.update(usage=u, failed=f),
    )
    streamed = await _drain(resp)

    assert streamed == b"".join(sse)  # byte-faithful relay survives the malformed usage
    assert seen["usage"] == {"output_tokens": 9}  # malformed input_tokens degraded
    assert seen["failed"] is False


# ── Issue 5: non-streaming generations also write a provider trace ───────────────────


_TRACE_CTX = {
    "backend_id": "codex-responses-local",
    "proxy_id": "p1",
    "mapped_model": "gpt-5.5-codex",
    "request_id": "req_trace",
    "forge_run_id": None,
    "forge_root_run_id": None,
    "provider_session_id": None,
    "provider_command": None,
    "downstream_event_id": None,
}


@pytest.mark.asyncio
async def test_forward_non_streaming_records_provider_trace(monkeypatch):
    """Issue 5 regression: a non-streaming generation records a provider trace with
    request_mode='non_streaming'. Before the fix, only the streaming path traced."""
    monkeypatch.setattr(rp.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(_FakeAsyncClient, "response_factory", staticmethod(_FakeResponse))
    traces: list = []
    monkeypatch.setattr(rp, "record_provider_trace", lambda **kw: traces.append(kw))

    await rp.forward(
        method="POST",
        url_path="/v1/responses",
        body={"model": "m", "input": "hi"},
        query_string="",
        inbound_headers={},
        base_url="https://u.test",
        api_key="K",
        request_id="req_trace",
        on_complete=lambda u, c, f, e: None,
        provider_trace_ctx=_TRACE_CTX,
    )

    assert len(traces) == 1
    assert traces[0]["request_mode"] == "non_streaming"
    assert traces[0]["final_usage_seen"] is True  # the _FakeResponse body carries usage
    assert traces[0]["proxy_id"] == "p1"  # ctx fields forwarded verbatim


@pytest.mark.asyncio
async def test_forward_non_streaming_no_trace_without_ctx(monkeypatch):
    """A non-generation relay (no provider_trace_ctx) records no trace and skips body parse."""
    monkeypatch.setattr(rp.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(_FakeAsyncClient, "response_factory", staticmethod(_FakeResponse))
    traces: list = []
    monkeypatch.setattr(rp, "record_provider_trace", lambda **kw: traces.append(kw))

    await rp.forward(
        method="GET",
        url_path="/v1/responses/resp_1",
        body=None,
        query_string="",
        inbound_headers={},
        base_url="https://u.test",
        api_key="K",
        request_id="req_notrace",
    )

    assert traces == []  # no ctx -> no trace


@pytest.mark.asyncio
async def test_forward_non_streaming_trace_final_usage_false_when_body_lacks_usage(monkeypatch):
    """final_usage_seen is honest: a non-streaming body with no usage records it False."""

    class _NoUsage(_FakeResponse):
        def __init__(self):
            super().__init__(content=b'{"id":"r"}')

    monkeypatch.setattr(rp.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(_FakeAsyncClient, "response_factory", staticmethod(_NoUsage))
    traces: list = []
    monkeypatch.setattr(rp, "record_provider_trace", lambda **kw: traces.append(kw))

    await rp.forward(
        method="POST",
        url_path="/v1/responses",
        body={"model": "m", "input": "hi"},
        query_string="",
        inbound_headers={},
        base_url="https://u.test",
        api_key="K",
        request_id="req_nousagetrace",
        on_complete=lambda u, c, f, e: None,
        provider_trace_ctx=_TRACE_CTX,
    )

    assert len(traces) == 1
    assert traces[0]["final_usage_seen"] is False  # no usage in body -> honestly unavailable


@pytest.mark.asyncio
async def test_forward_streaming_still_records_streaming_trace_mode(monkeypatch):
    """The streaming path still records request_mode='streaming' after parameterization."""
    monkeypatch.setattr(rp.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(_FakeAsyncClient, "stream_factory", staticmethod(_FakeStream))
    traces: list = []
    monkeypatch.setattr(rp, "record_provider_trace", lambda **kw: traces.append(kw))

    resp = await rp.forward(
        method="POST",
        url_path="/v1/responses",
        body={"model": "m", "input": "hi", "stream": True},
        query_string="",
        inbound_headers={},
        base_url="https://u.test",
        api_key="K",
        request_id="req_streamtrace",
        on_complete=lambda u, c, f, e: None,
        provider_trace_ctx=_TRACE_CTX,
    )
    await _drain(resp)  # the trace fires in the relay's finally, after full consumption

    assert len(traces) == 1
    assert traces[0]["request_mode"] == "streaming"


# ── Issue 29 (CWE-209): catalog errors must not leak exception text to the client ────


@pytest.mark.asyncio
async def test_responses_catalog_error_does_not_leak_exception_text(monkeypatch, caplog, proxy_runtime_ready):
    """Code-scanning #29 (py/stack-trace-exposure): a bearer-secret catalog error must NOT
    surface its message (source id, env var names) to the Codex client. The client gets a
    generic configuration error; the detail is logged server-side for the operator."""
    server = proxy_runtime_ready
    monkeypatch.setattr(
        server.config, "proxy", _proxy_cfg(wire_shape="openai_responses_passthrough", backend="codex-responses-local")
    )
    secret = "source 'codex-responses-local' declares 2 secret bearer vars: FOO_KEY, BAR_KEY"

    def _raise(_source):
        raise ValueError(secret)

    # The handler imports source_bearer_auth_env_var from forge.backend.sources at call time.
    monkeypatch.setattr("forge.backend.sources.source_bearer_auth_env_var", _raise)

    req = _RawReq(method="POST", body=b'{"model":"m","input":"hi"}')
    with caplog.at_level(logging.WARNING):
        resp = await ri.handle_responses_passthrough(req, method="POST", url_path="/v1/responses")

    assert resp.status_code == 500
    leaked = bytes(resp.body)
    assert secret.encode() not in leaked  # the catalog message is not exposed...
    assert b"FOO_KEY" not in leaked and b"BAR_KEY" not in leaked  # ...nor any env var name
    assert b"misconfigured" in leaked  # a generic, non-leaking message is returned instead
    assert secret in caplog.text  # ...while the full detail stays available in the server log
