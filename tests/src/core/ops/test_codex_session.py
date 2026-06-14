"""Tests for the Codex-runtime session ops (codex_frontend Phase 2).

Hermetic: the curation LLM, ``codex exec`` subprocess, and preflight are mocked; the
SessionManager/IndexStore/SessionStore stack is REAL (these ops exist to write manifest
state, so the assertions read actual manifests back). ``isolate_forge_home`` gives each
test a clean index + usage ledger. The real-codex stack is covered in
``tests/integration/core/test_codex_session_start.py``.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from forge.core.ops.codex_session import (
    CodexSessionResumeResult,
    CodexSessionStartResult,
    continue_codex_session,
    start_codex_session,
)
from forge.core.ops.context import ExecutionContext
from forge.core.ops.session import ForgeOpError
from forge.core.runtime.codex_preflight import CodexPreflight, HookSeam
from forge.core.usage.ledger import read_usage_events
from forge.session import IndexStore, SessionManager, SessionNotFoundError, SessionStore
from forge.session.codex_handoff import (
    consume_pending_context,
    pending_context_path,
    receipt_path,
    stage_pending_context,
    write_observation_receipt,
)
from forge.session.models import CodexConfirmed, create_session_state

_FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "codex"
_SUCCESS_STREAM = (_FIXTURES / "exec_json_success.jsonl").read_text()
_ERROR_STREAM = (_FIXTURES / "exec_json_error.jsonl").read_text()
_SUCCESS_TID = "019eaa51-6920-7c41-ae34-d4f7f368d55a"
_ERROR_TID = "019eaa51-f236-7bc2-be86-6903c9339b46"

_CURATED = {
    "goal": "Ship the bridge CLI",
    "decisions": [{"text": "Flag shape on session start", "citation": "turn 1"}],
    "current_state": "Ops landing",
    "files": ["src/forge/core/ops/codex_session.py"],
    "open_questions": [],
}


def _preflight() -> CodexPreflight:
    return CodexPreflight(
        installed=True,
        version="0.138.0",
        version_ok=True,
        auth_method="chatgpt_tokens",
        auth_source="codex_store",
        billing_mode="subscription_quota",
        ready=True,
        blocking_reason=None,
        hook_seam="enrollment_gated",
        proxy_responses="native_direct",
        doctor_status="ok",
    )


def _mock_codex_proc(stdout: str = _SUCCESS_STREAM, returncode: int = 0) -> MagicMock:
    proc = MagicMock()
    proc.communicate.return_value = (stdout, "")
    proc.returncode = returncode
    proc.poll.return_value = returncode
    proc.pid = 4242
    proc.wait.return_value = returncode
    return proc


def _fake_completion(text: str) -> Any:
    return SimpleNamespace(text=text, usage={"prompt_tokens": 200, "completion_tokens": 40})


def _write_transcript(path: Path) -> None:
    lines = [
        json.dumps(
            {
                "requestId": "r1",
                "timestamp": "2026-01-01T00:00:00Z",
                "message": {"role": "user", "content": [{"type": "text", "text": "Plan the bridge CLI."}]},
            }
        ),
        json.dumps(
            {
                "requestId": "r1",
                "timestamp": "2026-01-01T00:00:01Z",
                "message": {"role": "assistant", "content": [{"type": "text", "text": "Flag shape on start."}]},
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


def _seed_parent(proj: Path) -> None:
    """Persist a real 'planner' parent (manifest + transcript + index entry)."""
    transcript = proj / "transcript.jsonl"
    _write_transcript(transcript)
    state = create_session_state(name="planner", worktree_path=str(proj))
    state.confirmed.transcript_path = str(transcript)
    SessionStore(str(proj), "planner").write(state)
    _index_session("planner", proj, proj)


def _make_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, ExecutionContext]:
    proj = tmp_path / "project"
    (proj / ".forge").mkdir(parents=True)
    (proj / ".claude").mkdir()
    _seed_parent(proj)
    monkeypatch.chdir(proj)
    ctx = ExecutionContext(cwd=proj, worktree_root=proj, project_root=proj, forge_root=proj)
    return proj, ctx


class _CodexCapture:
    """Handle on the routed Popen mock: codex argv/cwd/stdin assertions."""

    def __init__(self, popen_mock: MagicMock, proc: MagicMock) -> None:
        self.popen_mock = popen_mock
        self.proc = proc

    @property
    def call(self) -> Any:
        return next(c for c in self.popen_mock.call_args_list if c.args and c.args[0] and c.args[0][0] == "codex")

    @property
    def argv(self) -> list[str]:
        return list(self.call.args[0])

    @property
    def stdin(self) -> str:
        return str(self.proc.communicate.call_args.kwargs["input"])


@contextmanager
def _codex_mocks(
    stdout: str = _SUCCESS_STREAM,
    returncode: int = 0,
    on_codex_spawn: Callable[[], None] | None = None,
) -> Generator[_CodexCapture]:
    """Standard hermetic mocks: preflight, curation LLM, codex subprocess.

    The Popen patch is GLOBAL (``_lifecycle.subprocess`` is the shared module), and
    the real SessionManager shells out to git during start_session -- so the mock
    routes by argv: ``codex`` gets the fixture replay, everything else gets the real
    Popen. ``on_codex_spawn`` runs when the codex turn starts -- hook-delivery tests
    use it to play the enrolled SessionStart hook (consume the staged handoff).
    """
    import subprocess as _subprocess

    real_popen = _subprocess.Popen
    codex_proc = _mock_codex_proc(stdout, returncode)

    def _route(argv: Any, *args: Any, **kwargs: Any) -> Any:
        if argv and argv[0] == "codex":
            if on_codex_spawn is not None:
                on_codex_spawn()
            return codex_proc
        return real_popen(argv, *args, **kwargs)

    mock_adapter = MagicMock()
    mock_adapter.complete.return_value = _fake_completion(json.dumps(_CURATED))
    with (
        patch("forge.core.ops.codex_session.assert_codex_ready", return_value=_preflight()),
        patch("forge.core.llm.SyncAdapter", return_value=mock_adapter),
        patch("forge.core.llm.get_client"),
        patch("forge.core.invoker._lifecycle.subprocess.Popen", side_effect=_route) as mock_popen,
    ):
        yield _CodexCapture(mock_popen, codex_proc)


class TestStartCodexSession:
    def test_happy_path_writes_manifest_facts(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        proj, ctx = _make_project(tmp_path, monkeypatch)

        with _codex_mocks():
            result = start_codex_session(ctx=ctx, name="impl", parent="planner", task="Build it")

        assert isinstance(result, CodexSessionStartResult)
        assert result.codex.success and result.codex.stdout == "OK"
        assert result.thread_id == _SUCCESS_TID

        state = SessionManager().get_session("impl", forge_root=str(proj))
        assert state.intent.launch is not None
        assert state.intent.launch.runtime == "codex"
        assert state.parent_session == "planner"
        assert state.confirmed.claude_session_id is None  # Claude-resume predicates must refuse
        assert state.confirmed.launch is None  # ANTHROPIC-key posture would misread for codex
        assert state.confirmed.codex is not None
        assert state.confirmed.codex.thread_id == _SUCCESS_TID
        assert state.confirmed.codex.auth_method == "chatgpt_tokens"
        assert state.confirmed.codex.auth_source == "codex_store"
        assert state.confirmed.codex.billing_mode == "subscription_quota"
        assert state.confirmed.derivation is not None
        assert state.confirmed.derivation.parent_session == "planner"
        assert state.confirmed.derivation.resume_mode == "transfer"
        assert state.confirmed.derivation.strategy == "ai-curated"
        assert state.confirmed.derivation.context_file == ".forge/prev_sessions/planner/children/impl.md"

        # The snapshot is the real session name -- no synthetic -codex- child.
        children = proj / ".forge" / "prev_sessions" / "planner" / "children"
        assert (children / "impl.md").is_file()
        assert not [p for p in children.iterdir() if "-codex-" in p.name]

    def test_run_tree_attributed_to_new_session(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _, ctx = _make_project(tmp_path, monkeypatch)
        with _codex_mocks():
            result = start_codex_session(ctx=ctx, name="impl", parent="planner", task="Build it")

        events = read_usage_events(root_run_id=result.root_run_id)
        assert {e.route for e in events} == {"core_llm", "codex_exec"}
        assert {e.session for e in events} == {"impl"}

    def test_unknown_strategy_rejected_before_creation(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        proj, ctx = _make_project(tmp_path, monkeypatch)
        with pytest.raises(ForgeOpError, match="Unknown strategy"):
            start_codex_session(ctx=ctx, name="impl", parent="planner", task="t", strategy="bogus")
        assert not SessionStore(str(proj), "impl").exists()

    def test_missing_parent_rejected_before_creation(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        proj, ctx = _make_project(tmp_path, monkeypatch)
        with pytest.raises(ForgeOpError, match="not found"):
            start_codex_session(ctx=ctx, name="impl", parent="ghost", task="t")
        assert not SessionStore(str(proj), "impl").exists()

    def test_preflight_failure_creates_no_session(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from dataclasses import replace

        from forge.core.runtime.codex_preflight import CodexPreflightError

        proj, ctx = _make_project(tmp_path, monkeypatch)
        not_ready = replace(_preflight(), ready=False, installed=False, blocking_reason="codex CLI not found")
        with patch(
            "forge.core.ops.codex_session.assert_codex_ready",
            side_effect=CodexPreflightError(not_ready),
        ):
            with pytest.raises(ForgeOpError, match="not ready"):
                start_codex_session(ctx=ctx, name="impl", parent="planner", task="t")
        assert not SessionStore(str(proj), "impl").exists()

    def test_failed_codex_turn_keeps_session(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        proj, ctx = _make_project(tmp_path, monkeypatch)
        with _codex_mocks(stdout=_ERROR_STREAM, returncode=1):
            result = start_codex_session(ctx=ctx, name="impl", parent="planner", task="Build it")

        assert result.codex.success is False
        state = SessionManager().get_session("impl", forge_root=str(proj))
        # The failed turn still opened a thread (recorded fixture) -- resumable.
        assert state.confirmed.codex is not None
        assert state.confirmed.codex.thread_id == _ERROR_TID

    def test_stale_snapshot_and_notes_replaced(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        proj, ctx = _make_project(tmp_path, monkeypatch)
        children = proj / ".forge" / "prev_sessions" / "planner" / "children"
        children.mkdir(parents=True)
        (children / "impl.md").write_text("STALE SNAPSHOT FROM A ROLLED-BACK RUN")
        (children / "impl.notes.md").write_text("## User Notes\n\nstale user note\n")

        with _codex_mocks():
            result = start_codex_session(ctx=ctx, name="impl", parent="planner", task="Build it")

        assert "STALE SNAPSHOT" not in (children / "impl.md").read_text()
        assert not (children / "impl.notes.md").exists()
        assert any("stale transfer snapshot" in w for w in result.warnings)

    def test_referenced_snapshot_collision_rolls_back(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        proj, ctx = _make_project(tmp_path, monkeypatch)
        snapshot = proj / ".forge" / "prev_sessions" / "planner" / "children" / "impl.md"
        snapshot.parent.mkdir(parents=True)
        snapshot.write_text("REFERENCED BY ANOTHER SESSION")

        # A session in a DIFFERENT forge_root references this exact snapshot absolutely.
        other_root = tmp_path / "other"
        (other_root / ".forge").mkdir(parents=True)
        other = create_session_state(name="other", worktree_path=str(other_root))
        from forge.session.models import Derivation

        other.confirmed.derivation = Derivation(parent_session="planner", context_file=str(snapshot))
        SessionStore(str(other_root), "other").write(other)
        _index_session("other", other_root, other_root)

        with _codex_mocks():
            with pytest.raises(ForgeOpError, match="referenced by another"):
                start_codex_session(ctx=ctx, name="impl", parent="planner", task="t")

        # Created session rolled back; the foreign snapshot untouched.
        assert not SessionStore(str(proj), "impl").exists()
        assert snapshot.read_text() == "REFERENCED BY ANOTHER SESSION"

    def test_rollout_discovered_and_recorded(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        proj, ctx = _make_project(tmp_path, monkeypatch)
        codex_home = tmp_path / "codex-home"
        day = codex_home / "sessions" / "2026" / "06" / "10"
        day.mkdir(parents=True)
        rollout = day / f"rollout-2026-06-10T12-00-00-{_SUCCESS_TID}.jsonl"
        rollout.write_text('{"type":"session_meta"}\n')
        monkeypatch.setenv("CODEX_HOME", str(codex_home))

        with _codex_mocks():
            result = start_codex_session(ctx=ctx, name="impl", parent="planner", task="Build it")

        assert result.rollout_path == str(rollout)
        state = SessionManager().get_session("impl", forge_root=str(proj))
        assert state.confirmed.codex is not None
        assert state.confirmed.codex.rollout_path == str(rollout)
        assert state.confirmed.codex.rollout_source == "discovered_by_thread_id"

    def test_no_rollout_recorded_honestly_absent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        proj, ctx = _make_project(tmp_path, monkeypatch)
        monkeypatch.setenv("CODEX_HOME", str(tmp_path / "empty-codex-home"))

        with _codex_mocks():
            result = start_codex_session(ctx=ctx, name="impl", parent="planner", task="Build it")

        assert result.rollout_path is None
        state = SessionManager().get_session("impl", forge_root=str(proj))
        assert state.confirmed.codex is not None
        assert state.confirmed.codex.rollout_path is None
        assert state.confirmed.codex.rollout_source is None


# The success stream minus thread.started: the recovery path's fixture.
_NO_THREAD_STREAM = "\n".join(_SUCCESS_STREAM.splitlines()[1:])


def _session_dir(proj: Path, name: str = "impl") -> Path:
    return SessionStore(str(proj), name).session_dir


class TestStartCodexHookDelivery:
    """--context-delivery hook: staging, receipt reconciliation, and the seam guard."""

    def _enrolled_hook(
        self,
        proj: Path,
        *,
        session_id: str = _SUCCESS_TID,
        transcript_path: str | None = None,
    ) -> Callable[[], None]:
        """Play the trust-enrolled codex-session-start hook at codex-spawn time."""

        def _consume() -> None:
            content = consume_pending_context(
                _session_dir(proj),
                session_id=session_id,
                transcript_path=transcript_path,
                source="startup",
            )
            assert content is not None and content.startswith("# Handoff context")

        return _consume

    def test_delivered_records_fact_and_receipt_rollout(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        proj, ctx = _make_project(tmp_path, monkeypatch)
        rollout = f"/codex-home/sessions/rollout-x-{_SUCCESS_TID}.jsonl"

        with _codex_mocks(on_codex_spawn=self._enrolled_hook(proj, transcript_path=rollout)) as codex:
            result = start_codex_session(
                ctx=ctx, name="impl", parent="planner", task="Build it", context_delivery="hook"
            )

        assert result.context_delivery == "session_start_hook"
        assert result.rollout_path == rollout
        assert result.thread_id == _SUCCESS_TID
        # The prompt carried ONLY the raw task -- the hook delivered the context.
        assert codex.stdin == "Build it"

        state = SessionManager().get_session("impl", forge_root=str(proj))
        assert state.confirmed.codex is not None
        assert state.confirmed.codex.context_delivery == "session_start_hook"
        assert state.confirmed.codex.rollout_path == rollout
        assert state.confirmed.codex.rollout_source == "session_start_hook"
        # One-shot: nothing staged survives the start turn.
        assert not pending_context_path(_session_dir(proj)).exists()

    def test_not_fired_keeps_session_and_records_undelivered(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        proj, ctx = _make_project(tmp_path, monkeypatch)

        with _codex_mocks() as codex:  # no hook plays: the staged file is never consumed
            result = start_codex_session(
                ctx=ctx, name="impl", parent="planner", task="Build it", context_delivery="hook"
            )

        assert result.context_delivery == "hook_undelivered"
        assert codex.stdin == "Build it"  # the turn ran context-less
        state = SessionManager().get_session("impl", forge_root=str(proj))
        assert state.confirmed.codex is not None
        assert state.confirmed.codex.context_delivery == "hook_undelivered"
        # One-shot invariant: reconciliation cleared the undelivered staging.
        assert not pending_context_path(_session_dir(proj)).exists()
        assert not receipt_path(_session_dir(proj)).exists()

    def test_observation_receipt_never_read_as_delivery(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Phase 4 contract regression (introduced by Phase 5): the observation receipt
        is a separate file; delivery reconciliation must never read it as a delivery
        receipt -- an observation WITHOUT a delivery receipt still reconciles
        hook_undelivered, and no observation field leaks into the manifest."""
        proj, ctx = _make_project(tmp_path, monkeypatch)

        def _observe_only() -> None:
            write_observation_receipt(
                _session_dir(proj),
                session_id=_SUCCESS_TID,
                transcript_path=f"/codex-home/sessions/rollout-x-{_SUCCESS_TID}.jsonl",
                source="startup",
            )

        with _codex_mocks(on_codex_spawn=_observe_only):
            result = start_codex_session(
                ctx=ctx, name="impl", parent="planner", task="Build it", context_delivery="hook"
            )

        assert result.context_delivery == "hook_undelivered"
        state = SessionManager().get_session("impl", forge_root=str(proj))
        assert state.confirmed.codex is not None
        assert state.confirmed.codex.context_delivery == "hook_undelivered"
        assert state.confirmed.codex.rollout_source != "session_start_hook"

    def test_mismatched_receipt_is_undelivered_with_warning(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        proj, ctx = _make_project(tmp_path, monkeypatch)

        with _codex_mocks(on_codex_spawn=self._enrolled_hook(proj, session_id="not-this-thread")):
            result = start_codex_session(
                ctx=ctx, name="impl", parent="planner", task="Build it", context_delivery="hook"
            )

        assert result.context_delivery == "hook_undelivered"
        assert any("does not match" in w for w in result.warnings)
        state = SessionManager().get_session("impl", forge_root=str(proj))
        assert state.confirmed.codex is not None
        assert state.confirmed.codex.context_delivery == "hook_undelivered"

    def test_thread_id_recovered_from_receipt_when_stream_missed_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The stream missed thread.started but the hook receipt carries the thread:
        the session must stay resumable (manifest thread_id recovered)."""
        proj, ctx = _make_project(tmp_path, monkeypatch)
        rollout = f"/codex-home/sessions/rollout-x-{_SUCCESS_TID}.jsonl"

        with _codex_mocks(
            stdout=_NO_THREAD_STREAM,
            on_codex_spawn=self._enrolled_hook(proj, transcript_path=rollout),
        ):
            result = start_codex_session(
                ctx=ctx, name="impl", parent="planner", task="Build it", context_delivery="hook"
            )

        assert result.thread_id == _SUCCESS_TID
        assert result.context_delivery == "session_start_hook"
        assert any("recovered" in w for w in result.warnings)
        assert not any("cannot be resumed" in w for w in result.warnings)
        state = SessionManager().get_session("impl", forge_root=str(proj))
        assert state.confirmed.codex is not None
        assert state.confirmed.codex.thread_id == _SUCCESS_TID
        assert state.confirmed.codex.rollout_path == rollout

    @pytest.mark.parametrize("seam", ["disabled", "unknown", "managed_suppressed", "untrusted"])
    def test_pre_turn_guard_rejects_hook_incapable_seams(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, seam: HookSeam
    ) -> None:
        from dataclasses import replace

        proj, ctx = _make_project(tmp_path, monkeypatch)
        incapable = replace(_preflight(), hook_seam=seam)

        with patch("forge.core.ops.codex_session.assert_codex_ready", return_value=incapable):
            with pytest.raises(ForgeOpError, match="hook-capable"):
                start_codex_session(ctx=ctx, name="impl", parent="planner", task="t", context_delivery="hook")

        assert not SessionStore(str(proj), "impl").exists()

    def test_default_mode_records_initial_message_and_stages_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        proj, ctx = _make_project(tmp_path, monkeypatch)

        with _codex_mocks() as codex:
            result = start_codex_session(ctx=ctx, name="impl", parent="planner", task="Build it")

        assert result.context_delivery == "initial_message"
        assert codex.stdin.startswith("# Handoff context")  # transfer rode the prompt
        state = SessionManager().get_session("impl", forge_root=str(proj))
        assert state.confirmed.codex is not None
        assert state.confirmed.codex.context_delivery == "initial_message"
        assert not pending_context_path(_session_dir(proj)).exists()
        assert not receipt_path(_session_dir(proj)).exists()


def _init_git_repo(repo: Path) -> None:
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "README.md").write_text("# test\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)


class TestStartCodexSessionGC:
    """Checklist row 4: the start op leaves no transfer orphans, owns its snapshot
    under the child's indexed forge_root, and rolls back cleanly for retry."""

    def test_start_leaves_zero_transfer_orphans(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from forge.core.ops.gc import collect_clean_report

        _, ctx = _make_project(tmp_path, monkeypatch)
        with _codex_mocks():
            start_codex_session(ctx=ctx, name="impl", parent="planner", task="Build it")

        report = collect_clean_report(ctx=ctx, scope="project")
        transfer = next(c for c in report.categories if c.category == "transfer_files")
        assert transfer.count == 0
        assert transfer.items == []

    def test_rollback_then_retry_assembles_fresh_snapshot(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        proj, ctx = _make_project(tmp_path, monkeypatch)
        children = proj / ".forge" / "prev_sessions" / "planner" / "children"

        with _codex_mocks():
            with patch(
                "forge.core.ops.codex_session.find_rollout_path",
                side_effect=RuntimeError("rollout scan failed"),
            ):
                with pytest.raises(RuntimeError, match="rollout scan failed"):
                    start_codex_session(ctx=ctx, name="impl", parent="planner", task="Build it")

            # Post-guard failure rolls back the session AND this run's snapshot.
            assert not SessionStore(str(proj), "impl").exists()
            assert not (children / "impl.md").exists()
            assert not (children / "impl.notes.md").exists()

            result = start_codex_session(ctx=ctx, name="impl", parent="planner", task="Build it")

        assert result.codex.success
        assert not any("stale" in w.lower() for w in result.warnings)
        assert (children / "impl.md").is_file()
        state = SessionManager().get_session("impl", forge_root=str(proj))
        assert state.confirmed.derivation is not None

    def test_worktree_snapshot_owned_by_child_forge_root(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from forge.core.ops.gc import _detect_orphan_transfer_files

        # Nested Forge project (forge_root != repo root): the manager remaps the
        # child's forge_root into the new worktree, so the op must thread
        # output_root or GC would resolve context_file under a root with no file.
        repo = tmp_path / "repo"
        proj = repo / "sub"
        (proj / ".forge").mkdir(parents=True)
        (proj / ".claude").mkdir()
        _init_git_repo(repo)
        _seed_parent(proj)
        monkeypatch.chdir(proj)
        ctx = ExecutionContext(cwd=proj, worktree_root=repo, project_root=repo, forge_root=proj)

        with _codex_mocks():
            result = start_codex_session(ctx=ctx, name="impl", parent="planner", task="Build it", create_worktree=True)

        assert result.codex.success
        entry = SessionManager().get_session_entry("impl", forge_root=None)
        assert entry.forge_root is not None
        child_fr = Path(entry.forge_root)
        assert child_fr != proj  # nested project: remapped into the new worktree

        snapshot = child_fr / ".forge" / "prev_sessions" / "planner" / "children" / "impl.md"
        assert snapshot.is_file()
        state = SessionManager().get_session("impl", forge_root=str(child_fr))
        assert state.confirmed.derivation is not None
        assert state.confirmed.derivation.context_file == ".forge/prev_sessions/planner/children/impl.md"

        # GC resolves the relative context_file under child_fr -> nothing flagged.
        ref_set = {("planner", str(proj)), ("impl", str(child_fr))}
        gc_result = _detect_orphan_transfer_files(ref_set, {proj, child_fr})
        assert gc_result.count == 0


def _seed_duplicate_project(tmp_path: Path, name: str = "impl") -> Path:
    """Index a same-named Claude session in a DIFFERENT project (no derivation)."""
    other_root = tmp_path / "other"
    (other_root / ".forge").mkdir(parents=True)
    other = create_session_state(name=name, worktree_path=str(other_root))
    SessionStore(str(other_root), name).write(other)
    _index_session(name, other_root, other_root)
    return other_root


class TestCrossProjectNameScoping:
    """Review finding (2026-06-10): session names are project-scoped, so every
    post-creation lookup/delete must be scoped to the child's forge_root -- an
    unscoped strict resolution raises AmbiguousSessionError when another project
    already has the name, stranding the just-created session."""

    def test_duplicate_name_in_other_project_does_not_break_start(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        proj, ctx = _make_project(tmp_path, monkeypatch)
        other_root = _seed_duplicate_project(tmp_path)

        with _codex_mocks():
            result = start_codex_session(ctx=ctx, name="impl", parent="planner", task="Build it")

        assert result.thread_id == _SUCCESS_TID
        state = SessionManager().get_session("impl", forge_root=str(proj))
        assert state.intent.launch is not None
        assert state.intent.launch.runtime == "codex"
        # The other project's same-named Claude session is untouched.
        other_state = SessionManager().get_session("impl", forge_root=str(other_root))
        assert other_state.intent.launch is not None
        assert other_state.intent.launch.runtime == "claude_code"

    def test_rollback_with_duplicate_name_deletes_only_this_project(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        proj, ctx = _make_project(tmp_path, monkeypatch)
        other_root = _seed_duplicate_project(tmp_path)

        with _codex_mocks():
            with patch(
                "forge.core.ops.codex_session.find_rollout_path",
                side_effect=RuntimeError("rollout scan failed"),
            ):
                with pytest.raises(RuntimeError, match="rollout scan failed"):
                    start_codex_session(ctx=ctx, name="impl", parent="planner", task="Build it")

        # OUR session rolled back (manifest + index entry gone)...
        assert not SessionStore(str(proj), "impl").exists()
        with pytest.raises(SessionNotFoundError):
            SessionManager().get_session_entry("impl", forge_root=str(proj))
        # ...while the other project's session survives untouched.
        assert SessionStore(str(other_root), "impl").exists()
        SessionManager().get_session_entry("impl", forge_root=str(other_root))


def _seed_codex_session(proj: Path, name: str = "impl", thread_id: str | None = _SUCCESS_TID) -> None:
    state = create_session_state(name=name, worktree_path=str(proj), runtime="codex", parent_session="planner")
    if thread_id is not None:
        state.confirmed.codex = CodexConfirmed(thread_id=thread_id)
    SessionStore(str(proj), name).write(state)
    _index_session(name, proj, proj, parent="planner")


class TestContinueCodexSession:
    def test_resume_builds_resume_argv_in_session_worktree(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        proj, _ = _make_project(tmp_path, monkeypatch)
        _seed_codex_session(proj)
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        invocation_ctx = ExecutionContext(
            cwd=elsewhere, worktree_root=elsewhere, project_root=elsewhere, forge_root=proj
        )

        with _codex_mocks() as codex:
            result = continue_codex_session(ctx=invocation_ctx, name="impl", task="Keep going")

        assert isinstance(result, CodexSessionResumeResult)
        assert codex.argv[-2:] == ["resume", _SUCCESS_TID]
        # Cross-CWD: the turn runs in the session's recorded worktree, not the invocation cwd.
        assert codex.call.kwargs["cwd"] == str(proj)
        assert codex.stdin == "Keep going"

    def test_resume_falls_back_to_global_lookup_from_other_forge_project(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        proj, _ = _make_project(tmp_path, monkeypatch)
        _seed_codex_session(proj)
        other_project = tmp_path / "other-project"
        (other_project / ".git").mkdir(parents=True)
        (other_project / ".forge").mkdir()
        invocation_ctx = ExecutionContext(
            cwd=other_project,
            worktree_root=other_project,
            project_root=other_project,
            forge_root=other_project,
        )

        with _codex_mocks() as codex:
            result = continue_codex_session(ctx=invocation_ctx, name="impl", task="Keep going")

        assert isinstance(result, CodexSessionResumeResult)
        assert codex.argv[-2:] == ["resume", _SUCCESS_TID]
        assert codex.call.kwargs["cwd"] == str(proj)

    def test_resume_refreshes_confirmed_codex(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        proj, ctx = _make_project(tmp_path, monkeypatch)
        _seed_codex_session(proj)

        with _codex_mocks():
            continue_codex_session(ctx=ctx, name="impl", task="Keep going")

        state = SessionManager().get_session("impl", forge_root=str(proj))
        assert state.confirmed.codex is not None
        assert state.confirmed.codex.last_run_at is not None
        assert state.confirmed.codex.thread_id == _SUCCESS_TID

    def test_resume_refreshes_auth_posture(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Review finding (2026-06-10): `session show` renders Auth from confirmed.codex,
        so a resume under a different Codex auth must refresh the recorded posture
        (CodexConfirmed is refreshed per run), not keep the first turn's."""
        from dataclasses import replace

        proj, ctx = _make_project(tmp_path, monkeypatch)
        state = create_session_state(name="impl", worktree_path=str(proj), runtime="codex", parent_session="planner")
        state.confirmed.codex = CodexConfirmed(
            thread_id=_SUCCESS_TID,
            auth_method="chatgpt_tokens",
            auth_source="codex_store",
            billing_mode="subscription_quota",
        )
        SessionStore(str(proj), "impl").write(state)
        _index_session("impl", proj, proj, parent="planner")

        changed = replace(_preflight(), auth_method="api_key", auth_source="env", billing_mode="api")
        with _codex_mocks():
            with patch("forge.core.ops.codex_session.assert_codex_ready", return_value=changed):
                continue_codex_session(ctx=ctx, name="impl", task="Keep going")

        refreshed = SessionManager().get_session("impl", forge_root=str(proj)).confirmed.codex
        assert refreshed is not None
        assert refreshed.auth_method == "api_key"
        assert refreshed.auth_source == "env"
        assert refreshed.billing_mode == "api"

    def test_resume_clears_stale_staged_handoff(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """One-shot defensively: a staged handoff that survived the start turn (crash
        window) must be cleared BEFORE the resume turn, never late-delivered."""
        proj, ctx = _make_project(tmp_path, monkeypatch)
        _seed_codex_session(proj)
        stage_pending_context(_session_dir(proj), "# Handoff context\n\nstale\n")

        with _codex_mocks():
            result = continue_codex_session(ctx=ctx, name="impl", task="Keep going")

        assert not pending_context_path(_session_dir(proj)).exists()
        assert any("stale staged handoff" in w for w in result.warnings)

    def test_claude_session_rejected(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _, ctx = _make_project(tmp_path, monkeypatch)
        # "planner" is a Claude-runtime session.
        with pytest.raises(ForgeOpError, match="not a Codex session"):
            continue_codex_session(ctx=ctx, name="planner", task="t")

    def test_missing_thread_id_rejected_with_guidance(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        proj, ctx = _make_project(tmp_path, monkeypatch)
        _seed_codex_session(proj, thread_id=None)
        with pytest.raises(ForgeOpError, match="no recorded Codex thread_id"):
            continue_codex_session(ctx=ctx, name="impl", task="t")

    def test_thread_id_drift_recorded_with_warning(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        proj, ctx = _make_project(tmp_path, monkeypatch)
        _seed_codex_session(proj, thread_id="00000000-old-thread-id")

        with _codex_mocks():  # stream announces _SUCCESS_TID
            result = continue_codex_session(ctx=ctx, name="impl", task="t")

        assert result.thread_id == _SUCCESS_TID
        assert any("drifted" in w for w in result.warnings)
        state = SessionManager().get_session("impl", forge_root=str(proj))
        assert state.confirmed.codex is not None
        assert state.confirmed.codex.thread_id == _SUCCESS_TID
