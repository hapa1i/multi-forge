"""Status line command for Claude Code.

Invoked by Claude Code's statusLine setting. Reads JSON from stdin,
produces a formatted status line to stdout.

Layout (5 categories):
  Where | Who | What | Metrics | State
  path (branch) | breadcrumb | template [Model] ctx_bar | cost dur | +12/-3 | in:12K out:3K cache:8K | THINK | LOOP N/M | SC
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any

import click

from forge.cli.statusline import sources as status_sources
from forge.cli.statusline import types as status_types
from forge.core.metric_formatting import (
    TokenDisplayPolicy,
    UsdDisplayPolicy,
    format_token_count,
    format_usd,
    format_usd_micros,
)
from forge.core.tiers import detect_tier_word

# Set up minimal logging for status line (stderr to avoid polluting stdout)
logger = logging.getLogger(__name__)

# ANSI color codes
RED = "\033[31m"
RED_BOLD = "\033[31;1m"
LIGHT_RED = "\033[91m"
YELLOW = "\033[33m"
YELLOW_BOLD = "\033[33;1m"
GREEN = "\033[32m"
GREEN_BOLD = "\033[32;1m"
PURPLE = "\033[35m"
BLUE = "\033[94m"
BREADCRUMB_COLOR = "\033[38;5;139m"  # dusty plum
TEMPLATE_COLOR = "\033[38;5;60m"  # deep blue-gray
METRICS_COLOR = "\033[38;5;145m"  # cool grey

# Context bar gradient (Gradient E: soft green → warm → hot)
CTX_LOW = "\033[38;5;115m"  # soft green (<25%)
CTX_MED = "\033[38;5;150m"  # light olive (25-49%)
CTX_HIGH = "\033[38;5;179m"  # warm gold (50-74%)
CTX_WARN = "\033[38;5;173m"  # burnt orange (75-89%)
CTX_CRIT = "\033[38;5;167m"  # hot coral (90-100%)
BOLD = "\033[1m"

# "Resets in" marker, bound inline to a rate-limit window (e.g. ``7d:52%↻1d``) so the
# countdown can't be misread as the trailing session duration. U+21BB is a symbol, not
# an emoji, so the normalize-text hook leaves it intact.
RESET_GLYPH = "↻"  # ↻

# Per-tier model colors (Option 4: navy family)
# 1M variants use a deeper shade of the same hue
TIER_HAIKU = "\033[38;5;67m"  # steel blue
TIER_SONNET = "\033[38;5;69m"  # cornflower
TIER_SONNET_DEEP = "\033[38;5;26m"  # deeper cornflower (1M context)
TIER_OPUS = "\033[38;5;75m"  # vivid blue
TIER_OPUS_DEEP = "\033[38;5;32m"  # deeper vivid blue (1M context)
DARK_GRAY = "\033[90m"
DIM = "\033[2m"
RESET = "\033[0m"

# ASCII display characters
PROGRESS_FILLED = "#"
PROGRESS_EMPTY = "-"

# Separator
SEP = f"{DARK_GRAY}|{RESET}"

# ASCII status indicators
THINKING_INDICATOR = "THINK"
VERIFICATION_INDICATOR = "LOOP"
SIDECAR_INDICATOR = "SC"
HOOK_DOUBLE_FIRE_INDICATOR = "HOOKx2"
HOOK_CLEANUP_INDICATOR = "HOOK!"
TOKEN_INPUT_LABEL = "in:"
TOKEN_OUTPUT_LABEL = "out:"
TOKEN_CACHE_LABEL = "cache:"
LINE_ADD_COLOR = "\033[38;5;28m"
LINE_REMOVE_COLOR = "\033[38;5;124m"

# Trailing margin width (non-breaking spaces) to prevent merging with Claude Code's
# native status display when rendered adjacent to custom statusLine output
TRAILING_MARGIN = 3

# Reserve for Claude Code's native token display (e.g., " 97595 tokens") appended
# to line 1. ccstatusline defaults to subtracting 40; we use a tighter estimate.
NATIVE_DISPLAY_RESERVE = 15

# Fallback terminal width when /dev/tty and COLUMNS are both unavailable.
# Conservative: "too narrow = mild truncation" is better than "too wide = wrapping bug".
DEFAULT_TERM_WIDTH = 80

# Separator as it appears in hardened output (spaces → NBSPs)
_HARDENED_SEP = f"\u00a0{SEP}\u00a0"


def _get_terminal_width() -> int:
    """Get terminal width, even when stdout is piped.

    Claude Code always pipes to statusLine commands, so os.get_terminal_size()
    on stdout fails. Instead, open /dev/tty (the controlling terminal) directly
    to query the real width. Falls back to COLUMNS env var, then DEFAULT_TERM_WIDTH.
    """
    try:
        fd = os.open("/dev/tty", os.O_RDONLY)
        try:
            return os.get_terminal_size(fd).columns
        finally:
            os.close(fd)
    except (OSError, ValueError):
        pass
    return shutil.get_terminal_size(fallback=(DEFAULT_TERM_WIDTH, 24)).columns


def compact_model_name(model: str) -> str:
    """Strip provider prefix and shorten model names for display.

    Delegates to the model catalog for short_name overrides, with generic
    rules (prefix stripping, -preview removal) for models not in the catalog.
    """
    from forge.core.models import get_compact_name

    return get_compact_name(model)


def _tier_color(tier: str, runtime: status_types.ProxyRuntimeTruth | None) -> str:
    """Pick color for a tier, using deep variant for extended context (>200K)."""
    extended = False
    if runtime:
        ctx = runtime.get_context_window_for_tier(tier)
        if ctx and ctx > 200_000:
            extended = True

    if tier == "opus":
        return TIER_OPUS_DEEP if extended else TIER_OPUS
    elif tier == "sonnet":
        return TIER_SONNET_DEEP if extended else TIER_SONNET
    return TIER_HAIKU


def get_tier_display(runtime: status_types.ProxyRuntimeTruth | None) -> str | None:
    """Get tier display string showing all mappings.

    Format: "O:model S:model H:model" with per-tier coloring.
    """
    if runtime is None:
        return None

    # Prefer runtime.tier_mappings (authoritative), fallback to legacy tiers
    tier_mappings = runtime.tier_mappings
    if not tier_mappings:
        tier_mappings = {k: v.get("model", "") for k, v in runtime.tiers.items()}

    if not tier_mappings:
        return None

    h_model = tier_mappings.get("haiku", "")
    s_model = tier_mappings.get("sonnet", "")
    o_model = tier_mappings.get("opus", "")

    if not any([h_model, s_model, o_model]):
        return None

    h_name = compact_model_name(h_model)
    s_name = compact_model_name(s_model)
    o_name = compact_model_name(o_model)

    oc = _tier_color("opus", runtime)
    sc = _tier_color("sonnet", runtime)
    hc = _tier_color("haiku", runtime)

    return f"{oc}O:{o_name}{RESET} {sc}S:{s_name}{RESET} {hc}H:{h_name}{RESET}"


# Context window info is sourced from:
# 1. Proxy runtime truth (GET /) when using proxy - authoritative from core.models catalog
# 2. Claude Code's JSON input (context_window field) when not using proxy
# No hardcoded fallback tables - unknown models will show context from Claude Code's input


def get_tier_from_display_name(display_name: str) -> str:
    """Map Claude Code's display name to tier."""
    display_lower = display_name.lower()
    # Fable carries no tier word of its own; it rides the opus tier.
    if "opus" in display_lower or "fable" in display_lower:
        return "opus"
    elif "sonnet" in display_lower:
        return "sonnet"
    elif "haiku" in display_lower:
        return "haiku"
    return "sonnet"


