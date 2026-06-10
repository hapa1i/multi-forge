"""Tests for the Codex CLI wiring (codex_frontend Phase 2).

Covers ``forge session start --runtime codex`` / ``forge session resume --task``
dispatch and flag-matrix validation, the ``_launch_claude_for_session`` runtime
backstop, the ``session_codex`` rendering layer, and ``session show`` for Codex
manifests. The ops themselves are covered in
``tests/src/core/ops/test_codex_session.py``; here the ops are mocked and the
assertions target Click plumbing (what reaches the op, what exits with which code).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.cli.session_codex import launch_codex_session, resume_codex_session
from forge.core.invoker.types import HeadlessResult
from forge.core.ops.codex_session import CodexSessionResumeResult, CodexSessionStartResult
from forge.core.ops.session import ForgeOpError
from forge.session import IndexStore, SessionStore
from forge.session.models import CodexConfirmed, create_session_state

_TID = "019eaa51-6920-7c41-ae34-d4f7f368d55a"

_CODEX_BASE = ["session", "start", "impl", "--runtime", "codex", "--resume-from", "planner", "--task", "Build it"]


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Minimal project cwd (.git + .forge) with a wide console for stable asserts."""
    monkeypatch.setenv("COLUMNS", "500")
    proj = tmp_path / "project"
    (proj / ".git").mkdir(parents=True)
    (proj / ".forge").mkdir()
    monkeypatch.chdir(proj)
    return proj


def _headless(returncode: int = 0, stdout: str = "OK", stderr: str = "") -> HeadlessResult:
    return HeadlessResult(label="codex", stdout=stdout, stderr=stderr, returncode=returncode, duration_seconds=0.1)


def _start_result(**overrides: object) -> CodexSessionStartResult:
    base: dict = {
        "session": "impl",
        "parent": "planner",
        "transfer_path": Path("/proj/.forge/prev_sessions/planner/children/impl.md"),
        "root_run_id": "run-1",
        "codex": _headless(),
        "curation_ran": True,
        "thread_id": _TID,
        "rollout_path": None,
        "worktree_path": None,
    }
    base.update(overrides)
    return CodexSessionStartResult(**base)


class TestStartFlagMatrix:
    """Validation happens before any session/op machinery -- no mocks needed."""

    def test_codex_requires_resume_from(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["session", "start", "impl", "--runtime", "codex", "--task", "t"])
        assert result.exit_code == 1
        assert "--runtime codex requires --resume-from" in result.output

    def test_codex_requires_task(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["session", "start", "impl", "--runtime", "codex", "--resume-from", "planner"])
        assert result.exit_code == 1
        assert "--runtime codex requires --task" in result.output

    @pytest.mark.parametrize(
        ("extra_args", "flag_label"),
        [
            (["--proxy", "p"], "--proxy"),
            (["--no-proxy"], "--no-proxy"),
            (["--sidecar"], "--sidecar"),
            (["--host-proxy"], "--host-proxy"),
            (["--subprocess-proxy", "p"], "--subprocess-proxy"),
            (["--system-prompt", "x"], "--system-prompt"),
            (["--incognito"], "--incognito"),
            (["--model", "claude-opus-4-8"], "--model"),
            (["--no-launch"], "--no-launch"),
            (["--extensions"], "--extensions/--no-extensions"),
            (["--supervise", "watcher"], "--supervise"),
            (["--supervisor-proxy", "p"], "--supervisor-proxy"),
            (["--no-supervisor-proxy"], "--no-supervisor-proxy"),
            (["--memory", "on"], "--memory"),
            (["--mount", "/a:/b"], "--mount"),
            (["--image", "img"], "--image"),
        ],
    )
    def test_claude_flags_rejected_with_codex(
        self, runner: CliRunner, extra_args: list[str], flag_label: str
    ) -> None:
        result = runner.invoke(main, _CODEX_BASE + extra_args)
        assert result.exit_code == 1
        assert f"{flag_label} is not supported with --runtime codex" in result.output

    def test_branch_requires_worktree(self, runner: CliRunner) -> None:
        result = runner.invoke(main, _CODEX_BASE + ["--branch", "feature"])
        assert result.exit_code == 1
        assert "--branch requires --worktree" in result.output

    @pytest.mark.parametrize(
        ("extra_args", "flag_label"),
        [
            (["--resume-from", "planner"], "--resume-from"),
            (["--task", "t"], "--task"),
            (["--strategy", "full"], "--strategy"),
            (["--depth", "2"], "--depth"),
            (["--sandbox", "read-only"], "--sandbox"),
        ],
    )
    def test_codex_only_flags_require_codex_runtime(
        self, runner: CliRunner, extra_args: list[str], flag_label: str
    ) -> None:
        result = runner.invoke(main, ["session", "start", "impl"] + extra_args)
        assert result.exit_code == 1
        assert f"{flag_label} requires --runtime codex" in result.output


