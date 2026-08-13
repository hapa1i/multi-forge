"""O030 regression: resume name validation runs after transfer artifact creation."""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.session import SessionManager
from forge.session.exceptions import InvalidSessionNameError
from forge.session.prev_sessions import parent_dir

pytestmark = pytest.mark.regression


@pytest.fixture
def resume_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    (project / ".forge").mkdir()
    monkeypatch.chdir(project)
    return project


def test_o030_overlong_auto_resume_name_fails_before_context_creation(resume_project: Path) -> None:
    parent_name = "p" * 64
    manager = SessionManager()
    manager.start_session(parent_name, worktree_path=str(resume_project))

    with pytest.raises(InvalidSessionNameError, match="at most 64 characters"):
        manager.resume_session(parent_name)

    assert not parent_dir(resume_project, parent_name).exists()


def test_o030_invalid_explicit_resume_name_fails_before_context_creation(resume_project: Path) -> None:
    manager = SessionManager()
    manager.start_session("resume-parent", worktree_path=str(resume_project))
    invalid_child_name = "c" * 65

    with pytest.raises(InvalidSessionNameError, match="at most 64 characters"):
        manager.resume_session("resume-parent", child_name=invalid_child_name)

    assert not parent_dir(resume_project, "resume-parent").exists()


def test_o030_valid_explicit_resume_name_still_creates_context(resume_project: Path) -> None:
    manager = SessionManager()
    manager.start_session("valid-parent", worktree_path=str(resume_project))

    child, transfer = manager.resume_session("valid-parent", child_name="valid-child")

    assert child.name == "valid-child"
    assert transfer.context_file is not None and transfer.context_file.is_file()
