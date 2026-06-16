"""Phase 4: Forge-unique opt-in segments (supervisor, policy, audit, drift).

These read state nothing else in the status line surfaces — session policy
posture (from the manifest, *effective* intent+overrides) and proxy audit/routing
posture (from GET / runtime truth). All four are opt-in: absent from
``DEFAULT_ORDER`` and rendered only when listed in ``statusline.segments``.

Tests cover the pure ``format_*`` helpers, the producers' data-shape handling via
``render_segments``, and the headline acceptance: a ``%supervisor suspend``
override flips the segment without mutating intent (we read effective state).
"""

from __future__ import annotations

import contextlib
import json
from unittest.mock import patch

from click.testing import CliRunner

from forge.cli import status_line as sl
from forge.cli.status_line import (
    _ANSI_RE,
    METRICS_COLOR,
    RED,
    YELLOW,
    ProxyRuntimeTruth,
    TranscriptStats,
    explicit_tier_from_model,
    format_audit,
    format_drift,
    format_forge_cost,
    format_launch,
    format_policy,
    format_spend_cap,
    format_supervisor,
    status_line,
)
from forge.cli.statusline.context import RenderContext
from forge.cli.statusline.names import DEFAULT_ORDER, SEGMENT_NAMES
from forge.cli.statusline.registry import render_segments
from forge.core.ops.usage_summary import SupervisorHealth
from forge.core.usage.ledger import UsageEvent, log_usage_event
from forge.runtime_config import RuntimeConfig, StatusLineConfig

# --- Builders -------------------------------------------------------------

_DATA = {"workspace": {"current_dir": "/tmp/demo"}, "model": {"id": "claude-opus-4-8", "display_name": "Opus"}}


def _plain(text):
    """Strip ANSI so label/value pairs (``{DIM}pol:{RESET}{color}TDD``) match."""
    return _ANSI_RE.sub("", text)


def _ctx(*, data=None, manifest=None, is_proxy=False, runtime=None):
    return RenderContext(
        data=data if data is not None else dict(_DATA),
        is_proxy=is_proxy,
        runtime=runtime,
        is_proxy_authoritative=is_proxy,
        manifest=manifest,
        is_session_authoritative=manifest is not None,
        config=RuntimeConfig(),
    )


def _proxy(raw):
    return ProxyRuntimeTruth(raw)


def _stream(ctx, segments):
    """Return the ANSI-stripped stream-bucket output of a render."""
    _where, stream = render_segments(ctx, segments)
    return [_plain(s) for s in stream]


def _seed_supervisor(**kw: object) -> None:
    """Append one usage event for the ``planner`` session (defaults: a supervisor success)."""
    base: dict[str, object] = {
        "run_id": "r",
        "root_run_id": "r",
        "runtime": "claude_code",
        "command": "supervisor",
        "status": "success",
        "session": "planner",
    }
    base.update(kw)
    log_usage_event(UsageEvent(**base))  # type: ignore[arg-type]


# --- Pure format helpers --------------------------------------------------


