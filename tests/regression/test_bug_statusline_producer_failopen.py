"""Regression: a producer raising crashed the whole status line (exit 1, no output).

Bug: ``render_segments`` called each producer without isolation, and
``_produce_cache_hit`` indexed ``runtime.raw["metrics"]`` without an isinstance
guard (unlike ``_produce_spend_cap``). A proxy ``GET /`` payload with a non-dict
``metrics`` raised ``AttributeError`` out of ``render_segments`` -> the full
``forge status-line`` exited non-zero with empty output, violating the
always-exit-0 / fail-open contract for a system-boundary (proxy HTTP) payload.

Root cause / fix: ``src/forge/cli/statusline/registry.py`` — isinstance guard in
``_produce_cache_hit`` plus a per-producer ``try/except`` in ``render_segments``
that degrades the failing segment to absent and debug-logs.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from forge.cli import status_line as sl
from forge.cli.status_line import ProxyRuntimeTruth, status_line
from forge.cli.statusline.context import RenderContext
from forge.cli.statusline.registry import render_segments
from forge.runtime_config import RuntimeConfig, StatusLineConfig

pytestmark = pytest.mark.regression


def _ctx(raw):
    return RenderContext(
        data={"workspace": {"current_dir": "/tmp/d"}, "model": {"id": "claude-opus-4-8", "display_name": "Opus"}},
        is_proxy=True,
        runtime=ProxyRuntimeTruth(raw),
        is_proxy_authoritative=True,
        manifest=None,
        is_session_authoritative=False,
        config=RuntimeConfig(),
    )


def test_non_dict_metrics_does_not_crash_cache_hit():
    ctx = _ctx({"is_proxy": True, "metrics": ["not", "a", "dict"], "proxy": {"template": "x"}})
    where, stream = render_segments(ctx, ["cache_hit"])  # must not raise
    assert (where, stream) == ([], [])  # segment degraded to absent


def test_failing_producer_degrades_not_whole_line():
    # A non-dict metrics breaks the cache_hit producer; path + model must still render.
    ctx = _ctx({"is_proxy": True, "metrics": "BROKEN", "proxy": {"template": "x"}})
    where, stream = render_segments(ctx, ["path", "cache_hit", "model"])
    assert len(where) == 1  # path
    assert len(stream) == 1  # model (cache_hit dropped)


def test_full_status_line_exits_zero_on_malformed_metrics():
    # The exact repro: a fresh proxy GET / with a non-dict metrics payload.
    runtime = ProxyRuntimeTruth(
        {
            "is_proxy": True,
            "metrics": "BROKEN",
            "proxy": {"template": "x"},
            "runtime": {"active_tier": "opus", "tier_mappings": {"opus": "o3"}},
        }
    )
    cfg = RuntimeConfig(statusline=StatusLineConfig(segments=["path", "model", "cache_hit"]))
    fixture = {
        "workspace": {"current_dir": "/tmp/d"},
        "model": {"id": "claude-opus-4-8", "display_name": "Opus"},
        "context_window": {"context_window_size": 200000, "used_percentage": 5, "current_usage": {"input_tokens": 100}},
    }
    with (
        patch.object(sl, "_get_terminal_width", return_value=200),
        patch.object(sl, "detect_proxy", return_value=(True, runtime, True)),
        patch.object(sl, "discover_session", return_value=(None, False)),
        patch.object(sl, "get_git_branch", return_value=None),
        patch("forge.runtime_config.get_runtime_config", return_value=cfg),
    ):
        result = CliRunner().invoke(status_line, input=json.dumps(fixture), env={"FORGE_STATUS_TRUNCATE": "0"})
    assert result.exit_code == 0  # fail-open: degraded, not crashed
    # path + model still render (proxy mode shows the tier display 'o3', not 'Opus'); cache_hit degraded.
    assert "/tmp/d" in result.output and "o3" in result.output
