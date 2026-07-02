"""CLI coverage for rewind resume strategy launch paths."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.session import SessionStore, create_session_state
from forge.session.config import LAUNCH_MODE_HOST, LAUNCH_MODE_SIDECAR


@pytest.fixture
def runner() -> CliRunner:
    """Create a CLI runner."""
    return CliRunner()


@pytest.fixture
def temp_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Set up temporary environment for tests."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("COLUMNS", "500")

    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    (project / ".forge").mkdir()
    monkeypatch.chdir(project)

    return project


def _nr_parent_and_fork(
    temp_env: Path,
    *,
    parent_sidecar: bool = False,
    with_transcript: bool = True,
):
    """Build (parent, worktree-fork) states; optionally seed the parent's Claude transcript."""
    from forge.session.claude.paths import get_transcript_path

    parent = create_session_state(
        "fork-parent",
        worktree_path=str(temp_env),
        worktree_branch="main",
        launch_mode=LAUNCH_MODE_SIDECAR if parent_sidecar else LAUNCH_MODE_HOST,
    )
    parent.confirmed.claude_session_id = "parent-uuid"
    parent.confirmed.claude_project_root = str(temp_env)
    if with_transcript:
        tp = get_transcript_path(str(temp_env), "parent-uuid")
        tp.parent.mkdir(parents=True, exist_ok=True)
        tp.write_text('{"type":"thinking","signature":"x"}\n')

    fork_worktree = temp_env / "fork-child"
    fork_worktree.mkdir(exist_ok=True)
    fork_state = create_session_state(
        "fork-child",
        parent_session="fork-parent",
        is_fork=True,
        worktree_path=str(fork_worktree),
        worktree_branch="fork-child",
    )
    assert fork_state.worktree is not None
    fork_state.worktree.is_worktree = True
    return parent, fork_state