class TestFormatHelpers:
    def test_supervisor_active_vs_suspended(self):
        assert "SUP" in format_supervisor(suspended=False)
        assert "susp" not in format_supervisor(suspended=False)
        assert "SUP(susp)" in format_supervisor(suspended=True)

    def test_supervisor_health_none_is_byte_identical(self):
        # The optional health params must not perturb the bare posture: zero failures
        # (the default, the fail-open None, and an empty streak) render today's token.
        for suspended, enabled in [(False, True), (True, True), (False, False)]:
            bare = format_supervisor(suspended=suspended, enabled=enabled)
            assert format_supervisor(suspended=suspended, enabled=enabled, recent_failures=0) == bare
            assert format_supervisor(suspended=suspended, enabled=enabled, recent_failures=0, last_kind=None) == bare

    def test_supervisor_health_suffix_and_tiers(self):
        # >0 failures append `!N <kind>`, tiered like format_spend_cap (yellow 1-2, red >=3).
        # Asserted on the active posture (METRICS_COLOR) so the tier color can only be the suffix.
        red3 = format_supervisor(suspended=False, recent_failures=3, last_kind="timeout")
        assert _plain(red3) == "SUP!3 timeout" and RED in red3
        yellow2 = format_supervisor(suspended=False, recent_failures=2, last_kind="timeout")
        assert _plain(yellow2) == "SUP!2 timeout" and YELLOW in yellow2
        err = format_supervisor(suspended=False, recent_failures=4, last_kind="error")
        assert _plain(err) == "SUP!4 error" and RED in err

    def test_supervisor_health_suffix_is_posture_independent(self):
        # The suffix attaches to whatever posture renders -- suspended/off keep their
        # prior fail-open history (they emit no new events to reset it).
        susp = format_supervisor(suspended=True, recent_failures=2, last_kind="timeout")
        assert _plain(susp) == "SUP(susp)!2 timeout"
        off = format_supervisor(suspended=False, enabled=False, recent_failures=4, last_kind="error")
        assert _plain(off) == "SUP(off)!4 error"

    def test_policy_known_bundles_abbreviated(self):
        assert "pol:TDD" in _plain(format_policy(["tdd"]) or "")
        assert "pol:TDD+STD" in _plain(format_policy(["tdd", "coding_standards"]) or "")

    def test_policy_unknown_bundle_uppercased(self):
        assert "pol:CUSTOM" in _plain(format_policy(["custom"]) or "")

    def test_policy_empty_or_garbage_is_none(self):
        assert format_policy([]) is None
        assert format_policy([1, None]) is None  # type: ignore[list-item]

    def test_audit_modes(self):
        assert "aud:pass" in _plain(format_audit("passthrough", thinking_preserved=True))
        assert "aud:inspect" in _plain(format_audit("inspect", thinking_preserved=True))
        assert "aud:override" in _plain(format_audit("override", thinking_preserved=True))

    def test_audit_lossy_only_when_intercepting_translated_wire(self):
        # inspect/override on a non-preserving wire -> lossy note; passthrough never.
        assert "(lossy)" in _plain(format_audit("inspect", thinking_preserved=False))
        assert "(lossy)" in _plain(format_audit("override", thinking_preserved=False))
        assert "(lossy)" not in _plain(format_audit("inspect", thinking_preserved=True))
        assert "(lossy)" not in _plain(format_audit("passthrough", thinking_preserved=False))

    def test_drift_flags_mismatch_only(self):
        assert format_drift("claude-opus-4-8", "claude-opus-4-8") is None  # aligned -> quiet
        out = format_drift("claude-opus-4-8", "o3")
        assert out is not None and "drift:" in _plain(out) and "!=" in _plain(out)

    def test_launch_direct_omit(self):
        out = format_launch({"routing_mode": "direct", "api_key_source": "omitted_by_config"})
        assert _plain(out or "") == "direct·key:omit"

    def test_launch_proxy_with_id_and_env_key(self):
        out = format_launch({"routing_mode": "proxy", "proxy_id": "p1", "api_key_source": "env"})
        assert _plain(out or "") == "proxy:p1·key:env"

    def test_launch_credential_file_abbreviated(self):
        out = format_launch({"routing_mode": "direct", "api_key_source": "credential_file"})
        assert _plain(out or "") == "direct·key:file"

    def test_launch_proxy_without_id(self):
        out = format_launch({"routing_mode": "proxy", "api_key_source": "none"})
        assert _plain(out or "") == "proxy·key:none"

    def test_launch_empty_is_none(self):
        # Unknown routing_mode + unknown source -> nothing showable.
        assert format_launch({}) is None
        assert format_launch({"routing_mode": "???", "api_key_source": "???"}) is None


# --- Producers via render_segments ---------------------------------------


