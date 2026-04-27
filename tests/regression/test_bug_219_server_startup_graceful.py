"""Regression tests for proxy server startup behavior."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.regression


def test_server_main_allows_start_without_proxy_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Starting proxy without proxy id should not require registry and should allow --auto-port."""

    from forge.proxy import server

    class _Tiers:
        haiku = "haiku-model"
        sonnet = "sonnet-model"
        opus = "opus-model"

    class _Reasoning:
        effort = "low"
        verbosity = "low"

    class _ProviderCfg:
        tiers = _Tiers()
        reasoning = _Reasoning()
        cache_ttl = 0
        base_url = "http://example"

    class _Proxy:
        preferred_provider = "litellm"
        default_port = 5555

        def get_provider(self, _provider: str) -> _ProviderCfg:
            return _ProviderCfg()

    class _Cfg:
        proxy = _Proxy()

    called: dict[str, object] = {"called": False, "kwargs": {}}

    def _fake_run(*_args, **kwargs):
        called["called"] = True
        called["kwargs"] = kwargs

    monkeypatch.setattr(server, "init_config", lambda **_: _Cfg())
    monkeypatch.setattr(server, "find_available_port", lambda *_args, **_kwargs: 5555)
    monkeypatch.setattr(server.uvicorn, "run", _fake_run)

    # click.Command callback (server.main is a click.Command)
    assert server.main.callback is not None
    server.main.callback(
        template="litellm-openai",
        port=5555,
        host="0.0.0.0",
        reload=False,
        auto_port=True,
        proxy_id=None,
    )

    assert called["called"] is True

    uvicorn_kwargs = called["kwargs"]
    assert isinstance(uvicorn_kwargs, dict)
    assert uvicorn_kwargs["port"] == 5555
    assert server.PROXY_ID is None
