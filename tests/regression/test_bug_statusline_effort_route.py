"""Statusline marking and drift must follow projection and passthrough dispatch."""

from unittest.mock import patch

import pytest

from forge.cli.statusline.context import RenderContext
from forge.cli.statusline.formatting import _ANSI_RE
from forge.cli.statusline.registry import render_segments
from forge.proxy.runtime_truth import ProxyRuntimeTruth
from forge.runtime_config import RuntimeConfig

pytestmark = pytest.mark.regression


@pytest.mark.parametrize(
    (
        "wire_shape",
        "client_model",
        "projected_tier",
        "expected_model",
        "expected_label",
    ),
    [
        (
            "openai_translated",
            "gpt-6.1-sol",
            "opus",
            "gpt-6.1-sol",
            "O:gpt-6.1-sol@unknown",
        ),
        (
            "anthropic_passthrough",
            "claude-opus-4-6[1m]",
            "sonnet",
            "claude-opus-4-6",
            "O:claude-opus-4-6@unknown",
        ),
    ],
)
def test_marking_drift_and_label_share_actual_dispatch_path(
    monkeypatch,
    wire_shape,
    client_model,
    projected_tier,
    expected_model,
    expected_label,
):
    monkeypatch.setenv("ANTHROPIC_CUSTOM_HEADERS", f"X-Forge-Model-Tier: {projected_tier}")
    runtime = ProxyRuntimeTruth(
        {
            "is_proxy": True,
            "wire_shape": wire_shape,
            "runtime": {
                "backend_id": "openrouter",
                "active_tier": "sonnet",
                "tier_mappings": {
                    "opus": "anthropic/claude-opus-5-5",
                    "sonnet": "openai/gpt-6-astra",
                },
                "model_alternatives": {"opus": {"gpt-6.1-sol": "openai/gpt-6.1-sol"}},
                "effort": {},
            },
        }
    )
    ctx = RenderContext(
        data={"model": {"id": client_model, "display_name": "Claude"}},
        is_proxy=True,
        runtime=runtime,
        is_proxy_authoritative=True,
        manifest=None,
        is_session_authoritative=False,
        config=RuntimeConfig(),
    )
    with (
        patch(
            "forge.core.models.model_practices.load_model_practices",
            return_value=object(),
        ),
        patch(
            "forge.core.models.model_practices.resolve_model_practice",
            return_value={"status": "marked"},
        ) as resolve,
    ):
        _, stream = render_segments(ctx, ["model", "drift", "marking"])
    visible = [_ANSI_RE.sub("", segment) for segment in stream]
    assert expected_label in visible[0]
    assert visible[1:] == ["mark:yes"]
    assert resolve.call_args.args[0] == expected_model
    assert ctx.route.tier == "opus"
