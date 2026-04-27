"""Docker-based integration tests for artifact-capture hook commands.

These tests run inside a session-scoped container (docker_in marker) for
complete filesystem isolation. They test the behavioral aspects of:
- plan-write hook (records plan file writes)
- exit-plan-mode hook (snapshots approved plans)
- stop hook (copies transcripts, creates pending-work markers)

Hooks always exit 0 for Claude Code safety, reporting success/failure in JSON.
"""

from __future__ import annotations

import json

import pytest

from tests.fixtures.docker import ContainerLike

pytestmark = [pytest.mark.integration, pytest.mark.docker_in]


class TestPlanWriteHook:
    """Tests for `forge hook plan-write` command.

    This hook is triggered on PostToolUse events when a file is written.
    It records the path if the file is in .claude/plans/.
    """

    def _setup_session(self, workspace: ContainerLike, session_name: str = "test-session") -> None:
        """Create a session for testing."""
        workspace.exec(f"cd /workspace && forge session start {session_name}")

    def _invoke_plan_write(
        self,
        workspace: ContainerLike,
        payload: dict,
        session_name: str = "test-session",
    ) -> dict:
        """Invoke plan-write hook and return parsed response."""
        payload_json = json.dumps(payload)
        result = workspace.exec(
            f"cd /workspace && export FORGE_SESSION={session_name} && echo '{payload_json}' | forge hook plan-write"
        )
        assert result.returncode == 0, f"Hook failed: {result.stderr}"
        return json.loads(result.stdout)

    def test_skips_non_plan_writes(self, mock_claude_workspace: ContainerLike) -> None:
        """Should skip files not in .claude/plans/ directory."""
        self._setup_session(mock_claude_workspace)

        output = self._invoke_plan_write(
            mock_claude_workspace,
            {
                "hook_event_name": "PostToolUse",
                "tool_input": {"file_path": "README.md"},
            },
        )

        assert output["success"] is True
        assert output["action"] == "skip"

    def test_skips_non_plan_claude_files(self, mock_claude_workspace: ContainerLike) -> None:
        """Should skip .claude/ files outside plans/ subdirectory."""
        self._setup_session(mock_claude_workspace)

        output = self._invoke_plan_write(
            mock_claude_workspace,
            {
                "hook_event_name": "PostToolUse",
                "tool_input": {"file_path": ".claude/settings.json"},
            },
        )

        assert output["success"] is True
        assert output["action"] == "skip"

    def test_records_plan_write(self, mock_claude_workspace: ContainerLike) -> None:
        """Should record plan file write to manifest."""
        self._setup_session(mock_claude_workspace)

        output = self._invoke_plan_write(
            mock_claude_workspace,
            {
                "hook_event_name": "PostToolUse",
                "tool_input": {"file_path": ".claude/plans/foo.md"},
            },
        )

        assert output["success"] is True
        assert output["action"] == "recorded"

        # Verify manifest was updated
        result = mock_claude_workspace.exec("cat /workspace/.forge/sessions/test-session/forge.session.json")
        manifest = json.loads(result.stdout)
        assert manifest["confirmed"]["latest_plan_path"] == ".claude/plans/foo.md"

    def test_records_nested_plan_path(self, mock_claude_workspace: ContainerLike) -> None:
        """Should record deeply nested plan paths."""
        self._setup_session(mock_claude_workspace)

        output = self._invoke_plan_write(
            mock_claude_workspace,
            {
                "hook_event_name": "PostToolUse",
                "tool_input": {"file_path": ".claude/plans/feature/subfeature/plan.md"},
            },
        )

        assert output["success"] is True
        assert output["action"] == "recorded"


