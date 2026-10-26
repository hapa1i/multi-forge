"""Worker routing builders and native-control assertions shared across test scopes."""

from __future__ import annotations

import json

from forge.core.reactive.routing import ModelRoute, RoutingResult, RoutingSource
from forge.core.runtime.codex_preflight import CodexPreflight
from forge.review.models import ModelSpec, PromptMode
from forge.review.routing import WorkerRoutingPlan

HOSTILE_ENV = {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1",
    "CLAUDE_CODE_FORK_SUBAGENT": "1",
    "CLAUDE_CODE_DISABLE_WORKFLOWS": "0",
    "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "0",
}


def assert_claude_worker_controls(argv: list[str], env: dict[str, str]) -> None:
    assert env["CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"] == "0"
    assert env["CLAUDE_CODE_FORK_SUBAGENT"] == "0"
    assert env["CLAUDE_CODE_DISABLE_WORKFLOWS"] == "1"
    assert env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"
    index = argv.index("--disallowedTools")
    assert argv[index + 1 : index + 4] == ["Agent", "Workflow", "SendMessage"]
    assert argv.count("--disable-slash-commands") == 1
    settings = [json.loads(value) for flag, value in zip(argv, argv[1:]) if flag == "--settings"]
    assert len(settings) == 1, "Worker and helper settings must be composed once"
    for projected in settings:
        assert projected["env"] == {key: env[key] for key in HOSTILE_ENV}


def make_model_spec(
    name: str = "test-model",
    family: str = "openai",
    direct: bool = False,
    prompt: str | None = None,
    prompt_mode: PromptMode = "override",
    runtime: str = "claude_code",
) -> ModelSpec:
    return ModelSpec(
        name=name,
        model_id=("codex-default" if runtime == "codex" else "claude-opus-4-6" if direct else "gpt-5.6-sol"),
        family="anthropic" if direct and runtime != "codex" else family,
        description="Test",
        prompt=prompt,
        prompt_mode=prompt_mode,
        runtime=runtime,
    )


def make_codex_spec() -> ModelSpec:
    return ModelSpec(
        name="codex",
        model_id="codex-default",
        family="openai",
        description="Native Codex",
        runtime="codex",
    )


def make_model_route(
    provider: str = "openrouter",
    model_ref: str = "openai/gpt-5.5",
    template_id: str = "openrouter-openai",
    credential: str = "openrouter",
    family: str = "openai",
) -> ModelRoute:
    return ModelRoute(
        provider=provider,
        credential=credential,
        family=family,
        template_id=template_id if provider != "direct" else None,
        template_family=family if provider != "direct" else None,
        model_ref=model_ref,
    )


def make_routing_result(
    route: ModelRoute | None = None,
    base_url: str | None = "http://localhost:8096",
    source: RoutingSource = "preferred_proxy",
) -> RoutingResult:
    if route is None:
        route = make_model_route()
    return RoutingResult(
        base_url=base_url,
        proxy_id="test-proxy",
        template="openrouter-openai",
        source=source,
        route=route,
        credential=route.credential if route else None,
    )


def runtime_native_result() -> RoutingResult:
    return RoutingResult(
        base_url=None,
        proxy_id=None,
        template=None,
        source="runtime_native",
        route=None,
        credential=None,
    )


def make_worker_plan(*results: RoutingResult, codex_preflight: CodexPreflight | None = None) -> WorkerRoutingPlan:
    return WorkerRoutingPlan(
        routes=tuple(results),
        resolved_at="2026-05-14T12:00:00Z",
        via_override=None,
        codex_preflight=codex_preflight,
    )


def make_codex_preflight(
    *,
    ready: bool = True,
    blocking_reason: str | None = None,
    billing_mode: str = "subscription_quota",
) -> CodexPreflight:
    return CodexPreflight(
        installed=True,
        version="0.145.0",
        version_ok=True,
        auth_method="chatgpt_tokens",
        auth_source="codex_store",
        billing_mode=billing_mode,  # type: ignore[arg-type]
        ready=ready,
        blocking_reason=blocking_reason,
        hook_seam="enrollment_gated",
        proxy_responses="native_direct",
        doctor_status="ok",
    )
