"""Tests for workflow-specific routing types and functions."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from unittest.mock import patch, sentinel

import pytest

from forge.core.reactive.routing import ModelRoute, RoutingResult, RoutingSource
from forge.review.routing import (
    WorkerRoutingPlan,
    WorkflowRoutingError,
    clear_template_cache,
    derive_model_routes,
    preferred_proxy_for_routes,
    resolve_invocation_routing,
    resolve_model_flag,
)


class TestResolveModelFlag:

    def test_proxied_returns_model_ref(self):
        route = ModelRoute(
            provider="openrouter",
            credential="openrouter",
            family="openai",
            template_id="openrouter-openai",
            template_family="openai",
            model_ref="openai/gpt-5.5",
        )
        assert resolve_model_flag(route) == "openai/gpt-5.5"

    def test_direct_returns_none(self):
        route = ModelRoute(
            provider="direct",
            credential="anthropic-api",
            family="anthropic",
            template_id=None,
            template_family=None,
            model_ref="claude-opus-4-6",
        )
        assert resolve_model_flag(route) is None

    def test_litellm_returns_model_ref(self):
        route = ModelRoute(
            provider="litellm",
            credential="litellm-remote",
            family="openai",
            template_id="litellm-openai",
            template_family="openai",
            model_ref="openai/gpt-5.5",
        )
        assert resolve_model_flag(route) == "openai/gpt-5.5"


class TestWorkerRoutingPlan:

    def _make_result(self, source: RoutingSource = "preferred_proxy") -> RoutingResult:
        return RoutingResult(
            base_url="http://localhost:8096",
            proxy_id="openrouter-openai",
            template="openrouter-openai",
            source=source,
            route=ModelRoute(
                provider="openrouter",
                credential="openrouter",
                family="openai",
                template_id="openrouter-openai",
                template_family="openai",
                model_ref="openai/gpt-5.6-sol",
            ),
            credential="openrouter",
        )

    def test_construction(self):
        r1 = self._make_result("preferred_proxy")
        r2 = self._make_result("route_scan")
        plan = WorkerRoutingPlan(
            routes=(r1, r2),
            resolved_at="2026-05-14T12:00:00Z",
            via_override=None,
        )
        assert len(plan.routes) == 2
        assert plan.routes[0].source == "preferred_proxy"
        assert plan.routes[1].source == "route_scan"
        assert plan.via_override is None

    def test_with_via_override(self):
        plan = WorkerRoutingPlan(
            routes=(self._make_result("explicit"),),
            resolved_at="2026-05-14T12:00:00Z",
            via_override="openrouter-anthropic",
        )
        assert plan.via_override == "openrouter-anthropic"

    def test_frozen(self):
        plan = WorkerRoutingPlan(
            routes=(self._make_result(),),
            resolved_at="2026-05-14T12:00:00Z",
            via_override=None,
        )
        with pytest.raises(AttributeError):
            plan.via_override = "something"  # type: ignore[misc]

    def test_routes_indexed_by_position(self):
        r1 = self._make_result("explicit")
        r2 = self._make_result("route_scan")
        r3 = self._make_result("direct")
        plan = WorkerRoutingPlan(
            routes=(r1, r2, r3),
            resolved_at="2026-05-14T12:00:00Z",
            via_override=None,
        )
        assert plan.routes[0].source == "explicit"
        assert plan.routes[1].source == "route_scan"
        assert plan.routes[2].source == "direct"


@dataclass(frozen=True)
class _StubModelSpec:
    name: str
    model_id: str
    family: str
    description: str = ""
    prompt: str | None = None
    prompt_mode: str = "override"
    worker_id: str | None = None
    runtime: str = "claude_code"


_EXPECTED_WORKFLOW_ROUTES = {
    "gpt-5.6-sol": (
        "openrouter-openai",
        "openrouter-openai-codex",
        "openrouter-anthropic",
        "openrouter-deepseek",
        "openrouter-gemini",
        "openrouter-gemini-flash",
        "openrouter-glm",
        "openrouter-kimi",
        "openrouter-minimax",
        "openrouter-qwen",
        "codex-responses-local",
        "litellm-openai",
        "litellm-openai-codex-local",
        "litellm-openai-local",
    ),
    "gemini-3.1-pro-preview": (
        "openrouter-gemini",
        "openrouter-gemini-flash",
        "openrouter-anthropic",
        "openrouter-deepseek",
        "openrouter-glm",
        "openrouter-kimi",
        "openrouter-minimax",
        "openrouter-openai",
        "openrouter-openai-codex",
        "openrouter-qwen",
        "litellm-gemini",
        "litellm-gemini-flash-local",
        "litellm-gemini-local",
    ),
    "deepseek-v4-pro": (
        "openrouter-deepseek",
        "openrouter-anthropic",
        "openrouter-gemini",
        "openrouter-gemini-flash",
        "openrouter-glm",
        "openrouter-kimi",
        "openrouter-minimax",
        "openrouter-openai",
        "openrouter-openai-codex",
        "openrouter-qwen",
    ),
    "minimax-m3": (
        "openrouter-minimax",
        "openrouter-anthropic",
        "openrouter-deepseek",
        "openrouter-gemini",
        "openrouter-gemini-flash",
        "openrouter-glm",
        "openrouter-kimi",
        "openrouter-openai",
        "openrouter-openai-codex",
        "openrouter-qwen",
    ),
    "qwen3.8-max": (
        "openrouter-qwen",
        "openrouter-anthropic",
        "openrouter-deepseek",
        "openrouter-gemini",
        "openrouter-gemini-flash",
        "openrouter-glm",
        "openrouter-kimi",
        "openrouter-minimax",
        "openrouter-openai",
        "openrouter-openai-codex",
    ),
    "glm-5.3": (
        "openrouter-glm",
        "openrouter-anthropic",
        "openrouter-deepseek",
        "openrouter-gemini",
        "openrouter-gemini-flash",
        "openrouter-kimi",
        "openrouter-minimax",
        "openrouter-openai",
        "openrouter-openai-codex",
        "openrouter-qwen",
    ),
    "kimi-k3": (
        "openrouter-kimi",
        "openrouter-anthropic",
        "openrouter-deepseek",
        "openrouter-gemini",
        "openrouter-gemini-flash",
        "openrouter-glm",
        "openrouter-minimax",
        "openrouter-openai",
        "openrouter-openai-codex",
        "openrouter-qwen",
    ),
}


class TestDeriveModelRoutes:
    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        clear_template_cache()
        yield
        clear_template_cache()

    def test_fixed_catalog_order_for_every_proxy_worker(self) -> None:
        from forge.review.models import AVAILABLE_MODELS

        assert set(_EXPECTED_WORKFLOW_ROUTES) == {
            spec.name for spec in AVAILABLE_MODELS.values() if spec.runtime != "codex" and spec.family != "anthropic"
        }
        for name, expected_templates in _EXPECTED_WORKFLOW_ROUTES.items():
            routes = derive_model_routes(AVAILABLE_MODELS[name])
            assert tuple(route.template_id for route in routes) == expected_templates
            assert preferred_proxy_for_routes(routes) == expected_templates[0]

    @pytest.mark.parametrize(
        ("name", "model_ref"),
        [
            ("claude-opus", "claude-opus-5"),
            ("claude-opus-4.6", "claude-opus-4-6"),
            ("claude-opus-4.6-1m", "claude-opus-4-6[1m]"),
            ("claude-opus-4.8", "claude-opus-4-8"),
            ("claude-fable", "claude-fable-5"),
        ],
    )
    def test_fixed_direct_worker_routes(self, name: str, model_ref: str) -> None:
        from forge.review.models import AVAILABLE_MODELS

        routes = derive_model_routes(AVAILABLE_MODELS[name])
        assert [(route.provider, route.template_id, route.model_ref) for route in routes] == [
            ("direct", None, model_ref)
        ]
        assert preferred_proxy_for_routes(routes) is None

    def test_catalog_order_is_deterministic(self) -> None:
        spec = _StubModelSpec(name="gpt-5.6-sol", model_id="gpt-5.6-sol", family="openai")
        assert derive_model_routes(spec) == derive_model_routes(spec)

    def test_runtime_native_worker_has_no_catalog_lookup(self) -> None:
        from forge.review.models import AVAILABLE_MODELS

        codex = AVAILABLE_MODELS["codex"]
        assert codex.runtime == "codex"
        with patch("forge.review.routing.derive_model_routes") as derive:
            resolve_invocation_routing([codex])
        derive.assert_not_called()


class TestResolveInvocationRouting:

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        clear_template_cache()
        yield
        clear_template_cache()

    def _patch_resolver(self, result):
        return patch(
            "forge.core.reactive.routing.resolve_subprocess_routing",
            return_value=result,
        )

    def test_direct_only_spec_bypasses_resolver(self):
        """Direct-only specs short-circuit; resolver is not called."""
        spec = _StubModelSpec(
            name="claude-opus",
            model_id="claude-opus",
            family="anthropic",
        )
        with self._patch_resolver(None) as mock_resolver:
            plan = resolve_invocation_routing([spec])

        mock_resolver.assert_not_called()
        assert len(plan.routes) == 1
        assert plan.routes[0].source == "direct"
        assert plan.routes[0].route is not None
        assert plan.routes[0].route.provider == "direct"
        assert plan.routes[0].credential == "anthropic-api"
        assert plan.codex_preflight is None

    def test_runtime_native_spec_bypasses_route_and_proxy_resolution(self):
        spec = _StubModelSpec(
            name="codex",
            model_id="codex-default",
            family="openai",
            runtime="codex",
        )

        with (
            patch("forge.review.routing.derive_model_routes") as mock_derive,
            self._patch_resolver(None) as mock_resolver,
            patch(
                "forge.core.runtime.codex_preflight_cache.read_fresh_codex_preflight",
                return_value=sentinel.preflight,
            ) as mock_preflight,
        ):
            plan = resolve_invocation_routing([spec])

        mock_derive.assert_not_called()
        mock_resolver.assert_not_called()
        mock_preflight.assert_called_once_with()
        assert plan.codex_preflight is sentinel.preflight
        assert plan.routes == (
            RoutingResult(
                base_url=None,
                proxy_id=None,
                template=None,
                source="runtime_native",
                route=None,
                credential=None,
            ),
        )

    def test_runtime_native_with_via_warns_and_ignores_proxy(self):
        spec = _StubModelSpec(
            name="codex",
            model_id="codex-default",
            family="openai",
            runtime="codex",
        )

        with patch(
            "forge.core.runtime.codex_preflight_cache.read_fresh_codex_preflight",
            return_value=sentinel.preflight,
        ):
            plan = resolve_invocation_routing([spec], via="openrouter-openai")

        assert plan.routes[0].source == "runtime_native"
        assert plan.routes[0].route is None
        assert plan.routes[0].warning is not None
        assert "uses direct routing; --proxy ignored" in plan.routes[0].warning

    def test_mixed_plan_preserves_positional_alignment_and_one_preflight_read(self):
        native_spec = _StubModelSpec(
            name="codex",
            model_id="codex-default",
            family="openai",
            runtime="codex",
        )
        direct_spec = _StubModelSpec(
            name="claude-opus",
            model_id="claude-opus",
            family="anthropic",
        )

        with (
            patch(
                "forge.core.runtime.codex_preflight_cache.read_fresh_codex_preflight",
                return_value=sentinel.preflight,
            ) as mock_preflight,
        ):
            plan = resolve_invocation_routing([direct_spec, native_spec, native_spec])

        assert [result.source for result in plan.routes] == [
            "direct",
            "runtime_native",
            "runtime_native",
        ]
        assert plan.routes[0].route is not None
        assert plan.routes[1].route is None
        assert plan.routes[2].route is None
        mock_preflight.assert_called_once_with()

    def test_direct_only_with_via_emits_warning(self):
        spec = _StubModelSpec(
            name="claude-opus",
            model_id="claude-opus",
            family="anthropic",
        )
        plan = resolve_invocation_routing([spec], via="openrouter-openai")

        assert plan.routes[0].warning is not None
        assert "--proxy ignored" in plan.routes[0].warning
        assert plan.via_override == "openrouter-openai"

    def test_proxy_spec_calls_resolver(self):
        """Proxy-capable specs go through the full resolver."""
        spec = _StubModelSpec(
            name="gpt-5.6-sol",
            model_id="gpt-5.6-sol",
            family="openai",
        )
        mock_result = RoutingResult(
            base_url="http://localhost:8096",
            proxy_id="openrouter-openai",
            template="openrouter-openai",
            source="preferred_proxy",
            route=ModelRoute(
                provider="openrouter",
                credential="openrouter",
                family="openai",
                template_id="openrouter-openai",
                template_family="openai",
                model_ref="openai/gpt-5.6-sol",
            ),
            credential="openrouter",
        )
        with self._patch_resolver(mock_result):
            plan = resolve_invocation_routing([spec])

        assert len(plan.routes) == 1
        assert plan.routes[0].source == "preferred_proxy"

    def test_proxy_spec_logs_routing_decision(self, caplog):
        """Plan resolution emits a consolidated routing decision line."""
        spec = _StubModelSpec(
            name="gpt-5.6-sol",
            model_id="gpt-5.6-sol",
            family="openai",
        )
        mock_result = RoutingResult(
            base_url="http://localhost:8096",
            proxy_id="openrouter-openai",
            template="openrouter-openai",
            source="preferred_proxy",
            route=ModelRoute(
                provider="openrouter",
                credential="openrouter",
                family="openai",
                template_id="openrouter-openai",
                template_family="openai",
                model_ref="openai/gpt-5.6-sol",
            ),
            credential="openrouter",
        )

        with (
            self._patch_resolver(mock_result),
            caplog.at_level(
                logging.INFO,
                logger="forge.review.routing",
            ),
        ):
            resolve_invocation_routing([spec])

        assert "Routing decision: model=gpt-5.6-sol source=preferred_proxy" in caplog.text
        assert "proxy=openrouter-openai" in caplog.text
        assert "template=openrouter-openai" in caplog.text
        assert "model_ref=openai/gpt-5.6-sol" in caplog.text

    def test_fail_closed_on_unresolved(self, monkeypatch):
        """Workflow raises when a spec has no route."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        spec = _StubModelSpec(
            name="gpt-5.6-sol",
            model_id="gpt-5.6-sol",
            family="openai",
        )
        unresolved = RoutingResult(
            base_url=None,
            proxy_id=None,
            template=None,
            source="unresolved",
            route=None,
            credential=None,
        )
        with self._patch_resolver(unresolved):
            with pytest.raises(WorkflowRoutingError, match="No running proxy") as excinfo:
                resolve_invocation_routing([spec])
        assert "Tip:" not in str(excinfo.value)
        assert excinfo.value.tip_lines == (
            "Run 'forge proxy create openrouter-openai' to create one,",
            "or 'forge proxy start <id>' if one exists.",
        )

    def test_fail_closed_error_mentions_credential_when_missing(self, monkeypatch):
        """Error mentions credential when the key is not configured."""
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        spec = _StubModelSpec(
            name="gpt-5.6-sol",
            model_id="gpt-5.6-sol",
            family="openai",
        )
        unresolved = RoutingResult(
            base_url=None,
            proxy_id=None,
            template=None,
            source="unresolved",
            route=None,
            credential=None,
        )

        with self._patch_resolver(unresolved):
            with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
                resolve_invocation_routing([spec])

    def test_mixed_direct_and_proxy_specs(self):
        """Batch with both direct and proxy specs resolves both."""
        direct_spec = _StubModelSpec(
            name="claude-opus",
            model_id="claude-opus",
            family="anthropic",
        )
        proxy_spec = _StubModelSpec(
            name="gpt-5.6-sol",
            model_id="gpt-5.6-sol",
            family="openai",
        )
        mock_result = RoutingResult(
            base_url="http://localhost:8096",
            proxy_id="openrouter-openai",
            template="openrouter-openai",
            source="preferred_proxy",
            route=ModelRoute(
                provider="openrouter",
                credential="openrouter",
                family="openai",
                template_id="openrouter-openai",
                template_family="openai",
                model_ref="openai/gpt-5.6-sol",
            ),
            credential="openrouter",
        )
        with self._patch_resolver(mock_result):
            plan = resolve_invocation_routing([direct_spec, proxy_spec])

        assert len(plan.routes) == 2
        assert plan.routes[0].source == "direct"
        assert plan.routes[1].source == "preferred_proxy"

    def test_plan_has_resolved_at_timestamp(self):
        spec = _StubModelSpec(
            name="claude-opus",
            model_id="claude-opus",
            family="anthropic",
        )
        plan = resolve_invocation_routing([spec])

        assert plan.resolved_at
        assert "T" in plan.resolved_at
