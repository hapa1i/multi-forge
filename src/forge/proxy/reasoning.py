"""Thinking -> reasoning_effort translation for the proxy.

Claude Code sends Anthropic-specific `thinking` config; litellm uses
`reasoning_effort` which it translates per provider (Gemini 3: thinking_level,
Gemini 2.5: thinkingBudget). These helpers map between the two and normalize
the result against the catalog's per-model effort levels. Extracted from
server.py to keep that module's size bounded.
"""

import logging

from fastapi import HTTPException

from forge.config import TierOverride

logger = logging.getLogger(__name__)

# Ordered from lowest to highest so we can compare with max().
EFFORT_RANK: dict[str | None, int] = {
    None: -1,
    "none": 0,
    "disable": 0,
    "minimal": 1,
    "low": 2,
    "medium": 3,
    "high": 4,
    "xhigh": 5,
    "max": 6,
}

# Budget thresholds for ceil-to-tier mapping (never downgrade).
# Checked top-down; first match wins.  LiteLLM internal budgets for
# reference: low ~ 1,024, medium ~ 8,192, high ~ 24,576.
BUDGET_THRESHOLDS: list[tuple[int, str]] = [
    (25_000, "xhigh"),  # >=25k tokens -> xhigh (above litellm high)
    (10_000, "high"),  # >=10k tokens -> high
    (2_000, "medium"),  # >=2k tokens  -> medium
    (500, "low"),  # >=500 tokens -> low
    (1, "minimal"),  # >=1 token    -> minimal
]

# Type-based fallback when budget_tokens is absent.
TYPE_TO_EFFORT: dict[str, str] = {
    "enabled": "high",
    "adaptive": "medium",
    "disabled": "none",
}


def derive_reasoning_effort(thinking: dict[str, object] | object | None) -> str | None:
    """Derive reasoning_effort from Claude Code's thinking config.

    Priority: budget_tokens (numeric, precise) > type (semantic label).
    Unknown types default to "medium" (safe — never results in no reasoning).
    """
    if not isinstance(thinking, dict):
        return None

    # 1) Use budget_tokens if present — data-driven, not label-driven.
    budget = thinking.get("budget_tokens")
    if isinstance(budget, (int, float)) and budget > 0:
        for threshold, effort in BUDGET_THRESHOLDS:
            if budget >= threshold:
                return effort
        return "minimal"  # budget_tokens in (0, 1) — fractional edge case

    # 2) Fall back to type-based mapping.
    thinking_type = thinking.get("type")
    if isinstance(thinking_type, str):
        mapped: str | None = TYPE_TO_EFFORT.get(thinking_type)
        if mapped is not None:
            return mapped
        # Unknown type — default to medium (safe), log warning.
        logger.warning(
            "Unknown thinking type '%s', defaulting to reasoning_effort='medium'",
            thinking_type,
        )
        return "medium"

    return None


def max_effort(a: str | None, b: str | None) -> str | None:
    """Return the higher of two reasoning_effort levels, treating None as unset."""
    if a is None:
        return b
    if b is None:
        return a
    return a if EFFORT_RANK.get(a, 3) >= EFFORT_RANK.get(b, 3) else b


def supported_efforts_for_model(model_id: str) -> tuple[str, ...] | None:
    """Return the catalog effort levels for a mapped model id, or None if unconstrained.

    None means the model is not in the catalog (arbitrary backend slugs are
    legal — fail open) or its entry lists no effort levels; both cases pass
    effort values through untouched.
    """
    from forge.core.models import ModelCatalogError, get_model_spec

    try:
        return get_model_spec(model_id).litellm_reasoning_efforts
    except ModelCatalogError:
        return None


def clamp_effort_to_supported(effort: str | None, supported: tuple[str, ...] | None) -> str | None:
    """Clamp a proxy-derived effort to the model's supported levels.

    Picks the highest supported level at or below the requested one. When the
    request sits below every supported level (e.g. "none" for a model with no
    off switch), returns the lowest supported level: omitting the value would
    fall through to the provider-side default, which may be the model's
    highest level.
    """
    if effort is None or supported is None or effort in supported:
        return effort
    requested_rank = EFFORT_RANK.get(effort, 3)
    ranked = sorted(supported, key=lambda level: EFFORT_RANK.get(level, 3))
    at_or_below = [level for level in ranked if EFFORT_RANK.get(level, 3) <= requested_rank]
    return at_or_below[-1] if at_or_below else ranked[0]


def raise_effort_to_supported(effort: str, supported: tuple[str, ...] | None) -> str | None:
    """Raise an effort floor to the model's supported levels without weakening it.

    The upward sibling of :func:`clamp_effort_to_supported`, for callers that
    enforce a floor rather than honor a request: picks the lowest supported
    level at or above ``effort``, so a floor the model cannot express exactly is
    never silently downgraded. Returns ``None`` when every supported level sits
    below the floor; the caller decides how to classify that incompatibility.
    """
    if supported is None or effort in supported:
        return effort
    floor_rank = EFFORT_RANK.get(effort, 3)
    ranked = sorted(supported, key=lambda level: EFFORT_RANK.get(level, 3))
    at_or_above = [level for level in ranked if EFFORT_RANK.get(level, 3) >= floor_rank]
    return at_or_above[0] if at_or_above else None


def resolve_reasoning_effort(
    request_data: object,
    *,
    tier_override: TierOverride | None,
    model_id: str,
    request_id: str,
) -> str | None:
    """Resolve the final reasoning_effort for a request.

    Priority: request explicit > thinking-derived > tier_override floor. The
    result is normalized against the catalog effort levels for the mapped
    model: an explicit unsupported value is rejected (the caller named an
    exact level), while derived values clamp (the caller asked for a thinking
    depth, not a specific level).
    """
    supported = supported_efforts_for_model(model_id)

    # Use getattr() for test stubs that don't include new fields.
    explicit = getattr(request_data, "reasoning_effort", None)
    if explicit is not None:
        if supported is not None and explicit not in supported:
            raise HTTPException(
                status_code=400,
                detail={
                    "type": "invalid_request_error",
                    "message": (
                        f"reasoning_effort '{explicit}' is not supported by '{model_id}' "
                        f"(supported: {', '.join(supported)}) [{request_id}]"
                    ),
                },
            )
        return explicit

    # Claude Code sends `thinking` (Anthropic-specific) instead of
    # `reasoning_effort`. Translate to reasoning_effort so litellm can
    # map it to each provider's native parameter.
    derived = derive_reasoning_effort(getattr(request_data, "thinking", None))

    # Apply tier_override as a floor: max(derived, tier_override).
    tier_effort = tier_override.reasoning_effort if tier_override else None
    effort = max_effort(derived, tier_effort)

    clamped = clamp_effort_to_supported(effort, supported)
    if clamped != effort:
        logger.debug(f"[{request_id}] Clamped reasoning_effort '{effort}' -> '{clamped}' for '{model_id}'")
    return clamped
