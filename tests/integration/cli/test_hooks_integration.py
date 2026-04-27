"""Docker-based integration tests for CLI hook commands.

These tests run inside a session-scoped container (docker_in marker) for
complete filesystem isolation. They test the behavioral aspects of hook
enable, disable, and session-start handling.

Note: Pure logic tests (like _get_last_assistant_text_for_verification) remain
in unit tests since they don't touch protected paths.
"""

from __future__ import annotations

import json

import pytest

from tests.fixtures.docker import ContainerLike

pytestmark = [pytest.mark.integration, pytest.mark.docker_in]


class TestHookEnableDisable:
    """Tests for `forge hook enable` and `forge hook disable` commands.

    Note: Hook config is stored in settings.local.json (not settings.json).
    """

    # The settings filename used by forge hook enable/disable
    SETTINGS_FILE = "settings.local.json"

    def test_install_creates_settings_file(self, mock_claude_workspace: ContainerLike) -> None:
        """Should create settings file with hook config."""
        # Ensure .claude dir exists
        mock_claude_workspace.exec("mkdir -p /workspace/.claude")

        result = mock_claude_workspace.exec("cd /workspace && forge hook enable")

        assert result.returncode == 0
        assert "Enabled" in result.stdout

        # Verify settings file was created
        settings_check = mock_claude_workspace.exec(f"cat /workspace/.claude/{self.SETTINGS_FILE}")
        assert settings_check.returncode == 0

        settings = json.loads(settings_check.stdout)
        assert "hooks" in settings
        assert "SessionStart" in settings["hooks"]

    def test_install_preserves_existing_settings(self, mock_claude_workspace: ContainerLike) -> None:
        """Should preserve other settings when enabling hooks."""
        # Create .claude dir with existing settings
        mock_claude_workspace.exec("mkdir -p /workspace/.claude")
        mock_claude_workspace.exec(f"""cat > /workspace/.claude/{self.SETTINGS_FILE} << 'EOF'
{{"other_setting": "value", "hooks": {{}}}}
EOF""")

        result = mock_claude_workspace.exec("cd /workspace && forge hook enable")

        assert result.returncode == 0

        settings_check = mock_claude_workspace.exec(f"cat /workspace/.claude/{self.SETTINGS_FILE}")
        settings = json.loads(settings_check.stdout)

        # Should preserve other settings
        assert settings["other_setting"] == "value"
        # Should have installed SessionStart hook
        assert "SessionStart" in settings["hooks"]

    def test_install_fails_if_already_configured(self, mock_claude_workspace: ContainerLike) -> None:
        """Should fail if SessionStart already configured without --force."""
        # Create settings with existing SessionStart hook
        mock_claude_workspace.exec("mkdir -p /workspace/.claude")
        mock_claude_workspace.exec(f"""cat > /workspace/.claude/{self.SETTINGS_FILE} << 'EOF'
{{"hooks": {{"SessionStart": [{{"type": "command", "command": "other-hook"}}]}}}}
EOF""")

        result = mock_claude_workspace.exec("cd /workspace && forge hook enable")

        assert result.returncode == 1
        assert "already configured" in result.stdout

    def test_install_force_overwrites(self, mock_claude_workspace: ContainerLike) -> None:
        """--force should overwrite existing SessionStart config."""
        # Create settings with existing SessionStart hook
        mock_claude_workspace.exec("mkdir -p /workspace/.claude")
        mock_claude_workspace.exec(f"""cat > /workspace/.claude/{self.SETTINGS_FILE} << 'EOF'
{{"hooks": {{"SessionStart": [{{"type": "command", "command": "other-hook"}}]}}}}
EOF""")

        result = mock_claude_workspace.exec("cd /workspace && forge hook enable --force")

        assert result.returncode == 0

        settings_check = mock_claude_workspace.exec(f"cat /workspace/.claude/{self.SETTINGS_FILE}")
        settings = json.loads(settings_check.stdout)

        # Should have our forge hook now
        hook_str = json.dumps(settings["hooks"]["SessionStart"])
        assert "forge hook session-start" in hook_str

    def test_uninstall_removes_hook(self, mock_claude_workspace: ContainerLike) -> None:
        """Should remove Forge hook from settings."""
        mock_claude_workspace.exec("mkdir -p /workspace/.claude")

        # Enable first
        mock_claude_workspace.exec("cd /workspace && forge hook enable")

        # Then disable
        result = mock_claude_workspace.exec("cd /workspace && forge hook disable")

        assert result.returncode == 0
        assert "Disabled" in result.stdout

        # Verify hook was removed
        settings_check = mock_claude_workspace.exec(f"cat /workspace/.claude/{self.SETTINGS_FILE}")
        settings = json.loads(settings_check.stdout)

        # SessionStart should be removed or empty
        assert "SessionStart" not in settings.get("hooks", {})

    def test_uninstall_preserves_other_hooks(self, mock_claude_workspace: ContainerLike) -> None:
        """Should preserve other hooks when disabling Forge hook."""
        mock_claude_workspace.exec("mkdir -p /workspace/.claude")

        # Enable forge hooks first (which creates the nested structure)
        mock_claude_workspace.exec("cd /workspace && forge hook enable")

        # Read what was installed
        settings = mock_claude_workspace.read_json(f"/workspace/.claude/{self.SETTINGS_FILE}")

        # Add another hook to the existing structure
        settings["hooks"]["SessionStart"].append({"type": "command", "command": "other-hook"})

        # Write back with the added hook
        mock_claude_workspace.write_json(f"/workspace/.claude/{self.SETTINGS_FILE}", settings)

        # Now disable should remove forge hook but keep other
        result = mock_claude_workspace.exec("cd /workspace && forge hook disable")

        assert result.returncode == 0

        settings_check = mock_claude_workspace.exec(f"cat /workspace/.claude/{self.SETTINGS_FILE}")
        settings = json.loads(settings_check.stdout)

        # Should still have the other hook
        remaining_hooks = settings.get("hooks", {}).get("SessionStart", [])
        assert len(remaining_hooks) == 1
        assert "other-hook" in json.dumps(remaining_hooks)

    def test_uninstall_no_settings_file(self, mock_claude_workspace: ContainerLike) -> None:
        """Should handle missing settings file gracefully."""
        mock_claude_workspace.exec("mkdir -p /workspace/.claude")
        # No settings file created

        result = mock_claude_workspace.exec("cd /workspace && forge hook disable")

        assert result.returncode == 0
        assert "No settings file" in result.stdout

    def test_uninstall_no_forge_hook(self, mock_claude_workspace: ContainerLike) -> None:
        """Should handle missing Forge hook gracefully."""
        mock_claude_workspace.exec("mkdir -p /workspace/.claude")
        mock_claude_workspace.exec(f"""cat > /workspace/.claude/{self.SETTINGS_FILE} << 'EOF'
{{"hooks": {{"SessionStart": [{{"type": "command", "command": "other-hook"}}]}}}}
EOF""")

        result = mock_claude_workspace.exec("cd /workspace && forge hook disable")

        assert result.returncode == 0
        assert "No Forge hooks found" in result.stdout


