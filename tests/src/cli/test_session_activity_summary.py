"""Tests for the session-end activity summary wired into the launcher.

Covers the best-effort summary helper (`_print_session_activity_summary`) and the
shared post-exit renderer (`_post_exit_render`) used by host + sidecar + fork.
"""

from __future__ import annotations

import io
from pathlib import Path

from rich.console import Console

from forge.cli import session_lifecycle as sl
from forge.core.usage.ledger import UsageEvent, log_usage_event
from forge.session.models import PolicyConfirmed, create_session_state
from forge.session.store import SessionStore


def _capture(monkeypatch) -> io.StringIO:
    buf = io.StringIO()
    monkeypatch.setattr(sl, "console", Console(file=buf, width=200, force_terminal=False))
    return buf


def _supervisor_event(session: str, status: str = "success") -> UsageEvent:
    return UsageEvent(
        run_id="r",
        root_run_id="r",
        runtime="claude_code",
        command="supervisor",
        status=status,
        session=session,
    )


def _warn_decision() -> dict:
    return {
        "final_decision": "warn",
        "warnings": ["Possible divergence: parse failed (0%)"],
        "evaluated_at": "2026-06-03T12:00:00Z",
        "decisions": [
            {"decision": "warn", "policy_id": "semantic.supervisor", "warnings": [], "cached": False},
        ],
    }


def _persist(tmp_path: Path, name: str, *, decisions: list[dict] | None = None):
    state = create_session_state(name, worktree_path=str(tmp_path))
    state.forge_root = str(tmp_path)
    if decisions is not None:
        state.confirmed.policy = PolicyConfirmed(decisions=decisions)
    SessionStore(str(tmp_path), name).write(state)
    return state


def test_summary_prints_when_data(monkeypatch, tmp_path: Path) -> None:
    buf = _capture(monkeypatch)
    state = _persist(tmp_path, "planner", decisions=[_warn_decision()])
    log_usage_event(_supervisor_event("planner", status="error"))

    sl._print_session_activity_summary(state, since=None)

    out = buf.getvalue()
    assert "Forge this session" in out
    assert "supervisor" in out


def test_summary_silent_when_empty(monkeypatch, tmp_path: Path) -> None:
    buf = _capture(monkeypatch)
    state = _persist(tmp_path, "quiet", decisions=[])
    sl._print_session_activity_summary(state, since=None)
    assert buf.getvalue() == ""


def test_summary_skips_incognito(monkeypatch, tmp_path: Path) -> None:
    buf = _capture(monkeypatch)
    state = _persist(tmp_path, "secret", decisions=[_warn_decision()])
    state.is_incognito = True
    log_usage_event(_supervisor_event("secret"))
    sl._print_session_activity_summary(state, since=None)
    assert buf.getvalue() == ""


def test_summary_skips_without_forge_root(monkeypatch, tmp_path: Path) -> None:
    buf = _capture(monkeypatch)
    state = create_session_state("planner", worktree_path=str(tmp_path))
    state.forge_root = None
    sl._print_session_activity_summary(state, since=None)
    assert buf.getvalue() == ""


def test_summary_never_raises(monkeypatch, tmp_path: Path) -> None:
    _capture(monkeypatch)
    state = _persist(tmp_path, "planner", decisions=[_warn_decision()])

    def _boom(*_a, **_k):
        raise RuntimeError("ledger exploded")

    monkeypatch.setattr("forge.core.ops.usage_summary.build_session_activity_summary", _boom)
    # Must not propagate — telemetry is best-effort.
    sl._print_session_activity_summary(state, since=None)


def test_post_exit_render_returns_exit_code(monkeypatch, tmp_path: Path) -> None:
    buf = _capture(monkeypatch)
    state = _persist(tmp_path, "planner", decisions=[_warn_decision()])
    log_usage_event(_supervisor_event("planner"))

    code = sl._post_exit_render(state, store_exists=True, exit_code=3, since=None)
    assert code == 3
    out = buf.getvalue()
    assert "Forge this session" in out
    assert "Reconnect to this conversation with:" in out


def test_post_exit_render_deleted_session_note(monkeypatch, tmp_path: Path) -> None:
    buf = _capture(monkeypatch)
    state = create_session_state("planner", worktree_path=str(tmp_path))
    state.forge_root = str(tmp_path)
    code = sl._post_exit_render(state, store_exists=False, exit_code=0, since=None)
    assert code == 0
    assert "was deleted during this run" in buf.getvalue()
