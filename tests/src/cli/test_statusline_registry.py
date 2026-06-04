"""Golden no-op guard + segment-registry tests for the status line.

The GOLDEN snapshots freeze the exact stdout of ``status_line()`` for a set of
representative fixtures, captured BEFORE the Phase 1 registry refactor. The
refactor must keep these byte-identical: the registry only reorganizes how the
five category lists are produced, not what they contain. Environment-dependent
inputs (proxy, session, git, terminal width, transcript) are patched so the
output is a pure function of stdin + the patched returns.
"""

from __future__ import annotations

import contextlib
import json
from unittest.mock import patch

from click.testing import CliRunner

from forge.cli import status_line as sl
from forge.cli.status_line import ProxyRuntimeTruth, TranscriptStats, status_line
from forge.cli.statusline.context import RenderContext
from forge.cli.statusline.names import DEFAULT_ORDER, SEGMENT_NAMES
from forge.cli.statusline.registry import SEGMENTS, render_segments, resolve_order
from forge.runtime_config import RuntimeConfig


def _render(fixture, *, proxy=None, session=None, stats=None):
    """Render status_line() with all environment-dependent inputs pinned."""
    runner = CliRunner()
    with contextlib.ExitStack() as es:
        es.enter_context(patch.object(sl, "_get_terminal_width", return_value=200))
        es.enter_context(patch.object(sl, "detect_proxy", return_value=(proxy or (False, None, False))))
        es.enter_context(patch.object(sl, "discover_session", return_value=(session or (None, False))))
        es.enter_context(patch.object(sl, "get_git_branch", return_value=None))
        es.enter_context(patch.object(sl, "_cached_scan_transcript", return_value=(stats or TranscriptStats())))
        # Pin API billing so cost_mode=auto is deterministic regardless of the
        # dev's ANTHROPIC_API_KEY — the snapshots are the API ($) view.
        res = runner.invoke(
            status_line,
            input=json.dumps(fixture),
            env={"FORGE_STATUS_TRUNCATE": "0", "ANTHROPIC_API_KEY": "sk-ant-test"},
        )
    assert res.exit_code == 0, res.output
    return res.output


# --- Fixtures -------------------------------------------------------------

FIXTURE_MINIMAL = {
    "workspace": {"current_dir": "/tmp/demo"},
    "model": {"display_name": "Opus 4.6"},
    "context_window": {
        "context_window_size": 200000,
        "used_percentage": 12,
        "current_usage": {"input_tokens": 12000, "cache_read_input_tokens": 2000, "cache_creation_input_tokens": 5000},
    },
}