class TestStartCodexDispatch:
    def test_defaults_reach_launcher(self, runner: CliRunner, project: Path) -> None:
        with (
            patch("forge.cli.guards.require_repo_root"),
            patch("forge.cli.session_codex.launch_codex_session", return_value=0) as launch,
        ):
            result = runner.invoke(main, _CODEX_BASE)

        assert result.exit_code == 0
        launch.assert_called_once_with(
            name="impl",
            parent="planner",
            task="Build it",
            strategy="ai-curated",
            depth=1,
            sandbox="workspace-write",
            worktree=False,
            branch=None,
        )

    def test_explicit_options_pass_through(self, runner: CliRunner, project: Path) -> None:
        with (
            patch("forge.cli.guards.require_main_repo_root") as main_guard,
            patch("forge.cli.guards.require_repo_root") as plain_guard,
            patch("forge.cli.session_codex.launch_codex_session", return_value=0) as launch,
        ):
            result = runner.invoke(
                main,
                _CODEX_BASE
                + ["--worktree", "--branch", "feat", "--strategy", "full", "--depth", "2", "--sandbox", "read-only"],
            )

        assert result.exit_code == 0
        main_guard.assert_called_once()
        plain_guard.assert_not_called()
        kwargs = launch.call_args.kwargs
        assert kwargs["strategy"] == "full"
        assert kwargs["depth"] == 2
        assert kwargs["sandbox"] == "read-only"
        assert kwargs["worktree"] is True
        assert kwargs["branch"] == "feat"

    def test_exit_code_propagates(self, runner: CliRunner, project: Path) -> None:
        with (
            patch("forge.cli.guards.require_repo_root"),
            patch("forge.cli.session_codex.launch_codex_session", return_value=3),
        ):
            result = runner.invoke(main, _CODEX_BASE)
        assert result.exit_code == 3

    def test_auto_name_generated_when_omitted(self, runner: CliRunner, project: Path) -> None:
        argv = ["session", "start", "--runtime", "codex", "--resume-from", "planner", "--task", "t"]
        with (
            patch("forge.cli.guards.require_repo_root"),
            patch("forge.cli.session_codex.launch_codex_session", return_value=0) as launch,
        ):
            result = runner.invoke(main, argv)

        assert result.exit_code == 0
        generated = launch.call_args.kwargs["name"]
        assert isinstance(generated, str) and generated


