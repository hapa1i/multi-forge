"""Tests for client request-ID validation at the proxy ingress boundary."""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest
from starlette.requests import Request
from starlette.responses import Response

from forge.core.wire_shapes import ANTHROPIC_PASSTHROUGH, DEFAULT_WIRE_SHAPE
from forge.proxy import server
from forge.proxy.request_id import REQUEST_ID_MAX_LENGTH, is_valid_request_id


@pytest.mark.parametrize(
    "value",
    [
        "550e8400-e29b-41d4-a716-446655440000",
        "ABCDEF0123456789",
        "req_client.42-alpha",
        "trace.id_with-punctuation",
        "x" * REQUEST_ID_MAX_LENGTH,
    ],
)
def test_request_id_validator_accepts_conventional_tokens(value: str) -> None:
    assert is_valid_request_id(value)


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "has whitespace",
        "path/segment",
        "line\nbreak",
        "colon:value",
        "non-ascii-ÿ",
        "x" * (REQUEST_ID_MAX_LENGTH + 1),
    ],
)
def test_request_id_validator_rejects_non_tokens(value: str | None) -> None:
    assert not is_valid_request_id(value)


def _request(path: str, method: str, request_id: str | tuple[str, ...] | None) -> Request:
    if request_id is None:
        headers = []
    else:
        values = (request_id,) if isinstance(request_id, str) else request_id
        headers = [(b"x-request-id", value.encode("latin-1")) for value in values]
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "headers": headers,
            "query_string": b"",
            "state": {},
        }
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "method", "request_id", "expected_prefix"),
    [
        ("/v1/messages", "POST", "invalid/id", "req_"),
        ("/v1/messages/count_tokens", "POST", "invalid id", "tok_"),
        ("/", "GET", None, "inf_"),
    ],
)
async def test_middleware_mints_endpoint_specific_id_for_invalid_or_absent_header(
    path: str,
    method: str,
    request_id: str | None,
    expected_prefix: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server, "_ensure_runtime_state", lambda: None)
    monkeypatch.setattr(server.config, "proxy", SimpleNamespace(wire_shape=DEFAULT_WIRE_SHAPE))
    request = _request(path, method, request_id)
    observed: dict[str, str] = {}

    async def _call_next(raw_request: Request) -> Response:
        observed["request_id"] = raw_request.state.request_id
        return Response(status_code=200)

    response = await server.log_requests_middleware(request, _call_next)
    generated = observed["request_id"]

    assert re.fullmatch(rf"{expected_prefix}[0-9a-f]{{12}}", generated)
    assert response.headers["X-Request-ID"] == generated


@pytest.mark.asyncio
async def test_middleware_preserves_valid_client_request_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_id = "Client.Trace_01-A"
    request = _request("/v1/models", "GET", request_id)
    observed: dict[str, str] = {}
    event_keys: list[str] = []

    def _mint_event_id(*, event_key: str | None = None) -> str:
        assert event_key is not None
        event_keys.append(event_key)
        return "ds_request_id"

    async def _call_next(raw_request: Request) -> Response:
        observed["request_id"] = raw_request.state.request_id
        return Response(status_code=200)

    monkeypatch.setattr(server, "mint_downstream_event_id", _mint_event_id)
    response = await server.log_requests_middleware(request, _call_next)

    assert observed["request_id"] == request_id
    assert response.headers["X-Request-ID"] == request_id
    assert any(request_id in event_key for event_key in event_keys)


@pytest.mark.asyncio
async def test_middleware_replaces_ambiguous_duplicate_request_ids() -> None:
    request = _request("/v1/models", "GET", ("valid-client-id", "second-client-id"))
    request.scope["headers"] = tuple(request.scope["headers"])
    observed: dict[str, object] = {}

    async def _call_next(raw_request: Request) -> Response:
        downstream_request = Request(raw_request.scope)
        observed["request_id"] = raw_request.state.request_id
        observed["header_values"] = downstream_request.headers.getlist("X-Request-ID")
        return Response(status_code=200)

    response = await server.log_requests_middleware(request, _call_next)
    generated = observed["request_id"]

    assert isinstance(generated, str)
    assert re.fullmatch(r"req_[0-9a-f]{12}", generated)
    assert observed["header_values"] == [generated]
    assert response.headers["X-Request-ID"] == generated


@pytest.mark.asyncio
async def test_passthrough_receives_the_validated_request_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server, "_ensure_runtime_state", lambda: None)
    monkeypatch.setattr(server.config, "proxy", SimpleNamespace(wire_shape=ANTHROPIC_PASSTHROUGH))
    observed: dict[str, str] = {}

    async def _passthrough(raw_request: Request, request_id: str, *, path: str) -> Response:
        observed["state_request_id"] = raw_request.state.request_id
        observed["argument_request_id"] = request_id
        observed["path"] = path
        return Response(status_code=200)

    async def _unexpected_call_next(_raw_request: Request) -> Response:
        raise AssertionError("passthrough request reached translated routing")

    monkeypatch.setattr(server, "_handle_anthropic_passthrough", _passthrough)
    response = await server.log_requests_middleware(
        _request("/v1/messages", "POST", "invalid/request"),
        _unexpected_call_next,
    )

    generated = observed["state_request_id"]
    assert re.fullmatch(r"req_[0-9a-f]{12}", generated)
    assert observed == {
        "state_request_id": generated,
        "argument_request_id": generated,
        "path": "/v1/messages",
    }
    assert response.headers["X-Request-ID"] == generated
