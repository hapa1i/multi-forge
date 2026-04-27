"""Tests for forge.guard.workflow.policy."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from forge.guard.types import ActionContext, PolicyDecision, Violation
from forge.guard.workflow.config import BranchConfig, CheckerConfig, WorkflowConfig
from forge.guard.workflow.policy import WorkflowPolicy


def _ctx(
    tool_name: str = "Write",
    target_path: str = "src/foo.py",
    new_content: str = "x = 1",
) -> ActionContext:
    return ActionContext(
        event=f"PreToolUse.{tool_name}",
        tool_name=tool_name,
        tool_args={},
        repo_root="/repo",
        session_name="test",
        target_path=target_path,
        new_content=new_content,
    )


def _simple_config(
    *,
    name: str = "test",
    description: str = "Test workflow",
    intent: str = "Test workflow intent",
    tool_names: list[str] | None = None,
    tagger_model: str = "test-model",
    tagger_prompt: str = "{tool_name}",
    branches: list[BranchConfig] | None = None,
    throttle_seconds: int = 30,
    max_cache_entries: int = 50,
) -> WorkflowConfig:
    return WorkflowConfig(
        name=name,
        description=description,
        intent=intent,
        tool_names=tool_names or ["Write", "Edit"],
        tagger_model=tagger_model,
        tagger_prompt=tagger_prompt,
        branches=branches
        or [
            BranchConfig(
                name="review",
                match_tags=["architectural"],
                checker=CheckerConfig(prompt_template="{tool_name}"),
            ),
        ],
        throttle_seconds=throttle_seconds,
        max_cache_entries=max_cache_entries,
    )


class TestWorkflowPolicyProperties:
    def test_policy_id(self):
        policy = WorkflowPolicy(config=_simple_config(name="divergence"))
        assert policy.policy_id == "workflow.divergence"

    def test_description(self):
        policy = WorkflowPolicy(config=_simple_config(description="My flow"))
        assert policy.description == "My flow"

    def test_applies_to_write(self):
        policy = WorkflowPolicy(config=_simple_config())
        assert policy.applies_to(_ctx(tool_name="Write")) is True

    def test_applies_to_edit(self):
        policy = WorkflowPolicy(config=_simple_config())
        assert policy.applies_to(_ctx(tool_name="Edit")) is True

    def test_does_not_apply_to_read(self):
        policy = WorkflowPolicy(config=_simple_config())
        assert policy.applies_to(_ctx(tool_name="Read")) is False

    def test_custom_tool_names(self):
        policy = WorkflowPolicy(config=_simple_config(tool_names=["Bash"]))
        assert policy.applies_to(_ctx(tool_name="Bash")) is True
        assert policy.applies_to(_ctx(tool_name="Write")) is False


class TestWorkflowPolicyEvaluate:
    @patch("forge.guard.workflow.policy.tag_action")
    def test_no_branch_match_allows(self, mock_tag):
        mock_tag.return_value = ["routine"]
        policy = WorkflowPolicy(config=_simple_config())

        result = policy.evaluate(_ctx())

        assert result.decision == "allow"
        mock_tag.assert_called_once()

    @patch("forge.guard.workflow.policy.tag_action")
    def test_matching_branch_executes(self, mock_tag):
        """When tagger returns a matching tag, the branch executes."""
        mock_tag.return_value = ["architectural"]
        config = _simple_config(
            branches=[
                BranchConfig(name="review", match_tags=["architectural"]),
            ]
        )
        policy = WorkflowPolicy(config=config)

        result = policy.evaluate(_ctx())

        # No stages → allow
        assert result.decision == "allow"

    @patch("forge.guard.workflow.policy.tag_action")
    def test_first_match_wins(self, mock_tag):
        """First matching branch is selected, not the best match."""
        mock_tag.return_value = ["architectural", "config"]
        config = _simple_config(
            branches=[
                BranchConfig(name="first", match_tags=["config"]),
                BranchConfig(name="second", match_tags=["architectural"]),
            ]
        )
        policy = WorkflowPolicy(config=config)
        result = policy.evaluate(_ctx())
        assert result.decision == "allow"
        assert result.policy_id == "workflow.test"

    @patch("forge.guard.workflow.policy.tag_action")
    def test_empty_tags_no_match(self, mock_tag):
        """When tagger returns empty tags (LLM error), no branch matches → allow."""
        mock_tag.return_value = []
        policy = WorkflowPolicy(config=_simple_config())

        result = policy.evaluate(_ctx())

        assert result.decision == "allow"

    @patch("forge.guard.workflow.policy.tag_action")
    def test_deny_decision_includes_intent(self, mock_tag):
        """Deny decisions from branches include the policy's intent."""
        mock_tag.return_value = ["architectural"]
        config = _simple_config(intent="Prevent architectural drift")
        policy = WorkflowPolicy(config=config)

        mock_branch = MagicMock()
        mock_branch.matches.return_value = True
        mock_branch.execute.return_value = PolicyDecision(
            decision="deny",
            policy_id="workflow.test",
            violations=[Violation(rule_id="test.rule", message="bad change", severity="high")],
        )
        policy._branches = [mock_branch]

        result = policy.evaluate(_ctx())
        assert result.decision == "deny"
        assert result.intent == "Prevent architectural drift"