class TestResumeCodexDispatch:
    def _codex_state(self, tmp_path: Path) -> object:
        return create_session_state("impl", worktree_path=str(tmp_path), runtime="codex")

    def test_dispatch_with_task(self, runner: CliRunner, tmp_path: Path) -> None:
        with (
            patch("forge.cli.session.SessionManager") as mgr_cls,
            patch("forge.cli.session_codex.resume_codex_session", return_value=0) as resume,
        ):
            mgr_cls.return_value.get_session.return_value = self._codex_state(tmp_path)
            result = runner.invoke(main, ["session", "resume", "impl", "--task", "next step"])

        assert result.exit_code == 0
        resume.assert_called_once_with(name="impl", task="next step", sandbox="workspace-write")

    def test_exit_code_propagates(self, runner: CliRunner, tmp_path: Path) -> None:
        with (
            patch("forge.cli.session.SessionManager") as mgr_cls,
            patch("forge.cli.session_codex.resume_codex_session", return_value=2),
        ):
            mgr_cls.return_value.get_session.return_value = self._codex_state(tmp_path)
            result = runner.invoke(main, ["session", "resume", "impl", "--task", "t"])
        assert result.exit_code == 2

    def test_requires_task(self, runner: CliRunner, tmp_path: Path) -> None:
        with patch("forge.cli.session.SessionManager") as mgr_cls:
            mgr_cls.return_value.get_session.return_value = self._codex_state(tmp_path)
            result = runner.invoke(main, ["session", "resume", "impl"])

        assert result.exit_code == 1
        assert "resuming a Codex session requires --task" in result.output

    @pytest.mark.parametrize(
        ("extra_args", "flag_label"),
        [
            (["--fresh"], "--fresh"),
            (["--force"], "--force"),
        ],
    )
    def test_claude_only_flags_rejected(
        self, runner: CliRunner, tmp_path: Path, extra_args: list[str], flag_label: str
    ) -> None:
        with patch("forge.cli.session.SessionManager") as mgr_cls:
            mgr_cls.return_value.get_session.return_value = self._codex_state(tmp_path)
            result = runner.invoke(main, ["session", "resume", "impl", "--task", "t"] + extra_args)

        assert result.exit_code == 1
        assert f"{flag_label} is not supported for Codex sessions" in result.output

    def test_task_rejected_for_claude_sessions(self, runner: CliRunner, tmp_path: Path) -> None:
        claude_state = create_session_state("cl", worktree_path=str(tmp_path))
        with patch("forge.cli.session.SessionManager") as mgr_cls:
            mgr_cls.return_value.get_session.return_value = claude_state
            result = runner.invoke(main, ["session", "resume", "cl", "--task", "t"])

        assert result.exit_code == 1
        assert "--task is only supported for Codex sessions" in result.output


