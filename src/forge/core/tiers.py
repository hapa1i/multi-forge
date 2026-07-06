"""Shared tier-word detection helpers."""

from __future__ import annotations


def detect_tier_word(model: str) -> str | None:
    """Infer an explicit haiku/sonnet/opus tier from a model name substring.

    Fable carries no tier word of its own; it rides the opus tier. The substring
    matching is intentionally naive to preserve existing proxy/statusline behavior.
    """
    name = model.lower()
    for tier in ("haiku", "sonnet", "opus"):
        if tier in name:
            return tier
    if "fable" in name:
        return "opus"
    return None
