"""Real-codex end-to-end for ``forge session start --runtime codex`` (Phase 2).

Drives the full ``start_codex_session`` op against a **real** ``codex exec`` run: session
creation, curated transfer keyed by the real session name, the first Codex turn, thread_id
capture from the live JSONL stream, rollout discovery in the real ``$CODEX_HOME``, and the
manifest facts the CLI later renders. This is the standing guard for the probe-61 claim that
the rollout filename ends with the stream's thread_id.

Only the curation network call (``_call_llm_for_curation``) is mocked, for the same reason as
``test_claude_to_codex_resume.py``: ``ai-curated`` silently falls back to ``structured``
without OpenRouter auth, which would unprove the two-event run-tree join. The test then
continues the session live (``codex exec resume`` with the prompt on **stdin** -- the
invoker's delivery path, which probe stage 60 never combined with ``resume``): a seed token
planted in turn 1 must be recalled in turn 2, proving stdin-prompt + resume + thread
identity in one 2-turn flow (probe stage 61's claims, kept verified here).

Never skips: fails loudly if ``codex`` is not installed/authenticated (the no-skip policy).
Run via: ``./scripts/test-integration.sh tests/integration/core/test_codex_session_start.py -v``.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from forge.core.ops.codex_session import continue_codex_session, start_codex_session
from forge.core.ops.context import ExecutionContext
from forge.core.ops.usage_summary import build_session_activity_summary
from forge.core.runtime.codex_preflight import CodexPreflight, preflight_codex
from forge.core.usage.ledger import read_usage_events
from forge.session.manager import SessionManager
from forge.session.models import create_session_state
from forge.session.store import SessionStore
from forge.session.transfer import _CurationCall

pytestmark = [pytest.mark.integration, pytest.mark.slow]

# Neutral curated context: the E2E proves the lifecycle plumbing, not that Codex builds
# anything -- the handoff carries no instruction that would pull the trivial task into work.
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
    """Persist a fully-registered parent session 'planner' (index entry + manifest)."""
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


def test_start_then_resume_codex_session_real_turns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pf = _require_codex_ready()
    _init_git_repo(tmp_path)
    (tmp_path / ".forge").mkdir()  # Rule 1: sessions require an enabled Forge project

    transcript = tmp_path / "planner.transcript.jsonl"
    _write_planning_transcript(transcript)
    _register_parent(tmp_path, transcript)
    monkeypatch.chdir(tmp_path)

    ctx = ExecutionContext(cwd=tmp_path, worktree_root=tmp_path, project_root=tmp_path, forge_root=tmp_path)
    canned = _CurationCall(
        curated=_CURATED,
        model_used="anthropic/claude-haiku-4.5 via openrouter",
        usage={"prompt_tokens": 350, "completion_tokens": 80},
        latency_ms=12.0,
    )

    with patch("forge.session.transfer._call_llm_for_curation", return_value=canned):
        result = start_codex_session(
            ctx=ctx,
            parent="planner",
            name="impl",
            task=(
                "Remember the word PERSIMMON for later in this conversation. "
                "Reply with the single word OK. No file changes are needed."
            ),
            sandbox="read-only",
            timeout_seconds=180,
        )

    # The real codex run consumed the curated-transfer prompt and completed.
    assert (
        result.codex.success
    ), f"rc={result.codex.returncode} error={result.codex.error} stderr={result.codex.stderr!r}"
    assert result.curation_ran is True
    assert result.thread_id, "live stream emitted no thread.started id"

    # Standing probe-61 guard: the real rollout file is keyed by the stream's thread_id.
    assert result.rollout_path is not None, "no rollout found in $CODEX_HOME for the live thread_id"
    assert result.rollout_path.endswith(f"-{result.thread_id}.jsonl"), result.rollout_path

    # Manifest facts (what `forge session show` renders and resume dispatches on).
    state = SessionManager().get_session("impl", forge_root=str(tmp_path))
    assert state.intent.launch is not None
    assert state.intent.launch.runtime == "codex"
    assert state.parent_session == "planner"
    assert state.confirmed.claude_session_id is None  # Claude-resume predicates must refuse
    assert state.confirmed.launch is None  # ANTHROPIC-key posture would misread for codex
    assert state.confirmed.codex is not None
    assert state.confirmed.codex.thread_id == result.thread_id
    assert state.confirmed.codex.rollout_path == result.rollout_path
    assert state.confirmed.codex.rollout_source == "discovered_by_thread_id"
    assert state.confirmed.codex.auth_method == pf.auth_method
    assert state.confirmed.derivation is not None
    assert state.confirmed.derivation.parent_session == "planner"
    assert state.confirmed.derivation.context_file == ".forge/prev_sessions/planner/children/impl.md"

    # The snapshot is keyed by the real session name -- no synthetic per-run children.
    children = tmp_path / ".forge" / "prev_sessions" / "planner" / "children"
    assert (children / "impl.md").is_file()
    assert not [p for p in children.iterdir() if "-codex-" in p.name]

    # Both planes attribute under one run tree, to the NEW session.
    events = read_usage_events(root_run_id=result.root_run_id)
    routes = {e.route for e in events}
    assert {"core_llm", "codex_exec"} <= routes, events
    assert {e.session for e in events} == {"impl"}

    # The user-visible rollup shows both sides of the hop.
    summary = build_session_activity_summary("impl", str(tmp_path))
    commands = {c.command for c in summary.commands}
    assert {"transfer-curate", "codex-bridge"} <= commands, commands

    # --- Continuation (probe 61b live): stdin prompt + `exec resume` recalls turn 1. ---
    resume = continue_codex_session(
        ctx=ctx,
        name="impl",
        task="What word did I ask you to remember earlier? Reply with only that word.",
        sandbox="read-only",
        timeout_seconds=180,
    )

    assert resume.codex.success, f"rc={resume.codex.returncode} error={resume.codex.error}"
    assert "PERSIMMON" in resume.codex.stdout.upper(), resume.codex.stdout
    # Probe 60b pinned thread-id stability across resume; drift would warn + re-record.
    assert resume.thread_id == result.thread_id
    assert resume.warnings == ()

    refreshed = SessionManager().get_session("impl", forge_root=str(tmp_path))
    assert refreshed.confirmed.codex is not None
    assert refreshed.confirmed.codex.thread_id == result.thread_id
    assert state.confirmed.codex.last_run_at is not None
    assert refreshed.confirmed.codex.last_run_at is not None
    assert refreshed.confirmed.codex.last_run_at >= state.confirmed.codex.last_run_at

    # The resume turn opens its own run tree, attributed to the same session.
    resume_events = read_usage_events(root_run_id=resume.root_run_id)
    assert {e.route for e in resume_events} == {"codex_exec"}, resume_events
    assert {e.session for e in resume_events} == {"impl"}
    assert {e.command for e in resume_events} == {"codex-resume"}
