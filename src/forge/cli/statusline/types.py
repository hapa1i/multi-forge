"""Neutral facts shared by status-line acquisition and rendering."""

from __future__ import annotations

from typing import Any, NamedTuple

__all__ = ["ProxyRuntimeTruth", "TranscriptStats"]


class ProxyRuntimeTruth:
    """Structured proxy runtime truth from the proxy identity endpoint."""

    def __init__(self, raw: dict[str, Any]):
        self.raw = raw
        self.is_proxy = raw.get("is_proxy", False)

        # Proxy identity (B2.1)
        proxy = raw.get("proxy", {})
        self.proxy_id = proxy.get("proxy_id")
        self.template = proxy.get("template") or raw.get("template", "unknown")
        self.port = proxy.get("port")
        self.base_url = proxy.get("base_url")

        # Runtime truth
        runtime = raw.get("runtime", {})
        self.active_tier = runtime.get("active_tier")
        self.active_context_window = runtime.get("active_context_window")
        self.context_windows = runtime.get("context_windows", {})
        self.tier_mappings = runtime.get("tier_mappings", {})

        # Older proxy response shape (system boundary: proxy HTTP response)
        self.tiers = raw.get("tiers", {})

    def get_context_window_for_tier(self, tier: str) -> int | None:
        """Get context window for a tier, preferring runtime truth."""
        if tier in self.context_windows:
            return self.context_windows[tier]
        tier_info = self.tiers.get(tier, {})
        return tier_info.get("context_window")

    @property
    def proxy_cost_usd(self) -> float:
        """Total estimated proxy cost in USD from the metrics snapshot."""
        metrics = self.raw.get("metrics", {})
        costs = metrics.get("costs", {})
        return costs.get("total_usd", 0.0)


class TranscriptStats(NamedTuple):
    """Results from one transcript scan."""

    has_thinking: bool = False
    user_count: int = 0
    tool_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
