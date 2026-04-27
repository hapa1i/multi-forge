"""Regression: re-approving identical plan content must not inflate Plans approved count.

Bug: `%plan` / `forge session show` reported ``Plans approved: 2`` when the user
had approved the same plan content twice within a short window. Root cause was a
timestamp-based snapshot filename (`make_timestamp_suffix`) that produced a new
file on every ExitPlanMode, plus an unconditional append to
``confirmed.artifacts["plans"]``.

Fix layers:

1. Snapshot filenames: ``{stem}-{hash}.md`` — source stem for readability, hash
   for dedup. Same source + same content = same path. Different source filenames
   with identical content produce distinct paths (accepted tradeoff).
2. Hook-level unique-entry rewrite: drop any existing entry with the same
   ``snapshot_path`` and append a fresh one, so duplicates stay collapsed while
   the most recently approved unique plan remains last in the list.

Affected files:
- src/forge/session/artifacts.py (snapshot_plan_approved, make_content_hash)
- src/forge/cli/hooks/commands.py (exit_plan_mode dedup)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from forge.session.artifacts import get_artifact_paths, snapshot_plan_approved
from forge.session.models import create_session_state
from forge.session.store import SessionStore

pytestmark = pytest.mark.regression


def test_identical_content_collapses_to_single_snapshot(tmp_path: Path) -> None:
    """Two snapshots of the same content must resolve to one file on disk."""
    plan_file = tmp_path / "plan.md"
    plan_file.write_text("# Plan\n\nStep 1: do thing")

    paths = get_artifact_paths(tmp_path, "planner")
    first_abs, first_rel = snapshot_plan_approved(paths=paths, source_plan_path=plan_file)
    second_abs, second_rel = snapshot_plan_approved(paths=paths, source_plan_path=plan_file)

    assert first_rel == second_rel
    assert first_abs == second_abs
    assert first_abs.is_file()
    assert len(list(paths.plans_abs.iterdir())) == 1


def test_changed_content_produces_distinct_snapshot(tmp_path: Path) -> None:
    """Genuine replans (different content) must still produce distinct files."""
    plan_file = tmp_path / "plan.md"
    paths = get_artifact_paths(tmp_path, "planner")

    plan_file.write_text("# Plan v1")
    _, rel_v1 = snapshot_plan_approved(paths=paths, source_plan_path=plan_file)

    plan_file.write_text("# Plan v2 — with new step")
    _, rel_v2 = snapshot_plan_approved(paths=paths, source_plan_path=plan_file)

    assert rel_v1 != rel_v2
    assert len(list(paths.plans_abs.iterdir())) == 2


def test_identical_content_across_renames_produces_distinct_snapshots(tmp_path: Path) -> None:
    """Cross-rename case: ``plan-a.md`` and ``plan-b.md`` with identical bytes
    produce different snapshot paths because filenames are stem-prefixed.
    Accepted tradeoff for human-readable snapshot names."""
    paths = get_artifact_paths(tmp_path, "planner")

    (tmp_path / "plan-a.md").write_text("# Same bytes\nnothing changed")
    (tmp_path / "plan-b.md").write_text("# Same bytes\nnothing changed")

    _, rel_a = snapshot_plan_approved(paths=paths, source_plan_path=tmp_path / "plan-a.md")
    _, rel_b = snapshot_plan_approved(paths=paths, source_plan_path=tmp_path / "plan-b.md")

    assert rel_a != rel_b
    assert len(list(paths.plans_abs.iterdir())) == 2


def _run_exit_plan_mode_hook(
    tmp_path: Path,
    session_name: str,
    source_plan_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    """Invoke `forge hook exit-plan-mode` via the Click runner and return the JSON payload."""
    from click.testing import CliRunner

    from forge.cli.main import hooks

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FORGE_FORGE_ROOT", str(tmp_path))
    monkeypatch.setenv("FORGE_SESSION", session_name)

    payload = {"hook_event_name": "PreToolUse", "transcript_path": ""}
    runner = CliRunner()

    # The hook resolves source_plan_path via confirmed.latest_plan_path or a
    # transcript scan. We pre-set latest_plan_path to the test plan file.
    store = SessionStore(str(tmp_path), session_name)
    state = store.read()
    state.confirmed.latest_plan_path = source_plan_path.relative_to(tmp_path).as_posix()
    store.write(state)

    result = runner.invoke(hooks, ["exit-plan-mode"], input=json.dumps(payload))
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def _load_plans(tmp_path: Path, session_name: str) -> list[dict[str, Any]]:
    plans = SessionStore(str(tmp_path), session_name).read().confirmed.artifacts.get("plans", [])
    assert isinstance(plans, list)
    return plans


def test_hook_dedups_consecutive_identical_approvals(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Hook must not append a duplicate audit entry for A -> A."""
    state = create_session_state("planner", worktree_path=str(tmp_path))
    state.forge_root = str(tmp_path)
    SessionStore(str(tmp_path), "planner").write(state)

    plan = tmp_path / "plan.md"
    plan.write_text("# Plan A")

    _run_exit_plan_mode_hook(tmp_path, "planner", plan, monkeypatch)
    _run_exit_plan_mode_hook(tmp_path, "planner", plan, monkeypatch)

    assert len(_load_plans(tmp_path, "planner")) == 1


def test_hook_dedups_non_consecutive_repeats(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Hook must not append when A reappears after B. Sequence A -> B -> A
    results in [A, B], not [A, B, A]."""
    state = create_session_state("planner", worktree_path=str(tmp_path))
    state.forge_root = str(tmp_path)
    SessionStore(str(tmp_path), "planner").write(state)

    plan = tmp_path / "plan.md"

    plan.write_text("# Plan A")
    first = _run_exit_plan_mode_hook(tmp_path, "planner", plan, monkeypatch)

    plan.write_text("# Plan B (different)")
    second = _run_exit_plan_mode_hook(tmp_path, "planner", plan, monkeypatch)

    plan.write_text("# Plan A")  # revert to A
    third = _run_exit_plan_mode_hook(tmp_path, "planner", plan, monkeypatch)

    plans = _load_plans(tmp_path, "planner")
    assert len(plans) == 2, f"expected [A, B], got {len(plans)} entries"
    # Confirm the distinct snapshot_paths are exactly two.
    assert len({p["snapshot_path"] for p in plans}) == 2
    # The re-approved A entry becomes the latest unique approval, so readers
    # that use "last snapshot wins" surface the current approved plan.
    assert first["snapshot_path"] == third["snapshot_path"] == plans[-1]["snapshot_path"]
    assert second["snapshot_path"] == plans[0]["snapshot_path"]
