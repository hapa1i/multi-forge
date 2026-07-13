"""Tests for session override CLI commands."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from forge.cli.main import main
from forge.session import IndexStore, SessionStore, create_session_state
from tests.src.cli.session_command_support import (
    successful_claude_launch,
)


def _seed_cross_project_session(*, caller_root: Path, target_root: Path, name: str) -> SessionStore:
    (target_root / ".forge").mkdir(parents=True)
    state = create_session_state(name, worktree_path=str(target_root))
    state.forge_root = str(target_root)
    store = SessionStore(str(target_root), name)
    store.write(state)
    IndexStore().add_session(
        name=name,
        worktree_path=str(target_root),
        project_root=str(caller_root),
        forge_root=str(target_root),
        checkout_root=str(target_root),
        relative_path=".",
    )
    return store


class TestSessionSetOverride:
    """Tests for 'forge session set' command."""

    def test_set_updates_overrides(self, runner: CliRunner, temp_env: Path) -> None:
        """Should set an override value."""
        with successful_claude_launch():
            runner.invoke(main, ["session", "start", "set-test"])

        result = runner.invoke(
            main,
            ["session", "set", "--session", "set-test", "policy.fail_mode", "closed"],
        )

        assert result.exit_code == 0
        assert "Set" in result.output
        assert "policy.fail_mode" in result.output
        assert "closed" in result.output

    def test_set_nested_key(self, runner: CliRunner, temp_env: Path) -> None:
        """Should set nested key values."""
        with successful_claude_launch():
            runner.invoke(main, ["session", "start", "nested-test"])

        result = runner.invoke(
            main,
            ["session", "set", "--session", "nested-test", "custom.my_flag", "true"],
        )

        assert result.exit_code == 1
        assert "custom.* is not supported" in result.output

    def test_set_json_value(self, runner: CliRunner, temp_env: Path) -> None:
        """Should parse JSON values."""
        with successful_claude_launch():
            runner.invoke(main, ["session", "start", "json-test"])

        result = runner.invoke(main, ["session", "set", "--session", "json-test", "custom.count", "42"])

        assert result.exit_code == 1
        assert "custom.* is not supported" in result.output

    def test_set_null_clears(self, runner: CliRunner, temp_env: Path) -> None:
        """Should set null value (clears field)."""
        with successful_claude_launch():
            runner.invoke(main, ["session", "start", "null-test"])

        result = runner.invoke(main, ["session", "set", "--session", "null-test", "custom.flag", "null"])

        assert result.exit_code == 1
        assert "custom.* is not supported" in result.output

    def test_set_invalid_key_fails(self, runner: CliRunner, temp_env: Path) -> None:
        """Should fail for invalid key."""
        with successful_claude_launch():
            runner.invoke(main, ["session", "start", "invalid-key-test"])

        result = runner.invoke(
            main,
            [
                "session",
                "set",
                "--session",
                "invalid-key-test",
                "confirmed.claude_session_id",
                "value",
            ],
        )

        assert result.exit_code == 1
        assert "cannot override" in result.output or "Error" in result.output

    def test_set_no_session_fails(self, runner: CliRunner, temp_env: Path) -> None:
        """Should fail when no session exists."""
        result = runner.invoke(main, ["session", "set", "policy.fail_mode", "closed"])

        assert result.exit_code == 1
        # Should mention no active session or session not found

    def test_set_with_session_option(self, runner: CliRunner, temp_env: Path) -> None:
        """Should accept --session option."""
        with successful_claude_launch():
            runner.invoke(main, ["session", "start", "target-session"])

        result = runner.invoke(
            main,
            ["session", "set", "--session", "target-session", "model_tier", "haiku"],
        )

        assert result.exit_code == 1
        assert "unknown field" in result.output

    def test_set_uses_incompatible_target_root_not_compatible_caller(self, runner: CliRunner, temp_env: Path) -> None:
        target_root = temp_env.parent / "target-project"
        store = _seed_cross_project_session(caller_root=temp_env, target_root=target_root, name="target-session")
        before = store.manifest_path.read_bytes()
        (target_root / ".forge" / "project.toml").write_text(
            'schema_version = 1\nrequired_forge = ">=9999"\n', encoding="utf-8"
        )

        result = runner.invoke(
            main,
            [
                "session",
                "set",
                "--session",
                "target-session",
                "policy.fail_mode",
                "closed",
            ],
        )

        assert result.exit_code == 1
        assert "requires Forge" in result.output
        assert store.manifest_path.read_bytes() == before

    def test_set_ignores_incompatible_caller_when_target_root_is_compatible(
        self, runner: CliRunner, temp_env: Path
    ) -> None:
        target_root = temp_env.parent / "target-project"
        store = _seed_cross_project_session(caller_root=temp_env, target_root=target_root, name="target-session")
        (temp_env / ".forge" / "project.toml").write_text(
            'schema_version = 1\nrequired_forge = ">=9999"\n', encoding="utf-8"
        )

        result = runner.invoke(
            main,
            [
                "session",
                "set",
                "--session",
                "target-session",
                "policy.fail_mode",
                "closed",
            ],
        )

        assert result.exit_code == 0, result.output
        assert store.read().overrides["policy"]["fail_mode"] == "closed"


class TestSessionReset:
    """Tests for 'forge session reset' command."""

    def test_reset_single_key(self, runner: CliRunner, temp_env: Path) -> None:
        """Should reset a single override key."""
        with successful_claude_launch():
            runner.invoke(main, ["session", "start", "reset-single"])

        # Set an override first
        runner.invoke(
            main,
            [
                "session",
                "set",
                "--session",
                "reset-single",
                "policy.fail_mode",
                "closed",
            ],
        )

        # Reset it
        result = runner.invoke(main, ["session", "reset", "--session", "reset-single", "policy.fail_mode"])

        assert result.exit_code == 0
        assert "Reset" in result.output or "policy.fail_mode" in result.output

    def test_reset_all(self, runner: CliRunner, temp_env: Path) -> None:
        """Should reset all overrides with --all."""
        with successful_claude_launch():
            runner.invoke(main, ["session", "start", "reset-all"])

        # Set some overrides
        runner.invoke(
            main,
            ["session", "set", "--session", "reset-all", "policy.fail_mode", "closed"],
        )
        # model_tier no longer exists; setting it should fail
        runner.invoke(main, ["session", "set", "--session", "reset-all", "model_tier", "haiku"])

        # Reset all
        result = runner.invoke(main, ["session", "reset", "--session", "reset-all", "--all"])

        assert result.exit_code == 0
        assert "Cleared" in result.output or "all" in result.output.lower()

    def test_reset_nonexistent_key_noop(self, runner: CliRunner, temp_env: Path) -> None:
        """Should be a no-op for key that isn't overridden."""
        with successful_claude_launch():
            runner.invoke(main, ["session", "start", "reset-noop"])

        result = runner.invoke(main, ["session", "reset", "--session", "reset-noop", "policy.fail_mode"])

        # Should succeed (no-op)
        assert result.exit_code == 0

    def test_reset_no_session_fails(self, runner: CliRunner, temp_env: Path) -> None:
        """Should fail when no session exists."""
        result = runner.invoke(main, ["session", "reset", "--session", "nonexistent", "policy.fail_mode"])

        assert result.exit_code == 1

    def test_reset_key_and_all_errors(self, runner: CliRunner, temp_env: Path) -> None:
        """Should error when both key and --all provided."""
        with successful_claude_launch():
            runner.invoke(main, ["session", "start", "reset-conflict"])

        result = runner.invoke(
            main,
            [
                "session",
                "reset",
                "--session",
                "reset-conflict",
                "policy.fail_mode",
                "--all",
            ],
        )

        assert result.exit_code == 1
        assert "Cannot specify both" in result.output or "conflict" in result.output.lower()

    def test_reset_no_args_clears_all(self, runner: CliRunner, temp_env: Path) -> None:
        """Reset with no args clears all overrides (same as --all)."""
        with successful_claude_launch():
            runner.invoke(main, ["session", "start", "reset-neither"])

        # Set some overrides first
        runner.invoke(
            main,
            [
                "session",
                "set",
                "--session",
                "reset-neither",
                "policy.fail_mode",
                "closed",
            ],
        )

        # Reset with no args
        result = runner.invoke(main, ["session", "reset", "--session", "reset-neither"])

        # Should succeed and clear all overrides
        assert result.exit_code == 0
        assert "Cleared" in result.output or "No overrides" in result.output


