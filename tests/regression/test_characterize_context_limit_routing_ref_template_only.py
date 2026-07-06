"""Characterization: CLI proxy routing carries a proxy id, not only a template.

The fresh-resume context-limit paths use ``routing.proxy_id`` when ``--proxy`` was
provided. A template-only ``ResolvedRouting`` would behave differently from
``_resume_context_ref`` (which falls back to ``proxy_id or template``), so this pins
the production resolver contract before deciding whether that difference is real drift.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from forge.cli.session import _resolve_routing_from_cli
from forge.proxy.proxies import ProxyEntry

pytestmark = pytest.mark.regression


def test_resolve_routing_from_cli_proxy_path_returns_proxy_id() -> None:
    entry = ProxyEntry(
        proxy_id="openrouter-kimi-1234",
        template="openrouter-kimi",
        base_url="http://localhost:8090",
        port=8090,
    )

    with (
        patch("forge.proxy.proxy_orchestrator.ensure_proxy", return_value=(entry, False)),
        patch("forge.cli.claude._healthcheck_proxy"),
        patch("forge.session.context_limit._get_context_limit_for_proxy", return_value=1048576),
    ):
        routing = _resolve_routing_from_cli(proxy_name="openrouter-kimi", direct=False)

    assert routing.template == "openrouter-kimi"
    assert routing.proxy_id == "openrouter-kimi-1234"
    assert routing.base_url == "http://localhost:8090"
    assert routing.context_limit == 1048576


def test_resolve_routing_from_cli_direct_path_has_no_template_or_proxy_id() -> None:
    routing = _resolve_routing_from_cli(proxy_name=None, direct=True)

    assert routing.template is None
    assert routing.proxy_id is None
    assert routing.base_url is None