class TestLaunchProducer:
    def test_renders_from_confirmed_launch(self):
        manifest = {"confirmed": {"launch": {"routing_mode": "direct", "api_key_source": "omitted_by_config"}}}
        out = _stream(_ctx(manifest=manifest), ["launch"])
        assert any("direct·key:omit" in s for s in out)

    def test_ambient_no_manifest_is_hidden(self):
        # Ambient session (no FORGE_SESSION -> manifest None): segment absent.
        assert _stream(_ctx(manifest=None), ["launch"]) == []

    def test_no_launch_block_is_hidden(self):
        assert _stream(_ctx(manifest={"confirmed": {"is_sandboxed": False}}), ["launch"]) == []

    def test_malformed_launch_is_hidden(self):
        # Shape-defensive: a non-dict launch must not raise, just render nothing.
        assert _stream(_ctx(manifest={"confirmed": {"launch": "corrupt"}}), ["launch"]) == []
        assert _stream(_ctx(manifest={"confirmed": "corrupt"}), ["launch"]) == []

    def test_off_by_default(self):
        # Opt-in: not in DEFAULT_ORDER, so a default render never shows it.
        assert "launch" not in DEFAULT_ORDER
        manifest = {"confirmed": {"launch": {"routing_mode": "direct", "api_key_source": "env"}}}
        out = _stream(_ctx(manifest=manifest), list(DEFAULT_ORDER))
        assert not any("key:" in s for s in out)


class TestSupervisorProducer:
    def test_active_supervisor_renders(self):
        manifest = {"intent": {"policy": {"enabled": True, "supervisor": {"suspended": False}}}}
        out = _stream(_ctx(manifest=manifest), ["supervisor"])
        assert any("SUP" in s and "(" not in s for s in out)

    def test_no_supervisor_is_hidden(self):
        # Policy present but no supervisor block -> nothing to show.
        manifest = {"intent": {"policy": {"enabled": True, "bundles": ["tdd"]}}}
        assert _stream(_ctx(manifest=manifest), ["supervisor"]) == []

    def test_no_manifest_is_hidden(self):
        assert _stream(_ctx(manifest=None), ["supervisor"]) == []

    def test_disabled_policy_shows_off_not_active(self):
        # Finding 1: %policy disable sets policy.enabled=False; the hook then exits
        # before running, so the supervisor is configured but NOT watching.
        manifest = {"intent": {"policy": {"enabled": False, "supervisor": {"suspended": False}}}}
        out = _stream(_ctx(manifest=manifest), ["supervisor"])
        assert any("SUP(off)" in s for s in out)

    def test_override_suspends_without_mutating_intent(self):
        # Headline acceptance: a sparse override flips the rendered posture to
        # suspended while raw intent stays active (we read effective state).
        intent = {"policy": {"enabled": True, "supervisor": {"suspended": False}}}
        manifest = {"intent": intent, "overrides": {"policy": {"supervisor": {"suspended": True}}}}
        stream = _stream(_ctx(manifest=manifest), ["supervisor"])
        assert any("SUP(susp)" in s for s in stream)
        # Intent dict is untouched (apply_overrides deepcopies).
        assert intent["policy"]["supervisor"]["suspended"] is False

    def test_health_suffix_from_ledger(self):
        # Acceptance: 3 supervisor timeouts in the ledger -> `SUP!3 timeout` end-to-end.
        for i in (1, 2, 3):
            _seed_supervisor(status="timeout", failure_type="timeout", ts=f"2026-06-16T12:00:0{i}Z")
        manifest = {
            "name": "planner",
            "created_at": "2026-06-16T00:00:00Z",
            "intent": {"policy": {"enabled": True, "supervisor": {"suspended": False}}},
        }
        out = _stream(_ctx(manifest=manifest), ["supervisor"])
        assert any("SUP!3 timeout" in s for s in out)

    def test_health_suffix_on_disabled_posture(self):
        # Posture-independent: a disabled supervisor still shows accrued fail-open history.
        manifest = {
            "name": "planner",
            "created_at": "2026-06-16T00:00:00Z",
            "intent": {"policy": {"enabled": False, "supervisor": {"suspended": False}}},
        }
        with patch(
            "forge.core.ops.usage_summary.read_supervisor_health",
            return_value=SupervisorHealth(4, "error", "ts"),
        ):
            out = _stream(_ctx(manifest=manifest), ["supervisor"])
        assert any("SUP(off)!4 error" in s for s in out)

    def test_health_suffix_on_suspended_posture(self):
        intent = {"policy": {"enabled": True, "supervisor": {"suspended": False}}}
        manifest = {
            "name": "planner",
            "created_at": "2026-06-16T00:00:00Z",
            "intent": intent,
            "overrides": {"policy": {"supervisor": {"suspended": True}}},
        }
        with patch(
            "forge.core.ops.usage_summary.read_supervisor_health",
            return_value=SupervisorHealth(2, "timeout", "ts"),
        ):
            out = _stream(_ctx(manifest=manifest), ["supervisor"])
        assert any("SUP(susp)!2 timeout" in s for s in out)

    def test_raising_reader_degrades_to_posture_only(self):
        # Fail-open differs from forge_cost: the throttle swallows the read error ->
        # supervisor_health is None -> the POSTURE still renders, just without a suffix
        # (the posture is manifest-derived, not ledger-derived).
        manifest = {
            "name": "planner",
            "created_at": "2026-06-16T00:00:00Z",
            "intent": {"policy": {"enabled": True, "supervisor": {"suspended": False}}},
        }
        with patch(
            "forge.core.ops.usage_summary.read_supervisor_health",
            side_effect=RuntimeError("ledger boom"),
        ):
            out = _stream(_ctx(manifest=manifest), ["supervisor"])
        assert any("SUP" in s for s in out)  # posture survives the read error
        assert not any("!" in s for s in out)  # but no health suffix


