"""Tests for session fork and cross-project CLI behavior."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from click.testing import CliRunner
from rich.console import Console

import forge.cli.session as session_cli
from forge.cli.main import main
from forge.session import IndexStore, SessionManager, SessionStore, create_session_state
from forge.session.active import ActiveSessionStore
from forge.session.config import LAUNCH_MODE_HOST, LAUNCH_MODE_SIDECAR
from tests.src.cli.session_command_support import (
    _proxy_cfg,
    _proxy_routing,
    _read_session_manifest,
    _seed_scoped_duplicate_sessions,
    _write_session_manifest,
    successful_claude_launch,
)


def _seed_cross_project_session(project: Path, session_name: str = "cross-sess") -> Path:
    """Seed a session in a nested forge_root that the current CWD can't reach."""
    other_root = project / "nested-sub"
    other_root.mkdir(parents=True, exist_ok=True)
    (other_root / ".forge").mkdir(parents=True, exist_ok=True)

    manifest = create_session_state(
        session_name,
        proxy_template="t",
        proxy_base_url="http://localhost:9999",
        worktree_path=str(other_root),
    )
    manifest.forge_root = str(other_root)
    SessionStore(str(other_root), session_name).write(manifest)
    IndexStore().add_session(
        name=session_name,
        worktree_path=str(other_root),
        project_root=str(project),
        forge_root=str(other_root),
    )
    return other_root


class TestCrossProjectHints:
    """Cross-project 'not found' hints across all affected commands."""

    def test_resume_cross_project_shows_hint(self, runner: CliRunner, temp_env: Path) -> None:
        """Resume from wrong forge_root should hint where the session lives."""
        _seed_cross_project_session(temp_env)

        result = runner.invoke(main, ["session", "resume", "cross-sess"])

        assert result.exit_code == 1
        assert "not found in current project" in result.output
        assert "nested-sub" in result.output

    def test_cross_project_hint_does_not_wrap_target_path(self, temp_env: Path, tmp_path: Path) -> None:
        """Cross-project hints should keep the target path intact on narrow terminals."""
        _seed_cross_project_session(temp_env)
        output = tmp_path / "hint-output.txt"

        with output.open("w", encoding="utf-8") as handle:
            narrow_console = Console(file=handle, width=40, force_terminal=False)
            with patch.object(session_cli, "console", narrow_console):
                hinted = session_cli._hint_cross_project_session("cross-sess", str(temp_env))

        rendered = output.read_text(encoding="utf-8")
        assert hinted is True
        assert "nested-sub" in rendered
        assert "nested-su\nb" not in rendered

    def test_fork_cross_project_shows_hint(self, runner: CliRunner, temp_env: Path) -> None:
        """Fork from wrong forge_root should hint where the parent lives."""
        _seed_cross_project_session(temp_env)

        result = runner.invoke(main, ["session", "fork", "cross-sess", "--name", "child"])

        assert result.exit_code == 1
        assert "not found in current project" in result.output
        assert "nested-sub" in result.output

    def test_show_cross_project_resolves(self, runner: CliRunner, temp_env: Path) -> None:
        """Show from wrong forge_root should resolve cross-project and succeed."""
        _seed_cross_project_session(temp_env)

        result = runner.invoke(main, ["session", "show", "cross-sess"])

        assert result.exit_code == 0
        assert "cross-sess" in result.output
        assert "nested-sub" in result.output  # cross-project note

    def test_shell_cross_project_shows_hint(self, runner: CliRunner, temp_env: Path) -> None:
        """Shell from wrong forge_root should hint where the session lives."""
        _seed_cross_project_session(temp_env)

        result = runner.invoke(main, ["session", "shell", "cross-sess"])

        assert result.exit_code == 1
        assert "not found in current project" in result.output
        assert "nested-sub" in result.output


