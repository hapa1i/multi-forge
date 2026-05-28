"""Tests for forge.guard.workflow.config."""

from __future__ import annotations

import dacite
import pytest

from forge.guard.workflow.config import (
    BranchConfig,
    CheckerConfig,
    FilterConfig,
    ReviewerConfig,
    WorkflowConfig,
)


class TestWorkflowConfig:
    def test_defaults(self):
        config = WorkflowConfig(name="test", description="A test workflow", intent="Test intent")
        assert config.tool_names == ["Write", "Edit"]
        assert config.tagger_model == "gemini/gemini-2.0-flash"
        assert config.tagger_prompt == ""
        assert config.branches == []
        assert config.throttle_seconds == 30
        assert config.max_cache_entries == 50

    def test_dacite_round_trip(self):
        data = {
            "name": "divergence",
            "description": "Divergence workflow",
            "intent": "Catch architectural drift early",
            "tagger_model": "openai/gpt-4o-mini",
            "tagger_prompt": "Classify: {tool_name}",
            "branches": [
                {
                    "name": "needs-review",
                    "match_tags": ["architectural"],
                    "filter": {
                        "path_patterns": [r"src/.*\.py$"],
                        "exclude_patterns": [r"tests/"],
                    },
                    "checker": {
                        "model": "gemini/gemini-2.0-flash",
                        "prompt_template": "Check: {content}",
                    },
                    "reviewer": {
                        "model": "openai/gpt-4o",
                        "prompt_template": "Review: {content}",
                    },
                }
            ],
        }
        config = dacite.from_dict(WorkflowConfig, data)
        assert config.name == "divergence"
        assert len(config.branches) == 1
        branch = config.branches[0]
        assert branch.name == "needs-review"
        assert branch.match_tags == ["architectural"]
        assert branch.filter is not None
        assert branch.filter.path_patterns == [r"src/.*\.py$"]
        assert branch.checker is not None
        assert branch.checker.model == "gemini/gemini-2.0-flash"
        assert branch.reviewer is not None
        assert branch.reviewer.model == "openai/gpt-4o"

    def test_intent_defaults_to_empty_string(self):
        """Configs without intent field deserialize with empty default."""
        data = {"name": "legacy", "description": "No intent field", "branches": []}
        config = dacite.from_dict(WorkflowConfig, data)
        assert config.intent == ""

    def test_missing_required_fields(self):
        with pytest.raises(dacite.MissingValueError):
            dacite.from_dict(WorkflowConfig, {"name": "test"})

    def test_branch_defaults(self):
        config = BranchConfig(name="test", match_tags=["foo"])
        assert config.match_mode == "any"
        assert config.filter is None
        assert config.checker is None
        assert config.reviewer is None

    def test_nested_configs_optional(self):
        """Branches can omit filter/checker/reviewer."""
        data = {
            "name": "simple",
            "description": "No stages",
            "intent": "Allow routine changes",
            "branches": [{"name": "allow-all", "match_tags": ["routine"]}],
        }
        config = dacite.from_dict(WorkflowConfig, data)
        branch = config.branches[0]
        assert branch.filter is None
        assert branch.checker is None
        assert branch.reviewer is None

    def test_filter_config_defaults(self):
        config = FilterConfig()
        assert config.path_patterns == []
        assert config.exclude_patterns == []
        assert config.max_content_length is None

    def test_checker_config_defaults(self):
        config = CheckerConfig()
        assert config.model == "gemini/gemini-2.0-flash"
        assert config.system_prompt is None

    def test_reviewer_config_defaults(self):
        config = ReviewerConfig()
        assert config.model == "gemini/gemini-2.0-flash"
        assert config.system_prompt is None
