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
    if ctx.is_proxy:
        proxy_cost = ctx.runtime.proxy_cost_usd if ctx.runtime else 0.0
        return sl.get_session_metrics(ctx.cost_data, True, proxy_cost_usd=proxy_cost)
    # Direct session: dollars are real only under API billing.
    if ctx.billing_mode == "api":
        return sl.get_session_metrics(ctx.cost_data, False)
    return sl.format_billing_cost(ctx.billing_mode, ctx.cost_data, ctx.data.get("rate_limits"))


def _produce_rate_limits(ctx: RenderContext) -> Optional[str]:
    # Under subscription/ambiguous billing the cost segment already shows the 5h
    # quota; suppress the standalone segment when cost is in the active layout to
    # avoid showing the same number twice.
    if ctx.billing_mode in ("subscription", "ambiguous") and "cost" in ctx.active_segments:
        return None
    return sl.format_rate_limits(ctx.data.get("rate_limits"), ctx.is_proxy, show_reset=True)


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


def _produce_cache_hit(ctx: RenderContext) -> Optional[str]:
    if ctx.config.statusline.cache_hit == "off":
        return None
    if ctx.is_proxy:
        # Proxy already computes this — free read, no transcript scan, no file.
        rate = ctx.runtime.raw.get("metrics", {}).get("cache_hit_rate") if ctx.runtime else None
    else:
        # Direct mode: deduped transcript computation, throttled on disk.
        from forge.cli.statusline.throttle import read_or_compute

        rate = read_or_compute(
            ctx.transcript_path,
            ctx.session_id,
            ctx.config.statusline.cache_hit_ttl,
            sl.compute_cache_hit_rate,
        )
    if rate is None:
        return None
    return sl.format_cache_hit(rate)


def _confirmed_bundles(ctx: RenderContext) -> Optional[list[str]]:
    confirmed = (ctx.manifest or {}).get("confirmed")
    cpolicy = confirmed.get("policy") if isinstance(confirmed, dict) else None
    bundles = cpolicy.get("bundles") if isinstance(cpolicy, dict) else None
    return bundles if isinstance(bundles, list) and bundles else None


def _produce_supervisor(ctx: RenderContext) -> Optional[str]:
    # Effective (intent+overrides) posture: a %supervisor suspend override flips
    # this without touching intent. Hidden entirely when no supervisor is set.
    # policy.enabled gates the whole subsystem — a disabled policy means the
    # supervisor is configured but not watching (the hook exits early).
    policy = ctx.effective_intent.get("policy")
    if not isinstance(policy, dict):
        return None
    supervisor = policy.get("supervisor")
    if not isinstance(supervisor, dict):
        return None
    return sl.format_supervisor(
        suspended=bool(supervisor.get("suspended", False)),
        enabled=bool(policy.get("enabled", False)),
    )


def _produce_policy(ctx: RenderContext) -> Optional[str]:
    # Effective intent is authoritative: an override that empties or disables the
    # bundle list must NOT revive stale confirmed bundles. Fall back to the
    # last-evaluated confirmed posture only when intent carries no policy at all.
    policy = ctx.effective_intent.get("policy")
    if isinstance(policy, dict):
        bundles = policy.get("bundles")
        if not isinstance(bundles, list) or not bundles:
            return None
        return sl.format_policy(bundles, enabled=bool(policy.get("enabled", False)))
    bundles = _confirmed_bundles(ctx)
    if bundles is None:
        return None
    return sl.format_policy(bundles)


def _produce_audit(ctx: RenderContext) -> Optional[str]:
    # Proxy-only: intercept posture lives in GET / runtime truth.
    if not ctx.is_proxy or ctx.runtime is None:
        return None
    raw = ctx.runtime.raw
    mode = raw.get("intercept_mode")
    if not isinstance(mode, str) or not mode:
        return None
    intercept = raw.get("intercept")
    thinking_preserved = bool(intercept.get("thinking_blocks_preserved")) if isinstance(intercept, dict) else False
    return sl.format_audit(mode, thinking_preserved)


def _produce_drift(ctx: RenderContext) -> Optional[str]:
    # Proxy-only: compare the backend this request actually routes to against the
    # model Claude Code reports. Routing prefers an explicit tier in the model
    # name over the proxy default (server.py:779), and runtime.active_tier is only
    # the *default* tier — so derive the route tier from stdin model.id first and
    # fall back to active_tier, mirroring the proxy. Needs model.id (not
    # display_name) to normalize.
    if not ctx.is_proxy or ctx.runtime is None:
        return None
    mappings = ctx.runtime.tier_mappings
    if not isinstance(mappings, dict) or not mappings:
        return None
    model_id = (ctx.data.get("model") or {}).get("id")
    if not model_id:
        return None
    route_tier = sl.explicit_tier_from_model(str(model_id)) or ctx.runtime.active_tier
    if not route_tier:
        return None
    backend = mappings.get(route_tier)
    if not backend:
        return None
    return sl.format_drift(str(model_id), str(backend))


def _produce_spend_cap(ctx: RenderContext) -> Optional[str]:
    # Proxy-only: spend caps live in GET / metrics.costs.caps. Absent when no caps
    # are configured or on a registry-fallback proxy (no live metrics snapshot).
    if not ctx.is_proxy or ctx.runtime is None:
        return None
    metrics = ctx.runtime.raw.get("metrics")
    costs = metrics.get("costs") if isinstance(metrics, dict) else None
    caps = costs.get("caps") if isinstance(costs, dict) else None
    if not isinstance(caps, dict) or not caps:
        return None
    return sl.format_spend_cap(caps)


# Every segment name now has a producer (no reserved names remain). The
# allowlist == producer-names equality test (test_statusline_registry.py)
# enforces this two-way sync whenever a segment is added.
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
    Segment("cache_hit", _produce_cache_hit),
    Segment("supervisor", _produce_supervisor),
    Segment("policy", _produce_policy),
    Segment("audit", _produce_audit),
    Segment("drift", _produce_drift),
    Segment("spend_cap", _produce_spend_cap),
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
    order = resolve_order(configured)
    ctx.active_segments = set(order)  # let producers see what else is active
    where: list[str] = []
    stream: list[str] = []
    for name in order:
        segment = _BY_NAME[name]
        rendered = segment.producer(ctx)
        if rendered is None:
            continue
        (where if segment.bucket == "where" else stream).append(rendered)
    return where, stream
