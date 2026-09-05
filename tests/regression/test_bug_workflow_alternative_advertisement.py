"""Workflow routing must recognize the alternative routes advertised by a proxy."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from forge.config.loader import load_config
from forge.core.reactive.routing import resolve_subprocess_routing
from forge.proxy.model_routes import effective_proxy_model_maps
from forge.review.models import resolve_model_specs
from forge.review.routing import derive_model_routes

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("template", ["openrouter-openai", "openrouter-openai-codex"])
@pytest.mark.parametrize("model", ["gpt-6-astra-pro", "gpt-5.6-sol"])
def test_alternative_worker_does_not_warn_on_fresh_proxy(template: str, model: str) -> None:
    config = load_config(template=template)
    tiers, alternatives = effective_proxy_model_maps(config.proxy)
    body = {"is_proxy": True, "runtime": {"tier_mappings": tiers, "model_alternatives": alternatives}}
    http_client = MagicMock()
    http_client.get.return_value.status_code = 200
    http_client.get.return_value.json.return_value = body
    entry = SimpleNamespace(
        proxy_id=template, template=template, base_url="http://localhost:8096", port=8096, pid=123, status="running"
    )
    routes = derive_model_routes(resolve_model_specs(model)[0])

    with (
        patch("httpx.Client") as http_client_class,
        patch("forge.core.reactive.routing.lookup_proxy_entry_strict", return_value=entry),
        patch("forge.core.reactive.routing._check_proxy_reachable", return_value=True),
    ):
        http_client_class.return_value.__enter__.return_value = http_client
        result = resolve_subprocess_routing(explicit_proxy=template, routes=routes, advisory_check=True)

    assert result.route is not None
    assert result.route.model_ref == f"openai/{model}"
    assert result.warning is None
