"""Tests for session name validation."""

from __future__ import annotations

import pytest

from forge.session.exceptions import InvalidSessionNameError
from forge.session.validation import (
    MAX_NAME_LENGTH,
    MIN_NAME_LENGTH,
    validate_name,
)


class TestValidNames:
    """Test cases for valid session names."""

    def test_minimum_length(self) -> None:
        """Accept 2-character names (minimum length)."""
        validate_name("ab")
        validate_name("a1")
        validate_name("1a")
        validate_name("12")

    def test_simple_names(self) -> None:
        """Accept simple lowercase names."""
        validate_name("test")
        validate_name("feature")
        validate_name("session")

    def test_names_with_hyphens(self) -> None:
        """Accept names with hyphens in the middle."""
        validate_name("my-session")
        validate_name("bug-123")
        validate_name("feature-auth-v2")
        validate_name("a-b-c-d")

    def test_names_with_numbers(self) -> None:
        """Accept names with numbers in any position."""
        validate_name("test123")
        validate_name("123test")
        validate_name("v1-alpha")
        validate_name("feature-v2-123")

    def test_maximum_length(self) -> None:
        """Accept names at maximum length (64 chars)."""
        name = "a" * MAX_NAME_LENGTH
        validate_name(name)

        # 64 chars: "a" (1) + "-b" * 30 (60) + "-ab" (3) = 64
        name_with_hyphens = "a" + "-b" * 30 + "-ab"
        assert len(name_with_hyphens) == 64
        validate_name(name_with_hyphens)


class TestInvalidNames:
    """Test cases for invalid session names."""

    def test_too_short(self) -> None:
        """Reject names shorter than minimum length."""
        with pytest.raises(InvalidSessionNameError, match="at least 2 characters"):
            validate_name("a")

        with pytest.raises(InvalidSessionNameError, match="at least 2 characters"):
            validate_name("")

    def test_too_long(self) -> None:
        """Reject names longer than maximum length."""
        name = "a" * (MAX_NAME_LENGTH + 1)
        with pytest.raises(InvalidSessionNameError, match="at most 64 characters"):
            validate_name(name)

    def test_uppercase(self) -> None:
        """Reject names with uppercase characters."""
        with pytest.raises(InvalidSessionNameError, match="lowercase alphanumeric"):
            validate_name("MySession")

        with pytest.raises(InvalidSessionNameError, match="lowercase alphanumeric"):
            validate_name("FEATURE")

        with pytest.raises(InvalidSessionNameError, match="lowercase alphanumeric"):
            validate_name("Test-Session")

    def test_leading_hyphen(self) -> None:
        """Reject names starting with hyphen."""
        with pytest.raises(InvalidSessionNameError, match="lowercase alphanumeric"):
            validate_name("-test")

        with pytest.raises(InvalidSessionNameError, match="lowercase alphanumeric"):
            validate_name("--")  # 2 chars but starts with hyphen

    def test_trailing_hyphen(self) -> None:
        """Reject names ending with hyphen."""
        with pytest.raises(InvalidSessionNameError, match="lowercase alphanumeric"):
            validate_name("test-")

    def test_consecutive_hyphens(self) -> None:
        """Reject names with consecutive hyphens."""
        with pytest.raises(InvalidSessionNameError, match="consecutive hyphens"):
            validate_name("test--session")

        with pytest.raises(InvalidSessionNameError, match="consecutive hyphens"):
            validate_name("my--feature")

        with pytest.raises(InvalidSessionNameError, match="consecutive hyphens"):
            validate_name("a--b")

    def test_special_characters(self) -> None:
        """Reject names with special characters."""
        invalid_names = [
            "test_session",  # underscore
            "my.session",  # dot
            "session@123",  # at sign
            "test session",  # space
            "test/session",  # slash
            "test:session",  # colon
        ]
        for name in invalid_names:
            with pytest.raises(InvalidSessionNameError, match="lowercase alphanumeric"):
                validate_name(name)


class TestConstants:
    """Test that constants are correctly defined."""

    def test_min_length(self) -> None:
        """MIN_NAME_LENGTH should be 2."""
        assert MIN_NAME_LENGTH == 2

    def test_max_length(self) -> None:
        """MAX_NAME_LENGTH should be 64."""
        assert MAX_NAME_LENGTH == 64
