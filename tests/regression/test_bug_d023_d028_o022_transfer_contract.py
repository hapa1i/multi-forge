"""Regressions for Wave 6 transfer preflight, depth, and reattach contracts."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.session import SessionManager, SessionStore
from forge.session.exceptions import ContextBudgetExceededError, SessionNotFoundError
from forge.session.prev_sessions import generated_path
from forge.session.transfer import parse_transfer_frontmatter
from tests.src.cli.session_command_support import successful_claude_launch

pytestmark = pytest.mark.regression


def _project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "init", str(project)], capture_output=True, check=True)
    (project / ".claude").mkdir()
    (project / ".forge").mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("FORGE_HOME", str(tmp_path / "forge-home"))
    monkeypatch.chdir(project)
    return project


def _start_session(
    manager: SessionManager,
    project: Path,
    name: str,
    *,
    parent: str | None = None,
    confirmed: bool = False,
) -> SessionStore:
    manager.start_session(name=name, worktree_path=str(project), direct=True)
    store = SessionStore(str(project), name)
    state = store.read()
    state.parent_session = parent
    if confirmed:
        state.confirmed.claude_session_id = f"{name}-uuid"
        state.confirmed.confirmed_by = "hook:SessionStart:startup"
    store.write(state)
    return store


def _seed_fallback_transcript(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, SessionManager, SessionStore]:
    project = _project(tmp_path, monkeypatch)
    manager = SessionManager()
    store = _start_session(manager, project, "parent", confirmed=True)
    transcript = project / "parent-live.jsonl"
    transcript.write_text("x" * 4096, encoding="utf-8")
    state = store.read()
    state.confirmed.transcript_path = str(transcript)
    store.write(state)
    return project, manager, store


def test_d023_manager_preflights_confirmed_transcript_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, manager, _store = _seed_fallback_transcript(tmp_path, monkeypatch)

    with pytest.raises(ContextBudgetExceededError):
        manager.resume_session(
            "parent",
            child_name="child",
            strategy="full",
            context_limit=100,
            forge_root=str(project),
        )

    assert not SessionStore(str(project), "child").session_dir.exists()
    with pytest.raises(SessionNotFoundError):
        manager.get_session_entry("child", forge_root=str(project))
    assert not generated_path(project, "parent").exists()


def test_d023_fork_preflights_confirmed_transcript_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _project_root, _real_manager, store = _seed_fallback_transcript(tmp_path, monkeypatch)
    parent = store.read()

    with (
        patch("forge.cli.session_fork.SessionManager") as manager_cls,
        patch("forge.cli.session_fork._resolve_context_limit", return_value=100),
        successful_claude_launch() as invoke_claude,
    ):
        manager = manager_cls.return_value
        manager.get_session.return_value = parent
        result = CliRunner().invoke(
            main,
            ["session", "fork", "parent", "--name", "child", "--strategy", "full"],
        )

    manager.fork_session.assert_not_called()
    invoke_claude.assert_not_called()
    assert result.exit_code == 1
    assert "exceeds context limit" in result.output


def test_d028_depth_all_traverses_to_terminal_ancestor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path, monkeypatch)
    manager = SessionManager()
    _start_session(manager, project, "root")
    _start_session(manager, project, "grandparent", parent="root")
    _start_session(manager, project, "parent", parent="grandparent")

    with successful_claude_launch():
        result = CliRunner().invoke(
            main,
            ["session", "resume", "parent", "--fresh", "--child-name", "child-all", "--depth", "all"],
        )

    assert result.exit_code == 0, result.output
    child = SessionStore(str(project), "child-all").read()
    assert child.confirmed.derivation is not None
    assert child.confirmed.derivation.lineage == ["parent", "grandparent", "root"]
    assert child.confirmed.derivation.depth == 3
    assert child.confirmed.derivation.context_file is not None
    frontmatter, _body, warning = parse_transfer_frontmatter(
        (project / child.confirmed.derivation.context_file).read_text(encoding="utf-8")
    )
    assert warning is None
    assert frontmatter is not None
    assert frontmatter["depth"] == 3


@pytest.mark.parametrize("depth", ["0", "-1"])
def test_d028_non_positive_depth_fails_without_child_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    depth: str,
) -> None:
    project = _project(tmp_path, monkeypatch)
    manager = SessionManager()
    _start_session(manager, project, "parent")

    with successful_claude_launch() as invoke_claude:
        result = CliRunner().invoke(
            main,
            ["session", "resume", "parent", "--fresh", "--child-name", "invalid-child", "--depth", depth],
        )

    assert result.exit_code == 1
    assert "--depth must be a positive integer or 'all'" in result.output
    assert not SessionStore(str(project), "invalid-child").session_dir.exists()
    assert not generated_path(project, "parent").exists()
    invoke_claude.assert_not_called()


def test_d028_positive_integer_depth_remains_compatible(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path, monkeypatch)
    manager = SessionManager()
    _start_session(manager, project, "root")
    _start_session(manager, project, "parent", parent="root")

    with successful_claude_launch():
        result = CliRunner().invoke(
            main,
            ["session", "resume", "parent", "--fresh", "--child-name", "child-two", "--depth", "2"],
        )

    assert result.exit_code == 0, result.output
    child = SessionStore(str(project), "child-two").read()
    assert child.confirmed.derivation is not None
    assert child.confirmed.derivation.lineage == ["parent", "root"]
    assert child.confirmed.derivation.depth == 2


@pytest.mark.parametrize(
    ("flag_args", "message"),
    [
        (["--strategy", "full"], "--strategy requires --fresh"),
        (["--depth", "2"], "--depth requires --fresh"),
    ],
)
def test_o022_explicit_transfer_flags_require_fresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    flag_args: list[str],
    message: str,
) -> None:
    project = _project(tmp_path, monkeypatch)
    manager = SessionManager()
    _start_session(manager, project, "parent", confirmed=True)

    with successful_claude_launch() as invoke_claude:
        result = CliRunner().invoke(main, ["session", "resume", "parent", *flag_args])

    assert result.exit_code == 1
    assert message in result.output
    invoke_claude.assert_not_called()


def test_o022_default_transfer_flags_preserve_ordinary_reattach(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path, monkeypatch)
    manager = SessionManager()
    _start_session(manager, project, "parent", confirmed=True)

    with successful_claude_launch() as invoke_claude:
        result = CliRunner().invoke(main, ["session", "resume", "parent"])

    assert result.exit_code == 0, result.output
    invoke_claude.assert_called_once()
