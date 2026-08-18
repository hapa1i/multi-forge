"""Regression: rewind fork preparation must not orphan transcript copies."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from forge.cli.session_rewind import _prepare_rewind_launch_artifacts
from forge.core.ops.session_fork_execution import (
    ForkExecutionError,
    execute_session_fork,
)
from forge.core.ops.session_fork_preflight import (
    ForkPreflightRequest,
    plan_session_fork,
)
from forge.core.state import FileLockTimeoutError
from forge.session import SessionManager, SessionState, SessionStore
from forge.session.claude.paths import get_transcript_path, resolve_claude_project_root
from forge.session.rewind import REWIND_CODE_DELTA_SCHEMA

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
def rewind_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, SessionManager, SessionState, Path]:
    repo = tmp_path / "repo"
    _init_repo(repo)
    monkeypatch.chdir(repo)
    manager = SessionManager()
    manager.start_session(name="parent", worktree_path=str(repo))
    store = SessionStore(str(repo), "parent")

    def _confirm(state: SessionState) -> None:
        state.confirmed.claude_session_id = "parent-uuid"
        state.confirmed.claude_project_root = str(repo)

    parent = store.update(timeout_s=5.0, mutate=_confirm)
    transcript = get_transcript_path(str(repo), "parent-uuid")
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text(
        "\n".join(
            [
                '{"message":{"role":"user","content":[{"type":"text","text":"one"}]}}',
                '{"message":{"role":"assistant","content":[{"type":"text","text":"first"}]}}',
                '{"message":{"role":"user","content":[{"type":"text","text":"two"}]}}',
                '{"message":{"role":"assistant","content":[{"type":"text","text":"second"}]}}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return repo, manager, parent, transcript


def _rewind_request(repo: Path) -> ForkPreflightRequest:
    return ForkPreflightRequest(
        parent_name="parent",
        fork_name="child",
        cwd=repo,
        forge_root=str(repo),
        create_worktree=True,
        strategy="rewind",
        strategy_explicit=True,
        drop_last=1,
        drop_last_explicit=True,
    )


def _unused_transfer(**_kwargs: object) -> tuple[Path | None, list[str]]:
    raise AssertionError("transfer preparation is not expected")


def test_ready_plain_fallback_is_removed_after_late_fork_failure(
    rewind_repo: tuple[Path, SessionManager, SessionState, Path],
) -> None:
    repo, manager, _parent, parent_transcript = rewind_repo
    original = parent_transcript.read_bytes()
    plan = plan_session_fork(_rewind_request(repo), manager=manager)
    copied: dict[str, Path] = {}

    def _fallback_factory(**kwargs: Any):
        with patch(
            "forge.cli.session_rewind.write_rewind_transcript_prefix",
            side_effect=ValueError("force full-copy fallback"),
        ):
            artifacts = _prepare_rewind_launch_artifacts(**kwargs)
        child_root = resolve_claude_project_root(kwargs["manifest"])
        copied["path"] = get_transcript_path(child_root, kwargs["parent_uuid"])
        assert copied["path"].is_file()
        assert artifacts.resume_transcript_ready is True
        assert artifacts.rewind_relocated_session_id is None
        return artifacts

    with (
        patch("forge.core.ops.session_fork_execution._combine_prompt_files", side_effect=OSError("prompt denied")),
        pytest.raises(ForkExecutionError, match="prompt denied"),
    ):
        execute_session_fork(
            plan,
            manager=manager,
            routing=None,
            supervisor_proxy=None,
            transfer_context_factory=_unused_transfer,
            rewind_artifact_factory=_fallback_factory,
        )

    assert not copied["path"].exists()
    assert parent_transcript.read_bytes() == original
    assert not SessionStore(str(plan.target.forge_root), "child").exists()
    assert manager.index_store.peek_session("child", forge_root=str(plan.target.forge_root)) is None


def test_partial_rewind_factory_failure_removes_fresh_transcript(
    rewind_repo: tuple[Path, SessionManager, SessionState, Path],
) -> None:
    repo, manager, parent, parent_transcript = rewind_repo
    _parent, child = manager.fork_session(
        parent_name="parent",
        fork_name="child",
        create_worktree=True,
        forge_root=str(repo),
        resume_mode="native-relocate",
    )
    child_root = resolve_claude_project_root(child)
    child_transcript_dir = get_transcript_path(child_root, "unused").parent
    persistence_error = FileLockTimeoutError(lock_path=repo / "rewind.lock", timeout_s=5.0)

    with (
        patch(
            "forge.cli.session_rewind.generate_rewind_code_delta_context",
            return_value=("## Rewind Code Delta\n", [], REWIND_CODE_DELTA_SCHEMA),
        ),
        patch("forge.cli.session_rewind._persist_rewind_derivation", side_effect=persistence_error),
        pytest.raises(FileLockTimeoutError),
    ):
        _prepare_rewind_launch_artifacts(
            manifest=child,
            parent_name="parent",
            parent_state=parent,
            parent_uuid="parent-uuid",
            drop_last=1,
        )

    assert list(child_transcript_dir.glob("*.jsonl")) == []
    assert parent_transcript.is_file()
