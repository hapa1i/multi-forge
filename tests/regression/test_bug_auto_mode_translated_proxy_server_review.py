"""Auto mode must not wait on a server review that a translated proxy cannot carry.

Claude Code asks Anthropic's server to review auto-mode actions in-band whenever
``ANTHROPIC_BASE_URL`` points at a gateway. Forge's translated proxy rebuilds the
request for a non-Anthropic upstream, so no review result ever arrives and
interactive Claude Code stops with "Auto mode can't check actions in this
session". Managed launches on translated routes must use Claude Code's local
classifier instead, while passthrough and direct launches keep the server review.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from forge.config.schema import ProxyInstanceConfig, TierModels
from forge.core.ops.claude_session import ClaudeLaunchReady, launch_claude_session
from forge.core.reactive.env import (
    CLAUDE_CODE_AUTO_MODE_SERVER_VAR,
    FORGE_AUTO_MODE_SERVER_MANAGED_VAR,
)
from forge.session import IndexStore, create_session_state
from forge.session.claude.invoke import _build_environment
from tests.fixtures.session_state import publish_session

pytestmark = pytest.mark.regression


def _launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, wire_shape: str | None
) -> tuple[dict[str, str], ClaudeLaunchReady]:
    if wire_shape is not None:
        saved_proxy = ProxyInstanceConfig(
            proxy_format=1,
            template="openrouter-gemini",
            template_digest="sha256:saved",
            provider="openrouter",
            proxy_endpoint="http://127.0.0.1:8097",
            port=8097,
            upstream_base_url="https://openrouter.ai/api/v1",
            wire_shape=wire_shape,
            tiers=TierModels(
                haiku="google/gemini-3.8-flash",
                sonnet="google/gemini-4-carbon",
                opus="google/gemini-4-carbon",
            ),
        )
        monkeypatch.setattr("forge.config.loader.load_proxy_instance_config", lambda _proxy_id: saved_proxy)
    monkeypatch.setattr("forge.session.launch_confirmation.read_proxy_cost_baseline", lambda *_a, **_kw: None)

    state = create_session_state("auto-mode", worktree_path=str(tmp_path))
    state.forge_root = str(tmp_path)
    publish_session(IndexStore(), state, tmp_path)
    child_env: dict[str, str] = {}
    events: list[ClaudeLaunchReady] = []

    def invoke(**kwargs: Any) -> int:
        # The real interactive builder owns the final child environment.
        child_env.update(
            _build_environment(
                kwargs["env_vars"],
                kwargs["unset_env_vars"],
                run_identity=kwargs["run_identity"],
                projected_model_tier=kwargs.get("projected_model_tier"),
            )
        )
        return 0

    launch_claude_session(
        manifest=state,
        session_id="auto-mode-uuid",
        resume_id=None,
        effective_template="openrouter-gemini" if wire_shape else None,
        runtime_base_url="http://127.0.0.1:8097" if wire_shape else None,
        proxy_id="slate-lime" if wire_shape else None,
        context_limit=1_000_000,
        use_sidecar=False,
        invoke=invoke,
        run_active=lambda runner, **_kwargs: runner(),
        on_launch_ready=events.append,
    )
    assert len(events) == 1
    return child_env, events[0]


@pytest.fixture(autouse=True)
def _no_user_auto_mode_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        CLAUDE_CODE_AUTO_MODE_SERVER_VAR,
        FORGE_AUTO_MODE_SERVER_MANAGED_VAR,
        "CLAUDE_CODE_AUTO_MODE_MODEL",
        "ANTHROPIC_DEFAULT_SONNET_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)


@pytest.mark.parametrize("wire_shape", ["openai_translated", "openai_responses_passthrough"])
def test_translated_session_uses_local_classifier_and_names_its_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, wire_shape: str
) -> None:
    child_env, event = _launch(tmp_path, monkeypatch, wire_shape=wire_shape)

    assert child_env[CLAUDE_CODE_AUTO_MODE_SERVER_VAR] == "0"
    # The 1M context pin maps Sonnet 5.5 to Claude Code's Sonnet 5 classifier default.
    assert child_env["ANTHROPIC_DEFAULT_SONNET_MODEL"] == "claude-sonnet-5-5[1m]"
    assert event.auto_mode_classifier_model == "claude-sonnet-5"


def test_passthrough_session_keeps_server_review(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    child_env, event = _launch(tmp_path, monkeypatch, wire_shape="anthropic_passthrough")

    assert CLAUDE_CODE_AUTO_MODE_SERVER_VAR not in child_env
    assert event.auto_mode_classifier_model is None


def test_direct_session_inside_translated_session_regains_server_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Claude Code's Bash tool hands the parent session's environment to nested launches.
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:8097")
    monkeypatch.setenv("FORGE_PROXY_WIRE_SHAPE", "openai_translated")
    monkeypatch.setenv(CLAUDE_CODE_AUTO_MODE_SERVER_VAR, "0")
    monkeypatch.setenv(FORGE_AUTO_MODE_SERVER_MANAGED_VAR, "1")

    child_env, event = _launch(tmp_path, monkeypatch, wire_shape=None)

    assert "ANTHROPIC_BASE_URL" not in child_env
    assert CLAUDE_CODE_AUTO_MODE_SERVER_VAR not in child_env
    assert FORGE_AUTO_MODE_SERVER_MANAGED_VAR not in child_env
    assert event.auto_mode_classifier_model is None
