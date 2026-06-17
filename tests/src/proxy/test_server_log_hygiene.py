"""Slice 1 (proxy_log_hygiene): successful, fast poll completions log at DEBUG, not INFO.

The status line polls GET / frequently; an INFO line per poll turned the proxy log into an
access-log stream. The middleware now demotes a successful, fast non-verbose completion to
DEBUG and keeps INFO only for failures (status >= 400) or slow responses (> _SLOW_POLL_LOG_S).

The middleware is exercised directly with a stub ``call_next``; the fast/slow boundary is
forced by patching ``_SLOW_POLL_LOG_S`` (no clock mocking).
"""

from __future__ import annotations

import asyncio
import logging

from starlette.requests import Request
from starlette.responses import Response

import forge.proxy.server as server

_LOGGER_NAME = "forge.proxy.server"


def _make_request(path: str = "/", method: str = "GET") -> Request:
    return Request({"type": "http", "method": method, "path": path, "headers": [], "query_string": b"", "state": {}})


def _run_middleware(status_code: int, *, path: str = "/", method: str = "GET") -> None:
    request = _make_request(path=path, method=method)

    async def call_next(_req: Request) -> Response:
        return Response(status_code=status_code)

    asyncio.run(server.log_requests_middleware(request, call_next))


def _completed_records(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if "Completed in" in r.getMessage()]


def test_fast_successful_poll_logs_debug(monkeypatch, caplog) -> None:
    monkeypatch.setattr(server, "_SLOW_POLL_LOG_S", 1e9)  # nothing counts as slow
    caplog.set_level(logging.DEBUG, logger=_LOGGER_NAME)

    _run_middleware(200)

    completed = _completed_records(caplog)
    assert len(completed) == 1
    assert completed[0].levelno == logging.DEBUG


def test_repeated_fast_polls_emit_no_info(monkeypatch, caplog) -> None:
    monkeypatch.setattr(server, "_SLOW_POLL_LOG_S", 1e9)
    caplog.set_level(logging.DEBUG, logger=_LOGGER_NAME)

    for _ in range(5):
        _run_middleware(200)

    infos = [r for r in _completed_records(caplog) if r.levelno == logging.INFO]
    assert infos == []


def test_slow_poll_logs_info(monkeypatch, caplog) -> None:
    monkeypatch.setattr(server, "_SLOW_POLL_LOG_S", -1.0)  # any elapsed is "slow"
    caplog.set_level(logging.DEBUG, logger=_LOGGER_NAME)

    _run_middleware(200)

    infos = [r for r in _completed_records(caplog) if r.levelno == logging.INFO]
    assert len(infos) == 1


def test_error_status_logs_info_even_when_fast(monkeypatch, caplog) -> None:
    monkeypatch.setattr(server, "_SLOW_POLL_LOG_S", 1e9)  # fast, but a failure
    caplog.set_level(logging.DEBUG, logger=_LOGGER_NAME)

    _run_middleware(503)

    infos = [r for r in _completed_records(caplog) if r.levelno == logging.INFO]
    assert len(infos) == 1
    assert "(503)" in infos[0].getMessage()


def test_verbose_endpoint_unaffected(monkeypatch, caplog) -> None:
    """A detailed-logging endpoint keeps its DEBUG 'Middleware:' line and no 'Completed' line."""
    monkeypatch.setattr(server, "_SLOW_POLL_LOG_S", 1e9)
    caplog.set_level(logging.DEBUG, logger=_LOGGER_NAME)

    _run_middleware(200, path="/v1/messages")

    assert _completed_records(caplog) == []
    assert any("Middleware:" in r.getMessage() for r in caplog.records)
