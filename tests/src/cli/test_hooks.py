"""Tests for CLI hook commands."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from forge.cli.hooks import (
    _get_last_assistant_text_for_verification,
    _run_verification_check,
    hooks,
)
from forge.session import SessionStore, create_session_state
from forge.session.models import VerificationConfig

# Test constants
DEFAULT_PROXY_FAMILY = "test-family"
DEFAULT_PROXY_URL = "http://localhost:8080"


class TestSessionStartCommand:
    """Tests for `forge hook session-start` command."""

    def test_empty_stdin(self) -> None:
        """Should return error for empty stdin."""
        runner = CliRunner()
        result = runner.invoke(hooks, ["session-start"], input="")

        assert result.exit_code == 0  # Always exit 0
        output = json.loads(result.output)
        assert output["success"] is False
        assert output["error"] == "invalid_input"
        assert "No input" in output["message"]

    def test_invalid_json(self) -> None:
        """Should return error for invalid JSON."""
        runner = CliRunner()
        result = runner.invoke(hooks, ["session-start"], input="not json")

        assert result.exit_code == 0  # Always exit 0
        output = json.loads(result.output)
        assert output["success"] is False
        assert output["error"] == "invalid_input"
        assert "Invalid JSON" in output["message"]

    def test_missing_required_fields(self) -> None:
        """Should return error for missing required fields."""
        runner = CliRunner()
        data = json.dumps({"session_id": "uuid-123"})  # Missing transcript_path and source
        result = runner.invoke(hooks, ["session-start"], input=data)

        assert result.exit_code == 0  # Always exit 0
        output = json.loads(result.output)
        assert output["success"] is False
        assert output["error"] == "invalid_input"
        assert "required fields" in output["message"]

    def test_invalid_source_value(self) -> None:
        """Should return error for invalid source value."""
        runner = CliRunner()
        data = json.dumps(
            {
                "session_id": "uuid-123",
                "transcript_path": "/path/to/file.jsonl",
                "source": "invalid_source",
            }
        )
        result = runner.invoke(hooks, ["session-start"], input=data)

        assert result.exit_code == 0  # Always exit 0
        output = json.loads(result.output)
        assert output["success"] is False
        assert output["error"] == "invalid_input"

    def test_session_not_found(self, tmp_path: Path) -> None:
        """Should return error when session cannot be resolved."""
        runner = CliRunner()
        data = json.dumps(
            {
                "session_id": "unknown-uuid",
                "transcript_path": "/path/to/file.jsonl",
                "source": "startup",
            }
        )

        # Use --cwd to point to temp directory with no session
        result = runner.invoke(hooks, ["session-start", "--cwd", str(tmp_path)], input=data)

        assert result.exit_code == 0  # Always exit 0
        output = json.loads(result.output)
        assert output["success"] is False
        assert output["error"] == "session_not_found"

    def test_successful_startup(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should successfully handle startup hook."""
        # Create manifest and persist session name
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()

        manifest = create_session_state(
            "test-session",
            proxy_template=DEFAULT_PROXY_FAMILY,
            proxy_base_url=DEFAULT_PROXY_URL,
        )
        manifest.confirmed.claude_session_id = "original-uuid"
        store = SessionStore(str(tmp_path), "test-session")
        store.write(manifest)

        monkeypatch.setenv("FORGE_SESSION", "test-session")
        monkeypatch.setenv("FORGE_FORGE_ROOT", str(tmp_path))

        runner = CliRunner()
        data = json.dumps(
            {
                "session_id": "new-uuid-456",
                "transcript_path": "/path/to/transcript.jsonl",
                "source": "startup",
            }
        )

        result = runner.invoke(hooks, ["session-start", "--cwd", str(tmp_path)], input=data)

        assert result.exit_code == 0
        output = json.loads(result.output)
        assert output["success"] is True
        assert output["session_name"] == "test-session"
        assert output["received_session_id"] == "new-uuid-456"
        assert output["received_source"] == "startup"

    def test_compact_overwrites_uuid(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should overwrite UUID on compact (1:1 session model)."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()

        manifest = create_session_state(
            "test-session",
            proxy_template=DEFAULT_PROXY_FAMILY,
            proxy_base_url=DEFAULT_PROXY_URL,
        )
        manifest.confirmed.claude_session_id = "original-uuid"
        store = SessionStore(str(tmp_path), "test-session")
        store.write(manifest)

        monkeypatch.setenv("FORGE_SESSION", "test-session")
        monkeypatch.setenv("FORGE_FORGE_ROOT", str(tmp_path))

        runner = CliRunner()
        data = json.dumps(
            {
                "session_id": "new-uuid-after-compact",
                "transcript_path": "/path/to/transcript.jsonl",
                "source": "compact",
            }
        )

        result = runner.invoke(hooks, ["session-start", "--cwd", str(tmp_path)], input=data)

        assert result.exit_code == 0
        output = json.loads(result.output)
        assert output["success"] is True

        # Verify UUID was overwritten (1:1 model, no history accumulation)
        updated_manifest = store.read()
        assert updated_manifest.confirmed.claude_session_id == "new-uuid-after-compact"


class TestGetLastAssistantTextForVerification:
    """Tests for _get_last_assistant_text_for_verification helper."""

    def test_empty_file(self, tmp_path: Path) -> None:
        """Should return None for empty transcript."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text("")
        assert _get_last_assistant_text_for_verification(str(transcript)) is None

    def test_no_assistant_messages(self, tmp_path: Path) -> None:
        """Should return None when no assistant messages."""
        transcript = tmp_path / "transcript.jsonl"
        lines = [
            json.dumps({"type": "human"}),
            json.dumps({"type": "system"}),
        ]
        transcript.write_text("\n".join(lines))
        assert _get_last_assistant_text_for_verification(str(transcript)) is None

    def test_single_assistant_message(self, tmp_path: Path) -> None:
        """Should extract text from single assistant message."""
        transcript = tmp_path / "transcript.jsonl"
        lines = [
            json.dumps(
                {
                    "type": "assistant",
                    "message": {"content": [{"type": "text", "text": "Hello world!"}]},
                }
            )
        ]
        transcript.write_text("\n".join(lines))
        result = _get_last_assistant_text_for_verification(str(transcript))
        assert result == "Hello world!"

    def test_multiple_assistant_messages_gets_last(self, tmp_path: Path) -> None:
        """Should return text from the most recent assistant message."""
        transcript = tmp_path / "transcript.jsonl"
        lines = [
            json.dumps(
                {
                    "type": "assistant",
                    "message": {"content": [{"type": "text", "text": "First message"}]},
                }
            ),
            json.dumps({"type": "human"}),
            json.dumps(
                {
                    "type": "assistant",
                    "message": {"content": [{"type": "text", "text": "Last message"}]},
                }
            ),
        ]
        transcript.write_text("\n".join(lines))
        result = _get_last_assistant_text_for_verification(str(transcript))
        assert result == "Last message"

    def test_multiple_content_blocks(self, tmp_path: Path) -> None:
        """Should concatenate multiple text blocks."""
        transcript = tmp_path / "transcript.jsonl"
        lines = [
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {"type": "tool_use", "name": "Read"},
                            {"type": "text", "text": "Part 1"},
                            {"type": "text", "text": "Part 2"},
                        ]
                    },
                }
            )
        ]
        transcript.write_text("\n".join(lines))
        result = _get_last_assistant_text_for_verification(str(transcript))
        # Implementation joins text blocks without separator
        assert result == "Part 1Part 2"

    def test_nonexistent_file(self) -> None:
        """Should return None for nonexistent file."""
        assert _get_last_assistant_text_for_verification("/does/not/exist.jsonl") is None


class TestRunVerificationCheck:
    """Tests for _run_verification_check function."""

    def _create_session_with_verification(
        self,
        tmp_path: Path,
        promise: str | None,
        bypass: bool = False,
        on_incomplete: str = "block",
        max_iterations: int = 50,
        max_minutes: int | None = None,
    ) -> tuple[SessionStore, Path]:
        """Helper to create a session with verification config."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(exist_ok=True)

        manifest = create_session_state(
            "test-session",
            proxy_template=DEFAULT_PROXY_FAMILY,
            proxy_base_url=DEFAULT_PROXY_URL,
        )
        manifest.intent.verification = VerificationConfig(
            promise=promise,
            bypass=bypass,
            on_incomplete=on_incomplete,
            max_iterations=max_iterations,
            max_minutes=max_minutes,
        )

        store = SessionStore(str(tmp_path), "test-session")
        store.write(manifest)

        return store, tmp_path

    def _create_transcript(self, tmp_path: Path, assistant_text: str) -> Path:
        """Helper to create a transcript file with assistant message."""
        transcript = tmp_path / "transcript.jsonl"
        lines = [
            json.dumps(
                {
                    "type": "assistant",
                    "message": {"content": [{"type": "text", "text": assistant_text}]},
                }
            )
        ]
        transcript.write_text("\n".join(lines))
        return transcript

    def test_no_verification_configured(self, tmp_path: Path) -> None:
        """Should allow stop when no verification configured."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()

        manifest = create_session_state(
            "test-session",
            proxy_template=DEFAULT_PROXY_FAMILY,
            proxy_base_url=DEFAULT_PROXY_URL,
        )
        # No verification config
        store = SessionStore(str(tmp_path), "test-session")
        store.write(manifest)

        transcript = self._create_transcript(tmp_path, "Some output")

        allow, message = _run_verification_check(store=store, manifest=manifest, transcript_path=transcript)
        assert allow is True
        assert message is None

    def test_no_promise_configured(self, tmp_path: Path) -> None:
        """Should allow stop when promise is None/empty."""
        store, wt_path = self._create_session_with_verification(tmp_path, promise=None)
        manifest = store.read()
        transcript = self._create_transcript(tmp_path, "Some output")

        allow, message = _run_verification_check(store=store, manifest=manifest, transcript_path=transcript)
        assert allow is True

    def test_bypass_allows_stop(self, tmp_path: Path) -> None:
        """Should allow stop when bypass is True."""
        store, wt_path = self._create_session_with_verification(tmp_path, promise="✓ COMPLETE", bypass=True)
        manifest = store.read()
        transcript = self._create_transcript(tmp_path, "No promise here")

        allow, message = _run_verification_check(store=store, manifest=manifest, transcript_path=transcript)
        assert allow is True

    def test_promise_found_allows_stop(self, tmp_path: Path) -> None:
        """Should allow stop when promise is found on standalone line."""
        store, wt_path = self._create_session_with_verification(tmp_path, promise="✓ COMPLETE")
        manifest = store.read()
        transcript = self._create_transcript(tmp_path, "Some work done.\n✓ COMPLETE\nMore text.")

        allow, message = _run_verification_check(store=store, manifest=manifest, transcript_path=transcript)
        assert allow is True

    def test_promise_not_found_blocks_stop(self, tmp_path: Path) -> None:
        """Should block stop when promise is missing."""
        store, wt_path = self._create_session_with_verification(tmp_path, promise="✓ COMPLETE", on_incomplete="block")
        manifest = store.read()
        transcript = self._create_transcript(tmp_path, "Work done, no completion signal.")

        allow, message = _run_verification_check(store=store, manifest=manifest, transcript_path=transcript)
        assert allow is False
        assert message is not None
        assert "verification" in message.lower() or "promise" in message.lower()

    def test_promise_not_found_warns_only(self, tmp_path: Path) -> None:
        """Should allow stop with warning when on_incomplete=warn."""
        store, wt_path = self._create_session_with_verification(tmp_path, promise="✓ COMPLETE", on_incomplete="warn")
        manifest = store.read()
        transcript = self._create_transcript(tmp_path, "No promise here")

        allow, message = _run_verification_check(store=store, manifest=manifest, transcript_path=transcript)
        assert allow is True  # Warn allows stop

    def test_promise_not_found_allow_mode(self, tmp_path: Path) -> None:
        """Should allow stop silently when on_incomplete=allow."""
        store, wt_path = self._create_session_with_verification(tmp_path, promise="✓ COMPLETE", on_incomplete="allow")
        manifest = store.read()
        transcript = self._create_transcript(tmp_path, "No promise here")

        allow, message = _run_verification_check(store=store, manifest=manifest, transcript_path=transcript)
        assert allow is True

    def test_whitespace_tolerance(self, tmp_path: Path) -> None:
        """Should match promise with leading/trailing whitespace on line."""
        store, wt_path = self._create_session_with_verification(tmp_path, promise="✓ COMPLETE")
        manifest = store.read()
        # Promise with extra whitespace
        transcript = self._create_transcript(tmp_path, "Work done.\n  ✓ COMPLETE  \nEnd.")

        allow, message = _run_verification_check(store=store, manifest=manifest, transcript_path=transcript)
        assert allow is True

    def test_multiline_promise_skips_verification(self, tmp_path: Path) -> None:
        """Should skip verification if promise contains newlines (misconfiguration)."""
        store, wt_path = self._create_session_with_verification(tmp_path, promise="Line1\nLine2")
        manifest = store.read()
        transcript = self._create_transcript(tmp_path, "Some output")

        allow, message = _run_verification_check(store=store, manifest=manifest, transcript_path=transcript)
        # Multi-line promises are treated as misconfiguration, skip verification
        assert allow is True

    def test_iterations_increment_on_block(self, tmp_path: Path) -> None:
        """Should increment iterations count when blocking."""
        store, wt_path = self._create_session_with_verification(tmp_path, promise="✓ COMPLETE", on_incomplete="block")
        manifest = store.read()
        transcript = self._create_transcript(tmp_path, "No promise")

        # First check
        allow, _ = _run_verification_check(store=store, manifest=manifest, transcript_path=transcript)
        assert allow is False

        # Reload manifest to check iterations
        manifest = store.read()
        assert manifest.confirmed.verification is not None
        assert manifest.confirmed.verification.iterations == 1

    def test_max_iterations_auto_bypass(self, tmp_path: Path) -> None:
        """Should auto-bypass after max_iterations reached."""
        store, wt_path = self._create_session_with_verification(tmp_path, promise="✓ COMPLETE", max_iterations=2)
        manifest = store.read()
        transcript = self._create_transcript(tmp_path, "No promise")

        # First block
        allow, _ = _run_verification_check(store=store, manifest=manifest, transcript_path=transcript)
        assert allow is False

        # Reload and check again
        manifest = store.read()
        allow, _ = _run_verification_check(store=store, manifest=manifest, transcript_path=transcript)
        assert allow is False

        # Third check should auto-bypass (iterations >= max)
        manifest = store.read()
        allow, message = _run_verification_check(store=store, manifest=manifest, transcript_path=transcript)
        assert allow is True  # Auto-bypassed


class TestCancelVerificationCommand:
    """Tests for %cancel-verification direct command."""

    def test_no_session_found(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should skip (fail-open) when no session can be resolved."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".claude").mkdir()

        runner = CliRunner()
        data = json.dumps({"prompt": "%cancel-verification"})
        result = runner.invoke(hooks, ["user-prompt-submit"], input=data)

        assert result.exit_code == 0
        output = json.loads(result.output)
        # With per-session dirs, no resolvable session → skip (fail-open)
        assert output["action"] == "skip"
        assert output["reason"] == "no_session"

    def test_no_verification_configured(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should return error when no verification configured."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("FORGE_SESSION", "test-session")
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()

        # Create session without verification
        manifest = create_session_state(
            "test-session",
            proxy_template=DEFAULT_PROXY_FAMILY,
            proxy_base_url=DEFAULT_PROXY_URL,
        )
        store = SessionStore(str(tmp_path), "test-session")
        store.write(manifest)

        runner = CliRunner()
        data = json.dumps({"prompt": "%cancel-verification"})
        result = runner.invoke(hooks, ["user-prompt-submit"], input=data)

        assert result.exit_code == 0
        output = json.loads(result.output)
        assert output["decision"] == "block"
        assert "No verification configured" in output["reason"]

    def test_already_bypassed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should return message when already bypassed."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("FORGE_SESSION", "test-session")
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()

        manifest = create_session_state(
            "test-session",
            proxy_template=DEFAULT_PROXY_FAMILY,
            proxy_base_url=DEFAULT_PROXY_URL,
        )
        manifest.intent.verification = VerificationConfig(promise="✓ COMPLETE", bypass=True)
        store = SessionStore(str(tmp_path), "test-session")
        store.write(manifest)

        runner = CliRunner()
        data = json.dumps({"prompt": "%cancel-verification"})
        result = runner.invoke(hooks, ["user-prompt-submit"], input=data)

        assert result.exit_code == 0
        output = json.loads(result.output)
        assert output["decision"] == "block"
        assert "already bypassed" in output["reason"].lower()

    def test_successful_bypass(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should successfully enable bypass."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("FORGE_SESSION", "test-session")
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()

        manifest = create_session_state(
            "test-session",
            proxy_template=DEFAULT_PROXY_FAMILY,
            proxy_base_url=DEFAULT_PROXY_URL,
        )
        manifest.intent.verification = VerificationConfig(promise="✓ COMPLETE", bypass=False)
        store = SessionStore(str(tmp_path), "test-session")
        store.write(manifest)

        runner = CliRunner()
        data = json.dumps({"prompt": "%cancel-verification"})
        result = runner.invoke(hooks, ["user-prompt-submit"], input=data)

        assert result.exit_code == 0
        output = json.loads(result.output)
        assert output["decision"] == "block"
        assert "bypass enabled" in output["reason"].lower()

        # Verify the override was persisted
        updated = store.read()
        assert "verification" in updated.overrides
        assert updated.overrides["verification"].get("bypass") is True
