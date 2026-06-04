"""Status-line segment registry.

Each ``Segment`` pairs a name with a *producer* — a thin adapter over the
``format_*`` helpers in ``forge.cli.status_line`` that returns the segment's
rendered string (or ``None`` to omit it). ``status_line()`` resolves the
configured order, runs the producers, and routes their output into two buckets:

- ``where`` — concatenated with no separator (``path`` + ``branch``).
- ``stream`` — separator-joined (everything else).

The renderer then feeds these to the unchanged ``render_categories()`` so the
wrap/harden tail is untouched. With the default (empty) config the resolved
order is ``names.DEFAULT_ORDER``, which reproduces today's exact output — the
golden guard in ``tests/src/cli/test_statusline_registry.py`` enforces this.

Import direction (avoids a cycle): this module imports ``status_line`` at module
level; ``status_line()`` imports this module LAZILY, so status_line.py's
top-level never pulls in the registry. Producers reach helpers via ``sl.<name>``
(module-attribute lookup at call time), which is also what lets tests patch them.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Optional

from forge.cli import status_line as sl
from forge.cli.statusline.context import RenderContext
from forge.cli.statusline.names import DEFAULT_ORDER

logger = logging.getLogger(__name__)

Producer = Callable[[RenderContext], Optional[str]]


@dataclass(frozen=True)
class Segment:
    """A named, ordered status-line atom.

    bucket: ``"where"`` (concatenated, leads the line) or ``"stream"``
    (separator-joined). The bucket is a fixed property of the segment, not
    user-reorderable across buckets.
    """

    name: str
    producer: Producer
    bucket: str = "stream"


# --- Producers (thin adapters; each mirrors one slice of the old inline assembly) ---


def _produce_path(ctx: RenderContext) -> Optional[str]:
    return f"{sl.GREEN_BOLD}{sl.get_compact_path(ctx.workspace_dir)}{sl.RESET}"


def _produce_branch(ctx: RenderContext) -> Optional[str]:
    branch = ctx.git_branch
    if not branch:
        return None
    return f" ({sl.YELLOW_BOLD}{branch}{sl.RESET})"


def _produce_breadcrumb(ctx: RenderContext) -> Optional[str]:
    if not ctx.manifest:
        return None
    breadcrumb = sl.format_breadcrumb(ctx.manifest, ctx.is_session_authoritative)
    if not breadcrumb:
        return None
    return f"{sl.BREADCRUMB_COLOR}{breadcrumb}{sl.RESET}"


def _produce_model(ctx: RenderContext) -> Optional[str]:
    info = ctx.context_info
    glyphs = (ctx.glyphs.filled, ctx.glyphs.empty)
    model_name = sl.format_model_label(ctx.raw_model_name, ctx.effective_context_window)

    tier_display = sl.get_tier_display(ctx.runtime) if ctx.is_proxy else None
    if tier_display:
        model_segment = f"[{tier_display}] {sl.get_context_display(info, glyphs)}"
    else:
        detected_tier = sl.get_tier_from_display_name(ctx.raw_model_name)
        model_color = sl._tier_color(detected_tier, ctx.runtime)
        model_segment = f"{model_color}[{model_name}]{sl.RESET} {sl.get_context_display(info, glyphs)}"

    if ctx.is_proxy and ctx.runtime and ctx.runtime.template and ctx.runtime.template != "unknown":
        suffix = "" if ctx.is_proxy_authoritative else "(~)"
        return f"{sl.TEMPLATE_COLOR}{ctx.runtime.template}{suffix}{sl.RESET} {model_segment}"
    return model_segment


def _produce_cost(ctx: RenderContext) -> Optional[str]:
    proxy_cost = ctx.runtime.proxy_cost_usd if ctx.runtime else 0.0
    return sl.get_session_metrics(ctx.cost_data, ctx.is_proxy, proxy_cost_usd=proxy_cost)


def _produce_rate_limits(ctx: RenderContext) -> Optional[str]:
    return sl.format_rate_limits(ctx.data.get("rate_limits"), ctx.is_proxy)


def _produce_lines(ctx: RenderContext) -> Optional[str]:
    return sl.format_line_changes(ctx.cost_data, ctx.workspace_dir)


def _produce_tokens(ctx: RenderContext) -> Optional[str]:
    input_tokens, output_tokens, cached_tokens = sl.get_token_breakdown_values(ctx.data, ctx.transcript_stats)
    return sl.format_token_breakdown(input_tokens, output_tokens, cached_tokens)


def _produce_think(ctx: RenderContext) -> Optional[str]:
    if ctx.transcript_stats.has_thinking:
        return f"{sl.BLUE}{sl.THINKING_INDICATOR}{sl.RESET}"
    return None


def _produce_loop(ctx: RenderContext) -> Optional[str]:
    if not ctx.manifest:
        return None
    return sl.format_verification(ctx.manifest)


def _produce_sidecar(ctx: RenderContext) -> Optional[str]:
    if not ctx.manifest:
        return None
    return sl.format_sidecar(ctx.manifest)


# Producers implemented so far. Later phases add cache_hit/supervisor/policy/
# audit/spend_cap/drift — their names already live in names.SEGMENT_NAMES so the
# config allowlist is stable across the rollout; until a producer exists the
# renderer drops the name (debug-logged).
SEGMENTS: tuple[Segment, ...] = (
    Segment("path", _produce_path, "where"),
    Segment("branch", _produce_branch, "where"),
    Segment("breadcrumb", _produce_breadcrumb),
    Segment("model", _produce_model),
    Segment("cost", _produce_cost),
    Segment("rate_limits", _produce_rate_limits),
    Segment("lines", _produce_lines),
    Segment("tokens", _produce_tokens),
    Segment("think", _produce_think),
    Segment("loop", _produce_loop),
    Segment("sidecar", _produce_sidecar),
)

_BY_NAME: dict[str, Segment] = {seg.name: seg for seg in SEGMENTS}


def resolve_order(configured: list[str]) -> list[str]:
    """Resolve the configured segment list to renderable names.

    Empty → ``DEFAULT_ORDER``. Otherwise keep the user's order, dropping names
    with no producer (debug-logged — ``forge config set``/``edit`` is the strict
    allowlist gate; the renderer degrades silently per the boundary contract).

    If a non-empty config resolves to *nothing* renderable — only reachable via a
    hand-edited config.yaml or one written by a newer Forge, since the CLI gate
    rejects unknown names — fall back to ``DEFAULT_ORDER`` rather than emit a
    blank status line.
    """
    if not configured:
        return list(DEFAULT_ORDER)
    resolved: list[str] = []
    for name in configured:
        if name in _BY_NAME:
            resolved.append(name)
        else:
            logger.debug("status-line: dropping segment with no producer: %s", name)
    if not resolved:
        logger.debug("status-line: all configured segments dropped; falling back to DEFAULT_ORDER")
        return list(DEFAULT_ORDER)
    return resolved


def render_segments(ctx: RenderContext, configured: list[str]) -> tuple[list[str], list[str]]:
    """Run producers in resolved order, splitting output into (where, stream)."""
    where: list[str] = []
    stream: list[str] = []
    for name in resolve_order(configured):
        segment = _BY_NAME[name]
        rendered = segment.producer(ctx)
        if rendered is None:
            continue
        (where if segment.bucket == "where" else stream).append(rendered)
    return where, stream
