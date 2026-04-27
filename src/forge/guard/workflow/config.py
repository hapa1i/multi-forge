"""Configuration dataclasses for WorkflowPolicy.

Deserialized from ``bundle_config["workflow"]["workflows"]`` dicts
via ``dacite.from_dict(WorkflowConfig, data)``.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FilterConfig:
    """Deterministic gating config for FilterStage."""

    path_patterns: list[str] = field(default_factory=list)
    exclude_patterns: list[str] = field(default_factory=list)
    max_content_length: int | None = None


@dataclass
class CheckerConfig:
    """Cheap LLM check config for CheckerStage."""

    model: str = "gemini/gemini-2.0-flash"
    prompt_template: str = ""
    system_prompt: str | None = None


@dataclass
class ReviewerConfig:
    """Deep LLM review config for ReviewerStage."""

    model: str = "gemini/gemini-2.0-flash"
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
    tagger_model: str = "gemini/gemini-2.0-flash"
    tagger_prompt: str = ""
    branches: list[BranchConfig] = field(default_factory=list)
    throttle_seconds: int = 30
    max_cache_entries: int = 50
