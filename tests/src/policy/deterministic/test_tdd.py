"""Tests for policy/deterministic/tdd.py."""

import pytest

from forge.policy.deterministic.tdd import (
    NoSkipTestsPolicy,
    TDDEnforcementPolicy,
)
from forge.policy.types import ActionContext


class TestTDDEnforcementPolicy:
    """Tests for the tests-before-impl TDD policy."""

    @pytest.fixture
    def policy(self) -> TDDEnforcementPolicy:
        """Create a strict tests-before-impl policy."""
        return TDDEnforcementPolicy(strict=True)

    @pytest.fixture
    def permissive_policy(self) -> TDDEnforcementPolicy:
        """Create a permissive tests-before-impl policy."""
        return TDDEnforcementPolicy(strict=False)

    def test_applies_to_src_writes(self, policy: TDDEnforcementPolicy) -> None:
        """Policy applies to writes under src/."""
        ctx = ActionContext(
            origin="claude_code",
            event="PreToolUse.Write",
            tool_name="Write",
            tool_args={},
            repo_root="/repo",
            session_name="test",
            target_path="src/foo.py",
        )
        assert policy.applies_to(ctx)

    def test_applies_to_tests_writes(self, policy: TDDEnforcementPolicy) -> None:
        """Policy applies to writes under tests/."""
        ctx = ActionContext(
            origin="claude_code",
            event="PreToolUse.Write",
            tool_name="Write",
            tool_args={},
            repo_root="/repo",
            session_name="test",
            target_path="tests/test_foo.py",
        )
        assert policy.applies_to(ctx)

    def test_not_applies_to_other_paths(self, policy: TDDEnforcementPolicy) -> None:
        """Policy does not apply to other paths."""
        ctx = ActionContext(
            origin="claude_code",
            event="PreToolUse.Write",
            tool_name="Write",
            tool_args={},
            repo_root="/repo",
            session_name="test",
            target_path="docs/readme.md",
        )
        assert not policy.applies_to(ctx)

    def test_denies_impl_without_tests(self, policy: TDDEnforcementPolicy, write_context: ActionContext) -> None:
        """Denies writing to src/ when no tests have been touched."""
        result = policy.evaluate(write_context)
        assert result.decision == "deny"
        assert len(result.violations) == 1
        assert "test" in result.violations[0].message.lower()

    def test_allows_test_writes(self, policy: TDDEnforcementPolicy, test_file_context: ActionContext) -> None:
        """Allows writing to tests/ directory."""
        result = policy.evaluate(test_file_context)
        assert result.decision == "allow"

    def test_allows_impl_after_tests(
        self,
        policy: TDDEnforcementPolicy,
        test_file_context: ActionContext,
        write_context: ActionContext,
    ) -> None:
        """Allows writing to src/ after tests have been touched."""
        # First touch tests
        policy.evaluate(test_file_context)

        # Now impl should be allowed
        result = policy.evaluate(write_context)
        assert result.decision == "allow"

    def test_permissive_warns_instead_of_deny(
        self, permissive_policy: TDDEnforcementPolicy, write_context: ActionContext
    ) -> None:
        """Permissive mode warns instead of denying."""
        result = permissive_policy.evaluate(write_context)
        assert result.decision == "warn"
        assert len(result.warnings) == 1

    def test_state_persistence(
        self,
        policy: TDDEnforcementPolicy,
        test_file_context: ActionContext,
    ) -> None:
        """Tests touched state can be persisted and restored."""
        # Touch a test
        policy.evaluate(test_file_context)

        # Get state
        state = policy.get_state()
        assert "tests/test_foo.py" in state["tests_touched"]

        # Create new policy and restore state
        new_policy = TDDEnforcementPolicy()
        new_policy.set_state(state)

        # Verify state restored
        assert "tests/test_foo.py" in new_policy._tests_touched


class TestNoSkipTestsPolicy:
    """Tests for the no-skip-tests policy."""

    @pytest.fixture
    def policy(self) -> NoSkipTestsPolicy:
        """Create a no-skip-tests policy."""
        return NoSkipTestsPolicy()

    def test_applies_to_content_with_code(self, policy: NoSkipTestsPolicy) -> None:
        """Policy applies when there is diff content."""
        ctx = ActionContext(
            origin="claude_code",
            event="PreToolUse.Write",
            tool_name="Write",
            tool_args={},
            repo_root="/repo",
            session_name="test",
            target_path="tests/test_foo.py",
            new_content="def test_foo(): pass",
        )
        assert policy.applies_to(ctx)

    def test_not_applies_without_content(self, policy: NoSkipTestsPolicy) -> None:
        """Policy does not apply without diff content."""
        ctx = ActionContext(
            origin="claude_code",
            event="PreToolUse.Write",
            tool_name="Write",
            tool_args={},
            repo_root="/repo",
            session_name="test",
            target_path="tests/test_foo.py",
            new_content=None,
        )
        assert not policy.applies_to(ctx)

    def test_allows_normal_tests(self, policy: NoSkipTestsPolicy) -> None:
        """Allows normal test code."""
        ctx = ActionContext(
            origin="claude_code",
            event="PreToolUse.Write",
            tool_name="Write",
            tool_args={},
            repo_root="/repo",
            session_name="test",
            target_path="tests/test_foo.py",
            new_content="def test_foo():\n    assert True",
        )
        result = policy.evaluate(ctx)
        assert result.decision == "allow"

    def test_denies_pytest_skip(self, policy: NoSkipTestsPolicy) -> None:
        """Denies pytest.skip() calls."""
        ctx = ActionContext(
            origin="claude_code",
            event="PreToolUse.Write",
            tool_name="Write",
            tool_args={},
            repo_root="/repo",
            session_name="test",
            target_path="tests/test_foo.py",
            new_content='def test_foo():\n    pytest.skip("not ready")',
        )
        result = policy.evaluate(ctx)
        assert result.decision == "deny"
        assert len(result.violations) == 1

    def test_denies_pytest_mark_skip(self, policy: NoSkipTestsPolicy) -> None:
        """Denies @pytest.mark.skip decorator."""
        ctx = ActionContext(
            origin="claude_code",
            event="PreToolUse.Write",
            tool_name="Write",
            tool_args={},
            repo_root="/repo",
            session_name="test",
            target_path="tests/test_foo.py",
            new_content="@pytest.mark.skip\ndef test_foo(): pass",
        )
        result = policy.evaluate(ctx)
        assert result.decision == "deny"

    def test_denies_pytest_mark_skipif(self, policy: NoSkipTestsPolicy) -> None:
        """Denies @pytest.mark.skipif decorator."""
        ctx = ActionContext(
            origin="claude_code",
            event="PreToolUse.Write",
            tool_name="Write",
            tool_args={},
            repo_root="/repo",
            session_name="test",
            target_path="tests/test_foo.py",
            new_content='@pytest.mark.skipif(True, reason="test")\ndef test_foo(): pass',
        )
        result = policy.evaluate(ctx)
        assert result.decision == "deny"

    def test_denies_unittest_skip(self, policy: NoSkipTestsPolicy) -> None:
        """Denies unittest.skip decorator."""
        ctx = ActionContext(
            origin="claude_code",
            event="PreToolUse.Write",
            tool_name="Write",
            tool_args={},
            repo_root="/repo",
            session_name="test",
            target_path="tests/test_foo.py",
            new_content='@unittest.skip("reason")\ndef test_foo(): pass',
        )
        result = policy.evaluate(ctx)
        assert result.decision == "deny"
