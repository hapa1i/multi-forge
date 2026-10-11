"""B4: raw index stat bytes and denied patch paths falsely poisoned turn_evidence coverage."""

import os
from pathlib import Path

import pytest

from forge.policy.semantic import turn_evidence as evidence
from tests.fixtures.stop_review import context, deadline, git

pytestmark = pytest.mark.regression


def test_index_stat_refresh_is_not_a_repository_change(tmp_path: Path) -> None:
    ctx = context(tmp_path)
    before = evidence.capture(ctx.checkout, ctx.storage, deadline=deadline())
    index = ctx.checkout / ".git/index"
    old_index = index.read_bytes()
    path = ctx.checkout / "work.txt"
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10_000_000_000))
    git(ctx.checkout, "update-index", "--refresh")
    assert index.read_bytes() != old_index
    after = evidence.capture(ctx.checkout, ctx.storage, deadline=deadline())
    assert after["digest"] == before["digest"]
    assert evidence.compare(ctx.storage, before, after, [])["complete"]


def test_denied_unapplied_path_has_no_missing_outcome_or_scope_gap(
    tmp_path: Path,
) -> None:
    ctx = context(tmp_path)
    snapshot = evidence.capture(ctx.checkout, ctx.storage, deadline=deadline())
    rows = [
        dict(
            id="blocked",
            turn_id=ctx.turn_id,
            phase=phase,
            paths=["never-created.txt"],
            coverage_issue="patch_outside_review_scope",
        )
        for phase in ("request", "denied")
    ]
    result = evidence.compare(ctx.storage, snapshot, snapshot, rows)
    assert result["complete"]
    assert result["actions"] == []
