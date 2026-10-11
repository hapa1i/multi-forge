"""Codex's absolute patch paths must match relative snapshot keys, including carry-forward."""

from pathlib import Path

import pytest

from forge.policy.semantic import turn_evidence
from tests.fixtures.stop_review import context, deadline

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("absolute", [True, False])
def test_native_paths_keep_complete_in_repository_coverage(tmp_path: Path, absolute: bool) -> None:
    ctx = context(tmp_path)
    before = turn_evidence.capture(ctx.checkout, ctx.storage, deadline=deadline())
    path = ctx.checkout / "work.txt"
    path.write_text("changed\n")
    after = turn_evidence.capture(ctx.checkout, ctx.storage, deadline=deadline())
    actions = [
        {"id": "native", "phase": phase, "paths": [str(path) if absolute else "work.txt"]}
        for phase in ("request", "outcome")
    ]
    assert turn_evidence.compare(ctx.storage, before, after, actions)["complete"]
    actions[0]["paths"] = [str(tmp_path / "outside.txt")]
    result = turn_evidence.compare(ctx.storage, before, after, actions)
    assert not result["complete"]
    assert "tool_path_outside_snapshot" in result["omissions"]
