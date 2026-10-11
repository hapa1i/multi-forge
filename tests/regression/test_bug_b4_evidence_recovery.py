"""B4 #3/#15: ordinary evidence limits froze review, and no-newline diffs were malformed."""

import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest

from forge.cli.hooks.codex_stop import _action
from forge.policy.semantic import stop_review as review
from forge.policy.semantic import turn_evidence
from forge.policy.semantic.supervisor import SupervisorRun
from forge.policy.types import PolicyDecision
from tests.fixtures.stop_review import changed, context, deadline

pytestmark = pytest.mark.regression


def run(ctx):
    return review.review_stop(ctx, deadline=deadline(), current_config=lambda: ctx.config_digest)


def test_large_read_does_not_disable_later_reviews(tmp_path: Path, monkeypatch) -> None:
    ctx = context(tmp_path)
    call = Mock(return_value=SupervisorRun(PolicyDecision("deny", "semantic.supervisor"), run_ok=True, parsed=True))
    monkeypatch.setattr(review, "run_supervisor_check", call)
    review.begin_turn(ctx, deadline=deadline())
    data = {
        "tool_use_id": "read",
        "tool_name": "exec_command",
        "tool_input": {"cmd": "cat work.txt"},
        "tool_response": "x" * 7000,
    }
    for phase in ("request", "outcome"):
        review.record_action(ctx, _action(data, phase, ctx))
    first = run(ctx)
    assert first.status == "partial" and not first.correction and not first.complete
    assert "tool_evidence_byte_limit" in review.status(ctx.forge_root, ctx.session)["coverage"]["omissions"]
    call.return_value = SupervisorRun(PolicyDecision("allow", "semantic.supervisor"), run_ok=True, parsed=True)
    for number in range(2, 6):
        later = replace(ctx, turn_id=f"01900001-0000-7000-8000-{number:012x}")
        changed(later, f"small edit {number}\n")
        assert run(later).status == "reviewed"
    assert call.call_count == 5
    assert review.status(ctx.forge_root, ctx.session)["excluded_work"]["reviewed"] is False


def test_resolved_binary_gap_does_not_remain_in_coverage(tmp_path: Path, monkeypatch) -> None:
    ctx = context(tmp_path)
    changed(ctx)
    (ctx.checkout / "binary").write_bytes(b"\0")
    call = Mock(return_value=SupervisorRun(PolicyDecision("allow", "semantic.supervisor"), run_ok=True, parsed=True))
    monkeypatch.setattr(review, "run_supervisor_check", call)
    assert run(ctx).status == "partial"
    (ctx.checkout / "binary").unlink()
    later = replace(ctx, turn_id="01900001-0000-7000-8000-000000000002")
    changed(later, "small edit\n")
    assert run(later).status == "reviewed"
    assert json.loads(call.call_args.args[1].raw_diff)["omissions"] == []


def test_unterminated_lines_have_distinct_diff_records(tmp_path: Path) -> None:
    ctx = context(tmp_path)
    (ctx.checkout / "work.txt").write_text("before")
    before = turn_evidence.capture(ctx.checkout, ctx.storage, deadline=deadline())
    (ctx.checkout / "work.txt").write_text("after")
    after = turn_evidence.capture(ctx.checkout, ctx.storage, deadline=deadline())
    evidence = turn_evidence.compare(ctx.storage, before, after, [])
    diff = evidence["changes"][0]["diff"]
    assert "-before\n\\ No newline at end of file\n+after\n\\ No newline at end of file\n" in diff
