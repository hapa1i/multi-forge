"""Post-launch confirmation writers for the session manifest.

Split from session_lifecycle.py (file-size compliance + shared ownership):
both ``session_lifecycle`` and ``session_fork`` record launch facts, so the
writers live in a neutral module instead of one importing the other.

These functions write to the *confirmed* half of the manifest after a launch:

- ``record_launch_confirmed`` -- routing + api-key posture into ``confirmed.launch``
- ``_infer_launch_confirmation`` -- Claude session UUID/transcript backfill

Both are best-effort: a missing or mid-run-deleted manifest must never break a
launch (status-line UX is non-critical).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse
from urllib.request import urlopen

from forge.core.reactive.env import InteractiveApiKeyDecision
from forge.core.state import now_iso
from forge.session import SessionState, SessionStore
from forge.session.exceptions import SessionFileNotFoundError

logger = logging.getLogger(__name__)

# Shared surface: consumed by session_lifecycle and session_fork. The underscore
# helpers are module-internal by convention but imported by siblings, so they are
# named here to document the exported API.
__all__ = [
    "ProxyCostBaseline",
    "record_launch_confirmed",
    "read_proxy_cost_baseline",
    "read_proxy_cost_baseline_micros",
    "_routing_mode_for",
    "_infer_launch_confirmation",
]

_COST_MICROS_PER_USD = 1_000_000


@dataclass(frozen=True)
class ProxyCostBaseline:
    """Launch-time snapshot of proxy cumulative cost metrics."""

    cost_micros: int | None
    started_at: str | None


def record_launch_confirmed(
    store: SessionStore,
    *,
    routing_mode: str,
    proxy_id: str | None,
    base_url: str | None,
    decision: InteractiveApiKeyDecision,
    proxy_cost_baseline_micros: int | None = None,
    proxy_cost_baseline_started_at: str | None = None,
) -> None:
    """Write immutable launch facts to ``confirmed.launch``.

    Centralized so every interactive entry point -- start, resume, the host fork
    closures, and sidecar -- records the same shape. ``decision`` is the child's
    api-key posture: host callers pass
    ``compute_interactive_api_key_decision(interactive=True)``; the sidecar caller
    builds it from the container env (the in-container child, not the host).
    """
    from forge.session.models import LaunchConfirmed

    launch = LaunchConfirmed(
        routing_mode=routing_mode,
        proxy_id=proxy_id,
        base_url=base_url,
        proxy_cost_baseline_micros=proxy_cost_baseline_micros,
        proxy_cost_baseline_started_at=proxy_cost_baseline_started_at,
        api_key_available_to_child=decision.available,
        api_key_source=decision.source,
    )
    # Preflight: if the session was deleted in the window before this best-effort
    # write (e.g. a concurrent `forge session delete`), skip it. Entering
    # store.update() would make the lock layer mkdir-parents the session dir to hold
    # its lockfile, resurrecting a deleted session as a lock-only directory -- the
    # same guard _infer_launch_confirmation documents below.
    if not store.exists():
        logger.debug("record_launch_confirmed: session manifest already removed; skipping launch record")
        return
    try:
        store.update(timeout_s=5.0, mutate=lambda m: setattr(m.confirmed, "launch", launch))
    except Exception:
        # Best-effort status-line UX: a missing or locked manifest must not break the
        # launch (mirrors the claude_project_root preseed). The launch segment simply
        # won't render for this session. Also covers the narrow exists()->update()
        # delete race (the manifest vanishing between the preflight and the locked write).
        logger.debug("record_launch_confirmed: manifest update failed", exc_info=True)


def read_proxy_cost_baseline(base_url: str | None, *, timeout_s: float = 0.5) -> ProxyCostBaseline | None:
    """Read the live proxy's cumulative reported-cost snapshot.

    Status-line proxy metrics are exposed as process-lifetime counters. Capturing
    this launch-time baseline lets the renderer show the current session's spend
    instead of prior spend from a reused proxy. Best-effort: launch must proceed
    if the proxy is unavailable or returns an older/non-Forge response.
    """
    if not base_url:
        return None

    normalized = base_url if "://" in base_url else f"http://{base_url}"
    parsed = urlparse(normalized)
    if not parsed.hostname:
        return None
    root_url = urlunparse((parsed.scheme or "http", parsed.netloc, "/", "", "", ""))

    try:
        with urlopen(root_url, timeout=timeout_s) as response:
            payload = response.read(1_000_000)
        raw = json.loads(payload.decode("utf-8"))
    except Exception:
        logger.debug("read_proxy_cost_baseline: proxy metrics read failed", exc_info=True)
        return None

    if not isinstance(raw, dict) or raw.get("is_proxy") is not True:
        return None
    metrics = raw.get("metrics")
    costs = metrics.get("costs") if isinstance(metrics, dict) else None
    started_at = metrics.get("started_at") if isinstance(metrics, dict) else None
    started_at = started_at if isinstance(started_at, str) and started_at else None
    total_usd = costs.get("total_usd") if isinstance(costs, dict) else None
    if isinstance(total_usd, bool) or not isinstance(total_usd, (int, float)):
        return ProxyCostBaseline(cost_micros=None, started_at=started_at)
    if total_usd <= 0:
        return ProxyCostBaseline(cost_micros=0, started_at=started_at)
    return ProxyCostBaseline(cost_micros=int(round(float(total_usd) * _COST_MICROS_PER_USD)), started_at=started_at)


def read_proxy_cost_baseline_micros(base_url: str | None, *, timeout_s: float = 0.5) -> int | None:
    """Read only the live proxy's cumulative reported-cost total."""
    baseline = read_proxy_cost_baseline(base_url, timeout_s=timeout_s)
    return baseline.cost_micros if baseline else None


