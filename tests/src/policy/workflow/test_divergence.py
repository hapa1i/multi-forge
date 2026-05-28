"""Tests for forge.policy.workflow.divergence."""

from __future__ import annotations

from forge.policy.workflow.divergence import (
    DIVERGENCE_CHECKER_PROMPT,
    DIVERGENCE_REVIEWER_PROMPT,
    DIVERGENCE_TAGGER_PROMPT,
    build_divergence_config,
)


class TestBuildDivergenceConfig:
    def test_default_name(self):
        config = build_divergence_config()
        assert config.name == "divergence"

    def test_default_has_one_branch(self):
        config = build_divergence_config()
        assert len(config.branches) == 1
        assert config.branches[0].name == "needs-review"

    def test_branch_matches_architectural_and_migration(self):
        config = build_divergence_config()
        branch = config.branches[0]
        assert "architectural" in branch.match_tags
        assert "migration" in branch.match_tags

    def test_branch_has_all_stages(self):
        config = build_divergence_config()
        branch = config.branches[0]
        assert branch.filter is not None
        assert branch.checker is not None
        assert branch.reviewer is not None

    def test_filter_excludes_tests(self):
        config = build_divergence_config()
        assert r"^tests/" in config.branches[0].filter.exclude_patterns

    def test_overrides_applied(self):
        config = build_divergence_config(tagger_model="custom/model", throttle_seconds=60)
        assert config.tagger_model == "custom/model"
        assert config.throttle_seconds == 60


class TestDivergencePrompts:
    def test_tagger_prompt_has_placeholders(self):
        assert "{tool_name}" in DIVERGENCE_TAGGER_PROMPT
        assert "{target_path}" in DIVERGENCE_TAGGER_PROMPT
        assert "{content}" in DIVERGENCE_TAGGER_PROMPT

    def test_checker_prompt_has_placeholders(self):
        assert "{tool_name}" in DIVERGENCE_CHECKER_PROMPT
        assert "{tags}" in DIVERGENCE_CHECKER_PROMPT

    def test_reviewer_prompt_has_placeholders(self):
        assert "{tool_name}" in DIVERGENCE_REVIEWER_PROMPT
        assert "{tags}" in DIVERGENCE_REVIEWER_PROMPT


class TestBuildDivergenceConfigEdgeCases:
    def test_override_branches_empty(self):
        """Overriding branches to empty list produces no-op routing."""
        config = build_divergence_config(branches=[])
        assert config.branches == []

    def test_override_throttle_zero(self):
        """throttle_seconds=0 means cache entries expire immediately."""
        config = build_divergence_config(throttle_seconds=0)
        assert config.throttle_seconds == 0

    def test_override_max_cache_entries(self):
        config = build_divergence_config(max_cache_entries=1)
        assert config.max_cache_entries == 1

    def test_prompts_can_format_with_all_variables(self):
        """All prompt templates accept the standard variable set without KeyError."""
        variables = {
            "tool_name": "Write",
            "target_path": "src/main.py",
            "content": "x = 1",
            "tags": "routine, config",
        }
        # Should not raise KeyError
        DIVERGENCE_TAGGER_PROMPT.format(**variables)
        DIVERGENCE_CHECKER_PROMPT.format(**variables)
        DIVERGENCE_REVIEWER_PROMPT.format(**variables)
