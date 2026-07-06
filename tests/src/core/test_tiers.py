"""Tests for shared tier-word detection."""

from __future__ import annotations

import inspect

import pytest

from forge.core import tiers
from forge.core.tiers import detect_tier_word


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("claude-haiku-4-5", "haiku"),
        ("claude-sonnet-4-6", "sonnet"),
        ("claude-opus-4-8", "opus"),
        ("claude-fable-5", "opus"),
        ("anthropic/claude-fable-5", "opus"),
        ("Claude-OPUS-4", "opus"),
        ("gpt-4o", None),
        ("", None),
        (None, None),
        ("opusculum-7", "opus"),
    ],
)
def test_detect_tier_word_preserves_existing_substring_behavior(model: str | None, expected: str | None) -> None:
    assert detect_tier_word(model) == expected


def test_tiers_leaf_has_no_proxy_or_cli_imports() -> None:
    source = inspect.getsource(tiers)

    assert "forge.proxy" not in source
    assert "forge.cli" not in source
