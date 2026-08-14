"""UI-free metric number formatting with explicit presentation policies."""

from __future__ import annotations

from enum import StrEnum


class TokenDisplayPolicy(StrEnum):
    """Reviewed compact token-count presentations."""

    UPPER_TENTHS = "upper_tenths"
    ACTIVITY_COMPACT = "activity_compact"


class UsdDisplayPolicy(StrEnum):
    """Reviewed human USD presentations."""

    COST_DETAIL = "cost_detail"
    ACTIVITY_DETAIL = "activity_detail"
    FIXED_CENTS = "fixed_cents"
    STATUS_WHOLE_CENTS = "status_whole_cents"
    STATUS_FRACTIONAL_CENTS = "status_fractional_cents"
    SPEND_CAP = "spend_cap"


def format_token_count(count: int, *, policy: TokenDisplayPolicy) -> str:
    """Format a token count under an explicitly selected presentation policy."""

    if policy is TokenDisplayPolicy.UPPER_TENTHS:
        if count >= 1_000_000:
            return f"{count / 1_000_000:.1f}M"
        if count >= 1_000:
            return f"{count / 1_000:.1f}K"
        return str(count)

    if policy is TokenDisplayPolicy.ACTIVITY_COMPACT:
        if count >= 1_000_000:
            return f"{count / 1_000_000:.1f}M"
        if count >= 1_000:
            return f"{count / 1_000:.0f}k"
        return str(count)

    raise ValueError(f"Unsupported token display policy: {policy}")


def format_usd(amount_usd: float, *, policy: UsdDisplayPolicy) -> str:
    """Format a USD amount under an explicitly selected presentation policy."""

    if policy is UsdDisplayPolicy.COST_DETAIL:
        if amount_usd >= 1.0:
            return f"${amount_usd:,.2f}"
        if amount_usd >= 0.01:
            return f"${amount_usd:.2f}"
        if amount_usd >= 0.0001:
            return f"${amount_usd:.4f}"
        if amount_usd > 0:
            return f"${amount_usd:.6f}"
        return "$0.00"

    if policy is UsdDisplayPolicy.ACTIVITY_DETAIL:
        if amount_usd and abs(amount_usd) < 0.01:
            return f"${amount_usd:.4f}"
        return f"${amount_usd:.2f}"

    if policy is UsdDisplayPolicy.FIXED_CENTS:
        return f"${amount_usd:.2f}"

    if policy is UsdDisplayPolicy.STATUS_WHOLE_CENTS:
        if amount_usd < 0.01:
            return f"{int(amount_usd * 100)}c"
        return f"${amount_usd:.2f}"

    if policy is UsdDisplayPolicy.STATUS_FRACTIONAL_CENTS:
        # Proxy totals are estimates assembled from reported requests, so the compact
        # status line retains the existing fractional-cent evidence below $0.01.
        if amount_usd < 0.01:
            return f"{int(amount_usd * 10_000) / 100}c"
        return f"${amount_usd:.2f}"

    if policy is UsdDisplayPolicy.SPEND_CAP:
        # Smoke-test caps can be tiny; fixed cents would collapse distinct current
        # and limit values such as $0.0005/$0.001 into the misleading $0.00/$0.00.
        if amount_usd >= 0.01:
            return f"${amount_usd:.2f}"
        if amount_usd <= 0:
            return "$0.00"
        return f"${amount_usd:.4f}"

    raise ValueError(f"Unsupported USD display policy: {policy}")


def format_usd_micros(amount_micros: int, *, policy: UsdDisplayPolicy) -> str:
    """Format an integer micro-USD amount under an explicit USD policy."""

    return format_usd(amount_micros / 1_000_000, policy=policy)
