"""Tests for new hook commands: pre-compact (repurposed), post-compact, worktree-create, subagent-stop."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from forge.cli.hooks._group import hooks
from forge.session.models import (
    CompactionConfirmed,
    SessionState,
    SubagentConfirmed,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _invoke(command_name: str, payload: dict) -> tuple[int, str, str]:
    """Invoke a hook command with JSON payload on stdin.

    Returns (exit_code, stdout, stderr).
    """
    runner = CliRunner()
    result = runner.invoke(
        hooks,
        [command_name],
        input=json.dumps(payload),
        catch_exceptions=False,
    )
    return result.exit_code, result.output, ""


def _make_state(name: str = "test-session") -> SessionState:
    from forge.core.state import now_iso

    return SessionState(
        schema_version=7,
        name=name,
        created_at=now_iso(),
        last_accessed_at=now_iso(),
    )


# ---------------------------------------------------------------------------
# PreCompact (repurposed: transcript capture)
# ---------------------------------------------------------------------------


class TestPreCompactTranscriptCapture:
    """PreCompact now captures transcript before compaction instead of blocking."""

    def test_exits_0_on_empty_stdin(self) -> None:
        runner = CliRunner()
        result = runner.invoke(hooks, ["pre-compact"], input="", catch_exceptions=False)
        assert result.exit_code == 0

    def test_exits_0_when_no_session(self, tmp_path: Path) -> None:
        payload = {
            "session_id": "abc123",
            "transcript_path": str(tmp_path / "transcript.jsonl"),
            "cwd": str(tmp_path),
        }
        exit_code, _, _ = _invoke("pre-compact", payload)
        assert exit_code == 0

    def test_exits_0_when_missing_transcript_path(self) -> None:
        payload = {"session_id": "abc123", "cwd": "/tmp"}
        exit_code, _, _ = _invoke("pre-compact", payload)
        assert exit_code == 0

    def test_exits_0_when_missing_session_id(self) -> None:
        payload = {"transcript_path": "/tmp/t.jsonl", "cwd": "/tmp"}
        exit_code, _, _ = _invoke("pre-compact", payload)
        assert exit_code == 0

    @patch("forge.cli.hooks.commands.resolve_session_store")
    @patch("forge.cli.hooks.commands.resolve_forge_root")
    @patch("forge.cli.hooks.commands.get_artifact_paths")
    @patch("forge.cli.hooks.commands.safe_copy_file")
    def test_copies_transcript_to_artifacts(
        self,
        mock_copy: MagicMock,
        mock_paths: MagicMock,
        mock_project: MagicMock,
        mock_store: MagicMock,
        tmp_path: Path,
    ) -> None:
        # Set up mocks
        state = _make_state()
        store = MagicMock()
        store.exists.return_value = True
        store.read.return_value = state
        mock_store.return_value = store
        mock_project.return_value = tmp_path
        mock_copy.return_value = True

        paths_obj = MagicMock()
        paths_obj.transcripts_abs = tmp_path / "artifacts" / "test-session" / "transcripts"
        paths_obj.transcripts_rel = Path(".forge/artifacts/test-session/transcripts")
        mock_paths.return_value = paths_obj

        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text('{"test": true}')

        payload = {
            "session_id": "uuid-abc",
            "transcript_path": str(transcript),
            "cwd": str(tmp_path),
        }
        exit_code, _, _ = _invoke("pre-compact", payload)
        assert exit_code == 0
        mock_copy.assert_called_once()
        # Verify copy destination has pre-compact in the name
        dst_arg = mock_copy.call_args[0][1]
        assert "pre-compact" in str(dst_arg)

    @patch("forge.cli.hooks.commands.resolve_session_store")
    @patch("forge.cli.hooks.commands.resolve_forge_root")
    @patch("forge.cli.hooks.commands.get_artifact_paths")
    @patch("forge.cli.hooks.commands.safe_copy_file")
    def test_updates_compaction_confirmed(
        self,
        mock_copy: MagicMock,
        mock_paths: MagicMock,
        mock_project: MagicMock,
        mock_store: MagicMock,
        tmp_path: Path,
    ) -> None:
        state = _make_state()
        store = MagicMock()
        store.exists.return_value = True
        store.read.return_value = state
        mock_store.return_value = store
        mock_project.return_value = tmp_path
        mock_copy.return_value = True

        paths_obj = MagicMock()
        paths_obj.transcripts_abs = tmp_path / "transcripts"
        paths_obj.transcripts_rel = Path(".forge/artifacts/test-session/transcripts")
        mock_paths.return_value = paths_obj

        payload = {
            "session_id": "uuid-abc",
            "transcript_path": str(tmp_path / "t.jsonl"),
            "cwd": str(tmp_path),
        }
        _invoke("pre-compact", payload)

        # Verify store.update was called with a mutate function
        store.update.assert_called_once()
        mutate_fn = store.update.call_args[1]["mutate"]

        # Execute the mutate function on a real state
        mutate_fn(state)
        assert state.confirmed.compaction is not None
        assert state.confirmed.compaction.compact_count == 1
        assert len(state.confirmed.compaction.transcript_snapshots) == 1
        assert state.confirmed.compaction.transcript_snapshots[0]["reason"] == "pre-compact"
        assert state.confirmed.confirmed_by == "hook:pre-compact"

    def test_never_blocks_compaction(self) -> None:
        """PreCompact must always exit 0, never exit 2."""
        payload = {"session_id": "x", "transcript_path": "/nonexistent", "cwd": "/tmp"}
        exit_code, _, _ = _invoke("pre-compact", payload)
        assert exit_code == 0


# ---------------------------------------------------------------------------
# PostCompact
# ---------------------------------------------------------------------------


class TestPostCompact:

    def test_exits_0_on_empty_stdin(self) -> None:
        runner = CliRunner()
        result = runner.invoke(hooks, ["post-compact"], input="", catch_exceptions=False)
        assert result.exit_code == 0

    def test_exits_0_when_no_session(self, tmp_path: Path) -> None:
        payload = {"session_id": "abc", "cwd": str(tmp_path)}
        exit_code, _, _ = _invoke("post-compact", payload)
        assert exit_code == 0

    @patch("forge.cli.hooks.commands.resolve_session_store")
    def test_updates_last_compact_at(self, mock_store: MagicMock, tmp_path: Path) -> None:
        state = _make_state()
        store = MagicMock()
        store.exists.return_value = True
        mock_store.return_value = store

        payload = {"session_id": "abc", "cwd": str(tmp_path), "trigger": "auto"}
        _invoke("post-compact", payload)

        store.update.assert_called_once()
        mutate_fn = store.update.call_args[1]["mutate"]
        mutate_fn(state)

        assert state.confirmed.compaction is not None
        assert state.confirmed.compaction.last_compact_at is not None
        assert state.confirmed.compaction.last_compact_type == "auto"
        assert state.confirmed.confirmed_by == "hook:post-compact"

    @patch("forge.cli.hooks.commands.resolve_session_store")
    def test_defaults_trigger_to_unknown(self, mock_store: MagicMock, tmp_path: Path) -> None:
        """When trigger field is missing, defaults to 'unknown'."""
        state = _make_state()
        store = MagicMock()
        store.exists.return_value = True
        mock_store.return_value = store

        payload = {"session_id": "abc", "cwd": str(tmp_path)}
        _invoke("post-compact", payload)

        mutate_fn = store.update.call_args[1]["mutate"]
        mutate_fn(state)

        assert state.confirmed.compaction is not None
        assert state.confirmed.compaction.last_compact_type == "unknown"

    @patch("forge.cli.hooks.commands.resolve_session_store")
    def test_preserves_existing_compaction_state(self, mock_store: MagicMock, tmp_path: Path) -> None:
        state = _make_state()
        state.confirmed.compaction = CompactionConfirmed(compact_count=3)

        store = MagicMock()
        store.exists.return_value = True
        mock_store.return_value = store

        payload = {"session_id": "abc", "cwd": str(tmp_path)}
        _invoke("post-compact", payload)

        mutate_fn = store.update.call_args[1]["mutate"]
        mutate_fn(state)

        # compact_count should NOT be incremented by PostCompact (PreCompact does that)
        assert state.confirmed.compaction.compact_count == 3
        assert state.confirmed.compaction.last_compact_at is not None


# ---------------------------------------------------------------------------
# WorktreeCreate
# ---------------------------------------------------------------------------


class TestWorktreeCreate:

    def test_exits_1_on_empty_stdin(self) -> None:
        runner = CliRunner()
        result = runner.invoke(hooks, ["worktree-create"], input="", catch_exceptions=False)
        assert result.exit_code == 1

    @patch("subprocess.run")
    def test_uses_hook_provided_name(
        self,
        mock_run: MagicMock,
        tmp_path: Path,
    ) -> None:
        """When CC provides a name slug, use it for worktree + branch naming."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        with (
            patch(
                "forge.session.worktree.create.get_main_repo_root",
                return_value=repo_root,
            ),
            patch(
                "forge.session.worktree.create.find_git_binary",
                return_value="/usr/bin/git",
            ),
            patch(
                "forge.install.installer.Installer.init",
                return_value=MagicMock(has_conflicts=False, modules=[]),
            ),
        ):
            payload = {"session_id": "abc12345", "cwd": str(repo_root), "name": "my-feature-wt"}
            runner = CliRunner()
            result = runner.invoke(hooks, ["worktree-create"], input=json.dumps(payload), catch_exceptions=False)

        assert result.exit_code == 0
        stdout_lines = result.output.strip().split("\n")
        assert len(stdout_lines) == 1
        # Should use the hook-provided name, not session_id
        assert "repo-my-feature-wt" in stdout_lines[0]

    @patch("subprocess.run")
    def test_generates_unique_name_without_hook_name(
        self,
        mock_run: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Without a name slug, generate a unique name per request (not session-locked)."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        with (
            patch(
                "forge.session.worktree.create.get_main_repo_root",
                return_value=repo_root,
            ),
            patch(
                "forge.session.worktree.create.find_git_binary",
                return_value="/usr/bin/git",
            ),
            patch(
                "forge.install.installer.Installer.init",
                return_value=MagicMock(has_conflicts=False, modules=[]),
            ),
        ):
            payload = {"session_id": "abc12345", "cwd": str(repo_root)}
            runner = CliRunner()
            result = runner.invoke(hooks, ["worktree-create"], input=json.dumps(payload), catch_exceptions=False)

        assert result.exit_code == 0
        stdout_lines = result.output.strip().split("\n")
        assert len(stdout_lines) == 1
        assert "repo-wt-" in stdout_lines[0]

    @patch("subprocess.run")
    def test_git_failure_exits_nonzero(
        self,
        mock_run: MagicMock,
        tmp_path: Path,
    ) -> None:
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        # Both git commands fail
        mock_run.return_value = MagicMock(returncode=128, stdout="", stderr="fatal: error")

        with (
            patch(
                "forge.session.worktree.create.get_main_repo_root",
                return_value=repo_root,
            ),
            patch(
                "forge.session.worktree.create.find_git_binary",
                return_value="/usr/bin/git",
            ),
        ):
            payload = {"session_id": "abc12345", "cwd": str(repo_root)}
            runner = CliRunner()
            result = runner.invoke(hooks, ["worktree-create"], input=json.dumps(payload), catch_exceptions=False)

        assert result.exit_code == 1
        assert result.output.strip() == ""

    @patch("subprocess.run")
    def test_extension_failure_still_prints_path(
        self,
        mock_run: MagicMock,
        tmp_path: Path,
    ) -> None:
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        with (
            patch(
                "forge.session.worktree.create.get_main_repo_root",
                return_value=repo_root,
            ),
            patch(
                "forge.session.worktree.create.find_git_binary",
                return_value="/usr/bin/git",
            ),
            patch(
                "forge.install.installer.Installer.init",
                side_effect=RuntimeError("install failed"),
            ),
            patch("forge.install.project_registry.ProjectRegistryStore.enroll") as mock_enroll,
        ):
            payload = {"session_id": "abc12345", "cwd": str(repo_root), "name": "ext-fail-wt"}
            runner = CliRunner()
            result = runner.invoke(hooks, ["worktree-create"], input=json.dumps(payload), catch_exceptions=False)

        # Should still succeed — extensions are non-fatal
        assert result.exit_code == 0
        assert "ext-fail-wt" in result.output
        mock_enroll.assert_called_once()
        assert mock_enroll.call_args.args[1] == "worktree"