class TestInspectShowsOverrides:
    """Tests that show command displays override information."""

    def test_show_displays_overrides_section(self, runner: CliRunner, temp_env: Path) -> None:
        """Show should display active overrides."""
        with successful_claude_launch():
            runner.invoke(main, ["session", "start", "inspect-override"])

        # Set an override
        runner.invoke(
            main,
            [
                "session",
                "set",
                "--session",
                "inspect-override",
                "policy.fail_mode",
                "closed",
            ],
        )

        # Show
        result = runner.invoke(main, ["session", "show", "inspect-override"])

        assert result.exit_code == 0
        # Should show the override somehow
        assert "closed" in result.output or "override" in result.output.lower()


class TestTransactionalBehavior:
    """Tests that manifest is not modified when validation fails."""

    def test_no_write_on_invalid_type(self, runner: CliRunner, temp_env: Path) -> None:
        """Manifest file should be unchanged when set fails type validation."""
        import json

        with successful_claude_launch():
            runner.invoke(main, ["session", "start", "transactional-test"])

        # Read manifest contents before (per-session directory)
        manifest_path = temp_env / ".forge" / "sessions" / "transactional-test" / "forge.session.json"
        content_before = manifest_path.read_text()
        data_before = json.loads(content_before)

        # Attempt to set an invalid value (tags should be list, not string)
        result = runner.invoke(
            main,
            [
                "session",
                "set",
                "--session",
                "transactional-test",
                "memory.tags",
                '"not-a-list"',
            ],
        )

        # Should fail
        assert result.exit_code == 1

        # Manifest should be unchanged
        content_after = manifest_path.read_text()
        data_after = json.loads(content_after)

        # Core fields should be identical
        assert data_before["name"] == data_after["name"]
        assert data_before["overrides"] == data_after["overrides"]

    def test_no_write_on_invalid_key(self, runner: CliRunner, temp_env: Path) -> None:
        """Manifest file should be unchanged when set fails key validation."""

        with successful_claude_launch():
            runner.invoke(main, ["session", "start", "invalid-key-transact"])

        manifest_path = temp_env / ".forge" / "sessions" / "invalid-key-transact" / "forge.session.json"
        content_before = manifest_path.read_text()

        # Attempt to set a confirmed field (should be rejected)
        result = runner.invoke(
            main,
            [
                "session",
                "set",
                "--session",
                "invalid-key-transact",
                "confirmed.foo",
                "bar",
            ],
        )

        assert result.exit_code == 1

        # Manifest should be unchanged
        content_after = manifest_path.read_text()
        assert content_before == content_after


