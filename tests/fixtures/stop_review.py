"""Small real Git worktrees for Stop evidence and reservation tests."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from forge.policy.semantic.stop_review import TurnContext, begin_turn, record_action
from forge.session import IndexStore, SessionStore, create_session_state
from forge.session.models import CodexConfirmed, PolicyIntent, SupervisorConfig
from tests.fixtures.session_state import publish_session

THREAD = "01900000-0000-7000-8000-000000000001"


def git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-c", "core.hooksPath=/dev/null", *args], cwd=root, stderr=subprocess.PIPE)


def context(tmp_path: Path, *, turn: int = 1, name: str = "executor") -> TurnContext:
    root = tmp_path / "repo"
    if not root.exists():
        root.mkdir()
        git(root, "init", "-q")
        git(root, "config", "user.name", "Fixture")
        git(root, "config", "user.email", "fixture@example.invalid")
        (root / ".gitignore").write_text(".forge/\nignored.txt\n")
        (root / "work.txt").write_text("original\n")
        git(root, "add", ".")
        git(root, "commit", "-qm", "baseline")
    plan = tmp_path / "approved.md"
    plan.write_text("Keep the work small and correct.\n")
    config = SupervisorConfig(review_trigger="stop", plan_override_path=str(plan), direct=True)
    store = SessionStore(str(root), name)
    if not store.exists():
        state = create_session_state(name, worktree_path=str(root), runtime="codex")
        state.forge_root = str(root)
        state.confirmed.codex = CodexConfirmed(thread_id=THREAD)
        state.intent.policy = PolicyIntent(enabled=True, bundles=[], supervisor=config)
        publish_session(IndexStore(), state, root)
    return TurnContext(
        root,
        name,
        root,
        THREAD,
        f"01900001-0000-7000-8000-{turn:012x}",
        config,
        None,
        store.review_identity(create=True) or "",
    )


def deadline() -> float:
    return time.monotonic() + 30


def changed(ctx: TurnContext, text: str = "changed\n", *, start: bool = True) -> None:
    if start:
        begin_turn(ctx, deadline=deadline())
    for phase in ("request", "outcome"):
        if phase == "outcome":
            (ctx.checkout / "work.txt").write_text(text)
        record_action(
            ctx,
            {
                "id": f"tool-{ctx.turn_id}",
                "phase": phase,
                "turn_id": ctx.turn_id,
                "tool": "apply_patch",
                "paths": ["work.txt"],
            },
        )
