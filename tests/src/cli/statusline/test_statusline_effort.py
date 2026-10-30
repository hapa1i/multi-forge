"""Launch-scoped effort rendering and defensive proxy observation parsing."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from forge.cli.status_line import status_line
from forge.cli.statusline import formatting as fmt
from forge.cli.statusline.context import RenderContext
from forge.cli.statusline.names import DEFAULT_ORDER
from forge.cli.statusline.registry import render_segments
from forge.cli.statusline.sources import detect_proxy
from forge.cli.statusline.types import ProxyRuntimeTruth, TranscriptStats
from forge.runtime_config import RuntimeConfig, StatusLineConfig


def _record(**changes):
    return {
        "tier": "opus",
        "tier_source": "request",
        "client_model": "claude-opus-5-5",
        "mapped_model": "openai/gpt-6-astra",
        "requested": "xhigh",
        "thinking": "adaptive",
        "opt_in": False,
        "client_applicable": True,
        "derived": "medium",
        "floor": "high",
        "pre_clamp": "high",
        "supported": ["low", "medium", "high", "xhigh", "max"],
        "resolved": "high",
        "source": "floor",
        "applied": "high",
        "wire": "reasoning.effort",
        "note": None,
        "observed_at": "2026-10-30T12:00:00Z",
        **changes,
    }


def _raw(effort=None, *, wire_shape="openai_translated"):
    return {
        "is_proxy": True,
        "wire_shape": wire_shape,
        "proxy": {"template": "openrouter-openai"},
        "runtime": {
            "backend_id": "openrouter",
            "active_tier": "sonnet",
            "tier_mappings": {
                "opus": "openai/gpt-6-astra",
                "sonnet": "openai/gpt-6-astra",
                "haiku": "openai/gpt-5.4-mini",
            },
            "model_alternatives": {},
            "effort": effort if effort is not None else {"opus": _record()},
        },
    }


def _context(*, raw=None, data=None, authoritative=True):
    return RenderContext(
        data=data
        or {
            "model": {"id": "claude-opus-5-5", "display_name": "Opus 5.5"},
            "effort": {"level": "xhigh"},
        },
        is_proxy=raw is not None,
        runtime=ProxyRuntimeTruth(raw) if raw is not None else None,
        is_proxy_authoritative=authoritative,
        manifest=None,
        is_session_authoritative=False,
        config=RuntimeConfig(),
    )


def _model(ctx):
    _, stream = render_segments(ctx, ["model"])
    return fmt._ANSI_RE.sub("", stream[0])


@pytest.fixture(autouse=True)
def _isolated_headers(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_CUSTOM_HEADERS", raising=False)


@pytest.mark.parametrize("level", ["low", "medium", "high", "xhigh", "max"])
def test_direct_effort_uses_stdin_and_context_only_appears_in_bar(level):
    ctx = _context(
        data={
            "model": {"display_name": "Opus 5.5 (1M context)"},
            "effort": {"level": level},
            "context_window": {"context_window_size": 1_000_000, "used_percentage": 47},
        }
    )
    assert _model(ctx) == f"[Opus 5.5 @{level}] ###----- 47%/1M"
    _, stream = render_segments(ctx, ["model"])
    assert fmt.TIER_OPUS in stream[0]


@pytest.mark.parametrize("effort", [None, {}, {"level": None}, {"level": []}, {"level": "high\n"}])
def test_direct_missing_or_invalid_effort_is_omitted(effort):
    assert "@" not in _model(_context(data={"model": {"display_name": "Opus"}, "effort": effort}))


def test_think_stays_available_only_by_opt_in():
    ctx = _context()
    ctx.transcript_stats = TranscriptStats(has_thinking=True)
    assert "think" not in DEFAULT_ORDER
    _, stream = render_segments(ctx, ["think"])
    assert fmt._ANSI_RE.sub("", stream[0]) == "THINK"


@pytest.mark.parametrize(
    ("changes", "stdin_effort", "expected"),
    [
        ({}, "xhigh", "high<-xhigh"),
        (
            {
                "applied": "xhigh",
                "resolved": "xhigh",
                "source": "client",
                "opt_in": True,
            },
            "xhigh",
            "xhigh",
        ),
        ({"requested": None}, None, "high"),
        (
            {
                "applied": "low",
                "resolved": "low",
                "requested": "max",
                "client_applicable": False,
                "thinking": "between_tools",
                "derived": "none",
                "floor": None,
            },
            "max",
            "low<-max",
        ),
        (
            {
                "requested": "max",
                "client_applicable": False,
                "thinking": "disabled",
                "derived": "none",
            },
            "max",
            "high<-max",
        ),
        ({"applied": None, "wire": "dropped"}, "xhigh", "dropped<-xhigh"),
        ({"applied": None, "wire": None}, "xhigh", "unknown"),
        ({}, "low", "high (stale)"),
    ],
)
def test_proxied_effort_uses_outbound_observation(changes, stdin_effort, expected):
    ctx = _context(raw=_raw({"opus": _record(**changes)}))
    ctx.data["effort"] = {"level": stdin_effort}
    text = _model(ctx)
    assert f"O:gpt-6-astra@{expected}" in text
    assert text.count("@") == 1
    _, stream = render_segments(ctx, ["model"])
    assert (fmt.YELLOW in stream[0]) is (changes.get("wire") == "dropped")


def test_model_alternative_names_observed_backend():
    raw = _raw({"opus": _record(client_model="gpt-6.1-sol", mapped_model="openai/gpt-6.1-sol")})
    raw["runtime"]["model_alternatives"] = {"opus": {"gpt-6.1-sol": "openai/gpt-6.1-sol"}}
    ctx = _context(raw=raw)
    ctx.data["model"]["id"] = "gpt-6.1-sol"
    with patch.dict("os.environ", {"ANTHROPIC_CUSTOM_HEADERS": "X-Forge-Model-Tier: opus"}):
        assert "O:gpt-6.1-sol@high<-xhigh" in _model(ctx)
        assert "(stale)" not in _model(ctx)


@pytest.mark.parametrize("change", ["model", "route"])
def test_same_effort_model_or_route_switch_is_stale(change):
    raw = _raw()
    ctx = _context(raw=raw)
    if change == "model":
        ctx.data["model"]["id"] = "claude-opus-4-6"
    else:
        ctx.runtime.tier_mappings["opus"] = "openai/gpt-6.1-sol"
    assert "O:gpt-6-astra@high (stale)" in _model(ctx)


def test_transport_suffix_alone_is_not_stale():
    raw = _raw({"opus": _record(client_model="claude-opus-5-5[1m]")})
    assert "(stale)" not in _model(_context(raw=raw))


def test_old_stdin_without_effort_does_not_claim_a_level_change():
    ctx = _context(raw=_raw())
    del ctx.data["effort"]
    assert "high<-xhigh" in _model(ctx)
    assert "(stale)" not in _model(ctx)


def test_unknown_route_truth_does_not_invalidate_an_observed_backend():
    raw = _raw(wire_shape=None)
    raw["runtime"]["tier_mappings"]["opus"] = "different-model"
    text = _model(_context(raw=raw))
    assert "O:gpt-6-astra@high<-xhigh" in text
    assert "(stale)" not in text


def test_passthrough_observation_uses_request_model_despite_advertised_mapping():
    raw = _raw(
        {
            "opus": _record(
                client_model="claude-opus-4-6",
                mapped_model="claude-opus-4-6",
                source="passthrough",
                applied="xhigh",
                wire="output_config.effort",
            )
        },
        wire_shape="anthropic_passthrough",
    )
    raw["runtime"]["tier_mappings"]["opus"] = "claude-opus-5-5"
    ctx = _context(raw=raw)
    ctx.data["model"]["id"] = "claude-opus-4-6[1m]"
    assert "O:claude-opus-4-6@xhigh" in _model(ctx)
    assert "(stale)" not in _model(ctx)


def test_explicit_backend_observation_is_not_compared_to_tier_default():
    raw = _raw({"sonnet": _record(tier="sonnet", client_model="custom/model", mapped_model="custom/actual")})
    ctx = _context(raw=raw)
    ctx.data["model"]["id"] = "custom/model"
    assert ctx.route.model is None
    assert "S:actual@high<-xhigh" in _model(ctx)
    assert "(stale)" not in _model(ctx)


@pytest.mark.parametrize("kind", ["empty", "old", "fallback", "malformed"])
def test_no_supported_launch_observation_is_unknown(kind):
    raw = _raw({})
    if kind == "old":
        del raw["runtime"]["effort"]
    elif kind == "malformed":
        raw["runtime"]["effort"] = {"opus": {"applied": "high"}}
    elif kind == "fallback":
        raw = _raw()
    ctx = _context(raw=raw, authoritative=kind != "fallback")
    assert "O:gpt-6-astra@unknown" in _model(ctx)


def test_other_tier_observation_does_not_annotate_active_tier():
    raw = _raw({"sonnet": _record(tier="sonnet")})
    assert "O:gpt-6-astra@unknown" in _model(_context(raw=raw))


def test_runtime_truth_retains_complete_records_and_valid_empty_map():
    record = _record()
    truth = ProxyRuntimeTruth(_raw({"opus": record}))
    assert truth.has_effort_observations
    assert truth.effort == {"opus": record}
    assert ProxyRuntimeTruth(_raw({})).has_effort_observations


@pytest.mark.parametrize("bad", [None, [], "bad", {"other": _record()}, {"opus": {}}, {"opus": []}])
def test_invalid_effort_map_is_unsupported(bad):
    raw = _raw()
    raw["runtime"]["effort"] = bad
    truth = ProxyRuntimeTruth(raw)
    assert not truth.has_effort_observations
    assert truth.effort == {}


@pytest.mark.parametrize(
    "changes",
    [
        {"tier": "sonnet"},
        {"opt_in": 1},
        {"client_applicable": None},
        {"requested": []},
        {"applied": "\x1b[31mhigh"},
        {"mapped_model": "bad\nmodel"},
        {"source": "guessed"},
        {"wire": {}},
        {"wire": None},
        {"wire": "dropped"},
        {"applied": None},
        {"supported": "high"},
        {"supported": [False]},
        {"note": "\x1b[0m"},
    ],
)
def test_one_malformed_record_invalidates_entire_effort_map(changes):
    raw = _raw({"opus": _record(**changes), "sonnet": _record(tier="sonnet")})
    truth = ProxyRuntimeTruth(raw)
    assert not truth.has_effort_observations
    assert truth.effort == {}


@pytest.mark.parametrize("shape", [None, {}, "unknown"])
def test_unknown_wire_shape_does_not_predict_route(shape):
    assert _context(raw=_raw(wire_shape=shape)).route.model is None


@pytest.mark.parametrize(
    ("enabled", "header", "query"),
    [
        (True, "X-Forge-Launch: run_0123456789ab", "?forge_launch=run_0123456789ab"),
        (False, "X-Forge-Launch: run_0123456789ab", ""),
        (True, "X-Forge-Launch: invalid&other=yes", ""),
        (
            True,
            "X-Forge-Launch: run_0123456789ab\nX-Forge-Launch: run_abcdef012345",
            "",
        ),
        (True, "", ""),
    ],
)
def test_launch_query_uses_existing_single_fetch(monkeypatch, enabled, header, query):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://localhost:8090/v1")
    monkeypatch.setenv("ANTHROPIC_CUSTOM_HEADERS", header)
    response = MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps(_raw()).encode()
    with patch("urllib.request.urlopen", return_value=response) as fetch:
        is_proxy, truth, authoritative = detect_proxy(include_effort=enabled)
    assert is_proxy and authoritative and truth is not None
    assert fetch.call_count == 1
    assert fetch.call_args.args == (f"http://localhost:8090/{query}",)
    assert truth.effort == ({"opus": _record()} if query else {})
    assert truth.has_effort_observations is bool(query)


@pytest.mark.parametrize(
    ("segments", "expected_queries"),
    [(["path"], []), (["cost"], [False]), (["model"], [True])],
)
def test_model_free_layout_does_no_effort_work(segments, expected_queries):
    config = RuntimeConfig(statusline=StatusLineConfig(segments=segments))
    with (
        patch("forge.runtime_config.get_runtime_config", return_value=config),
        patch(
            "forge.cli.statusline.sources.detect_proxy",
            return_value=(False, None, False),
        ) as proxy,
        patch("forge.cli.statusline.sources.discover_session", return_value=(None, False)),
        patch(
            "forge.cli.statusline.context.read_projected_model_tier",
            side_effect=AssertionError("route not needed"),
        ),
    ):
        result = CliRunner().invoke(status_line, input=json.dumps({"workspace": {"current_dir": "/tmp"}}))
    assert result.exit_code == 0, result.output
    assert [call.kwargs["include_effort"] for call in proxy.call_args_list] == expected_queries
