"""Regression for D024: PreCompact records hid the latest resumable transcript artifact.

PreCompact appended a ``snapshot_path``-only shape to the canonical transcript list.
Readers then inspected only the tail, so derivation, transfer assembly, and both
full-strategy budget preflights lost the preceding ``copied_path`` record.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from forge.cli.hooks import hooks
from forge.cli.main import main
from forge.session import SessionManager, SessionStore, create_session_state
from forge.session.exceptions import (
    ContextBudgetExceededError,
    TranscriptArtifactStateError,
)
from forge.session.models import CompactionConfirmed
from forge.session.transfer import ResumeStrategy, assemble_transfer_context

pytestmark = pytest.mark.regression


def _canonical(path: str, *, session_id: str = "parent-uuid") -> dict[str, object]:
    return {
        "captured_at": "2026-08-05T00:00:00Z",
        "reason": "stop",
        "source_path": "/tmp/parent.jsonl",
        "session_id": session_id,
        "copied_path": path,
        "copied": True,
    }


def _legacy_snapshot() -> dict[str, object]:
    return {
        "captured_at": "2026-08-05T00:01:00Z",
        "reason": "pre-compact",
        "source_path": "/tmp/parent.jsonl",
        "snapshot_path": ".forge/artifacts/parent/transcripts/parent-uuid_pre-compact.jsonl",
        "copied": True,
    }


def _project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "init", str(project)], capture_output=True, check=True)
    (project / ".claude").mkdir()
    (project / ".forge").mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("FORGE_HOME", str(tmp_path / "forge-home"))
    monkeypatch.chdir(project)
    return project


def _seed_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    content: str = '{"type":"assistant"}\n',
) -> tuple[Path, SessionManager, SessionStore, str]:
    project = _project(tmp_path, monkeypatch)
    manager = SessionManager()
    manager.start_session(name="parent", worktree_path=str(project), direct=True)
    copied_path = ".forge/artifacts/parent/transcripts/parent-uuid.jsonl"
    transcript = project / copied_path
    transcript.parent.mkdir(parents=True)
    transcript.write_text(content, encoding="utf-8")
    store = SessionStore(str(project), "parent")
    state = store.read()
    state.confirmed.claude_session_id = "parent-uuid"
    state.confirmed.artifacts["transcripts"] = [_canonical(copied_path), _legacy_snapshot()]
    store.write(state)
    return project, manager, store, copied_path


def test_precompact_migrates_legacy_tail_and_writes_only_the_dedicated_snapshot_collection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    project = _project(tmp_path, monkeypatch)
    monkeypatch.setenv("FORGE_SESSION", "parent")
    monkeypatch.setenv("FORGE_FORGE_ROOT", str(project))
    store = SessionStore(str(project), "parent")
    state = create_session_state("parent", worktree_path=str(project))
    copied_path = ".forge/artifacts/parent/transcripts/parent-uuid.jsonl"
    canonical = _canonical(copied_path)
    legacy = _legacy_snapshot()
    state.confirmed.claude_session_id = "parent-uuid"
    state.confirmed.artifacts["transcripts"] = [canonical, legacy]
    state.confirmed.compaction = CompactionConfirmed(transcript_snapshots=[dict(legacy)])
    store.write(state)
    transcript = project / "parent.jsonl"
    transcript.write_text("{}\n", encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="forge.session.artifacts"):
        result = CliRunner().invoke(
            hooks,
            ["pre-compact"],
            input=json.dumps(
                {
                    "hook_event_name": "PreCompact",
                    "session_id": "parent-uuid",
                    "transcript_path": str(transcript),
                    "cwd": str(project),
                }
            ),
        )

    assert result.exit_code == 0
    updated = store.read()
    assert updated.confirmed.artifacts["transcripts"] == [canonical]
    assert updated.confirmed.compaction is not None
    snapshots = updated.confirmed.compaction.transcript_snapshots
    assert len(snapshots) == 2
    assert sum(snapshot["snapshot_path"] == legacy["snapshot_path"] for snapshot in snapshots) == 1
    assert all(snapshot["reason"] == "pre-compact" for snapshot in snapshots)
    assert "migrated 1 recognized legacy PreCompact snapshot" in caplog.text


def test_precompact_preserves_malformed_dedicated_snapshot_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    project = _project(tmp_path, monkeypatch)
    monkeypatch.setenv("FORGE_SESSION", "parent")
    monkeypatch.setenv("FORGE_FORGE_ROOT", str(project))
    store = SessionStore(str(project), "parent")
    state = create_session_state("parent", worktree_path=str(project))
    canonical = _canonical(".forge/artifacts/parent/transcripts/parent-uuid.jsonl")
    legacy = _legacy_snapshot()
    malformed_snapshots = [{"snapshot_path": legacy["snapshot_path"]}]
    state.confirmed.claude_session_id = "parent-uuid"
    state.confirmed.artifacts["transcripts"] = [canonical, legacy]
    state.confirmed.compaction = CompactionConfirmed(
        compact_count=3,
        transcript_snapshots=malformed_snapshots,
    )
    store.write(state)
    transcript = project / "parent.jsonl"
    transcript.write_text("{}\n", encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="forge.cli.hooks.commands"):
        result = CliRunner().invoke(
            hooks,
            ["pre-compact"],
            input=json.dumps(
                {
                    "hook_event_name": "PreCompact",
                    "session_id": "parent-uuid",
                    "transcript_path": str(transcript),
                    "cwd": str(project),
                }
            ),
        )

    assert result.exit_code == 0
    updated = store.read()
    assert updated.confirmed.artifacts["transcripts"] == [canonical, legacy]
    assert updated.confirmed.compaction is not None
    assert updated.confirmed.compaction.compact_count == 3
    assert updated.confirmed.compaction.transcript_snapshots == malformed_snapshots
    assert "pre-compact: transcript artifact state is malformed" in caplog.text


def test_legacy_snapshot_tail_does_not_hide_native_derivation_or_transfer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, manager, store, copied_path = _seed_parent(tmp_path, monkeypatch)

    child, native_transfer = manager.resume_session("parent", child_name="native-child", resume_mode="native")
    assert child.confirmed.derivation is not None
    assert child.confirmed.derivation.parent_transcript == copied_path
    assert native_transfer.transcript_artifact_path == copied_path

    assembled = assemble_transfer_context(
        parent_name="parent",
        parent_state=store.read(),
        forge_root=project,
        strategy=ResumeStrategy.MINIMAL,
        depth=1,
        get_session=lambda _name: None,
    )
    assert assembled.transcript_artifact_path == copied_path


def test_legacy_snapshot_tail_does_not_bypass_manager_full_budget_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _project_root, manager, _store, _copied_path = _seed_parent(tmp_path, monkeypatch, content="x" * 4096)

    with pytest.raises(ContextBudgetExceededError):
        manager.resume_session("parent", child_name="budget-child", strategy="full", context_limit=100)


def test_legacy_snapshot_tail_does_not_bypass_cli_fork_full_budget_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path, monkeypatch)
    copied_path = ".forge/artifacts/parent/transcripts/parent-uuid.jsonl"
    transcript = project / copied_path
    transcript.parent.mkdir(parents=True)
    transcript.write_text("x" * 4096, encoding="utf-8")
    parent = create_session_state(
        "parent",
        proxy_template="litellm-openai",
        proxy_base_url="http://localhost:8085",
        worktree_path=str(project),
        worktree_branch="main",
    )
    parent.confirmed.claude_session_id = "parent-uuid"
    parent.forge_root = str(project)
    parent.confirmed.artifacts["transcripts"] = [_canonical(copied_path), _legacy_snapshot()]

    with (
        patch("forge.cli.session_fork.SessionManager") as manager_cls,
        patch("forge.cli.session_fork._resolve_context_limit", return_value=100),
        patch("forge.core.ops.claude_session.invoke_claude") as invoke_claude,
    ):
        manager = manager_cls.return_value
        manager.get_session.return_value = parent
        result = CliRunner().invoke(
            main,
            ["session", "fork", "parent", "--name", "child", "--strategy", "full"],
        )

    assert result.exit_code == 1
    assert "exceeds context limit" in result.output
    manager.fork_session.assert_not_called()
    invoke_claude.assert_not_called()


def test_malformed_parent_artifacts_fail_before_worktree_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path, monkeypatch)
    manager = SessionManager()
    manager.start_session(name="parent", worktree_path=str(project), direct=True)
    store = SessionStore(str(project), "parent")
    state = store.read()
    state.confirmed.artifacts["transcripts"] = [{"copied_path": {"not": "a string"}}]
    store.write(state)

    with patch(
        "forge.session.worktree.create_worktree",
        side_effect=AssertionError("worktree creation must not run"),
    ) as create_worktree:
        with pytest.raises(TranscriptArtifactStateError, match="non-string or empty copied_path"):
            manager.fork_session("parent", "child", create_worktree=True)

    create_worktree.assert_not_called()