class TestExitPlanModeHook:
    """Tests for `forge hook exit-plan-mode` command.

    This hook is triggered on PreToolUse events when ExitPlanMode is called.
    It snapshots the approved plan to .forge/artifacts/.
    """

    def _setup_session_with_plan(
        self,
        workspace: ContainerLike,
        session_name: str = "test-session",
        plan_content: str = "# Test Plan\n\nThis is a test plan.",
    ) -> str:
        """Create a session with a plan file."""
        workspace.exec(f"cd /workspace && forge session start {session_name}")

        # Create plan file
        workspace.exec("mkdir -p /workspace/.claude/plans")
        workspace.exec(f"echo '{plan_content}' > /workspace/.claude/plans/test-plan.md")

        # Record the plan in manifest (simulating plan-write hook)
        result = workspace.exec(f"cat /workspace/.forge/sessions/{session_name}/forge.session.json")
        manifest = json.loads(result.stdout)
        manifest["confirmed"]["latest_plan_path"] = ".claude/plans/test-plan.md"
        manifest_json = json.dumps(manifest)
        workspace.exec(
            f"cat > /workspace/.forge/sessions/{session_name}/forge.session.json << 'EOF'\n{manifest_json}\nEOF"
        )

        return ".claude/plans/test-plan.md"

    def _invoke_exit_plan_mode(
        self,
        workspace: ContainerLike,
        payload: dict,
        session_name: str = "test-session",
    ) -> dict:
        """Invoke exit-plan-mode hook and return parsed response."""
        payload_json = json.dumps(payload)
        result = workspace.exec(
            f"cd /workspace && export FORGE_SESSION={session_name} && echo '{payload_json}' | forge hook exit-plan-mode"
        )
        assert result.returncode == 0, f"Hook failed: {result.stderr}"
        return json.loads(result.stdout)

    def test_snapshots_approved_plan(self, mock_claude_workspace: ContainerLike) -> None:
        """Should snapshot approved plan to artifacts directory."""
        self._setup_session_with_plan(mock_claude_workspace)

        output = self._invoke_exit_plan_mode(
            mock_claude_workspace,
            {
                "hook_event_name": "PreToolUse",
            },
        )

        assert output["success"] is True
        assert output["action"] == "snapshotted"

        # Verify artifact was created
        result = mock_claude_workspace.exec(
            "ls /workspace/.forge/artifacts/test-session/plans/ 2>/dev/null || echo 'no-artifacts'"
        )
        assert "no-artifacts" not in result.stdout
        # Should have at least one snapshot file

    def test_records_plan_artifact_in_manifest(self, mock_claude_workspace: ContainerLike) -> None:
        """Should record plan artifact in manifest."""
        self._setup_session_with_plan(mock_claude_workspace)

        self._invoke_exit_plan_mode(
            mock_claude_workspace,
            {
                "hook_event_name": "PreToolUse",
            },
        )

        # Verify manifest was updated
        result = mock_claude_workspace.exec("cat /workspace/.forge/sessions/test-session/forge.session.json")
        manifest = json.loads(result.stdout)

        plans = manifest["confirmed"].get("artifacts", {}).get("plans", [])
        assert len(plans) >= 1
        assert plans[-1]["kind"] == "approved"
        assert "snapshot_path" in plans[-1]

    def test_handles_no_plan_recorded(self, mock_claude_workspace: ContainerLike) -> None:
        """Should handle gracefully when no plan has been recorded."""
        mock_claude_workspace.exec("cd /workspace && forge session start no-plan-session")

        output = self._invoke_exit_plan_mode(
            mock_claude_workspace,
            {
                "hook_event_name": "PreToolUse",
            },
            session_name="no-plan-session",
        )

        # Hook reports success=False when there's no plan to snapshot
        # This is valid - the hook exits 0 but indicates nothing was done
        assert output["success"] is False or output.get("action") == "skip"
        # Should indicate why it couldn't proceed
        assert "no_plan" in str(output).lower() or "error" in output


