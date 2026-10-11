"""B4 #8/#14: move origins escaped scope checks and accepted symlink plans failed at Stop."""

from dataclasses import replace
from pathlib import Path

import pytest

from forge.cli.hooks.codex_stop import _action
from forge.core.ops.policy import _validated_plan_path
from forge.policy.semantic.plan_source import read_plan
from tests.fixtures.stop_review import context

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("source", ["../outside.txt", ".forge/hidden.txt"])
def test_move_checks_source_as_well_as_destination(tmp_path: Path, source: str) -> None:
    ctx = context(tmp_path)
    patch = f"*** Begin Patch\n*** Update File: {source}\n*** Move to: imported.txt\n@@\n-old\n+new\n*** End Patch"
    action = _action(
        {
            "tool_use_id": "move",
            "tool_name": "apply_patch",
            "tool_input": {"command": patch},
        },
        "request",
        ctx,
    )
    assert action["coverage_issue"] == "patch_outside_review_scope"


def test_accepted_plan_link_is_pinned_to_its_readable_target(tmp_path: Path) -> None:
    ctx = context(tmp_path)
    link = tmp_path / "plan-link.md"
    assert ctx.config.plan_override_path is not None
    link.symlink_to(ctx.config.plan_override_path)
    accepted = _validated_plan_path(link)
    assert accepted == str(Path(ctx.config.plan_override_path).resolve())
    snapshot = read_plan(replace(ctx.config, plan_override_path=accepted))
    assert snapshot.text == Path(ctx.config.plan_override_path).read_text()