def test_worktree_rewind_launches_truncated_uuid_with_context(runner: CliRunner, temp_env: Path) -> None:
    """A rewind worktree fork resumes the fresh truncated UUID and appends the code-delta context."""
    from forge.session.claude.paths import get_transcript_path

    parent, fork_state = _nr_parent_and_fork(temp_env)
    assert fork_state.worktree is not None
    fork_worktree = Path(fork_state.worktree.path)
    parent_transcript = get_transcript_path(str(temp_env), "parent-uuid")
    parent_transcript.write_text(
        "\n".join(
            [
                '{"requestId":"r1","message":{"role":"user","content":[{"type":"text","text":"one"}]}}',
                '{"requestId":"r2","message":{"role":"assistant","content":[{"type":"text","text":"two"}]}}',
                '{"requestId":"r3","message":{"role":"assistant","content":[{"type":"text","text":"three"}]}}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    SessionStore(str(fork_worktree), "fork-child").write(fork_state)

    with (
        patch("forge.cli.session.SessionManager") as mock_manager_cls,
        patch("forge.cli.session.invoke_claude", return_value=0) as mock_invoke,
    ):
        mock_manager = mock_manager_cls.return_value
        mock_manager.get_session.return_value = parent
        mock_manager.fork_session.return_value = (parent, fork_state)
        result = runner.invoke(
            main,
            [
                "session",
                "fork",
                "fork-parent",
                "-n",
                "fork-child",
                "--worktree",
                "--strategy",
                "rewind",
                "--drop-last",
                "1",
            ],
        )

    assert result.exit_code == 0, result.output
    kwargs = mock_invoke.call_args.kwargs
    assert kwargs["resume_id"] != "parent-uuid"
    assert kwargs["fork_session"] is True
    prompt_file = kwargs["system_prompt_file"]
    assert prompt_file is not None
    assert "Rewind Code Delta: fork-parent" in Path(prompt_file).read_text(encoding="utf-8")
    rewind_transcript = get_transcript_path(str(fork_worktree), kwargs["resume_id"])
    assert rewind_transcript.read_text(encoding="utf-8").count("\n") == 2

    persisted = SessionStore(str(fork_worktree), "fork-child").read()
    assert persisted.confirmed.derivation is not None
    assert persisted.confirmed.derivation.resume_mode == "native-relocate"
    assert persisted.confirmed.derivation.strategy == "rewind"
    assert persisted.confirmed.derivation.dropped_turns == 1
    assert persisted.confirmed.derivation.context_file == ".forge/prev_sessions/fork-parent/children/fork-child.md"
    assert persisted.confirmed.derivation.rewind_relocated_session_id == kwargs["resume_id"]


def test_same_directory_rewind_fork_is_rejected(runner: CliRunner, temp_env: Path) -> None:
    result = runner.invoke(
        main,
        ["session", "fork", "fork-parent", "-n", "fork-child", "--strategy", "rewind", "--drop-last", "1"],
    )

    assert result.exit_code == 1
    assert "--strategy rewind on fork requires --worktree or --into" in result.output


def test_rewind_fork_requires_drop_last(runner: CliRunner, temp_env: Path) -> None:
    result = runner.invoke(
        main,
        ["session", "fork", "fork-parent", "-n", "fork-child", "--worktree", "--strategy", "rewind"],
    )

    assert result.exit_code == 1
    assert "--strategy rewind requires --drop-last N" in result.output


def test_rewind_fork_rejects_sidecar_parent(runner: CliRunner, temp_env: Path) -> None:
    parent, _fork_state = _nr_parent_and_fork(temp_env, parent_sidecar=True)
    with (
        patch("forge.cli.session.SessionManager") as mock_manager_cls,
        patch("forge.cli.session.invoke_claude") as mock_invoke,
    ):
        mock_manager = mock_manager_cls.return_value
        mock_manager.get_session.return_value = parent
        result = runner.invoke(
            main,
            [
                "session",
                "fork",
                "fork-parent",
                "-n",
                "fork-child",
                "--worktree",
                "--strategy",
                "rewind",
                "--drop-last",
                "1",
            ],
        )

    assert result.exit_code == 1
    assert "--resume-mode native-relocate is not supported with sidecar mode" in result.output
    mock_manager.fork_session.assert_not_called()
    mock_invoke.assert_not_called()


def test_rewind_fork_rejects_sidecar_child_at_launch_seam(runner: CliRunner, temp_env: Path) -> None:
    parent, fork_state = _nr_parent_and_fork(temp_env)
    if fork_state.intent.launch is not None:
        fork_state.intent.launch.mode = LAUNCH_MODE_SIDECAR

    with (
        patch("forge.cli.session.SessionManager") as mock_manager_cls,
        patch("forge.cli.session.invoke_claude") as mock_invoke,
        patch("forge.cli.session_fork._prepare_rewind_launch_artifacts") as mock_prepare,
    ):
        mock_manager = mock_manager_cls.return_value
        mock_manager.get_session.return_value = parent
        mock_manager.fork_session.return_value = (parent, fork_state)
        result = runner.invoke(
            main,
            [
                "session",
                "fork",
                "fork-parent",
                "-n",
                "fork-child",
                "--worktree",
                "--strategy",
                "rewind",
                "--drop-last",
                "1",
            ],
        )

    assert result.exit_code == 1
    assert "--strategy rewind is not supported with sidecar mode" in result.output
    mock_prepare.assert_not_called()
    mock_invoke.assert_not_called()


def test_resume_fresh_rewind_uses_truncated_uuid_with_context(runner: CliRunner, temp_env: Path) -> None:
    """--fresh --strategy rewind resumes a fresh transcript prefix plus code-delta context."""
    from forge.session.claude.paths import get_transcript_path

    runner.invoke(main, ["session", "start", "rewind-parent", "--no-launch"])
    store = SessionStore(str(temp_env), "rewind-parent")

    def _confirm_rewind_parent(m: object) -> None:
        m.confirmed.claude_session_id = "parent-rewind-uuid"  # type: ignore[attr-defined]
        m.confirmed.confirmed_by = "hook:SessionStart:startup"  # type: ignore[attr-defined]

    store.update(timeout_s=5.0, mutate=_confirm_rewind_parent)
    parent_transcript = get_transcript_path(str(temp_env), "parent-rewind-uuid")
    parent_transcript.parent.mkdir(parents=True, exist_ok=True)
    parent_transcript.write_text(
        "\n".join(
            [
                '{"requestId":"r1","message":{"role":"user","content":[{"type":"text","text":"one"}]}}',
                '{"requestId":"r2","message":{"role":"assistant","content":[{"type":"text","text":"two"}]}}',
                '{"requestId":"r3","message":{"role":"assistant","content":[{"type":"text","text":"three"}]}}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with patch("forge.cli.session.invoke_claude", return_value=0) as mock_invoke:
        result = runner.invoke(
            main,
            [
                "session",
                "resume",
                "rewind-parent",
                "--fresh",
                "--child-name",
                "rewind-child",
                "--strategy",
                "rewind",
                "--drop-last",
                "1",
            ],
        )

    assert result.exit_code == 0, result.output
    kwargs = mock_invoke.call_args.kwargs
    assert kwargs["resume_id"] != "parent-rewind-uuid"
    assert kwargs["fork_session"] is True
    assert kwargs["session_id"] is None
    prompt_file = kwargs["system_prompt_file"]
    assert prompt_file is not None
    assert "Rewind Code Delta: rewind-parent" in Path(prompt_file).read_text(encoding="utf-8")
    rewind_transcript = get_transcript_path(str(temp_env), kwargs["resume_id"])
    assert rewind_transcript.read_text(encoding="utf-8").count("\n") == 2

    child = SessionStore(str(temp_env), "rewind-child").read()
    assert child.confirmed.derivation is not None
    assert child.confirmed.derivation.resume_mode == "native-relocate"
    assert child.confirmed.derivation.strategy == "rewind"
    assert child.confirmed.derivation.dropped_turns == 1
    assert child.confirmed.derivation.rewind_relocated_session_id == kwargs["resume_id"]
    assert child.confirmed.derivation.context_file == ".forge/prev_sessions/rewind-parent/children/rewind-child.md"


def test_resume_fresh_rewind_requires_valid_drop_last(runner: CliRunner, temp_env: Path) -> None:
    result = runner.invoke(main, ["session", "resume", "missing", "--fresh", "--strategy", "rewind"])

    assert result.exit_code == 1
    assert "--strategy rewind requires --drop-last N" in result.output

    result = runner.invoke(
        main,
        ["session", "resume", "missing", "--fresh", "--strategy", "rewind", "--drop-last", "-1"],
    )

    assert result.exit_code == 1
    assert "--drop-last must be non-negative" in result.output


def test_resume_fresh_rewind_empty_prefix_falls_back_native(runner: CliRunner, temp_env: Path) -> None:
    """N >= total turns falls back before launching an empty <R>.jsonl."""
    from forge.session.claude.paths import get_transcript_path

    runner.invoke(main, ["session", "start", "rewind-empty", "--no-launch"])
    store = SessionStore(str(temp_env), "rewind-empty")

    def _confirm_empty_parent(m: object) -> None:
        m.confirmed.claude_session_id = "parent-empty-uuid"  # type: ignore[attr-defined]
        m.confirmed.confirmed_by = "hook:SessionStart:startup"  # type: ignore[attr-defined]

    store.update(timeout_s=5.0, mutate=_confirm_empty_parent)
    parent_transcript = get_transcript_path(str(temp_env), "parent-empty-uuid")
    parent_transcript.parent.mkdir(parents=True, exist_ok=True)
    parent_transcript.write_text(
        '{"requestId":"r1","message":{"role":"user","content":[{"type":"text","text":"one"}]}}\n',
        encoding="utf-8",
    )

    with patch("forge.cli.session.invoke_claude", return_value=0) as mock_invoke:
        result = runner.invoke(
            main,
            [
                "session",
                "resume",
                "rewind-empty",
                "--fresh",
                "--child-name",
                "rewind-empty-child",
                "--strategy",
                "rewind",
                "--drop-last",
                "5",
            ],
        )

    assert result.exit_code == 0, result.output
    assert "would leave no resumable transcript turns" in result.output
    kwargs = mock_invoke.call_args.kwargs
    assert kwargs["resume_id"] == "parent-empty-uuid"
    assert kwargs["system_prompt_file"] is None
    child = SessionStore(str(temp_env), "rewind-empty-child").read()
    assert child.confirmed.derivation is not None
    assert child.confirmed.derivation.strategy is None
    assert child.confirmed.derivation.rewind_relocated_session_id is None


def test_resume_fresh_rewind_snap_warning_reports_extra_turns(runner: CliRunner, temp_env: Path) -> None:
    """Safe-boundary snap-back tells the user when more turns were dropped than requested."""
    from forge.session.claude.paths import get_transcript_path

    runner.invoke(main, ["session", "start", "rewind-snap", "--no-launch"])
    store = SessionStore(str(temp_env), "rewind-snap")

    def _confirm_snap_parent(m: object) -> None:
        m.confirmed.claude_session_id = "parent-snap-uuid"  # type: ignore[attr-defined]
        m.confirmed.confirmed_by = "hook:SessionStart:startup"  # type: ignore[attr-defined]

    store.update(timeout_s=5.0, mutate=_confirm_snap_parent)
    parent_transcript = get_transcript_path(str(temp_env), "parent-snap-uuid")
    parent_transcript.parent.mkdir(parents=True, exist_ok=True)
    parent_transcript.write_text(
        "\n".join(
            [
                '{"message":{"role":"user","content":[{"type":"text","text":"u1"}]}}',
                '{"message":{"role":"assistant","content":[{"type":"text","text":"a1"}]}}',
                '{"message":{"role":"user","content":[{"type":"text","text":"please read"}]}}',
                '{"message":{"role":"assistant","content":[{"type":"tool_use","id":"toolu_1","name":"Read","input":{"file_path":"README.md"}}]}}',
                '{"message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"toolu_1","content":"done"}]}}',
                '{"message":{"role":"assistant","content":[{"type":"text","text":"read done"}]}}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with patch("forge.cli.session.invoke_claude", return_value=0):
        result = runner.invoke(
            main,
            [
                "session",
                "resume",
                "rewind-snap",
                "--fresh",
                "--child-name",
                "rewind-snap-child",
                "--strategy",
                "rewind",
                "--drop-last",
                "1",
            ],
        )

    assert result.exit_code == 0, result.output
    assert "Safe rewind boundary dropped 1 additional turn(s) (2 total dropped)." in result.output


def test_resume_fresh_rewind_writer_error_falls_back_native(runner: CliRunner, temp_env: Path) -> None:
    """A defensive writer failure becomes a plain native child, not a traceback."""
    from forge.session.claude.paths import get_transcript_path

    runner.invoke(main, ["session", "start", "rewind-fallback", "--no-launch"])
    store = SessionStore(str(temp_env), "rewind-fallback")

    def _confirm_rewind_fallback(m: object) -> None:
        m.confirmed.claude_session_id = "parent-fallback-uuid"  # type: ignore[attr-defined]
        m.confirmed.confirmed_by = "hook:SessionStart:startup"  # type: ignore[attr-defined]

    store.update(timeout_s=5.0, mutate=_confirm_rewind_fallback)
    parent_transcript = get_transcript_path(str(temp_env), "parent-fallback-uuid")
    parent_transcript.parent.mkdir(parents=True, exist_ok=True)
    parent_transcript.write_text(
        '{"requestId":"r1","message":{"role":"user","content":[{"type":"text","text":"one"}]}}\n',
        encoding="utf-8",
    )

    with (
        patch("forge.cli.session_rewind.write_rewind_transcript_prefix", side_effect=ValueError("bad turn order")),
        patch("forge.cli.session.invoke_claude", return_value=0) as mock_invoke,
    ):
        result = runner.invoke(
            main,
            [
                "session",
                "resume",
                "rewind-fallback",
                "--fresh",
                "--child-name",
                "rewind-fallback-child",
                "--strategy",
                "rewind",
                "--drop-last",
                "1",
            ],
        )

    assert result.exit_code == 0, result.output
    assert "falling back to plain native resume" in result.output
    kwargs = mock_invoke.call_args.kwargs
    assert kwargs["resume_id"] == "parent-fallback-uuid"
    assert kwargs["fork_session"] is True
    assert kwargs["system_prompt_file"] is None
    child = SessionStore(str(temp_env), "rewind-fallback-child").read()
    assert child.confirmed.derivation is not None
    assert child.confirmed.derivation.resume_mode == "native"
    assert child.confirmed.derivation.strategy is None
