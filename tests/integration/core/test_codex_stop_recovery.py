"""Stop recovery across real CLI processes and durable state; no runtime inference."""

import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest

from forge.policy.semantic import stop_review as review
from forge.policy.semantic.supervisor import SupervisorRun
from forge.policy.types import PolicyDecision
from forge.session import IndexStore
from forge.session.events import get_session_event_journal_path
from forge.session.models import PolicyIntent, create_session_state
from tests.fixtures.session_state import publish_session
from tests.fixtures.stop_review import changed, context, deadline

pytestmark = pytest.mark.integration


def test_operator_resets_incomplete_scope_then_next_prompt_can_be_reviewed(tmp_path: Path, monkeypatch) -> None:
    ctx = context(tmp_path)
    state = create_session_state(ctx.session, worktree_path=str(ctx.checkout), runtime="codex")
    state.intent.policy = PolicyIntent(enabled=True, supervisor=ctx.config)
    state.forge_root = str(ctx.forge_root)
    publish_session(IndexStore(), state, ctx.checkout, forge_root=ctx.forge_root)
    changed(ctx)
    review.record_action(ctx, {"id": "lost-outcome", "phase": "request", "turn_id": ctx.turn_id})
    assert (
        review.review_stop(ctx, deadline=deadline(), current_config=lambda: ctx.config_digest).status == "unavailable"
    )
    journal = get_session_event_journal_path(ctx.forge_root, ctx.session, "review")
    before = journal.read_bytes()

    def command(*extra: str) -> dict:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "from forge.cli.main import main; main()",
                "policy",
                "supervisor",
                "reset-review",
                "--session",
                ctx.session,
                "--json",
                *extra,
            ],
            cwd=ctx.checkout,
            env=dict(
                os.environ,
                FORGE_FORGE_ROOT=str(ctx.forge_root),
                PYTHON_DOTENV_DISABLED="1",
            ),
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, result.stderr
        assert result.stderr == ""
        return json.loads(result.stdout)

    assert command()["applied"] is False
    assert journal.read_bytes() == before
    assert command("--yes")["applied"] is True
    review.begin_turn(ctx, deadline=deadline())
    assert review.status(ctx.forge_root, ctx.session)["reset_requested"]
    new = replace(ctx, turn_id="01900001-0000-7000-8000-000000000002")
    changed(new, "after operator reset\n")
    call = Mock(return_value=SupervisorRun(PolicyDecision("allow", "semantic.supervisor"), run_ok=True, parsed=True))
    monkeypatch.setattr(review, "run_supervisor_check", call)
    assert review.review_stop(new, deadline=deadline(), current_config=lambda: new.config_digest).complete
    assert review.status(ctx.forge_root, ctx.session)["excluded_work"]["reviewed"] is False
    assert call.call_count == 1
