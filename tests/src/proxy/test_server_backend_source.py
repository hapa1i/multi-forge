"""Tests for proxy backend-source attribution (unified_backend).

``_backend_source_id`` reads the user-owned ``proxy.yaml`` ``source``. A known catalog
id is returned silently; an unrecognized one is still returned (best-effort, not
rejected -- proxy.yaml is a system boundary) but warns ONCE so the silent
telemetry-attribution gap is visible.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from forge.proxy import server

_UNKNOWN_MARKER = "not a known backend source"


def test_known_source_returns_silently(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.setattr(server.config, "proxy", SimpleNamespace(source="openrouter"))
    server._warned_unknown_backend_sources.clear()
    with caplog.at_level(logging.WARNING, logger=server.logger.name):
        assert server._backend_source_id() == "openrouter"
    assert not [r for r in caplog.records if _UNKNOWN_MARKER in r.getMessage()]


def test_empty_source_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server.config, "proxy", SimpleNamespace(source=""))
    assert server._backend_source_id() is None


def test_unknown_source_warns_once_and_still_returns(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(server.config, "proxy", SimpleNamespace(source="not-a-real-source"))
    server._warned_unknown_backend_sources.discard("not-a-real-source")
    with caplog.at_level(logging.WARNING, logger=server.logger.name):
        # Returns the raw value both times (degrade, do not reject)...
        assert server._backend_source_id() == "not-a-real-source"
        assert server._backend_source_id() == "not-a-real-source"
    # ...but warns exactly once for that value (warn-once guard).
    warnings = [
        r for r in caplog.records if _UNKNOWN_MARKER in r.getMessage() and "not-a-real-source" in r.getMessage()
    ]
    assert len(warnings) == 1
