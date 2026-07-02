"""Tests for interactive Codex session ops (codex_frontend Phase 5).

The TUI is an injected ``invoke`` callable (no Popen routing needed); the curation
LLM and preflight are mocked like ``test_codex_session.py``. Thread identity is
reconciled post-exit, so most cases stage receipts / rollout files via the fake
``$CODEX_HOME`` and assert what landed in ``confirmed.codex``.
"""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Generator
from unittest.mock import MagicMock, patch

import pytest

from forge.core.ops.codex_interactive import (
    ROLLOUT_SOURCE_POST_EXIT,
    CodexInteractiveResult,
    _remove_lock_only_session_dir,
    _update_manifest_if_present,
    reattach_codex_session,
    start_interactive_codex_session,
)
from forge.core.ops.context import ExecutionContext
from forge.core.ops.session import ForgeOpError
from forge.core.runtime.codex_preflight import CodexPreflight
from forge.core.usage.ledger import read_usage_events
from forge.session import SessionManager, SessionStore
from forge.session.active import ActiveSessionStore
from forge.session.codex_handoff import (
    consume_pending_context,
    pending_context_path,
    stage_pending_context,
    write_observation_receipt,
)
from forge.session.index import IndexStore
from forge.session.models import CodexConfirmed, create_session_state

_TID = "019eaa51-6920-7c41-ae34-d4f7f368d55a"
_TID_B = "11111111-2222-3333-4444-555555555555"

_CURATED = {
    "goal": "Ship the interactive frontend",
    "decisions": [{"text": "Bare means interactive", "citation": "turn 1"}],
    "current_state": "Ops landing",
    "files": ["src/forge/core/ops/codex_interactive.py"],
    "open_questions": [],
}


def _preflight(*, hook_seam: str = "enrollment_gated") -> CodexPreflight:
    return CodexPreflight(
        installed=True,
        version="0.139.0",
        version_ok=True,
        auth_method="chatgpt_tokens",
        auth_source="codex_store",
        billing_mode="subscription_quota",
        ready=True,
        blocking_reason=None,
        hook_seam=hook_seam,  # type: ignore[arg-type]
        proxy_responses="native_direct",
        doctor_status="ok",
    )


def _fake_completion(text: str) -> Any:
    return SimpleNamespace(text=text, usage={"prompt_tokens": 200, "completion_tokens": 40})


def _write_transcript(path: Path) -> None:
    lines = [
        json.dumps(
            {
                "requestId": "r1",
                "timestamp": "2026-01-01T00:00:00Z",
                "message": {"role": "user", "content": [{"type": "text", "text": "Plan the frontend."}]},
            }
        ),
        json.dumps(
            {
                "requestId": "r1",
                "timestamp": "2026-01-01T00:00:01Z",
                "message": {"role": "assistant", "content": [{"type": "text", "text": "Bare means interactive."}]},
            }
        ),
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _index_session(name: str, forge_root: Path, project_root: Path, parent: str | None = None) -> None:
    IndexStore().add_session(
        name=name,
        worktree_path=str(forge_root),
        project_root=str(project_root),
        forge_root=str(forge_root),
        checkout_root=str(forge_root),
        relative_path=".",
        is_incognito=False,
        is_fork=False,
        parent_session=parent,
    )


def _make_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, ExecutionContext]:
    proj = tmp_path / "project"
    (proj / ".forge").mkdir(parents=True)
    (proj / ".claude").mkdir()
    transcript = proj / "transcript.jsonl"
    _write_transcript(transcript)
    state = create_session_state(name="planner", worktree_path=str(proj))
    state.confirmed.transcript_path = str(transcript)
    SessionStore(str(proj), "planner").write(state)
    _index_session("planner", proj, proj)
    monkeypatch.chdir(proj)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
    ctx = ExecutionContext(cwd=proj, worktree_root=proj, project_root=proj, forge_root=proj)
    return proj, ctx


