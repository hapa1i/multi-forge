"""Tests for the proxy's provider-trace correlation headers (openrouter_observability Phase 1).

The middleware reads + VALIDATES the inbound ``X-Forge-Session``/``X-Forge-Command`` headers
a proxy-routed subprocess stamps, stores the sanitized values on ``request.state``, and never
forwards them upstream (the passthrough allowlist excludes them structurally).
"""

from __future__ import annotations

from types import SimpleNamespace

from starlette.requests import Request
from starlette.responses import Response
from starlette.testclient import TestClient

from forge.core.run_id import FORGE_COMMAND_HEADER, FORGE_SESSION_HEADER
from forge.proxy import passthrough
from forge.proxy.server import (
    _forge_session_command,
    _valid_command_header,
    _valid_session_header,
)

VALID_SESSION = "forge_sess_7e81a1bb765d_supervisor"
VALID_COMMAND = "supervisor"


# --- Validators (drop spoofed/over-long inbound values) ---


def test_valid_session_header_accepts_well_formed() -> None:
    assert _valid_session_header(VALID_SESSION) == VALID_SESSION
    assert _valid_session_header("forge_run_7e81a1bb765d") == "forge_run_7e81a1bb765d"


def test_valid_session_header_rejects_spoofed() -> None:
    assert _valid_session_header(None) is None
    assert _valid_session_header("not-a-session") is None
    assert _valid_session_header("forge_sess_NOPE") is None
    assert _valid_session_header("forge_sess_7e81a1bb765d\nX-Evil: y") is None
    assert _valid_session_header("forge_sess_7e81a1bb765d_" + "a" * 65) is None


def test_valid_command_header_accepts_clean() -> None:
    assert _valid_command_header("supervisor") == "supervisor"
    assert _valid_command_header("memory_writer") == "memory_writer"


def test_valid_command_header_rejects_spoofed() -> None:
    assert _valid_command_header(None) is None
    assert _valid_command_header("memory writer") is None  # space (not canonical)
    assert _valid_command_header("role\nX-Evil: y") is None  # injection
    assert _valid_command_header("a" * 65) is None  # over the cap


# --- Getter ---


def _request_with_state(**state: object) -> Request:
    return Request({"type": "http", "headers": [], "state": dict(state)})


def test_forge_session_command_getter_reads_state() -> None:
    req = _request_with_state(forge_session=VALID_SESSION, forge_command="review")
    assert _forge_session_command(req) == (VALID_SESSION, "review")


def test_forge_session_command_getter_defaults_none() -> None:
    req = _request_with_state()
    assert _forge_session_command(req) == (None, None)


# --- Middleware integration: state is set before the passthrough branch ---


def _capture_state_via_passthrough(monkeypatch, headers: dict[str, str]) -> SimpleNamespace:
    """Send a request through the middleware and capture request.state at the passthrough seam."""
    import forge.proxy.server as server

    monkeypatch.setattr(server, "_ensure_runtime_state", lambda: None)
    monkeypatch.setattr(server.config, "proxy", SimpleNamespace(wire_shape="anthropic_passthrough"))

    captured: dict[str, object] = {}

    async def _spy(request, *args, **kwargs):
        captured["session"] = getattr(request.state, "forge_session", "MISSING")
        captured["command"] = getattr(request.state, "forge_command", "MISSING")
        return Response(status_code=200)

    monkeypatch.setattr(server, "_handle_anthropic_passthrough", _spy)

    client = TestClient(server.app, raise_server_exceptions=False)
    client.post("/v1/messages", json={"model": "x", "max_tokens": 1, "messages": []}, headers=headers)
    return SimpleNamespace(**captured)


def test_middleware_stores_valid_headers(monkeypatch) -> None:
    state = _capture_state_via_passthrough(
        monkeypatch,
        {FORGE_SESSION_HEADER: VALID_SESSION, FORGE_COMMAND_HEADER: VALID_COMMAND},
    )
    assert state.session == VALID_SESSION
    assert state.command == VALID_COMMAND


def test_middleware_drops_spoofed_headers(monkeypatch) -> None:
    state = _capture_state_via_passthrough(
        monkeypatch,
        {FORGE_SESSION_HEADER: "forge_sess_NOPE", FORGE_COMMAND_HEADER: "a" * 100},
    )
    assert state.session is None
    assert state.command is None


def test_middleware_none_when_headers_absent(monkeypatch) -> None:
    state = _capture_state_via_passthrough(monkeypatch, {})
    assert state.session is None
    assert state.command is None


# --- Never forwarded upstream (the passthrough allowlist excludes them) ---


def test_forge_headers_not_forwarded_upstream() -> None:
    inbound = {
        "x-forge-session": VALID_SESSION,
        "x-forge-command": VALID_COMMAND,
        "x-forge-run-id": "run_7e81a1bb765d",
        "anthropic-version": "2023-06-01",
    }
    headers = passthrough.build_upstream_headers(inbound, "UPSTREAM-KEY")
    assert "x-forge-session" not in {k.lower() for k in headers}
    assert "x-forge-command" not in {k.lower() for k in headers}
    assert "x-forge-run-id" not in {k.lower() for k in headers}
    assert headers["anthropic-version"] == "2023-06-01"  # allowlisted header still forwarded