def _routing_mode_for(base_url: str | None, proxy_id: str | None) -> str:
    """Classify how an interactive launch reaches the model, for launch metadata."""
    if not base_url:
        return "direct"
    return "proxy" if proxy_id else "custom_base_url"


def _infer_launch_confirmation(
    *,
    store: SessionStore,
    manifest: SessionState,
    session_id: str | None,
) -> None:
    """Backfill transcript/runtime confirmation after a successful host launch."""
    if session_id is None or manifest.confirmed.is_sandboxed:
        return

    try:
        from forge.session.claude.paths import (
            get_transcript_path,
            resolve_claude_project_root,
        )
    except ImportError:
        return

    # Prefer persisted launch root; fall back to computed root
    if manifest.confirmed.claude_project_root:
        transcript_path = get_transcript_path(manifest.confirmed.claude_project_root, session_id)
    else:
        transcript_path = get_transcript_path(resolve_claude_project_root(manifest), session_id)
    if not transcript_path.is_file():
        return

    def _mutate(state: SessionState) -> None:
        # 1:1 model: overwrite UUID directly (no accumulation)
        state.confirmed.claude_session_id = session_id
        state.confirmed.transcript_path = str(transcript_path)
        state.confirmed.confirmed_at = now_iso()
        if state.confirmed.confirmed_by is None:
            state.confirmed.confirmed_by = "cli:launch:inferred"

    # Preflight: if the session was deleted while Claude ran, skip the backfill.
    # Entering store.update() would make the lock layer recreate the session dir
    # to hold its lockfile (file_lock mkdir-parents), resurrecting a deleted
    # session as a lock-only directory.
    if not store.exists():
        logger.debug("Skipping launch confirmation: session %r manifest already removed", manifest.name)
        return

    try:
        store.update(timeout_s=5.0, mutate=_mutate)
    except SessionFileNotFoundError:
        # Deleted in the narrow window between the exists() check and the locked
        # read; degrade quietly (no traceback).
        logger.debug("Skipping launch confirmation: session %r manifest removed mid-run", manifest.name)
