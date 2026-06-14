"""Regression: Codex TDD tests-first sort ignored nested tests/src layouts.

Bug: ``sort_contexts_tests_first`` matched only top-level ``tests/``/``src/`` prefixes,
while the TDD policy's ``applies_to`` uses ``is_under_directory`` (nested-aware). An atomic
``apply_patch`` listing impl before test under nested dirs (``pkg/src`` / ``pkg/tests``)
was not reordered tests-first, so impl evaluated first with ``tests_touched`` empty -> a
false TDD deny.

Fix: ``sort_contexts_tests_first`` reuses the shared ``is_under_directory``
(src/forge/cli/hooks/codex_policy.py, src/forge/policy/deterministic/base.py).
"""

from __future__ import annotations

import pytest

from forge.cli.hooks.codex_policy import sort_contexts_tests_first
from forge.policy.types import ActionContext

pytestmark = pytest.mark.regression


def _ctx(path: str) -> ActionContext:
    return ActionContext(
        origin="codex",
        event="PreToolUse.Write",
        tool_name="Write",
        tool_args={},
        repo_root="/repo",
        session_name="s",
        target_path=path,
    )


def test_nested_layout_sorts_tests_before_impl() -> None:
    # Patch order is impl-first (the false-deny trigger); the sort must put the test first.
    ordered = sort_contexts_tests_first([_ctx("pkg/src/widget.py"), _ctx("pkg/tests/test_widget.py")])
    assert [c.target_path for c in ordered] == ["pkg/tests/test_widget.py", "pkg/src/widget.py"]


def test_top_level_layout_still_sorts_tests_first() -> None:
    ordered = sort_contexts_tests_first([_ctx("src/widget.py"), _ctx("tests/test_widget.py")])
    assert [c.target_path for c in ordered] == ["tests/test_widget.py", "src/widget.py"]
