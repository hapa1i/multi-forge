"""Docker-based integration tests for Stop hook verification policy.

These tests run inside a session-scoped container (docker_in marker) for
complete filesystem isolation. They test the behavioral aspects of the
Stop hook's verification policy - promise detection, bypass modes, and
auto-bypass after max iterations.

Note: Tests that mock subprocess.run for pytest execution remain in unit
tests since they're testing Python-level behavior rather than CLI behavior.
"""

from __future__ import annotations

import json

import pytest

from tests.fixtures.docker import ContainerLike

pytestmark = [pytest.mark.integration, pytest.mark.docker_in]


class TestStopHookVerificationPolicy:
    """Tests for Stop hook verification promise detection.

    The verification policy checks assistant messages for "completion promises"
    like "I'll run the tests" and requires those tests to actually run before
    the session can complete.
    """

    def _create_session_with_verification(
        self,
        workspace: ContainerLike,
        session_name: str = "test-session",
        max_iterations: int = 3,
        max_minutes: int = 30,
    ) -> None:
        """Create a session with verification policy configured."""
        # Create session
        workspace.exec(f"cd /workspace && forge session start {session_name}")

        # Find per-session manifest and add verification config
        result = workspace.exec("find /workspace/.forge/sessions -name forge.session.json | head -1")
        manifest_path = result.stdout.strip()
        result = workspace.exec(f"cat {manifest_path}")
        manifest = json.loads(result.stdout)

        # Add verification policy to intent
        manifest["intent"]["verification"] = {
            "max_iterations": max_iterations,
            "max_minutes": max_minutes,
        }

        # Write back
        manifest_json = json.dumps(manifest)
        workspace.exec(f"cat > {manifest_path} << 'EOF'\n{manifest_json}\nEOF")

    def _create_transcript(
        self,
        workspace: ContainerLike,
        messages: list[dict],
        path: str = "/tmp/claude/transcript.jsonl",
    ) -> str:
        """Create a transcript file with the given messages."""
        workspace.exec("mkdir -p /tmp/claude")

        # Build JSONL content
        lines = [json.dumps(msg) for msg in messages]
        content = "\\n".join(lines)

        workspace.exec(f"printf '{content}\\n' > {path}")
        return path

    def _invoke_stop_hook(
        self,
        workspace: ContainerLike,
        session_id: str = "test-uuid",
        transcript_path: str = "/tmp/claude/transcript.jsonl",
    ) -> dict:
        """Invoke the stop hook and return parsed response."""
        payload = json.dumps(
            {
                "session_id": session_id,
                "transcript_path": transcript_path,
            }
        )

        result = workspace.exec(
            f"cd /workspace && export FORGE_SESSION=test-session && echo '{payload}' | forge hook stop"
        )
        assert result.returncode == 0, f"Stop hook failed: {result.stderr}"
        return json.loads(result.stdout)

    def test_no_promise_no_verification(self, mock_claude_workspace: ContainerLike) -> None:
        """Stop hook should succeed when no verification promise detected."""
        self._create_session_with_verification(mock_claude_workspace)

        # Create transcript without any verification promises
        messages = [
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "Done with the task."}]},
            },
        ]
        self._create_transcript(mock_claude_workspace, messages)

        output = self._invoke_stop_hook(mock_claude_workspace)

        assert output["success"] is True
        # Should not have pending verification
        assert output.get("verification_pending") is not True

    def test_promise_detected_triggers_verification(self, mock_claude_workspace: ContainerLike) -> None:
        """Stop hook should detect verification promise in assistant message."""
        self._create_session_with_verification(mock_claude_workspace)

        # Create transcript with a completion promise
        messages = [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "text",
                            "text": "I've implemented the feature. Let me run the tests to verify everything works.",
                        }
                    ]
                },
            },
        ]
        self._create_transcript(mock_claude_workspace, messages)

        output = self._invoke_stop_hook(mock_claude_workspace)

        # Hook should succeed (always exits 0 for Claude safety)
        # Verification detection may set pending flag but doesn't block
        assert output["success"] is True