def _seed_codex_session(proj: Path, name: str = "impl", thread_id: str | None = _TID) -> None:
    state = create_session_state(name=name, worktree_path=str(proj), runtime="codex", parent_session="planner")
    if thread_id is not None:
        state.confirmed.codex = CodexConfirmed(thread_id=thread_id)
    SessionStore(str(proj), name).write(state)
    _index_session(name, proj, proj, parent="planner")


def _make_rollout(
    home: Path,
    thread_id: str,
    *,
    cwd: str,
    ts: str = "2026-06-11T10-00-00",
    age_seconds: float | None = None,
) -> Path:
    day = home / "sessions" / "2026" / "06" / "11"
    day.mkdir(parents=True, exist_ok=True)
    path = day / f"rollout-{ts}-{thread_id}.jsonl"
    path.write_text(json.dumps({"cwd": cwd}) + "\n")
    if age_seconds is not None:
        old = time.time() - age_seconds
        os.utime(path, (old, old))
    return path


class _FakeInvoke:
    """Injected TUI stand-in: records kwargs, runs a side effect 'during' the run."""

    def __init__(self, returncode: int = 0, side_effect: Callable[..., object] | None = None) -> None:
        self.returncode = returncode
        self.side_effect = side_effect
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> int:
        self.calls.append(kwargs)
        if self.side_effect is not None:
            self.side_effect(**kwargs)
        return self.returncode

    @property
    def kwargs(self) -> dict[str, Any]:
        return self.calls[-1]


@contextmanager
def _interactive_mocks(
    *,
    hook_seam: str = "enrollment_gated",
    on_curation: Callable[[], None] | None = None,
) -> Generator[None]:
    """Hermetic mocks: preflight + the curation LLM (no Popen -- invoke is injected)."""

    def _complete(*args: Any, **kwargs: Any) -> Any:
        if on_curation is not None:
            on_curation()
        return _fake_completion(json.dumps(_CURATED))

    mock_adapter = MagicMock()
    mock_adapter.complete.side_effect = _complete
    with (
        patch(
            "forge.core.ops.codex_interactive.assert_codex_ready",
            return_value=_preflight(hook_seam=hook_seam),
        ),
        patch("forge.core.llm.SyncAdapter", return_value=mock_adapter),
        patch("forge.core.llm.get_client"),
    ):
        yield


def _session_dir(proj: Path, name: str = "impl") -> Path:
    return SessionStore(str(proj), name).session_dir


def _codex_home(tmp_path: Path) -> Path:
    return tmp_path / "codex-home"


