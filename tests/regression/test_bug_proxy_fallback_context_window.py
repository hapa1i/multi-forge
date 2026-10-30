"""Registry fallback must render the catalog window instead of Claude's cached size."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from forge.cli.statusline.context import RenderContext
from forge.cli.statusline.formatting import _ANSI_RE
from forge.cli.statusline.registry import render_segments
from forge.cli.statusline.sources import detect_proxy
from forge.runtime_config import RuntimeConfig

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("config_available,expected", [(True, "20%/1M"), (False, "50%/400K")])
def test_registry_fallback_context_window_reaches_rendered_bar(monkeypatch, config_available, expected):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://localhost:8085")
    monkeypatch.delenv("ANTHROPIC_CUSTOM_HEADERS", raising=False)
    entry = SimpleNamespace(base_url="http://localhost:8085", port=8085, template="litellm-openai")
    config = SimpleNamespace(proxy=SimpleNamespace(default_tier="sonnet", backend=None))
    with (
        patch("urllib.request.urlopen", side_effect=OSError("Connection refused")),
        patch("forge.proxy.proxies.ProxyRegistryStore") as store,
        patch("forge.config.loader.load_config", return_value=config) as load_config,
        patch("forge.proxy.model_routes.effective_proxy_model_maps", return_value=({"sonnet": "gpt-4.1"}, {})),
    ):
        store.return_value.read.return_value = SimpleNamespace(proxies={"fallback": entry})
        if not config_available:
            load_config.side_effect = OSError("Config unavailable")
        is_proxy, runtime, authoritative = detect_proxy()

    assert is_proxy and runtime is not None and not authoritative
    ctx = RenderContext(
        data={
            "model": {"display_name": "Sonnet", "id": "claude-sonnet-4-5"},
            "context_window": {"context_window_size": 400_000, "current_usage": {"input_tokens": 200_000}},
        },
        is_proxy=is_proxy,
        runtime=runtime,
        is_proxy_authoritative=authoritative,
        manifest=None,
        is_session_authoritative=False,
        config=RuntimeConfig(),
    )
    _, stream = render_segments(ctx, ["model"])
    assert _ANSI_RE.sub("", stream[0]).endswith(expected)