class TestPolicyProducer:
    def test_effective_bundles_render(self):
        manifest = {"intent": {"policy": {"enabled": True, "bundles": ["tdd"]}}}
        out = _stream(_ctx(manifest=manifest), ["policy"])
        assert any("pol:TDD" in s and "(off)" not in s for s in out)

    def test_disabled_policy_marks_bundles_off(self):
        # Finding 1: a disabled policy must not report its bundles as active.
        manifest = {"intent": {"policy": {"enabled": False, "bundles": ["tdd"]}}}
        out = _stream(_ctx(manifest=manifest), ["policy"])
        assert any("pol:TDD(off)" in s for s in out)

    def test_override_clears_bundles_does_not_revive_confirmed(self):
        # Finding 2: an override that empties bundles is authoritative — the stale
        # confirmed bundles must NOT be revived as the active posture.
        manifest = {
            "intent": {"policy": {"enabled": True, "bundles": ["tdd"]}},
            "overrides": {"policy": {"bundles": []}},
            "confirmed": {"policy": {"bundles": ["tdd"]}},
        }
        assert _stream(_ctx(manifest=manifest), ["policy"]) == []

    def test_confirmed_fallback_only_when_no_effective_policy(self):
        # Confirmed is the last-evaluated posture; surface it ONLY when intent
        # carries no policy block at all (not when it explicitly clears bundles).
        manifest = {"intent": {}, "confirmed": {"policy": {"bundles": ["coding_standards"]}}}
        assert any("pol:STD" in s for s in _stream(_ctx(manifest=manifest), ["policy"]))

    def test_no_policy_anywhere_is_hidden(self):
        assert _stream(_ctx(manifest={"intent": {}}), ["policy"]) == []


class TestAuditProducer:
    _RAW = {
        "is_proxy": True,
        "intercept_mode": "inspect",
        "wire_shape": "openai_translated",
        "intercept": {"thinking_blocks_preserved": False},
        "runtime": {"active_tier": "opus", "tier_mappings": {"opus": "o3"}},
        "proxy": {"template": "litellm-openai"},
        "metrics": {},
    }

    def test_proxy_audit_renders_mode_and_lossy(self):
        ctx = _ctx(is_proxy=True, runtime=_proxy(self._RAW))
        out = _stream(ctx, ["audit"])
        assert any("aud:inspect" in s and "(lossy)" in s for s in out)

    def test_passthrough_preserves_thinking(self):
        raw = {**self._RAW, "intercept_mode": "passthrough", "intercept": {"thinking_blocks_preserved": True}}
        out = _stream(_ctx(is_proxy=True, runtime=_proxy(raw)), ["audit"])
        assert any("aud:pass" in s and "(lossy)" not in s for s in out)

    def test_direct_mode_hidden(self):
        assert _stream(_ctx(is_proxy=False, runtime=None), ["audit"]) == []