class TestBareInteractiveStart:
    def test_records_discovered_thread_and_manifest_facts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        proj, ctx = _make_project(tmp_path, monkeypatch)
        invoke = _FakeInvoke(side_effect=lambda **kw: _make_rollout(_codex_home(tmp_path), _TID, cwd=kw["cwd"]))

        with _interactive_mocks():
            result = start_interactive_codex_session(ctx=ctx, name="solo", invoke=invoke)

        assert isinstance(result, CodexInteractiveResult)
        assert result.exit_code == 0
        assert result.thread_id == _TID
        assert result.rollout_source == ROLLOUT_SOURCE_POST_EXIT
        assert result.context_delivery is None  # bare start: no transfer to deliver
        assert result.curation_ran is None

        assert invoke.kwargs["initial_prompt"] is None
        assert invoke.kwargs["sandbox"] == "workspace-write"
        assert invoke.kwargs["cwd"] == str(proj)
        assert invoke.kwargs["forge_root"] == str(proj)

        state = SessionManager().get_session("solo", forge_root=str(proj))
        assert state.intent.launch is not None and state.intent.launch.runtime == "codex"
        assert state.confirmed.derivation is None  # no parent, no derivation
        assert state.confirmed.launch is None
        assert state.confirmed.claude_session_id is None
        assert state.confirmed.codex is not None
        assert state.confirmed.codex.thread_id == _TID
        assert state.confirmed.codex.rollout_source == ROLLOUT_SOURCE_POST_EXIT
        assert state.confirmed.codex.context_delivery is None
        assert state.confirmed.codex.auth_method == "chatgpt_tokens"

    def test_no_rollout_keeps_session_with_warning(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        proj, ctx = _make_project(tmp_path, monkeypatch)

        with _interactive_mocks():
            result = start_interactive_codex_session(ctx=ctx, name="solo", invoke=_FakeInvoke())

        assert result.thread_id is None
        assert any("cannot be resumed" in w for w in result.warnings)
        state = SessionManager().get_session("solo", forge_root=str(proj))
        assert state.confirmed.codex is not None
        assert state.confirmed.codex.thread_id is None

    def test_lone_stray_rollout_with_different_cwd_not_recorded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        proj, ctx = _make_project(tmp_path, monkeypatch)

        def _stray_rollout(**kw: Any) -> None:
            _make_rollout(_codex_home(tmp_path), _TID_B, cwd=str(tmp_path / "elsewhere"))

        with _interactive_mocks():
            result = start_interactive_codex_session(
                ctx=ctx, name="solo", invoke=_FakeInvoke(side_effect=_stray_rollout)
            )

        assert result.thread_id is None
        assert any("No Codex rollout appeared" in w for w in result.warnings)
        state = SessionManager().get_session("solo", forge_root=str(proj))
        assert state.confirmed.codex is not None
        assert state.confirmed.codex.thread_id is None

    def test_deleted_during_tui_does_not_recreate_session_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        proj, ctx = _make_project(tmp_path, monkeypatch)

        def _delete_during_tui(**kw: Any) -> None:
            _make_rollout(_codex_home(tmp_path), _TID, cwd=kw["cwd"])
            assert SessionStore(str(proj), "solo").delete() is True

        with _interactive_mocks():
            result = start_interactive_codex_session(
                ctx=ctx, name="solo", invoke=_FakeInvoke(side_effect=_delete_during_tui)
            )

        assert result.thread_id == _TID
        assert any("deleted while Codex was running" in w for w in result.warnings)
        store = SessionStore(str(proj), "solo")
        assert not store.exists()
        assert not store.session_dir.exists()

    def test_ambiguous_rollouts_refuse_to_guess(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        proj, ctx = _make_project(tmp_path, monkeypatch)

        def _two_rollouts(**kw: Any) -> None:
            _make_rollout(_codex_home(tmp_path), _TID, cwd=kw["cwd"], ts="2026-06-11T10-00-00")
            _make_rollout(_codex_home(tmp_path), _TID_B, cwd=kw["cwd"], ts="2026-06-11T10-00-01")

        with _interactive_mocks():
            result = start_interactive_codex_session(
                ctx=ctx, name="solo", invoke=_FakeInvoke(side_effect=_two_rollouts)
            )

        assert result.thread_id is None
        assert any("refusing to guess" in w for w in result.warnings)

    def test_sandbox_passthrough_and_exit_code(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _, ctx = _make_project(tmp_path, monkeypatch)
        invoke = _FakeInvoke(returncode=3)

        with _interactive_mocks():
            result = start_interactive_codex_session(ctx=ctx, name="solo", sandbox="read-only", invoke=invoke)

        assert invoke.kwargs["sandbox"] == "read-only"
        assert result.exit_code == 3

    def test_bogus_strategy_ignored_without_parent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # The CLI rejects --strategy without --resume-from; at op level a bare start
        # never validates (or uses) the strategy.
        _, ctx = _make_project(tmp_path, monkeypatch)
        with _interactive_mocks():
            result = start_interactive_codex_session(ctx=ctx, name="solo", strategy="bogus", invoke=_FakeInvoke())
        assert result.session == "solo"


class TestBridgeInteractiveStart:
    def test_initial_message_prompt_holds_and_derivation_mirrors_headless(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        proj, ctx = _make_project(tmp_path, monkeypatch)
        invoke = _FakeInvoke(side_effect=lambda **kw: _make_rollout(_codex_home(tmp_path), _TID, cwd=kw["cwd"]))

        with _interactive_mocks():
            result = start_interactive_codex_session(ctx=ctx, name="impl", parent="planner", invoke=invoke)

        prompt = invoke.kwargs["initial_prompt"]
        assert prompt is not None
        assert prompt.startswith("# Handoff context")
        assert "# Hold for instructions" in prompt
        assert "WAIT for the user's instruction" in prompt
        assert "# Your task" not in prompt  # the human types in the TUI

        assert result.context_delivery == "initial_message"
        assert result.curation_ran is True
        assert (proj / ".forge" / "prev_sessions" / "planner" / "children" / "impl.md").is_file()

        state = SessionManager().get_session("impl", forge_root=str(proj))
        assert state.confirmed.derivation is not None
        assert state.confirmed.derivation.parent_session == "planner"
        assert state.confirmed.derivation.resume_mode == "transfer"
        assert state.confirmed.derivation.strategy == "ai-curated"
        assert state.confirmed.derivation.context_file is not None
        assert state.confirmed.codex is not None
        assert state.confirmed.codex.context_delivery == "initial_message"

    def test_hook_mode_delivered_via_receipt(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        proj, ctx = _make_project(tmp_path, monkeypatch)
        rollout = f"/codex-home/sessions/2026/06/11/rollout-2026-06-11T10-00-00-{_TID}.jsonl"

        def _enrolled_hook(**kw: Any) -> None:
            content = consume_pending_context(
                _session_dir(proj),
                session_id=_TID,
                transcript_path=rollout,
                source="startup",
            )
            assert content is not None and content.startswith("# Handoff context")

        invoke = _FakeInvoke(side_effect=_enrolled_hook)
        with _interactive_mocks():
            result = start_interactive_codex_session(
                ctx=ctx, name="impl", parent="planner", context_delivery="hook", invoke=invoke
            )

        assert invoke.kwargs["initial_prompt"] is None  # context rode the hook, not the prompt
        assert result.context_delivery == "session_start_hook"
        assert result.thread_id == _TID
        assert result.rollout_path == rollout
        assert result.rollout_source == "session_start_hook"
        assert not pending_context_path(_session_dir(proj)).exists()

        state = SessionManager().get_session("impl", forge_root=str(proj))
        assert state.confirmed.codex is not None
        assert state.confirmed.codex.context_delivery == "session_start_hook"

    def test_hook_mode_undelivered_records_and_clears(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        proj, ctx = _make_project(tmp_path, monkeypatch)
        invoke = _FakeInvoke(side_effect=lambda **kw: _make_rollout(_codex_home(tmp_path), _TID, cwd=kw["cwd"]))

        with _interactive_mocks():
            result = start_interactive_codex_session(
                ctx=ctx, name="impl", parent="planner", context_delivery="hook", invoke=invoke
            )

        assert result.context_delivery == "hook_undelivered"
        # The thread is still recoverable by discovery -- delivery and identity are
        # separate facts.
        assert result.thread_id == _TID
        assert result.rollout_source == ROLLOUT_SOURCE_POST_EXIT
        assert not pending_context_path(_session_dir(proj)).exists()  # one-shot cleared
        state = SessionManager().get_session("impl", forge_root=str(proj))
        assert state.confirmed.codex is not None
        assert state.confirmed.codex.context_delivery == "hook_undelivered"

    def test_hook_seam_guard_fails_before_state(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        proj, ctx = _make_project(tmp_path, monkeypatch)
        with _interactive_mocks(hook_seam="disabled"):
            with pytest.raises(ForgeOpError, match="hook-capable"):
                start_interactive_codex_session(
                    ctx=ctx, name="impl", parent="planner", context_delivery="hook", invoke=_FakeInvoke()
                )
        assert not SessionStore(str(proj), "impl").exists()

    def test_observation_receipt_beats_discovery(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        proj, ctx = _make_project(tmp_path, monkeypatch)
        observed_rollout = f"/codex-home/sessions/2026/06/11/rollout-2026-06-11T10-00-00-{_TID}.jsonl"

        def _observe_and_stray_rollout(**kw: Any) -> None:
            write_observation_receipt(
                _session_dir(proj),
                session_id=_TID,
                transcript_path=observed_rollout,
                source="startup",
            )
            _make_rollout(_codex_home(tmp_path), _TID_B, cwd=kw["cwd"])  # a concurrent stranger

        with _interactive_mocks():
            result = start_interactive_codex_session(
                ctx=ctx, name="impl", parent="planner", invoke=_FakeInvoke(side_effect=_observe_and_stray_rollout)
            )

        assert result.thread_id == _TID  # receipt-sourced, not the stray rollout
        assert result.rollout_path == observed_rollout
        assert result.rollout_source == "session_start_hook"

    def test_run_identity_shared_with_curation_event(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """One-run-tree pin: the TUI env triple == the curation event's root."""
        _, ctx = _make_project(tmp_path, monkeypatch)
        invoke = _FakeInvoke()

        with _interactive_mocks():
            result = start_interactive_codex_session(ctx=ctx, name="impl", parent="planner", invoke=invoke)

        curation_events = [e for e in read_usage_events() if e.command == "transfer-curate"]
        assert len(curation_events) == 1
        root = invoke.kwargs["run_identity"]
        assert curation_events[0].root_run_id == root.root_run_id
        assert result.operation_started_at is not None

    def test_two_timestamps_assembly_era_rollout_excluded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A rollout that appeared during assembly (backdated past the discovery skew)
        must not be discovered; the launch-window rollout is, unambiguously. The
        summary window (operation_started_at) still covers the curation event."""
        proj, ctx = _make_project(tmp_path, monkeypatch)

        def _assembly_era_rollout() -> None:
            _make_rollout(_codex_home(tmp_path), _TID_B, cwd=str(proj), age_seconds=10.0)

        invoke = _FakeInvoke(side_effect=lambda **kw: _make_rollout(_codex_home(tmp_path), _TID, cwd=kw["cwd"]))
        with _interactive_mocks(on_curation=_assembly_era_rollout):
            result = start_interactive_codex_session(ctx=ctx, name="impl", parent="planner", invoke=invoke)

        assert result.thread_id == _TID  # exactly one launch-window candidate

        curation_events = [e for e in read_usage_events() if e.command == "transfer-curate"]
        event_ts = datetime.fromisoformat(curation_events[0].ts.replace("Z", "+00:00"))
        # The ledger ts truncates to whole seconds; compare at that granularity.
        assert result.operation_started_at.replace(microsecond=0) <= event_ts

    def test_pre_launch_raise_rolls_back_session_and_snapshot(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        proj, ctx = _make_project(tmp_path, monkeypatch)
        children = proj / ".forge" / "prev_sessions" / "planner" / "children"

        with _interactive_mocks():
            with patch(
                "forge.core.ops.codex_interactive.stage_pending_context",
                side_effect=RuntimeError("staging failed"),
            ):
                with pytest.raises(RuntimeError, match="staging failed"):
                    start_interactive_codex_session(
                        ctx=ctx, name="impl", parent="planner", context_delivery="hook", invoke=_FakeInvoke()
                    )

        assert not SessionStore(str(proj), "impl").exists()
        assert not (children / "impl.md").exists()
        assert not (children / "impl.notes.md").exists()

    def test_invoke_raise_never_rolls_back(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Once the TUI launches, the session is the user's -- even a spawn failure
        must not delete it."""
        proj, ctx = _make_project(tmp_path, monkeypatch)

        def _boom(**kw: Any) -> None:
            raise RuntimeError("spawn failed")

        with _interactive_mocks():
            with pytest.raises(RuntimeError, match="spawn failed"):
                start_interactive_codex_session(
                    ctx=ctx, name="impl", parent="planner", invoke=_FakeInvoke(side_effect=_boom)
                )

        assert SessionStore(str(proj), "impl").exists()

    def test_active_session_tracked_during_run(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _, ctx = _make_project(tmp_path, monkeypatch)
        seen: dict[str, bool] = {}

        def _check_active(**kw: Any) -> None:
            sessions = ActiveSessionStore().read().sessions
            # Keys are make_scoped_key(name, forge_root) = name + sep + root-hash.
            seen["during"] = any(key.startswith("impl") for key in sessions)

        with _interactive_mocks():
            start_interactive_codex_session(
                ctx=ctx, name="impl", parent="planner", invoke=_FakeInvoke(side_effect=_check_active)
            )

        assert seen["during"] is True
        after = ActiveSessionStore().read().sessions
        assert not any(key.startswith("impl") for key in after)

    def test_no_codex_usage_event_for_the_tui_turn(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _, ctx = _make_project(tmp_path, monkeypatch)
        with _interactive_mocks():
            start_interactive_codex_session(ctx=ctx, name="impl", parent="planner", invoke=_FakeInvoke())

        routes = {e.route for e in read_usage_events()}
        assert "codex_exec" not in routes  # the TUI turn is unmetered
        commands = {e.command for e in read_usage_events()}
        assert "transfer-curate" in commands  # the curation event still lands

    @pytest.mark.parametrize("strategy", ["bogus", "rewind"])
    def test_bad_strategy_with_parent_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, strategy: str
    ) -> None:
        proj, ctx = _make_project(tmp_path, monkeypatch)
        with _interactive_mocks():
            with pytest.raises(ForgeOpError, match="Unknown strategy"):
                start_interactive_codex_session(
                    ctx=ctx, name="impl", parent="planner", strategy=strategy, invoke=_FakeInvoke()
                )
        assert not SessionStore(str(proj), "impl").exists()


class TestReattachCodexSession:
    def test_reattach_argv_in_recorded_worktree(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        proj, _ = _make_project(tmp_path, monkeypatch)
        _seed_codex_session(proj)
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        ctx = ExecutionContext(cwd=elsewhere, worktree_root=elsewhere, project_root=elsewhere, forge_root=proj)
        invoke = _FakeInvoke()

        with _interactive_mocks():
            result = reattach_codex_session(ctx=ctx, name="impl", invoke=invoke)

        assert invoke.kwargs["resume_thread_id"] == _TID
        assert invoke.kwargs.get("initial_prompt") is None
        assert invoke.kwargs["cwd"] == str(proj)  # the session's recorded worktree
        assert result.thread_id == _TID
        assert result.context_delivery is None

    def test_refusals_match_headless_resume(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        proj, ctx = _make_project(tmp_path, monkeypatch)
        with _interactive_mocks():
            # The seeded 'planner' parent is a Claude session.
            with pytest.raises(ForgeOpError, match="is not a Codex session"):
                reattach_codex_session(ctx=ctx, name="planner", invoke=_FakeInvoke())

        _seed_codex_session(proj, name="no-thread", thread_id=None)
        with _interactive_mocks():
            with pytest.raises(ForgeOpError, match="no recorded Codex thread_id"):
                reattach_codex_session(ctx=ctx, name="no-thread", invoke=_FakeInvoke())

    def test_thread_drift_recorded_from_observation(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        proj, ctx = _make_project(tmp_path, monkeypatch)
        _seed_codex_session(proj)

        def _observe_drift(**kw: Any) -> None:
            write_observation_receipt(_session_dir(proj), session_id=_TID_B, transcript_path=None, source="resume")

        with _interactive_mocks():
            result = reattach_codex_session(ctx=ctx, name="impl", invoke=_FakeInvoke(side_effect=_observe_drift))

        assert any("drifted" in w for w in result.warnings)
        assert result.thread_id == _TID_B
        state = SessionManager().get_session("impl", forge_root=str(proj))
        assert state.confirmed.codex is not None
        assert state.confirmed.codex.thread_id == _TID_B

    def test_stale_receipts_cleared_before_launch(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        proj, ctx = _make_project(tmp_path, monkeypatch)
        _seed_codex_session(proj)
        stage_pending_context(_session_dir(proj), "stale staged context")
        write_observation_receipt(_session_dir(proj), session_id=_TID_B, transcript_path=None, source="startup")

        with _interactive_mocks():
            result = reattach_codex_session(ctx=ctx, name="impl", invoke=_FakeInvoke())

        assert any("stale staged handoff" in w for w in result.warnings)
        assert not pending_context_path(_session_dir(proj)).exists()
        # The planted (pre-launch) observation was cleared, so no false drift.
        assert not any("drifted" in w for w in result.warnings)
        assert result.thread_id == _TID

    def test_auth_and_rollout_refreshed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        proj, ctx = _make_project(tmp_path, monkeypatch)
        _seed_codex_session(proj)
        rollout = _make_rollout(_codex_home(tmp_path), _TID, cwd=str(proj))

        with _interactive_mocks():
            result = reattach_codex_session(ctx=ctx, name="impl", invoke=_FakeInvoke())

        assert result.rollout_path == str(rollout)
        assert result.rollout_source == "discovered_by_thread_id"
        state = SessionManager().get_session("impl", forge_root=str(proj))
        assert state.confirmed.codex is not None
        assert state.confirmed.codex.rollout_path == str(rollout)
        assert state.confirmed.codex.auth_method == "chatgpt_tokens"
        assert state.confirmed.codex.last_run_at is not None

    def test_deleted_during_reattach_does_not_recreate_session_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        proj, ctx = _make_project(tmp_path, monkeypatch)
        _seed_codex_session(proj)

        def _delete_during_tui(**kw: Any) -> None:
            assert SessionStore(str(proj), "impl").delete() is True

        with _interactive_mocks():
            result = reattach_codex_session(ctx=ctx, name="impl", invoke=_FakeInvoke(side_effect=_delete_during_tui))

        assert result.thread_id == _TID
        assert any("deleted while Codex was running" in w for w in result.warnings)
        store = SessionStore(str(proj), "impl")
        assert not store.exists()
        assert not store.session_dir.exists()


class TestUpdateManifestIfPresent:
    """The exists()->update() race window and the lock-only-shell sweep.

    The ops-level deleted-during-TUI tests land in the exists() preflight branch;
    these pin the narrower race where the delete lands AFTER the preflight, so
    update()'s lock acquisition recreates the session dir before read() raises.
    """

    @staticmethod
    def _exists_true_once() -> Callable[[SessionStore], bool]:
        """exists() reporting True once (delete lands after the preflight), then real."""
        real_exists = SessionStore.exists
        preflight = [True]

        def _exists(self: SessionStore) -> bool:
            if preflight:
                preflight.pop()
                return True
            return real_exists(self)

        return _exists

    def test_race_window_removes_lock_only_dir(self, tmp_path: Path) -> None:
        store = SessionStore(str(tmp_path), "ghost")
        store.session_dir.mkdir(parents=True)
        (store.session_dir / "forge.session.json.lock").touch()
        warnings: list[str] = []

        with patch.object(SessionStore, "exists", self._exists_true_once()):
            updated = _update_manifest_if_present(store, mutate=lambda m: None, warnings=warnings, session="ghost")

        assert updated is False
        assert any("deleted while Codex was running" in w for w in warnings)
        assert not store.session_dir.exists()

    def test_race_window_preserves_non_lock_content(self, tmp_path: Path) -> None:
        store = SessionStore(str(tmp_path), "ghost")
        receipt_dir = store.session_dir / "codex"
        receipt_dir.mkdir(parents=True)
        (receipt_dir / "observation-receipt.json").write_text("{}", encoding="utf-8")
        warnings: list[str] = []

        with patch.object(SessionStore, "exists", self._exists_true_once()):
            updated = _update_manifest_if_present(store, mutate=lambda m: None, warnings=warnings, session="ghost")

        assert updated is False
        assert any("deleted while Codex was running" in w for w in warnings)
        # A dir holding more than the lock is not ours to judge; nothing is removed.
        assert (receipt_dir / "observation-receipt.json").exists()

    def test_sweep_removes_empty_dir_shell(self, tmp_path: Path) -> None:
        # Another actor already unlinked the lock; the bare shell still goes.
        empty = tmp_path / "ghost-session"
        empty.mkdir()
        _remove_lock_only_session_dir(empty)
        assert not empty.exists()

    def test_sweep_missing_dir_is_noop(self, tmp_path: Path) -> None:
        _remove_lock_only_session_dir(tmp_path / "never-existed")