def explicit_tier_from_model(model_id: str) -> str | None:
    """Infer an explicit haiku/sonnet/opus tier from a model id, else None.

    1:1 mirror of the proxy's ``_tier_from_model_name`` (proxy/server.py): request
    routing prefers an explicit tier in the model name over ``config.proxy
    .default_tier``. Returns None when no tier substring is present (the proxy then
    falls back to its default), so the drift producer can replicate the real route
    instead of comparing against the proxy default tier.
    """
    return detect_tier_word(model_id or "")


def parse_context_from_json(data: dict[str, Any]) -> dict[str, Any] | None:
    """Parse context usage from Claude Code's JSON input.

    Uses the official context_window field from Claude Code's status line contract.

    Expected format:
        context_window:
            context_window_size: 200000
            current_usage:
                input_tokens: 8500
                cache_creation_input_tokens: 5000
                cache_read_input_tokens: 2000
    """
    context_window_data = data.get("context_window")
    if not context_window_data:
        return None

    # Claude Code sends context_window as int (just the size) or dict (size + usage).
    # When it's an int there's no usage breakdown to display.
    if isinstance(context_window_data, (int, float)):
        return None

    context_window_size = context_window_data.get("context_window_size", 0)
    if not context_window_size or context_window_size <= 0:
        return None

    current_usage = context_window_data.get("current_usage") or {}

    # Calculate current context from current_usage fields
    input_tokens = current_usage.get("input_tokens", 0)
    cache_creation = current_usage.get("cache_creation_input_tokens", 0)
    cache_read = current_usage.get("cache_read_input_tokens", 0)
    total_tokens = input_tokens + cache_creation + cache_read

    used_percentage = context_window_data.get("used_percentage")
    if used_percentage is None and total_tokens <= 0:
        return None

    if used_percentage is not None:
        percent_used = min(100, int(used_percentage))
        # Back-compute tokens from percentage so proxy override path stays consistent
        if total_tokens <= 0:
            total_tokens = int(context_window_size * used_percentage / 100)
    else:
        percent_used = min(100, int((total_tokens / context_window_size) * 100))

    return {
        "percent": percent_used,
        "tokens": total_tokens,
        "context_window": context_window_size,
    }


def get_effective_context_window(
    data: dict[str, Any],
    runtime: status_types.ProxyRuntimeTruth | None,
    context_info: dict[str, Any] | None,
) -> int | None:
    """Resolve the best-known context window size for display."""
    if runtime and runtime.active_context_window:
        return runtime.active_context_window

    if context_info:
        context_window = context_info.get("context_window", 0)
        if context_window > 0:
            return context_window

    context_window_data = data.get("context_window")
    if isinstance(context_window_data, dict):
        context_window_size = context_window_data.get("context_window_size", 0)
        if context_window_size > 0:
            return context_window_size
    if isinstance(context_window_data, (int, float)) and context_window_data > 0:
        return int(context_window_data)

    return None


def format_model_label(display_name: str, context_window: int | None) -> str:
    """Clean Claude's display name and append non-default context size when useful."""
    base_name = re.sub(r"\s*\([^)]*context[^)]*\)", "", display_name).strip()
    if context_window and context_window > 200_000:
        return f"{base_name} ({format_context_size(context_window)})"
    return base_name


def format_context_size(size: int) -> str:
    """Format context window size for display (e.g., 2097152 -> "2M")."""
    if size >= 1_000_000:
        millions = size // 1_000_000
        remainder = (size % 1_000_000) // 100_000
        if remainder > 0:
            return f"{millions}.{remainder}M"
        return f"{millions}M"
    elif size >= 1000:
        return f"{size // 1000}K"
    return str(size)