class TestDriftProducer:
    def test_mismatch_renders(self):
        raw = {
            "is_proxy": True,
            "runtime": {"active_tier": "opus", "tier_mappings": {"opus": "o3"}},
            "proxy": {"template": "litellm-openai"},
        }
        ctx = _ctx(is_proxy=True, runtime=_proxy(raw))
        assert any("drift:" in s for s in _stream(ctx, ["drift"]))

    def test_aligned_is_quiet(self):
        raw = {
            "is_proxy": True,
            "runtime": {"active_tier": "opus", "tier_mappings": {"opus": "claude-opus-4-8"}},
            "proxy": {"template": "anthropic-passthrough"},
        }
        ctx = _ctx(is_proxy=True, runtime=_proxy(raw))
        assert _stream(ctx, ["drift"]) == []

    def test_no_model_id_avoids_false_positive(self):
        # display_name only (no model.id) -> can't normalize -> hidden, not a guess.
        raw = {"is_proxy": True, "runtime": {"active_tier": "opus", "tier_mappings": {"opus": "o3"}}}
        ctx = _ctx(data={"workspace": {}, "model": {"display_name": "Opus"}}, is_proxy=True, runtime=_proxy(raw))
        assert _stream(ctx, ["drift"]) == []

    def test_explicit_tier_beats_default_no_false_positive(self):
        # Finding 3: active_tier is the proxy *default* (sonnet here), but routing
        # prefers the explicit tier in the model name (opus). The opus request
        # routes to the opus backend == model.id, so there is NO drift — comparing
        # against the sonnet default would have false-positived.
        raw = {
            "is_proxy": True,
            "runtime": {
                "active_tier": "sonnet",
                "tier_mappings": {"sonnet": "claude-sonnet-4-5", "opus": "claude-opus-4-8"},
            },
            "proxy": {"template": "anthropic-passthrough"},
        }
        ctx = _ctx(
            data={"workspace": {}, "model": {"id": "claude-opus-4-8", "display_name": "Opus"}},
            is_proxy=True,
            runtime=_proxy(raw),
        )
        assert _stream(ctx, ["drift"]) == []

    def test_no_explicit_tier_falls_back_to_default(self):
        # A bare backend model id (no haiku/sonnet/opus) -> route by proxy default.
        raw = {
            "is_proxy": True,
            "runtime": {"active_tier": "sonnet", "tier_mappings": {"sonnet": "gpt-4o"}},
            "proxy": {"template": "litellm-openai"},
        }
        ctx = _ctx(
            data={"workspace": {}, "model": {"id": "custom-model", "display_name": "Custom"}},
            is_proxy=True,
            runtime=_proxy(raw),
        )
        assert any("drift:" in s for s in _stream(ctx, ["drift"]))  # custom-model != gpt-4o

    def test_tier_detection_parity_with_proxy(self):
        # explicit_tier_from_model is a deliberate 1:1 mirror of the proxy's
        # _tier_from_model_name (status_line can't import proxy.server on the hot
        # path). If the proxy's tier logic changes and the mirror doesn't, the drift
        # segment silently replicates the wrong route. This guard fails on drift;
        # the proxy is the source of truth. (Follow-up: extract a shared helper.)
        from forge.proxy.server import _tier_from_model_name

        corpus = [
            "claude-opus-4-8",
            "claude-fable-5",  # Fable rides the opus tier in both mirrors
            "claude-sonnet-4-5",
            "claude-3-5-haiku-20241022",
            "Claude-OPUS-4",  # case-insensitive
            "gpt-4o",  # no tier substring -> None
            "o3",
            "gemini-1.5-pro",
            "custom-model",
            "",  # empty
            "opusculum-7",  # shared naive-substring quirk: both must agree (-> opus)
        ]
        for model in corpus:
            assert explicit_tier_from_model(model) == _tier_from_model_name(model), model

    def test_fable_rides_opus_tier(self):
        # Fable has no tier word of its own; both the model-id and display-name
        # detectors must classify it as opus (else the status line mis-colors it).
        assert explicit_tier_from_model("claude-fable-5") == "opus"
        assert sl.get_tier_from_display_name("Claude Fable 5") == "opus"


