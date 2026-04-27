"""Tests for resume path resolution in nested Forge projects."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from forge.session.exceptions import ContextBudgetExceededError
from forge.session.manager import SessionManager
from forge.session.store import SessionStore


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