def get_context_display(
    context_info: dict[str, Any] | None,
    glyphs: tuple[str, str] | None = None,
) -> str:
    """Generate context display with progress bar.

    ``glyphs`` is an optional ``(filled, empty)`` pair for the bar; defaults to
    the ASCII module constants so existing callers stay byte-identical.
    """
    filled_char, empty_char = glyphs if glyphs is not None else (PROGRESS_FILLED, PROGRESS_EMPTY)
    if not context_info:
        return f"{DARK_GRAY}---{RESET}"

    percent = context_info.get("percent", 0)
    warning = context_info.get("warning", "")
    context_window = context_info.get("context_window", 0)

    # 5-step gradient with wider bands at extremes (2/7, 1/7, 1/7, 1/7, 2/7).
    # Auto-compact fires around 80% so the warning zone starts early at 57%.
    if percent >= 72:
        color = CTX_CRIT
        alert = "!"
    elif percent >= 57:
        color = CTX_WARN
        alert = ""
    elif percent >= 43:
        color = CTX_HIGH
        alert = ""
    elif percent >= 29:
        color = CTX_MED
        alert = ""
    else:
        color = CTX_LOW
        alert = ""

    segments = 8
    filled = percent * segments // 100
    empty = segments - filled
    bar = filled_char * filled + empty_char * empty

    # Warning overrides
    if warning == "auto-compact":
        alert = "AC"
    elif warning == "low":
        alert = "!"

    if context_window > 0:
        size_str = format_context_size(context_window)
        alert_str = f" {alert}" if alert else ""
        return f"{color}{bar} {percent}%/{BOLD}{size_str}{alert_str}{RESET}"
    else:
        alert_str = f" {alert}" if alert else ""
        return f"{color}{bar} {percent}%{BOLD}{alert_str}{RESET}"


def _format_duration(cost_data: dict[str, Any]) -> str | None:
    """Format session duration (colored), or None if absent. Unrelated to billing."""
    duration_ms = (cost_data or {}).get("total_duration_ms", 0)
    if duration_ms <= 0:
        return None
    minutes = duration_ms // 60000
    color = YELLOW if minutes >= 30 else METRICS_COLOR
    duration_str = f"{duration_ms // 1000}s" if duration_ms < 60000 else f"{minutes}m"
    return f"{color}{duration_str}{RESET}"


def get_session_metrics(
    cost_data: dict[str, Any],
    is_proxy: bool,
    proxy_cost_usd: float = 0.0,
) -> str | None:
    """Get session metrics (cost in dollars, duration). Returns bare string or None.

    This is the API-billing / proxy view (dollars are real). Subscription/quota
    rendering lives in ``format_billing_cost``.
    """
    if not cost_data and proxy_cost_usd <= 0:
        return None

    metrics: list[str] = []

    if is_proxy and proxy_cost_usd > 0:
        cost_str = f"~{format_usd(proxy_cost_usd, policy=UsdDisplayPolicy.STATUS_FRACTIONAL_CENTS)}"
        metrics.append(f"{METRICS_COLOR}{cost_str}{RESET}")
    elif not is_proxy:
        cost_usd = (cost_data or {}).get("total_cost_usd", 0)
        if cost_usd > 0:
            cost_str = format_usd(cost_usd, policy=UsdDisplayPolicy.STATUS_WHOLE_CENTS)
            metrics.append(f"{METRICS_COLOR}{cost_str}{RESET}")

    duration = _format_duration(cost_data)
    if duration:
        metrics.append(duration)

    return " ".join(metrics) if metrics else None


def get_compact_path(current_dir: str) -> str:
    """Create compact path: project/.../dir."""
    if not current_dir:
        return ""

    home = str(Path.home())
    workspace_path = os.path.join(home, "workspace")

    if current_dir.startswith(workspace_path + "/"):
        rel_path = current_dir[len(workspace_path) + 1 :]
        parts = rel_path.split("/")
        num_parts = len(parts)

        if num_parts == 1:
            return parts[0]
        elif num_parts == 2:
            return f"{parts[0]}/{parts[-1]}"
        else:
            return f"{parts[0]}/.../{parts[-1]}"
    else:
        # Outside workspace, use ~ substitution
        if current_dir.startswith(home):
            return "~" + current_dir[len(home) :]
        return current_dir


# --- Formatting helpers ---

# Breadcrumb separator
BREADCRUMB_SEP = " > "
BREADCRUMB_ELISION = "..."

# Terminal states where verification loop has ended (no indicator needed).
# "error" is intentionally excluded — a broken verifier is actionable info.
_VERIFICATION_TERMINAL = {
    "passed",
    "max_iterations",
    "max_minutes",
    "bypassed",
    "warned",
}

# ANSI escape sequence regex for stripping/preserving color codes
_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def _char_width(c: str) -> int:
    """Return terminal display width of a single character.

    Handles emoji (2 cols), variation selectors and combining marks (0 cols),
    and East Asian wide/fullwidth characters (2 cols).
    """
    cp = ord(c)
    # Zero-width: variation selectors, ZWJ, ZWNJ
    if cp in (0xFE0E, 0xFE0F, 0x200D, 0x200C):
        return 0
    cat = unicodedata.category(c)
    if cat.startswith("M"):  # Combining marks
        return 0
    # Supplementary characters (most emoji live here)
    if cp >= 0x10000:
        return 2
    eaw = unicodedata.east_asian_width(c)
    if eaw in ("W", "F"):
        return 2
    return 1


def _visible_width(text: str) -> int:
    """Return terminal display width of text, stripping ANSI and counting Unicode correctly.

    Key difference from len(): emoji like 🧠 count as 2 columns,
    and variation selectors (U+FE0F) after BMP characters add 1 extra column
    (BMP char goes from 1-col text to 2-col emoji presentation).
    """
    stripped = _ANSI_RE.sub("", text)
    width = 0
    prev_cp = 0
    for c in stripped:
        cp = ord(c)
        # VS16 after a narrow BMP char → upgrade previous char to emoji width
        if cp == 0xFE0F and 0 < prev_cp < 0x10000:
            eaw = unicodedata.east_asian_width(chr(prev_cp))
            if eaw not in ("W", "F"):
                width += 1  # was counted as 1, should be 2
            prev_cp = cp
            continue
        w = _char_width(c)
        width += w
        if w > 0:
            prev_cp = cp
    return width


