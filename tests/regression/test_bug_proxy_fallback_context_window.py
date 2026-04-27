"""Regression: proxy registry fallback returns wrong context window.

Bug: When the proxy's GET / health check fails, detect_proxy() falls back
to the proxy registry but returns empty runtime: {}. This makes
active_context_window None, so get_effective_context_window() falls through
to Claude Code's cached data, which may reflect the auto-compact window (e.g.,
400K for GPT-5.5) rather than the proxy's actual model context window.

Root cause: The registry fallback in detect_proxy() did not compute
tier mappings or context windows from the proxy config file.

Fix: Enrich the registry fallback by loading proxy.yaml and computing
context windows from the model catalog (best-effort, same data as GET /).

Affected file: src/forge/cli/status_line.py
"""

import pytest

from forge.cli.status_line import ProxyRuntimeTruth, get_effective_context_window

pytestmark = pytest.mark.regression


def test_empty_runtime_has_no_context_window():
    """The pre-fix condition: empty runtime means active_context_window is None."""
    runtime = ProxyRuntimeTruth({"is_proxy": True, "proxy": {}, "runtime": {}, "tiers": {}})
    assert runtime.active_context_window is None


def test_enriched_runtime_has_correct_context_window():
    """The post-fix condition: enriched runtime carries the catalog context window."""
    runtime = ProxyRuntimeTruth(
        {
            "is_proxy": True,
            "proxy": {},
            "runtime": {
                "tier_mappings": {"sonnet": "gpt-4.1"},
                "context_windows": {"sonnet": 1_000_000},
                "active_tier": "sonnet",
                "active_context_window": 1_000_000,
            },
            "tiers": {},
        }
    )
    assert runtime.active_context_window == 1_000_000


def test_enriched_runtime_wins_over_claude_code_cached_data():
    """get_effective_context_window prefers proxy runtime over Claude Code's cached data."""
    enriched_runtime = ProxyRuntimeTruth(
        {
            "is_proxy": True,
            "proxy": {},
            "runtime": {"active_context_window": 1_000_000},
            "tiers": {},
        }
    )
    claude_data = {"context_window": {"context_window_size": 400_000, "current_usage": {}}}

    result = get_effective_context_window(claude_data, enriched_runtime, {"context_window": 400_000})
    assert result == 1_000_000


def test_empty_runtime_falls_through_to_claude_code_data():
    """Without enrichment, resolution falls through to Claude Code's cached (wrong) value."""
    empty_runtime = ProxyRuntimeTruth({"is_proxy": True, "proxy": {}, "runtime": {}, "tiers": {}})

    result = get_effective_context_window({}, empty_runtime, {"context_window": 400_000})
    assert result == 400_000