class TestSpendCapFormat:
    def test_binding_window_is_highest_percent(self):
        caps = {
            "daily": {"current_usd": 1.0, "limit_usd": 10.0, "percent": 10.0},
            "monthly": {"current_usd": 42.0, "limit_usd": 100.0, "percent": 42.0},
        }
        out = _plain(format_spend_cap(caps) or "")
        assert "cap:m" in out and "$42.00/$100.00" in out and "(42%)" in out  # monthly binds

    def test_single_daily_window(self):
        out = _plain(format_spend_cap({"daily": {"current_usd": 3.2, "limit_usd": 5.0, "percent": 64.0}}) or "")
        assert "cap:d" in out and "$3.20/$5.00" in out and "(64%)" in out

    def test_sub_cent_caps_keep_precision(self):
        # Regression: _fmt_dollars collapsed sub-cent amounts to "0c", so a tiny
        # smoke cap rendered as the misleading "cap:d 0c/0c (50%)". Caps can be
        # legitimately sub-cent, so the binding amounts must stay distinguishable.
        out = _plain(format_spend_cap({"daily": {"current_usd": 0.0005, "limit_usd": 0.001, "percent": 50.0}}) or "")
        assert "$0.0005/$0.0010" in out and "(50%)" in out
        assert "0c" not in out

    def test_threshold_colors(self):
        def _c(pct):
            return format_spend_cap({"daily": {"current_usd": 1.0, "limit_usd": 2.0, "percent": pct}}) or ""

        assert METRICS_COLOR in _c(50.0)  # normal
        assert YELLOW in _c(80.0)  # warning
        assert RED in _c(95.0)  # critical

    def test_empty_or_garbage_is_none(self):
        assert format_spend_cap({}) is None
        assert format_spend_cap({"daily": {"percent": "bad", "current_usd": 1, "limit_usd": 2}}) is None
        assert format_spend_cap({"daily": "notadict"}) is None  # type: ignore[dict-item]


class TestSpendCapProducer:
    _RAW = {
        "is_proxy": True,
        "proxy": {"template": "litellm-openai"},
        "metrics": {
            "costs": {
                "total_usd": 1.0,
                "caps": {"daily": {"current_usd": 3.2, "limit_usd": 5.0, "percent": 64.0}},
            }
        },
    }

    def test_renders_when_caps_present(self):
        ctx = _ctx(is_proxy=True, runtime=_proxy(self._RAW))
        assert any("cap:d" in s for s in _stream(ctx, ["spend_cap"]))

    def test_no_caps_key_hidden(self):
        raw = {"is_proxy": True, "metrics": {"costs": {"total_usd": 1.0}}, "proxy": {}}
        assert _stream(_ctx(is_proxy=True, runtime=_proxy(raw)), ["spend_cap"]) == []

    def test_direct_mode_hidden(self):
        assert _stream(_ctx(is_proxy=False, runtime=None), ["spend_cap"]) == []


