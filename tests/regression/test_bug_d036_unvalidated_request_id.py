"""Regression: untrusted client request IDs must not become correlation identifiers."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from starlette.requests import Request
from starlette.responses import Response

from forge.proxy import server

pytestmark = pytest.mark.regression

_GENERATED_REQUEST_ID_RE = re.compile(r"^req_[0-9a-f]{12}$")


@dataclass(frozen=True)
class _MiddlewareResult:
    state_request_id: str
    response_request_id: str
    downstream_request_ids: tuple[str, ...]
    downstream_event_keys: tuple[str, ...]
    log_messages: tuple[str, ...]


def _request_with_id(value: bytes) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/v1/models",
            "headers": [(b"x-request-id", value)],
            "query_string": b"",
            "state": {},
        }
    )


async def _run_middleware(
    value: bytes,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> _MiddlewareResult:
    downstream_event_keys: list[str] = []

    def _mint_event_id(*, event_key: str | None = None) -> str:
        assert event_key is not None
        downstream_event_keys.append(event_key)
        return "ds_d036"

    monkeypatch.setattr(server, "mint_downstream_event_id", _mint_event_id)
    caplog.set_level(logging.DEBUG, logger=server.logger.name)
    request = _request_with_id(value)
    observed_request_ids: list[str] = []
    observed_header_request_ids: list[str] = []

    async def _call_next(raw_request: Request) -> Response:
        downstream_request = Request(raw_request.scope)
        observed_request_ids.append(raw_request.state.request_id)
        observed_header_request_ids.extend(downstream_request.headers.getlist("X-Request-ID"))
        return Response(status_code=200)

    response = await server.log_requests_middleware(request, _call_next)
    return _MiddlewareResult(
        state_request_id=observed_request_ids[0],
        response_request_id=response.headers["X-Request-ID"],
        downstream_request_ids=tuple(observed_header_request_ids),
        downstream_event_keys=tuple(downstream_event_keys),
        log_messages=tuple(record.getMessage() for record in caplog.records),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw_value",
    [
        pytest.param(b"d036 whitespace", id="whitespace"),
        pytest.param(b"d036/../path", id="path-syntax"),
        pytest.param(b"d036\ncontrol", id="control"),
        pytest.param(b"d036:\xff", id="non-token-bytes"),
        pytest.param(b"x" * 129, id="overlong"),
    ],
)
async def test_invalid_request_id_uses_generated_value_everywhere(
    raw_value: bytes,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    raw_text = raw_value.decode("latin-1")
    result = await _run_middleware(raw_value, monkeypatch, caplog)

    assert _GENERATED_REQUEST_ID_RE.fullmatch(result.state_request_id)
    assert result.response_request_id == result.state_request_id
    assert result.downstream_request_ids == (result.state_request_id,)
    assert all(raw_text not in event_key for event_key in result.downstream_event_keys)
    assert all(raw_text not in message for message in result.log_messages)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "request_id",
    [
        "550e8400-e29b-41d4-a716-446655440000",
        "ABCDEF0123456789",
        "req_client.42-alpha",
        "trace.id_with-punctuation",
    ],
)
async def test_conventional_request_id_is_preserved(
    request_id: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    result = await _run_middleware(request_id.encode("ascii"), monkeypatch, caplog)

    assert result.state_request_id == request_id
    assert result.response_request_id == request_id
    assert result.downstream_request_ids == (request_id,)
    assert any(request_id in event_key for event_key in result.downstream_event_keys)
    assert any(request_id in message for message in result.log_messages)


@pytest.mark.asyncio
async def test_invalid_request_id_cannot_reach_full_body_audit(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from forge.proxy import audit_logger

    raw_request_id = "d036/audit-canary"
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    monkeypatch.setattr(server, "PROXY_ID", "d036")
    monkeypatch.setattr(server, "_backend_instance_id", lambda: None)
    monkeypatch.setattr(
        server.config,
        "proxy",
        SimpleNamespace(
            wire_shape="openai_translated",
            active_template="d036-test",
            preferred_provider="litellm",
            intercept=SimpleNamespace(mode="inspect"),
            audit=SimpleNamespace(audit_full_body=True, effective_redact_headers=lambda: set()),
        ),
    )
    monkeypatch.setattr(audit_logger, "_drift_state", {})
    request = _request_with_id(raw_request_id.encode("ascii"))

    async def _call_next(raw_request: Request) -> Response:
        downstream_request = Request(raw_request.scope)
        await server._observe_request_side(
            {"messages": []},
            downstream_request.state.request_id,
            headers=dict(downstream_request.headers),
        )
        return Response(status_code=200)

    response = await server.log_requests_middleware(request, _call_next)
    generated_request_id = response.headers["X-Request-ID"]
    records = [record for record in audit_logger.read_audit_logs(record_type="request") if record.get("full_body")]

    assert _GENERATED_REQUEST_ID_RE.fullmatch(generated_request_id)
    assert len(records) == 1
    assert records[0]["request_id"] == generated_request_id
    assert records[0]["request_headers"]["x-request-id"] == generated_request_id
    assert raw_request_id not in str(records[0])
