"""Tests for core naming module."""

from __future__ import annotations

import re

import pytest

from forge.core.naming import (
    DEFAULT_WORDS,
    generate_name,
    generate_parts,
    generate_unique_name,
)


class TestGenerateName:
    """Tests for generate_name()."""

    def test_returns_hyphenated_slug(self) -> None:
        """Name should be hyphen-separated words."""
        name = generate_name()
        assert "-" in name
        assert name == name.lower()  # All lowercase

    def test_default_is_two_words(self) -> None:
        """Default should produce 2-word names."""
        name = generate_name()
        parts = name.split("-")
        assert len(parts) == 2

    @pytest.mark.parametrize("words", [2, 3, 4])
    def test_word_count_options(self, words: int) -> None:
        """Should support 2, 3, or 4 word names."""
        name = generate_name(words=words)  # type: ignore[arg-type]
        parts = name.split("-")
        # 4-word names include "of" so may have 5 parts
        assert len(parts) >= words

    def test_multiple_calls_produce_variation(self) -> None:
        """Multiple calls should eventually produce different names."""
        names = {generate_name() for _ in range(100)}
        assert len(names) > 1

    def test_name_format_is_valid(self) -> None:
        """Generated names should be valid identifiers (lowercase, alphanumeric + hyphens)."""
        for _ in range(10):
            name = generate_name()
            assert re.match(r"^[a-z]+(-[a-z]+)+$", name), f"Invalid format: {name}"


class TestGenerateUniqueName:
    """Tests for generate_unique_name()."""

    def test_avoids_existing_names(self) -> None:
        """Should not return a name in the existing set."""
        # Generate some existing names
        existing = {generate_name() for _ in range(50)}
        name = generate_unique_name(existing)
        assert name not in existing

    def test_empty_existing_set(self) -> None:
        """Should work with empty existing set."""
        name = generate_unique_name(set())
        assert "-" in name

    def test_falls_back_to_suffix_when_exhausted(self) -> None:
        """Should fall back to suffixed name when max_attempts exhausted."""
        # Use max_attempts=0 to force immediate fallback
        name = generate_unique_name(set(), max_attempts=0)

        # Must have a numeric suffix (3-4 digits)
        assert re.match(r"^[a-z]+-[a-z]+-\d{3,4}$", name), f"Expected suffix: {name}"

    def test_fallback_guarantees_uniqueness(self) -> None:
        """Fallback should loop until truly unique (not just append suffix blindly)."""
        # Generate a large existing set
        existing = {generate_name() for _ in range(1000)}

        # Generate many names with max_attempts=0 to always use fallback
        for _ in range(100):
            name = generate_unique_name(existing, max_attempts=0)
            # Every name must be unique
            assert name not in existing
            existing.add(name)

    def test_respects_word_count(self) -> None:
        """Should use specified word count."""
        name = generate_unique_name(set(), words=3)
        parts = name.split("-")
        assert len(parts) >= 3


class TestGenerateParts:
    """Tests for generate_parts()."""

    def test_returns_list(self) -> None:
        """Should return a list of strings."""
        parts = generate_parts()
        assert isinstance(parts, list)
        assert all(isinstance(p, str) for p in parts)

    def test_default_word_count(self) -> None:
        """Default should return DEFAULT_WORDS parts."""
        parts = generate_parts()
        assert len(parts) == DEFAULT_WORDS

    @pytest.mark.parametrize(
        ("words", "min_parts"),
        [
            (2, 2),  # adjective-noun (exactly 2)
            (3, 3),  # adjective-adjective-noun (3-4, may include 'of')
            (4, 4),  # adjective-adjective-noun-of-noun (4-5)
        ],
    )
    def test_word_count_options(self, words: int, min_parts: int) -> None:
        """Should support different word counts (coolname may add 'of' connector)."""
        parts = generate_parts(words=words)  # type: ignore[arg-type]
        # coolname can include "of" as a connector, so parts >= words
        assert len(parts) >= min_parts

    def test_parts_are_lowercase(self) -> None:
        """All parts should be lowercase."""
        parts = generate_parts()
        assert all(p == p.lower() for p in parts)
