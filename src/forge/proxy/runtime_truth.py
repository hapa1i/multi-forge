"""Defensive, secret-free facts parsed from a proxy identity response."""

from __future__ import annotations

from typing import Any

from forge.core.identifiers import is_lowercase_identifier

_TIER_KEYS = frozenset({"haiku", "sonnet", "opus"})


class ProxyRuntimeTruth:
    """Structured proxy runtime truth from the proxy identity endpoint."""

    def __init__(self, raw: dict[str, Any]):
        self.raw = raw
        self.is_proxy = raw.get("is_proxy") is True

        proxy = raw.get("proxy", {})
        proxy = proxy if isinstance(proxy, dict) else {}
        self.proxy_id = _optional_string(proxy.get("proxy_id"))
        self.template = _optional_string(proxy.get("template")) or _optional_string(raw.get("template")) or "unknown"
        port = proxy.get("port")
        self.port = port if isinstance(port, int) and not isinstance(port, bool) else None
        self.base_url = _optional_string(proxy.get("base_url"))

        runtime = raw.get("runtime", {})
        runtime = runtime if isinstance(runtime, dict) else {}
        self.has_authoritative_route_truth = _has_authoritative_route_truth(runtime)
        self.backend_id = _optional_string(runtime.get("backend_id"))
        self.active_tier = _optional_string(runtime.get("active_tier"))
        active_context_window = runtime.get("active_context_window")
        self.active_context_window = (
            active_context_window
            if isinstance(active_context_window, int) and not isinstance(active_context_window, bool)
            else None
        )
        context_windows = runtime.get("context_windows", {})
        self.context_windows = context_windows if isinstance(context_windows, dict) else {}
        self.tier_mappings = _string_map(runtime.get("tier_mappings"))
        self.model_alternatives = _nested_string_map(runtime.get("model_alternatives"))

        tiers = raw.get("tiers", {})
        self.tiers = tiers if isinstance(tiers, dict) else {}

    def get_context_window_for_tier(self, tier: str) -> int | None:
        """Get context window for a tier, preferring runtime truth."""
        if tier in self.context_windows:
            value = self.context_windows[tier]
            return value if isinstance(value, int) and not isinstance(value, bool) else None
        tier_info = self.tiers.get(tier, {})
        if not isinstance(tier_info, dict):
            return None
        value = tier_info.get("context_window")
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    @property
    def proxy_cost_usd(self) -> float:
        """Total estimated proxy cost in USD from the metrics snapshot."""
        metrics = self.raw.get("metrics", {})
        metrics = metrics if isinstance(metrics, dict) else {}
        costs = metrics.get("costs", {})
        costs = costs if isinstance(costs, dict) else {}
        value = costs.get("total_usd", 0.0)
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _string_map(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {key: item for key, item in value.items() if isinstance(key, str) and key and isinstance(item, str) and item}


def _nested_string_map(value: object) -> dict[str, dict[str, str]]:
    if not isinstance(value, dict):
        return {}
    return {
        key: mapped for key, item in value.items() if isinstance(key, str) and key and (mapped := _string_map(item))
    }


def _has_authoritative_route_truth(runtime: dict[str, Any]) -> bool:
    """Return whether the new route fields are present and structurally intact."""
    if not {"backend_id", "model_alternatives", "tier_mappings"}.issubset(runtime):
        return False
    backend_id = runtime["backend_id"]
    if backend_id is not None and not is_lowercase_identifier(backend_id):
        return False
    tier_mappings = runtime["tier_mappings"]
    if (
        not isinstance(tier_mappings, dict)
        or not tier_mappings
        or not set(tier_mappings).issubset(_TIER_KEYS)
        or not all(isinstance(model, str) for model in tier_mappings.values())
        or not any(tier_mappings.values())
    ):
        return False
    alternatives = runtime["model_alternatives"]
    if not isinstance(alternatives, dict) or not set(alternatives).issubset(_TIER_KEYS):
        return False
    return all(
        isinstance(tier, str)
        and bool(tier)
        and isinstance(mapping, dict)
        and bool(mapping)
        and _string_map(mapping) == mapping
        for tier, mapping in alternatives.items()
    )