class TestCrossProjectResolution:
    """Commands that resolve sessions across forge_root boundaries."""

    def test_show_cross_project_json(self, runner: CliRunner, temp_env: Path) -> None:
        """JSON output should work for cross-project sessions."""
        _seed_cross_project_session(temp_env)

        result = runner.invoke(main, ["session", "show", "cross-sess", "--json"])

        assert result.exit_code == 0
        import json

        data = json.loads(result.output)
        assert data["session_name"] == "cross-sess"

    def test_delete_all_stays_project_scoped(self, runner: CliRunner, temp_env: Path) -> None:
        """--all only deletes sessions in the current forge_root, not cross-project."""
        _seed_cross_project_session(temp_env)

        # Also seed a session in the current forge_root
        local = create_session_state(
            "local-sess",
            proxy_template="t",
            proxy_base_url="http://localhost:9999",
            worktree_path=str(temp_env),
        )
        local.forge_root = str(temp_env)
        SessionStore(str(temp_env), "local-sess").write(local)
        IndexStore().add_session(
            name="local-sess",
            worktree_path=str(temp_env),
            project_root=str(temp_env),
            forge_root=str(temp_env),
        )

        result = runner.invoke(main, ["session", "delete", "--all", "--yes"])

        assert result.exit_code == 0
        assert "local-sess" in result.output

        # Cross-project session should still exist
        from forge.session.manager import SessionManager

        remaining = SessionManager().list_sessions()
        remaining_names = [n for n, _ in remaining]
        assert "cross-sess" in remaining_names

    def test_set_cross_project_resolves(self, runner: CliRunner, temp_env: Path) -> None:
        """set --session should resolve cross-project sessions."""
        _seed_cross_project_session(temp_env)

        result = runner.invoke(main, ["session", "set", "agent", "custom", "--session", "cross-sess"])

        assert result.exit_code == 0
        assert "agent" in result.output

    def test_reset_cross_project_resolves(self, runner: CliRunner, temp_env: Path) -> None:
        """reset --session should resolve cross-project sessions."""
        _seed_cross_project_session(temp_env)

        # First set an override, then reset it
        runner.invoke(main, ["session", "set", "agent", "custom", "--session", "cross-sess"])
        result = runner.invoke(main, ["session", "reset", "agent", "--session", "cross-sess"])

        assert result.exit_code == 0
        assert "Reset" in result.output or "override" in result.output.lower()

    def test_delete_all_refuses_outside_forge_project(self, runner: CliRunner, tmp_path: Path, monkeypatch) -> None:
        """--all should refuse when _cwd_forge_root() is None (outside any Forge project)."""
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))

        # Directory with no .forge/
        bare_dir = tmp_path / "bare"
        bare_dir.mkdir()
        (bare_dir / ".git").mkdir()
        monkeypatch.chdir(bare_dir)

        result = runner.invoke(main, ["session", "delete", "--all", "--yes"])

        assert result.exit_code == 1
        assert "requires being inside a Forge project" in result.output

    def test_delete_cross_project_corrupt_manifest(self, runner: CliRunner, temp_env: Path) -> None:
        """Force-delete should work on cross-project sessions with corrupt manifests."""
        other_root = _seed_cross_project_session(temp_env)

        # Corrupt the manifest
        manifest_path = other_root / ".forge" / "sessions" / "cross-sess" / "forge.session.json"
        manifest_path.write_text("{invalid json")

        result = runner.invoke(main, ["session", "delete", "cross-sess", "--yes", "--force"])

        # Should succeed (force-delete cleans up despite corrupt manifest)
        assert result.exit_code == 0

    def test_show_ambiguous_shows_locations(
        self, runner: CliRunner, temp_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Show of ambiguous name from a third forge_root should list all locations."""
        _seed_scoped_duplicate_sessions(temp_env)

        # "shared" exists in forge_root_a (temp_env) and forge_root_b (temp_env/nested-project).
        # Run show from a third forge_root where "shared" does NOT exist.
        forge_root_c = temp_env / "other-project"
        forge_root_c.mkdir(parents=True, exist_ok=True)
        (forge_root_c / ".forge").mkdir(parents=True, exist_ok=True)

        # Must patch CWD too — resolve_session_identifier derives its own
        # forge_root from Path.cwd(), not from session._cwd_forge_root().
        monkeypatch.chdir(forge_root_c)
        with patch("forge.cli.session_manage._cwd_forge_root", return_value=str(forge_root_c)):
            result = runner.invoke(main, ["session", "show", "shared"])

        assert result.exit_code == 1
        assert "Ambiguous" in result.output or "multiple" in result.output.lower()


class TestResumeProjectScoping:
    """Resume/relaunch should stay scoped to the current forge_root."""

    def test_resume_force_active_relaunches_current_project_duplicate(self, runner: CliRunner, temp_env: Path) -> None:
        """--force relaunch should not fall through to an ambiguous duplicate in another project."""
        forge_root_a, forge_root_b = _seed_scoped_duplicate_sessions(temp_env)

        current_state = _read_session_manifest(forge_root_a, "shared")
        current_state.confirmed.claude_session_id = "uuid-alpha"
        current_state.confirmed.confirmed_by = "hook:SessionStart:startup"
        _write_session_manifest(forge_root_a, "shared", current_state)

        other_state = _read_session_manifest(forge_root_b, "shared")
        other_state.confirmed.claude_session_id = "uuid-beta"
        other_state.confirmed.confirmed_by = "hook:SessionStart:startup"
        _write_session_manifest(forge_root_b, "shared", other_state)

        ActiveSessionStore().upsert_session(
            "shared",
            worktree_path=str(forge_root_a),
            launch_mode=LAUNCH_MODE_HOST,
            forge_root=str(forge_root_a),
            launcher_pid=os.getpid(),
        )

        with successful_claude_launch() as mock_invoke:
            result = runner.invoke(main, ["session", "resume", "shared", "--force"])

        assert result.exit_code == 0, result.output
        assert mock_invoke.call_args is not None
        assert mock_invoke.call_args.kwargs["resume_id"] == "uuid-alpha"

        manager = SessionManager()
        project_a_sessions = [name for name, _ in manager.list_sessions(forge_root_filter=str(forge_root_a))]
        project_b_sessions = [name for name, _ in manager.list_sessions(forge_root_filter=str(forge_root_b))]
        assert project_a_sessions.count("shared") == 1
        assert len(project_a_sessions) == 2
        assert project_b_sessions == ["shared"]


class TestSessionFork:
    """Tests for 'forge session fork' command."""

    def test_fork_direct_parent_clears_proxy_env(self, runner: CliRunner, temp_env: Path) -> None:
        """Direct same-dir forks should not inherit proxy env from the shell."""
        parent = create_session_state(
            "fork-parent",
            worktree_path=str(temp_env),
            worktree_branch="main",
        )
        parent.confirmed.claude_session_id = "parent-uuid"

        fork_state = create_session_state(
            "fork-child",
            parent_session="fork-parent",
            is_fork=True,
            worktree_path=str(temp_env),
        )

        with (
            patch("forge.cli.session_fork.SessionManager") as mock_manager_cls,
            successful_claude_launch() as mock_invoke,
        ):
            mock_manager = mock_manager_cls.return_value
            mock_manager.fork_session.return_value = (parent, fork_state)

            result = runner.invoke(main, ["session", "fork", "fork-parent", "--name", "fork-child"])

        assert result.exit_code == 0
        kwargs = mock_invoke.call_args.kwargs
        assert "ANTHROPIC_BASE_URL" not in kwargs["env_vars"]
        assert "ACTIVE_TEMPLATE" not in kwargs["env_vars"]
        assert "FORGE_PROXY_WIRE_SHAPE" not in kwargs["env_vars"]
        assert "CLAUDE_CODE_AUTO_COMPACT_WINDOW" not in kwargs["env_vars"]
        assert sorted(kwargs["unset_env_vars"]) == [
            "ACTIVE_TEMPLATE",
            "ANTHROPIC_BASE_URL",
            "FORGE_PROXY_WIRE_SHAPE",
        ]
        assert kwargs["model"] is None

    def test_non_direct_sidecar_fork_uses_sidecar_launcher(self, runner: CliRunner, temp_env: Path) -> None:
        """A sidecar parent should fork through the sidecar launch path."""
        runner.invoke(
            main,
            ["session", "start", "fork-sidecar-parent", "--sidecar", "--no-launch"],
        )

        store = SessionStore(str(temp_env), "fork-sidecar-parent")

        def _confirm_parent(m: object) -> None:
            m.confirmed.claude_session_id = "parent-sidecar-uuid"  # type: ignore[attr-defined]

        store.update(timeout_s=5.0, mutate=_confirm_parent)

        with (
            patch("forge.sidecar.docker.is_docker_available", return_value=True),
            patch("forge.sidecar.get_secrets_for_template", return_value={}),
            patch("forge.sidecar.run_sidecar_session", return_value=0) as mock_run_sidecar,
            successful_claude_launch() as mock_invoke,
        ):
            result = runner.invoke(
                main,
                [
                    "session",
                    "fork",
                    "fork-sidecar-parent",
                    "--name",
                    "fork-sidecar-child",
                ],
            )

        assert result.exit_code == 0, result.output
        assert mock_run_sidecar.called is True
        assert mock_invoke.called is False

    def test_bad_sidecar_mount_fork_does_not_confirm_sandbox(self, runner: CliRunner, temp_env: Path) -> None:
        """Sidecar validation failures before the runner should not mark the child sandboxed."""
        start_result = runner.invoke(
            main,
            [
                "session",
                "start",
                "fork-bad-mount-parent",
                "--sidecar",
                "--mount",
                "/host/only",
                "--no-launch",
            ],
        )
        assert start_result.exit_code == 0, start_result.output

        store = SessionStore(str(temp_env), "fork-bad-mount-parent")

        def _confirm_parent(m: object) -> None:
            m.confirmed.claude_session_id = "parent-sidecar-uuid"  # type: ignore[attr-defined]

        store.update(timeout_s=5.0, mutate=_confirm_parent)

        with (
            patch("forge.sidecar.docker.is_docker_available", return_value=True),
            patch("forge.sidecar.run_sidecar_session", return_value=0) as mock_run_sidecar,
        ):
            result = runner.invoke(
                main,
                [
                    "session",
                    "fork",
                    "fork-bad-mount-parent",
                    "--name",
                    "fork-bad-mount-child",
                ],
            )

        assert result.exit_code == 1, result.output
        assert "Invalid mount specification" in result.output
        assert mock_run_sidecar.called is False
        child = SessionStore(str(temp_env), "fork-bad-mount-child").read()
        assert child.confirmed.is_sandboxed is False

    def test_fork_default_no_worktree(self, runner: CliRunner, temp_env: Path) -> None:
        """Default fork stays in parent's directory (no worktree)."""
        parent = create_session_state(
            "fork-parent",
            proxy_template="litellm-openai",
            proxy_base_url="http://localhost:8085",
            worktree_path=str(temp_env),
            worktree_branch="main",
        )
        parent.confirmed.claude_session_id = "parent-uuid"

        fork_state = create_session_state(
            "fork-child",
            proxy_template="litellm-openai",
            proxy_base_url="http://localhost:8085",
            parent_session="fork-parent",
            is_fork=True,
            worktree_path=str(temp_env),
        )

        with (
            patch("forge.cli.session_fork.SessionManager") as mock_manager_cls,
            successful_claude_launch() as mock_invoke,
        ):
            mock_manager = mock_manager_cls.return_value
            mock_manager.fork_session.return_value = (parent, fork_state)

            result = runner.invoke(main, ["session", "fork", "fork-parent", "--name", "fork-child"])

        assert result.exit_code == 0
        # No worktree info in output
        assert "Worktree:" not in result.output
        # Claude invoked with --resume --fork-session
        assert mock_invoke.call_args is not None
        kwargs = mock_invoke.call_args.kwargs
        assert kwargs["resume_id"] == "parent-uuid"
        assert kwargs["fork_session"] is True
        # Manager called without create_worktree
        call_kwargs = mock_manager.fork_session.call_args.kwargs
        assert call_kwargs.get("create_worktree") is False

    def test_fork_with_worktree_starts_fresh_with_context(self, runner: CliRunner, temp_env: Path) -> None:
        """Worktree fork starts fresh Claude with parent handoff context (no --resume)."""
        parent = create_session_state(
            "fork-parent",
            proxy_template="litellm-openai",
            proxy_base_url="http://localhost:8085",
            worktree_path=str(temp_env),
            worktree_branch="main",
        )
        parent.confirmed.claude_session_id = "parent-uuid"

        fork_worktree = temp_env / "fork-child"
        fork_worktree.mkdir()
        fork_state = create_session_state(
            "fork-child",
            proxy_template="litellm-openai",
            proxy_base_url="http://localhost:8085",
            parent_session="fork-parent",
            is_fork=True,
            worktree_path=str(fork_worktree),
            worktree_branch="fork-child",
        )
        assert fork_state.worktree is not None
        fork_state.worktree.is_worktree = True

        context_file = fork_worktree / ".forge" / "prev_sessions" / "fork-parent" / "children" / "fork-child.md"
        context_file.parent.mkdir(parents=True)
        context_file.write_text("# Parent context\n")

        with (
            patch("forge.cli.session_fork.SessionManager") as mock_manager_cls,
            successful_claude_launch() as mock_invoke,
            patch(
                "forge.cli.session_fork._generate_parent_transfer_context",
                return_value=(context_file, []),
            ),
        ):
            mock_manager = mock_manager_cls.return_value
            mock_manager.fork_session.return_value = (parent, fork_state)

            result = runner.invoke(
                main,
                [
                    "session",
                    "fork",
                    "fork-parent",
                    "--name",
                    "fork-child",
                    "--worktree",
                ],
            )

        assert result.exit_code == 0
        assert "Worktree:" in result.output
        # UUID pre-seeded for fresh worktree fork
        kwargs = mock_invoke.call_args.kwargs
        assert kwargs.get("session_id") is not None
        assert len(kwargs["session_id"]) == 36  # UUID format
        assert kwargs.get("name") == "fork-child"
        assert kwargs.get("resume_id") is None
        assert kwargs.get("fork_session") is None
        assert kwargs.get("system_prompt_file") is not None
        call_kwargs = mock_manager.fork_session.call_args.kwargs
        assert call_kwargs["create_worktree"] is True

    # ---- native-relocate (--resume-mode) -------------------------------------

    def _nr_parent_and_fork(
        self,
        temp_env: Path,
        *,
        parent_sidecar: bool = False,
        with_transcript: bool = True,
    ):
        """Build (parent, worktree-fork) states; optionally seed the parent's Claude transcript."""
        from forge.session import LAUNCH_MODE_HOST as _HOST
        from forge.session import LAUNCH_MODE_SIDECAR as _SC
        from forge.session.claude.paths import get_transcript_path

        parent = create_session_state(
            "fork-parent",
            worktree_path=str(temp_env),
            worktree_branch="main",
            launch_mode=_SC if parent_sidecar else _HOST,
        )
        parent.confirmed.claude_session_id = "parent-uuid"
        parent.confirmed.claude_project_root = str(temp_env)
        if with_transcript:
            tp = get_transcript_path(str(temp_env), "parent-uuid")
            tp.parent.mkdir(parents=True, exist_ok=True)
            tp.write_text('{"type":"thinking","signature":"x"}\n')

        fork_worktree = temp_env / "fork-child"
        fork_worktree.mkdir(exist_ok=True)
        fork_state = create_session_state(
            "fork-child",
            parent_session="fork-parent",
            is_fork=True,
            worktree_path=str(fork_worktree),
            worktree_branch="fork-child",
        )
        assert fork_state.worktree is not None
        fork_state.worktree.is_worktree = True
        return parent, fork_state

    def test_native_relocate_worktree_resumes_parent(self, runner: CliRunner, temp_env: Path) -> None:
        """--resume-mode native-relocate relocates the parent JSONL and resumes natively."""
        from forge.session.claude.paths import get_transcript_path

        parent, fork_state = self._nr_parent_and_fork(temp_env)
        with (
            patch("forge.cli.session_fork.SessionManager") as mock_manager_cls,
            successful_claude_launch() as mock_invoke,
        ):
            mock_manager = mock_manager_cls.return_value
            mock_manager.get_session.return_value = parent
            mock_manager.fork_session.return_value = (parent, fork_state)
            result = runner.invoke(
                main,
                [
                    "session",
                    "fork",
                    "fork-parent",
                    "-n",
                    "fork-child",
                    "--worktree",
                    "--resume-mode",
                    "native-relocate",
                ],
            )

        assert result.exit_code == 0, result.output
        kwargs = mock_invoke.call_args.kwargs
        assert kwargs.get("resume_id") == "parent-uuid"
        assert kwargs.get("fork_session") is True
        assert kwargs.get("session_id") is None
        # The parent transcript was relocated into the child's encoded dir.
        child_cwd = str(temp_env / "fork-child")
        assert get_transcript_path(child_cwd, "parent-uuid").is_file()

    def test_worktree_default_prints_native_relocate_tip(self, runner: CliRunner, temp_env: Path) -> None:
        """A plain worktree fork (no --resume-mode) surfaces the native-relocate option."""
        parent, fork_state = self._nr_parent_and_fork(temp_env)
        context_file = temp_env / "fork-child" / ".forge" / "ctx.md"
        context_file.parent.mkdir(parents=True, exist_ok=True)
        context_file.write_text("# ctx\n")
        with (
            patch("forge.cli.session_fork.SessionManager") as mock_manager_cls,
            successful_claude_launch(),
            patch(
                "forge.cli.session_fork._generate_parent_transfer_context",
                return_value=(context_file, []),
            ),
        ):
            mock_manager = mock_manager_cls.return_value
            mock_manager.get_session.return_value = parent
            mock_manager.fork_session.return_value = (parent, fork_state)
            result = runner.invoke(
                main,
                ["session", "fork", "fork-parent", "-n", "fork-child", "--worktree"],
            )

        assert result.exit_code == 0, result.output
        assert "--resume-mode native-relocate" in result.output

    def test_native_relocate_rejects_sidecar(self, runner: CliRunner, temp_env: Path) -> None:
        """A non-direct sidecar parent rejects native-relocate before any fork is created."""
        parent, fork_state = self._nr_parent_and_fork(temp_env, parent_sidecar=True)
        with patch("forge.cli.session_fork.SessionManager") as mock_manager_cls:
            mock_manager = mock_manager_cls.return_value
            mock_manager.get_session.return_value = parent
            mock_manager.fork_session.return_value = (parent, fork_state)
            result = runner.invoke(
                main,
                [
                    "session",
                    "fork",
                    "fork-parent",
                    "-n",
                    "fork-child",
                    "--worktree",
                    "--resume-mode",
                    "native-relocate",
                ],
            )

        assert result.exit_code != 0
        assert "not supported with sidecar" in result.output
        mock_manager.fork_session.assert_not_called()

    def test_native_relocate_allows_direct_sidecar_parent(self, runner: CliRunner, temp_env: Path) -> None:
        """--no-proxy forces host launch, so a sidecar parent is NOT rejected with --no-proxy."""
        parent, fork_state = self._nr_parent_and_fork(temp_env, parent_sidecar=True)
        with (
            patch("forge.cli.session_fork.SessionManager") as mock_manager_cls,
            successful_claude_launch(),
        ):
            mock_manager = mock_manager_cls.return_value
            mock_manager.get_session.return_value = parent
            mock_manager.fork_session.return_value = (parent, fork_state)
            result = runner.invoke(
                main,
                [
                    "session",
                    "fork",
                    "fork-parent",
                    "-n",
                    "fork-child",
                    "--worktree",
                    "--no-proxy",
                    "--resume-mode",
                    "native-relocate",
                ],
            )

        assert "not supported with sidecar" not in result.output
        mock_manager.fork_session.assert_called_once()

    def test_native_relocate_rejects_no_launch(self, runner: CliRunner, temp_env: Path) -> None:
        parent, fork_state = self._nr_parent_and_fork(temp_env)
        with patch("forge.cli.session_fork.SessionManager") as mock_manager_cls:
            mock_manager = mock_manager_cls.return_value
            mock_manager.get_session.return_value = parent
            mock_manager.fork_session.return_value = (parent, fork_state)
            result = runner.invoke(
                main,
                [
                    "session",
                    "fork",
                    "fork-parent",
                    "-n",
                    "fork-child",
                    "--worktree",
                    "--no-launch",
                    "--resume-mode",
                    "native-relocate",
                ],
            )

        assert result.exit_code != 0
        assert "--no-launch" in result.output
        mock_manager.fork_session.assert_not_called()

    def test_native_relocate_rejects_missing_parent_transcript(self, runner: CliRunner, temp_env: Path) -> None:
        parent, fork_state = self._nr_parent_and_fork(temp_env, with_transcript=False)
        with patch("forge.cli.session_fork.SessionManager") as mock_manager_cls:
            mock_manager = mock_manager_cls.return_value
            mock_manager.get_session.return_value = parent
            mock_manager.fork_session.return_value = (parent, fork_state)
            result = runner.invoke(
                main,
                [
                    "session",
                    "fork",
                    "fork-parent",
                    "-n",
                    "fork-child",
                    "--worktree",
                    "--resume-mode",
                    "native-relocate",
                ],
            )

        assert result.exit_code != 0
        assert "no Claude transcript" in result.output
        mock_manager.fork_session.assert_not_called()

    def test_resume_mode_on_same_directory_fork_warns(self, runner: CliRunner, temp_env: Path) -> None:
        """--resume-mode native-relocate on a same-directory fork is inapplicable: tip + ignored.

        (transfer is now same-dir-legal; only native-relocate is cross-CWD-only, so the tip is
        scoped to native-relocate and points at native resume or --resume-mode transfer.)
        """
        parent, _ = self._nr_parent_and_fork(temp_env)
        samedir_fork = create_session_state(
            "fork-child",
            parent_session="fork-parent",
            is_fork=True,
            worktree_path=str(temp_env),
        )
        if samedir_fork.worktree is not None:
            samedir_fork.worktree.is_worktree = False
        with (
            patch("forge.cli.session_fork.SessionManager") as mock_manager_cls,
            successful_claude_launch(),
        ):
            mock_manager = mock_manager_cls.return_value
            mock_manager.get_session.return_value = parent
            mock_manager.fork_session.return_value = (parent, samedir_fork)
            result = runner.invoke(
                main,
                [
                    "session",
                    "fork",
                    "fork-parent",
                    "-n",
                    "fork-child",
                    "--resume-mode",
                    "native-relocate",
                ],
            )

        assert "--resume-mode native-relocate only applies to --worktree/--into forks" in result.output
        mock_manager.fork_session.assert_called_once()

    # ---- same-directory transfer forks (decoupled transfer mode) -------------

    def _samedir_parent_and_fork(self, temp_env: Path, *, fork_launch_mode: str = LAUNCH_MODE_HOST):
        """Build (parent, same-directory fork) states.

        A same-directory fork carries a non-None Worktree with is_worktree=False -- the shape
        manager.fork_session produces when no worktree is created (the path is the shared parent
        checkout). Downstream code gates on is_worktree, never truthiness.
        """
        parent = create_session_state("fork-parent", worktree_path=str(temp_env), worktree_branch="main")
        parent.confirmed.claude_session_id = "parent-uuid"
        fork_state = create_session_state(
            "fork-child",
            parent_session="fork-parent",
            is_fork=True,
            worktree_path=str(temp_env),
            launch_mode=fork_launch_mode,
        )
        assert fork_state.worktree is not None
        fork_state.worktree.is_worktree = False
        return parent, fork_state

    def _seed_context_file(self, temp_env: Path, text: str = "# Parent transfer context\n") -> Path:
        ctx = temp_env / ".forge" / "ctx.md"
        ctx.parent.mkdir(parents=True, exist_ok=True)
        ctx.write_text(text)
        return ctx

    def test_samedir_strategy_autoswitches_to_transfer(self, runner: CliRunner, temp_env: Path) -> None:
        """Explicit --strategy on a same-dir fork auto-switches it to transfer: the manager is told
        resume_mode='transfer', an info line prints, and Claude launches with a fresh session_id
        (no parent --resume/--fork-session)."""
        parent, fork_state = self._samedir_parent_and_fork(temp_env)
        ctx = self._seed_context_file(temp_env)
        with (
            patch("forge.cli.session_fork.SessionManager") as mock_manager_cls,
            successful_claude_launch() as mock_invoke,
            patch(
                "forge.cli.session_fork._generate_parent_transfer_context",
                return_value=(ctx, []),
            ),
        ):
            mock_manager = mock_manager_cls.return_value
            mock_manager.get_session.return_value = parent
            mock_manager.fork_session.return_value = (parent, fork_state)
            result = runner.invoke(
                main,
                [
                    "session",
                    "fork",
                    "fork-parent",
                    "-n",
                    "fork-child",
                    "--strategy",
                    "structured",
                ],
            )

        assert result.exit_code == 0, result.output
        assert "switched to transfer mode" in result.output
        assert mock_manager.fork_session.call_args.kwargs.get("resume_mode") == "transfer"
        kwargs = mock_invoke.call_args.kwargs
        assert kwargs.get("session_id") is not None
        assert len(kwargs["session_id"]) == 36  # UUID format
        assert kwargs.get("resume_id") is None
        assert kwargs.get("fork_session") is None

    def test_samedir_transfer_uses_fresh_session_id(self, runner: CliRunner, temp_env: Path) -> None:
        """Same-dir transfer launches a fresh child session with the assembled context as the
        append-system-prompt file, never a native parent resume."""
        parent, fork_state = self._samedir_parent_and_fork(temp_env)
        ctx = self._seed_context_file(temp_env, "# Parent transfer context\nSENTINEL-CTX\n")
        with (
            patch("forge.cli.session_fork.SessionManager") as mock_manager_cls,
            successful_claude_launch() as mock_invoke,
            patch(
                "forge.cli.session_fork._generate_parent_transfer_context",
                return_value=(ctx, []),
            ),
        ):
            mock_manager = mock_manager_cls.return_value
            mock_manager.get_session.return_value = parent
            mock_manager.fork_session.return_value = (parent, fork_state)
            result = runner.invoke(
                main,
                [
                    "session",
                    "fork",
                    "fork-parent",
                    "-n",
                    "fork-child",
                    "--resume-mode",
                    "transfer",
                ],
            )

        assert result.exit_code == 0, result.output
        kwargs = mock_invoke.call_args.kwargs
        assert kwargs.get("session_id") is not None
        assert kwargs.get("resume_id") is None
        assert kwargs.get("fork_session") is None
        prompt_file = kwargs.get("system_prompt_file")
        assert prompt_file is not None
        assert "SENTINEL-CTX" in Path(prompt_file).read_text()

    def test_samedir_native_default_unchanged(self, runner: CliRunner, temp_env: Path) -> None:
        """A plain same-dir fork (no transfer flags) still resumes the parent natively and does NOT
        auto-switch to transfer -- the unset --strategy default must not trigger the switch.
        """
        parent, fork_state = self._samedir_parent_and_fork(temp_env)
        with (
            patch("forge.cli.session_fork.SessionManager") as mock_manager_cls,
            successful_claude_launch() as mock_invoke,
        ):
            mock_manager = mock_manager_cls.return_value
            mock_manager.get_session.return_value = parent
            mock_manager.fork_session.return_value = (parent, fork_state)
            result = runner.invoke(main, ["session", "fork", "fork-parent", "-n", "fork-child"])

        assert result.exit_code == 0, result.output
        assert "switched to transfer mode" not in result.output
        kwargs = mock_invoke.call_args.kwargs
        assert kwargs.get("resume_id") == "parent-uuid"
        assert kwargs.get("fork_session") is True
        assert kwargs.get("session_id") is None
        assert mock_manager.fork_session.call_args.kwargs.get("resume_mode") is None

    def test_samedir_transfer_sidecar_registers_fork(self, runner: CliRunner, temp_env: Path) -> None:
        """Sidecar same-dir transfer: launch_claude_session gets a fresh session_id,
        fork_session=False, register_fork=True (the only thing setting FORGE_FORK_NAME when
        fork_session is False), and a non-None system_prompt_file."""
        from forge.core.ops.claude_session import ClaudeSessionLaunchResult

        parent, fork_state = self._samedir_parent_and_fork(temp_env, fork_launch_mode=LAUNCH_MODE_SIDECAR)
        ctx = self._seed_context_file(temp_env)
        launch_result = ClaudeSessionLaunchResult(
            exit_code=0,
            session=fork_state.name,
            manifest=fork_state,
            worktree_path=fork_state.worktree.path if fork_state.worktree else None,
            warnings=(),
            operation_started_at=datetime.now(UTC),
            routing_mode="proxy",
            proxy_id=None,
            base_url="http://localhost:8085",
            is_sandboxed=True,
            claude_project_root=(fork_state.worktree.path if fork_state.worktree else None),
            store_exists=True,
        )
        with (
            patch("forge.cli.session_fork.SessionManager") as mock_manager_cls,
            patch(
                "forge.cli.session_fork._generate_parent_transfer_context",
                return_value=(ctx, []),
            ),
            patch(
                "forge.core.ops.claude_session.launch_claude_session",
                return_value=launch_result,
            ) as mock_launch,
        ):
            mock_manager = mock_manager_cls.return_value
            mock_manager.get_session.return_value = parent
            mock_manager.fork_session.return_value = (parent, fork_state)
            result = runner.invoke(
                main,
                [
                    "session",
                    "fork",
                    "fork-parent",
                    "-n",
                    "fork-child",
                    "--resume-mode",
                    "transfer",
                ],
            )

        assert result.exit_code == 0, result.output
        assert mock_launch.called
        kwargs = mock_launch.call_args.kwargs
        assert kwargs.get("session_id") is not None
        assert len(kwargs["session_id"]) == 36
        assert kwargs.get("resume_id") is None
        assert kwargs.get("fork_session") is False
        assert kwargs.get("register_fork") is True
        assert kwargs.get("system_prompt_file") is not None

    def test_samedir_transfer_over_budget_blocks(self, runner: CliRunner, temp_env: Path) -> None:
        """A same-dir --strategy full fork (auto-switched to transfer) preflights the context budget
        and blocks an over-limit parent transcript without --force, before fork_session().
        """
        artifacts = temp_env / ".forge" / "artifacts" / "fork-parent" / "transcripts"
        artifacts.mkdir(parents=True)
        (artifacts / "large.jsonl").write_text("x" * 4096)

        parent = create_session_state(
            "fork-parent",
            proxy_template="litellm-openai",
            proxy_base_url="http://localhost:8085",
            worktree_path=str(temp_env),
            worktree_branch="main",
        )
        parent.confirmed.claude_session_id = "parent-uuid"
        parent.forge_root = str(temp_env)
        parent.confirmed.artifacts["transcripts"] = [
            {"copied_path": ".forge/artifacts/fork-parent/transcripts/large.jsonl"}
        ]

        with (
            patch("forge.cli.session_fork.SessionManager") as mock_manager_cls,
            patch("forge.cli.session_fork._resolve_context_limit", return_value=100),
            patch("forge.core.ops.claude_session.invoke_claude") as mock_invoke,
        ):
            mock_manager = mock_manager_cls.return_value
            mock_manager.get_session.return_value = parent
            result = runner.invoke(
                main,
                [
                    "session",
                    "fork",
                    "fork-parent",
                    "-n",
                    "fork-child",
                    "--strategy",
                    "full",
                ],
            )

        assert result.exit_code == 1
        assert "exceeds context limit" in result.output
        mock_manager.fork_session.assert_not_called()
        mock_invoke.assert_not_called()

    def test_samedir_explicit_resume_mode_transfer(self, runner: CliRunner, temp_env: Path) -> None:
        """Explicit --resume-mode transfer on a same-dir fork takes the transfer launch shape and
        does NOT print the native-relocate 'only applies' tip or the auto-switch info line (nothing
        was switched -- it was requested)."""
        parent, fork_state = self._samedir_parent_and_fork(temp_env)
        ctx = self._seed_context_file(temp_env)
        with (
            patch("forge.cli.session_fork.SessionManager") as mock_manager_cls,
            successful_claude_launch() as mock_invoke,
            patch(
                "forge.cli.session_fork._generate_parent_transfer_context",
                return_value=(ctx, []),
            ),
        ):
            mock_manager = mock_manager_cls.return_value
            mock_manager.get_session.return_value = parent
            mock_manager.fork_session.return_value = (parent, fork_state)
            result = runner.invoke(
                main,
                [
                    "session",
                    "fork",
                    "fork-parent",
                    "-n",
                    "fork-child",
                    "--resume-mode",
                    "transfer",
                ],
            )

        assert result.exit_code == 0, result.output
        assert "only applies to --worktree/--into" not in result.output
        assert "switched to transfer mode" not in result.output
        kwargs = mock_invoke.call_args.kwargs
        assert kwargs.get("session_id") is not None
        assert kwargs.get("resume_id") is None

    def test_samedir_transfer_inline_plan_embeds_text(self, runner: CliRunner, temp_env: Path) -> None:
        """--inline-plan on a same-dir fork auto-switches to transfer AND passes inline_plan=True plus
        the strategy into the shared assembly; the assembled context flows into the launch
        system_prompt_file. (Plan-text resolution itself is covered by test_transfer.py.)
        """
        parent, fork_state = self._samedir_parent_and_fork(temp_env)
        ctx = self._seed_context_file(temp_env, "# Context\nAPPROVED-PLAN-SENTINEL\n")
        captured: dict[str, object] = {}

        def _spy(
            *,
            manager,
            manifest,
            parent_state=None,
            strategy="structured",
            inline_plan=False,
        ):
            captured["strategy"] = strategy
            captured["inline_plan"] = inline_plan
            return ctx, []

        with (
            patch("forge.cli.session_fork.SessionManager") as mock_manager_cls,
            successful_claude_launch() as mock_invoke,
            patch(
                "forge.cli.session_fork._generate_parent_transfer_context",
                side_effect=_spy,
            ),
        ):
            mock_manager = mock_manager_cls.return_value
            mock_manager.get_session.return_value = parent
            mock_manager.fork_session.return_value = (parent, fork_state)
            result = runner.invoke(
                main,
                [
                    "session",
                    "fork",
                    "fork-parent",
                    "-n",
                    "fork-child",
                    "--inline-plan",
                    "--strategy",
                    "full",
                ],
            )

        assert result.exit_code == 0, result.output
        assert captured == {"strategy": "full", "inline_plan": True}
        prompt_file = mock_invoke.call_args.kwargs.get("system_prompt_file")
        assert prompt_file is not None
        assert "APPROVED-PLAN-SENTINEL" in Path(prompt_file).read_text()

    def test_native_relocate_warns_strategy_ignored(self, runner: CliRunner, temp_env: Path) -> None:
        parent, fork_state = self._nr_parent_and_fork(temp_env)
        with (
            patch("forge.cli.session_fork.SessionManager") as mock_manager_cls,
            successful_claude_launch(),
        ):
            mock_manager = mock_manager_cls.return_value
            mock_manager.get_session.return_value = parent
            mock_manager.fork_session.return_value = (parent, fork_state)
            result = runner.invoke(
                main,
                [
                    "session",
                    "fork",
                    "fork-parent",
                    "-n",
                    "fork-child",
                    "--worktree",
                    "--strategy",
                    "full",
                    "--resume-mode",
                    "native-relocate",
                ],
            )

        assert "ignored with --resume-mode native-relocate" in result.output

    def test_native_relocate_rolls_back_on_conflict(self, runner: CliRunner, temp_env: Path) -> None:
        """A relocation conflict rolls back the fork WITHOUT deleting the pre-existing transcript."""
        from forge.session.claude import RelocateConflictError

        parent, fork_state = self._nr_parent_and_fork(temp_env)
        with (
            patch("forge.cli.session_fork.SessionManager") as mock_manager_cls,
            patch(
                "forge.session.claude.relocate_transcript",
                side_effect=RelocateConflictError("dup"),
            ),
        ):
            mock_manager = mock_manager_cls.return_value
            mock_manager.get_session.return_value = parent
            mock_manager.fork_session.return_value = (parent, fork_state)
            result = runner.invoke(
                main,
                [
                    "session",
                    "fork",
                    "fork-parent",
                    "-n",
                    "fork-child",
                    "--worktree",
                    "--resume-mode",
                    "native-relocate",
                ],
            )

        assert result.exit_code != 0
        assert "already holds a different transcript" in result.output
        # Rollback must NOT delete transcripts: the conflicting dest file is the user's, and the
        # cleanup branch would otherwise unlink the exact file the conflict protected.
        mock_manager.delete_session.assert_called_once()
        assert mock_manager.delete_session.call_args.kwargs["delete_transcripts"] is False

    def test_native_relocate_rolls_back_on_io_error(self, runner: CliRunner, temp_env: Path) -> None:
        """A non-custom IO failure (e.g. PermissionError) rolls back the fork without a traceback."""
        parent, fork_state = self._nr_parent_and_fork(temp_env)
        with (
            patch("forge.cli.session_fork.SessionManager") as mock_manager_cls,
            patch(
                "forge.session.claude.relocate_transcript",
                side_effect=PermissionError("denied"),
            ),
        ):
            mock_manager = mock_manager_cls.return_value
            mock_manager.get_session.return_value = parent
            mock_manager.fork_session.return_value = (parent, fork_state)
            result = runner.invoke(
                main,
                [
                    "session",
                    "fork",
                    "fork-parent",
                    "-n",
                    "fork-child",
                    "--worktree",
                    "--resume-mode",
                    "native-relocate",
                ],
            )

        assert result.exit_code != 0
        # Clean exit (SystemExit), not an uncaught PermissionError traceback.
        assert isinstance(result.exception, SystemExit)
        assert "Could not relocate" in result.output
        mock_manager.delete_session.assert_called_once()
        assert mock_manager.delete_session.call_args.kwargs["delete_transcripts"] is False

    def test_sidecar_worktree_fork_injects_addendum_once(self, runner: CliRunner, temp_env: Path) -> None:
        """Sidecar worktree forks should combine context with one copy of the addendum."""
        parent = create_session_state(
            "fork-parent",
            proxy_template="litellm-openai",
            proxy_base_url="http://localhost:8085",
            worktree_path=str(temp_env),
            worktree_branch="main",
        )
        parent.confirmed.claude_session_id = "parent-uuid"

        fork_worktree = temp_env / "fork-child"
        fork_worktree.mkdir()
        fork_state = create_session_state(
            "fork-child",
            proxy_template="litellm-openai",
            proxy_base_url="http://localhost:8085",
            parent_session="fork-parent",
            is_fork=True,
            worktree_path=str(fork_worktree),
            worktree_branch="fork-child",
            launch_mode=LAUNCH_MODE_SIDECAR,
        )
        assert fork_state.worktree is not None
        fork_state.worktree.is_worktree = True
        fork_state.forge_root = str(fork_worktree)
        SessionStore(str(fork_worktree), "fork-child").write(fork_state)

        context_file = fork_worktree / ".forge" / "prev_sessions" / "fork-parent" / "children" / "fork-child.md"
        context_file.parent.mkdir(parents=True)
        context_file.write_text("# Parent context\n", encoding="utf-8")

        with (
            patch("forge.cli.session_fork.SessionManager") as mock_manager_cls,
            patch(
                "forge.cli.session_fork._resolve_routing_from_cli",
                return_value=_proxy_routing(),
            ),
            patch(
                "forge.config.loader.load_proxy_instance_config",
                return_value=_proxy_cfg(),
            ),
            patch(
                "forge.cli.session_fork._generate_parent_transfer_context",
                return_value=(context_file, []),
            ),
            patch("forge.sidecar.docker.is_docker_available", return_value=True),
            patch("forge.sidecar.get_secrets_for_template", return_value={}),
            patch("forge.sidecar.run_sidecar_session", return_value=0),
        ):
            mock_manager = mock_manager_cls.return_value
            mock_manager.fork_session.return_value = (parent, fork_state)

            result = runner.invoke(
                main,
                [
                    "session",
                    "fork",
                    "fork-parent",
                    "--name",
                    "fork-child",
                    "--worktree",
                    "--proxy",
                    "openai-proxy",
                ],
            )

        assert result.exit_code == 0, result.output
        combined = fork_worktree / ".forge" / "launch-context" / "fork-child.md"
        content = combined.read_text(encoding="utf-8")
        assert "# Parent context" in content
        assert content.count("# Tool Parameter Guidance") == 1

    def test_host_worktree_fork_injects_addendum_once(self, runner: CliRunner, temp_env: Path) -> None:
        """Host worktree forks should let the shared launcher own managed addendum composition."""
        parent = create_session_state(
            "fork-parent",
            proxy_template="litellm-openai",
            proxy_base_url="http://localhost:8085",
            worktree_path=str(temp_env),
            worktree_branch="main",
        )
        parent.confirmed.claude_session_id = "parent-uuid"

        fork_worktree = temp_env / "fork-child"
        fork_worktree.mkdir()
        fork_state = create_session_state(
            "fork-child",
            proxy_template="litellm-openai",
            proxy_base_url="http://localhost:8085",
            parent_session="fork-parent",
            is_fork=True,
            worktree_path=str(fork_worktree),
            worktree_branch="fork-child",
        )
        assert fork_state.worktree is not None
        fork_state.worktree.is_worktree = True
        fork_state.forge_root = str(fork_worktree)

        context_file = fork_worktree / ".forge" / "prev_sessions" / "fork-parent" / "children" / "fork-child.md"
        context_file.parent.mkdir(parents=True)
        context_file.write_text("# Parent context\n", encoding="utf-8")

        with (
            patch("forge.cli.session_fork.SessionManager") as mock_manager_cls,
            patch(
                "forge.cli.session_fork._resolve_routing_from_cli",
                return_value=_proxy_routing(),
            ),
            patch(
                "forge.config.loader.load_proxy_instance_config",
                return_value=_proxy_cfg(),
            ),
            patch(
                "forge.cli.session_fork._generate_parent_transfer_context",
                return_value=(context_file, []),
            ),
            successful_claude_launch() as mock_invoke,
        ):
            mock_manager = mock_manager_cls.return_value
            mock_manager.fork_session.return_value = (parent, fork_state)

            result = runner.invoke(
                main,
                [
                    "session",
                    "fork",
                    "fork-parent",
                    "--name",
                    "fork-child",
                    "--worktree",
                    "--proxy",
                    "openai-proxy",
                ],
            )

        assert result.exit_code == 0, result.output
        prompt_file = mock_invoke.call_args.kwargs["system_prompt_file"]
        content = Path(prompt_file).read_text(encoding="utf-8")
        assert "# Parent context" in content
        assert content.count("# Tool Parameter Guidance") == 1

    def test_fork_worktree_uses_nested_forge_roots_for_extension_inheritance(
        self, runner: CliRunner, temp_env: Path
    ) -> None:
        """Worktree forks should install inherited extensions at the child nested root."""
        parent_nested_root = temp_env / "packages" / "app"
        parent_nested_root.mkdir(parents=True)

        parent = create_session_state(
            "fork-parent",
            proxy_template="litellm-openai",
            proxy_base_url="http://localhost:8085",
            worktree_path=str(parent_nested_root),
            worktree_branch="main",
        )
        parent.confirmed.claude_session_id = "parent-uuid"
        parent.forge_root = str(parent_nested_root)

        fork_worktree = temp_env / "fork-child"
        fork_worktree.mkdir()
        child_nested_root = fork_worktree / "packages" / "app"
        child_nested_root.mkdir(parents=True)
        fork_state = create_session_state(
            "fork-child",
            proxy_template="litellm-openai",
            proxy_base_url="http://localhost:8085",
            parent_session="fork-parent",
            is_fork=True,
            worktree_path=str(fork_worktree),
            worktree_branch="fork-child",
        )
        assert fork_state.worktree is not None
        fork_state.worktree.is_worktree = True
        fork_state.forge_root = str(child_nested_root)

        with (
            patch("forge.cli.session_fork.SessionManager") as mock_manager_cls,
            patch("forge.core.ops.claude_session.invoke_claude") as mock_invoke,
            patch("forge.cli.session_fork._auto_install_extensions") as mock_auto,
            patch(
                "forge.cli.session_fork._generate_parent_transfer_context",
                return_value=(None, []),
            ),
        ):
            mock_manager = mock_manager_cls.return_value
            mock_manager.fork_session.return_value = (parent, fork_state)

            result = runner.invoke(
                main,
                [
                    "session",
                    "fork",
                    "fork-parent",
                    "--name",
                    "fork-child",
                    "--worktree",
                    "--no-launch",
                ],
            )

        assert result.exit_code == 0
        mock_invoke.assert_not_called()
        mock_auto.assert_called_once_with(
            install_root=child_nested_root,
            parent_project_root=parent_nested_root,
            force_extensions=None,
        )

    def test_fork_worktree_full_strategy_budget_uses_parent_forge_root(
        self, runner: CliRunner, temp_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Full-strategy preflight should read transcript artifacts from parent forge_root."""
        parent_nested_root = temp_env / "packages" / "app"
        parent_nested_root.mkdir(parents=True)
        (parent_nested_root / ".forge" / "artifacts" / "fork-parent" / "transcripts").mkdir(parents=True)
        monkeypatch.chdir(parent_nested_root)

        transcript_path = parent_nested_root / ".forge" / "artifacts" / "fork-parent" / "transcripts" / "large.jsonl"
        transcript_path.write_text("x" * 4096)

        parent = create_session_state(
            "fork-parent",
            proxy_template="litellm-openai",
            proxy_base_url="http://localhost:8085",
            worktree_path=str(parent_nested_root),
            worktree_branch="main",
        )
        parent.confirmed.claude_session_id = "parent-uuid"
        parent.forge_root = str(parent_nested_root)
        parent.confirmed.artifacts["transcripts"] = [
            {"copied_path": ".forge/artifacts/fork-parent/transcripts/large.jsonl"}
        ]

        with (
            patch("forge.cli.session_fork.SessionManager") as mock_manager_cls,
            patch("forge.cli.session_fork._resolve_context_limit", return_value=100),
            patch("forge.core.ops.claude_session.invoke_claude") as mock_invoke,
        ):
            mock_manager = mock_manager_cls.return_value
            mock_manager.get_session.return_value = parent
            mock_manager.resolve_project_root.return_value = str(temp_env)

            result = runner.invoke(
                main,
                [
                    "session",
                    "fork",
                    "fork-parent",
                    "--name",
                    "fork-child",
                    "--worktree",
                    "--strategy",
                    "full",
                ],
            )

        assert result.exit_code == 1
        assert "exceeds context limit" in result.output
        mock_manager.fork_session.assert_not_called()
        mock_invoke.assert_not_called()

    def test_fork_branch_implies_worktree(self, runner: CliRunner, temp_env: Path) -> None:
        """--branch automatically enables --worktree."""
        parent = create_session_state(
            "fork-parent",
            proxy_template="litellm-openai",
            proxy_base_url="http://localhost:8085",
            worktree_path=str(temp_env),
            worktree_branch="main",
        )
        parent.confirmed.claude_session_id = "parent-uuid"

        fork_worktree = temp_env / "fork-child"
        fork_worktree.mkdir()
        fork_state = create_session_state(
            "fork-child",
            proxy_template="litellm-openai",
            proxy_base_url="http://localhost:8085",
            parent_session="fork-parent",
            is_fork=True,
            worktree_path=str(fork_worktree),
            worktree_branch="custom-branch",
        )
        assert fork_state.worktree is not None
        fork_state.worktree.is_worktree = True

        with (
            patch("forge.cli.session_fork.SessionManager") as mock_manager_cls,
            successful_claude_launch(),
            patch(
                "forge.cli.session_fork._generate_parent_transfer_context",
                return_value=(None, []),
            ),
        ):
            mock_manager = mock_manager_cls.return_value
            mock_manager.fork_session.return_value = (parent, fork_state)

            result = runner.invoke(
                main,
                [
                    "session",
                    "fork",
                    "fork-parent",
                    "--name",
                    "fork-child",
                    "--branch",
                    "custom-branch",
                ],
            )

        assert result.exit_code == 0
        call_kwargs = mock_manager.fork_session.call_args.kwargs
        assert call_kwargs["create_worktree"] is True
        assert call_kwargs["branch"] == "custom-branch"

    def test_fork_worktree_requires_git_repo(self, runner: CliRunner, temp_env: Path) -> None:
        """Fork with --worktree requires a proper git repository."""
        with successful_claude_launch():
            runner.invoke(main, ["session", "start", "fork-parent"])

        result = runner.invoke(
            main,
            ["session", "fork", "fork-parent", "--name", "fork-child", "--worktree"],
        )

        assert result.exit_code == 1
        assert "git" in result.output.lower()

    def test_worktree_fork_never_attempts_resume(self, runner: CliRunner, temp_env: Path) -> None:
        """Worktree fork should never try --resume --fork-session (it can't work cross-project)."""
        parent = create_session_state(
            "fork-parent",
            proxy_template="litellm-openai",
            proxy_base_url="http://localhost:8085",
            worktree_path=str(temp_env),
            worktree_branch="main",
        )
        parent.confirmed.claude_session_id = "parent-uuid"

        fork_worktree = temp_env / "fork-child"
        fork_worktree.mkdir()
        fork = create_session_state(
            "fork-child",
            proxy_template="litellm-openai",
            proxy_base_url="http://localhost:8085",
            parent_session="fork-parent",
            is_fork=True,
            worktree_path=str(fork_worktree),
            worktree_branch="fork-child",
        )
        assert fork.worktree is not None
        fork.worktree.is_worktree = True

        with (
            patch("forge.cli.session_fork.SessionManager") as mock_manager_cls,
            successful_claude_launch() as mock_invoke,
            patch(
                "forge.cli.session_fork._generate_parent_transfer_context",
                return_value=(None, []),
            ),
        ):
            mock_manager = mock_manager_cls.return_value
            mock_manager.fork_session.return_value = (parent, fork)

            result = runner.invoke(
                main,
                [
                    "session",
                    "fork",
                    "fork-parent",
                    "--name",
                    "fork-child",
                    "--worktree",
                ],
            )

        assert result.exit_code == 0
        kwargs = mock_invoke.call_args.kwargs
        assert kwargs.get("resume_id") is None
        assert kwargs.get("fork_session") is None

    def test_fork_no_worktree_no_launch_tip_on_failure(self, runner: CliRunner, temp_env: Path) -> None:
        """Non-worktree fork failure should NOT show cross-worktree tip."""
        parent = create_session_state(
            "fork-parent",
            proxy_template="litellm-openai",
            proxy_base_url="http://localhost:8085",
            worktree_path=str(temp_env),
            worktree_branch="main",
        )
        parent.confirmed.claude_session_id = "parent-uuid"

        fork_state = create_session_state(
            "fork-child",
            proxy_template="litellm-openai",
            proxy_base_url="http://localhost:8085",
            parent_session="fork-parent",
            is_fork=True,
            worktree_path=str(temp_env),
        )

        with (
            patch("forge.cli.session_fork.SessionManager") as mock_manager_cls,
            patch("forge.core.ops.claude_session.invoke_claude", return_value=1),
        ):
            mock_manager = mock_manager_cls.return_value
            mock_manager.fork_session.return_value = (parent, fork_state)

            result = runner.invoke(main, ["session", "fork", "fork-parent", "--name", "fork-child"])

        assert result.exit_code == 1
        assert "forge session launch" not in result.output

    def test_fork_direct_flag_passes_to_manager(self, runner: CliRunner, temp_env: Path) -> None:
        """--no-proxy flag is forwarded to manager.fork_session."""
        parent = create_session_state(
            "fork-parent",
            proxy_template="litellm-openai",
            proxy_base_url="http://localhost:8085",
            worktree_path=str(temp_env),
            worktree_branch="main",
        )
        parent.confirmed.claude_session_id = "parent-uuid"

        # Manager returns a fork with no proxy (direct mode)
        fork_state = create_session_state(
            "fork-child",
            parent_session="fork-parent",
            is_fork=True,
            worktree_path=str(temp_env),
        )

        with (
            patch("forge.cli.session_fork.SessionManager") as mock_manager_cls,
            successful_claude_launch(),
        ):
            mock_manager = mock_manager_cls.return_value
            mock_manager.fork_session.return_value = (parent, fork_state)

            result = runner.invoke(
                main,
                [
                    "session",
                    "fork",
                    "fork-parent",
                    "--name",
                    "fork-child",
                    "--no-proxy",
                ],
            )

        assert result.exit_code == 0
        call_kwargs = mock_manager.fork_session.call_args.kwargs
        assert call_kwargs["parent_name"] == "fork-parent"
        assert call_kwargs["fork_name"] == "fork-child"
        assert call_kwargs["direct"] is True
        assert call_kwargs["is_incognito"] is False
        assert call_kwargs["create_worktree"] is False

    def test_fork_direct_uses_configured_model_override(self, runner: CliRunner, temp_env: Path) -> None:
        """Direct forks should honor the configured direct-model override."""
        parent = create_session_state(
            "fork-parent",
            proxy_template="litellm-openai",
            proxy_base_url="http://localhost:8085",
            worktree_path=str(temp_env),
            worktree_branch="main",
        )
        parent.confirmed.claude_session_id = "parent-uuid"

        fork_state = create_session_state(
            "fork-child",
            parent_session="fork-parent",
            is_fork=True,
            worktree_path=str(temp_env),
        )

        with (
            patch("forge.cli.session_fork.SessionManager") as mock_manager_cls,
            successful_claude_launch() as mock_invoke,
            patch(
                "forge.runtime_config.get_default_direct_model",
                return_value="claude-sonnet-4-6",
            ),
        ):
            mock_manager = mock_manager_cls.return_value
            mock_manager.fork_session.return_value = (parent, fork_state)

            result = runner.invoke(
                main,
                [
                    "session",
                    "fork",
                    "fork-parent",
                    "--name",
                    "fork-child",
                    "--no-proxy",
                ],
            )

        assert result.exit_code == 0
        assert mock_invoke.call_args is not None
        kwargs = mock_invoke.call_args.kwargs
        assert kwargs["model"] is None
        assert kwargs["env_vars"]["ANTHROPIC_MODEL"] == "sonnet"
        assert kwargs["env_vars"]["ANTHROPIC_DEFAULT_SONNET_MODEL"] == "claude-sonnet-4-6"

    def test_fork_no_launch_skips_claude(self, runner: CliRunner, temp_env: Path) -> None:
        """--no-launch should create fork without invoking Claude."""
        parent = create_session_state(
            "fork-parent",
            proxy_template="litellm-openai",
            proxy_base_url="http://localhost:8085",
            worktree_path=str(temp_env),
            worktree_branch="main",
        )
        parent.confirmed.claude_session_id = "parent-uuid"

        fork_state = create_session_state(
            "fork-child",
            proxy_template="litellm-openai",
            proxy_base_url="http://localhost:8085",
            parent_session="fork-parent",
            is_fork=True,
            worktree_path=str(temp_env),
        )

        with (
            patch("forge.cli.session_fork.SessionManager") as mock_manager_cls,
            patch("forge.core.ops.claude_session.invoke_claude") as mock_invoke,
        ):
            mock_manager = mock_manager_cls.return_value
            mock_manager.fork_session.return_value = (parent, fork_state)

            result = runner.invoke(
                main,
                [
                    "session",
                    "fork",
                    "fork-parent",
                    "--name",
                    "fork-child",
                    "--no-launch",
                ],
            )

        assert result.exit_code == 0
        assert "--no-launch" in result.output
        mock_invoke.assert_not_called()

    def test_fork_worktree_no_launch_generates_context_and_prints_tip(self, runner: CliRunner, temp_env: Path) -> None:
        """--worktree --no-launch should generate context and print cd tip."""
        parent = create_session_state(
            "fork-parent",
            proxy_template="litellm-openai",
            proxy_base_url="http://localhost:8085",
            worktree_path=str(temp_env),
            worktree_branch="main",
        )
        parent.confirmed.claude_session_id = "parent-uuid"

        fork_worktree = temp_env / "fork-child"
        fork_worktree.mkdir()
        fork_state = create_session_state(
            "fork-child",
            proxy_template="litellm-openai",
            proxy_base_url="http://localhost:8085",
            parent_session="fork-parent",
            is_fork=True,
            worktree_path=str(fork_worktree),
            worktree_branch="fork-child",
        )
        assert fork_state.worktree is not None
        fork_state.worktree.is_worktree = True

        context_file = fork_worktree / ".forge" / "prev_sessions" / "fork-parent" / "children" / "fork-child.md"
        context_file.parent.mkdir(parents=True)
        context_file.write_text("# Parent context\n")

        with (
            patch("forge.cli.session_fork.SessionManager") as mock_manager_cls,
            patch("forge.core.ops.claude_session.invoke_claude") as mock_invoke,
            patch(
                "forge.cli.session_fork._generate_parent_transfer_context",
                return_value=(context_file, []),
            ),
        ):
            mock_manager = mock_manager_cls.return_value
            mock_manager.fork_session.return_value = (parent, fork_state)

            result = runner.invoke(
                main,
                [
                    "session",
                    "fork",
                    "fork-parent",
                    "--name",
                    "fork-child",
                    "--worktree",
                    "--no-launch",
                ],
            )

        assert result.exit_code == 0
        assert "--no-launch" in result.output
        # Rich wraps long lines; normalize whitespace for assertions
        normalized = " ".join(result.output.split())
        assert "forge session resume fork-child" in normalized
        compact = "".join(result.output.split())
        assert f"cd{fork_worktree}&&forgesessionresumefork-child" in compact
        mock_invoke.assert_not_called()

    def test_fork_worktree_no_launch_tip_uses_nested_forge_root(self, runner: CliRunner, temp_env: Path) -> None:
        """Nested worktree forks should print the nested Forge root, not checkout root."""
        parent = create_session_state(
            "fork-parent",
            proxy_template="litellm-openai",
            proxy_base_url="http://localhost:8085",
            worktree_path=str(temp_env),
            worktree_branch="main",
        )
        parent.confirmed.claude_session_id = "parent-uuid"

        fork_worktree = temp_env / "fork-child"
        fork_worktree.mkdir()
        nested_root = fork_worktree / "experiments" / "drafting" / "iterative-drafting-poc"
        nested_root.mkdir(parents=True)
        fork_state = create_session_state(
            "fork-child",
            proxy_template="litellm-openai",
            proxy_base_url="http://localhost:8085",
            parent_session="fork-parent",
            is_fork=True,
            worktree_path=str(fork_worktree),
            worktree_branch="fork-child",
        )
        assert fork_state.worktree is not None
        fork_state.worktree.is_worktree = True
        fork_state.forge_root = str(nested_root)

        context_file = nested_root / ".forge" / "prev_sessions" / "fork-parent" / "children" / "fork-child.md"
        context_file.parent.mkdir(parents=True)
        context_file.write_text("# Parent context\n")

        with (
            patch("forge.cli.session_fork.SessionManager") as mock_manager_cls,
            patch("forge.core.ops.claude_session.invoke_claude") as mock_invoke,
            patch("forge.cli.session_fork._auto_install_extensions", return_value=False),
            patch(
                "forge.cli.session_fork._generate_parent_transfer_context",
                return_value=(context_file, []),
            ),
        ):
            mock_manager = mock_manager_cls.return_value
            mock_manager.fork_session.return_value = (parent, fork_state)

            result = runner.invoke(
                main,
                [
                    "session",
                    "fork",
                    "fork-parent",
                    "--name",
                    "fork-child",
                    "--worktree",
                    "--no-launch",
                ],
            )

        assert result.exit_code == 0
        normalized = " ".join(result.output.split())
        assert "forge session resume fork-child" in normalized
        compact = "".join(result.output.split())
        assert f"cd{nested_root}&&forgesessionresumefork-child" in compact
        mock_invoke.assert_not_called()

    def test_fork_worktree_post_exit_tip_uses_nested_forge_root(self, runner: CliRunner, temp_env: Path) -> None:
        """Host worktree forks should print the nested resume dir after Claude exits."""
        parent = create_session_state(
            "fork-parent",
            proxy_template="litellm-openai",
            proxy_base_url="http://localhost:8085",
            worktree_path=str(temp_env),
            worktree_branch="main",
        )
        parent.confirmed.claude_session_id = "parent-uuid"

        fork_worktree = temp_env / "fork-child"
        fork_worktree.mkdir()
        nested_root = fork_worktree / "experiments" / "drafting" / "iterative-drafting-poc"
        nested_root.mkdir(parents=True)
        fork_state = create_session_state(
            "fork-child",
            proxy_template="litellm-openai",
            proxy_base_url="http://localhost:8085",
            parent_session="fork-parent",
            is_fork=True,
            worktree_path=str(fork_worktree),
            worktree_branch="fork-child",
        )
        assert fork_state.worktree is not None
        fork_state.worktree.is_worktree = True
        fork_state.forge_root = str(nested_root)

        context_file = nested_root / ".forge" / "prev_sessions" / "fork-parent" / "children" / "fork-child.md"
        context_file.parent.mkdir(parents=True)
        context_file.write_text("# Parent context\n")

        with (
            patch("forge.cli.session_fork.SessionManager") as mock_manager_cls,
            successful_claude_launch(),
            patch(
                "forge.core.ops.claude_session.run_with_active_session",
                side_effect=lambda runner, **kw: runner(),
            ),
            patch("forge.cli.session_lifecycle._warn_if_hooks_missing"),
            patch("forge.cli.session_lifecycle._warn_if_version_outdated"),
            patch("forge.cli.session_fork._auto_install_extensions", return_value=False),
            patch(
                "forge.cli.session_fork._generate_parent_transfer_context",
                return_value=(context_file, []),
            ),
        ):
            mock_manager = mock_manager_cls.return_value
            mock_manager.fork_session.return_value = (parent, fork_state)

            result = runner.invoke(
                main,
                [
                    "session",
                    "fork",
                    "fork-parent",
                    "--name",
                    "fork-child",
                    "--worktree",
                ],
            )

        assert result.exit_code == 0
        normalized = " ".join(result.output.replace("\x1b[2K", "").split())
        assert "Reconnect to this conversation with:" in normalized
        compact = "".join(result.output.replace("\x1b[2K", "").split())
        assert f"cd{nested_root}&&forgesessionresumefork-child" in compact


class TestSessionForkIntoPreflight:
    """Tests for --into cross-repo preflight validation."""

    def test_into_nested_incompatible_target_refuses_before_proxy_or_fork(
        self, runner: CliRunner, temp_env: Path
    ) -> None:
        parent = create_session_state("planner", worktree_path=str(temp_env), worktree_branch="main")
        into_dir = temp_env / "existing-wt"
        target_root = into_dir / "packages" / "app"
        (target_root / ".forge").mkdir(parents=True)
        (target_root / ".forge" / "project.toml").write_text(
            'schema_version = 1\nrequired_forge = ">=9999"\n', encoding="utf-8"
        )
        common_git = str(temp_env / ".git")

        def fake_git_run(cmd, **kwargs):
            from unittest.mock import MagicMock

            result = MagicMock(returncode=0)
            if "--show-toplevel" in cmd:
                result.stdout = str(into_dir)
            elif "--git-common-dir" in cmd:
                result.stdout = common_git
            elif "--abbrev-ref" in cmd:
                result.stdout = "feat-branch"
            else:
                result.stdout = ""
            return result

        with (
            patch("forge.cli.session_fork.SessionManager") as manager_cls,
            patch("subprocess.run", side_effect=fake_git_run),
            patch("forge.cli.session_fork._resolve_routing_from_cli") as resolve_routing,
        ):
            manager = manager_cls.return_value
            manager.get_session.return_value = parent
            manager.index_store.get_session.return_value = SimpleNamespace(relative_path="packages/app")

            result = runner.invoke(
                main,
                ["session", "fork", "planner", "--into", str(into_dir), "--proxy", "test-proxy"],
            )

        assert result.exit_code == 1
        assert ">=9999" in result.output
        assert "running Forge" in result.output
        assert str(target_root / ".forge" / "project.toml") in result.output
        resolve_routing.assert_not_called()
        manager.fork_session.assert_not_called()

    def test_into_cross_repo_rejected_before_fork(self, runner: CliRunner, temp_env: Path) -> None:
        """--into targeting a different repo should fail before fork_session() is called."""
        parent = create_session_state(
            "planner",
            worktree_path=str(temp_env),
            worktree_branch="main",
        )

        into_dir = temp_env / "other-worktree"
        into_dir.mkdir()

        with (
            patch("forge.cli.session_fork.SessionManager") as mock_manager_cls,
            # Simulate --into target resolving to a real git checkout
            patch("subprocess.run") as mock_run,
        ):
            mock_manager = mock_manager_cls.return_value
            mock_manager.get_session.return_value = parent

            def fake_git_run(cmd, **kwargs):
                """Return different git-common-dir for target vs parent."""
                from unittest.mock import MagicMock

                result = MagicMock()
                result.returncode = 0
                git_c_path = cmd[cmd.index("-C") + 1] if "-C" in cmd else None
                if "--show-toplevel" in cmd:
                    result.stdout = str(into_dir)
                elif "--git-common-dir" in cmd:
                    if git_c_path and str(into_dir) in git_c_path:
                        result.stdout = "/repos/other-repo/.git"
                    else:
                        result.stdout = str(temp_env / ".git")
                elif "--abbrev-ref" in cmd:
                    result.stdout = "some-branch"
                else:
                    result.stdout = ""
                return result

            mock_run.side_effect = fake_git_run

            result = runner.invoke(
                main,
                ["session", "fork", "planner", "--into", str(into_dir)],
            )

        assert result.exit_code != 0
        assert "not part of the same repository" in result.output
        # fork_session should never have been called
        mock_manager.fork_session.assert_not_called()

    def test_into_same_repo_passes_preflight(self, runner: CliRunner, temp_env: Path) -> None:
        """--into targeting the same repo should pass preflight and reach fork_session()."""
        parent = create_session_state(
            "planner",
            worktree_path=str(temp_env),
            worktree_branch="main",
        )
        parent.confirmed.claude_session_id = "uuid-parent"

        fork_state = create_session_state(
            "reviewer",
            parent_session="planner",
            is_fork=True,
            worktree_path=str(temp_env / "wt"),
        )

        into_dir = temp_env / "existing-wt"
        into_dir.mkdir()

        common_git = str(temp_env / ".git")

        with (
            patch("forge.cli.session_fork.SessionManager") as mock_manager_cls,
            successful_claude_launch(),
            patch("subprocess.run") as mock_run,
        ):
            mock_manager = mock_manager_cls.return_value
            mock_manager.get_session.return_value = parent
            mock_manager.fork_session.return_value = (parent, fork_state)

            def fake_git_run(cmd, **kwargs):
                from unittest.mock import MagicMock

                result = MagicMock()
                result.returncode = 0
                if "--show-toplevel" in cmd:
                    result.stdout = str(into_dir)
                elif "--git-common-dir" in cmd:
                    # Same repo for both target and parent
                    result.stdout = common_git
                elif "--abbrev-ref" in cmd:
                    result.stdout = "feat-branch"
                else:
                    result.stdout = ""
                return result

            mock_run.side_effect = fake_git_run

            result = runner.invoke(
                main,
                ["session", "fork", "planner", "--into", str(into_dir), "--no-launch"],
            )

        assert "not part of the same repository" not in result.output
        # fork_session should have been called
        mock_manager.fork_session.assert_called_once()

    def test_into_skip_extension_check_uses_nested_target_root(self, runner: CliRunner, temp_env: Path) -> None:
        """Existing local installs should be detected at the target nested Forge root."""
        parent_nested_root = temp_env / "packages" / "app"
        parent_nested_root.mkdir(parents=True)

        parent = create_session_state(
            "planner",
            proxy_template="litellm-openai",
            proxy_base_url="http://localhost:8085",
            worktree_path=str(parent_nested_root),
            worktree_branch="main",
        )
        parent.confirmed.claude_session_id = "uuid-parent"
        parent.forge_root = str(parent_nested_root)

        into_dir = temp_env / "existing-wt"
        into_dir.mkdir()
        child_nested_root = into_dir / "packages" / "app"
        child_nested_root.mkdir(parents=True)

        fork_state = create_session_state(
            "reviewer",
            proxy_template="litellm-openai",
            proxy_base_url="http://localhost:8085",
            parent_session="planner",
            is_fork=True,
            worktree_path=str(into_dir),
            worktree_branch="reviewer",
        )
        assert fork_state.worktree is not None
        fork_state.worktree.is_worktree = True
        fork_state.forge_root = str(child_nested_root)

        common_git = str(temp_env / ".git")

        with (
            patch("forge.cli.session_fork.SessionManager") as mock_manager_cls,
            patch("forge.core.ops.claude_session.invoke_claude") as mock_invoke,
            patch("forge.cli.session_fork._auto_install_extensions") as mock_auto,
            patch(
                "forge.cli.session_fork._generate_parent_transfer_context",
                return_value=(None, []),
            ),
            patch("forge.install.tracking.TrackingStore") as mock_tracking_cls,
            patch("subprocess.run") as mock_run,
        ):
            mock_manager = mock_manager_cls.return_value
            mock_manager.get_session.return_value = parent
            mock_manager.fork_session.return_value = (parent, fork_state)

            tracking_store = mock_tracking_cls.return_value
            tracking_store.get_installation.side_effect = lambda scope, path=None: (
                object() if scope == "local" and path == str(child_nested_root) else None
            )

            def fake_git_run(cmd, **kwargs):
                from unittest.mock import MagicMock

                result = MagicMock()
                result.returncode = 0
                if "--show-toplevel" in cmd:
                    result.stdout = str(into_dir)
                elif "--git-common-dir" in cmd:
                    result.stdout = common_git
                elif "--abbrev-ref" in cmd:
                    result.stdout = "reviewer"
                else:
                    result.stdout = ""
                return result

            mock_run.side_effect = fake_git_run

            result = runner.invoke(
                main,
                [
                    "session",
                    "fork",
                    "planner",
                    "--name",
                    "reviewer",
                    "--into",
                    str(into_dir),
                    "--no-launch",
                ],
            )

        assert result.exit_code == 0
        tracking_store.get_installation.assert_any_call("local", str(child_nested_root))
        mock_auto.assert_not_called()
        mock_invoke.assert_not_called()
