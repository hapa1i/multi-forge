"""A delayed hook cannot recreate content or mutate a replacement session."""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from forge.cli.hooks import hooks
from forge.cli.hooks.commands import _capture_transcript_artifact
from forge.core.paths import get_forge_home
from forge.session.exceptions import SessionNotFoundError
from forge.session.index import IndexStore
from forge.session.models import create_session_state
from forge.session.store import SessionStore
from forge.session.workers import (
    SESSION_INSTANCE_ENV,
    capture_session_instance,
    find_active_session_workers,
)
from tests.fixtures.session_state import delete_published_session, publish_session

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("replacement", [False, True])
def test_stale_capture_cannot_publish_after_session_deletion(tmp_path: Path, replacement: bool) -> None:
    state = create_session_state("subject", worktree_path=str(tmp_path))
    index = IndexStore()
    publish_session(index, state, tmp_path, forge_root=tmp_path)
    owner = capture_session_instance(tmp_path, "subject")
    store = SessionStore(str(tmp_path), "subject")
    transcript = tmp_path / "native.jsonl"
    transcript.write_text('{"sessionId":"original-native-id"}\n')
    assert delete_published_session(index, "subject", tmp_path)
    if replacement:
        publish_session(
            index, create_session_state("subject", worktree_path=str(tmp_path)), tmp_path, forge_root=tmp_path
        )
        before = store.manifest_path.read_bytes()
    with pytest.raises(SessionNotFoundError):
        _capture_transcript_artifact(
            cwd=tmp_path,
            store=store,
            manifest=state,
            transcript_path=str(transcript),
            session_id="original-native-id",
            reason="stop",
            confirmed_by="hook:stop",
            event_label="Stop",
            fail_on_copy_error=True,
            expected_instance_id=owner,
        )
    assert not (tmp_path / ".forge/artifacts/subject").exists()
    if replacement:
        assert store.manifest_path.read_bytes() == before


def test_capture_registers_a_live_worker_until_files_and_manifest_finish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from forge.cli.hooks import commands

    state = create_session_state("subject", worktree_path=str(tmp_path))
    publish_session(IndexStore(), state, tmp_path, forge_root=tmp_path)
    owner = capture_session_instance(tmp_path, "subject")
    transcript = tmp_path / "native.jsonl"
    transcript.write_text("{}\n")
    original = commands.safe_copy_file
    seen = []

    def checked_copy(src, dst, *, overwrite=False):
        seen.extend(find_active_session_workers(tmp_path, "subject", owner))
        return original(src, dst, overwrite=overwrite)

    monkeypatch.setattr(commands, "safe_copy_file", checked_copy)
    _capture_transcript_artifact(
        cwd=tmp_path,
        store=SessionStore(str(tmp_path), "subject"),
        manifest=state,
        transcript_path=str(transcript),
        session_id="native-id",
        reason="stop",
        confirmed_by="hook:stop",
        event_label="Stop",
        fail_on_copy_error=True,
        expected_instance_id=owner,
    )
    assert seen and "Stop" in seen[0]
    assert not find_active_session_workers(tmp_path, "subject", owner)


@pytest.mark.parametrize(
    "command,event",
    [
        ("stop", "Stop"),
        ("stop-failure", "StopFailure"),
        ("pre-compact", "PreCompact"),
        ("session-start", "SessionStart"),
        ("exit-plan-mode", "PreToolUse"),
        ("post-compact", "PostCompact"),
        ("subagent-stop", "SubagentStop"),
        ("plan-write", "PostToolUse"),
    ],
)
def test_deleted_launch_cannot_capture_into_replacement_or_qa(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str, event: str
) -> None:
    state = create_session_state("subject", worktree_path=str(tmp_path))
    index = IndexStore()
    publish_session(index, state, tmp_path, forge_root=tmp_path)
    owner = capture_session_instance(tmp_path, "subject")
    assert delete_published_session(index, "subject", tmp_path)
    publish_session(index, create_session_state("subject", worktree_path=str(tmp_path)), tmp_path, forge_root=tmp_path)
    replacement = SessionStore(str(tmp_path), "subject")
    before = replacement.manifest_path.read_bytes()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FORGE_SESSION", "subject")
    monkeypatch.setenv("FORGE_FORGE_ROOT", str(tmp_path))
    monkeypatch.setenv(SESSION_INSTANCE_ENV, owner)
    transcript = tmp_path / "native.jsonl"
    transcript.write_text('{"sessionId":"old-native-id"}\n')
    qa = get_forge_home() / "manual-testing/qa"
    run = qa / "runs/example"
    run.mkdir(parents=True)
    (qa / ".pending-transcript").write_text(json.dumps({"run_dir": str(run), "session_id": "old-native-id"}))
    result = CliRunner().invoke(
        hooks,
        [command],
        input=json.dumps(
            {
                "hook_event_name": event,
                "session_id": "old-native-id",
                "transcript_path": str(transcript),
                "source": "compact",
                "tool_name": "Write",
                "tool_input": {"file_path": ".claude/plans/example.md"},
            }
        ),
    )
    assert result.exit_code == 0
    assert not (tmp_path / ".forge/artifacts/subject").exists()
    assert not (run / "transcript.jsonl").exists()
    assert replacement.manifest_path.read_bytes() == before


def test_policy_result_cannot_attach_to_session_replaced_during_evaluation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unittest.mock import MagicMock

    from forge.policy.types import CompositeDecision
    from forge.session.models import PolicyIntent

    index = IndexStore()
    original = create_session_state("subject", worktree_path=str(tmp_path))
    original.intent.policy = PolicyIntent(enabled=True, bundles=["coding_standards"])
    publish_session(index, original, tmp_path, forge_root=tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FORGE_SESSION", "subject")
    monkeypatch.setenv("FORGE_FORGE_ROOT", str(tmp_path))
    engine = MagicMock()
    engine.registered_policy_ids = []
    engine.get_collected_state.return_value = {}
    replacement_bytes: list[bytes] = []

    def evaluate(context):
        assert delete_published_session(index, "subject", tmp_path)
        replacement = create_session_state("subject", worktree_path=str(tmp_path))
        publish_session(index, replacement, tmp_path, forge_root=tmp_path)
        replacement_bytes.append(SessionStore(str(tmp_path), "subject").manifest_path.read_bytes())
        return CompositeDecision(final_decision="allow", decisions=[])

    engine.evaluate.side_effect = evaluate
    monkeypatch.setattr("forge.cli.hooks.commands.build_hook_engine", lambda effective: engine)
    monkeypatch.setattr("forge.cli.hooks.commands.register_supervisor_and_restore", lambda *args: None)
    result = CliRunner().invoke(
        hooks,
        ["policy-check"],
        input=json.dumps(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Write",
                "tool_input": {"file_path": "docs/note.md", "content": "safe synthetic note"},
            }
        ),
    )
    assert result.exit_code == 0, result.output
    assert "Policy state persistence failed" in result.stderr
    assert SessionStore(str(tmp_path), "subject").manifest_path.read_bytes() == replacement_bytes[0]