class TestCwdGuardWiring:
    """Verify session commands call the correct CWD guard."""

    def test_start_calls_require_repo_root(self, runner: CliRunner, temp_env: Path) -> None:
        with (
            patch("forge.cli.guards.require_repo_root", return_value=temp_env) as mock_rr,
            patch("forge.cli.guards.require_main_repo_root") as mock_mrr,
            successful_claude_launch(),
        ):
            runner.invoke(main, ["session", "start", "policy-test"])
        mock_rr.assert_called_once()
        mock_mrr.assert_not_called()

    def test_start_worktree_calls_require_main_repo_root(self, runner: CliRunner, temp_env: Path) -> None:
        with (
            patch("forge.cli.guards.require_repo_root") as mock_rr,
            patch("forge.cli.guards.require_main_repo_root", return_value=temp_env) as mock_mrr,
            successful_claude_launch(),
            patch("forge.session.worktree.get_main_repo_root", return_value=temp_env),
            patch("forge.session.worktree.create_worktree") as mock_wt,
            patch("forge.session.worktree.copy_runtime_config"),
        ):
            from forge.session.worktree.create import WorktreeResult

            mock_wt.return_value = WorktreeResult(
                worktree_path=str(temp_env / "wt"),
                branch="policy-wt-test",
                created_branch=True,
            )
            (temp_env / "wt").mkdir()
            runner.invoke(
                main,
                [
                    "session",
                    "start",
                    "policy-wt-test",
                    "--worktree",
                    "--no-proxy",
                    "--no-launch",
                ],
            )
        mock_mrr.assert_called_once()
        mock_rr.assert_not_called()

    def test_fork_calls_require_repo_root(self, runner: CliRunner, temp_env: Path) -> None:
        with successful_claude_launch():
            runner.invoke(main, ["session", "start", "fork-parent", "--no-proxy", "--no-launch"])

        with (
            patch("forge.cli.guards.require_repo_root", return_value=temp_env) as mock_rr,
            patch("forge.cli.guards.require_main_repo_root") as mock_mrr,
            successful_claude_launch(),
        ):
            runner.invoke(
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
        mock_rr.assert_called_once()
        mock_mrr.assert_not_called()

    def test_fork_worktree_calls_require_main_repo_root(self, runner: CliRunner, temp_env: Path) -> None:
        with successful_claude_launch():
            runner.invoke(
                main,
                ["session", "start", "fork-wt-parent", "--no-proxy", "--no-launch"],
            )

        with (
            patch("forge.cli.guards.require_repo_root") as mock_rr,
            patch("forge.cli.guards.require_main_repo_root", return_value=temp_env) as mock_mrr,
        ):
            # Don't need full worktree setup — guard is called before fork_session
            runner.invoke(
                main,
                [
                    "session",
                    "fork",
                    "fork-wt-parent",
                    "--name",
                    "fork-wt-child",
                    "--worktree",
                    "--no-proxy",
                ],
            )
        mock_mrr.assert_called_once()
        mock_rr.assert_not_called()

    def test_fork_into_skips_guards(self, runner: CliRunner, temp_env: Path) -> None:
        with successful_claude_launch():
            runner.invoke(
                main,
                ["session", "start", "fork-into-parent", "--no-proxy", "--no-launch"],
            )

        with (
            patch("forge.cli.guards.require_repo_root") as mock_rr,
            patch("forge.cli.guards.require_main_repo_root") as mock_mrr,
        ):
            # --into has its own validation; CWD guards should not be called
            runner.invoke(main, ["session", "fork", "fork-into-parent", "--into", str(temp_env)])
        mock_rr.assert_not_called()
        mock_mrr.assert_not_called()

    def test_incognito_calls_require_repo_root(self, runner: CliRunner, temp_env: Path) -> None:
        with (
            patch("forge.cli.guards.require_repo_root", return_value=temp_env) as mock_rr,
            successful_claude_launch(),
        ):
            runner.invoke(main, ["session", "incognito", "policy-incog", "--no-proxy"])
        mock_rr.assert_called_once()
