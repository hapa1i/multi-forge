"""Render context for the status line.

Built once per ``status_line()`` invocation and passed to every segment producer.
Expensive derivations (transcript scan, git branch, context parsing) are
``cached_property`` so they run at most once AND only if an enabled segment
actually accesses them — e.g. ``segments: [path, model]`` does no transcript
scan and no git subprocess.

Helpers come from ``forge.cli.status_line`` via module-attribute lookup at call
time (so tests can patch them, and so the import direction stays acyclic — see
the module docstring in ``registry.py``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
from typing import Any

from forge.cli import status_line as sl
from forge.cli.status_line import ProxyRuntimeTruth, TranscriptStats
from forge.cli.statusline.palette import (
    Glyphs,
    Palette,
    resolve_glyphs,
    resolve_palette,
)
from forge.core.ops.usage_summary import SupervisorHealth
from forge.runtime_config import RuntimeConfig

_COST_MICROS_PER_USD = 1_000_000


@dataclass
class RenderContext:
    """Inputs + lazily-derived values shared across segment producers."""

    data: dict[str, Any]
    is_proxy: bool
    runtime: ProxyRuntimeTruth | None
    is_proxy_authoritative: bool
    manifest: dict[str, Any] | None
    is_session_authoritative: bool
    config: RuntimeConfig

    # FORGE_FORGE_ROOT (None for ambient sessions). Namespaces the forge_cost
    # throttle cache key so same-named sessions in different forge roots don't
    # collide; not part of any ledger query (the ledger filters by session name).
    forge_root: str | None = None

    # Set by render_segments() to the resolved render order, so a producer can
    # see what else is active (e.g. rate_limits suppresses itself when cost
    # already shows the quota). Empty until render_segments runs.
    active_segments: set[str] = field(default_factory=set)

    # --- Cheap raw accessors (no I/O) ---

    @property
    def workspace_dir(self) -> str:
        return self.data.get("workspace", {}).get("current_dir", "")

    @property
    def raw_model_name(self) -> str:
        return self.data.get("model", {}).get("display_name", "Claude")

    @property
    def transcript_path(self) -> str:
        return self.data.get("transcript_path", "")

    @property
    def session_id(self) -> str | None:
        return self.data.get("session_id")

    @property
    def cost_data(self) -> dict[str, Any]:
        return self.data.get("cost") or {}

    @property
    def proxy_cost_baseline_micros(self) -> int | None:
        """Launch-time proxy cost baseline from ``confirmed.launch``."""
        confirmed = (self.manifest or {}).get("confirmed")
        launch = confirmed.get("launch") if isinstance(confirmed, dict) else None
        baseline = launch.get("proxy_cost_baseline_micros") if isinstance(launch, dict) else None
        if isinstance(baseline, bool) or not isinstance(baseline, int):
            return None
        return max(0, baseline)

    @property
    def proxy_cost_baseline_started_at(self) -> str | None:
        """Proxy metrics process timestamp captured with the launch baseline."""
        confirmed = (self.manifest or {}).get("confirmed")
        launch = confirmed.get("launch") if isinstance(confirmed, dict) else None
        started_at = launch.get("proxy_cost_baseline_started_at") if isinstance(launch, dict) else None
        return started_at if isinstance(started_at, str) and started_at else None

    @property
    def proxy_runtime_started_at(self) -> str | None:
        """Current proxy metrics process timestamp."""
        metrics = self.runtime.raw.get("metrics") if self.runtime else None
        started_at = metrics.get("started_at") if isinstance(metrics, dict) else None
        return started_at if isinstance(started_at, str) and started_at else None

    @property
    def scoped_proxy_cost_usd(self) -> float:
        """Proxy-reported cost scoped to this launch when a baseline exists."""
        if not self.runtime:
            return 0.0
        current = self.runtime.proxy_cost_usd
        if isinstance(current, bool) or not isinstance(current, (int, float)) or current <= 0:
            return 0.0

        baseline = self.proxy_cost_baseline_micros
        if baseline is None:
            return float(current)

        baseline_started_at = self.proxy_cost_baseline_started_at
        runtime_started_at = self.proxy_runtime_started_at
        if baseline_started_at and runtime_started_at and baseline_started_at != runtime_started_at:
            return float(current)

        current_micros = int(round(float(current) * _COST_MICROS_PER_USD))
        if current_micros >= baseline:
            return (current_micros - baseline) / _COST_MICROS_PER_USD

        # The proxy likely restarted after launch and reset its cumulative
        # metrics. Do not subtract an old-process baseline from a new-process
        # total; the current proxy total is the best available scoped value.
        return float(current)

    @property
    def palette(self) -> Palette:
        return resolve_palette(self.config.statusline.palette)

    @property
    def glyphs(self) -> Glyphs:
        return resolve_glyphs(self.config.statusline.glyphs)

    @property
    def billing_mode(self) -> str:
        """``api`` | ``subscription`` | ``ambiguous`` (explicit declaration only).

        Only an explicit ``cost_mode`` asserts a payer. ``auto`` stays
        ``ambiguous``: a key in the env is a capability, not proof of who pays
        (Forge may have hydrated it into an OAuth session), so it must not flip
        the display to API dollars. ``format_billing_cost`` then shows the 5h
        quota when present, else hedges ``≈$``.
        """
        mode = self.config.statusline.cost_mode
        if mode in ("api", "subscription"):
            return mode
        return "ambiguous"

    # --- Lazy derivations (run once, only if accessed) ---

    @cached_property
    def transcript_stats(self) -> TranscriptStats:
        return sl._cached_scan_transcript(self.transcript_path)

    @cached_property
    def git_branch(self) -> str | None:
        return sl.get_git_branch(self.workspace_dir)

    @cached_property
    def context_info(self) -> dict[str, Any] | None:
        info = sl.parse_context_from_json(self.data)
        # Proxy runtime truth overrides the context window when available.
        if self.is_proxy and self.runtime and self.runtime.active_context_window and info:
            tokens = info.get("tokens", 0)
            window = self.runtime.active_context_window
            info["context_window"] = window
            info["percent"] = min(100, int((tokens / window) * 100))
        return info

    @cached_property
    def effective_context_window(self) -> int | None:
        return sl.get_effective_context_window(self.data, self.runtime, self.context_info)

    @cached_property
    def effective_intent(self) -> dict[str, Any]:
        """Session intent with overrides applied (the in-force posture).

        ``%policy disable`` / ``%supervisor suspend`` write sparse overrides and
        leave ``intent`` untouched, so the supervisor/policy producers must read
        this merged view, not raw intent. ``apply_overrides`` is a pure dict merge
        — no ``SessionState``/dacite construction on the hot path. Manifest is
        Forge-owned, but the status line is fail-open, so non-dict shapes degrade
        to ``{}`` rather than raise.
        """
        if not self.manifest:
            return {}
        intent = self.manifest.get("intent")
        if not isinstance(intent, dict):
            return {}
        overrides = self.manifest.get("overrides")
        if not isinstance(overrides, dict):
            return intent
        from forge.session.effective import apply_overrides

        return apply_overrides(intent, overrides)

    @cached_property
    def supervisor_health(self) -> SupervisorHealth | None:
        """Recent frontier-supervisor fail-open health for the bar (throttled, fail-open).

        ``None`` when there is no Forge session to attribute to, or when the throttled
        ledger read fails open. Manifest-gated and root-scoped exactly like the
        ``forge_cost`` segment; the throttle is time-only (supervisor fail-opens accrue via
        ledger writes that never touch the transcript). Lazy `cached_property`: the ledger
        read happens only if the (opt-in) supervisor producer reads this.
        """
        name = (self.manifest or {}).get("name")
        if not isinstance(name, str) or not name:  # manifest-gated, like _produce_forge_cost
            return None

        from forge.cli.statusline.throttle import read_or_compute_session_health
        from forge.core.ops.usage_summary import read_supervisor_health
        from forge.core.state import parse_iso

        # Bound the scan to events at/after session creation (an event cannot predate it);
        # a malformed/absent created_at falls back to an unbounded scan.
        since = None
        created_raw = (self.manifest or {}).get("created_at")
        if isinstance(created_raw, str):
            try:
                since = parse_iso(created_raw)
            except ValueError:
                since = None

        cache_key = f"{self.forge_root or ''}\x00{name}"
        return read_or_compute_session_health(
            cache_key,
            self.config.statusline.forge_cost_ttl,
            lambda: read_supervisor_health(name, since=since),
        )
