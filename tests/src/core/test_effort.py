"""Tests for the two reasoning-effort vocabularies and their validators.

The Claude-CLI vocabulary (``CLAUDE_EFFORT_LEVELS``, includes ``max``) and the
core.llm vocabulary (``ReasoningEffort``/``REASONING_EFFORT_LEVELS``, includes
``none``) must stay distinct. A drift guard asserts the inline mirror in
``session.models`` matches ``ReasoningEffort`` exactly.
"""

from __future__ import annotations

import pytest

from forge.core.effort import CLAUDE_EFFORT_LEVELS, validate_claude_effort
from forge.core.llm.types import REASONING_EFFORT_LEVELS, validate_reasoning_effort


class TestVocabularies:
    def test_claude_levels_include_max_not_none(self):
        assert "max" in CLAUDE_EFFORT_LEVELS
        assert "none" not in CLAUDE_EFFORT_LEVELS
        assert set(CLAUDE_EFFORT_LEVELS) == {"low", "medium", "high", "xhigh", "max"}

    def test_reasoning_levels_include_none_not_max(self):
        assert "none" in REASONING_EFFORT_LEVELS
        assert "max" not in REASONING_EFFORT_LEVELS
        assert set(REASONING_EFFORT_LEVELS) == {"none", "low", "medium", "high", "xhigh"}

    def test_vocabularies_are_not_equal(self):
        # max is Claude-only; none is checker-only. Conflating them is a bug.
        assert set(CLAUDE_EFFORT_LEVELS) != set(REASONING_EFFORT_LEVELS)


class TestValidateClaudeEffort:
    def test_none_allowed(self):
        validate_claude_effort(None)  # inherit-default sentinel

    @pytest.mark.parametrize("level", ["low", "medium", "high", "xhigh", "max"])
    def test_accepts_each_level(self, level):
        validate_claude_effort(level)

    def test_rejects_checker_only_none(self):
        # The literal string "none" is a ReasoningEffort value, not a claude --effort level.
        with pytest.raises(ValueError, match="effort must be one of"):
            validate_claude_effort("none")

    def test_rejects_bogus(self):
        with pytest.raises(ValueError, match="effort must be one of"):
            validate_claude_effort("turbo")


class TestValidateReasoningEffort:
    def test_none_arg_allowed(self):
        validate_reasoning_effort(None)

    @pytest.mark.parametrize("level", ["none", "low", "medium", "high", "xhigh"])
    def test_accepts_each_level(self, level):
        validate_reasoning_effort(level)

    def test_rejects_claude_only_max(self):
        with pytest.raises(ValueError, match="reasoning_effort must be one of"):
            validate_reasoning_effort("max")

    def test_rejects_bogus(self):
        with pytest.raises(ValueError, match="reasoning_effort must be one of"):
            validate_reasoning_effort("turbo")


class TestDriftGuard:
    def test_models_checker_mirror_matches_reasoning_effort(self):
        """The inline _CHECKER_EFFORT_LEVELS mirror in session.models exists so the
        foundational dataclass module avoids importing heavy core.llm. It must stay
        identical to the canonical ReasoningEffort vocabulary."""
        from forge.session.models import _CHECKER_EFFORT_LEVELS

        assert tuple(_CHECKER_EFFORT_LEVELS) == tuple(REASONING_EFFORT_LEVELS)
