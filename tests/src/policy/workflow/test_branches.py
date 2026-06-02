"""Tests for forge.policy.workflow.branches."""

from __future__ import annotations

from unittest.mock import MagicMock

from forge.policy.types import ActionContext, PolicyDecision
from forge.policy.workflow.branches import Branch
from forge.policy.workflow.config import (
    BranchConfig,
    CheckerConfig,
    FilterConfig,
    ReviewerConfig,
)


def _ctx(target_path: str = "src/foo.py") -> ActionContext:
    return ActionContext(
        runtime="claude_code",
        event="PreToolUse.Write",
        tool_name="Write",
        tool_args={},
        repo_root="/repo",
        session_name="test",
        target_path=target_path,
        new_content="x = 1",
    )


class TestBranchMatches:
    def test_any_mode_matches_single(self):
        branch = Branch(
            name="test",
            match_tags=["a", "b"],
            match_mode="any",
            filter=None,
            checker=None,
            reviewer=None,
        )
        assert branch.matches(["a"]) is True

    def test_any_mode_no_match(self):
        branch = Branch(
            name="test",
            match_tags=["a", "b"],
            match_mode="any",
            filter=None,
            checker=None,
            reviewer=None,
        )
        assert branch.matches(["c"]) is False

    def test_all_mode_requires_all(self):
        branch = Branch(
            name="test",
            match_tags=["a", "b"],
            match_mode="all",
            filter=None,
            checker=None,
            reviewer=None,
        )
        assert branch.matches(["a"]) is False
        assert branch.matches(["a", "b"]) is True
        assert branch.matches(["a", "b", "c"]) is True

    def test_empty_tags_no_match(self):
        branch = Branch(
            name="test",
            match_tags=["a"],
            match_mode="any",
            filter=None,
            checker=None,
            reviewer=None,
        )
        assert branch.matches([]) is False

    def test_empty_match_tags_never_matches(self):
        branch = Branch(
            name="test",
            match_tags=[],
            match_mode="any",
            filter=None,
            checker=None,
            reviewer=None,
        )
        assert branch.matches(["a"]) is False


class TestBranchFromConfig:
    def test_creates_stages_from_config(self):
        config = BranchConfig(
            name="review",
            match_tags=["arch"],
            filter=FilterConfig(path_patterns=[r"src/"]),
            checker=CheckerConfig(prompt_template="{tool_name}"),
            reviewer=ReviewerConfig(prompt_template="{tool_name}"),
        )
        branch = Branch.from_config(config)
        assert branch.filter is not None
        assert branch.checker is not None
        assert branch.reviewer is not None

    def test_none_stages_when_config_missing(self):
        config = BranchConfig(name="simple", match_tags=["routine"])
        branch = Branch.from_config(config)
        assert branch.filter is None
        assert branch.checker is None
        assert branch.reviewer is None


class TestBranchExecute:
    def test_no_stages_returns_allow(self):
        branch = Branch(
            name="test",
            match_tags=["a"],
            match_mode="any",
            filter=None,
            checker=None,
            reviewer=None,
        )
        result = branch.execute(_ctx(), ["a"], "wf.test")
        assert result.decision == "allow"
        assert result.policy_id == "wf.test"

    def test_filter_blocks_skips_to_allow(self):
        mock_filter = MagicMock()
        mock_filter.passes.return_value = False
        branch = Branch(
            name="test",
            match_tags=["a"],
            match_mode="any",
            filter=mock_filter,
            checker=MagicMock(),
            reviewer=MagicMock(),
        )
        result = branch.execute(_ctx(), ["a"], "wf.test")
        assert result.decision == "allow"
        branch.checker.check.assert_not_called()
        branch.reviewer.review.assert_not_called()

    def test_checker_allow_short_circuits(self):
        mock_filter = MagicMock()
        mock_filter.passes.return_value = True
        mock_checker = MagicMock()
        mock_checker.check.return_value = PolicyDecision(decision="allow", policy_id="wf.test")
        mock_reviewer = MagicMock()

        branch = Branch(
            name="test",
            match_tags=["a"],
            match_mode="any",
            filter=mock_filter,
            checker=mock_checker,
            reviewer=mock_reviewer,
        )
        result = branch.execute(_ctx(), ["a"], "wf.test")

        assert result.decision == "allow"
        assert result.policy_id == "wf.test"
        mock_reviewer.review.assert_not_called()

    def test_checker_none_escalates_to_reviewer(self):
        mock_filter = MagicMock()
        mock_filter.passes.return_value = True
        mock_checker = MagicMock()
        mock_checker.check.return_value = None
        mock_reviewer = MagicMock()
        mock_reviewer.review.return_value = PolicyDecision(
            decision="warn", policy_id="wf.test", warnings=["needs attention"]
        )

        branch = Branch(
            name="test",
            match_tags=["a"],
            match_mode="any",
            filter=mock_filter,
            checker=mock_checker,
            reviewer=mock_reviewer,
        )
        result = branch.execute(_ctx(), ["a"], "wf.test")

        assert result.decision == "warn"
        mock_reviewer.review.assert_called_once()

    def test_no_filter_goes_straight_to_checker(self):
        mock_checker = MagicMock()
        mock_checker.check.return_value = PolicyDecision(decision="allow", policy_id="wf.test")
        branch = Branch(
            name="test",
            match_tags=["a"],
            match_mode="any",
            filter=None,
            checker=mock_checker,
            reviewer=None,
        )
        result = branch.execute(_ctx(), ["a"], "wf.test")
        assert result.decision == "allow"
        mock_checker.check.assert_called_once()
