"""Regression: failed fork preparation must not retain a newly created transfer snapshot."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Never
from unittest.mock import patch

import pytest

from forge.cli.session import _generate_parent_transfer_context
from forge.core.ops.session_fork_execution import (
    ForkExecutionError,
    execute_session_fork,
)
from forge.core.ops.session_fork_preflight import (
    ForkPreflightRequest,
    plan_session_fork,
)
from forge.session import SessionManager, SessionState, SessionStore
from forge.session.claude.paths import get_transcript_path, resolve_claude_project_root
from forge.session.prev_sessions import child_path, ensure_child, generated_path

pytestmark = pytest.mark.regression


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init", str(path)], capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    (path / ".forge").mkdir()
    (path / "README.md").write_text("# test\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "commit", "-m", "init"],
        cwd=path,
        capture_output=True,
        check=True,
    )


@pytest.fixture
def transfer_fork_repo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, str, SessionManager, Path]:
    repo = tmp_path / "repo"
    _init_repo(repo)
    monkeypatch.chdir(repo)
    manager = SessionManager()
    created = manager.start_session(name="parent", worktree_path=str(repo))
    forge_root = created.forge_root or str(repo)
    store = SessionStore(forge_root, "parent")

    def _confirm(state: SessionState) -> None:
        state.confirmed.claude_session_id = "parent-uuid"
        state.confirmed.claude_project_root = str(repo)

    parent = store.update(timeout_s=5.0, mutate=_confirm)
    transcript = get_transcript_path(resolve_claude_project_root(parent), "parent-uuid")
    transcript.parent.mkdir(parents=True, exist_ok=True)
    return repo, forge_root, manager, transcript


def _request(repo: Path, forge_root: str) -> ForkPreflightRequest:
    return ForkPreflightRequest(
        parent_name="parent",
        fork_name="child",
        cwd=repo,
        forge_root=forge_root,
        no_launch=True,
        resume_mode="transfer",
        strategy="full",
        strategy_explicit=True,
    )


def _write_turn(transcript: Path, value: str) -> None:
    record = {"type": "user", "uuid": "u1", "message": {"role": "user", "content": value}}
    transcript.write_text(json.dumps(record) + "\n", encoding="utf-8")


def _unused_rewind(**_kwargs: object) -> Never:
    raise AssertionError("rewind preparation is not expected")


def _execute_transfer(*, repo: Path, forge_root: str, manager: SessionManager) -> None:
    plan = plan_session_fork(_request(repo, forge_root), manager=manager)
    execute_session_fork(
        plan,
        manager=manager,
        routing=None,
        supervisor_proxy=None,
        transfer_context_factory=_generate_parent_transfer_context,
        rewind_artifact_factory=_unused_rewind,
    )


def test_late_failure_removes_owned_snapshot_and_retry_uses_fresh_context(
    transfer_fork_repo: tuple[Path, str, SessionManager, Path],
) -> None:
    repo, forge_root, manager, transcript = transfer_fork_repo
    snapshot = child_path(Path(forge_root), "parent", "child")
    _write_turn(transcript, "OLD TRANSCRIPT VALUE")

    with (
        patch("forge.core.ops.session_fork_execution._combine_prompt_files", side_effect=OSError("combine denied")),
        pytest.raises(ForkExecutionError, match="combine denied"),
    ):
        _execute_transfer(repo=repo, forge_root=forge_root, manager=manager)

    assert not SessionStore(forge_root, "child").exists()
    assert manager.index_store.peek_session("child", forge_root=forge_root) is None
    assert not snapshot.exists()

    _write_turn(transcript, "NEW TRANSCRIPT VALUE")
    _execute_transfer(repo=repo, forge_root=forge_root, manager=manager)

    retry_context = snapshot.read_text(encoding="utf-8")
    assert "NEW TRANSCRIPT VALUE" in retry_context
    assert "OLD TRANSCRIPT VALUE" not in retry_context


def test_late_failure_preserves_preexisting_snapshot(
    transfer_fork_repo: tuple[Path, str, SessionManager, Path],
) -> None:
    repo, forge_root, manager, transcript = transfer_fork_repo
    snapshot = child_path(Path(forge_root), "parent", "child")
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_text("PRE-EXISTING SNAPSHOT\n", encoding="utf-8")
    _write_turn(transcript, "CURRENT TRANSCRIPT VALUE")

    with (
        patch("forge.core.ops.session_fork_execution._combine_prompt_files", side_effect=OSError("combine denied")),
        pytest.raises(ForkExecutionError, match="combine denied"),
    ):
        _execute_transfer(repo=repo, forge_root=forge_root, manager=manager)

    assert snapshot.read_text(encoding="utf-8") == "PRE-EXISTING SNAPSHOT\n"


def test_factory_write_then_failure_removes_owned_snapshot(
    transfer_fork_repo: tuple[Path, str, SessionManager, Path],
) -> None:
    repo, forge_root, manager, transcript = transfer_fork_repo
    snapshot = child_path(Path(forge_root), "parent", "child")
    _write_turn(transcript, "CURRENT TRANSCRIPT VALUE")
    plan = plan_session_fork(_request(repo, forge_root), manager=manager)

    def _partial_factory(**_kwargs: object) -> Never:
        cache = generated_path(Path(forge_root), "parent")
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text("PARTIAL SNAPSHOT\n", encoding="utf-8")
        ensure_child(Path(forge_root), "parent", "child")
        raise OSError("factory denied")

    with pytest.raises(ForkExecutionError, match="factory denied"):
        execute_session_fork(
            plan,
            manager=manager,
            routing=None,
            supervisor_proxy=None,
            transfer_context_factory=_partial_factory,
            rewind_artifact_factory=_unused_rewind,
        )

    assert not snapshot.exists()


def test_snapshot_cleanup_failure_names_retained_path(
    transfer_fork_repo: tuple[Path, str, SessionManager, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, forge_root, manager, transcript = transfer_fork_repo
    snapshot = child_path(Path(forge_root), "parent", "child")
    _write_turn(transcript, "CURRENT TRANSCRIPT VALUE")
    real_unlink = Path.unlink

    def _fail_snapshot_unlink(path: Path, missing_ok: bool = False) -> None:
        if path == snapshot:
            raise PermissionError("snapshot busy")
        real_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", _fail_snapshot_unlink)
    with (
        patch("forge.core.ops.session_fork_execution._combine_prompt_files", side_effect=OSError("combine denied")),
        pytest.raises(ForkExecutionError, match="Session cleanup succeeded") as raised,
    ):
        _execute_transfer(repo=repo, forge_root=forge_root, manager=manager)

    assert str(snapshot) in str(raised.value)
    assert raised.value.tip is not None
    assert f"Remove '{snapshot}' before retrying" in raised.value.tip
    assert snapshot.is_file()
    assert not SessionStore(forge_root, "child").exists()
    assert manager.index_store.peek_session("child", forge_root=forge_root) is None
