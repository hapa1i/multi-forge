"""Tests for the Codex CLI wiring (codex_frontend Phases 2 and 5).

Covers ``forge session start --runtime codex`` / ``forge session resume``
dispatch and flag-matrix validation (``--task`` selects the headless turn;
omitting it the interactive TUI), the Claude launcher runtime backstop, the
``session_codex`` rendering layer, and ``session show`` for Codex manifests.
The ops themselves are covered in
``tests/src/core/ops/test_codex_session.py`` and ``test_codex_interactive.py``;
here the ops are mocked and the assertions target Click plumbing (what reaches
the op, what exits with which code).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.cli.session_codex import (
    _render_interactive_launch,
    launch_codex_session,
    launch_interactive_codex_session,
    reattach_interactive_codex_session,
    resume_codex_session,
)
from forge.core.invoker.types import HeadlessResult
from forge.core.ops.codex_interactive import (
    CodexInteractiveLaunch,
    CodexInteractiveResult,
)
from forge.core.ops.codex_session import (
    CodexSessionResumeResult,
    CodexSessionStartResult,
)
from forge.core.ops.session import ForgeOpError
from forge.session import IndexStore, SessionStore
from forge.session.active import ActiveSessionEntry
from forge.session.models import CodexConfirmed, create_session_state

_TID = "019eaa51-6920-7c41-ae34-d4f7f368d55a"

_CODEX_BASE = [
    "session",
    "start",
    "impl",
    "--runtime",
    "codex",
    "--resume-from",
    "planner",
    "--task",
    "Build it",
]


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
    return HeadlessResult(
        label="codex",
        stdout=stdout,
        stderr=stderr,
        returncode=returncode,
        duration_seconds=0.1,
    )


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


def _interactive_result(**overrides: object) -> CodexInteractiveResult:
    base: dict = {
        "session": "impl",
        "forge_root": "/proj",
        "exit_code": 0,
        "thread_id": _TID,
        "rollout_path": f"/codex/sessions/2026/06/11/rollout-x-{_TID}.jsonl",
        "rollout_source": "discovered_post_exit",
        "context_delivery": None,
        "curation_ran": None,
        "operation_started_at": datetime.now(timezone.utc),
        "warnings": (),
    }
    base.update(overrides)
    return CodexInteractiveResult(**base)


class TestStartFlagMatrix:
    """Validation happens before any session/op machinery -- no mocks needed."""

    def test_task_requires_resume_from(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["session", "start", "impl", "--runtime", "codex", "--task", "t"])
        assert result.exit_code == 1
        assert "--task requires --resume-from" in result.output
        assert "omit --task for an interactive session" in result.output

    @pytest.mark.parametrize(
        ("extra_args", "flag_label"),
        [
            (["--strategy", "full"], "--strategy"),
            (["--depth", "2"], "--depth"),
            (["--context-delivery", "hook"], "--context-delivery"),
        ],
    )
    def test_transfer_flags_require_parent(self, runner: CliRunner, extra_args: list[str], flag_label: str) -> None:
        """Bare interactive start: the transfer-shaping flags have no transfer to shape."""
        result = runner.invoke(main, ["session", "start", "impl", "--runtime", "codex"] + extra_args)
        assert result.exit_code == 1
        assert f"{flag_label} requires --resume-from <parent>" in result.output

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
            (["--cascade"], "--cascade"),
            (["--checker-model", "openai/gpt-5"], "--checker-model"),
            (["--checker-provider", "openrouter"], "--checker-provider"),
            (["--checker-effort", "low"], "--checker-effort"),
            (["--supervisor-effort", "medium"], "--supervisor-effort"),
            (["--memory", "on"], "--memory"),
            (["--mount", "/a:/b"], "--mount"),
            (["--image", "img"], "--image"),
        ],
    )
    def test_claude_flags_rejected_with_codex(self, runner: CliRunner, extra_args: list[str], flag_label: str) -> None:
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
            (["--context-delivery", "hook"], "--context-delivery"),
        ],
    )
    def test_codex_only_flags_require_codex_runtime(
        self, runner: CliRunner, extra_args: list[str], flag_label: str
    ) -> None:
        result = runner.invoke(main, ["session", "start", "impl"] + extra_args)
        assert result.exit_code == 1
        assert f"{flag_label} requires --runtime codex" in result.output

    def test_plain_claude_start_not_rejected_by_codex_defaults(self, runner: CliRunner, project: Path) -> None:
        """Regression: every codex-only Click option must default to None -- a real
        default (e.g. --context-delivery "initial-message") would trip
        reject_codex_flags_for_claude on every plain Claude `session start`."""
        with (
            patch("forge.cli.guards.require_repo_root"),
            patch("forge.cli.session_lifecycle.launch_new_session", return_value=0) as launch,
        ):
            result = runner.invoke(main, ["session", "start", "impl"])

        assert "requires --runtime codex" not in result.output
        assert result.exit_code == 0
        launch.assert_called_once()

    def test_start_help_describes_codex_sandbox_as_tui_mode(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["session", "start", "--help"])

        assert result.exit_code == 0
        assert "Codex sandbox mode for the launched TUI" in result.output
        assert "requires --runtime codex" in result.output


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
            context_delivery="initial-message",
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
                + [
                    "--worktree",
                    "--branch",
                    "feat",
                    "--strategy",
                    "full",
                    "--depth",
                    "2",
                    "--sandbox",
                    "read-only",
                    "--context-delivery",
                    "hook",
                ],
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
        assert kwargs["context_delivery"] == "hook"

    def test_exit_code_propagates(self, runner: CliRunner, project: Path) -> None:
        with (
            patch("forge.cli.guards.require_repo_root"),
            patch("forge.cli.session_codex.launch_codex_session", return_value=3),
        ):
            result = runner.invoke(main, _CODEX_BASE)
        assert result.exit_code == 3

    def test_auto_name_generated_when_omitted(self, runner: CliRunner, project: Path) -> None:
        argv = [
            "session",
            "start",
            "--runtime",
            "codex",
            "--resume-from",
            "planner",
            "--task",
            "t",
        ]
        with (
            patch("forge.cli.guards.require_repo_root"),
            patch("forge.cli.session_codex.launch_codex_session", return_value=0) as launch,
        ):
            result = runner.invoke(main, argv)

        assert result.exit_code == 0
        generated = launch.call_args.kwargs["name"]
        assert isinstance(generated, str) and generated


class TestStartInteractiveDispatch:
    """Bare and --resume-from-only starts route to the interactive launcher (Phase 5)."""

    def test_bare_start_dispatches_interactive(self, runner: CliRunner, project: Path) -> None:
        with (
            patch("forge.cli.guards.require_repo_root"),
            patch(
                "forge.cli.session_codex.launch_interactive_codex_session",
                return_value=0,
            ) as launch,
        ):
            result = runner.invoke(main, ["session", "start", "impl", "--runtime", "codex"])

        assert result.exit_code == 0
        launch.assert_called_once_with(
            name="impl",
            parent=None,
            strategy="ai-curated",
            depth=1,
            sandbox="workspace-write",
            worktree=False,
            branch=None,
            context_delivery="initial-message",
        )

    def test_bridge_without_task_dispatches_interactive(self, runner: CliRunner, project: Path) -> None:
        with (
            patch("forge.cli.guards.require_repo_root"),
            patch(
                "forge.cli.session_codex.launch_interactive_codex_session",
                return_value=0,
            ) as launch,
        ):
            result = runner.invoke(
                main,
                [
                    "session",
                    "start",
                    "impl",
                    "--runtime",
                    "codex",
                    "--resume-from",
                    "planner",
                ]
                + ["--strategy", "full", "--depth", "2", "--context-delivery", "hook"],
            )

        assert result.exit_code == 0
        kwargs = launch.call_args.kwargs
        assert kwargs["parent"] == "planner"
        assert kwargs["strategy"] == "full"
        assert kwargs["depth"] == 2
        assert kwargs["context_delivery"] == "hook"

    def test_bare_sandbox_passes_through(self, runner: CliRunner, project: Path) -> None:
        """--sandbox shapes the TUI itself, not the transfer -- valid without a parent."""
        with (
            patch("forge.cli.guards.require_repo_root"),
            patch(
                "forge.cli.session_codex.launch_interactive_codex_session",
                return_value=0,
            ) as launch,
        ):
            result = runner.invoke(
                main,
                [
                    "session",
                    "start",
                    "impl",
                    "--runtime",
                    "codex",
                    "--sandbox",
                    "read-only",
                ],
            )

        assert result.exit_code == 0
        assert launch.call_args.kwargs["sandbox"] == "read-only"

    def test_interactive_exit_code_propagates(self, runner: CliRunner, project: Path) -> None:
        with (
            patch("forge.cli.guards.require_repo_root"),
            patch(
                "forge.cli.session_codex.launch_interactive_codex_session",
                return_value=3,
            ),
        ):
            result = runner.invoke(main, ["session", "start", "impl", "--runtime", "codex"])
        assert result.exit_code == 3

    def test_task_still_dispatches_headless(self, runner: CliRunner, project: Path) -> None:
        """--task keeps the Phase 2 headless path; the interactive launcher is untouched."""
        with (
            patch("forge.cli.guards.require_repo_root"),
            patch("forge.cli.session_codex.launch_codex_session", return_value=0) as headless,
            patch(
                "forge.cli.session_codex.launch_interactive_codex_session",
                return_value=0,
            ) as interactive,
        ):
            result = runner.invoke(main, _CODEX_BASE)

        assert result.exit_code == 0
        headless.assert_called_once()
        interactive.assert_not_called()


class TestResumeCodexDispatch:
    def _codex_state(self, tmp_path: Path) -> object:
        return create_session_state("impl", worktree_path=str(tmp_path), runtime="codex")

    def test_dispatch_with_task(self, runner: CliRunner, tmp_path: Path) -> None:
        with (
            patch("forge.cli.session_lifecycle.SessionManager") as mgr_cls,
            patch("forge.cli.session_codex.resume_codex_session", return_value=0) as resume,
        ):
            mgr_cls.return_value.get_session.return_value = self._codex_state(tmp_path)
            result = runner.invoke(main, ["session", "resume", "impl", "--task", "next step"])

        assert result.exit_code == 0
        resume.assert_called_once_with(name="impl", task="next step", sandbox="workspace-write")

    def test_dispatch_with_task_falls_back_to_global_codex_session_from_other_project(
        self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        codex_project = tmp_path / "codex-project"
        other_project = tmp_path / "other-project"
        for project_root in (codex_project, other_project):
            (project_root / ".git").mkdir(parents=True)
            (project_root / ".forge").mkdir()

        state = create_session_state("impl", worktree_path=str(codex_project), runtime="codex")
        state.forge_root = str(codex_project)
        state.confirmed.codex = CodexConfirmed(thread_id=_TID)
        SessionStore(str(codex_project), "impl").write(state)
        IndexStore().add_session(
            name="impl",
            worktree_path=str(codex_project),
            project_root=str(codex_project),
            forge_root=str(codex_project),
            checkout_root=str(codex_project),
            relative_path=".",
            is_incognito=False,
            is_fork=False,
            parent_session="planner",
        )

        monkeypatch.chdir(other_project)
        with patch("forge.cli.session_codex.resume_codex_session", return_value=0) as resume:
            result = runner.invoke(main, ["session", "resume", "impl", "--task", "next step"])

        assert result.exit_code == 0, result.output
        resume.assert_called_once_with(name="impl", task="next step", sandbox="workspace-write")

    def test_exit_code_propagates(self, runner: CliRunner, tmp_path: Path) -> None:
        with (
            patch("forge.cli.session_lifecycle.SessionManager") as mgr_cls,
            patch("forge.cli.session_codex.resume_codex_session", return_value=2),
        ):
            mgr_cls.return_value.get_session.return_value = self._codex_state(tmp_path)
            result = runner.invoke(main, ["session", "resume", "impl", "--task", "t"])
        assert result.exit_code == 2

    def test_bare_resume_reattaches(self, runner: CliRunner, tmp_path: Path) -> None:
        with (
            patch("forge.cli.session_lifecycle.SessionManager") as mgr_cls,
            patch("forge.cli.session_codex._get_active_session_entry", return_value=None),
            patch(
                "forge.cli.session_codex.reattach_interactive_codex_session",
                return_value=0,
            ) as reattach,
        ):
            mgr_cls.return_value.get_session.return_value = self._codex_state(tmp_path)
            result = runner.invoke(main, ["session", "resume", "impl"])

        assert result.exit_code == 0
        reattach.assert_called_once_with(name="impl")

    def test_bare_resume_refused_while_active(self, runner: CliRunner, tmp_path: Path) -> None:
        """Claude reconnect parity: no second TUI on a live launch (and no --force escape)."""
        entry = ActiveSessionEntry(
            worktree_path=str(tmp_path),
            started_at="2026-06-11T00:00:00Z",
            launch_mode="host",
            launcher_pid=4242,
        )
        with (
            patch("forge.cli.session_lifecycle.SessionManager") as mgr_cls,
            patch("forge.cli.session_codex._get_active_session_entry", return_value=entry),
            patch("forge.cli.session_codex.reattach_interactive_codex_session") as reattach,
        ):
            mgr_cls.return_value.get_session.return_value = self._codex_state(tmp_path)
            result = runner.invoke(main, ["session", "resume", "impl"])

        assert result.exit_code == 1
        assert "appears to still be active" in result.output
        assert "Launch mode: host" in result.output
        assert "Launcher PID: 4242" in result.output
        assert "Reconnect is only available after the previous launch has exited" in result.output
        reattach.assert_not_called()

    def test_force_rejected_for_bare_resume(self, runner: CliRunner, tmp_path: Path) -> None:
        """--force is Claude-only; it must not become an active-gate escape for codex."""
        with patch("forge.cli.session_lifecycle.SessionManager") as mgr_cls:
            mgr_cls.return_value.get_session.return_value = self._codex_state(tmp_path)
            result = runner.invoke(main, ["session", "resume", "impl", "--force"])

        assert result.exit_code == 1
        assert "--force is not supported for Codex sessions" in result.output

    def test_bare_resume_falls_back_to_global_codex_session_from_other_project(
        self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Codex reattach is cross-CWD by design: the TUI runs in the recorded worktree."""
        codex_project = tmp_path / "codex-project"
        other_project = tmp_path / "other-project"
        for project_root in (codex_project, other_project):
            (project_root / ".git").mkdir(parents=True)
            (project_root / ".forge").mkdir()

        state = create_session_state("impl", worktree_path=str(codex_project), runtime="codex")
        state.forge_root = str(codex_project)
        state.confirmed.codex = CodexConfirmed(thread_id=_TID)
        SessionStore(str(codex_project), "impl").write(state)
        IndexStore().add_session(
            name="impl",
            worktree_path=str(codex_project),
            project_root=str(codex_project),
            forge_root=str(codex_project),
            checkout_root=str(codex_project),
            relative_path=".",
            is_incognito=False,
            is_fork=False,
            parent_session="planner",
        )

        monkeypatch.chdir(other_project)
        with (
            patch("forge.cli.session_codex._get_active_session_entry", return_value=None),
            patch(
                "forge.cli.session_codex.reattach_interactive_codex_session",
                return_value=0,
            ) as reattach,
        ):
            result = runner.invoke(main, ["session", "resume", "impl"])

        assert result.exit_code == 0, result.output
        reattach.assert_called_once_with(name="impl")

    def test_bare_claude_resume_cross_project_keeps_refusal(
        self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The unscoped fallback now resolves the manifest for every bare resume, but a
        Claude hit must keep today's project-scoped refusal (hint + exit 1)."""
        claude_project = tmp_path / "claude-project"
        other_project = tmp_path / "other-project"
        for project_root in (claude_project, other_project):
            (project_root / ".git").mkdir(parents=True)
            (project_root / ".forge").mkdir()

        state = create_session_state("impl", worktree_path=str(claude_project))
        state.forge_root = str(claude_project)
        SessionStore(str(claude_project), "impl").write(state)
        IndexStore().add_session(
            name="impl",
            worktree_path=str(claude_project),
            project_root=str(claude_project),
            forge_root=str(claude_project),
            checkout_root=str(claude_project),
            relative_path=".",
            is_incognito=False,
            is_fork=False,
            parent_session=None,
        )

        monkeypatch.chdir(other_project)
        result = runner.invoke(main, ["session", "resume", "impl"])

        assert result.exit_code == 1
        assert "session 'impl' not found in current project" in result.output
        assert "exists in:" in result.output
        assert "Run the command from that directory instead." in result.output

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
        with patch("forge.cli.session_lifecycle.SessionManager") as mgr_cls:
            mgr_cls.return_value.get_session.return_value = self._codex_state(tmp_path)
            result = runner.invoke(main, ["session", "resume", "impl", "--task", "t"] + extra_args)

        assert result.exit_code == 1
        assert f"{flag_label} is not supported for Codex sessions" in result.output

    def test_task_rejected_for_claude_sessions(self, runner: CliRunner, tmp_path: Path) -> None:
        claude_state = create_session_state("cl", worktree_path=str(tmp_path))
        with patch("forge.cli.session_lifecycle.SessionManager") as mgr_cls:
            mgr_cls.return_value.get_session.return_value = claude_state
            result = runner.invoke(main, ["session", "resume", "cl", "--task", "t"])

        assert result.exit_code == 1
        assert "--task is only supported for Codex sessions" in result.output


class TestLaunchClaudeBackstop:
    def test_codex_manifest_refused(self, tmp_path: Path) -> None:
        from forge.core.ops.claude_session import launch_claude_session

        state = create_session_state("impl", worktree_path=str(tmp_path), runtime="codex")
        with pytest.raises(ForgeOpError, match="runtime 'codex'"):
            launch_claude_session(
                manifest=state,
                session_id=None,
                resume_id=None,
                effective_template=None,
                runtime_base_url=None,
                context_limit=200_000,
                use_sidecar=False,
            )


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
        with patch(
            "forge.cli.session_codex.start_codex_session",
            side_effect=ForgeOpError("parent not found"),
        ):
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
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "Error:" in captured.err and "parent not found" in captured.err

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

    def test_start_hook_undelivered_exits_one_with_tip(self, capsys: pytest.CaptureFixture[str]) -> None:
        """The handoff is the point of the command: a successful codex turn that ran
        WITHOUT the parent context still fails loud (session kept, fact recorded)."""
        result = _start_result(context_delivery="hook_undelivered")
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
                context_delivery="hook",
            )

        assert code == 1
        captured = capsys.readouterr()
        assert "Created Codex session" in captured.out
        assert "did not deliver the transfer context" in captured.err
        assert "hook_undelivered" in captured.err
        assert "Tip:" in captured.err and "forge session delete impl" in captured.err

    def test_start_hook_delivered_renders_delivery_line(self, capsys: pytest.CaptureFixture[str]) -> None:
        result = _start_result(context_delivery="session_start_hook")
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
                context_delivery="hook",
            )

        assert code == 0
        out = capsys.readouterr().out
        assert "Context delivery: SessionStart hook" in out

    def test_resume_success_render(self, capsys: pytest.CaptureFixture[str]) -> None:
        result = CodexSessionResumeResult(
            session="impl",
            thread_id=_TID,
            root_run_id="run-2",
            codex=_headless(stdout="Done"),
            rollout_path=None,
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
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "Error:" in captured.err and "no recorded Codex thread" in captured.err


class TestInteractiveCliRendering:
    """Direct calls into session_codex with the interactive ops mocked."""

    def test_announce_bare(self, capsys: pytest.CaptureFixture[str]) -> None:
        _render_interactive_launch(
            CodexInteractiveLaunch(
                session="impl",
                parent=None,
                worktree_path=None,
                transfer_path=None,
                context_delivery=None,
            )
        )
        out = capsys.readouterr().out
        assert "Created Codex session" in out and "impl" in out
        assert "from '" not in out  # no parent line on a bare start
        assert "direct (OpenAI via codex CLI)" in out

    def test_announce_bridge_hook(self, capsys: pytest.CaptureFixture[str]) -> None:
        _render_interactive_launch(
            CodexInteractiveLaunch(
                session="impl",
                parent="planner",
                worktree_path="/wt/impl",
                transfer_path=Path("/proj/.forge/prev_sessions/planner/children/impl.md"),
                context_delivery="hook",
            )
        )
        out = capsys.readouterr().out
        assert "(from 'planner')" in out
        assert "Worktree: /wt/impl" in out
        assert "Transfer:" in out
        assert "Context delivery: SessionStart hook" in out

    def test_announce_reattach(self, capsys: pytest.CaptureFixture[str]) -> None:
        _render_interactive_launch(
            CodexInteractiveLaunch(
                session="impl",
                parent=None,
                worktree_path=None,
                transfer_path=None,
                context_delivery=None,
                reattach_thread_id=_TID,
            )
        )
        out = capsys.readouterr().out
        assert "Reattaching Codex session" in out and _TID in out

    def test_interactive_start_op_error_exits_one(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch(
            "forge.cli.session_codex.start_interactive_codex_session",
            side_effect=ForgeOpError("Codex runtime not ready: no codex binary"),
        ):
            code = launch_interactive_codex_session(
                name="impl",
                parent=None,
                strategy="ai-curated",
                depth=1,
                sandbox="workspace-write",
                worktree=False,
                branch=None,
            )

        assert code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "Error:" in captured.err and "not ready" in captured.err

    def test_interactive_finish_renders_thread_and_warnings(self, capsys: pytest.CaptureFixture[str]) -> None:
        result = _interactive_result(warnings=("2 Codex rollouts appeared during this run",))
        with patch(
            "forge.cli.session_codex.start_interactive_codex_session",
            return_value=result,
        ):
            code = launch_interactive_codex_session(
                name="impl",
                parent=None,
                strategy="ai-curated",
                depth=1,
                sandbox="workspace-write",
                worktree=False,
                branch=None,
            )

        assert code == 0
        out = capsys.readouterr().out
        assert f"Thread: {_TID}" in out
        assert "Warning:" in out and "2 Codex rollouts appeared" in out

    def test_interactive_exit_code_passes_through(self) -> None:
        result = _interactive_result(exit_code=130, thread_id=None, rollout_path=None, rollout_source=None)
        with patch(
            "forge.cli.session_codex.start_interactive_codex_session",
            return_value=result,
        ):
            code = launch_interactive_codex_session(
                name="impl",
                parent=None,
                strategy="ai-curated",
                depth=1,
                sandbox="workspace-write",
                worktree=False,
                branch=None,
            )

        assert code == 130

    def test_interactive_hook_undelivered_exits_one_with_tip(self, capsys: pytest.CaptureFixture[str]) -> None:
        """The TUI ran without the parent context: fail loud even on a clean exit."""
        result = _interactive_result(context_delivery="hook_undelivered", curation_ran=True)
        with patch(
            "forge.cli.session_codex.start_interactive_codex_session",
            return_value=result,
        ):
            code = launch_interactive_codex_session(
                name="impl",
                parent="planner",
                strategy="ai-curated",
                depth=1,
                sandbox="workspace-write",
                worktree=False,
                branch=None,
                context_delivery="hook",
            )

        assert code == 1
        captured = capsys.readouterr()
        assert "Thread:" in captured.out
        assert "did not deliver the transfer context" in captured.err
        assert "hook_undelivered" in captured.err
        assert "forge session delete impl" in captured.err

    def test_reattach_op_error_exits_one(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch(
            "forge.cli.session_codex.reattach_codex_session",
            side_effect=ForgeOpError("session 'impl' has no recorded Codex thread"),
        ):
            code = reattach_interactive_codex_session(name="impl")

        assert code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "Error:" in captured.err and "no recorded Codex thread" in captured.err

    def test_reattach_success_passes_through(self) -> None:
        result = _interactive_result()
        with patch("forge.cli.session_codex.reattach_codex_session", return_value=result) as op:
            code = reattach_interactive_codex_session(name="impl")

        assert code == 0
        assert op.call_args.kwargs["sandbox"] == "workspace-write"


class TestShowCodexSession:
    def _seed(self, proj: Path, *, context_delivery: str | None = None) -> None:
        state = create_session_state("impl", worktree_path=str(proj), runtime="codex")
        state.confirmed.codex = CodexConfirmed(
            thread_id=_TID,
            rollout_path=f"/codex/sessions/2026/06/10/rollout-x-{_TID}.jsonl",
            rollout_source="discovered_by_thread_id",
            auth_method="chatgpt_tokens",
            auth_source="codex_store",
            billing_mode="subscription_quota",
            last_run_at="2026-06-10T00:00:00Z",
            context_delivery=context_delivery,
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

    def test_show_human_renders_delivery_line(self, runner: CliRunner, project: Path) -> None:
        self._seed(project, context_delivery="initial_message")
        result = runner.invoke(main, ["session", "show", "impl"])

        assert result.exit_code == 0
        assert "Delivery:" in result.output and "initial_message" in result.output

    def test_show_human_omits_delivery_when_unset(self, runner: CliRunner, project: Path) -> None:
        """Bare interactive starts record context_delivery=None -- no line to show."""
        self._seed(project)
        result = runner.invoke(main, ["session", "show", "impl"])

        assert result.exit_code == 0
        assert "Delivery:" not in result.output

    def test_show_human_suppresses_claude_vestiges(self, runner: CliRunner, project: Path) -> None:
        """The display-only intent.agent ("claude-code") and the Claude-computed
        Model Family ("anthropic") would misread on a Codex session."""
        self._seed(project)
        result = runner.invoke(main, ["session", "show", "impl"])

        assert result.exit_code == 0
        assert "Agent:" not in result.output
        assert "Model Family" not in result.output
        assert "Computed Context" not in result.output
