"""Regression: interactive non-Claude routes must reach their planned proxy model."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

import forge.proxy.data_models as proxy_data_models
import forge.proxy.server as proxy_server
from forge.config.loader import load_config
from forge.core.ops import claude_session as claude_session_ops
from forge.core.ops.claude_session import launch_claude_session
from forge.core.ops.session_model_routing import (
    ProxyRouteSnapshot,
    plan_session_model_route,
)
from forge.core.run_id import ANTHROPIC_CUSTOM_HEADERS_VAR, FORGE_MODEL_TIER_HEADER
from forge.proxy.data_models import MessagesRequest
from forge.proxy.model_routes import effective_proxy_model_maps
from forge.session import SessionStore, create_session_state
from forge.session.claude.invoke import _build_environment
from forge.session.models import ModelRouteIntent

pytestmark = pytest.mark.regression


@pytest.mark.parametrize(
    ("template", "requested_model", "model_tier", "selected_model"),
    [
        pytest.param(
            "openrouter-gemini-flash",
            "gemini-3.7-flash",
            "opus",
            "google/gemini-3.7-flash",
            id="openrouter",
        ),
        pytest.param(
            "litellm-gemini",
            "gemini-3.6-flash",
            None,
            "vertex_ai/gemini-3.6-flash",
            id="litellm-remote",
        ),
    ],
)
def test_non_claude_alternative_survives_launcher_to_proxy_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    template: str,
    requested_model: str,
    model_tier: str | None,
    selected_model: str,
) -> None:
    loaded = load_config(template=template)
    tier_mappings, alternatives = effective_proxy_model_maps(loaded.proxy)
    proxy = ProxyRouteSnapshot(
        template=template,
        base_url="http://127.0.0.1:65530",
        proxy_id=None,
        source_id=None,
        default_tier=loaded.proxy.default_tier,
        tier_mappings=tier_mappings,
        model_alternatives=alternatives,
        wire_shape=loaded.proxy.wire_shape,
    )
    plan = plan_session_model_route(requested_model, model_tier=model_tier, explicit_proxy=proxy)
    assert plan.kind == "proxy"
    assert plan.selected_model == selected_model
    if model_tier is not None:
        assert plan.selected_tier == model_tier

    worktree = tmp_path / template
    worktree.mkdir()
    route = ModelRouteIntent(
        requested_model=plan.request.requested_model,
        selected_tier=plan.selected_tier,
        kind="proxy",
        source_id=plan.source_id,
    )
    state = create_session_state(
        f"{template}-session",
        proxy_template=template,
        proxy_base_url=proxy.base_url,
        worktree_path=str(worktree),
        model_route=route,
    )
    state.forge_root = str(worktree)
    store = SessionStore(str(worktree), state.name)
    store.write(state)

    captured: dict[str, Any] = {}
    child_env: dict[str, str] = {}
    routing_payloads: list[dict[str, Any]] = []

    def invoke(**kwargs: Any) -> int:
        captured.update(kwargs)
        child_env.update(
            _build_environment(
                kwargs["env_vars"],
                kwargs["unset_env_vars"],
                run_identity=kwargs["run_identity"],
                projected_model_tier=kwargs.get("projected_model_tier"),
            )
        )
        return 0

    monkeypatch.setenv(
        ANTHROPIC_CUSTOM_HEADERS_VAR,
        f"X-User-Header: keep\n{FORGE_MODEL_TIER_HEADER}: haiku",
    )
    monkeypatch.setattr(claude_session_ops, "read_proxy_cost_baseline", lambda _base_url: None)
    result = launch_claude_session(
        manifest=state,
        session_id=None,
        resume_id=None,
        effective_template=template,
        runtime_base_url=proxy.base_url,
        context_limit=plan.context_limit,
        use_sidecar=False,
        fork_session=None,
        on_routing_payload=routing_payloads.append,
        invoke=invoke,
        run_active=lambda *, runner, **_kwargs: runner(),
    )

    assert result.exit_code == 0
    env_vars = cast(dict[str, str], captured["env_vars"])
    tier_default_var = f"ANTHROPIC_DEFAULT_{plan.selected_tier.upper()}_MODEL"
    assert env_vars["ANTHROPIC_MODEL"] == plan.selected_tier
    assert env_vars[tier_default_var] == plan.request.requested_model
    assert captured["projected_model_tier"] == plan.selected_tier
    custom_header_lines = child_env[ANTHROPIC_CUSTOM_HEADERS_VAR].splitlines()
    assert "X-User-Header: keep" in custom_header_lines
    tier_header_lines = [
        line for line in custom_header_lines if line.lower().startswith(f"{FORGE_MODEL_TIER_HEADER.lower()}:")
    ]
    assert tier_header_lines == [f"{FORGE_MODEL_TIER_HEADER}: {plan.selected_tier}"]

    assert routing_payloads[0]["requested_model"] == plan.request.requested_model
    assert routing_payloads[0]["selected_tier"] == plan.selected_tier
    assert routing_payloads[0]["selected_model"] == plan.selected_model
    persisted = store.read()
    assert persisted.intent.launch is not None
    assert persisted.intent.launch.model_route == route
    assert persisted.confirmed.route_commit is not None

    monkeypatch.setattr(proxy_server, "config", loaded)
    monkeypatch.setattr(proxy_data_models, "config", loaded)
    request = MessagesRequest(model=env_vars[tier_default_var], messages=[], max_tokens=1)
    projected_tier = tier_header_lines[0].split(":", 1)[1].strip()
    dispatched = proxy_server._resolve_model_with_alternatives(request, projected_tier=projected_tier)

    assert request.original_model_name == plan.request.requested_model
    assert dispatched.tier == plan.selected_tier
    assert dispatched.model == plan.selected_model
