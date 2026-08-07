"""Tests for resume path resolution in nested Forge projects."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from forge.session.exceptions import ContextBudgetExceededError, SessionNotFoundError
from forge.session.manager import SessionManager
from forge.session.prev_sessions import child_path, generated_path
from forge.session.store import SessionStore
from forge.session.transfer import TRANSFER_CONTEXT_STRATEGY_VALUES


def _init_git_repo(path: Path) -> None:
    """Create a minimal git repo at *path*."""
    subprocess.run(["git", "init", str(path)], capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        capture_output=True,
        check=True,
        cwd=str(path),
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        capture_output=True,
        check=True,
        cwd=str(path),
    )
    (path / "README.md").write_text("# Test\n")
    subprocess.run(["git", "add", "."], capture_output=True, check=True, cwd=str(path))
    subprocess.run(["git", "commit", "-m", "init"], capture_output=True, check=True, cwd=str(path))


def _enable_forge(path: Path) -> None:
    """Create .claude/ and .forge/ at *path*."""
    (path / ".claude").mkdir(exist_ok=True)
    (path / ".forge").mkdir(exist_ok=True)


def _create_resume_parent(tmp_path: Path) -> tuple[Path, SessionManager]:
    project = tmp_path / "project"
    _init_git_repo(project)
    _enable_forge(project)
    manager = SessionManager()
    manager.start_session(name="parent", worktree_path=str(project))
    return project, manager


class TestResumeArtifactPaths:
    """Resume budget checks should resolve artifacts from forge_root."""

    def test_resume_full_budget_uses_nested_forge_root(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Nested project transcripts should be read from the stored forge_root."""
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir()

        repo = tmp_path / "monorepo"
        _init_git_repo(repo)
        nested = repo / "packages" / "app"
        nested.mkdir(parents=True)
        _enable_forge(nested)

        manager = SessionManager()
        manager.start_session(name="parent", worktree_path=str(nested))

        transcript_dir = nested / ".forge" / "artifacts" / "parent" / "transcripts"
        transcript_dir.mkdir(parents=True)
        transcript_path = transcript_dir / "large.jsonl"
        transcript_path.write_text("x" * 4096)

        store = SessionStore(str(nested), "parent")
        state = store.read()
        state.confirmed.artifacts["transcripts"] = [{"copied_path": ".forge/artifacts/parent/transcripts/large.jsonl"}]
        store.write(state)

        with pytest.raises(ContextBudgetExceededError):
            manager.resume_session("parent", strategy="full", context_limit=100)


class TestResumeStrategyValidation:
    @pytest.mark.parametrize("strategy", TRANSFER_CONTEXT_STRATEGY_VALUES)
    def test_supported_transfer_strategy_matches_persisted_derivation(self, tmp_path: Path, strategy: str) -> None:
        project, manager = _create_resume_parent(tmp_path)
        child_name = f"child-{strategy}"

        child, transfer = manager.resume_session(
            "parent",
            child_name=child_name,
            strategy=strategy,
            forge_root=str(project),
        )

        assert child.confirmed.derivation is not None
        assert child.confirmed.derivation.strategy == strategy
        assert transfer.context_file is not None
        assert f"strategy: {strategy}" in transfer.context_file.read_text(encoding="utf-8")
        persisted = SessionStore(str(project), child_name).read()
        assert persisted.confirmed.derivation is not None
        assert persisted.confirmed.derivation.strategy == strategy

    @pytest.mark.parametrize("strategy", ["not-a-strategy", "rewind"])
    def test_non_transfer_strategy_fails_before_artifacts_or_child_state(self, tmp_path: Path, strategy: str) -> None:
        project, manager = _create_resume_parent(tmp_path)
        child_name = f"child-{strategy}"

        with pytest.raises(ValueError) as exc_info:
            manager.resume_session(
                "parent",
                child_name=child_name,
                strategy=strategy,
                forge_root=str(project),
            )

        valid = ", ".join(TRANSFER_CONTEXT_STRATEGY_VALUES)
        assert str(exc_info.value) == f"Unknown strategy '{strategy}' (valid: {valid})."
        assert not SessionStore(str(project), child_name).session_dir.exists()
        with pytest.raises(SessionNotFoundError):
            manager.get_session_entry(child_name, forge_root=str(project))
        assert not generated_path(project, "parent").exists()
        assert not child_path(project, "parent", child_name).exists()

    def test_native_resume_keeps_null_strategy_and_writes_no_transfer_context(self, tmp_path: Path) -> None:
        project, manager = _create_resume_parent(tmp_path)

        child, transfer = manager.resume_session(
            "parent",
            child_name="native-child",
            resume_mode="native",
            forge_root=str(project),
        )

        assert child.confirmed.derivation is not None
        assert child.confirmed.derivation.strategy is None
        assert transfer.context_file is None
        assert not generated_path(project, "parent").exists()
        persisted = SessionStore(str(project), child.name).read()
        assert persisted.confirmed.derivation is not None
        assert persisted.confirmed.derivation.strategy is None