class TestFormatForgeCost:
    def test_none_and_nonpositive_render_nothing(self):
        # No segment for not-yet-measured / no-cost / (defensively) negative.
        assert format_forge_cost(None) is None
        assert format_forge_cost(0) is None
        assert format_forge_cost(-5) is None

    def test_dollars_and_subcent(self):
        assert _plain(format_forge_cost(40_000) or "") == "forge +$0.04"
        assert _plain(format_forge_cost(1_234_567) or "") == "forge +$1.23"
        # Reuses _fmt_dollars, which collapses sub-cent to "Nc".
        assert _plain(format_forge_cost(4_000) or "") == "forge +0c"

    def test_distinct_from_native_cost_prefix(self):
        # Visually distinguishable from Claude's native cost: carries a `forge +` prefix.
        assert "forge" in _plain(format_forge_cost(50_000) or "")
        assert "+" in _plain(format_forge_cost(50_000) or "")


class TestForgeCostProducer:
    """`forge_cost` reads the usage ledger (throttled, time-only). sum_forge_added_cost
    is patched so the producer's shape-defense and fail-open are deterministic; the
    throttle writes to the autouse-isolated forge home."""

    _MANIFEST = {"name": "sess-a"}

    def test_renders_added_cost_for_session(self):
        with patch("forge.core.ops.usage_summary.sum_forge_added_cost", return_value=40_000):
            out = _stream(_ctx(manifest=self._MANIFEST), ["forge_cost"])
        assert any("forge +$0.04" in s for s in out)

    def test_no_manifest_is_hidden(self):
        # Ambient session: nothing to attribute, no ledger read.
        assert _stream(_ctx(manifest=None), ["forge_cost"]) == []

    def test_manifest_without_name_is_hidden(self):
        assert _stream(_ctx(manifest={"confirmed": {}}), ["forge_cost"]) == []
        assert _stream(_ctx(manifest={"name": ""}), ["forge_cost"]) == []
        assert _stream(_ctx(manifest={"name": 123}), ["forge_cost"]) == []  # type: ignore[dict-item]

    def test_no_reported_cost_renders_nothing(self):
        # sum returns None (no reported cost) -> compute maps to 0 -> format -> None.
        with patch("forge.core.ops.usage_summary.sum_forge_added_cost", return_value=None):
            assert _stream(_ctx(manifest=self._MANIFEST), ["forge_cost"]) == []

    def test_ledger_read_error_fails_open_to_hidden(self):
        # A raising ledger read must degrade to "no segment", never crash the line.
        with patch("forge.core.ops.usage_summary.sum_forge_added_cost", side_effect=RuntimeError("ledger boom")):
            assert _stream(_ctx(manifest=self._MANIFEST), ["forge_cost"]) == []

    def test_off_by_default(self):
        with patch("forge.core.ops.usage_summary.sum_forge_added_cost", return_value=40_000):
            out = _stream(_ctx(manifest=self._MANIFEST), list(DEFAULT_ORDER))
        assert not any("forge +" in s for s in out)


# --- Registry wiring ------------------------------------------------------


class TestOptInWiring:
    def test_all_forge_segments_named_and_opt_in(self):
        for name in ("supervisor", "policy", "audit", "drift", "spend_cap", "forge_cost"):
            assert name in SEGMENT_NAMES
            assert name not in DEFAULT_ORDER

    def test_default_order_excludes_forge_segments(self):
        # A render with no config (DEFAULT_ORDER) emits none of them.
        manifest = {"intent": {"policy": {"supervisor": {"suspended": False}, "bundles": ["tdd"]}}}
        where, stream = render_segments(_ctx(manifest=manifest), [])
        joined = "".join(where + stream)
        assert "SUP" not in joined and "pol:" not in joined