# ---------------------------------------------------------------------------
# SubagentStop
# ---------------------------------------------------------------------------


class TestSubagentStop:

    def test_exits_0_on_empty_stdin(self) -> None:
        runner = CliRunner()
        result = runner.invoke(hooks, ["subagent-stop"], input="", catch_exceptions=False)
        assert result.exit_code == 0

    def test_exits_0_when_no_session(self, tmp_path: Path) -> None:
        payload = {"session_id": "abc", "cwd": str(tmp_path), "agent_type": "Explore"}
        exit_code, _, _ = _invoke("subagent-stop", payload)
        assert exit_code == 0

    @patch("forge.cli.hooks.commands.resolve_session_store")
    def test_tracks_agent_type_and_count(self, mock_store: MagicMock, tmp_path: Path) -> None:
        state = _make_state()
        store = MagicMock()
        store.exists.return_value = True
        mock_store.return_value = store

        payload = {
            "session_id": "abc",
            "cwd": str(tmp_path),
            "agent_id": "agent-001",
            "agent_type": "Explore",
            "agent_transcript_path": "/tmp/agent.jsonl",
            "last_assistant_message": "Found 3 issues in the codebase.",
        }
        _invoke("subagent-stop", payload)

        store.update.assert_called_once()
        mutate_fn = store.update.call_args[1]["mutate"]
        mutate_fn(state)

        sa = state.confirmed.subagents
        assert sa is not None
        assert sa.total_count == 1
        assert sa.by_type == {"Explore": 1}
        assert sa.last_agent_id == "agent-001"
        assert sa.last_agent_type == "Explore"
        assert sa.last_transcript_path == "/tmp/agent.jsonl"
        assert sa.last_message_preview == "Found 3 issues in the codebase."
        assert sa.last_stop_at is not None
        assert state.confirmed.confirmed_by == "hook:subagent-stop"

    @patch("forge.cli.hooks.commands.resolve_session_store")
    def test_multiple_types_counted_separately(self, mock_store: MagicMock, tmp_path: Path) -> None:
        state = _make_state()
        state.confirmed.subagents = SubagentConfirmed(
            total_count=2,
            by_type={"Explore": 1, "Bash": 1},
        )
        store = MagicMock()
        store.exists.return_value = True
        mock_store.return_value = store

        payload = {
            "session_id": "abc",
            "cwd": str(tmp_path),
            "agent_id": "agent-003",
            "agent_type": "Explore",
        }
        _invoke("subagent-stop", payload)

        mutate_fn = store.update.call_args[1]["mutate"]
        mutate_fn(state)

        sa = state.confirmed.subagents
        assert sa is not None
        assert sa.total_count == 3
        assert sa.by_type == {"Explore": 2, "Bash": 1}

    @patch("forge.cli.hooks.commands.resolve_session_store")
    def test_message_preview_truncated(self, mock_store: MagicMock, tmp_path: Path) -> None:
        state = _make_state()
        store = MagicMock()
        store.exists.return_value = True
        mock_store.return_value = store

        long_message = "x" * 500
        payload = {
            "session_id": "abc",
            "cwd": str(tmp_path),
            "agent_id": "agent-004",
            "agent_type": "Plan",
            "last_assistant_message": long_message,
        }
        _invoke("subagent-stop", payload)

        mutate_fn = store.update.call_args[1]["mutate"]
        mutate_fn(state)

        sa = state.confirmed.subagents
        assert sa is not None
        assert sa.last_message_preview is not None
        assert len(sa.last_message_preview) == 200

    @patch("forge.cli.hooks.commands.resolve_session_store")
    def test_none_message_stored_as_none(self, mock_store: MagicMock, tmp_path: Path) -> None:
        state = _make_state()
        store = MagicMock()
        store.exists.return_value = True
        mock_store.return_value = store

        payload = {
            "session_id": "abc",
            "cwd": str(tmp_path),
            "agent_id": "agent-005",
            "agent_type": "Bash",
        }
        _invoke("subagent-stop", payload)

        mutate_fn = store.update.call_args[1]["mutate"]
        mutate_fn(state)

        assert state.confirmed.subagents is not None
        assert state.confirmed.subagents.last_message_preview is None