class TestSessionStartHook:
    """Tests for `forge hook session-start` command.

    These tests simulate Claude Code invoking the session-start hook with
    JSON payloads. Tests verify manifest updates and response handling.
    """

    def _setup_session(self, workspace: ContainerLike, session_name: str = "test-session") -> None:
        """Helper to set up a session for hook testing."""
        # Create session (this creates manifest)
        workspace.exec(f"cd /workspace && forge session start {session_name}")

    def test_empty_stdin_returns_error(self, mock_claude_workspace: ContainerLike) -> None:
        """Should return error for empty stdin."""
        self._setup_session(mock_claude_workspace)

        result = mock_claude_workspace.exec(
            "cd /workspace && export FORGE_SESSION=test-session && echo '' | forge hook session-start"
        )

        assert result.returncode == 0  # Hooks always exit 0
        output = json.loads(result.stdout)
        assert output["success"] is False
        assert output["error"] == "invalid_input"

    def test_invalid_json_returns_error(self, mock_claude_workspace: ContainerLike) -> None:
        """Should return error for invalid JSON."""
        self._setup_session(mock_claude_workspace)

        result = mock_claude_workspace.exec(
            "cd /workspace && export FORGE_SESSION=test-session && echo 'not json' | forge hook session-start"
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["success"] is False
        assert output["error"] == "invalid_input"
        assert "Invalid JSON" in output["message"]

    def test_missing_required_fields(self, mock_claude_workspace: ContainerLike) -> None:
        """Should return error for missing required fields."""
        self._setup_session(mock_claude_workspace)

        # Missing transcript_path and source
        payload = json.dumps({"session_id": "uuid-123"})
        result = mock_claude_workspace.exec(
            f"cd /workspace && export FORGE_SESSION=test-session && echo '{payload}' | forge hook session-start"
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["success"] is False
        assert "required fields" in output["message"]

    def test_session_not_found(self, mock_claude_workspace: ContainerLike) -> None:
        """Should return error when session cannot be resolved."""
        # Don't create a session, just have .claude dir
        mock_claude_workspace.exec("mkdir -p /workspace/.claude")

        payload = json.dumps(
            {
                "session_id": "unknown-uuid",
                "transcript_path": "/path/to/file.jsonl",
                "source": "startup",
            }
        )

        result = mock_claude_workspace.exec(f"cd /workspace && echo '{payload}' | forge hook session-start")

        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["success"] is False
        assert output["error"] == "session_not_found"

    def test_successful_startup(self, mock_claude_workspace: ContainerLike) -> None:
        """Should successfully handle startup hook."""
        self._setup_session(mock_claude_workspace)

        payload = json.dumps(
            {
                "session_id": "new-uuid-456",
                "transcript_path": "/path/to/transcript.jsonl",
                "source": "startup",
            }
        )

        result = mock_claude_workspace.exec(
            f"cd /workspace && export FORGE_SESSION=test-session && echo '{payload}' | forge hook session-start"
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["success"] is True
        assert output["session_name"] == "test-session"
        assert output["received_session_id"] == "new-uuid-456"
        assert output["received_source"] == "startup"

    def test_compact_overwrites_uuid(self, mock_claude_workspace: ContainerLike) -> None:
        """Should overwrite UUID on compact (1:1 session model)."""
        self._setup_session(mock_claude_workspace)

        # First, simulate initial session start
        payload1 = json.dumps(
            {
                "session_id": "original-uuid",
                "transcript_path": "/path/to/transcript.jsonl",
                "source": "startup",
            }
        )
        mock_claude_workspace.exec(
            f"cd /workspace && export FORGE_SESSION=test-session && echo '{payload1}' | forge hook session-start"
        )

        # Then simulate compact with new UUID
        payload2 = json.dumps(
            {
                "session_id": "new-uuid-after-compact",
                "transcript_path": "/path/to/transcript.jsonl",
                "source": "compact",
            }
        )

        result = mock_claude_workspace.exec(
            f"cd /workspace && export FORGE_SESSION=test-session && echo '{payload2}' | forge hook session-start"
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["success"] is True

        # Verify UUID was overwritten (1:1 model, no history accumulation)
        manifest_check = mock_claude_workspace.exec("cat /workspace/.forge/sessions/test-session/forge.session.json")
        manifest = json.loads(manifest_check.stdout)

        assert manifest["confirmed"]["claude_session_id"] == "new-uuid-after-compact"

    def test_deferred_same_dir_fork_startup_reconciles_child_uuid(self, mock_claude_workspace: ContainerLike) -> None:
        """A launched same-dir fork should adopt the child UUID from SessionStart."""
        mock_claude_workspace.exec("cd /workspace && forge session start fork-parent --no-launch")

        # UUID is hook-owned; simulate hook confirmation for parent
        parent_uuid = "parent-uuid-for-fork"
        mock_claude_workspace.exec(
            f'cd /forge && uv run python -c "'
            f"import json; from pathlib import Path; "
            f"p = Path('/workspace/.forge/sessions/fork-parent/forge.session.json'); "
            f"d = json.loads(p.read_text()); "
            f"d['confirmed']['claude_session_id'] = '{parent_uuid}'; "
            f"p.write_text(json.dumps(d))"
            f'"'
        )

        result = mock_claude_workspace.exec(
            "cd /workspace && forge session fork fork-parent --name fork-child --no-launch"
        )
        assert result.returncode == 0

        child_before = mock_claude_workspace.read_json("/workspace/.forge/sessions/fork-child/forge.session.json")
        assert child_before["confirmed"]["claude_session_id"] is None

        mock_claude_workspace.exec("> /tmp/claude_invocations.log")
        launch_result = mock_claude_workspace.exec("cd /workspace && forge session resume fork-child")

        assert launch_result.returncode == 0
        assert "Fork parent Claude conversation" in launch_result.stdout

        invocations = mock_claude_workspace.exec("cat /tmp/claude_invocations.log")
        assert "--resume" in invocations.stdout
        assert "--fork-session" in invocations.stdout

        payload = json.dumps(
            {
                "session_id": "child-uuid-456",
                "transcript_path": "/tmp/fork-child-transcript.jsonl",
                "source": "startup",
            }
        )
        hook_result = mock_claude_workspace.exec(
            f"cd /workspace && export FORGE_SESSION=fork-child && echo '{payload}' | forge hook session-start"
        )

        assert hook_result.returncode == 0
        output = json.loads(hook_result.stdout)
        assert output["success"] is True
        assert output["session_name"] == "fork-child"

        child_after = mock_claude_workspace.read_json("/workspace/.forge/sessions/fork-child/forge.session.json")
        assert child_after["confirmed"]["claude_session_id"] == "child-uuid-456"
        assert child_after["confirmed"]["transcript_path"] == "/tmp/fork-child-transcript.jsonl"
        assert child_after["confirmed"]["confirmed_by"] == "hook:SessionStart:startup"
        assert child_after["confirmed"]["claude_session_id"] != parent_uuid


class TestStopHookIntegration:
    """Integration tests for Stop hook behavior.

    These tests verify the Stop hook correctly captures transcripts
    and creates pending-work markers.
    """

    def _setup_session(self, workspace: ContainerLike, session_name: str = "test-session") -> None:
        """Helper to set up a session for hook testing."""
        workspace.exec(f"cd /workspace && forge session start {session_name}")

    def test_stop_hook_returns_json(self, mock_claude_workspace: ContainerLike) -> None:
        """Stop hook should return valid JSON response."""
        self._setup_session(mock_claude_workspace)

        # Create a minimal transcript
        mock_claude_workspace.exec(
            """mkdir -p /tmp/claude && echo '{"type":"assistant"}' > /tmp/claude/transcript.jsonl"""
        )

        payload = json.dumps(
            {
                "session_id": "test-uuid",
                "transcript_path": "/tmp/claude/transcript.jsonl",
            }
        )

        result = mock_claude_workspace.exec(
            f"cd /workspace && export FORGE_SESSION=test-session && echo '{payload}' | forge hook stop"
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert "success" in output
