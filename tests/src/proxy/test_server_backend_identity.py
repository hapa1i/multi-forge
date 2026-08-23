"""Tests for proxy backend-instance attribution and runtime identity."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from forge.config.schema import TierModels
from forge.proxy import server

_UNKNOWN_MARKER = "not a known backend instance"


def test_known_backend_returns_silently(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.setattr(server.config, "proxy", SimpleNamespace(backend="openrouter"))
    server._warned_unknown_backend_instances.clear()
    with caplog.at_level(logging.WARNING, logger=server.logger.name):
        assert server._backend_instance_id() == "openrouter"
    assert not [record for record in caplog.records if _UNKNOWN_MARKER in record.getMessage()]


def test_local_backend_uses_logical_instance_not_managed_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
        assert server._backend_instance_id() == "not-a-real-backend"
        assert server._backend_instance_id() == "not-a-real-backend"
    warnings = [
        record
        for record in caplog.records
        if _UNKNOWN_MARKER in record.getMessage() and "not-a-real-backend" in record.getMessage()
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


@pytest.mark.asyncio
async def test_root_exposes_effective_backend_and_model_alternatives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import forge.proxy.proxy_identity as identity

    provider = SimpleNamespace(
        tiers=TierModels(
            haiku="",
            sonnet="qwen/qwen3.6-flash",
            opus="anthropic/claude-opus-5",
        ),
        model_alternatives={"opus": {"opus": "qwen/qwen3.6-max-preview"}},
        allow_non_zdr=False,
        zdr_fallbacks={},
    )
    proxy = SimpleNamespace(
        preferred_provider="openrouter",
        default_tier="sonnet",
        backend="openrouter",
        wire_shape="openai_translated",
        intercept=SimpleNamespace(mode="passthrough"),
        audit=SimpleNamespace(audit_full_body=False),
        get_provider=lambda _provider=None: provider,
    )
    monkeypatch.setattr(server, "_ensure_runtime_state", lambda: None)
    monkeypatch.setattr(server.config, "proxy", proxy)
    monkeypatch.setattr(server, "get_context_window", lambda _model: 200_000)
    monkeypatch.setattr(
        server.client_factory,
        "get_default_hyperparams_for_tier",
        lambda **_kwargs: SimpleNamespace(model_dump=lambda **_dump_kwargs: {}),
    )
    monkeypatch.setattr(server, "build_intercept_capability_section", lambda *_args: {})
    monkeypatch.setattr(server, "advertise_responses_ingress", lambda *_args: False)
    monkeypatch.setattr(server, "_downstream_retention_status_section", lambda: ({}, False))
    monkeypatch.setattr(
        identity,
        "get_proxy_identity",
        lambda **_kwargs: SimpleNamespace(
            proxy_id="qwen-1",
            template="openrouter-qwen",
            port=8085,
            base_url="http://localhost:8085",
            source="process",
            status="running",
        ),
    )
    monkeypatch.setenv("ACTIVE_TEMPLATE", "openrouter-qwen")
    monkeypatch.setenv("PREFERRED_PROVIDER", "openrouter")
    monkeypatch.setenv("ACTIVE_PORT", "8085")
    monkeypatch.setenv("FORGE_PROXY_ID", "qwen-1")
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "http",
            "server": ("localhost", 8085),
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "headers": [],
        }
    )

    response = await server.root(request)

    assert response["runtime"]["backend_id"] == "openrouter"
    assert response["runtime"]["tier_mappings"] == {
        "haiku": "",
        "sonnet": "qwen/qwen3.8-27b",
        "opus": "anthropic/claude-opus-5",
    }
    assert response["runtime"]["context_windows"] == {
        "haiku": 200_000,
        "sonnet": 200_000,
        "opus": 200_000,
    }
    assert response["tiers"]["haiku"] == {"model": "", "context_window": 200_000}
    assert response["runtime"]["model_alternatives"] == {"opus": {"opus": "qwen/qwen3.8-2.4t-a95b"}}
