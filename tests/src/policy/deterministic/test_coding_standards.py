"""Tests for policy/deterministic/coding_standards.py."""

import pytest

from forge.policy.deterministic.coding_standards import (
    NoBackwardCompatPolicy,
    NoEmojiPolicy,
    NoTypeCheckingPolicy,
)
from forge.policy.types import ActionContext


class TestNoTypeCheckingPolicy:
    """Tests for the no-TYPE_CHECKING policy."""

    @pytest.fixture
    def policy(self) -> NoTypeCheckingPolicy:
        return NoTypeCheckingPolicy()

    def test_applies_to_python_files(self, policy: NoTypeCheckingPolicy) -> None:
        """Policy applies to Python files with content."""
        ctx = ActionContext(
            origin="claude_code",
            event="PreToolUse.Write",
            tool_name="Write",
            tool_args={},
            repo_root="/repo",
            session_name="test",
            target_path="src/foo.py",
            new_content="import os",
        )
        assert policy.applies_to(ctx)

    def test_not_applies_to_non_python(self, policy: NoTypeCheckingPolicy) -> None:
        """Policy does not apply to non-Python files."""
        ctx = ActionContext(
            origin="claude_code",
            event="PreToolUse.Write",
            tool_name="Write",
            tool_args={},
            repo_root="/repo",
            session_name="test",
            target_path="src/foo.js",
            new_content="import os",
        )
        assert not policy.applies_to(ctx)

    def test_allows_normal_imports(self, policy: NoTypeCheckingPolicy) -> None:
        """Allows normal import statements."""
        ctx = ActionContext(
            origin="claude_code",
            event="PreToolUse.Write",
            tool_name="Write",
            tool_args={},
            repo_root="/repo",
            session_name="test",
            target_path="src/foo.py",
            new_content="from typing import List, Dict",
        )
        result = policy.evaluate(ctx)
        assert result.decision == "allow"

    def test_denies_type_checking_block(self, policy: NoTypeCheckingPolicy) -> None:
        """Denies TYPE_CHECKING conditional blocks."""
        ctx = ActionContext(
            origin="claude_code",
            event="PreToolUse.Write",
            tool_name="Write",
            tool_args={},
            repo_root="/repo",
            session_name="test",
            target_path="src/foo.py",
            new_content="if TYPE_CHECKING:\n    from .other import Foo",
        )
        result = policy.evaluate(ctx)
        assert result.decision == "deny"
        assert len(result.violations) == 1

    def test_denies_type_checking_import(self, policy: NoTypeCheckingPolicy) -> None:
        """Denies importing TYPE_CHECKING."""
        ctx = ActionContext(
            origin="claude_code",
            event="PreToolUse.Write",
            tool_name="Write",
            tool_args={},
            repo_root="/repo",
            session_name="test",
            target_path="src/foo.py",
            new_content="from typing import TYPE_CHECKING",
        )
        result = policy.evaluate(ctx)
        assert result.decision == "deny"


class TestNoBackwardCompatPolicy:
    """Tests for the no-backward-compat policy."""

    @pytest.fixture
    def policy(self) -> NoBackwardCompatPolicy:
        return NoBackwardCompatPolicy()

    def test_allows_normal_code(self, policy: NoBackwardCompatPolicy) -> None:
        """Allows normal code without backward-compat patterns."""
        ctx = ActionContext(
            origin="claude_code",
            event="PreToolUse.Write",
            tool_name="Write",
            tool_args={},
            repo_root="/repo",
            session_name="test",
            target_path="src/foo.py",
            new_content="def foo():\n    return 42",
        )
        result = policy.evaluate(ctx)
        assert result.decision == "allow"

    def test_denies_backward_compat_comment(self, policy: NoBackwardCompatPolicy) -> None:
        """Denies backward compatibility comments."""
        ctx = ActionContext(
            origin="claude_code",
            event="PreToolUse.Write",
            tool_name="Write",
            tool_args={},
            repo_root="/repo",
            session_name="test",
            target_path="src/foo.py",
            new_content="# backward compat\ndef old_func(): pass",
        )
        result = policy.evaluate(ctx)
        assert result.decision == "deny"

    def test_denies_legacy_comment(self, policy: NoBackwardCompatPolicy) -> None:
        """Denies legacy comments."""
        ctx = ActionContext(
            origin="claude_code",
            event="PreToolUse.Write",
            tool_name="Write",
            tool_args={},
            repo_root="/repo",
            session_name="test",
            target_path="src/foo.py",
            new_content="# legacy support\ndef old_func(): pass",
        )
        result = policy.evaluate(ctx)
        assert result.decision == "deny"

    def test_denies_deprecated_comment(self, policy: NoBackwardCompatPolicy) -> None:
        """Denies deprecated comments."""
        ctx = ActionContext(
            origin="claude_code",
            event="PreToolUse.Write",
            tool_name="Write",
            tool_args={},
            repo_root="/repo",
            session_name="test",
            target_path="src/foo.py",
            new_content="# deprecated\ndef old_func(): pass",
        )
        result = policy.evaluate(ctx)
        assert result.decision == "deny"

    def test_denies_todo_remove_later(self, policy: NoBackwardCompatPolicy) -> None:
        """Denies TODO remove later comments."""
        ctx = ActionContext(
            origin="claude_code",
            event="PreToolUse.Write",
            tool_name="Write",
            tool_args={},
            repo_root="/repo",
            session_name="test",
            target_path="src/foo.py",
            new_content="# TODO: remove this later\ndef old_func(): pass",
        )
        result = policy.evaluate(ctx)
        assert result.decision == "deny"


