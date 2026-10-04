"""Context-estimator aliases must not choose the real model on passthrough routes."""

from pathlib import Path
from typing import Any

import pytest

from forge.cli.claude import _build_bare_launch_env
from forge.config.schema import ProxyInstanceConfig, TierModels
from forge.core.models.direct_model import apply_proxy_context_model_defaults
from forge.core.ops.claude_session import launch_claude_session
from forge.session import IndexStore, create_session_state
from tests.fixtures.session_state import publish_session

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("managed", [False, True])
@pytest.mark.parametrize("wire_shape", ["anthropic_passthrough", "openai_translated", "openai_responses_passthrough"])
def test_saved_proxy_wire_shape_controls_estimator_pins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, managed: bool, wire_shape: str
) -> None:
    # A user-owned wire shape wins over the current template's translated default.
    saved_proxy = ProxyInstanceConfig(
        proxy_format=1,
        template="openrouter-anthropic",
        template_digest="sha256:saved",
        provider="litellm",
        proxy_endpoint="http://127.0.0.1:8096",
        port=8096,
        upstream_base_url="https://api.anthropic.com",
        wire_shape=wire_shape,
        tiers=TierModels(haiku="claude-haiku-4-5", sonnet="claude-sonnet-5", opus="claude-opus-5"),
    )
    monkeypatch.setattr(
        "forge.config.loader.load_proxy_instance_config",
        lambda _proxy_id: saved_proxy,
    )
    captured: dict[str, str] = {}
    if managed:
        state = create_session_state("saved-proxy", worktree_path=str(tmp_path))
        state.forge_root = str(tmp_path)
        publish_session(IndexStore(), state, tmp_path)

        def invoke(**kwargs: Any) -> int:
            captured.update(kwargs["env_vars"])
            return 0

        launch_claude_session(
            manifest=state,
            session_id="saved-proxy-uuid",
            resume_id=None,
            effective_template="openrouter-anthropic",
            runtime_base_url="http://127.0.0.1:8096",
            proxy_id="saved-proxy",
            context_limit=1_000_000,
            use_sidecar=False,
            invoke=invoke,
            run_active=lambda runner, **_kwargs: runner(),
        )
    else:
        captured, _ = _build_bare_launch_env(
            base_url="http://127.0.0.1:8096",
            template="openrouter-anthropic",
            proxy_id="saved-proxy",
            context_limit=1_000_000,
        )

    for tier in ("SONNET", "OPUS"):
        key = f"ANTHROPIC_DEFAULT_{tier}_MODEL"
        if wire_shape == "anthropic_passthrough":
            assert key not in captured
        else:
            assert captured[key].endswith("[1m]")


@pytest.mark.parametrize("wire_shape", ["anthropic_passthrough", None])
def test_nontranslated_or_unknown_routes_preserve_explicit_native_pins(wire_shape: str | None) -> None:
    env = {"ANTHROPIC_DEFAULT_SONNET_MODEL": "claude-sonnet-5"}

    apply_proxy_context_model_defaults(env, 1_000_000, wire_shape=wire_shape)

    assert env == {"ANTHROPIC_DEFAULT_SONNET_MODEL": "claude-sonnet-5"}
