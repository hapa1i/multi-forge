"""Verb-level cost attribution via proxy metric snapshot deltas.

Wraps subprocess invocations (panel, supervisor, memory-writer, etc.) to
measure cost by snapshotting proxy metrics before and after execution.
Results populate the yielded holder for usage attribution. Downstream request
records joined by run-tree identity back the proxy spend surface.

All verb costs are marked ``estimated`` because concurrent proxy traffic
(e.g., the main interactive session) may share the same proxy during
the measurement window.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ProxyCostDelta:
    """Cost delta for a single proxy between two snapshots."""

    base_url: str
    cost_micros: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    request_count: int = 0
    # Count of requests that reported a cost in the window. Distinguishes a real
    # reported $0 from "no dollar evidence" — cost_micros is 0 in both cases.
    reported_request_count: int = 0


@dataclass
class VerbCostResult:
    """Aggregated cost attribution for one verb invocation.

    Also serves as the holder ``track_verb_cost`` yields: it is populated in
    place on context exit, so a caller can read the (estimated) delta for usage
    attribution. ``measured`` is True when a proxy snapshot delta was captured
    (tokens are real); ``cost_measured`` is True only when the window also had a
    reported-cost request — so a passthrough verb (tokens but no reported cost)
    is ``measured`` yet not ``cost_measured`` (its $0 is "no figure," not a real $0).
    """

    verb: str
    total_cost_micros: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    request_count: int = 0
    duration_ms: float = 0.0
    estimated: bool = True
    measured: bool = False
    cost_measured: bool = False
    per_proxy: list[ProxyCostDelta] = field(default_factory=list)


def _fetch_snapshot(base_url: str, timeout: float = 2.0) -> dict[str, Any] | None:
    """Fetch proxy metrics via GET /. Returns None on failure."""
    try:
        normalized = base_url if "://" in base_url else f"http://{base_url}"
        url = normalized.rstrip("/") + "/"
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read())
        if data.get("is_proxy") and "metrics" in data:
            return data["metrics"]
    except Exception as e:
        logger.debug("Failed to fetch proxy snapshot from %s: %s", base_url, e)
    return None


def _compute_delta(before: dict[str, Any], after: dict[str, Any], base_url: str) -> ProxyCostDelta:
    """Compute the difference between two proxy metric snapshots."""
    b_tokens = before.get("tokens", {})
    a_tokens = after.get("tokens", {})
    b_costs = before.get("costs", {})
    a_costs = after.get("costs", {})

    # Clamp every delta at >= 0. A proxy restart/reset between the before/after
    # snapshots makes `after < before`, which would otherwise log a negative
    # "spend"/token delta -- and a negative cost delta inflates the unattributed
    # "Interactive" residual in `forge telemetry costs show`. A reset means "no attributable
    # delta for this verb," not negative usage.
    return ProxyCostDelta(
        base_url=base_url,
        cost_micros=max(0, a_costs.get("total_micros", 0) - b_costs.get("total_micros", 0)),
        input_tokens=max(0, a_tokens.get("input", 0) - b_tokens.get("input", 0)),
        output_tokens=max(0, a_tokens.get("output", 0) - b_tokens.get("output", 0)),
        cached_tokens=max(0, a_tokens.get("cached", 0) - b_tokens.get("cached", 0)),
        request_count=max(0, after.get("total_requests", 0) - before.get("total_requests", 0)),
        reported_request_count=max(
            0, a_costs.get("reported_request_count", 0) - b_costs.get("reported_request_count", 0)
        ),
    )


def resolve_subprocess_proxy_url() -> str | None:
    """Resolve the current FORGE_SUBPROCESS_PROXY to a base URL, if configured."""
    from forge.core.reactive.env import (
        FORGE_SUBPROCESS_BASE_URL_VAR,
        FORGE_SUBPROCESS_PROXY_VAR,
    )
    from forge.core.reactive.proxy import lookup_proxy_base_url

    injected_url = os.environ.get(FORGE_SUBPROCESS_BASE_URL_VAR)
    if injected_url:
        return injected_url

    proxy = os.environ.get(FORGE_SUBPROCESS_PROXY_VAR)
    if not proxy:
        return None

    try:
        return lookup_proxy_base_url(proxy)
    except Exception:
        return None


def resolve_proxy_urls(specs: list[Any]) -> list[str]:
    """Extract unique proxy base URLs from a list of ModelSpecs.

    For specs with no explicit proxy, falls back to FORGE_SUBPROCESS_PROXY
    when configured.
    Deduplicates by resolved URL.
    """
    from forge.core.reactive.env import (
        FORGE_SUBPROCESS_BASE_URL_VAR,
        FORGE_SUBPROCESS_PROXY_VAR,
    )
    from forge.core.reactive.proxy import lookup_proxy_base_url

    subprocess_proxy = os.environ.get(FORGE_SUBPROCESS_PROXY_VAR)
    subprocess_base_url = os.environ.get(FORGE_SUBPROCESS_BASE_URL_VAR)
    seen: set[str] = set()
    urls: list[str] = []
    for spec in specs:
        proxy = getattr(spec, "preferred_proxy", None) or getattr(spec, "proxy", None) or subprocess_proxy
        if not proxy:
            continue
        try:
            url: str | None
            if subprocess_base_url and proxy == subprocess_proxy:
                url = subprocess_base_url
            else:
                url = lookup_proxy_base_url(proxy)
            if url and url not in seen:
                seen.add(url)
                urls.append(url)
        except Exception:
            pass
    return urls


def resolve_proxy_urls_from_plan(plan: Any) -> list[str]:
    """Extract unique proxy base URLs from a WorkerRoutingPlan.

    Uses actual routing decisions (correct for --proxy, subprocess proxy,
    route scan, and session proxy fallback).
    """
    seen: set[str] = set()
    urls: list[str] = []
    for result in plan.routes:
        url = result.base_url
        if url and url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


@contextmanager
def track_verb_cost(verb: str, proxy_base_urls: list[str]):
    """Snapshot proxy metrics across all proxies before/after a verb invocation.

    Args:
        verb: Origin label ("panel", "supervisor", "memory-writer", etc.)
        proxy_base_urls: ALL proxy base URLs this verb will use.
            Direct workers (no proxy) are excluded — only proxied
            requests have cost data at the proxy level.

    Yields a :class:`VerbCostResult` holder, populated in place on exit so a
    caller can read the (estimated) delta after the block for usage attribution
    (``with track_verb_cost(...) as cost: ...``). Callers that don't bind it are
    unaffected. On exit the verb-cost record is still logged as before; a
    no-proxy verb yields an unmeasured holder (``measured=False``).
    """
    holder = VerbCostResult(verb=verb)
    unique_urls = list(dict.fromkeys(u for u in proxy_base_urls if u))

    snapshots_before: dict[str, dict[str, Any]] = {}
    for url in unique_urls:
        snap = _fetch_snapshot(url)
        if snap is not None:
            snapshots_before[url] = snap

    start = time.monotonic()
    try:
        yield holder
    finally:
        # Always record wall-clock latency, even for a no-proxy verb -- the work
        # still took real time and the usage ledger records latency_ms.
        holder.duration_ms = (time.monotonic() - start) * 1000

        if unique_urls:
            try:
                deltas: list[ProxyCostDelta] = []
                for url in unique_urls:
                    if url not in snapshots_before:
                        continue
                    after = _fetch_snapshot(url)
                    if after is None:
                        continue
                    deltas.append(_compute_delta(snapshots_before[url], after, url))

                # Populate the holder in place so the (already-yielded) caller sees it.
                holder.total_cost_micros = sum(d.cost_micros for d in deltas)
                holder.input_tokens = sum(d.input_tokens for d in deltas)
                holder.output_tokens = sum(d.output_tokens for d in deltas)
                holder.cached_tokens = sum(d.cached_tokens for d in deltas)
                holder.request_count = sum(d.request_count for d in deltas)
                holder.estimated = True
                # measured=True only when a real snapshot delta was captured, so callers
                # can tell "no proxy / no data" from a captured window.
                holder.measured = bool(deltas)
                # cost_measured=True only when the window had a reported-cost request, so
                # a tokens-only passthrough verb reports cost-unavailable, not a fake $0.
                holder.cost_measured = sum(d.reported_request_count for d in deltas) > 0
                holder.per_proxy = deltas
            except Exception as e:
                logger.warning("Failed to track verb cost for %s: %s", verb, e)
