"""Worktree removal must preserve native stores and recorded native sources."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from forge.session import IndexStore, SessionStore
from forge.session.cleanup_state import cleanup_state_path
from forge.session.deletion import apply_session_deletion, plan_session_deletion
from forge.session.exceptions import ForgeSessionError
from forge.session.models import (
    AdoptionConfirmed,
    CodexConfirmed,
    CompactionConfirmed,
    SubagentConfirmed,
    create_session_state,
)
from tests.fixtures.session_state import publish_session

pytestmark = pytest.mark.regression


@pytest.fixture
def native_checkout(git_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from forge.session import deletion, purge_native

    monkeypatch.setattr(deletion, "check_native_inactivity", lambda runtime: ())
    monkeypatch.setattr(purge_native, "check_native_inactivity", lambda runtime: ())
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    checkout = tmp_path / "checkout"
    subprocess.run(
        ["git", "worktree", "add", "-b", "subject", str(checkout)],
        cwd=git_repo,
        check=True,
        capture_output=True,
    )
    state = create_session_state("subject", worktree_path=str(checkout), worktree_branch="subject")
    state.forge_root = str(checkout)
    assert state.worktree is not None
    state.worktree.is_worktree = True
    publish_session(IndexStore(), state, git_repo, forge_root=checkout)
    return checkout


@pytest.mark.parametrize("purge", [False, True])
@pytest.mark.parametrize("variable", ["CLAUDE_CONFIG_DIR", "CLAUDE_HOME", "CODEX_HOME"])
@pytest.mark.parametrize("home_above_checkout", [False, True])
def test_configured_native_storage_blocks_forced_worktree_removal(
    native_checkout: Path,
    monkeypatch: pytest.MonkeyPatch,
    variable: str,
    purge: bool,
    home_above_checkout: bool,
) -> None:
    home = native_checkout.parent if home_above_checkout else native_checkout / "native-home"
    home.mkdir(exist_ok=True)
    native = native_checkout / "retained-history.jsonl"
    native.write_bytes(b"synthetic native history outside the purge inventory\n")
    monkeypatch.setenv(variable, str(home))
    index = IndexStore()
    manifest = SessionStore(str(native_checkout), "subject").manifest_path
    before = {path: path.read_bytes() for path in (native, manifest, index.index_path)}

    plan = plan_session_deletion(index, "subject", forge_root=str(native_checkout), force=True, purge=purge)
    assert any("native storage" in reason and "--keep-worktree" in reason for reason in plan.refusals)
    with pytest.raises(ForgeSessionError, match="native storage"):
        apply_session_deletion(index, plan)
    assert all(path.read_bytes() == data for path, data in before.items())
    assert not cleanup_state_path(native_checkout, "subject").exists()

    retained = plan_session_deletion(
        index, "subject", forge_root=str(native_checkout), force=True, purge=purge, delete_worktree=False
    )
    assert not retained.refusals
    apply_session_deletion(index, retained)
    assert native.read_bytes() == before[native]
    assert native_checkout.is_dir()
    assert not manifest.exists()


@pytest.mark.parametrize("purge", [False, True])
def test_native_home_changed_after_preview_refuses_before_any_removal(
    native_checkout: Path, monkeypatch: pytest.MonkeyPatch, purge: bool
) -> None:
    index = IndexStore()
    native = native_checkout / "native-home/history.jsonl"
    native.parent.mkdir()
    native.write_bytes(b"retained native bytes\n")
    plan = plan_session_deletion(index, "subject", forge_root=str(native_checkout), force=True, purge=purge)
    assert not plan.refusals
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(native.parent))
    with pytest.raises(ForgeSessionError, match="native storage"):
        apply_session_deletion(index, plan)
    assert native.read_bytes() == b"retained native bytes\n"
    assert SessionStore(str(native_checkout), "subject").exists()
    assert not cleanup_state_path(native_checkout, "subject").exists()


@pytest.mark.parametrize("source", ["transcript", "rollout", "adopted", "subagent", "rollover", "snapshot"])
def test_recorded_native_path_blocks_delete_after_home_changes(native_checkout: Path, source: str) -> None:
    native = native_checkout / "old-native-home/conversation.jsonl"
    native.parent.mkdir()
    native.write_bytes(b"historical native bytes\n")
    store = SessionStore(str(native_checkout), "subject")
    state = store.read()
    if source == "transcript":
        state.confirmed.transcript_path = str(native)
    elif source == "rollout":
        state.confirmed.codex = CodexConfirmed(rollout_path=str(native))
    elif source == "adopted":
        state.confirmed.adoption = AdoptionConfirmed(source_runtime="claude_code", source_path=str(native))
    elif source == "subagent":
        state.confirmed.subagents = SubagentConfirmed(last_transcript_path=str(native))
    elif source == "rollover":
        state.confirmed.artifacts["transcripts"] = [
            {
                "source_path": str(native),
                "session_id": "aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa",
                "copied_path": ".forge/artifacts/subject/transcripts/conversation.jsonl",
                "copied": False,
            }
        ]
    else:
        state.confirmed.compaction = CompactionConfirmed(
            transcript_snapshots=[
                {
                    "reason": "pre-compact",
                    "captured_at": "2026-10-20T00:00:00+00:00",
                    "source_path": str(native),
                    "snapshot_path": ".forge/artifacts/subject/transcripts/snapshot.jsonl",
                    "copied": False,
                }
            ]
        )
    store.write(state)
    index = IndexStore()
    plan = plan_session_deletion(index, "subject", forge_root=str(native_checkout), force=True)
    assert any("native storage" in reason and str(native) in reason for reason in plan.refusals)
    with pytest.raises(ForgeSessionError, match="native storage"):
        apply_session_deletion(index, plan)
    assert native.read_bytes() == b"historical native bytes\n"
    assert store.exists()


def test_another_sessions_recorded_native_path_is_preserved(native_checkout: Path, tmp_path: Path) -> None:
    native = native_checkout / "historical-native.jsonl"
    native.write_bytes(b"another session's native bytes\n")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    state = create_session_state("other", worktree_path=str(elsewhere))
    state.forge_root = str(elsewhere)
    state.confirmed.transcript_path = str(native)
    index = IndexStore()
    publish_session(index, state, elsewhere, forge_root=elsewhere)
    plan = plan_session_deletion(index, "subject", forge_root=str(native_checkout), force=True)
    assert any("other native source" in reason for reason in plan.refusals)
    with pytest.raises(ForgeSessionError, match="native storage"):
        apply_session_deletion(index, plan)
    assert native.read_bytes() == b"another session's native bytes\n"


def test_relative_native_home_refuses_ambiguous_worktree_overlap(
    native_checkout: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CODEX_HOME", "native-home")
    plan = plan_session_deletion(IndexStore(), "subject", forge_root=str(native_checkout), force=True)
    assert any("relative native home" in reason and "--keep-worktree" in reason for reason in plan.refusals)
