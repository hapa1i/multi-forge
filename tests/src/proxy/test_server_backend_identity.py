"""Tests for proxy backend-instance attribution (unified_backend).

``_backend_instance_id`` reads the user-owned ``proxy.yaml`` ``backend``. A known
backend instance id is returned silently; an unrecognized one is still returned
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
    server._warned_unknown_backend_instances.clear()
    with caplog.at_level(logging.WARNING, logger=server.logger.name):
        assert server._backend_instance_id() == "openrouter"
    assert not [r for r in caplog.records if _UNKNOWN_MARKER in r.getMessage()]


def test_local_backend_uses_logical_instance_not_managed_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server.config, "proxy", SimpleNamespace(backend="litellm-gemini-local"))

    assert server._backend_instance_id() == "litellm-gemini-local"
    assert server._backend_instance_id() != "litellm-4000"


def test_empty_backend_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server.config, "proxy", SimpleNamespace(backend=""))
    assert server._backend_instance_id() is None


def test_unknown_backend_warns_once_and_still_returns(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(server.config, "proxy", SimpleNamespace(backend="not-a-real-backend"))
    server._warned_unknown_backend_instances.discard("not-a-real-backend")
    with caplog.at_level(logging.WARNING, logger=server.logger.name):
        # Returns the raw value both times (degrade, do not reject)...
        assert server._backend_instance_id() == "not-a-real-backend"
        assert server._backend_instance_id() == "not-a-real-backend"
    # ...but warns exactly once for that value (warn-once guard).
    warnings = [
        r for r in caplog.records if _UNKNOWN_MARKER in r.getMessage() and "not-a-real-backend" in r.getMessage()
    ]
    assert len(warnings) == 1


def test_inspect_route_uses_backend_not_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        server.config,
        "proxy",
        SimpleNamespace(
            active_template="openrouter-openai",
            preferred_provider="openrouter",
            backend="openrouter",
            wire_shape="openai_translated",
        ),
    )

    route = server._inspect_route()

    assert route == {
        "template": "openrouter-openai",
        "provider": "openrouter",
        "backend": "openrouter",
        "wire_shape": "openai_translated",
    }
    assert "source" not in route
