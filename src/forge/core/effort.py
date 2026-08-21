"""Reasoning-effort vocabularies for Forge subprocesses.

Two distinct effort vocabularies exist and must not be conflated:

- ``CLAUDE_EFFORT_LEVELS`` -- the ``claude --effort`` CLI flag accepts
  ``low/medium/high/xhigh/max`` (``max`` is Claude-only). Used for every Forge
  ``claude -p`` subprocess: the supervisor frontier, the memory writer, shadow
  curation, the team supervisor, and the workflow fan-out.
- core.llm ``ReasoningEffort`` (``none/low/medium/high/xhigh``; ``none`` is
  API-only) -- the user-facing tier-1 plan-checker vocabulary. Provider
  transports use a separate catalog-aware union that can also include labels
  such as ``minimal``, ``disable``, or ``max``.

This module is a dependency-light leaf (typing only) so the foundational
``forge.session.models`` dataclasses can validate Claude-effort fields without
importing the heavy ``core.llm`` / ``core.reactive`` packages (which would risk
an import cycle). The checker vocabulary's validator, ``validate_reasoning_effort``,
lives in ``forge.core.llm.types`` beside ``ReasoningEffort``; modules already in
that layer (CLI, plan_check) use it directly.
"""

from __future__ import annotations

from typing import Literal, get_args

# The claude CLI's --effort levels (confirmed from `claude --help`). `max` has no
# tier-1 checker ReasoningEffort equivalent; `none` (a ReasoningEffort value) is
# NOT a valid `claude --effort` level. Provider transports may independently
# support either label through their model-specific catalogs.
ClaudeEffort = Literal["low", "medium", "high", "xhigh", "max"]

CLAUDE_EFFORT_LEVELS: tuple[str, ...] = get_args(ClaudeEffort)


def validate_claude_effort(value: str | None) -> None:
    """Raise ValueError if ``value`` is not a valid ``claude --effort`` level.

    ``None`` is allowed (means "inherit the model/tier default").
    """
    if value is not None and value not in CLAUDE_EFFORT_LEVELS:
        raise ValueError(f"effort must be one of {', '.join(CLAUDE_EFFORT_LEVELS)}, got {value!r}")