def format_breadcrumb(manifest: dict[str, Any], is_authoritative: bool) -> str | None:
    """Format session lineage as breadcrumb: origin > ... > parent > current.

    Rules (max 3 crumbs):
    - No lineage → session_name
    - 1 ancestor -> parent > current
    - 2 ancestors -> origin > parent > current
    - 3+ ancestors -> origin > ... > parent > current

    lineage field is [parent, grandparent, ...] (nearest first).
    """
    session_name = manifest.get("name", "")
    if not session_name:
        return None

    derivation = manifest.get("confirmed", {}).get("derivation") or {}
    lineage: list[str] = derivation.get("lineage", [])
    suffix = "" if is_authoritative else "(~)"

    if not lineage:
        return f"{session_name}{suffix}"

    # Reverse: [parent, grandparent, origin] → [origin, grandparent, parent]
    ancestors = list(reversed(lineage))

    if len(ancestors) == 1:
        breadcrumb = f"{ancestors[0]}{BREADCRUMB_SEP}{session_name}"
    elif len(ancestors) == 2:
        breadcrumb = BREADCRUMB_SEP.join(ancestors) + f"{BREADCRUMB_SEP}{session_name}"
    else:
        # 3+ ancestors: origin > ... > parent > current
        breadcrumb = (
            f"{ancestors[0]}{BREADCRUMB_SEP}{BREADCRUMB_ELISION}{BREADCRUMB_SEP}"
            f"{ancestors[-1]}{BREADCRUMB_SEP}{session_name}"
        )

    return f"{breadcrumb}{suffix}"


def format_verification(manifest: dict[str, Any]) -> str | None:
    """Format verification status: LOOP N/M when active, None otherwise."""
    confirmed_verif = manifest.get("confirmed", {}).get("verification") or {}
    iterations = confirmed_verif.get("iterations", 0)
    if iterations == 0:
        return None

    last_result = confirmed_verif.get("last_result")
    if last_result in _VERIFICATION_TERMINAL:
        return None

    max_iterations = manifest.get("intent", {}).get("verification", {}).get("max_iterations", 50)
    return f"{VERIFICATION_INDICATOR} {iterations}/{max_iterations}"


def format_sidecar(manifest: dict[str, Any]) -> str | None:
    """Return ASCII indicator when session uses sidecar mode."""
    if manifest.get("confirmed", {}).get("is_sandboxed", False):
        return SIDECAR_INDICATOR
    return None


def format_hook_double_fire(double_fire: bool) -> str | None:
    """Return a compact diagnostic when Forge hooks may fire more than once."""

    if not double_fire:
        return None
    return f"{YELLOW_BOLD}{HOOK_DOUBLE_FIRE_INDICATOR}{RESET}"


def format_hook_cleanup_required(cleanup_required: bool) -> str | None:
    """Return a diagnostic distinct from genuine duplicate execution."""

    if not cleanup_required:
        return None
    return f"{YELLOW_BOLD}{HOOK_CLEANUP_INDICATOR}{RESET}"


def format_hook_migration_state(double_fire: bool, cleanup_required: bool) -> str | None:
    """Render independent double-fire and cleanup-required hook states."""

    parts = [
        part
        for part in (
            format_hook_double_fire(double_fire),
            format_hook_cleanup_required(cleanup_required),
        )
        if part
    ]
    return " ".join(parts) if parts else None


def format_native_sandbox() -> str | None:
    """Return indicator if Claude Code native sandbox is active.

    TODO: Claude Code does not currently expose a discoverable
    env var for sandbox state (Seatbelt/bubblewrap). Wire this in when
    the detection mechanism is confirmed. Candidates: CLAUDE_SANDBOX,
    CLAUDE_CODE_SANDBOX_MODE, or presence of sandbox-runtime process.
    """
    return None


