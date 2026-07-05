"""Tests for session start, delete, incognito, and help CLI commands."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

import forge.cli.session as session_cli
from forge.cli.main import main
from forge.session import IndexStore, SessionManager, SessionStore, create_session_state
from forge.session.active import ActiveSessionStore
from forge.session.config import LAUNCH_MODE_HOST
from forge.session.exceptions import DirtyWorktreeError, SessionNotFoundError
from tests.src.cli.session_command_support import (
    _proxy_cfg,
    _proxy_routing,
    _seed_scoped_duplicate_sessions,
    successful_claude_launch,
)


class TestSessionStart:
    """Tests for 'forge session start' command."""

    def test_start_creates_session(self, runner: CliRunner, temp_env: Path) -> None:
        """Should create a new session."""
        with successful_claude_launch():
            result = runner.invoke(main, ["session", "start", "new-session"])

        assert result.exit_code == 0
        assert "Created session" in result.output
        assert "new-session" in result.output

    def test_start_tracks_active_session_during_launch(self, runner: CliRunner, temp_env: Path) -> None:
        """Active-session registry should be present during launch and cleared after exit."""
        captured: dict[str, str | bool | None] = {}

        def fake_invoke(*_args, **_kwargs):
            entry = ActiveSessionStore().get_session("tracked-start")
            captured["was_active"] = entry is not None
            captured["session_id"] = entry.claude_session_id if entry else None
            return 0

        with patch("forge.core.ops.claude_session.invoke_claude", side_effect=fake_invoke):
            result = runner.invoke(main, ["session", "start", "tracked-start"])

        assert result.exit_code == 0
        assert captured["was_active"] is True
        assert isinstance(captured["session_id"], str)
        assert ActiveSessionStore().get_session("tracked-start") is None

    def test_start_defaults_to_direct(self, runner: CliRunner, temp_env: Path) -> None:
        """No flags should default to direct mode."""
        result = runner.invoke(main, ["session", "start", "direct-default", "--no-launch"])

        assert result.exit_code == 0
        assert "Routing: direct" in result.output

        manager = SessionManager()
        manifest = manager.get_session_store("direct-default").read()
        assert manifest.intent.proxy is None

    def test_start_direct_creates_session_without_proxy(self, runner: CliRunner, temp_env: Path) -> None:
        """--no-proxy should create a session with no proxy intent."""
        result = runner.invoke(main, ["session", "start", "direct-test", "--no-proxy", "--no-launch"])

        assert result.exit_code == 0
        assert "Routing: direct" in result.output

        manager = SessionManager()
        manifest = manager.get_session_store("direct-test").read()
        assert manifest.intent.proxy is None

    def test_start_worktree_uses_nested_forge_roots_for_extension_inheritance(
        self, runner: CliRunner, temp_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Nested Forge projects should inherit/install extensions at nested roots."""
        parent_nested_root = temp_env / "packages" / "app"
        parent_nested_root.mkdir(parents=True)
        (parent_nested_root / ".forge").mkdir()
        monkeypatch.chdir(parent_nested_root)

        worktree_root = temp_env / "wt-nested"
        worktree_root.mkdir()
        child_nested_root = worktree_root / "packages" / "app"
        child_nested_root.mkdir(parents=True)

        manifest = create_session_state(
            "wt-nested",
            proxy_template="litellm-openai",
            proxy_base_url="http://localhost:8085",
            worktree_path=str(worktree_root),
            worktree_branch="wt-nested",
        )
        assert manifest.worktree is not None
        manifest.worktree.is_worktree = True
        manifest.forge_root = str(child_nested_root)

        with (
            patch("forge.cli.session_lifecycle.SessionManager") as mock_manager_cls,
            patch("forge.cli.session_lifecycle._auto_install_extensions") as mock_auto,
        ):
            mock_manager = mock_manager_cls.return_value
            mock_manager.start_session.return_value = manifest

            result = runner.invoke(main, ["session", "start", "wt-nested", "--worktree", "--no-launch"])

        assert result.exit_code == 0
        mock_auto.assert_called_once_with(
            install_root=child_nested_root,
            parent_project_root=parent_nested_root,
            force_extensions=None,
        )

    def test_start_with_model(self, runner: CliRunner, temp_env: Path) -> None:
        """--model pins direct Claude sessions through env vars."""
        with successful_claude_launch() as mock_invoke:
            result = runner.invoke(main, ["session", "start", "model-test", "--model", "opus-4-8"])

        assert result.exit_code == 0
        assert mock_invoke.call_args is not None
        kwargs = mock_invoke.call_args.kwargs
        assert kwargs["model"] is None
        assert kwargs["env_vars"]["ANTHROPIC_MODEL"] == "opus"
        assert kwargs["env_vars"]["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "claude-opus-4-8"

        state = SessionStore(str(temp_env), "model-test").read()
        assert state.intent.launch is not None
        assert state.intent.launch.direct_model == "claude-opus-4-8"

    def test_start_with_proxy_injects_model_addendum(self, runner: CliRunner, temp_env: Path) -> None:
        """Proxy-routed managed launches append the model-family prompt addendum."""
        with (
            patch(
                "forge.cli.session_lifecycle._resolve_routing_from_cli",
                return_value=_proxy_routing(),
            ),
            patch(
                "forge.config.loader.load_proxy_instance_config",
                return_value=_proxy_cfg(),
            ),
            successful_claude_launch() as mock_invoke,
        ):
            result = runner.invoke(main, ["session", "start", "addendum-start", "--proxy", "openai-proxy"])

        assert result.exit_code == 0, result.output
        prompt_file = mock_invoke.call_args.kwargs["system_prompt_file"]
        assert prompt_file is not None
        prompt_content = Path(prompt_file).read_text(encoding="utf-8")
        assert "Tool Parameter Guidance" in prompt_content
        assert "pages" in prompt_content

    def test_start_with_large_context_proxy_sets_claude_context_defaults(
        self, runner: CliRunner, temp_env: Path
    ) -> None:
        """Large-context proxy launches tell Claude Code to use 1M Claude aliases locally."""
        routing = session_cli.ResolvedRouting(
            template="openrouter-gemini",
            base_url="http://localhost:8097",
            proxy_id="gemini-proxy",
            context_limit=1048576,
        )
        with (
            patch(
                "forge.cli.session_lifecycle._resolve_routing_from_cli",
                return_value=routing,
            ),
            patch(
                "forge.config.loader.load_proxy_instance_config",
                return_value=_proxy_cfg(),
            ),
            successful_claude_launch() as mock_invoke,
        ):
            result = runner.invoke(
                main,
                ["session", "start", "proxy-context", "--proxy", "openrouter-gemini"],
            )

        assert result.exit_code == 0, result.output
        env_vars = mock_invoke.call_args.kwargs["env_vars"]
        assert env_vars["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] == "1048576"
        assert env_vars["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "claude-opus-4-8[1m]"
        assert env_vars["ANTHROPIC_DEFAULT_SONNET_MODEL"] == "claude-sonnet-5[1m]"
        assert "ANTHROPIC_MODEL" not in env_vars

    def test_start_with_model_no_launch_stores_normalized_pin(self, runner: CliRunner, temp_env: Path) -> None:
        result = runner.invoke(
            main,
            [
                "session",
                "start",
                "model-no-launch",
                "--model",
                "claude-opus-4-8[1m]",
                "--no-launch",
            ],
        )

        assert result.exit_code == 0
        state = SessionStore(str(temp_env), "model-no-launch").read()
        assert state.intent.launch is not None
        assert state.intent.launch.direct_model == "claude-opus-4-8[1m]"

    def test_start_with_sonnet_model_sets_sonnet_env(self, runner: CliRunner, temp_env: Path) -> None:
        with successful_claude_launch() as mock_invoke:
            result = runner.invoke(
                main,
                [
                    "session",
                    "start",
                    "sonnet-model",
                    "--model",
                    "claude-sonnet-4-6[1m]",
                ],
            )

        assert result.exit_code == 0
        kwargs = mock_invoke.call_args.kwargs
        assert kwargs["env_vars"]["ANTHROPIC_MODEL"] == "sonnet"
        assert kwargs["env_vars"]["ANTHROPIC_DEFAULT_SONNET_MODEL"] == "claude-sonnet-4-6[1m]"

    def test_start_with_model_accepts_subprocess_proxy(self, runner: CliRunner, temp_env: Path) -> None:
        with successful_claude_launch() as mock_invoke:
            result = runner.invoke(
                main,
                [
                    "session",
                    "start",
                    "model-subprocess",
                    "--model",
                    "opus-4-8",
                    "--subprocess-proxy",
                    "openrouter-anthropic",
                ],
            )

        assert result.exit_code == 0
        kwargs = mock_invoke.call_args.kwargs
        assert kwargs["env_vars"]["FORGE_SUBPROCESS_PROXY"] == "openrouter-anthropic"
        assert kwargs["env_vars"]["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "claude-opus-4-8"

    @pytest.mark.parametrize("flag", ["--sidecar", "--host-proxy"])
    def test_start_with_model_rejects_sidecar_and_host_proxy(
        self,
        runner: CliRunner,
        temp_env: Path,
        flag: str,
    ) -> None:
        args = ["session", "start", "bad-model", "--model", "opus-4-8", flag]

        result = runner.invoke(main, args)

        assert result.exit_code == 1
        assert "--model" in result.output

    def test_start_with_unknown_model_rejects_before_create(self, runner: CliRunner, temp_env: Path) -> None:
        result = runner.invoke(main, ["session", "start", "bad-model", "--model", "claude-opus-4.8.1"])

        assert result.exit_code == 1
        assert "Unknown direct Claude model" in result.output
        assert not SessionStore(str(temp_env), "bad-model").exists()

    def test_start_with_model_and_proxy_validates_alternatives(self, runner: CliRunner, temp_env: Path) -> None:
        """--model + --proxy should validate that the proxy has model_alternatives for the model."""
        from forge.config.schema import ProxyInstanceConfig, TierModels

        proxy_cfg = ProxyInstanceConfig(
            proxy_format=1,
            template="openrouter-anthropic",
            template_digest="abc",
            provider="openrouter",
            proxy_endpoint="http://localhost:8095",
            port=8095,
            upstream_base_url="https://openrouter.ai/api/v1",
            tiers=TierModels(haiku="h", sonnet="s", opus="o"),
            model_alternatives={"opus": {"claude-opus-4-8": "anthropic/claude-opus-4.8"}},
        )
        routing = session_cli.ResolvedRouting(
            template="openrouter-anthropic",
            base_url="http://localhost:8095",
            proxy_id="test-or-proxy",
        )
        with (
            patch(
                "forge.cli.session_lifecycle._resolve_routing_from_cli",
                return_value=routing,
            ),
            patch("forge.config.loader.load_proxy_instance_config", return_value=proxy_cfg),
            successful_claude_launch() as mock_invoke,
        ):
            result = runner.invoke(
                main,
                [
                    "session",
                    "start",
                    "model-proxy-ok",
                    "--proxy",
                    "test-or-proxy",
                    "--model",
                    "claude-opus-4-8",
                ],
            )

        assert result.exit_code == 0, result.output
        env_vars = mock_invoke.call_args.kwargs["env_vars"]
        assert env_vars["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "claude-opus-4-8"

    def test_start_with_model_and_proxy_rejects_unconfigured_alternative(
        self, runner: CliRunner, temp_env: Path
    ) -> None:
        """--model + --proxy should error when the proxy has no matching alternative."""
        from forge.config.schema import ProxyInstanceConfig, TierModels

        proxy_cfg = ProxyInstanceConfig(
            proxy_format=1,
            template="openrouter-openai",
            template_digest="abc",
            provider="openrouter",
            proxy_endpoint="http://localhost:8096",
            port=8096,
            upstream_base_url="https://openrouter.ai/api/v1",
            tiers=TierModels(haiku="h", sonnet="s", opus="o"),
        )
        routing = session_cli.ResolvedRouting(
            template="openrouter-openai",
            base_url="http://localhost:8096",
            proxy_id="test-or-openai",
        )
        with (
            patch(
                "forge.cli.session_lifecycle._resolve_routing_from_cli",
                return_value=routing,
            ),
            patch("forge.config.loader.load_proxy_instance_config", return_value=proxy_cfg),
        ):
            result = runner.invoke(
                main,
                [
                    "session",
                    "start",
                    "model-proxy-bad",
                    "--proxy",
                    "test-or-openai",
                    "--model",
                    "claude-opus-4-8",
                ],
            )

        assert result.exit_code == 1
        assert "does not configure model alternative" in result.output

    def test_start_duplicate_fails(self, runner: CliRunner, temp_env: Path) -> None:
        """Should fail when session already exists."""
        with successful_claude_launch():
            runner.invoke(main, ["session", "start", "duplicate-test"])

        with successful_claude_launch():
            result = runner.invoke(main, ["session", "start", "duplicate-test"])

        assert result.exit_code == 1
        assert "already exists" in result.output
        assert "Tip:" in result.output
        assert "forge session resume duplicate-test" in result.output
        assert "forge session delete duplicate-test" in result.output

    def test_start_without_name_auto_generates(self, runner: CliRunner, temp_env: Path) -> None:
        """Should auto-generate a name when none provided."""
        with (
            patch(
                "forge.cli.session_lifecycle.generate_unique_name",
                return_value="auto-test-session",
            ),
            successful_claude_launch(),
        ):
            result = runner.invoke(main, ["session", "start"])

        assert result.exit_code == 0
        assert "auto-test-session" in result.output

    def test_start_without_name_direct(self, runner: CliRunner, temp_env: Path) -> None:
        """Auto-name should work with --no-proxy flag."""
        with patch(
            "forge.cli.session_lifecycle.generate_unique_name",
            return_value="auto-direct",
        ):
            result = runner.invoke(main, ["session", "start", "--no-proxy", "--no-launch"])

        assert result.exit_code == 0
        assert "auto-direct" in result.output
        assert "Routing: direct" in result.output

    def test_start_help_shows_optional_name(self, runner: CliRunner) -> None:
        """Click should render [NAME] for optional argument."""
        result = runner.invoke(main, ["session", "start", "--help"])

        assert result.exit_code == 0
        assert "[NAME]" in result.output
        assert "[1m]" not in result.output
        assert "claude-sonnet-4-6)" in result.output

    def test_start_sidecar_persists_launch_preferences(self, runner: CliRunner, temp_env: Path) -> None:
        """Sidecar start should persist relaunch image/mount settings."""
        result = runner.invoke(
            main,
            [
                "session",
                "start",
                "sidecar-test",
                "--sidecar",
                "--mount",
                "/data:/mnt/data:ro",
                "--image",
                "forge-sidecar:test",
                "--no-launch",
            ],
        )

        assert result.exit_code == 0

        manager = SessionManager()
        manifest = manager.get_session_store("sidecar-test").read()
        assert manifest.intent.launch is not None
        assert manifest.intent.launch.mode == "sidecar"
        assert manifest.intent.launch.sidecar is not None
        assert manifest.intent.launch.sidecar.mounts == ["/data:/mnt/data:ro"]
        assert manifest.intent.launch.sidecar.image == "forge-sidecar:test"


class TestSessionDelete:
    """Tests for 'forge session delete' command."""

    def test_delete_removes_session(self, runner: CliRunner, temp_env: Path) -> None:
        """Should delete the session."""
        with successful_claude_launch():
            runner.invoke(main, ["session", "start", "delete-test"])

        result = runner.invoke(main, ["session", "delete", "delete-test", "--yes"])

        assert result.exit_code == 0
        assert "Deleted session" in result.output

    def test_delete_nonexistent_fails(self, runner: CliRunner, temp_env: Path) -> None:
        """Should fail for nonexistent session."""
        result = runner.invoke(main, ["session", "delete", "nonexistent", "--yes"])

        assert result.exit_code == 1
        assert "not found" in result.output

    def test_delete_prompts_without_yes(self, runner: CliRunner, temp_env: Path) -> None:
        """Should prompt for confirmation without --yes."""
        with successful_claude_launch():
            runner.invoke(main, ["session", "start", "confirm-test"])

        # Simulate 'n' response to confirmation
        result = runner.invoke(main, ["session", "delete", "confirm-test"], input="n\n")

        assert "Cancelled" in result.output

    def test_delete_blocks_active_session_without_force(self, runner: CliRunner, temp_env: Path) -> None:
        """A live session is blocked before the confirm prompt unless --force."""
        runner.invoke(main, ["session", "start", "active-delete", "--no-launch"])
        ActiveSessionStore().upsert_session(
            "active-delete",
            worktree_path=str(temp_env),
            launch_mode=LAUNCH_MODE_HOST,
            launcher_pid=os.getpid(),
            claude_session_id="uuid-live-123",
        )

        result = runner.invoke(main, ["session", "delete", "active-delete"])

        assert result.exit_code == 1
        assert "appears to still be active" in result.output
        assert "still running in Claude Code" in result.output
        assert "--force" in result.output
        # Blocked before the confirmation prompt; session not deleted.
        assert "Are you sure" not in result.output
        assert "Deleted session" not in result.output

    def test_delete_yes_blocks_active_without_force(self, runner: CliRunner, temp_env: Path) -> None:
        """--yes alone no longer deletes a live session; --force is required."""
        runner.invoke(main, ["session", "start", "forced-active-delete", "--no-launch"])
        ActiveSessionStore().upsert_session(
            "forced-active-delete",
            worktree_path=str(temp_env),
            launch_mode=LAUNCH_MODE_HOST,
            launcher_pid=os.getpid(),
        )

        result = runner.invoke(main, ["session", "delete", "forced-active-delete", "--yes"])

        assert result.exit_code == 1
        assert "appears to still be active" in result.output
        assert "--force" in result.output
        assert "Deleted session" not in result.output

    def test_delete_force_deletes_active_session(self, runner: CliRunner, temp_env: Path) -> None:
        """--force overrides the active-session guard and deletes (warning stays informational)."""
        runner.invoke(main, ["session", "start", "force-active", "--no-launch"])
        ActiveSessionStore().upsert_session(
            "force-active",
            worktree_path=str(temp_env),
            launch_mode=LAUNCH_MODE_HOST,
            launcher_pid=os.getpid(),
        )

        result = runner.invoke(main, ["session", "delete", "force-active", "--yes", "--force"])

        assert result.exit_code == 0
        assert "appears to still be active" in result.output
        assert "Deleted session" in result.output

    def test_delete_orphan_blocks_active_session_without_force(self, runner: CliRunner, temp_env: Path) -> None:
        """A live session whose index entry is gone (orphan dir) is still blocked unless --force."""
        from forge.core.ops.context import _cwd_forge_root
        from forge.session.index import IndexStore

        runner.invoke(main, ["session", "start", "orphan-live", "--no-launch"])
        fr = _cwd_forge_root()
        ActiveSessionStore().upsert_session(
            "orphan-live",
            worktree_path=fr or str(temp_env),
            forge_root=fr,
            launch_mode=LAUNCH_MODE_HOST,
            launcher_pid=os.getpid(),
        )
        # Drop the index entry, leaving the dir on disk + a live active entry.
        IndexStore().remove_session("orphan-live")

        result = runner.invoke(main, ["session", "delete", "orphan-live"])

        assert result.exit_code == 1
        assert "still running in Claude Code" in result.output
        # Orphan cleanup must NOT run while the launch is live.
        assert "Cleaned up orphaned" not in result.output

    def test_delete_orphan_force_deletes_active_session(self, runner: CliRunner, temp_env: Path) -> None:
        """--force lets orphan cleanup remove a live session's directory."""
        from forge.core.ops.context import _cwd_forge_root
        from forge.session.index import IndexStore

        runner.invoke(main, ["session", "start", "orphan-force", "--no-launch"])
        fr = _cwd_forge_root()
        ActiveSessionStore().upsert_session(
            "orphan-force",
            worktree_path=fr or str(temp_env),
            forge_root=fr,
            launch_mode=LAUNCH_MODE_HOST,
            launcher_pid=os.getpid(),
        )
        IndexStore().remove_session("orphan-force")

        result = runner.invoke(main, ["session", "delete", "orphan-force", "--yes", "--force"])

        assert result.exit_code == 0
        assert "Cleaned up orphaned" in result.output

    def test_delete_all_skips_active_sessions_without_force(self, runner: CliRunner, temp_env: Path) -> None:
        """--all skips live sessions (deletes the rest) unless --force is given."""
        runner.invoke(main, ["session", "start", "idle-one", "--no-launch"])
        runner.invoke(main, ["session", "start", "live-one", "--no-launch"])
        ActiveSessionStore().upsert_session(
            "live-one",
            worktree_path=str(temp_env),
            launch_mode=LAUNCH_MODE_HOST,
            launcher_pid=os.getpid(),
        )

        result = runner.invoke(main, ["session", "delete", "--all", "--yes"])

        assert result.exit_code == 0
        assert "Skipping" in result.output
        assert "live-one" in result.output
        assert "--force" in result.output

        list_result = runner.invoke(main, ["session", "list"])
        assert "idle-one" not in list_result.output
        assert "live-one" in list_result.output

    def test_delete_all_force_deletes_active_sessions(self, runner: CliRunner, temp_env: Path) -> None:
        """--all --force deletes live sessions too."""
        runner.invoke(main, ["session", "start", "live-a", "--no-launch"])
        runner.invoke(main, ["session", "start", "live-b", "--no-launch"])
        for nm in ("live-a", "live-b"):
            ActiveSessionStore().upsert_session(
                nm,
                worktree_path=str(temp_env),
                launch_mode=LAUNCH_MODE_HOST,
                launcher_pid=os.getpid(),
            )

        result = runner.invoke(main, ["session", "delete", "--all", "--yes", "--force"])

        assert result.exit_code == 0
        list_result = runner.invoke(main, ["session", "list"])
        assert "live-a" not in list_result.output
        assert "live-b" not in list_result.output

    def test_delete_multiple_sessions(self, runner: CliRunner, temp_env: Path) -> None:
        """Should delete multiple sessions in one command."""
        with successful_claude_launch():
            runner.invoke(main, ["session", "start", "multi-1"])
            runner.invoke(main, ["session", "start", "multi-2"])
            runner.invoke(main, ["session", "start", "multi-3"])

        result = runner.invoke(main, ["session", "delete", "multi-1", "multi-2", "multi-3", "--yes"])

        assert result.exit_code == 0
        assert "Deleted session" in result.output
        assert "multi-1" in result.output
        assert "multi-2" in result.output
        assert "multi-3" in result.output
        assert "3 deleted" in result.output

        manager = SessionManager()
        assert not manager.session_exists("multi-1")
        assert not manager.session_exists("multi-2")
        assert not manager.session_exists("multi-3")

    def test_delete_all_sessions(self, runner: CliRunner, temp_env: Path) -> None:
        """--all should delete every session."""
        with successful_claude_launch():
            runner.invoke(main, ["session", "start", "all-1"])
            runner.invoke(main, ["session", "start", "all-2"])

        result = runner.invoke(main, ["session", "delete", "--all", "--yes"])

        assert result.exit_code == 0
        assert "Deleted session" in result.output
        assert "2 deleted" in result.output

        manager = SessionManager()
        assert len(manager.list_sessions()) == 0

    def test_delete_all_with_names_errors(self, runner: CliRunner, temp_env: Path) -> None:
        """--all with explicit names should error."""
        result = runner.invoke(main, ["session", "delete", "--all", "some-name", "--yes"])

        assert result.exit_code == 1
        assert "Cannot combine --all" in result.output

    def test_delete_no_args_errors(self, runner: CliRunner, temp_env: Path) -> None:
        """No names and no --all should error."""
        result = runner.invoke(main, ["session", "delete"])

        assert result.exit_code == 1
        assert "Provide session name(s) or use --all" in result.output

    def test_delete_all_empty_is_noop(self, runner: CliRunner, temp_env: Path) -> None:
        """--all with no sessions should show a message and succeed."""
        result = runner.invoke(main, ["session", "delete", "--all", "--yes"])

        assert result.exit_code == 0
        assert "No sessions to delete" in result.output

    def test_delete_partial_failure(self, runner: CliRunner, temp_env: Path) -> None:
        """Should continue deleting after a failure and report summary."""
        with successful_claude_launch():
            runner.invoke(main, ["session", "start", "exists-1"])

        result = runner.invoke(main, ["session", "delete", "exists-1", "nonexistent", "--yes"])

        assert result.exit_code == 1
        assert "Deleted session" in result.output
        assert "exists-1" in result.output
        assert "not found" in result.output
        assert "1 deleted" in result.output
        assert "1 failed" in result.output

    def test_delete_all_prompts_without_yes(self, runner: CliRunner, temp_env: Path) -> None:
        """--all without --yes should prompt with session list."""
        with successful_claude_launch():
            runner.invoke(main, ["session", "start", "prompt-1"])
            runner.invoke(main, ["session", "start", "prompt-2"])

        result = runner.invoke(main, ["session", "delete", "--all"], input="n\n")

        assert "all 2 session(s)" in result.output
        assert "Cancelled" in result.output

    def test_delete_all_reports_skipped_active_sessions(self, runner: CliRunner, temp_env: Path) -> None:
        """--all (no --force) reports and skips live sessions, deleting only the rest."""
        runner.invoke(main, ["session", "start", "all-active-1", "--no-launch"])
        runner.invoke(main, ["session", "start", "all-active-2", "--no-launch"])
        ActiveSessionStore().upsert_session(
            "all-active-2",
            worktree_path=str(temp_env),
            launch_mode=LAUNCH_MODE_HOST,
            launcher_pid=os.getpid(),
        )

        result = runner.invoke(main, ["session", "delete", "--all"], input="n\n")

        assert result.exit_code == 0
        assert "Skipping" in result.output
        assert "all-active-2" in result.output
        # Only the idle session remains as a deletion candidate.
        assert "all 1 session(s)" in result.output
        assert "Cancelled" in result.output

    def test_delete_dirty_worktree_shows_force_tip(self, runner: CliRunner, temp_env: Path) -> None:
        """Single-session dirty worktree failures should keep the force guidance."""
        with patch(
            "forge.cli.session_manage._delete_single_session",
            side_effect=DirtyWorktreeError("/tmp/wt"),
        ):
            result = runner.invoke(main, ["session", "delete", "dirty-sess", "--yes"])

        assert result.exit_code == 1
        assert "Error:" in result.output
        assert "/tmp/wt" in result.output
        assert "Use --force to remove anyway, or commit/stash your changes first." in result.output

    def test_delete_single_session_not_found_uses_cli_error_format(self, runner: CliRunner, temp_env: Path) -> None:
        """Single-session ForgeSessionError should preserve standard CLI formatting."""
        with patch(
            "forge.cli.session_manage._delete_single_session",
            side_effect=SessionNotFoundError("missing-sess"),
        ):
            result = runner.invoke(main, ["session", "delete", "missing-sess", "--yes"])

        assert result.exit_code == 1
        assert "Error:" in result.output
        assert "missing-sess" in result.output
        assert "Deleted session" not in result.output

    def test_delete_multi_session_forge_error_uses_per_target_summary(self, runner: CliRunner, temp_env: Path) -> None:
        """Multi-session ForgeSessionError should be reported per target without aborting immediately."""
        with patch("forge.cli.session_manage._delete_single_session") as mock_delete:
            mock_delete.side_effect = [None, SessionNotFoundError("missing-sess")]
            result = runner.invoke(main, ["session", "delete", "ok-sess", "missing-sess", "--yes"])

        assert result.exit_code == 1
        assert "Deleted session" in result.output
        assert "ok-sess" in result.output
        assert "missing-sess" in result.output
        assert "1 deleted" in result.output
        assert "1 failed" in result.output
        assert "Error:" in result.output

    def test_delete_cross_project_resolves(self, runner: CliRunner, temp_env: Path) -> None:
        """Delete from wrong forge_root should resolve cross-project and succeed."""
        forge_root_a, forge_root_b = _seed_scoped_duplicate_sessions(temp_env)

        # CWD is temp_env (forge_root_a), but delete the session scoped to forge_root_b
        other_name = "other-project-sess"
        other_manifest = create_session_state(
            other_name,
            proxy_template="t",
            proxy_base_url="http://localhost:9999",
            worktree_path=str(forge_root_b),
        )
        other_manifest.forge_root = str(forge_root_b)
        SessionStore(str(forge_root_b), other_name).write(other_manifest)
        IndexStore().add_session(
            name=other_name,
            worktree_path=str(forge_root_b),
            project_root=str(temp_env),
            forge_root=str(forge_root_b),
        )

        result = runner.invoke(main, ["session", "delete", other_name, "--yes"])

        assert result.exit_code == 0
        assert "Deleted" in result.output
        assert "nested-project" in result.output  # cross-project note

    def test_delete_cross_project_ambiguous_shows_all_roots(self, runner: CliRunner, temp_env: Path) -> None:
        """Delete of a duplicate name from wrong project should list all locations."""
        _seed_scoped_duplicate_sessions(temp_env)

        # "shared" exists in forge_root_a (temp_env) and forge_root_b (temp_env/nested-project).
        # Create a third forge_root where "shared" does NOT exist, and run delete from there.
        forge_root_c = temp_env / "other-project"
        forge_root_c.mkdir(parents=True, exist_ok=True)
        (forge_root_c / ".forge").mkdir(parents=True, exist_ok=True)

        # Patch _cwd_forge_root and os.getcwd so the orphan check
        # (SessionStore at Path.cwd()) doesn't find the session on disk.
        with (
            patch(
                "forge.cli.session_manage._cwd_forge_root",
                return_value=str(forge_root_c),
            ),
            patch("os.getcwd", return_value=str(forge_root_c)),
        ):
            result = runner.invoke(main, ["session", "delete", "shared", "--yes"])

        assert result.exit_code == 1
        assert "Ambiguous" in result.output or "multiple" in result.output.lower()


class TestSessionIncognito:
    """Tests for 'forge session incognito' command."""

    def test_incognito_creates_session(self, runner: CliRunner, temp_env: Path) -> None:
        """Should create an incognito session."""
        with successful_claude_launch():
            result = runner.invoke(main, ["session", "incognito", "incognito-test"])

        assert result.exit_code == 0
        assert "incognito" in result.output.lower()

    def test_incognito_generates_name(self, runner: CliRunner, temp_env: Path) -> None:
        """Should generate name when not provided."""
        with successful_claude_launch():
            result = runner.invoke(main, ["session", "incognito"])

        assert result.exit_code == 0
        assert "Created incognito session" in result.output

    def test_incognito_direct_clears_proxy_env(self, runner: CliRunner, temp_env: Path) -> None:
        """Direct incognito sessions should unset proxy routing env vars."""
        with successful_claude_launch() as mock_invoke:
            result = runner.invoke(main, ["session", "incognito", "direct-incognito", "--no-proxy"])

        assert result.exit_code == 0
        assert "Routing: direct" in result.output
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


class TestMainGroup:
    """Tests for main CLI group."""

    def test_help(self, runner: CliRunner) -> None:
        """Should show help."""
        result = runner.invoke(main, ["--help"])

        assert result.exit_code == 0
        assert "Multi-Forge" in result.output

    def test_session_subcommand_help(self, runner: CliRunner) -> None:
        """Should show session subcommand help."""
        result = runner.invoke(main, ["session", "--help"])

        assert result.exit_code == 0
        assert "start" in result.output
        assert "resume" in result.output
        assert "list" in result.output
        assert "launch" not in result.output
