"""Configuration dataclasses for WorkflowPolicy.

Deserialized strictly from ``bundle_config["workflow"]["workflows"]`` dicts
via ``dacite.from_dict(WorkflowConfig, data, config=dacite.Config(strict=True))``.
"""

from __future__ import annotations

from dataclasses import dataclass, field


def _require_int(field_name: str, value: object) -> None:
    """Require a built-in integer; ``bool`` is an ``int`` subclass and must not pass manifest validation."""
    if type(value) is not int:
        raise TypeError(f"{field_name} must be int, got {type(value).__name__}")


@dataclass
class FilterConfig:
    """Deterministic gating config for FilterStage."""

    path_patterns: list[str] = field(default_factory=list)
    exclude_patterns: list[str] = field(default_factory=list)
    max_content_length: int | None = None

    def __post_init__(self) -> None:
        if self.max_content_length is not None:
            _require_int("max_content_length", self.max_content_length)


@dataclass
class CheckerConfig:
    """Cheap LLM check config for CheckerStage."""

    model: str = "gemini/gemini-3.6-flash"
    prompt_template: str = ""
    system_prompt: str | None = None


@dataclass
class ReviewerConfig:
    """Deep LLM review config for ReviewerStage."""

    model: str = "gemini/gemini-3.6-flash"
    prompt_template: str = ""
    system_prompt: str | None = None


@dataclass
class BranchConfig:
    """Config for a single routing branch."""

    name: str
    match_tags: list[str]
    match_mode: str = "any"
    filter: FilterConfig | None = None
    checker: CheckerConfig | None = None
    reviewer: ReviewerConfig | None = None


@dataclass
class WorkflowConfig:
    """Top-level config for a single WorkflowPolicy instance."""

    name: str
    description: str
    intent: str = ""
    tool_names: list[str] = field(default_factory=lambda: ["Write", "Edit"])
    tagger_model: str = "gemini/gemini-3.6-flash"
    tagger_prompt: str = ""
    branches: list[BranchConfig] = field(default_factory=list)
    throttle_seconds: int = 30
    max_cache_entries: int = 50

    def __post_init__(self) -> None:
        _require_int("throttle_seconds", self.throttle_seconds)
        _require_int("max_cache_entries", self.max_cache_entries)
