"""Read-only command-core preflight coverage for ``session fork``."""

from __future__ import annotations

import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from forge.core.ops.session_fork_preflight import (
    ForkPreflightError,
    ForkPreflightRequest,
    _validate_command_cwd,
    plan_session_fork,
)
from forge.session import SessionManager, SessionStore
from forge.session.claude.paths import get_transcript_path
from forge.session.exceptions import (
    BranchExistsError,
    CannotForkIncognitoError,
    SessionExistsError,
    SessionNotFoundError,
    SessionWorktreeMissingError,
    TranscriptArtifactStateError,
)
from forge.session.identity import make_scoped_key


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init", str(path)], capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    (path / ".forge").mkdir()
    (path / "README.md").write_text("# test\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, capture_output=True, check=True)


def _snapshot(repo: Path, manager: SessionManager) -> tuple[bytes, dict[str, bytes], str, str, dict[str, bytes]]:
    index = manager.index_store.index_path.read_bytes()
    manifests = {str(path.relative_to(repo)): path.read_bytes() for path in sorted(repo.rglob("forge.session.json"))}
    worktrees = subprocess.run(
        ["git", "worktree", "list", "--porcelain"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout
    branches = subprocess.run(
        ["git", "for-each-ref", "--format=%(refname):%(objectname)", "refs/heads"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    transfers = {
        str(path.relative_to(repo)): path.read_bytes()
        for path in sorted((repo / ".forge" / "prev_sessions").rglob("*"))
        if path.is_file()
    }
    return index, manifests, worktrees, branches, transfers


@pytest.fixture
def fork_preflight_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, SessionManager]:
    repo = tmp_path / "repo"
    _init_repo(repo)
    monkeypatch.chdir(repo)
    manager = SessionManager()
    manager.start_session(name="parent", worktree_path=str(repo))

    store = SessionStore(str(repo), "parent")

    def _confirm_parent(state: object) -> None:
        state.confirmed.claude_session_id = "parent-uuid"  # type: ignore[attr-defined]

    store.update(timeout_s=5.0, mutate=_confirm_parent)
    transfer = repo / ".forge" / "prev_sessions" / "parent" / "generated.md"
    transfer.parent.mkdir(parents=True)
    transfer.write_text("existing transfer\n", encoding="utf-8")
    return repo, manager


def _request(repo: Path, **overrides: Any) -> ForkPreflightRequest:
    request = ForkPreflightRequest(
        parent_name="parent",
        fork_name="child",
        cwd=repo,
        forge_root=str(repo),
    )
    return replace(request, **overrides)


@pytest.mark.parametrize(
    ("overrides", "error_type"),
    [
        ({"direct": True, "proxy_name": "test-proxy"}, ForkPreflightError),
        ({"supervisor_proxy": "test-proxy"}, ForkPreflightError),
        ({"checker_model": "claude-opus-5", "supervise_target": True}, ForkPreflightError),
        ({"direct_model": "gpt-5.6"}, ForkPreflightError),
        ({"create_worktree": True, "into_path": "/unused"}, ForkPreflightError),
        ({"drop_last": 1, "drop_last_explicit": True}, ForkPreflightError),
        ({"strategy": "rewind", "strategy_explicit": True}, ForkPreflightError),
        (
            {
                "create_worktree": True,
                "resume_mode": "native-relocate",
                "no_launch": True,
            },
            ForkPreflightError,
        ),
    ],
)
def test_rejected_option_families_leave_durable_and_git_state_unchanged(
    fork_preflight_repo: tuple[Path, SessionManager],
    overrides: dict[str, object],
    error_type: type[Exception],
) -> None:
    repo, manager = fork_preflight_repo
    before = _snapshot(repo, manager)

    with pytest.raises(error_type):
        plan_session_fork(_request(repo, **overrides), manager=manager)

    assert _snapshot(repo, manager) == before


def test_target_collision_is_rejected_without_changing_state(
    fork_preflight_repo: tuple[Path, SessionManager],
) -> None:
    repo, manager = fork_preflight_repo
    manager.start_session(name="child", worktree_path=str(repo))
    before = _snapshot(repo, manager)

    with pytest.raises(SessionExistsError):
        plan_session_fork(_request(repo, no_launch=True), manager=manager)

    assert _snapshot(repo, manager) == before


def test_worktree_branch_collision_is_rejected_without_changing_git_state(
    fork_preflight_repo: tuple[Path, SessionManager],
) -> None:
    repo, manager = fork_preflight_repo
    subprocess.run(["git", "branch", "child"], cwd=repo, check=True)
    before = _snapshot(repo, manager)

    with pytest.raises(BranchExistsError):
        plan_session_fork(_request(repo, create_worktree=True, no_launch=True), manager=manager)

    assert _snapshot(repo, manager) == before


def test_missing_parent_uuid_is_rejected_without_changing_state(
    fork_preflight_repo: tuple[Path, SessionManager],
) -> None:
    repo, manager = fork_preflight_repo
    store = SessionStore(str(repo), "parent")
    store.update(timeout_s=5.0, mutate=lambda state: setattr(state.confirmed, "claude_session_id", None))
    before = _snapshot(repo, manager)

    with pytest.raises(ForkPreflightError, match="Parent session has no UUID"):
        plan_session_fork(_request(repo), manager=manager)

    assert _snapshot(repo, manager) == before


def test_template_model_mismatch_is_rejected_before_proxy_start(
    fork_preflight_repo: tuple[Path, SessionManager],
) -> None:
    repo, manager = fork_preflight_repo
    before = _snapshot(repo, manager)

    with pytest.raises(ForkPreflightError, match="Proxy template 'openrouter-openai' does not configure"):
        plan_session_fork(
            _request(
                repo,
                proxy_name="openrouter-openai",
                direct_model="claude-opus-4-8",
                no_launch=True,
            ),
            manager=manager,
        )

    assert _snapshot(repo, manager) == before


def test_missing_supervisor_proxy_is_rejected_without_changing_state(
    fork_preflight_repo: tuple[Path, SessionManager],
) -> None:
    repo, manager = fork_preflight_repo
    before = _snapshot(repo, manager)

    with pytest.raises(ForkPreflightError, match="no template named 'missing-supervisor-proxy'"):
        plan_session_fork(
            _request(
                repo,
                supervise_target=True,
                supervisor_proxy="missing-supervisor-proxy",
                no_launch=True,
            ),
            manager=manager,
        )

    assert _snapshot(repo, manager) == before


@pytest.mark.parametrize(
    ("state_change", "error_type"),
    [
        ("codex", ForkPreflightError),
        ("incognito", CannotForkIncognitoError),
        ("missing-worktree", SessionWorktreeMissingError),
    ],
)
def test_parent_rejection_families_leave_state_unchanged(
    fork_preflight_repo: tuple[Path, SessionManager],
    state_change: str,
    error_type: type[Exception],
) -> None:
    repo, manager = fork_preflight_repo
    store = SessionStore(str(repo), "parent")

    def _change_parent(state: object) -> None:
        if state_change == "codex":
            state.intent.launch.runtime = "codex"  # type: ignore[attr-defined,union-attr]
        elif state_change == "incognito":
            state.is_incognito = True  # type: ignore[attr-defined]
        else:
            state.worktree.path = str(repo / "missing")  # type: ignore[attr-defined,union-attr]

    store.update(timeout_s=5.0, mutate=_change_parent)
    before = _snapshot(repo, manager)

    with pytest.raises(error_type):
        plan_session_fork(_request(repo), manager=manager)

    assert _snapshot(repo, manager) == before


def test_native_relocation_prerequisite_failure_leaves_state_unchanged(
    fork_preflight_repo: tuple[Path, SessionManager],
) -> None:
    repo, manager = fork_preflight_repo
    before = _snapshot(repo, manager)

    with pytest.raises(ForkPreflightError, match="no Claude transcript to relocate"):
        plan_session_fork(
            _request(repo, create_worktree=True, resume_mode="native-relocate"),
            manager=manager,
        )

    assert _snapshot(repo, manager) == before


def test_native_relocation_conflict_is_rejected_before_worktree_creation(
    fork_preflight_repo: tuple[Path, SessionManager],
) -> None:
    repo, manager = fork_preflight_repo
    source = get_transcript_path(str(repo), "parent-uuid")
    destination = get_transcript_path(str(repo.parent / "repo-child"), "parent-uuid")
    source.parent.mkdir(parents=True, exist_ok=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"parent transcript")
    destination.write_bytes(b"unrelated transcript")
    before = _snapshot(repo, manager)

    with pytest.raises(ForkPreflightError, match="destination worktree already holds a different transcript"):
        plan_session_fork(
            _request(repo, create_worktree=True, resume_mode="native-relocate"),
            manager=manager,
        )

    assert source.read_bytes() == b"parent transcript"
    assert destination.read_bytes() == b"unrelated transcript"
    assert (repo.parent / "repo-child").exists() is False
    assert _snapshot(repo, manager) == before


def test_malformed_parent_artifact_state_is_rejected_without_writes(
    fork_preflight_repo: tuple[Path, SessionManager],
) -> None:
    repo, manager = fork_preflight_repo
    SessionStore(str(repo), "parent").update(
        timeout_s=5.0,
        mutate=lambda state: state.confirmed.artifacts.__setitem__("transcripts", "invalid"),
    )
    before = _snapshot(repo, manager)

    with pytest.raises(TranscriptArtifactStateError, match="expected a list"):
        plan_session_fork(_request(repo, no_launch=True), manager=manager)

    assert _snapshot(repo, manager) == before


def test_budget_rejection_leaves_state_unchanged(
    fork_preflight_repo: tuple[Path, SessionManager],
) -> None:
    repo, manager = fork_preflight_repo
    transcript = repo / "parent.jsonl"
    transcript.write_text("x" * 100, encoding="utf-8")
    SessionStore(str(repo), "parent").update(
        timeout_s=5.0,
        mutate=lambda state: setattr(state.confirmed, "transcript_path", str(transcript)),
    )
    before = _snapshot(repo, manager)

    with pytest.raises(ForkPreflightError, match="exceeds context limit"):
        plan_session_fork(
            _request(repo, strategy="full", resume_mode="transfer", no_launch=True),
            manager=manager,
            context_limit_resolver=lambda _ref: 1,
        )

    assert _snapshot(repo, manager) == before


def test_stale_parent_row_is_not_pruned_by_rejected_preflight(
    fork_preflight_repo: tuple[Path, SessionManager],
) -> None:
    repo, manager = fork_preflight_repo
    SessionStore(str(repo), "parent").delete()
    index_before = manager.index_store.index_path.read_bytes()
    assert make_scoped_key("parent", str(repo)) in manager.index_store.read().sessions

    with pytest.raises(SessionNotFoundError, match="session 'parent' not found"):
        plan_session_fork(_request(repo, no_launch=True), manager=manager)

    assert manager.index_store.index_path.read_bytes() == index_before


def test_successful_plan_is_typed_and_does_not_reserve_the_child(
    fork_preflight_repo: tuple[Path, SessionManager],
) -> None:
    repo, manager = fork_preflight_repo
    before = _snapshot(repo, manager)

    plan = plan_session_fork(_request(repo, no_launch=True), manager=manager)

    assert plan.parent.name == "parent"
    assert plan.fork_name == "child"
    assert plan.target.forge_root == repo
    assert plan.resume_mode == "native"
    assert plan.transfer_depth == 1
    assert plan.parent_session_id is None
    assert SessionStore(str(repo), "child").exists() is False
    assert _snapshot(repo, manager) == before


def test_worktree_plan_resolves_git_target_without_creating_it(
    fork_preflight_repo: tuple[Path, SessionManager],
) -> None:
    repo, manager = fork_preflight_repo
    before = _snapshot(repo, manager)

    plan = plan_session_fork(_request(repo, create_worktree=True, no_launch=True), manager=manager)

    assert plan.target.checkout_root == repo.parent / "repo-child"
    assert plan.target.forge_root == repo.parent / "repo-child"
    assert plan.target.branch == "child"
    assert plan.resume_mode == "transfer"
    assert plan.target.checkout_root.exists() is False
    assert _snapshot(repo, manager) == before


def test_module_has_no_click_dependency() -> None:
    import forge.core.ops.session_fork_preflight as preflight

    assert "click" not in preflight.__dict__


def test_same_directory_cwd_retains_non_git_forge_root_allowance(tmp_path: Path) -> None:
    """The extracted guard preserves require_repo_root's Forge-root alternative."""
    (tmp_path / ".forge").mkdir()

    _validate_command_cwd(tmp_path, create_worktree=False)