class TestNoEmojiPolicy:
    """Tests for the no-emoji policy."""

    @pytest.fixture
    def policy(self) -> NoEmojiPolicy:
        return NoEmojiPolicy()

    def test_applies_to_python(self, policy: NoEmojiPolicy) -> None:
        ctx = ActionContext(
            origin="claude_code",
            event="PreToolUse.Write",
            tool_name="Write",
            tool_args={},
            repo_root="/repo",
            session_name="test",
            target_path="src/foo.py",
            new_content="print('hello')",
        )
        assert policy.applies_to(ctx)

    def test_applies_to_javascript(self, policy: NoEmojiPolicy) -> None:
        ctx = ActionContext(
            origin="claude_code",
            event="PreToolUse.Write",
            tool_name="Write",
            tool_args={},
            repo_root="/repo",
            session_name="test",
            target_path="src/app.ts",
            new_content="console.log('hello')",
        )
        assert policy.applies_to(ctx)

    def test_not_applies_to_markdown(self, policy: NoEmojiPolicy) -> None:
        ctx = ActionContext(
            origin="claude_code",
            event="PreToolUse.Write",
            tool_name="Write",
            tool_args={},
            repo_root="/repo",
            session_name="test",
            target_path="docs/README.md",
            new_content="# Hello",
        )
        assert not policy.applies_to(ctx)

    def test_not_applies_to_json(self, policy: NoEmojiPolicy) -> None:
        ctx = ActionContext(
            origin="claude_code",
            event="PreToolUse.Write",
            tool_name="Write",
            tool_args={},
            repo_root="/repo",
            session_name="test",
            target_path="config.json",
            new_content="{}",
        )
        assert not policy.applies_to(ctx)

    def test_allows_clean_code(self, policy: NoEmojiPolicy) -> None:
        ctx = ActionContext(
            origin="claude_code",
            event="PreToolUse.Write",
            tool_name="Write",
            tool_args={},
            repo_root="/repo",
            session_name="test",
            target_path="src/foo.py",
            new_content="def hello():\n    return 'world'",
        )
        result = policy.evaluate(ctx)
        assert result.decision == "allow"

    def test_allows_text_safe_symbols(self, policy: NoEmojiPolicy) -> None:
        """Text-safe dingbats (checkmark, cross, warning, arrows) are allowed."""
        ctx = ActionContext(
            origin="claude_code",
            event="PreToolUse.Write",
            tool_name="Write",
            tool_args={},
            repo_root="/repo",
            session_name="test",
            target_path="src/foo.py",
            new_content="# \u2714 pass  \u2718 fail  \u26a0\ufe0e warning  \u2192 next",
        )
        result = policy.evaluate(ctx)
        assert result.decision == "allow"

    def test_denies_face_emoji(self, policy: NoEmojiPolicy) -> None:
        ctx = ActionContext(
            origin="claude_code",
            event="PreToolUse.Write",
            tool_name="Write",
            tool_args={},
            repo_root="/repo",
            session_name="test",
            target_path="src/foo.py",
            new_content="print('Hello \U0001f600')",
        )
        result = policy.evaluate(ctx)
        assert result.decision == "deny"
        assert len(result.violations) == 1
        assert "emoji" in result.violations[0].message.lower()

    def test_denies_rocket_emoji(self, policy: NoEmojiPolicy) -> None:
        ctx = ActionContext(
            origin="claude_code",
            event="PreToolUse.Write",
            tool_name="Write",
            tool_args={},
            repo_root="/repo",
            session_name="test",
            target_path="src/deploy.sh",
            new_content="echo 'Deploying \U0001f680'",
        )
        result = policy.evaluate(ctx)
        assert result.decision == "deny"

    def test_denies_fire_emoji_in_edit(self, policy: NoEmojiPolicy) -> None:
        ctx = ActionContext(
            origin="claude_code",
            event="PreToolUse.Edit",
            tool_name="Edit",
            tool_args={},
            repo_root="/repo",
            session_name="test",
            target_path="src/foo.py",
            new_content="# \U0001f525 Hot path",
        )
        result = policy.evaluate(ctx)
        assert result.decision == "deny"

    def test_evidence_shows_unique_emoji(self, policy: NoEmojiPolicy) -> None:
        ctx = ActionContext(
            origin="claude_code",
            event="PreToolUse.Write",
            tool_name="Write",
            tool_args={},
            repo_root="/repo",
            session_name="test",
            target_path="src/foo.py",
            new_content="# \U0001f680 \U0001f525 \U0001f680 repeated",
        )
        result = policy.evaluate(ctx)
        assert result.decision == "deny"
        evidence = result.violations[0].evidence
        assert evidence is not None
        assert "3 emoji" in evidence
