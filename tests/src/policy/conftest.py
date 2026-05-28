"""Fixtures for policy module tests."""

from __future__ import annotations

import pytest

from forge.policy.types import ActionContext


@pytest.fixture
def write_context() -> ActionContext:
    """Create a Write action context for testing."""
    return ActionContext(
        event="PreToolUse.Write",
        tool_name="Write",
        tool_args={"file_path": "/repo/src/foo.py", "content": "print(1)"},
        repo_root="/repo",
        session_name="test-session",
        target_path="src/foo.py",
        new_content="print(1)",
    )


@pytest.fixture
def edit_context() -> ActionContext:
    """Create an Edit action context for testing."""
    return ActionContext(
        event="PreToolUse.Edit",
        tool_name="Edit",
        tool_args={
            "file_path": "/repo/src/foo.py",
            "old_string": "x",
            "new_string": "y",
        },
        repo_root="/repo",
        session_name="test-session",
        target_path="src/foo.py",
        new_content="y",
    )


@pytest.fixture
def test_file_context() -> ActionContext:
    """Create a test file Write context for testing."""
    return ActionContext(
        event="PreToolUse.Write",
        tool_name="Write",
        tool_args={
            "file_path": "/repo/tests/test_foo.py",
            "content": "def test_foo(): pass",
        },
        repo_root="/repo",
        session_name="test-session",
        target_path="tests/test_foo.py",
        new_content="def test_foo(): pass",
    )
