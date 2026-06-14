"""Tests for policy/types.py."""

import pytest

from forge.policy.types import (
    ActionContext,
    CompositeDecision,
    PolicyDecision,
    Violation,
)


class TestActionContext:
    """Tests for ActionContext dataclass."""

    def test_create_minimal(self) -> None:
        """Test creating ActionContext with minimal required fields."""
        ctx = ActionContext(
            origin="claude_code",
            event="PreToolUse.Write",
            tool_name="Write",
            tool_args={},
            repo_root="/repo",
            session_name="test",
        )
        assert ctx.event == "PreToolUse.Write"
        assert ctx.tool_name == "Write"
        assert ctx.target_path is None
        assert ctx.new_content is None

    def test_create_full(self) -> None:
        """Test creating ActionContext with all fields."""
        ctx = ActionContext(
            origin="claude_code",
            event="PreToolUse.Write",
            tool_name="Write",
            tool_args={"file_path": "/repo/src/foo.py", "content": "code"},
            repo_root="/repo",
            session_name="test",
            target_path="src/foo.py",
            new_content="code",
        )
        assert ctx.target_path == "src/foo.py"
        assert ctx.new_content == "code"

    def test_immutable(self) -> None:
        """Test that ActionContext is frozen (immutable)."""
        ctx = ActionContext(
            origin="claude_code",
            event="PreToolUse.Write",
            tool_name="Write",
            tool_args={},
            repo_root="/repo",
            session_name="test",
        )
        with pytest.raises(Exception):  # FrozenInstanceError
            ctx.tool_name = "Edit"  # type: ignore


class TestViolation:
    """Tests for Violation dataclass."""

    def test_create_minimal(self) -> None:
        """Test creating Violation with minimal fields."""
        v = Violation(
            rule_id="test.rule",
            message="Test violation",
            severity="high",
        )
        assert v.rule_id == "test.rule"
        assert v.severity == "high"
        assert v.citations == []

    def test_create_with_citations(self) -> None:
        """Test creating Violation with citations."""
        v = Violation(
            rule_id="test.rule",
            message="Test violation",
            severity="medium",
            citations=["section 1", "section 2"],
        )
        assert len(v.citations) == 2


class TestPolicyDecision:
    """Tests for PolicyDecision dataclass."""

    def test_allow_decision(self) -> None:
        """Test creating an allow decision."""
        d = PolicyDecision(decision="allow", policy_id="test")
        assert d.decision == "allow"
        assert d.violations == []
        assert d.warnings == []
        assert d.cached is False

    def test_deny_decision(self) -> None:
        """Test creating a deny decision with violations."""
        v = Violation(rule_id="test", message="fail", severity="high")
        d = PolicyDecision(decision="deny", policy_id="test", violations=[v])
        assert d.decision == "deny"
        assert len(d.violations) == 1


class TestCompositeDecision:
    """Tests for CompositeDecision dataclass."""

    def test_allow_result(self) -> None:
        """Test composite with allow decision."""
        c = CompositeDecision(final_decision="allow")
        assert c.final_decision == "allow"
        assert c.decisions == []
        assert c.blocking_violations == []

    def test_deny_result(self) -> None:
        """Test composite with deny decision and blocking violations."""
        v = Violation(rule_id="test", message="blocked", severity="critical")
        c = CompositeDecision(
            final_decision="deny",
            blocking_violations=[v],
        )
        assert c.final_decision == "deny"
        assert len(c.blocking_violations) == 1
