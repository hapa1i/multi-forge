"""Defensive, secret-free facts parsed from a proxy identity response."""

from __future__ import annotations

from typing import Any

from forge.core.identifiers import is_lowercase_identifier
from forge.core.wire_shapes import VALID_WIRE_SHAPES

_TIER_KEYS = frozenset({"haiku", "sonnet", "opus"})
_EFFORT_LEVELS = frozenset({"none", "disable", "minimal", "low", "medium", "high", "xhigh", "max"})
_EFFORT_SOURCES = frozenset({"explicit", "client", "thinking", "floor", "passthrough", "override"})
_EFFORT_WIRES = frozenset(
    {
        "reasoning_effort",
        "reasoning.effort",
        "thinkingConfig.thinkingLevel",
        "output_config.effort",
        "dropped",
    }
)
_EFFORT_FIELDS = frozenset(
    {
        "tier",
        "tier_source",
        "client_model",
        "mapped_model",
        "requested",
        "thinking",
        "opt_in",
        "client_applicable",
        "derived",
        "floor",
        "pre_clamp",
        "supported",
        "resolved",
        "source",
        "applied",
        "wire",
        "note",
        "observed_at",
    }
)


class ProxyRuntimeTruth:
    """Structured proxy runtime truth from the proxy identity endpoint."""

    def __init__(self, raw: dict[str, Any]):
        self.raw = raw
        self.is_proxy = raw.get("is_proxy") is True
        wire_shape = raw.get("wire_shape")
        self.wire_shape = wire_shape if isinstance(wire_shape, str) and wire_shape in VALID_WIRE_SHAPES else None

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
        backend_id = runtime.get("backend_id")
        self.backend_id = backend_id if is_lowercase_identifier(backend_id) else None
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
        effort = runtime.get("effort")
        self.effort = _effort_map(effort)
        # A bad tier must not hide another tier's usable outbound observation.
        self.has_effort_observations = isinstance(effort, dict) and (not effort or bool(self.effort))

        tiers = raw.get("tiers", {})
        self.tiers = tiers if isinstance(tiers, dict) else {}

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


def _effort_map(value: object) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        return {}
    return {
        tier: {key: record[key] for key in _EFFORT_FIELDS}
        for tier, record in value.items()
        if tier in _TIER_KEYS and isinstance(record, dict) and _valid_effort_record(tier, record)
    }


def _valid_effort_record(tier: str, record: dict[str, Any]) -> bool:
    if not _EFFORT_FIELDS.issubset(record) or record["tier"] != tier:
        return False
    for field in ("tier_source", "client_model", "mapped_model", "observed_at"):
        value = record[field]
        if not isinstance(value, str) or not value or not value.isprintable():
            return False
    # Requested effort is client vocabulary; a newer client may add a level.
    for field in ("requested", "thinking", "note"):
        value = record[field]
        if value is not None and (not isinstance(value, str) or not value.isprintable()):
            return False
    if record["requested"] == "":
        return False
    for field in ("opt_in", "client_applicable"):
        if not isinstance(record[field], bool):
            return False
    for field in ("derived", "floor", "pre_clamp", "resolved", "applied"):
        value = record[field]
        if value is not None and (not isinstance(value, str) or value not in _EFFORT_LEVELS):
            return False
    supported = record["supported"]
    if supported is not None and (
        not isinstance(supported, list)
        or not all(isinstance(level, str) and level in _EFFORT_LEVELS for level in supported)
    ):
        return False
    source, wire = record["source"], record["wire"]
    valid_wire = (
        isinstance(source, str)
        and source in _EFFORT_SOURCES
        and (wire is None or (isinstance(wire, str) and wire in _EFFORT_WIRES))
    )
    if not valid_wire:
        return False
    return (record["applied"] is None) == (wire is None or wire == "dropped")


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
