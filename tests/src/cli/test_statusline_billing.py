"""End-to-end billing-aware cost rendering through status_line().

cost_mode (declare) + ANTHROPIC_API_KEY (heuristic) decide whether the cost
segment shows real dollars (API billing) or the 5h quota (subscription, where
dollars are a phantom figure). ANTHROPIC_API_KEY is controlled via the CliRunner
env so these are deterministic regardless of the dev's environment.
"""

from __future__ import annotations

import contextlib
import json
from unittest.mock import patch

from click.testing import CliRunner

from forge.cli import status_line as sl
from forge.cli.status_line import _ANSI_RE, TranscriptStats, status_line
from forge.runtime_config import RuntimeConfig, StatusLineConfig

_BASE = {
    "workspace": {"current_dir": "/tmp/demo"},
    "model": {"display_name": "Opus 4.6"},
    "context_window": {
        "context_window_size": 200000,
        "used_percentage": 12,
        "current_usage": {"input_tokens": 1000},
    },
}
COST = {**_BASE, "cost": {"total_cost_usd": 0.42, "total_duration_ms": 185000}}
COST_RL = {**COST, "rate_limits": {"five_hour": {"used_percentage": 23}}}


def _render(fixture, *, cost_mode="auto", api_key=False, segments=None):
    sl_kwargs: dict = {"cost_mode": cost_mode}
    if segments is not None:
        sl_kwargs["segments"] = segments
    cfg = RuntimeConfig(statusline=StatusLineConfig(**sl_kwargs))
    env = {"FORGE_STATUS_TRUNCATE": "0", "ANTHROPIC_API_KEY": "sk-test" if api_key else None}
    runner = CliRunner()
    with contextlib.ExitStack() as es:
        es.enter_context(patch.object(sl, "_get_terminal_width", return_value=200))
        es.enter_context(patch.object(sl, "detect_proxy", return_value=(False, None, False)))
        es.enter_context(patch.object(sl, "discover_session", return_value=(None, False)))
        es.enter_context(patch.object(sl, "get_git_branch", return_value=None))
        es.enter_context(patch.object(sl, "_cached_scan_transcript", return_value=TranscriptStats()))
        es.enter_context(patch("forge.runtime_config.get_runtime_config", return_value=cfg))
        res = runner.invoke(status_line, input=json.dumps(fixture), env=env)
    assert res.exit_code == 0, res.output
    return _ANSI_RE.sub("", res.output)


class TestBillingModeRendering:
    def test_api_mode_shows_dollars(self):
        visible = _render(COST, cost_mode="api")
        assert "$0.42" in visible
        assert "RL:" not in visible

    def test_subscription_shows_quota_not_dollars(self):
        visible = _render(COST_RL, cost_mode="subscription")
        assert "RL:23%" in visible
        assert "0.42" not in visible  # phantom dollars hidden

    def test_auto_with_api_key_shows_dollars(self):
        visible = _render(COST, cost_mode="auto", api_key=True)
        assert "$0.42" in visible

    def test_auto_without_key_shows_quota(self):
        visible = _render(COST_RL, cost_mode="auto", api_key=False)
        assert "RL:23%" in visible
        assert "0.42" not in visible

    def test_auto_without_key_no_rate_limits_hedges_with_approx(self):
        visible = _render(COST, cost_mode="auto", api_key=False)
        assert "\u2248$0.42" in visible


class TestRateLimitsSuppression:
    def test_rate_limits_suppressed_when_cost_shows_quota(self):
        # subscription + both cost and rate_limits enabled -> the quota shows once
        # (via cost); the standalone rate_limits segment suppresses itself.
        visible = _render(COST_RL, cost_mode="subscription", segments=["model", "cost", "rate_limits"])
        assert visible.count("RL:") == 1

    def test_rate_limits_shown_when_cost_absent(self):
        # No cost segment -> nothing else shows the quota, so rate_limits renders.
        visible = _render(COST_RL, cost_mode="subscription", segments=["model", "rate_limits"])
        assert "RL:23%" in visible

    def test_api_mode_keeps_both_cost_and_rate_limits(self):
        # In API mode cost shows dollars and rate_limits shows quota — both useful.
        visible = _render(COST_RL, cost_mode="api", segments=["model", "cost", "rate_limits"])
        assert "$0.42" in visible
        assert "RL:23%" in visible
