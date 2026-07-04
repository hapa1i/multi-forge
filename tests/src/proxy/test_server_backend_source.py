"""Tests for proxy backend attribution (unified_backend).

``_backend_source_id`` reads the user-owned ``proxy.yaml`` ``backend``. A known
catalog id is returned silently; an unrecognized one is still returned
(best-effort, not rejected -- proxy.yaml is a system boundary) but warns ONCE so
the silent telemetry-attribution gap is visible.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from forge.proxy import server

_UNKNOWN_MARKER = "not a known backend instance"


def test_known_backend_returns_silently(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.setattr(server.config, "proxy", SimpleNamespace(backend="openrouter"))
    server._warned_unknown_backend_sources.clear()
    with caplog.at_level(logging.WARNING, logger=server.logger.name):
        assert server._backend_source_id() == "openrouter"
    assert not [r for r in caplog.records if _UNKNOWN_MARKER in r.getMessage()]


def test_empty_backend_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server.config, "proxy", SimpleNamespace(backend=""))
    assert server._backend_source_id() is None


def test_unknown_backend_warns_once_and_still_returns(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(server.config, "proxy", SimpleNamespace(backend="not-a-real-backend"))
    server._warned_unknown_backend_sources.discard("not-a-real-backend")
    with caplog.at_level(logging.WARNING, logger=server.logger.name):
        # Returns the raw value both times (degrade, do not reject)...
        assert server._backend_source_id() == "not-a-real-backend"
        assert server._backend_source_id() == "not-a-real-backend"
    # ...but warns exactly once for that value (warn-once guard).
    warnings = [
        r for r in caplog.records if _UNKNOWN_MARKER in r.getMessage() and "not-a-real-backend" in r.getMessage()
    ]
    assert len(warnings) == 1