class TestWorkflowPolicyCache:
    @patch("forge.guard.workflow.policy.tag_action")
    def test_branch_allow_is_cached(self, mock_tag):
        """Clean allow from a matched branch is cached."""
        mock_tag.return_value = ["architectural"]
        config = _simple_config(branches=[BranchConfig(name="review", match_tags=["architectural"])])
        policy = WorkflowPolicy(config=config)

        # First call — cache miss, branch matches, no stages → allow
        policy.evaluate(_ctx())
        assert mock_tag.call_count == 1

        # Second call — cache hit
        result = policy.evaluate(_ctx())
        assert result.decision == "allow"
        assert result.cached is True
        assert mock_tag.call_count == 1  # Not called again

    @patch("forge.guard.workflow.policy.tag_action")
    def test_no_branch_match_not_cached(self, mock_tag):
        """No-branch-matched allows are NOT cached (tagger may have failed)."""
        mock_tag.return_value = ["routine"]
        policy = WorkflowPolicy(config=_simple_config())

        policy.evaluate(_ctx())
        policy.evaluate(_ctx())
        # Tag action called twice — not cached
        assert mock_tag.call_count == 2

    @patch("forge.guard.workflow.policy.tag_action")
    def test_warn_not_cached(self, mock_tag):
        """Warn decisions are not cached (re-evaluate next time)."""
        mock_tag.return_value = ["architectural"]

        # Branch with a mock that returns warn
        branch_config = BranchConfig(name="review", match_tags=["architectural"])
        config = _simple_config(branches=[branch_config])
        policy = WorkflowPolicy(config=config)

        # Manually replace branch with mock
        mock_branch = MagicMock()
        mock_branch.matches.return_value = True
        mock_branch.execute.return_value = PolicyDecision(
            decision="warn", policy_id="workflow.test", warnings=["needs attention"]
        )
        policy._branches = [mock_branch]

        policy.evaluate(_ctx())
        policy.evaluate(_ctx())
        # Tag action called twice (no cache)
        assert mock_tag.call_count == 2


class TestWorkflowPolicyState:
    def test_state_round_trip(self):
        policy1 = WorkflowPolicy(config=_simple_config())
        policy1._cache.update("key1", decision="allow")
        state = policy1.get_state()

        policy2 = WorkflowPolicy(config=_simple_config())
        policy2.set_state(state)

        result = policy2._cache.check("key1")
        assert result is not None
        assert result["decision"] == "allow"

    def test_empty_state(self):
        policy = WorkflowPolicy(config=_simple_config())
        policy.set_state({})
        assert policy._cache.check("anything") is None

    def test_get_state_structure(self):
        policy = WorkflowPolicy(config=_simple_config())
        state = policy.get_state()
        assert "cache" in state
        assert isinstance(state["cache"], dict)


# --- Edge cases ---


class TestWorkflowPolicyEdgeCases:
    def test_applies_to_case_sensitive(self):
        """Tool name matching is case-sensitive."""
        policy = WorkflowPolicy(config=_simple_config(tool_names=["Write"]))
        assert policy.applies_to(_ctx(tool_name="write")) is False

    def test_applies_to_unlisted_tool(self):
        """Tool not in tool_names list doesn't match."""
        policy = WorkflowPolicy(config=_simple_config(tool_names=["Bash"]))
        assert policy.applies_to(_ctx(tool_name="Write")) is False
        assert policy.applies_to(_ctx(tool_name="Edit")) is False

    @patch("forge.guard.workflow.policy.tag_action")
    def test_no_branches_configured_allows(self, mock_tag):
        """No branches → tag is called but no branch matches → allow."""
        mock_tag.return_value = ["architectural"]
        config = _simple_config(branches=[])
        policy = WorkflowPolicy(config=config)
        result = policy.evaluate(_ctx())
        assert result.decision == "allow"

    @patch("forge.guard.workflow.policy.tag_action")
    def test_branch_allow_with_empty_warnings_is_cached(self, mock_tag):
        """Allow with empty warnings list (falsy) is cached."""
        mock_tag.return_value = ["architectural"]
        mock_branch = MagicMock()
        mock_branch.matches.return_value = True
        mock_branch.execute.return_value = PolicyDecision(decision="allow", policy_id="workflow.test", warnings=[])
        config = _simple_config(branches=[BranchConfig(name="review", match_tags=["architectural"])])
        policy = WorkflowPolicy(config=config)
        policy._branches = [mock_branch]

        policy.evaluate(_ctx())
        result = policy.evaluate(_ctx())
        # Second call should be cached
        assert result.cached is True
        assert mock_tag.call_count == 1

    @patch("forge.guard.workflow.policy.tag_action")
    def test_deny_not_cached(self, mock_tag):
        """Deny decisions are never cached."""
        mock_tag.return_value = ["architectural"]
        mock_branch = MagicMock()
        mock_branch.matches.return_value = True
        mock_branch.execute.return_value = PolicyDecision(
            decision="deny",
            policy_id="workflow.test",
            violations=[Violation(rule_id="r", message="bad", severity="high")],
        )
        config = _simple_config(branches=[BranchConfig(name="r", match_tags=["architectural"])])
        policy = WorkflowPolicy(config=config)
        policy._branches = [mock_branch]

        policy.evaluate(_ctx())
        policy.evaluate(_ctx())
        assert mock_tag.call_count == 2
