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


def _effort_record(**changes):
    return {
        "tier": "sonnet",
        "tier_source": "fallback",
        "client_model": "custom-model",
        "mapped_model": "custom-model",
        "requested": None,
        "thinking": None,
        "opt_in": False,
        "client_applicable": False,
        "derived": None,
        "floor": None,
        "pre_clamp": None,
        "supported": None,
        "resolved": None,
        "source": "passthrough",
        "applied": None,
        "wire": None,
        "note": None,
        "observed_at": "2026-10-30T12:00:00Z",
        **changes,
    }


def _context_with_observations(effort, *, wire_shape="anthropic_passthrough"):
    return RenderContext(
        data={"model": {"id": "custom-model", "display_name": "Custom"}},
        is_proxy=True,
        runtime=ProxyRuntimeTruth(
            {
                "is_proxy": True,
                "wire_shape": wire_shape,
                "runtime": {
                    "backend_id": "anthropic",
                    "active_tier": None,
                    "tier_mappings": {"sonnet": "claude-sonnet-5-5"},
                    "model_alternatives": {},
                    "effort": effort,
                },
            }
        ),
        is_proxy_authoritative=True,
        manifest=None,
        is_session_authoritative=False,
        config=RuntimeConfig(),
    )


@pytest.mark.parametrize("wire_shape", ["anthropic_passthrough", "openai_translated", None])
def test_only_live_passthrough_uses_sonnet_when_default_tier_is_absent(monkeypatch, wire_shape):
    monkeypatch.delenv("ANTHROPIC_CUSTOM_HEADERS", raising=False)
    ctx = _context_with_observations({"sonnet": _effort_record()}, wire_shape=wire_shape)
    _, stream = render_segments(ctx, ["model", "drift"])
    visible = _ANSI_RE.sub("", " ".join(stream))
    if wire_shape == "anthropic_passthrough":
        assert ctx.route.tier == "sonnet"
        assert ctx.route.model == "custom-model"
        assert "S:custom-model@unset" in visible
    else:
        assert ctx.route.tier is None
        assert ctx.route.model is None
        assert "@unset" not in visible
    assert "drift:" not in visible


@pytest.mark.parametrize("changed_effort", [None, "low"])
def test_observed_absent_parameter_renders_unset_including_when_stale(monkeypatch, changed_effort):
    monkeypatch.setenv("ANTHROPIC_CUSTOM_HEADERS", "X-Forge-Model-Tier: sonnet")
    ctx = _context_with_observations({"sonnet": _effort_record()})
    if changed_effort:
        ctx.data["effort"] = {"level": changed_effort}
    _, stream = render_segments(ctx, ["model"])
    visible = _ANSI_RE.sub("", stream[0])
    assert f"@unset{' (stale)' if changed_effort else ''}" in visible
    assert "@unknown" not in visible


@pytest.mark.parametrize("other_requested", ["future-client-level", "invalid\nlevel"])
def test_other_tier_requested_effort_cannot_hide_active_observation(monkeypatch, other_requested):
    monkeypatch.setenv("ANTHROPIC_CUSTOM_HEADERS", "X-Forge-Model-Tier: sonnet")
    ctx = _context_with_observations(
        {
            "sonnet": _effort_record(),
            "haiku": _effort_record(tier="haiku", requested=other_requested),
        }
    )
    _, stream = render_segments(ctx, ["model"])
    assert "S:custom-model@unset" in _ANSI_RE.sub("", stream[0])
