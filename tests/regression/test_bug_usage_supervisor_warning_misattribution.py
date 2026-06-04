"""Regression: non-supervisor policy warnings rendered as supervisor activity.

Bug: ``core/ops/usage_summary._policy_activity`` collected the entry-level composite
``warnings`` -- which ``policy/engine.py`` accumulates from EVERY policy in a PreToolUse
evaluation (``all_warnings.extend(d.warnings)``) -- and keyed ``PolicyActivity.has_content``
off the resulting total. A deterministic policy warning (e.g. TDD in permissive mode,
``tdd.tests-before-impl`` -> ``_warn(...)``) with no ``semantic.supervisor`` participation
therefore surfaced a phantom "supervisor: 0 allow / 0 warn / 0 block" section carrying an
unrelated warning.

Fix: warnings are collected from the ``semantic.supervisor`` sub-decision only, and
``_policy_activity`` returns ``None`` when the supervisor took part in no in-window
decision.

Affected: ``src/forge/core/ops/usage_summary.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.core.ops.usage_summary import build_session_activity_summary
from forge.session.models import PolicyConfirmed, create_session_state
from forge.session.store import SessionStore

pytestmark = pytest.mark.regression

_AT = "2026-06-03T12:00:00Z"


def _sub(policy_id: str, decision: str, warnings: list[str]) -> dict:
    return {
        "decision": decision,
        "policy_id": policy_id,
        "violations": [],
        "warnings": warnings,
        "cached": False,
        "evaluated_at": _AT,
    }


def _entry(*, final: str, composite_warnings: list[str], subs: list[dict]) -> dict:
    """A composite decision entry mirroring store.serialize_composite_decision: the
    entry-level ``warnings`` is the composite across all participating policies."""
    return {
        "final_decision": final,
        "context_summary": None,
        "blocking_violations": [],
        "warnings": composite_warnings,
        "evaluated_at": _AT,
        "decisions": subs,
    }


def _write(forge_root: Path, name: str, decisions: list[dict]) -> None:
    state = create_session_state(name, worktree_path=str(forge_root))
    state.confirmed.policy = PolicyConfirmed(decisions=decisions)
    SessionStore(str(forge_root), name).write(state)


def test_tdd_only_warning_is_not_supervisor_activity(tmp_path: Path) -> None:
    # TDD warned; the supervisor never participated in this evaluation.
    tdd_warning = "TDD: write a failing test first"
    _write(
        tmp_path,
        "planner",
        [
            _entry(
                final="warn",
                composite_warnings=[tdd_warning],
                subs=[_sub("tdd.tests-before-impl", "warn", [tdd_warning])],
            )
        ],
    )
    summary = build_session_activity_summary("planner", forge_root=str(tmp_path))
    # No supervisor sub-decision -> no supervisor section at all (was: phantom 0/0/0).
    assert summary.policy is None


def test_concurrent_tdd_warning_excluded_from_supervisor(tmp_path: Path) -> None:
    # One evaluation where TDD warned AND the supervisor allowed (no supervisor warning).
    tdd_warning = "TDD: write a failing test first"
    _write(
        tmp_path,
        "planner",
        [
            _entry(
                final="warn",
                composite_warnings=[tdd_warning],  # composite, contributed by TDD only
                subs=[
                    _sub("tdd.tests-before-impl", "warn", [tdd_warning]),
                    _sub("semantic.supervisor", "allow", []),
                ],
            )
        ],
    )
    summary = build_session_activity_summary("planner", forge_root=str(tmp_path))
    assert summary.policy is not None  # the supervisor allowed -> real supervisor activity
    assert summary.policy.supervisor_allow == 1
    assert summary.policy.supervisor_warn == 0
    # The TDD warning must NOT be attributed to the supervisor.
    assert summary.policy.total_warnings == 0
    assert summary.policy.recent_warnings == []
