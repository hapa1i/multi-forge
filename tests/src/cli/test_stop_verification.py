"""Tests for Stop-hook verification policy.

These tests validate the completion_promise verification behavior:
- Checks only the last assistant message
- Promise must appear on a standalone line
- Blocks Stop with exit code 2 + stderr when configured to block
- Supports bypass via overrides (verification.bypass)

Note: Stop hook copies transcript to artifacts; we use a small synthetic transcript.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from forge.cli.hooks import hooks
from forge.session import SessionStore, create_session_state
from forge.session.models import VerificationConfig


def _write_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SessionStore:
    manifest = create_session_state(
        "test-session",
        proxy_template="test-family",
        proxy_base_url="http://localhost:8080",
    )
    store = SessionStore(str(tmp_path), "test-session")
    store.write(manifest)

    monkeypatch.setenv("FORGE_SESSION", "test-session")
    return store


def _write_transcript_requestid_format(path: Path, *, text: str) -> None:
    # Newest assistant message at later timestamp
    lines = [
        json.dumps(
            {
                "requestId": "r1",
                "timestamp": "2025-01-01T00:00:01Z",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "older"}],
                },
            }
        ),
        json.dumps(
            {
                "requestId": "r2",
                "timestamp": "2025-01-01T00:00:02Z",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": text}],
                },
            }
        ),
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


class TestStopVerification:
    def test_blocks_when_promise_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        store = _write_session(tmp_path, monkeypatch)

        # Enable verification in intent
        manifest = store.read()
        manifest.intent.verification = VerificationConfig(promise="<done>COMPLETE</done>")
        store.write(manifest)

        transcript = tmp_path / "t.jsonl"
        _write_transcript_requestid_format(transcript, text="not done yet")

        runner = CliRunner()
        payload = {
            "hook_event_name": "Stop",
            "transcript_path": str(transcript),
            "session_id": "uuid-123",
        }
        result = runner.invoke(hooks, ["stop"], input=json.dumps(payload))

        assert result.exit_code == 2
        assert "Verification incomplete" in result.stderr
        # Should mention escape hatch
        assert "%cancel-verification" in result.stderr

    def test_allows_when_promise_present_standalone_line(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        store = _write_session(tmp_path, monkeypatch)

        manifest = store.read()
        manifest.intent.verification = VerificationConfig(promise="<done>COMPLETE</done>")
        store.write(manifest)

        transcript = tmp_path / "t.jsonl"
        _write_transcript_requestid_format(transcript, text="work done\n<done>COMPLETE</done>\nthanks")

        runner = CliRunner()
        payload = {
            "hook_event_name": "Stop",
            "transcript_path": str(transcript),
            "session_id": "uuid-123",
        }
        result = runner.invoke(hooks, ["stop"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert out["success"] is True
        assert out["action"] in ("copied", "partial")

    def test_allows_when_bypassed_via_override(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        store = _write_session(tmp_path, monkeypatch)

        manifest = store.read()
        manifest.intent.verification = VerificationConfig(promise="<done>COMPLETE</done>")
        # Bypass in overrides
        manifest.overrides = {"verification": {"bypass": True}}
        store.write(manifest)

        transcript = tmp_path / "t.jsonl"
        _write_transcript_requestid_format(transcript, text="not done yet")

        runner = CliRunner()
        payload = {
            "hook_event_name": "Stop",
            "transcript_path": str(transcript),
            "session_id": "uuid-123",
        }
        result = runner.invoke(hooks, ["stop"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert out["success"] is True

    def test_warn_mode_does_not_block(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        store = _write_session(tmp_path, monkeypatch)

        manifest = store.read()
        manifest.intent.verification = VerificationConfig(
            promise="<done>COMPLETE</done>",
            on_incomplete="warn",
        )
        store.write(manifest)

        transcript = tmp_path / "t.jsonl"
        _write_transcript_requestid_format(transcript, text="not done yet")

        runner = CliRunner()
        payload = {
            "hook_event_name": "Stop",
            "transcript_path": str(transcript),
            "session_id": "uuid-123",
        }
        result = runner.invoke(hooks, ["stop"], input=json.dumps(payload))

        assert result.exit_code == 0
        assert "Warning: Verification incomplete" in result.stderr

    def test_auto_bypass_after_max_iterations(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        store = _write_session(tmp_path, monkeypatch)

        manifest = store.read()
        manifest.intent.verification = VerificationConfig(
            promise="<done>COMPLETE</done>",
            max_iterations=0,
        )
        # If max_iterations=0, first failure should auto-bypass (iterations+1 > 0)
        store.write(manifest)

        transcript = tmp_path / "t.jsonl"
        _write_transcript_requestid_format(transcript, text="not done yet")

        runner = CliRunner()
        payload = {
            "hook_event_name": "Stop",
            "transcript_path": str(transcript),
            "session_id": "uuid-123",
        }
        result = runner.invoke(hooks, ["stop"], input=json.dumps(payload))

        assert result.exit_code == 0
        assert "auto-bypassed" in result.stderr

        updated = store.read()
        assert updated.overrides.get("verification", {}).get("bypass") is True

    def test_auto_bypass_after_max_minutes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Stop auto-bypasses when elapsed time exceeds max_minutes."""
        from forge.session.models import VerificationConfirmed

        monkeypatch.chdir(tmp_path)
        store = _write_session(tmp_path, monkeypatch)

        manifest = store.read()
        manifest.intent.verification = VerificationConfig(
            promise="<done>COMPLETE</done>",
            max_minutes=1,  # 1 minute limit
        )
        # Pre-seed started_at to far in the past (simulating elapsed time > 1 minute)
        manifest.confirmed.verification = VerificationConfirmed(
            started_at="2020-01-01T00:00:00Z",
            iterations=1,
        )
        store.write(manifest)

        transcript = tmp_path / "t.jsonl"
        _write_transcript_requestid_format(transcript, text="not done yet")

        runner = CliRunner()
        payload = {
            "hook_event_name": "Stop",
            "transcript_path": str(transcript),
            "session_id": "uuid-123",
        }
        result = runner.invoke(hooks, ["stop"], input=json.dumps(payload))

        assert result.exit_code == 0  # Auto-bypassed, not blocked
        # Match actual stderr output: "Verification auto-bypassed: exceeded max_minutes (1)."
        assert "auto-bypassed" in result.stderr
        assert "max_minutes" in result.stderr
        assert "(1)" in result.stderr  # Configured limit appears

        updated = store.read()
        assert updated.confirmed.verification is not None
        assert updated.confirmed.verification.last_result == "max_minutes"
        assert updated.confirmed.verification.last_error is not None
        assert "Exceeded" in updated.confirmed.verification.last_error
        assert updated.overrides.get("verification", {}).get("bypass") is True

    def test_uses_timestamp_not_requestid_for_last_message(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify timestamp-based ordering when messages share the same requestId.

        This test proves the fix: two assistant messages with the SAME requestId
        but different timestamps. The later timestamp should win, not the file order.
        """
        monkeypatch.chdir(tmp_path)
        store = _write_session(tmp_path, monkeypatch)

        manifest = store.read()
        manifest.intent.verification = VerificationConfig(promise="<done>COMPLETE</done>")
        store.write(manifest)

        # Create transcript with same requestId but different timestamps
        # The EARLIER file entry has the LATER timestamp (contains promise)
        # The LATER file entry has the EARLIER timestamp (no promise)
        # If we used file order or requestId grouping, we'd get wrong result
        transcript = tmp_path / "t.jsonl"
        lines = [
            # First in file, but LATER timestamp - this should win
            json.dumps(
                {
                    "requestId": "same-request",
                    "timestamp": "2025-01-01T00:00:10Z",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "done\n<done>COMPLETE</done>"}],
                    },
                }
            ),
            # Second in file, but EARLIER timestamp - this should NOT win
            json.dumps(
                {
                    "requestId": "same-request",
                    "timestamp": "2025-01-01T00:00:05Z",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "not done yet"}],
                    },
                }
            ),
            "",
        ]
        transcript.write_text("\n".join(lines), encoding="utf-8")

        runner = CliRunner()
        payload = {
            "hook_event_name": "Stop",
            "transcript_path": str(transcript),
            "session_id": "uuid-123",
        }
        result = runner.invoke(hooks, ["stop"], input=json.dumps(payload))

        # Should pass because timestamp 00:00:10 > 00:00:05, and that message has the promise
        assert result.exit_code == 0, f"Expected pass (later timestamp has promise). stderr: {result.stderr}"
        out = json.loads(result.output)
        assert out["success"] is True

    def test_stop_records_policy_provenance(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Stop hook always records forge_version in confirmed.policy."""
        import forge

        monkeypatch.chdir(tmp_path)
        store = _write_session(tmp_path, monkeypatch)

        # Create minimal transcript (no verification configured)
        transcript = tmp_path / "t.jsonl"
        _write_transcript_requestid_format(transcript, text="some work done")

        runner = CliRunner()
        payload = {
            "hook_event_name": "Stop",
            "transcript_path": str(transcript),
            "session_id": "uuid-123",
        }
        result = runner.invoke(hooks, ["stop"], input=json.dumps(payload))

        assert result.exit_code == 0

        # Re-read manifest and check provenance
        updated = store.read()
        assert updated.confirmed.policy is not None
        assert updated.confirmed.policy.forge_version == forge.__version__

    def test_stop_preserves_existing_policy_state(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Stop hook preserves existing policy state (from PreToolUse) while updating forge_version."""
        import forge
        from forge.session.models import PolicyConfirmed

        monkeypatch.chdir(tmp_path)
        store = _write_session(tmp_path, monkeypatch)

        # Pre-seed policy state (as if PreToolUse had set it)
        manifest = store.read()
        manifest.confirmed.policy = PolicyConfirmed(
            forge_version="old-version",
            bundles=["tdd", "coding_standards"],
            rules_active=["no-bsd-sed", "tests-before-impl"],
            decisions=[{"rule": "no-bsd-sed", "outcome": "allowed"}],
            policy_states={
                "tdd.tests-before-impl": {"tests_touched": ["tests/test_foo.py"]},
                "semantic.supervisor": {
                    "cache": {
                        "hash123": {
                            "verdict": "aligned",
                            "cached_at": "2025-01-01T00:00:00Z",
                        }
                    }
                },
            },
        )
        store.write(manifest)

        transcript = tmp_path / "t.jsonl"
        _write_transcript_requestid_format(transcript, text="some work done")

        runner = CliRunner()
        payload = {
            "hook_event_name": "Stop",
            "transcript_path": str(transcript),
            "session_id": "uuid-123",
        }
        result = runner.invoke(hooks, ["stop"], input=json.dumps(payload))

        assert result.exit_code == 0

        # Re-read and verify: forge_version updated, everything else preserved
        updated = store.read()
        policy = updated.confirmed.policy
        assert policy is not None
        assert policy.forge_version == forge.__version__  # Updated
        assert policy.bundles == ["tdd", "coding_standards"]  # Preserved
        assert policy.rules_active == ["no-bsd-sed", "tests-before-impl"]  # Preserved
        assert policy.decisions == [{"rule": "no-bsd-sed", "outcome": "allowed"}]  # Preserved
        assert policy.policy_states == {
            "tdd.tests-before-impl": {"tests_touched": ["tests/test_foo.py"]},
            "semantic.supervisor": {
                "cache": {
                    "hash123": {
                        "verdict": "aligned",
                        "cached_at": "2025-01-01T00:00:00Z",
                    }
                }
            },
        }  # Preserved


class TestSessionEndHook:
    """Tests for session-end hook (no-op due to anthropics/claude-code#9090)."""

    def test_session_end_is_noop(self) -> None:
        """session-end hook is a no-op placeholder (CC suppresses output)."""
        runner = CliRunner()
        result = runner.invoke(hooks, ["session-end"])
        assert result.exit_code == 0


class TestTestSuiteVerification:
    """Tests for test_suite verification type."""

    def _make_mock_result(self, returncode: int, stderr: str = "") -> object:
        """Create mock subprocess.CompletedProcess-like object."""
        from unittest.mock import Mock

        mock = Mock()
        mock.returncode = returncode
        mock.stderr = stderr.encode("utf-8")
        return mock

    def test_test_suite_passes_when_tests_pass(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """test_suite allows Stop when uv run pytest exits 0."""
        import subprocess

        monkeypatch.chdir(tmp_path)
        store = _write_session(tmp_path, monkeypatch)

        manifest = store.read()
        manifest.intent.verification = VerificationConfig(type="test_suite")
        store.write(manifest)

        transcript = tmp_path / "t.jsonl"
        _write_transcript_requestid_format(transcript, text="some work")

        # Mock subprocess.run to return success
        monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: self._make_mock_result(0))

        runner = CliRunner()
        payload = {
            "hook_event_name": "Stop",
            "transcript_path": str(transcript),
            "session_id": "uuid-123",
        }
        result = runner.invoke(hooks, ["stop"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert out["success"] is True

        updated = store.read()
        assert updated.confirmed.verification is not None
        assert updated.confirmed.verification.last_result == "passed"

    def test_test_suite_blocks_when_tests_fail(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """test_suite blocks Stop when uv run pytest exits non-zero."""
        import subprocess

        monkeypatch.chdir(tmp_path)
        store = _write_session(tmp_path, monkeypatch)

        manifest = store.read()
        manifest.intent.verification = VerificationConfig(type="test_suite")
        store.write(manifest)

        transcript = tmp_path / "t.jsonl"
        _write_transcript_requestid_format(transcript, text="some work")

        # Mock subprocess.run to return failure
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *args, **kwargs: self._make_mock_result(1, stderr="FAILED test_foo.py"),
        )

        runner = CliRunner()
        payload = {
            "hook_event_name": "Stop",
            "transcript_path": str(transcript),
            "session_id": "uuid-123",
        }
        result = runner.invoke(hooks, ["stop"], input=json.dumps(payload))

        assert result.exit_code == 2
        assert "tests did not pass" in result.stderr
        assert "%cancel-verification" in result.stderr

        updated = store.read()
        assert updated.confirmed.verification is not None
        assert updated.confirmed.verification.last_result == "failed"
        assert updated.confirmed.verification.last_error is not None
        assert "exit 1" in updated.confirmed.verification.last_error

    def test_test_suite_respects_max_iterations(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """test_suite auto-bypasses after max_iterations."""
        import subprocess

        monkeypatch.chdir(tmp_path)
        store = _write_session(tmp_path, monkeypatch)

        manifest = store.read()
        manifest.intent.verification = VerificationConfig(
            type="test_suite",
            max_iterations=0,  # Auto-bypass on first failure
        )
        store.write(manifest)

        transcript = tmp_path / "t.jsonl"
        _write_transcript_requestid_format(transcript, text="some work")

        # Mock subprocess.run to return failure
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *args, **kwargs: self._make_mock_result(1, stderr="FAILED"),
        )

        runner = CliRunner()
        payload = {
            "hook_event_name": "Stop",
            "transcript_path": str(transcript),
            "session_id": "uuid-123",
        }
        result = runner.invoke(hooks, ["stop"], input=json.dumps(payload))

        assert result.exit_code == 0  # Auto-bypassed
        assert "auto-bypassed" in result.stderr
        assert "max_iterations" in result.stderr

        updated = store.read()
        assert updated.overrides.get("verification", {}).get("bypass") is True

    def test_test_suite_timeout_returns_failure(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """test_suite treats timeout as failure."""
        import subprocess

        monkeypatch.chdir(tmp_path)
        store = _write_session(tmp_path, monkeypatch)

        manifest = store.read()
        manifest.intent.verification = VerificationConfig(
            type="test_suite",
            test_timeout_seconds=1,  # Short timeout
        )
        store.write(manifest)

        transcript = tmp_path / "t.jsonl"
        _write_transcript_requestid_format(transcript, text="some work")

        # Mock subprocess.run to raise TimeoutExpired
        def mock_run(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd=["uv", "run", "pytest"], timeout=1)

        monkeypatch.setattr(subprocess, "run", mock_run)

        runner = CliRunner()
        payload = {
            "hook_event_name": "Stop",
            "transcript_path": str(transcript),
            "session_id": "uuid-123",
        }
        result = runner.invoke(hooks, ["stop"], input=json.dumps(payload))

        assert result.exit_code == 2  # Blocked
        assert "tests did not pass" in result.stderr

        updated = store.read()
        assert updated.confirmed.verification is not None
        assert updated.confirmed.verification.last_result == "failed"
        assert updated.confirmed.verification.last_error is not None
        assert "timeout" in updated.confirmed.verification.last_error
