"""Regression: fork/resume/relaunch must carry the supervisor consumer-lane intent.

Bug (consumer_lanes T1b review, HIGH): the per-field intent-inheritance loops in
``SessionManager._create_resume_child``, ``fork_session``, and ``relaunch_session``
enumerated a fixed allowlist (``subprocess_proxy``, ``policy``, ``memory``,
``system_prompt``, ``verification``). Promoting the supervisor lane out of
``intent.policy.supervisor.supervisor_runtime`` into the sibling
``intent.consumer_lanes`` silently dropped it from that allowlist, so a codex-bound
parent produced a child that silently downgraded to the default opus lane.

Root cause: a field moved out of an inherited container into a non-inherited sibling.
Affected: ``src/forge/session/manager.py`` (3 allowlist sites).

Each path inherits the re-resolvable *intent* but NOT the frozen *confirmed* binding:
confirmed is hook-written and re-freezes on the child's own first dispatch.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from forge.policy.semantic.supervisor import SUPERVISOR_CONSUMER
from forge.session import SessionManager, SessionStore
from forge.session.consumer_lanes import set_intent_lane
from forge.session.models import LaneRecord, SessionState

pytestmark = pytest.mark.regression

# The codex lane is SUPERVISOR_CONSUMER's one declared non-default override (T4); using it
# makes inheritance observable -- a dropped lane would silently fall back to the opus default.
_CODEX = LaneRecord("codex", "chatgpt", "gpt-5-codex")


def _init_forge_project(path: Path) -> None:
    subprocess.run(["git", "init", str(path)], capture_output=True, check=True)
    (path / ".claude").mkdir()
    (path / ".forge").mkdir()


def _pin_supervisor_lane(project: Path, name: str, lane: LaneRecord) -> None:
    store = SessionStore(str(project), name)
    store.update(timeout_s=5.0, mutate=lambda m: set_intent_lane(m, SUPERVISOR_CONSUMER, lane))


def _assert_inherited_codex(child: SessionState, project: Path, child_name: str) -> None:
    # In-memory child state carries the intent override...
    assert child.intent.consumer_lanes is not None
    assert child.intent.consumer_lanes.supervisor == _CODEX
    # ...the frozen binding is NOT inherited; the child re-freezes on its own first dispatch.
    assert child.confirmed.consumer_lanes is None
    # ...and the persisted manifest agrees (inheritance is written, not just returned).
    persisted = SessionStore(str(project), child_name).read()
    assert persisted.intent.consumer_lanes is not None
    assert persisted.intent.consumer_lanes.supervisor == _CODEX
    assert persisted.confirmed.consumer_lanes is None


def test_resume_child_inherits_supervisor_lane(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _init_forge_project(project)
    manager = SessionManager()
    manager.start_session(name="parent", worktree_path=str(project), direct=True)
    _pin_supervisor_lane(project, "parent", _CODEX)

    child, _handoff = manager.resume_session("parent", child_name="child")

    _assert_inherited_codex(child, project, "child")


def test_fork_child_inherits_supervisor_lane(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _init_forge_project(project)
    manager = SessionManager()
    manager.start_session(name="parent", worktree_path=str(project), direct=True)
    _pin_supervisor_lane(project, "parent", _CODEX)

    _parent, fork = manager.fork_session("parent", "fork")

    _assert_inherited_codex(fork, project, "fork")


def test_relaunch_child_inherits_supervisor_lane(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _init_forge_project(project)
    manager = SessionManager()
    manager.start_session(name="parent", worktree_path=str(project), direct=True)
    _pin_supervisor_lane(project, "parent", _CODEX)

    _parent, child = manager.relaunch_session("parent", child_name="child")

    _assert_inherited_codex(child, project, "child")
