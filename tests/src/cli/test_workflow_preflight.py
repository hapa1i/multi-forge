"""Tests for workflow preflight output."""

from __future__ import annotations

import json
from unittest.mock import patch

from click.testing import CliRunner

from forge.cli import workflow as workflow_module
from forge.cli.main import main
from forge.core.reactive.routing import ModelRoute, RoutingResult
from forge.review.models import ModelSpec, MultiReviewOutput, ReviewResult
from forge.review.routing import WorkerRoutingPlan


def test_run_preflight_prints_routing_warnings() -> None:
    spec = ModelSpec(
        name="gpt-5.5",
        model_id="gpt-5.5",
        family="openai",
        provider_refs=(("openrouter", "openai/gpt-5.5"),),
        description="test",
    )
    route = ModelRoute(
        provider="openrouter",
        credential="openrouter",
        family="openai",
        template_id="openrouter-anthropic",
        template_family="anthropic",
        model_ref="openai/gpt-5.5",
    )
    plan = WorkerRoutingPlan(
        routes=(
            RoutingResult(
                base_url="http://localhost:8095",
                proxy_id="openrouter-anthropic",
                template="openrouter-anthropic",
                source="route_scan",
                route=route,
                credential="openrouter",
                warning="tier overrides may differ",
            ),
        ),
        resolved_at="2026-05-14T12:00:00Z",
        via_override=None,
    )

    with (
        patch("forge.review.engine.preflight_check", return_value=[]),
        patch.object(workflow_module.console, "print") as mock_print,
    ):
        workflow_module._run_preflight([spec], routing_plan=plan)

    printed = "\n".join(str(call.args[0]) for call in mock_print.call_args_list)
    assert "Routing warning" in printed
    assert "gpt-5.5: tier overrides may differ" in printed


def _auto_routing_plan(specs, **_kw):
    route = ModelRoute(
        provider="openrouter",
        credential="openrouter",
        family="openai",
        template_id="openrouter-openai",
        template_family="openai",
        model_ref="openai/gpt-5.5",
    )
    return WorkerRoutingPlan(
        routes=tuple(
            RoutingResult(
                base_url="http://localhost:8096",
                proxy_id="openrouter-openai",
                template="openrouter-openai",
                source="preferred_proxy",
                route=route,
                credential="openrouter",
            )
            for _ in specs
        ),
        resolved_at="2026-05-14T12:00:00Z",
        via_override=None,
    )


def _codex_routing_plan(specs, *, ready=True, blocking_reason=None, **_kw):
    from types import SimpleNamespace

    return WorkerRoutingPlan(
        routes=tuple(
            RoutingResult(
                base_url=None,
                proxy_id=None,
                template=None,
                source="runtime_native",
                route=None,
                credential=None,
            )
            for _ in specs
        ),
        resolved_at="2026-07-22T12:00:00Z",
        via_override=None,
        codex_preflight=SimpleNamespace(ready=ready, blocking_reason=blocking_reason),
    )


def test_workflow_json_preflight_reports_missing_claude_cli(monkeypatch):
    monkeypatch.setattr("forge.review.routing.resolve_invocation_routing", _auto_routing_plan)
    monkeypatch.setattr("forge.review.engine.shutil.which", lambda name: None)

    runner = CliRunner()
    with patch("forge.review.engine.run_multi_review") as mock_run:
        result = runner.invoke(
            main,
            [
                "workflow",
                "panel",
                "-p",
                "Review this",
                "--models",
                "deepseek-v4-pro",
                "--json",
            ],
        )

    assert result.exit_code == 1
    data = json.loads(result.output)
    assert "claude CLI not found in PATH" in data["preflight_errors"][0]
    mock_run.assert_not_called()


def test_codex_only_workflow_does_not_require_claude_binary(monkeypatch):
    monkeypatch.setattr("forge.review.routing.resolve_invocation_routing", _codex_routing_plan)
    monkeypatch.setattr("forge.review.engine.shutil.which", lambda name: None)

    with patch("forge.review.engine.run_multi_review") as mock_run:
        mock_run.return_value = MultiReviewOutput(
            prompt="Review this",
            results=[ReviewResult("codex", "ok", "", True, 1.0)],
        )
        result = CliRunner().invoke(
            main,
            ["workflow", "panel", "-p", "Review this", "--models", "codex", "--json"],
        )

    assert result.exit_code == 0
    mock_run.assert_called_once()


def test_codex_cache_miss_human_preflight_names_runtime_refresh_not_claude(monkeypatch):
    def missing_plan(specs, **_kw):
        plan = _codex_routing_plan(specs)
        return WorkerRoutingPlan(
            routes=plan.routes,
            resolved_at=plan.resolved_at,
            via_override=None,
            codex_preflight=None,
        )

    monkeypatch.setattr("forge.review.routing.resolve_invocation_routing", missing_plan)

    with patch("forge.review.engine.run_multi_review") as mock_run:
        result = CliRunner().invoke(
            main,
            ["workflow", "panel", "-p", "Review this", "--models", "codex"],
        )

    assert result.exit_code == 1
    assert "forge runtime preflight codex" in result.output
    assert "command -v claude" not in result.output
    mock_run.assert_not_called()


def test_codex_with_resume_context_fails_closed_naming_blind(monkeypatch):
    monkeypatch.setattr("forge.review.routing.resolve_invocation_routing", _codex_routing_plan)

    with patch("forge.review.engine.run_multi_review") as mock_run:
        result = CliRunner().invoke(
            main,
            [
                "workflow",
                "panel",
                "-p",
                "Review this",
                "--models",
                "codex",
                "--context",
                "resume:uuid-123",
            ],
        )

    assert result.exit_code == 1
    assert "--context blind" in " ".join(result.output.split())
    mock_run.assert_not_called()