FIXTURE_FULL = {
    "workspace": {"current_dir": "/tmp/demo"},
    "model": {"display_name": "Sonnet 4.6"},
    "context_window": {
        "context_window_size": 1000000,
        "used_percentage": 47,
        "total_input_tokens": 28000,
        "total_output_tokens": 17500,
        "current_usage": {"input_tokens": 12000, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
    },
    "cost": {"total_cost_usd": 0.42, "total_duration_ms": 185000, "total_lines_added": 12, "total_lines_removed": 3},
}

FIXTURE_SESSION = {
    "workspace": {"current_dir": "/tmp/demo"},
    "model": {"display_name": "Opus 4.6"},
    "context_window": {
        "context_window_size": 200000,
        "used_percentage": 30,
        "current_usage": {"input_tokens": 60000, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
    },
}
SESSION_MANIFEST = (
    {
        "name": "child-sess",
        "intent": {"verification": {"max_iterations": 50}},
        "confirmed": {
            "derivation": {"lineage": ["parent-sess"]},
            "verification": {"iterations": 3, "last_result": "running"},
            "is_sandboxed": True,
        },
    },
    True,
)

FIXTURE_PROXY = {
    "workspace": {"current_dir": "/tmp/demo"},
    "model": {"display_name": "Opus"},
    "context_window": {
        "context_window_size": 200000,
        "used_percentage": 20,
        "current_usage": {"input_tokens": 40000, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
    },
}
PROXY_RUNTIME = (
    True,
    ProxyRuntimeTruth(
        {
            "is_proxy": True,
            "proxy": {
                "proxy_id": "p1",
                "template": "litellm-openai",
                "port": 8085,
                "base_url": "http://localhost:8085",
            },
            "runtime": {
                "tier_mappings": {"haiku": "gpt-4o-mini", "sonnet": "gpt-4o", "opus": "o3"},
                "context_windows": {"haiku": 128000, "sonnet": 128000, "opus": 200000},
                "active_tier": "sonnet",
                "active_context_window": 128000,
            },
            "tiers": {},
            "metrics": {"costs": {"total_usd": 0.0123}},
        }
    ),
    True,
)

# --- Golden snapshots (frozen pre-refactor; must not change) --------------

GOLDEN_MINIMAL = "\x1b[0m\x1b[32;1m/tmp/demo\x1b[0m\xa0\x1b[90m|\x1b[0m\xa0\x1b[38;5;75m[Opus\xa04.6]\x1b[0m\xa0\x1b[38;5;115m--------\xa012%/\x1b[1m200K\x1b[0m\x1b[0m\xa0\xa0\xa0\n"

GOLDEN_FULL = "\x1b[0m\x1b[32;1m/tmp/demo\x1b[0m\xa0\x1b[90m|\x1b[0m\xa0\x1b[38;5;69m[Sonnet\xa04.6\xa0(1M)]\x1b[0m\xa0\x1b[38;5;179m###-----\xa047%/\x1b[1m1M\x1b[0m\xa0\x1b[90m|\x1b[0m\xa0\x1b[38;5;145m$0.42\x1b[0m\xa0\x1b[38;5;145m3m\x1b[0m\xa0\x1b[90m|\x1b[0m\xa0\x1b[38;5;28m+12\x1b[0m\x1b[90m/\x1b[0m\x1b[38;5;124m-3\x1b[0m\xa0\x1b[90m|\x1b[0m\xa0\x1b[2min:\x1b[0m\x1b[38;5;145m28.0K\x1b[0m\xa0\x1b[2mout:\x1b[0m\x1b[38;5;145m17.5K\x1b[0m\xa0\x1b[90m|\x1b[0m\xa0\x1b[94mTHINK\x1b[0m\x1b[0m\xa0\xa0\xa0\n"

GOLDEN_SESSION = "\x1b[0m\x1b[32;1m/tmp/demo\x1b[0m\xa0\x1b[90m|\x1b[0m\xa0\x1b[38;5;139mparent-sess\xa0>\xa0child-sess\x1b[0m\xa0\x1b[90m|\x1b[0m\xa0\x1b[38;5;75m[Opus\xa04.6]\x1b[0m\xa0\x1b[38;5;150m##------\xa030%/\x1b[1m200K\x1b[0m\xa0\x1b[90m|\x1b[0m\xa0LOOP\xa03/50\xa0\x1b[90m|\x1b[0m\xa0SC\x1b[0m\xa0\xa0\xa0\n"

GOLDEN_PROXY = "\x1b[0m\x1b[32;1m/tmp/demo\x1b[0m\xa0\x1b[90m|\x1b[0m\xa0\x1b[38;5;60mlitellm-openai\x1b[0m\xa0[\x1b[38;5;75mO:o3\x1b[0m\xa0\x1b[38;5;69mS:gpt-4o\x1b[0m\xa0\x1b[38;5;67mH:gpt-4o-mini\x1b[0m]\xa0\x1b[38;5;150m##------\xa031%/\x1b[1m128K\x1b[0m\xa0\x1b[90m|\x1b[0m\xa0\x1b[38;5;145m~$0.01\x1b[0m\x1b[0m\xa0\xa0\xa0\n"


class TestGoldenNoOpGuard:
    """The registry refactor must preserve byte-identical output (default config)."""

    def test_minimal_direct(self):
        assert _render(FIXTURE_MINIMAL) == GOLDEN_MINIMAL

    def test_full_direct_metrics_with_thinking(self):
        assert _render(FIXTURE_FULL, stats=TranscriptStats(has_thinking=True)) == GOLDEN_FULL

    def test_session_breadcrumb_loop_sidecar(self):
        assert _render(FIXTURE_SESSION, session=SESSION_MANIFEST) == GOLDEN_SESSION

    def test_proxy_template_and_tier_display(self):
        assert _render(FIXTURE_PROXY, proxy=PROXY_RUNTIME) == GOLDEN_PROXY


def _ctx(fixture):
    """Build a RenderContext for direct (non-CLI) registry tests."""
    return RenderContext(
        data=fixture,
        is_proxy=False,
        runtime=None,
        is_proxy_authoritative=False,
        manifest=None,
        is_session_authoritative=False,
        config=RuntimeConfig(),
    )


class TestRegistryInvariants:
    """The registry's names and resolution stay consistent with the allowlist."""

    def test_allowlist_equals_producers(self):
        # SEGMENT_NAMES must be EXACTLY the renderable set: every allowlisted
        # name has a producer, and every producer is allowlisted. This prevents
        # `forge config set` from accepting a segment that renders nothing.
        assert {seg.name for seg in SEGMENTS} == set(SEGMENT_NAMES)

    def test_default_order_segments_all_implemented(self):
        names = {seg.name for seg in SEGMENTS}
        assert all(name in names for name in DEFAULT_ORDER)

    def test_resolve_empty_is_default_order(self):
        assert resolve_order([]) == list(DEFAULT_ORDER)

    def test_resolve_drops_names_without_producer(self):
        # Renderer degrades silently (set/edit is the strict allowlist gate).
        assert resolve_order(["path", "bogus", "model"]) == ["path", "model"]

    def test_resolve_all_dropped_falls_back_to_default(self):
        # Only reachable via a hand-edited / newer-Forge config: a non-empty list
        # of not-yet-implemented (reserved) names must not blank the bar. spend_cap
        # is the lone reserved name (Phase 5); update this if it gains a producer.
        assert resolve_order(["spend_cap"]) == list(DEFAULT_ORDER)

    def test_resolve_preserves_user_order(self):
        assert resolve_order(["model", "path"]) == ["model", "path"]


class TestLazyContext:
    """Customization's payoff: disabled segments do zero work."""

    def test_minimal_segments_skip_transcript_and_git(self):
        ctx = _ctx(FIXTURE_MINIMAL)
        with (
            patch.object(sl, "_cached_scan_transcript") as scan,
            patch.object(sl, "get_git_branch") as git,
        ):
            where, stream = render_segments(ctx, ["path", "model"])
        scan.assert_not_called()
        git.assert_not_called()
        assert len(where) == 1  # path
        assert len(stream) == 1  # model

    def test_default_order_scans_transcript_once(self):
        # Control: tokens + think both read transcript_stats, but the
        # cached_property collapses that to a single scan.
        ctx = _ctx(FIXTURE_MINIMAL)
        with patch.object(sl, "_cached_scan_transcript", return_value=TranscriptStats()) as scan:
            render_segments(ctx, list(DEFAULT_ORDER))
        scan.assert_called_once()

    def test_branch_segment_triggers_git(self):
        # Control: the branch segment (not in [path, model]) does call git.
        ctx = _ctx(FIXTURE_MINIMAL)
        with patch.object(sl, "get_git_branch", return_value="main") as git:
            render_segments(ctx, ["path", "branch"])
        git.assert_called_once()