def _extract_windows(
    rate_limits: Any,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Return ``(five_hour, seven_day)`` windows from either Claude Code shape.

    Current payload is an object ``{five_hour: {...}, seven_day: {...}}``; older
    payloads were a list of ``{type, used_percentage, resets_at}`` entries. Either
    window may be absent (``None``). Returns ``(None, None)`` for anything that
    isn't a recognizable rate-limit container (a bare dict without the object keys
    is rejected, not guessed). A legacy untyped single-entry list is treated as
    the 5h window (the prior fallback).
    """
    if isinstance(rate_limits, dict):
        five_obj = rate_limits.get("five_hour")
        seven_obj = rate_limits.get("seven_day")
        return (
            five_obj if isinstance(five_obj, dict) else None,
            seven_obj if isinstance(seven_obj, dict) else None,
        )

    if isinstance(rate_limits, list):
        five: dict[str, Any] | None = None
        seven: dict[str, Any] | None = None
        untyped: dict[str, Any] | None = None
        for entry in rate_limits:
            if not isinstance(entry, dict):
                continue
            window_type = str(entry.get("type", "")).lower()
            if "7" in window_type or "day" in window_type or "week" in window_type:
                seven = seven or entry
            elif "5" in window_type or "hour" in window_type:
                five = five or entry
            elif untyped is None:
                untyped = entry
        if five is None and seven is None:
            five = untyped
        return five, seven

    logger.debug("rate_limits unexpected type: %s", type(rate_limits).__name__)
    return None, None


def _format_reset_countdown(resets_at: Any, now: float | None = None) -> str | None:
    """Compact 'time until reset' (e.g. ``3d``/``2h``/``5m``) from an ISO or epoch value.

    Returns None when absent, already elapsed, or unparseable (fail-open).
    """
    if resets_at is None:
        return None
    if now is None:
        now = time.time()
    epoch: float | None = None
    if isinstance(resets_at, (int, float)):
        epoch = float(resets_at)
    elif isinstance(resets_at, str):
        from forge.core.state import try_parse_iso

        parsed = try_parse_iso(resets_at)
        if parsed is None:
            return None
        epoch = parsed.timestamp()
    if epoch is None:
        return None
    remaining = epoch - now
    if remaining <= 0:
        return None
    # Sanity cap: a 5h/7d rate-limit window never resets more than ~8 days out.
    # Beyond that the timestamp is malformed (wrong units/epoch) — omit rather
    # than render an absurd "616518h" (system boundary, best-effort).
    if remaining > 8 * 86400:
        return None
    hours = int(remaining // 3600)
    if hours >= 24:
        return f"{int(remaining // 86400)}d"
    if hours >= 1:
        return f"{hours}h"
    return f"{max(1, int(remaining // 60))}m"


def _heat_color(percent: float) -> str:
    """Heat-map a 0-100 usage percentage onto the shared context gradient.

    Reuses the ``CTX_*`` palette (soft green → warm → hot) so quota burn reads
    like the context bar. Bands follow the palette's documented intent
    (<25 / 25-49 / 50-74 / 75-89 / 90-100), NOT the context bar's
    auto-compact-skewed thresholds — a quota has no auto-compact, so 100% is the
    real wall.
    """
    if percent >= 90:
        return CTX_CRIT
    if percent >= 75:
        return CTX_WARN
    if percent >= 50:
        return CTX_HIGH
    if percent >= 25:
        return CTX_MED
    return CTX_LOW


def _format_window_entry(label: str, window: dict[str, Any]) -> tuple[str, float, Any] | None:
    """Render one labeled, heat-mapped window (``5h:34%``) or None if no valid pct.

    Returns ``(rendered, used_pct, resets_at)`` so the caller can pick the
    higher-pressure window for the reset countdown.
    """
    used_pct = window.get("used_percentage")
    if used_pct is None:
        return None
    try:
        pct_float = float(used_pct)
    except (TypeError, ValueError):
        logger.debug("rate_limits used_percentage unexpected value: %r", used_pct)
        return None
    rendered = f"{DIM}{label}:{RESET}{_heat_color(pct_float)}{int(pct_float)}%{RESET}"
    return rendered, pct_float, window.get("resets_at")


def format_rate_limits(
    rate_limits: Any,
    is_proxy: bool,
    *,
    show_reset: bool = False,
    now: float | None = None,
) -> str | None:
    """Format quota burn from Claude Code's rate_limits field.

    Shows both windows when present — ``5h:N% · 7d:M%`` — each heat-mapped on the
    shared context gradient (soft green → hot coral) by its own usage, so the
    binding limit lights up while the calmer window stays green. The ``5h``/``7d``
    labels are self-describing, so no segment prefix is added. Handles the object
    and legacy list payload shapes. Skipped in proxy mode (the proxy has its own
    rate limits). With ``show_reset`` a reset countdown is bound INLINE to the
    higher-pressure window (``7d:52%↻1d``) so it can't be misread as the trailing
    session duration.
    """
    if is_proxy or not rate_limits:
        return None

    five, seven = _extract_windows(rate_limits)
    entries = [
        entry
        for label, window in (("5h", five), ("7d", seven))
        if window is not None and (entry := _format_window_entry(label, window)) is not None
    ]
    if not entries:
        return None

    # Bind the countdown to the window under most pressure (the binding limit),
    # inline after its percentage — never as a trailing token.
    binding = max(range(len(entries)), key=lambda i: entries[i][1]) if show_reset else -1
    parts: list[str] = []
    for i, (rendered, _, resets_at) in enumerate(entries):
        if i == binding:
            countdown = _format_reset_countdown(resets_at, now)
            if countdown:
                rendered += f"{DIM}{RESET_GLYPH}{countdown}{RESET}"
        parts.append(rendered)
    return f"{DIM} · {RESET}".join(parts)


def format_billing_cost(
    billing_mode: str,
    cost_data: dict[str, Any],
    rate_limits: Any,
    *,
    now: float | None = None,
) -> str | None:
    """Cost segment for non-API billing (direct sessions).

    ``subscription``/``ambiguous`` show the 5h quota instead of dollars (which are
    a phantom figure on a subscription). When no quota data is available,
    ``ambiguous`` (the ``auto`` default — billing is undeclared and never inferred
    from an API key) hedges with ``≈$X.XX`` to flag the figure as uncertain; an
    explicit ``subscription`` shows no dollar figure at all. Duration is always
    appended when present.
    """
    parts: list[str] = []
    quota = format_rate_limits(rate_limits, is_proxy=False, show_reset=True, now=now)
    if quota:
        parts.append(quota)
    elif billing_mode == "ambiguous":
        cost_usd = (cost_data or {}).get("total_cost_usd", 0) or 0
        if cost_usd > 0:
            cost_str = format_usd(cost_usd, policy=UsdDisplayPolicy.STATUS_WHOLE_CENTS)
            parts.append(f"{METRICS_COLOR}\u2248{cost_str}{RESET}")

    duration = _format_duration(cost_data)
    if duration:
        parts.append(duration)

    return " ".join(parts) if parts else None


def format_cache_hit(rate: float) -> str:
    """Format a cache-hit-rate percentage as ``cache:N%`` (green when high)."""
    pct = int(rate)
    color = GREEN if rate >= 50 else METRICS_COLOR
    return f"{DIM}cache:{RESET}{color}{pct}%{RESET}"


# Compact labels for the Forge-unique opt-in segments. Known names map to short
# codes; unknown names fall back to the uppercased raw name (honest, if longer).
_BUNDLE_LABELS = {"tdd": "TDD", "coding_standards": "STD"}
_AUDIT_MODE_LABELS = {
    "passthrough": "pass",
    "inspect": "inspect",
    "override": "override",
}


def format_supervisor(
    suspended: bool,
    enabled: bool = True,
    *,
    recent_failures: int = 0,
    last_kind: str | None = None,
) -> str:
    """Supervisor posture, optionally suffixed with recent fail-open health.

    Posture: ``SUP`` active, ``SUP(susp)`` suspended, ``SUP(off)`` when policy is
    disabled. ``policy.enabled=False`` makes the whole policy subsystem inert (the
    hook exits before running), so a disabled supervisor is not actually watching —
    distinct from suspended. Both non-active states use the warning color.

    When ``recent_failures > 0`` a posture-independent ``!N <kind>`` suffix is
    appended (``SUP!3 timeout``) — the newest-first contiguous run of frontier
    supervisor runs the usage ledger recorded as a non-``success`` status, tiered
    like :func:`format_spend_cap` (yellow 1-2, red >= 3). ``recent_failures == 0``
    (the default, and the no-session / fail-open case) renders the bare posture,
    byte-identical to a supervisor with no health data. ``last_kind`` is the display
    kind (``"timeout"`` | ``"error"``) of the newest failure.
    """
    if not enabled:
        token = f"{YELLOW}SUP(off){RESET}"
    elif suspended:
        token = f"{YELLOW}SUP(susp){RESET}"
    else:
        token = f"{METRICS_COLOR}SUP{RESET}"
    if recent_failures <= 0:
        return token  # byte-identical to today: no failures -> bare posture
    color = RED if recent_failures >= 3 else YELLOW
    kind = last_kind or "error"  # reader guarantees a kind when count>0; defend the str|None type
    return f"{token}{color}!{recent_failures} {kind}{RESET}"


def format_policy(bundles: list[str], enabled: bool = True) -> str | None:
    """Active policy bundles as ``pol:TDD+STD``. None if no usable bundle names.

    When policy is disabled the bundles are configured but not enforced, so the
    label gets an ``(off)`` suffix in the warning color rather than claiming they
    are active.
    """
    labels = [_BUNDLE_LABELS.get(b, b.upper()) for b in bundles if isinstance(b, str) and b]
    if not labels:
        return None
    joined = "+".join(labels)
    if not enabled:
        return f"{DIM}pol:{RESET}{YELLOW}{joined}(off){RESET}"
    return f"{DIM}pol:{RESET}{METRICS_COLOR}{joined}{RESET}"


def format_audit(mode: str, thinking_preserved: bool) -> str:
    """Proxy audit posture as ``aud:<mode>`` (+ ``(lossy)`` when applicable).

    ``override`` actively rewrites traffic, so it gets the warning color. When
    inspecting/overriding on a translated wire, thinking-block signatures can't
    round-trip — mirror ``GET /``'s lossy framing with a dim suffix.
    """
    label = _AUDIT_MODE_LABELS.get(mode, mode)
    color = YELLOW if mode == "override" else METRICS_COLOR
    out = f"{DIM}aud:{RESET}{color}{label}{RESET}"
    if mode in ("inspect", "override") and not thinking_preserved:
        out += f"{DIM}(lossy){RESET}"
    return out


def format_drift(stdin_model_id: str, backend_model: str) -> str | None:
    """Flag when the served backend differs from the model Claude Code reports.

    Compares compact names so equivalent IDs (``claude-opus-4-8`` vs its catalog
    short name) don't false-positive. Returns None when aligned — the segment is
    an alert, so no news is good news.
    """
    shown = compact_model_name(stdin_model_id)
    served = compact_model_name(backend_model)
    if shown == served:
        return None
    return f"{YELLOW}drift:{shown}!={served}{RESET}"


def format_spend_cap(caps: dict[str, Any]) -> str | None:
    """Spend-cap proximity for the binding window, e.g. ``cap:m $42.00/$100.00 (42%)``.

    ``caps`` is the proxy's ``metrics.costs.caps`` (``{"daily"|"monthly":
    {current_usd, limit_usd, percent}}``). Shows whichever configured window is
    closest to its limit — the one that blocks first — marked ``d``/``m``.
    Threshold-colored: normal < 75%, yellow 75-89%, red >= 90%. None if no usable
    entry.
    """
    binding: tuple[float, str, float, float] | None = None
    for window in ("daily", "monthly"):
        entry = caps.get(window)
        if not isinstance(entry, dict):
            continue
        pct, cur, lim = (
            entry.get("percent"),
            entry.get("current_usd"),
            entry.get("limit_usd"),
        )
        if not all(isinstance(v, (int, float)) for v in (pct, cur, lim)):
            continue
        if binding is None or float(pct) > binding[0]:  # type: ignore[arg-type]  # guarded above
            binding = (float(pct), window[0], float(cur), float(lim))  # type: ignore[arg-type]
    if binding is None:
        return None
    pct, marker, cur, lim = binding
    color = RED if pct >= 90 else YELLOW if pct >= 75 else METRICS_COLOR
    current = format_usd(cur, policy=UsdDisplayPolicy.SPEND_CAP)
    limit = format_usd(lim, policy=UsdDisplayPolicy.SPEND_CAP)
    return f"{DIM}cap:{RESET}{color}{marker} {current}/{limit} ({int(pct)}%){RESET}"


_LAUNCH_KEY_LABELS = {
    "env": "env",
    "credential_file": "file",
    "none": "none",
    "omitted_by_config": "omit",
}


def format_launch(launch: dict[str, Any]) -> str | None:
    """Render ``confirmed.launch`` as ``<route>·key:<posture>`` (e.g. ``proxy:p1·key:env``).

    Describes how the interactive session reached the model and whether an API key
    was made available to it — the honest auth breadcrumb the status line needs
    (``omit`` means Forge deliberately withheld the key, so a key in the ambient
    env is not the payer). Shape-defensive: returns None when nothing is showable.
    """
    routing_mode = launch.get("routing_mode")
    proxy_id = launch.get("proxy_id")
    if routing_mode == "proxy":
        route = f"proxy:{proxy_id}" if proxy_id else "proxy"
    elif routing_mode == "custom_base_url":
        route = "custom"
    elif routing_mode == "direct":
        route = "direct"
    else:
        route = None

    source = launch.get("api_key_source")
    key_label = _LAUNCH_KEY_LABELS.get(source) if isinstance(source, str) else None

    parts: list[str] = []
    if route:
        parts.append(f"{TEMPLATE_COLOR}{route}{RESET}")
    if key_label:
        parts.append(f"{DIM}key:{RESET}{METRICS_COLOR}{key_label}{RESET}")
    if not parts:
        return None
    return f"{DIM}·{RESET}".join(parts)


def format_forge_cost(micros: int | None) -> str | None:
    """Render Forge's *additional* headless cost for the session as ``forge +$X.XX``.

    Visually distinct from Claude's native ``cost`` segment via the ``forge +``
    prefix — this is what Forge spent on top of the interactive harness (memory
    writer, supervisor, review fan-out), reported-or-nothing. ``None`` or a
    non-positive value renders nothing (a not-yet-measured or no-cost session shows
    no segment rather than a misleading ``+$0.00``).
    """
    if micros is None or micros <= 0:
        return None
    cost = format_usd_micros(micros, policy=UsdDisplayPolicy.STATUS_WHOLE_CENTS)
    return f"{DIM}forge{RESET} {METRICS_COLOR}+{cost}{RESET}"


def format_token_breakdown(input_tokens: int, output_tokens: int, cached_tokens: int) -> str | None:
    """Format cumulative token breakdown: in:12K out:3.2K cache:8K."""
    if input_tokens == 0 and output_tokens == 0 and cached_tokens == 0:
        return None
    parts: list[str] = []
    if input_tokens > 0:
        tokens = format_token_count(input_tokens, policy=TokenDisplayPolicy.UPPER_TENTHS)
        parts.append(f"{DIM}{TOKEN_INPUT_LABEL}{RESET}{METRICS_COLOR}{tokens}{RESET}")
    if output_tokens > 0:
        tokens = format_token_count(output_tokens, policy=TokenDisplayPolicy.UPPER_TENTHS)
        parts.append(f"{DIM}{TOKEN_OUTPUT_LABEL}{RESET}{METRICS_COLOR}{tokens}{RESET}")
    if cached_tokens > 0:
        tokens = format_token_count(cached_tokens, policy=TokenDisplayPolicy.UPPER_TENTHS)
        parts.append(f"{DIM}{TOKEN_CACHE_LABEL}{RESET}{METRICS_COLOR}{tokens}{RESET}")
    return " ".join(parts) if parts else None


def format_line_changes(cost_data: dict[str, Any], current_dir: str = "") -> str | None:
    """Format direct line counts as +added/-removed with conventional colors."""
    lines_added, lines_removed = status_sources.get_line_change_values(cost_data, current_dir)
    if lines_added == 0 and lines_removed == 0:
        return None

    parts: list[str] = []
    if lines_added > 0:
        parts.append(f"{LINE_ADD_COLOR}+{lines_added}{RESET}")
    if lines_removed > 0:
        parts.append(f"{LINE_REMOVE_COLOR}-{lines_removed}{RESET}")

    return f"{DARK_GRAY}/{RESET}".join(parts) if len(parts) == 2 else parts[0]


def get_token_breakdown_values(data: dict[str, Any], stats: status_types.TranscriptStats) -> tuple[int, int, int]:
    """Prefer token totals from Claude Code input, with transcript fallback."""
    context_window_data = data.get("context_window")
    if not isinstance(context_window_data, dict):
        return stats.input_tokens, stats.output_tokens, stats.cached_tokens

    input_tokens = context_window_data.get("total_input_tokens")
    output_tokens = context_window_data.get("total_output_tokens")

    # Prefer aggregate key; fall back to sum of breakdown keys to avoid double-counting
    total_cached = context_window_data.get("total_cached_tokens")
    if total_cached is not None:
        cached_tokens: int | None = int(total_cached)
    else:
        read = context_window_data.get("total_cache_read_input_tokens")
        creation = context_window_data.get("total_cache_creation_input_tokens")
        if read is not None or creation is not None:
            cached_tokens = int(read or 0) + int(creation or 0)
        else:
            cached_tokens = None

    return (
        int(input_tokens) if input_tokens is not None else stats.input_tokens,
        int(output_tokens) if output_tokens is not None else stats.output_tokens,
        cached_tokens if cached_tokens is not None else stats.cached_tokens,
    )


def truncate_ansi(text: str, max_width: int) -> str:
    """Truncate text to max_width visible columns, preserving ANSI codes.

    Uses _char_width() for correct emoji/Unicode column counting.
    Appends '...' when limit reached.
    """
    if max_width <= 3:
        return "..."

    visible_len = 0
    result: list[str] = []
    in_ansi = False
    prev_cp = 0

    for char in text:
        if char == "\033":
            in_ansi = True
            result.append(char)
        elif in_ansi:
            result.append(char)
            if char == "m":
                in_ansi = False
        else:
            cp = ord(char)
            # VS16 after BMP char upgrades it to emoji width
            if cp == 0xFE0F and 0 < prev_cp < 0x10000:
                eaw = unicodedata.east_asian_width(chr(prev_cp))
                if eaw not in ("W", "F"):
                    visible_len += 1
                result.append(char)
                prev_cp = cp
                continue

            w = _char_width(char)
            if visible_len + w <= max_width - 3:
                result.append(char)
                visible_len += w
                if w > 0:
                    prev_cp = cp
            else:
                result.append("...")
                break
    else:
        return text

    return "".join(result)


def _wrap_output(output: str, available: int) -> str:
    """Wrap at a separator boundary instead of truncating with '...'.

    Splits at the last | separator that fits within `available` visible columns.
    Line 2 gets an ANSI reset prefix. Falls back to truncate_ansi() when
    there are no separators or the first segment alone exceeds the width.
    """
    segments = output.split(_HARDENED_SEP)
    if len(segments) <= 1:
        return truncate_ansi(output, available)

    sep_visible_width = _visible_width(_HARDENED_SEP)

    line1_parts = [segments[0]]
    line1_visible = _visible_width(segments[0])
    split_idx = 1

    for i in range(1, len(segments)):
        seg_visible = _visible_width(segments[i])
        new_width = line1_visible + sep_visible_width + seg_visible
        if new_width <= available:
            line1_parts.append(segments[i])
            line1_visible = new_width
            split_idx = i + 1
        else:
            break

    if split_idx >= len(segments):
        return output

    if not line1_parts or line1_visible == 0:
        return truncate_ansi(output, available)

    line1 = _HARDENED_SEP.join(line1_parts)
    remaining = segments[split_idx:]
    line2 = "\x1b[0m" + _HARDENED_SEP.join(remaining)

    line2_visible = _visible_width(line2)
    if line2_visible > available:
        line2 = truncate_ansi(line2, available)

    return line1 + "\n" + line2


def render_categories(
    where: list[str],
    who: list[str],
    what: list[str],
    metrics: list[str],
    state: list[str],
) -> str:
    """Join category segments into final status line string.

    Where parts are concatenated directly (path + branch).
    All other segments are flattened with SEP between each — no visual
    distinction between within-category and between-category separators.
    """
    parts: list[str] = []

    if where:
        parts.append("".join(where))

    for category in (who, what, metrics, state):
        for segment in category:
            parts.append(f" {SEP} {segment}")

    return "".join(parts)


@click.command(name="status-line", hidden=True)
def status_line() -> None:
    """Generate status line for Claude Code.

    Reads JSON from stdin (Claude Code's status line contract),
    outputs formatted status line to stdout.

    This command is invoked by Claude Code's statusLine setting.

    Exempt from automatic debug logging (runs every poll cycle).
    Enable via FORGE_DEBUG=1 or config.yaml log_level: debug.
    Logs to $FORGE_HOME/logs/cli/status-line.<PID>.log.
    """
    # Status-line configures its own logging (exempt from main.py auto-config,
    # same pattern as hooks/_group.py).
    from forge.core.logging import configure_debug_logging

    configure_debug_logging(component="status-line", subdirectory="cli")

    try:
        json_data = sys.stdin.read()
        if not json_data.strip():
            click.echo(f"{RED}[Error: No input]{RESET}", color=True)
            return

        data = json.loads(json_data)
    except json.JSONDecodeError:
        click.echo(f"{RED}[Error: Invalid JSON]{RESET}", color=True)
        return

    if not isinstance(data, dict):
        click.echo(f"{RED}[Error: Invalid input]{RESET}", color=True)
        return
    if not isinstance(data.get("workspace"), dict):
        data["workspace"] = {}

    logger.debug("env: FORGE_HOME=%s", os.environ.get("FORGE_HOME", "<unset>"))
    logger.debug("env: ANTHROPIC_BASE_URL=%s", os.environ.get("ANTHROPIC_BASE_URL", "<unset>"))
    logger.debug("env: FORGE_SESSION=%s", os.environ.get("FORGE_SESSION", "<unset>"))
    logger.debug("input keys: %s", list(data.keys()))
    logger.debug(
        "workspace.current_dir: %s",
        data.get("workspace", {}).get("current_dir", "<missing>"),
    )

    # Resolve the registry-owned source plan before any live proxy or durable
    # session work. A configured segment may trigger only the sources declared
    # by its registry entry; each requested source is acquired once and shared
    # by every producer through RenderContext.
    from forge.cli.statusline.context import RenderContext
    from forge.cli.statusline.palette import apply_palette
    from forge.cli.statusline.registry import StatusSource, render_plan, resolve_plan
    from forge.runtime_config import get_runtime_config

    config = get_runtime_config()
    plan = resolve_plan(config.statusline.segments)
    logger.debug("status-line: required sources=%s", sorted(source.value for source in plan.sources))

    if StatusSource.PROXY in plan.sources:
        is_proxy, runtime, is_proxy_authoritative = status_sources.detect_proxy()
    else:
        is_proxy, runtime, is_proxy_authoritative = False, None, False

    logger.debug("proxy: is_proxy=%s, authoritative=%s", is_proxy, is_proxy_authoritative)
    if runtime:
        logger.debug(
            "proxy: template=%s, tier_mappings=%s",
            runtime.template,
            runtime.tier_mappings,
        )
    else:
        logger.debug("proxy: runtime=None")

    if StatusSource.SESSION in plan.sources:
        session_manifest, is_session_authoritative = status_sources.discover_session()
    else:
        session_manifest, is_session_authoritative = None, False
    session_name = session_manifest.get("name") if session_manifest else None
    logger.debug("session: name=%s, authoritative=%s", session_name, is_session_authoritative)
    logger.debug(
        "context_window raw: %s (type=%s)",
        data.get("context_window"),
        type(data.get("context_window")).__name__,
    )

    # Build the render context once, then let the segment registry produce the
    # line. RenderContext is lazy (cached_property): a transcript scan or git
    # subprocess runs only if an enabled segment accesses it. The registry routes
    # producer output into a `where` list (concatenated) + a `stream` list
    # (separator-joined), preserving today's exact order via DEFAULT_ORDER.
    ctx = RenderContext(
        data=data,
        is_proxy=is_proxy,
        runtime=runtime,
        is_proxy_authoritative=is_proxy_authoritative,
        manifest=session_manifest,
        is_session_authoritative=is_session_authoritative,
        config=config,
        forge_root=os.environ.get("FORGE_FORGE_ROOT"),
    )
    where, stream = render_plan(ctx, plan)

    # === RENDER ===
    output = render_categories(where, [], [], stream, [])
    # Recolor by the configured palette (default == no-op: empty remap).
    output = apply_palette(output, ctx.palette)

    # Output hardening (from ccstatusline)
    # ANSI reset prefix: override Claude Code's dim default styling
    output = "\x1b[0m" + output
    # Non-breaking spaces: prevent VSCode terminal from trimming
    output = output.replace(" ", "\u00a0")

    # Wrap or truncate to prevent terminal line wrapping (which causes Forge output
    # to overlap Claude Code's native status on the next terminal row). Prefers
    # wrapping at a | separator boundary (preserves all info on two lines) over
    # truncation with '...' (loses info). Always on by default; set
    # FORGE_STATUS_TRUNCATE=0 to disable.
    if os.environ.get("FORGE_STATUS_TRUNCATE") != "0":
        term_width = _get_terminal_width()
        available = term_width - TRAILING_MARGIN - NATIVE_DISPLAY_RESERVE
        if available > 3:
            display_width = _visible_width(output)
            if display_width + TRAILING_MARGIN + NATIVE_DISPLAY_RESERVE > term_width:
                output = _wrap_output(output, available)

    # Trailing margin on each line: RESET prevents color bleed, NBSP padding
    # prevents visual merging with Claude Code's native token display.
    margin = RESET + "\u00a0" * TRAILING_MARGIN
    output = "\n".join(line + margin for line in output.split("\n"))

    logger.debug(
        "output line_count=%d, visible_width=%d, term_width=%d",
        output.count("\n") + 1,
        _visible_width(output.split("\n")[0]),
        _get_terminal_width(),
    )

    # Force color=True since Claude Code pipes output (not a TTY)
    click.echo(output, color=True)
