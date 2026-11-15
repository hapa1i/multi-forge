"""A child sent to a different proxy must not inherit the spawner's wire shape.

Workflow workers and the supervisor runner pass their own ``base_url`` to
``build_claude_env``, which starts from the spawning session's environment. The
inherited ``FORGE_PROXY_WIRE_SHAPE`` described the session's proxy, so a translated
worker under a passthrough session lost the prompt-cache and auto-mode workarounds,
and a passthrough worker under a translated session kept both.
"""

from __future__ import annotations

import json

import pytest

from forge.core.paths import get_forge_home
from forge.core.reactive.env import (
    CLAUDE_CODE_ATTRIBUTION_HEADER_VAR,
    CLAUDE_CODE_AUTO_MODE_SERVER_VAR,
    FORGE_AUTO_MODE_SERVER_MANAGED_VAR,
    FORGE_PROXY_WIRE_SHAPE_VAR,
    build_claude_env,
)

pytestmark = pytest.mark.regression

_PASSTHROUGH_URL = "http://127.0.0.1:18301"
_TRANSLATED_URL = "http://127.0.0.1:18302"


@pytest.fixture(autouse=True)
def _registry(monkeypatch: pytest.MonkeyPatch) -> None:
    proxies = {
        "pass-proxy": ("anthropic-passthrough", _PASSTHROUGH_URL, 18301),
        "gem-proxy": ("openrouter-gemini", _TRANSLATED_URL, 18302),
    }
    registry = {
        "version": 1,
        "proxies": {
            proxy_id: {"proxy_id": proxy_id, "template": template, "base_url": url, "port": port, "status": "healthy"}
            for proxy_id, (template, url, port) in proxies.items()
        },
    }
    path = get_forge_home() / "proxies" / "index.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(registry), encoding="utf-8")
    for key in (
        CLAUDE_CODE_ATTRIBUTION_HEADER_VAR,
        CLAUDE_CODE_AUTO_MODE_SERVER_VAR,
        FORGE_AUTO_MODE_SERVER_MANAGED_VAR,
    ):
        monkeypatch.delenv(key, raising=False)


def test_translated_worker_under_passthrough_session_gets_translated_policies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_BASE_URL", _PASSTHROUGH_URL)
    monkeypatch.setenv(FORGE_PROXY_WIRE_SHAPE_VAR, "anthropic_passthrough")

    env = build_claude_env(base_url=_TRANSLATED_URL)

    assert env[FORGE_PROXY_WIRE_SHAPE_VAR] == "openai_translated"
    assert env[CLAUDE_CODE_ATTRIBUTION_HEADER_VAR] == "0"
    assert env[CLAUDE_CODE_AUTO_MODE_SERVER_VAR] == "0"


def test_passthrough_worker_under_translated_session_drops_translated_policies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_BASE_URL", _TRANSLATED_URL)
    monkeypatch.setenv(FORGE_PROXY_WIRE_SHAPE_VAR, "openai_translated")
    monkeypatch.setenv(CLAUDE_CODE_ATTRIBUTION_HEADER_VAR, "0")
    monkeypatch.setenv(CLAUDE_CODE_AUTO_MODE_SERVER_VAR, "0")
    monkeypatch.setenv(FORGE_AUTO_MODE_SERVER_MANAGED_VAR, "1")

    env = build_claude_env(base_url=_PASSTHROUGH_URL)

    assert env[FORGE_PROXY_WIRE_SHAPE_VAR] == "anthropic_passthrough"
    assert CLAUDE_CODE_ATTRIBUTION_HEADER_VAR not in env
    assert CLAUDE_CODE_AUTO_MODE_SERVER_VAR not in env
    assert FORGE_AUTO_MODE_SERVER_MANAGED_VAR not in env