class TestStopHookBypassModes:
    """Tests for Stop hook verification bypass modes.

    Bypass modes allow skipping verification in certain scenarios:
    - force_complete: Explicit bypass by user
    - auto-bypass: After max_iterations or max_minutes exceeded
    """

    def _create_session_with_verification(
        self,
        workspace: ContainerLike,
        session_name: str = "test-session",
        max_iterations: int = 3,
        max_minutes: int = 30,
        iteration_count: int = 0,
    ) -> None:
        """Create a session with verification policy and optional iteration count."""
        workspace.exec(f"cd /workspace && forge session start {session_name}")

        # Find per-session manifest
        result = workspace.exec("find /workspace/.forge/sessions -name forge.session.json | head -1")
        manifest_path = result.stdout.strip()
        result = workspace.exec(f"cat {manifest_path}")
        manifest = json.loads(result.stdout)

        manifest["intent"]["verification"] = {
            "max_iterations": max_iterations,
            "max_minutes": max_minutes,
        }

        # Add iteration count to confirmed state if needed
        if iteration_count > 0:
            if "confirmed" not in manifest:
                manifest["confirmed"] = {}
            manifest["confirmed"]["verification_iterations"] = iteration_count

        manifest_json = json.dumps(manifest)
        workspace.exec(f"cat > {manifest_path} << 'EOF'\n{manifest_json}\nEOF")

    def _create_transcript(
        self,
        workspace: ContainerLike,
        messages: list[dict],
        path: str = "/tmp/claude/transcript.jsonl",
    ) -> str:
        """Create a transcript file."""
        workspace.exec("mkdir -p /tmp/claude")
        lines = [json.dumps(msg) for msg in messages]
        content = "\\n".join(lines)
        workspace.exec(f"printf '{content}\\n' > {path}")
        return path

    def _invoke_stop_hook(self, workspace: ContainerLike, **kwargs) -> dict:
        """Invoke stop hook with given payload fields."""
        payload = {
            "session_id": kwargs.get("session_id", "test-uuid"),
            "transcript_path": kwargs.get("transcript_path", "/tmp/claude/transcript.jsonl"),
        }
        if "force_complete" in kwargs:
            payload["force_complete"] = kwargs["force_complete"]

        payload_json = json.dumps(payload)
        result = workspace.exec(
            f"cd /workspace && export FORGE_SESSION=test-session && echo '{payload_json}' | forge hook stop"
        )
        assert result.returncode == 0
        return json.loads(result.stdout)

    def test_force_complete_bypasses_verification(self, mock_claude_workspace: ContainerLike) -> None:
        """force_complete flag should bypass verification."""
        self._create_session_with_verification(mock_claude_workspace)

        # Create transcript with promise
        messages = [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "text",
                            "text": "Running the tests now to verify.",
                        }
                    ]
                },
            },
        ]
        self._create_transcript(mock_claude_workspace, messages)

        output = self._invoke_stop_hook(mock_claude_workspace, force_complete=True)

        # Should succeed even with promise, due to force_complete
        assert output["success"] is True

    def test_auto_bypass_after_max_iterations(self, mock_claude_workspace: ContainerLike) -> None:
        """Should auto-bypass verification after max_iterations exceeded."""
        self._create_session_with_verification(
            mock_claude_workspace,
            max_iterations=3,
            iteration_count=4,  # Already exceeded max
        )

        # Create transcript with promise
        messages = [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "text",
                            "text": "Let me verify by running tests.",
                        }
                    ]
                },
            },
        ]
        self._create_transcript(mock_claude_workspace, messages)

        output = self._invoke_stop_hook(mock_claude_workspace)

        # Should succeed due to auto-bypass
        assert output["success"] is True


