"""Regression: a fresh proxy ``GET /`` omitted spend-cap proximity.

Bug: ``root()`` (the documented "source of runtime truth", polled by the status
line before any request flows) read the module-global ``cost_tracker`` directly.
On a freshly-imported uvicorn app that global is ``None`` and ``config`` holds
import-time defaults until the first POST runs ``_ensure_runtime_state()``. So a
``GET /`` that landed before any POST reported the default template/tiers and
omitted ``metrics.costs.caps`` entirely — the ``spend_cap`` status-line segment
rendered nothing even though caps were configured. After a POST warmed the
module it worked, making the failure load-order-dependent.

Root cause / fix: ``src/forge/proxy/server.py`` — ``root()`` now calls the
idempotent ``_ensure_runtime_state()`` at the top of its body (the POST handlers
already did), so the very first GET initializes config + the caps tracker.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from forge.proxy.metrics import proxy_metrics

pytestmark = pytest.mark.regression


def test_fresh_get_root_initializes_caps_before_any_post(monkeypatch):
    import forge.proxy.server as server
    from forge.config.schema import CostCaps, CostConfig
    from forge.proxy.server import app

    proxy_metrics.reset()  # singleton; isolate from any prior test's counters

    # Fresh process: tracker uninitialized, no POST has run _ensure_runtime_state().
    monkeypatch.setattr(server, "cost_tracker", None)
    # Neutralize reload() so the real _ensure_runtime_state keeps our caps config
    # instead of re-reading disk (the real reload path is covered by the
    # python -m import-split test in test_metrics_integration.py).
    monkeypatch.setattr(server, "reload", lambda *_a, **_k: None)

    provider = SimpleNamespace(tiers=SimpleNamespace(haiku="claude-haiku", sonnet="claude-sonnet", opus="claude-opus"))
    proxy = SimpleNamespace(
        costs=CostConfig(caps=CostCaps(per_day=5.0), cap_mode="post", on_cap_hit="warn"),
        get_provider=lambda _name=None: provider,
        default_tier="sonnet",
        preferred_provider="openai",
        active_template="litellm-openai",
        wire_shape="openai_translated",
        intercept=None,
        audit=None,
    )
    monkeypatch.setattr(server.config, "proxy", proxy)
    # Pin proxy identity so the test doesn't depend on registry/env discovery.
    monkeypatch.setattr(
        "forge.proxy.proxy_identity.get_proxy_identity",
        lambda **_: SimpleNamespace(
            proxy_id="p1",
            template="litellm-openai",
            port=8084,
            base_url="http://localhost:8084",
            source="registry",
            status="running",
        ),
    )

    from fastapi.testclient import TestClient

    resp = TestClient(app).get("/")

    assert resp.status_code == 200
    # The fix's payoff: root() self-initialized the caps tracker on the first GET.
    assert server.cost_tracker is not None and server.cost_tracker.has_caps
    caps = resp.json()["metrics"]["costs"]["caps"]
    assert "daily" in caps
    assert caps["daily"]["limit_usd"] == 5.0