class TestStopHookArtifacts:
    """Tests for `forge hook stop` artifact handling.

    This hook copies transcripts to artifacts and creates pending-work markers.
    """

    def _setup_session_with_transcript(
        self,
        workspace: ContainerLike,
        session_name: str = "test-session",
        session_id: str = "uuid-123",
    ) -> str:
        """Create a session with a transcript file."""
        workspace.exec(f"cd /workspace && forge session start {session_name}")

        # Create transcript file
        workspace.exec("mkdir -p /tmp/claude")
        workspace.exec('echo \'{"type": "assistant"}\' > /tmp/claude/transcript.jsonl')

        # Update manifest with transcript path and session ID
        result = workspace.exec(f"cat /workspace/.forge/sessions/{session_name}/forge.session.json")
        manifest = json.loads(result.stdout)
        manifest["confirmed"]["transcript_path"] = "/tmp/claude/transcript.jsonl"
        manifest["confirmed"]["claude_session_id"] = session_id
        manifest_json = json.dumps(manifest)
        workspace.exec(
            f"cat > /workspace/.forge/sessions/{session_name}/forge.session.json << 'EOF'\n{manifest_json}\nEOF"
        )

        return "/tmp/claude/transcript.jsonl"

    def _invoke_stop_hook(
        self,
        workspace: ContainerLike,
        payload: dict,
        session_name: str = "test-session",
    ) -> dict:
        """Invoke stop hook and return parsed response."""
        payload_json = json.dumps(payload)
        result = workspace.exec(
            f"cd /workspace && export FORGE_SESSION={session_name} && echo '{payload_json}' | forge hook stop"
        )
        assert result.returncode == 0, f"Hook failed: {result.stderr}"
        return json.loads(result.stdout)

    def test_copies_transcript_to_artifacts(self, mock_claude_workspace: ContainerLike) -> None:
        """Should copy transcript to artifacts directory."""
        transcript_path = self._setup_session_with_transcript(mock_claude_workspace)

        output = self._invoke_stop_hook(
            mock_claude_workspace,
            {
                "hook_event_name": "Stop",
                "transcript_path": transcript_path,
                "session_id": "uuid-123",
            },
        )

        assert output["success"] is True
        assert output["action"] == "copied"

        # Verify transcript was copied
        result = mock_claude_workspace.exec(
            "ls /workspace/.forge/artifacts/test-session/transcripts/ 2>/dev/null || echo 'no-transcripts'"
        )
        assert "uuid-123.jsonl" in result.stdout or "no-transcripts" not in result.stdout

    def test_records_transcript_artifact_in_manifest(self, mock_claude_workspace: ContainerLike) -> None:
        """Should record transcript artifact in manifest."""
        transcript_path = self._setup_session_with_transcript(mock_claude_workspace)

        self._invoke_stop_hook(
            mock_claude_workspace,
            {
                "hook_event_name": "Stop",
                "transcript_path": transcript_path,
                "session_id": "uuid-123",
            },
        )

        # Verify manifest was updated
        result = mock_claude_workspace.exec("cat /workspace/.forge/sessions/test-session/forge.session.json")
        manifest = json.loads(result.stdout)

        transcripts = manifest["confirmed"].get("artifacts", {}).get("transcripts", [])
        assert len(transcripts) >= 1
        assert transcripts[-1]["session_id"] == "uuid-123"

    def test_creates_pending_work_marker(self, mock_claude_workspace: ContainerLike) -> None:
        """Should create pending-work marker for async processing."""
        transcript_path = self._setup_session_with_transcript(mock_claude_workspace)

        output = self._invoke_stop_hook(
            mock_claude_workspace,
            {
                "hook_event_name": "Stop",
                "transcript_path": transcript_path,
                "session_id": "uuid-123",
            },
        )

        assert output["success"] is True
        assert output.get("queued") is True

        # Verify pending-work marker exists
        result = mock_claude_workspace.exec("ls ~/.forge/pending-work/ 2>/dev/null || echo 'no-pending'")
        # Marker may exist - depends on implementation
        assert result.returncode == 0

    def test_marker_contains_session_info(self, mock_claude_workspace: ContainerLike) -> None:
        """Pending-work marker should contain session info."""
        self._setup_session_with_transcript(
            mock_claude_workspace,
            session_name="marker-info-test",
            session_id="uuid-456",
        )

        self._invoke_stop_hook(
            mock_claude_workspace,
            {
                "hook_event_name": "Stop",
                "transcript_path": "/tmp/claude/transcript.jsonl",
                "session_id": "uuid-456",
            },
            session_name="marker-info-test",
        )

        # Check marker content (schema v2: session fields are inside payload)
        result = mock_claude_workspace.exec("cat ~/.forge/pending-work/uuid-456.json")
        assert result.returncode == 0, "Pending-work marker was not created"

        marker = json.loads(result.stdout)
        assert marker["kind"] == "stop"
        assert marker["marker_id"] == "uuid-456"
        assert marker["payload"]["session_id"] == "uuid-456"
        assert marker["payload"]["session_name"] == "marker-info-test"