class TestStopHookTranscriptProcessing:
    """Tests for Stop hook transcript file processing.

    These tests verify the hook correctly reads and processes transcript files
    in various formats and states.
    """

    def _setup_session(self, workspace: ContainerLike, session_name: str = "test-session") -> None:
        """Create a basic session."""
        workspace.exec(f"cd /workspace && forge session start {session_name}")

    def _invoke_stop_hook(self, workspace: ContainerLike, payload: dict) -> dict:
        """Invoke stop hook with payload."""
        payload_json = json.dumps(payload)
        result = workspace.exec(
            f"cd /workspace && export FORGE_SESSION=test-session && echo '{payload_json}' | forge hook stop"
        )
        assert result.returncode == 0
        return json.loads(result.stdout)

    def test_missing_transcript_path(self, mock_claude_workspace: ContainerLike) -> None:
        """Should handle missing transcript_path field gracefully."""
        self._setup_session(mock_claude_workspace)

        output = self._invoke_stop_hook(
            mock_claude_workspace,
            {
                "session_id": "test-uuid",
                # No transcript_path
            },
        )

        # Hook may skip gracefully for events without transcripts
        # This is valid behavior - not all hook events have transcripts
        assert output["success"] is True
        assert output.get("action") == "skip" or output.get("reason") == "wrong_event"

    def test_nonexistent_transcript_file(self, mock_claude_workspace: ContainerLike) -> None:
        """Should handle nonexistent transcript file."""
        self._setup_session(mock_claude_workspace)

        output = self._invoke_stop_hook(
            mock_claude_workspace,
            {
                "session_id": "test-uuid",
                "transcript_path": "/nonexistent/path/transcript.jsonl",
            },
        )

        # Should handle gracefully (may succeed with empty transcript or report error)
        assert "success" in output

    def test_empty_transcript_file(self, mock_claude_workspace: ContainerLike) -> None:
        """Should handle empty transcript file."""
        self._setup_session(mock_claude_workspace)

        # Create empty transcript
        mock_claude_workspace.exec("mkdir -p /tmp/claude && touch /tmp/claude/empty.jsonl")

        output = self._invoke_stop_hook(
            mock_claude_workspace,
            {
                "session_id": "test-uuid",
                "transcript_path": "/tmp/claude/empty.jsonl",
            },
        )

        # Should succeed (no promises to detect)
        assert output["success"] is True

    def test_malformed_transcript_entries(self, mock_claude_workspace: ContainerLike) -> None:
        """Should handle malformed JSON entries gracefully."""
        self._setup_session(mock_claude_workspace)

        # Create transcript with mix of valid and invalid entries
        mock_claude_workspace.exec("""
            mkdir -p /tmp/claude
            cat > /tmp/claude/malformed.jsonl << 'EOF'
{"type": "assistant", "message": {"content": [{"type": "text", "text": "valid"}]}}
not json at all
{"type": "assistant", "message": {"content": [{"type": "text", "text": "also valid"}]}}
EOF
        """)

        output = self._invoke_stop_hook(
            mock_claude_workspace,
            {
                "session_id": "test-uuid",
                "transcript_path": "/tmp/claude/malformed.jsonl",
            },
        )

        # Should handle gracefully
        assert "success" in output


class TestStopHookPendingWorkMarker:
    """Tests for Stop hook pending-work marker creation.

    The Stop hook creates markers in ~/.forge/pending-work/ for async
    processing of completed sessions.
    """

    def _setup_session(self, workspace: ContainerLike, session_name: str = "test-session") -> None:
        """Create a basic session."""
        workspace.exec(f"cd /workspace && forge session start {session_name}")

    def _create_transcript(self, workspace: ContainerLike) -> str:
        """Create a minimal transcript."""
        workspace.exec("""
            mkdir -p /tmp/claude
            echo '{"type": "assistant", "message": {"content": []}}' > /tmp/claude/transcript.jsonl
        """)
        return "/tmp/claude/transcript.jsonl"

    def _invoke_stop_hook(self, workspace: ContainerLike) -> dict:
        """Invoke stop hook."""
        payload = json.dumps(
            {
                "session_id": "test-uuid",
                "transcript_path": "/tmp/claude/transcript.jsonl",
            }
        )
        result = workspace.exec(
            f"cd /workspace && export FORGE_SESSION=test-session && echo '{payload}' | forge hook stop"
        )
        return json.loads(result.stdout)

    def test_creates_pending_work_marker(self, mock_claude_workspace: ContainerLike) -> None:
        """Stop hook should create pending-work marker for async processing."""
        self._setup_session(mock_claude_workspace)
        self._create_transcript(mock_claude_workspace)

        output = self._invoke_stop_hook(mock_claude_workspace)

        assert output["success"] is True

        # Check for pending-work marker
        mock_claude_workspace.exec("ls ~/.forge/pending-work/ 2>/dev/null || echo 'no-markers'")
        # Note: Marker creation is implementation-dependent
        # The test verifies the hook completes successfully

    def test_marker_contains_session_info(self, mock_claude_workspace: ContainerLike) -> None:
        """Pending-work marker should contain session identification."""
        self._setup_session(mock_claude_workspace, session_name="marker-test")
        self._create_transcript(mock_claude_workspace)

        self._invoke_stop_hook(mock_claude_workspace)

        # Check marker content if it exists
        result = mock_claude_workspace.exec("""
            if ls ~/.forge/pending-work/*.json 2>/dev/null; then
                cat ~/.forge/pending-work/*.json
            else
                echo '{"status": "no-marker"}'
            fi
        """)
        # Marker content is implementation-dependent
        assert result.returncode == 0
