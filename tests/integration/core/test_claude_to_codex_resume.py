"""Real-codex end-to-end: plan in Claude (recorded) -> implement in Codex (Slice 5e).

Exercises the full ``bridge_session_to_codex`` stack that the hermetic unit suite can only
mock: a recorded "planning" transcript is curated into a Codex-targeted transfer, prepended
to a task, and handed to a **real** ``codex exec`` run -- with BOTH the curation usage event
and the ``codex_exec`` event landing under one run tree.

Only the curation network call (``_call_llm_for_curation``) is mocked. ``ai-curated`` defaults
to OpenRouter (``transfer.py``), which silently falls back to ``structured`` without auth, so
without the mock the two-event join would not be proven; mocking it keeps **codex auth** the
sole hard external dependency. Everything else -- the emission path, the ``os.environ`` run-tree
contract, transfer assembly, the ``codex`` subprocess, the ledger, and the activity summary --
is real.

Never skips: fails loudly if ``codex`` is not installed/authenticated (the no-skip policy).
Run via: ``./scripts/test-integration.sh tests/integration/core/test_claude_to_codex_resume.py -v``.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from forge.core.ops.codex_bridge import bridge_session_to_codex
from forge.core.ops.context import ExecutionContext
from forge.core.ops.usage_summary import build_session_activity_summary
from forge.core.runtime.codex_preflight import CodexPreflight, preflight_codex
from forge.core.usage.ledger import read_usage_events
from forge.session.manager import SessionManager
from forge.session.models import create_session_state
from forge.session.store import SessionStore
from forge.session.transfer import _CurationCall

pytestmark = [pytest.mark.integration, pytest.mark.slow]

# Neutral curated context: the E2E proves the plumbing (curate -> codex -> one run tree), not
# that Codex implements anything, so the handoff carries no build instruction that would pull a
# trivial "reply OK" task into real work.
_CURATED = {
    "goal": "Acknowledge prior planning context",
    "decisions": [{"text": "No code changes required for this handoff", "citation": "turn 2"}],
    "current_state": "Planning complete; nothing left to build",
    "files": [],
    "open_questions": [],
}


def _require_codex_ready() -> CodexPreflight:
    pf = preflight_codex()
    if not pf.ready:
        pytest.fail(f"codex not ready ({pf.blocking_reason}). Install + authenticate codex, then re-run.")
    return pf


def _init_git_repo(path: Path) -> None:
    """codex exec refuses to run outside a git repo; a real worktree always is one."""
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "bridge@test.local"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "bridge"], cwd=path, check=True)


def _write_planning_transcript(path: Path) -> None:
    lines = [
        json.dumps(
            {
                "requestId": "r1",
                "timestamp": "2026-01-01T00:00:00Z",
                "message": {"role": "user", "content": [{"type": "text", "text": "Let's plan a tiny adder."}]},
            }
        ),
        json.dumps(
            {
                "requestId": "r1",
                "timestamp": "2026-01-01T00:00:01Z",
                "message": {"role": "assistant", "content": [{"type": "text", "text": "A pure add(a, b)."}]},
            }
        ),
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _register_parent(forge_root: Path, transcript: Path) -> None:
    """Persist a fully-registered parent session 'planner' (index entry + manifest).

    Real persistence, no SessionManager mock: ``get_session`` resolves the index entry first,
    then the on-disk manifest, so the bridge exercises both.
    """
    mgr = SessionManager()
    mgr.index_store.add_session(
        name="planner",
        worktree_path=str(forge_root),
        project_root=str(forge_root),
        forge_root=str(forge_root),
    )
    state = create_session_state(name="planner", worktree_path=str(forge_root))
    state.confirmed.transcript_path = str(transcript)
    SessionStore(str(forge_root), "planner").write(state)


def test_plan_in_claude_implement_in_codex_under_one_run_tree(tmp_path: Path) -> None:
    _require_codex_ready()
    _init_git_repo(tmp_path)

    transcript = tmp_path / "planner.transcript.jsonl"
    _write_planning_transcript(transcript)
    _register_parent(tmp_path, transcript)

    ctx = ExecutionContext(cwd=tmp_path, worktree_root=tmp_path, project_root=tmp_path, forge_root=tmp_path)
    canned = _CurationCall(
        curated=_CURATED,
        model_used="anthropic/claude-haiku-4.5 via openrouter",
        usage={"prompt_tokens": 350, "completion_tokens": 80},
        latency_ms=12.0,
    )

    with patch("forge.session.transfer._call_llm_for_curation", return_value=canned):
        result = bridge_session_to_codex(
            ctx=ctx,
            parent="planner",
            task="Reply with the single word OK. No file changes are needed.",
            cwd=str(tmp_path),
            strategy="ai-curated",
            timeout_seconds=180,
        )

    # The real codex run consumed the curated-transfer prompt and completed.
    assert (
        result.codex.success
    ), f"rc={result.codex.returncode} error={result.codex.error} stderr={result.codex.stderr!r}"
    assert result.curation_ran is True
    assert result.child.startswith("planner-codex-")

    # Both planes attribute under one run tree, same session.
    events = read_usage_events(root_run_id=result.root_run_id)
    routes = {e.route for e in events}
    assert {"core_llm", "codex_exec"} <= routes, events
    assert {e.session for e in events} == {"planner"}
    curation = next(e for e in events if e.route == "core_llm")
    assert curation.command == "transfer-curate"
    assert curation.runtime == "forge_cli"

    # The user-visible rollup shows both sides of the hop.
    summary = build_session_activity_summary("planner", str(tmp_path))
    commands = {c.command for c in summary.commands}
    assert {"transfer-curate", "codex-bridge"} <= commands, commands