class TestEndToEndRender:
    """Full status_line() path: config -> registry -> palette -> harden tail."""

    def _render(self, fixture, *, segments, session=None):
        cfg = RuntimeConfig(statusline=StatusLineConfig(segments=segments))
        runner = CliRunner()
        with contextlib.ExitStack() as es:
            es.enter_context(patch.object(sl, "_get_terminal_width", return_value=200))
            es.enter_context(patch.object(sl, "detect_proxy", return_value=(False, None, False)))
            es.enter_context(patch.object(sl, "discover_session", return_value=(session or (None, False))))
            es.enter_context(patch.object(sl, "get_git_branch", return_value=None))
            es.enter_context(patch.object(sl, "_cached_scan_transcript", return_value=TranscriptStats()))
            es.enter_context(patch("forge.runtime_config.get_runtime_config", return_value=cfg))
            res = runner.invoke(status_line, input=json.dumps(fixture), env={"FORGE_STATUS_TRUNCATE": "0"})
        assert res.exit_code == 0, res.output
        return _plain(res.output)

    def test_suspended_supervisor_and_policy_render_through_cli(self):
        manifest = (
            {
                "intent": {"policy": {"enabled": True, "supervisor": {"suspended": False}, "bundles": ["tdd"]}},
                "overrides": {"policy": {"supervisor": {"suspended": True}}},
            },
            True,
        )
        visible = self._render(dict(_DATA), segments=["path", "model", "supervisor", "policy"], session=manifest)
        assert "SUP(susp)" in visible
        assert "pol:TDD" in visible

    def test_forge_segments_omitted_when_no_data(self):
        # Configured but no session/proxy -> baseline path+model only, no crash.
        visible = self._render(dict(_DATA), segments=["path", "model", "supervisor", "policy", "audit", "drift"])
        assert "SUP" not in visible and "pol:" not in visible and "aud:" not in visible and "drift:" not in visible

    def test_supervisor_segment_exits_zero_on_corrupt_ledger(self):
        # Acceptance row "Status-line fail-open": a malformed usage shard must yield empty
        # health, the bar must still exit 0, and the posture renders with NO '!' suffix.
        # Drives a REAL corrupt shard through the full status_line() CLI with the supervisor
        # segment ACTIVELY reading the ledger -- the other e2e cases never trigger a ledger
        # read (their manifests carry no "name", so supervisor_health is gated out early).
        from forge.core.paths import get_forge_home

        events_dir = get_forge_home() / "usage" / "events"
        events_dir.mkdir(parents=True, exist_ok=True)
        (events_dir / "2026-06_bad.jsonl").write_text("{ not valid json\n", encoding="utf-8")
        manifest = (
            {
                "name": "planner",
                "created_at": "2026-06-16T00:00:00Z",
                "intent": {"policy": {"enabled": True, "supervisor": {"suspended": False}}},
            },
            True,
        )
        # _render asserts exit_code == 0 internally.
        visible = self._render(dict(_DATA), segments=["path", "model", "supervisor"], session=manifest)
        assert "SUP" in visible  # posture renders through the full CLI
        assert "SUP!" not in visible  # corrupt ledger -> empty health -> no suffix


class TestSupervisorHealthContext:
    """`RenderContext.supervisor_health` -- manifest-gated, lazy, throttled.

    Exercises the accessor directly; the `SUP!N` render that consumes it is covered by
    `TestFormatHelpers` (the format) and `TestSupervisorProducer` (the producer wiring).
    """

    def test_none_without_session_name(self):
        assert _ctx(manifest=None).supervisor_health is None
        assert _ctx(manifest={"intent": {}}).supervisor_health is None  # no "name"

    def test_reads_ledger_streak(self):
        for i in (1, 2, 3):
            _seed_supervisor(status="timeout", failure_type="timeout", ts=f"2026-06-16T12:00:0{i}Z")
        health = _ctx(manifest={"name": "planner", "created_at": "2026-06-16T00:00:00Z"}).supervisor_health
        assert health is not None
        assert health.recent_failures == 3
        assert health.last_kind == "timeout"

    def test_is_lazy_and_cached(self):
        with patch(
            "forge.core.ops.usage_summary.read_supervisor_health",
            return_value=SupervisorHealth(2, "timeout", "ts"),
        ) as reader:
            ctx = _ctx(manifest={"name": "planner", "created_at": "2026-06-16T00:00:00Z"})
            reader.assert_not_called()  # cached_property is lazy: construction reads nothing
            first = ctx.supervisor_health
            second = ctx.supervisor_health
        assert first == second == SupervisorHealth(2, "timeout", "ts")
        assert reader.call_count == 1  # cached_property collapses repeat access to one read
