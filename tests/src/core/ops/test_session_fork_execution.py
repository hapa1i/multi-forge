"""Mutation, compensation, and launch-plan coverage for ``session fork``."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Never
from unittest.mock import patch

import pytest

from forge.core.ops.session_fork_execution import (
    ForkCreated,
    ForkExecutionError,
    execute_session_fork,
)
from forge.core.ops.session_fork_preflight import (
    ForkPreflightRequest,
    plan_session_fork,
)
from forge.session import SessionManager, SessionState, SessionStore
from forge.session.claude.paths import get_transcript_path, resolve_claude_project_root


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
def fork_execution_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, SessionManager, SessionState]:
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
    transcript = get_transcript_path(resolve_claude_project_root(parent), "parent-uuid")
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text('{"type":"user","message":{"content":"hello"}}\n', encoding="utf-8")
    return repo, manager, parent


def _request(repo: Path, **overrides: object) -> ForkPreflightRequest:
    values: dict[str, object] = {
        "parent_name": "parent",
        "fork_name": "child",
        "cwd": repo,
        "forge_root": str(repo),
    }
    values.update(overrides)
    return ForkPreflightRequest(**values)  # type: ignore[arg-type]


def _unused_rewind(**_kwargs: object) -> Never:
    raise AssertionError("rewind preparation is not expected")


def _unused_transfer(**_kwargs: object) -> tuple[Path | None, list[str]]:
    raise AssertionError("transfer preparation is not expected")


def test_transfer_preparation_failure_rolls_back_child(
    fork_execution_repo: tuple[Path, SessionManager, SessionState],
) -> None:
    repo, manager, _parent = fork_execution_repo
    plan = plan_session_fork(_request(repo, resume_mode="transfer", no_launch=True), manager=manager)

    def _fail_transfer(**_kwargs: object) -> tuple[Path | None, list[str]]:
        raise OSError("context denied")

    with pytest.raises(ForkExecutionError, match="context denied") as raised:
        execute_session_fork(
            plan,
            manager=manager,
            routing=None,
            supervisor_proxy=None,
            transfer_context_factory=_fail_transfer,
            rewind_artifact_factory=_unused_rewind,
        )

    assert any(isinstance(event, ForkCreated) for event in raised.value.events)
    assert not SessionStore(str(repo), "child").exists()
    assert manager.index_store.peek_session("child", forge_root=str(repo)) is None


def test_supervisor_mutation_failure_rolls_back_child(
    fork_execution_repo: tuple[Path, SessionManager, SessionState],
) -> None:
    repo, manager, _parent = fork_execution_repo
    plan = plan_session_fork(_request(repo, supervise_target=True, no_launch=True), manager=manager)

    with (
        patch("forge.core.ops.session_fork_execution.apply_supervisor_wiring", side_effect=OSError("wiring denied")),
        pytest.raises(ForkExecutionError, match="wiring denied"),
    ):
        execute_session_fork(
            plan,
            manager=manager,
            routing=None,
            supervisor_proxy=None,
            transfer_context_factory=_unused_transfer,
            rewind_artifact_factory=_unused_rewind,
        )

    assert not SessionStore(str(repo), "child").exists()
    assert manager.index_store.peek_session("child", forge_root=str(repo)) is None


def test_native_relocation_failure_rolls_back_child_worktree_and_branch(
    fork_execution_repo: tuple[Path, SessionManager, SessionState],
) -> None:
    repo, manager, _parent = fork_execution_repo
    plan = plan_session_fork(
        _request(repo, create_worktree=True, resume_mode="native-relocate"),
        manager=manager,
    )

    with (
        patch("forge.session.claude.relocate_transcript", side_effect=PermissionError("denied")),
        pytest.raises(ForkExecutionError, match="Could not relocate"),
    ):
        execute_session_fork(
            plan,
            manager=manager,
            routing=None,
            supervisor_proxy=None,
            transfer_context_factory=_unused_transfer,
            rewind_artifact_factory=_unused_rewind,
        )

    assert not plan.target.checkout_root.exists()
    assert not subprocess.run(
        ["git", "branch", "--list", plan.target.branch or "child"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert manager.index_store.peek_session("child", forge_root=str(plan.target.forge_root)) is None


@dataclass(frozen=True)
class _UnreadyRewind:
    resume_id: str = "parent-uuid"
    context_path: Path | None = None
    warnings: list[str] = field(default_factory=lambda: ["fallback copy failed"])
    rewind_relocated_session_id: str | None = None
    resume_transcript_ready: bool = False


def test_unready_rewind_rolls_back_child_worktree(
    fork_execution_repo: tuple[Path, SessionManager, SessionState],
) -> None:
    repo, manager, _parent = fork_execution_repo
    plan = plan_session_fork(
        _request(
            repo,
            create_worktree=True,
            strategy="rewind",
            strategy_explicit=True,
            drop_last=1,
            drop_last_explicit=True,
        ),
        manager=manager,
    )

    with pytest.raises(ForkExecutionError, match="could not prepare a resumable transcript") as raised:
        execute_session_fork(
            plan,
            manager=manager,
            routing=None,
            supervisor_proxy=None,
            transfer_context_factory=_unused_transfer,
            rewind_artifact_factory=lambda **_kwargs: _UnreadyRewind(),
        )

    assert "fallback copy failed" in [getattr(event, "message", "") for event in raised.value.events]
    assert not plan.target.checkout_root.exists()


@dataclass(frozen=True)
class _Routing:
    template: str | None = "runtime-template"
    base_url: str | None = "http://localhost:9999"
    proxy_id: str | None = "runtime-proxy"
    context_limit: int | None = 123_456


def test_realized_routing_builds_launch_plan_without_inherited_reresolution(
    fork_execution_repo: tuple[Path, SessionManager, SessionState],
) -> None:
    repo, manager, _parent = fork_execution_repo
    plan = plan_session_fork(_request(repo), manager=manager)

    with (
        patch(
            "forge.core.ops.session_fork_execution.get_effective_proxy_for_resume",
            side_effect=AssertionError("explicit routing must not re-resolve"),
        ),
        patch("forge.core.ops.session_fork_execution._resolve_context_limit", return_value=123_456),
    ):
        result = execute_session_fork(
            plan,
            manager=manager,
            routing=_Routing(),
            supervisor_proxy=None,
            transfer_context_factory=_unused_transfer,
            rewind_artifact_factory=_unused_rewind,
        )

    assert result.launch_plan is not None
    assert result.launch_plan.effective_template == "runtime-template"
    assert result.launch_plan.runtime_base_url == "http://localhost:9999"
    assert result.launch_plan.proxy_id == "runtime-proxy"
    assert result.launch_plan.resume_id == "parent-uuid"
    assert result.launch_plan.fork_session is True


def test_rollback_failure_surfaces_explicit_recovery(
    fork_execution_repo: tuple[Path, SessionManager, SessionState],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, manager, _parent = fork_execution_repo
    plan = plan_session_fork(_request(repo, resume_mode="transfer", no_launch=True), manager=manager)

    def _fail_transfer(**_kwargs: object) -> tuple[Path | None, list[str]]:
        raise OSError("context denied")

    monkeypatch.setattr(manager, "delete_session", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("busy")))
    with pytest.raises(ForkExecutionError, match="Cleanup also failed") as raised:
        execute_session_fork(
            plan,
            manager=manager,
            routing=None,
            supervisor_proxy=None,
            transfer_context_factory=_fail_transfer,
            rewind_artifact_factory=_unused_rewind,
        )

    assert raised.value.tip is not None
    assert "forge session delete child --yes --force --keep-transcripts" in raised.value.tip
    assert SessionStore(str(repo), "child").exists()