class TestLaunchClaudeBackstop:
    def test_codex_manifest_refused(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        from forge.cli.session_lifecycle import _launch_claude_for_session

        state = create_session_state("impl", worktree_path=str(tmp_path), runtime="codex")
        code = _launch_claude_for_session(
            manifest=state,
            session_id=None,
            resume_id=None,
            effective_template=None,
            runtime_base_url=None,
            context_limit=200_000,
            use_sidecar=False,
        )

        assert code == 1
        assert "runtime 'codex'" in capsys.readouterr().out


class TestCodexCliRendering:
    """Direct calls into session_codex with the ops mocked; Rich prints to stdout."""

    def test_start_success_renders_summary_and_tip(self, capsys: pytest.CaptureFixture[str]) -> None:
        result = _start_result(warnings=("no rollout file found",))
        with patch("forge.cli.session_codex.start_codex_session", return_value=result):
            code = launch_codex_session(
                name="impl",
                parent="planner",
                task="t",
                strategy="ai-curated",
                depth=1,
                sandbox="workspace-write",
                worktree=False,
                branch=None,
            )

        assert code == 0
        out = capsys.readouterr().out
        assert "Created Codex session" in out
        assert "impl" in out and "planner" in out
        assert "direct (OpenAI via codex CLI)" in out
        assert _TID in out
        assert "Warning:" in out and "no rollout file found" in out
        assert "Tip:" in out and "forge session resume impl --task" in out

    def test_start_op_error_exits_one(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("forge.cli.session_codex.start_codex_session", side_effect=ForgeOpError("parent not found")):
            code = launch_codex_session(
                name="impl",
                parent="ghost",
                task="t",
                strategy="ai-curated",
                depth=1,
                sandbox="workspace-write",
                worktree=False,
                branch=None,
            )

        assert code == 1
        out = capsys.readouterr().out
        assert "Error:" in out and "parent not found" in out

    def test_start_failed_turn_returns_codex_exit_code(self, capsys: pytest.CaptureFixture[str]) -> None:
        result = _start_result(codex=_headless(returncode=2, stdout="", stderr="boom"), thread_id=None)
        with patch("forge.cli.session_codex.start_codex_session", return_value=result):
            code = launch_codex_session(
                name="impl",
                parent="planner",
                task="t",
                strategy="ai-curated",
                depth=1,
                sandbox="workspace-write",
                worktree=False,
                branch=None,
            )

        assert code == 2
        out = capsys.readouterr().out
        assert "Codex turn failed." in out and "boom" in out
        assert "Tip:" not in out  # no resume tip without a usable thread

    def test_resume_success_render(self, capsys: pytest.CaptureFixture[str]) -> None:
        result = CodexSessionResumeResult(
            session="impl", thread_id=_TID, root_run_id="run-2", codex=_headless(stdout="Done"), rollout_path=None
        )
        with patch("forge.cli.session_codex.continue_codex_session", return_value=result):
            code = resume_codex_session(name="impl", task="t", sandbox="workspace-write")

        assert code == 0
        out = capsys.readouterr().out
        assert "Resumed Codex session" in out and _TID in out and "Done" in out

    def test_resume_op_error_exits_one(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch(
            "forge.cli.session_codex.continue_codex_session",
            side_effect=ForgeOpError("session 'impl' has no recorded Codex thread"),
        ):
            code = resume_codex_session(name="impl", task="t", sandbox="workspace-write")

        assert code == 1
        out = capsys.readouterr().out
        assert "Error:" in out and "no recorded Codex thread" in out


class TestShowCodexSession:
    def _seed(self, proj: Path) -> None:
        state = create_session_state("impl", worktree_path=str(proj), runtime="codex")
        state.confirmed.codex = CodexConfirmed(
            thread_id=_TID,
            rollout_path=f"/codex/sessions/2026/06/10/rollout-x-{_TID}.jsonl",
            rollout_source="discovered_by_thread_id",
            auth_method="chatgpt_tokens",
            auth_source="codex_store",
            billing_mode="subscription_quota",
            last_run_at="2026-06-10T00:00:00Z",
        )
        SessionStore(str(proj), "impl").write(state)
        IndexStore().add_session(
            name="impl",
            worktree_path=str(proj),
            project_root=str(proj),
            forge_root=str(proj),
            checkout_root=str(proj),
            relative_path=".",
            is_incognito=False,
            is_fork=False,
            parent_session="planner",
        )

    def test_show_json_includes_runtime_and_codex(self, runner: CliRunner, project: Path) -> None:
        self._seed(project)
        result = runner.invoke(main, ["session", "show", "impl", "--json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["intent"]["runtime"] == "codex"
        assert data["confirmed"]["codex"]["thread_id"] == _TID
        assert data["confirmed"]["codex"]["auth_method"] == "chatgpt_tokens"

    def test_show_human_renders_runtime_and_thread(self, runner: CliRunner, project: Path) -> None:
        self._seed(project)
        result = runner.invoke(main, ["session", "show", "impl"])

        assert result.exit_code == 0
        assert "Runtime:" in result.output and "codex" in result.output
        assert "direct (OpenAI via codex CLI)" in result.output
        assert "Thread:" in result.output and _TID in result.output
        assert "chatgpt_tokens (codex_store)" in result.output

    def test_show_human_suppresses_claude_vestiges(self, runner: CliRunner, project: Path) -> None:
        """The display-only intent.agent ("claude-code") and the Claude-computed
        Model Family ("anthropic") would misread on a Codex session."""
        self._seed(project)
        result = runner.invoke(main, ["session", "show", "impl"])

        assert result.exit_code == 0
        assert "Agent:" not in result.output
        assert "Model Family" not in result.output
        assert "Computed Context" not in result.output
