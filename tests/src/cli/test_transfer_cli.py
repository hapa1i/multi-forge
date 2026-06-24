"""Tests for the ``forge session transfer`` CLI group (Slice 02 clean-break move)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from click.testing import CliRunner

from forge.cli.main import main


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def transfer_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A Forge project with a 'planner' session and a seeded transfer tree.

    Seeds ``generated.md`` + ``children/exec.md`` (byte-identical) via the real
    assembler so frontmatter/strategy round-trip exactly as in production.
    """
    from forge.session import IndexStore, SessionStore, create_session_state
    from forge.session.transfer import ResumeStrategy, assemble_transfer_context

    forge_root = tmp_path / "project"
    (forge_root / ".forge").mkdir(parents=True)

    state = create_session_state("planner", worktree_path=str(forge_root))
    state.forge_root = str(forge_root)
    SessionStore(str(forge_root), "planner").write(state)
    IndexStore().add_session(
        name="planner",
        worktree_path=str(forge_root),
        project_root=str(tmp_path),
        forge_root=str(forge_root),
        checkout_root=str(forge_root),
        relative_path=".",
        is_incognito=False,
        is_fork=False,
        parent_session=None,
    )
    assemble_transfer_context(
        parent_name="planner",
        parent_state=state,
        forge_root=forge_root,
        strategy=ResumeStrategy.STRUCTURED,
        depth=1,
        get_session=lambda _: None,
        child_name="exec",
    )
    monkeypatch.chdir(forge_root)
    return forge_root


def _fake_editor(tmp_path: Path, *, append: str | None = None, exit_code: int = 0) -> str:
    """Write a fake $EDITOR script; optionally append text to the edited file."""
    script = tmp_path / "fake-editor.sh"
    body = "#!/bin/sh\n"
    if append is not None:
        body += f'printf "%s" {json.dumps(append)} >> "$1"\n'
    body += f"exit {exit_code}\n"
    script.write_text(body)
    script.chmod(0o755)
    return str(script)


class TestTransferShow:
    def test_show_cache(self, runner: CliRunner, transfer_project: Path) -> None:
        result = runner.invoke(main, ["session", "transfer", "show", "planner"])
        assert result.exit_code == 0, result.output
        assert "# Session Context" in result.output

    def test_show_json_has_frontmatter(self, runner: CliRunner, transfer_project: Path) -> None:
        result = runner.invoke(main, ["session", "transfer", "show", "planner", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["child"] is None
        assert payload["frontmatter"]["strategy"] == "structured"
        assert payload["frontmatter"]["schema_version"] == 1
        assert "child" not in payload["frontmatter"]  # child-agnostic

    def test_show_json_includes_section_map(self, runner: CliRunner, transfer_project: Path) -> None:
        result = runner.invoke(main, ["session", "transfer", "show", "planner", "--json"])
        assert result.exit_code == 0, result.output
        sections = json.loads(result.output)["sections"]
        assert isinstance(sections, list) and sections
        assert all({"level", "title"} <= set(entry) for entry in sections)
        # The document title (h1) is part of the map.
        assert any(s["level"] == 1 and "Session Context" in s["title"] for s in sections)

    def test_show_child_view(self, runner: CliRunner, transfer_project: Path) -> None:
        result = runner.invoke(main, ["session", "transfer", "show", "planner", "--child", "exec"])
        assert result.exit_code == 0, result.output
        assert "# Session Context" in result.output

    def test_show_missing_parent_errors_with_tip(self, runner: CliRunner, transfer_project: Path) -> None:
        result = runner.invoke(main, ["session", "transfer", "show", "nope"])
        assert result.exit_code == 1
        assert "Error:" in result.output
        assert "resume" in result.output  # recovery tip names the resume path


class TestTransferEdit:
    def test_edit_creates_and_merges_notes(
        self, runner: CliRunner, transfer_project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EDITOR", _fake_editor(tmp_path, append="run the suite\n"))
        result = runner.invoke(main, ["session", "transfer", "edit", "planner", "--child", "exec"])
        assert result.exit_code == 0, result.output

        notes = transfer_project / ".forge" / "prev_sessions" / "planner" / "children" / "exec.notes.md"
        assert notes.is_file()
        assert "run the suite" in notes.read_text(encoding="utf-8")

        # The note now appears in the composed child view (i.e. at launch).
        shown = runner.invoke(main, ["session", "transfer", "show", "planner", "--child", "exec"])
        assert "run the suite" in shown.output

    def test_edit_ambiguous_child_errors(
        self, runner: CliRunner, transfer_project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from forge.session.prev_sessions import ensure_child

        ensure_child(transfer_project, "planner", "exec2")  # now two children
        monkeypatch.setenv("EDITOR", _fake_editor(tmp_path))
        result = runner.invoke(main, ["session", "transfer", "edit", "planner"])
        assert result.exit_code == 1
        assert "multiple" in result.output.lower()


class TestTransferRegenerate:
    def test_regenerate_preserves_strategy(self, runner: CliRunner, transfer_project: Path) -> None:
        result = runner.invoke(main, ["session", "transfer", "regenerate", "planner"])
        assert result.exit_code == 0, result.output
        assert "Regenerated" in result.output
        # Strategy defaults to the cache's existing frontmatter, not structured-by-accident.
        assert "structured" in result.output

    def test_regenerate_does_not_touch_notes(
        self, runner: CliRunner, transfer_project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        notes = transfer_project / ".forge" / "prev_sessions" / "planner" / "children" / "exec.notes.md"
        notes.write_text("## User Notes\n\nkeep me", encoding="utf-8")
        result = runner.invoke(main, ["session", "transfer", "regenerate", "planner"])
        assert result.exit_code == 0, result.output
        assert notes.read_text(encoding="utf-8") == "## User Notes\n\nkeep me"

    def test_regenerate_default_target_runtime_is_claude(self, runner: CliRunner, transfer_project: Path) -> None:
        # The seeded cache is target_runtime=claude; a no-flag regenerate stays claude.
        result = runner.invoke(main, ["session", "transfer", "regenerate", "planner"])
        assert result.exit_code == 0, result.output
        assert "runtime=claude" in result.output

    def test_regenerate_target_runtime_codex_flips_frontmatter(self, runner: CliRunner, transfer_project: Path) -> None:
        result = runner.invoke(main, ["session", "transfer", "regenerate", "planner", "--target-runtime", "codex"])
        assert result.exit_code == 0, result.output
        assert "runtime=codex" in result.output
        show = runner.invoke(main, ["session", "transfer", "show", "planner", "--json"])
        assert json.loads(show.output)["frontmatter"]["target_runtime"] == "codex"

    def test_regenerate_defaults_target_runtime_from_cache(self, runner: CliRunner, transfer_project: Path) -> None:
        # Flip to codex, then a no-flag regenerate must NOT silently flip back to claude.
        runner.invoke(main, ["session", "transfer", "regenerate", "planner", "--target-runtime", "codex"])
        result = runner.invoke(main, ["session", "transfer", "regenerate", "planner"])
        assert result.exit_code == 0, result.output
        assert "runtime=codex" in result.output

    def test_regenerate_rejects_unknown_target_runtime(self, runner: CliRunner, transfer_project: Path) -> None:
        result = runner.invoke(main, ["session", "transfer", "regenerate", "planner", "--target-runtime", "gemini"])
        assert result.exit_code != 0  # click.Choice rejects before the op runs


class TestTransferDiff:
    def test_diff_no_drift(self, runner: CliRunner, transfer_project: Path) -> None:
        result = runner.invoke(main, ["session", "transfer", "diff", "planner", "--child", "exec"])
        assert result.exit_code == 0, result.output
        assert "No drift" in result.output

    def test_diff_shows_drift(self, runner: CliRunner, transfer_project: Path) -> None:
        cache = transfer_project / ".forge" / "prev_sessions" / "planner" / "generated.md"
        cache.write_text(cache.read_text(encoding="utf-8") + "\nDRIFTED LINE\n", encoding="utf-8")
        result = runner.invoke(main, ["session", "transfer", "diff", "planner", "--child", "exec"])
        assert result.exit_code == 0, result.output
        assert "DRIFTED LINE" in result.output

    def test_diff_ignores_frontmatter_metadata(self, runner: CliRunner, transfer_project: Path) -> None:
        """A restamped ``generated_at`` (every regenerate) is not reported as drift."""
        cache = transfer_project / ".forge" / "prev_sessions" / "planner" / "generated.md"
        text = cache.read_text(encoding="utf-8")
        bumped = re.sub(r"generated_at: .*", "generated_at: 2099-01-01T00:00:00Z", text)
        assert bumped != text  # the frontmatter timestamp line existed and changed
        cache.write_text(bumped, encoding="utf-8")

        result = runner.invoke(main, ["session", "transfer", "diff", "planner", "--child", "exec"])
        assert result.exit_code == 0, result.output
        assert "No drift" in result.output
        assert "generated_at" not in result.output

    def test_diff_json_no_drift_wrapper(self, runner: CliRunner, transfer_project: Path) -> None:
        result = runner.invoke(main, ["session", "transfer", "diff", "planner", "--child", "exec", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert set(payload) == {"parent", "child", "has_drift", "diff"}
        assert payload["parent"] == "planner"
        assert payload["child"] == "exec"
        assert payload["has_drift"] is False
        assert payload["diff"] == ""

    def test_diff_json_drift_wrapper(self, runner: CliRunner, transfer_project: Path) -> None:
        cache = transfer_project / ".forge" / "prev_sessions" / "planner" / "generated.md"
        cache.write_text(cache.read_text(encoding="utf-8") + "\nDRIFTED LINE\n", encoding="utf-8")
        result = runner.invoke(main, ["session", "transfer", "diff", "planner", "--child", "exec", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert set(payload) == {"parent", "child", "has_drift", "diff"}
        assert payload["parent"] == "planner"
        assert payload["child"] == "exec"
        assert payload["has_drift"] is True
        assert "DRIFTED LINE" in payload["diff"]

    def test_diff_json_inferred_child(self, runner: CliRunner, transfer_project: Path) -> None:
        # No --child: the single seeded child ('exec') is inferred and echoed back.
        result = runner.invoke(main, ["session", "transfer", "diff", "planner", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["child"] == "exec"
        assert payload["has_drift"] is False
        assert payload["diff"] == ""

    def test_diff_json_missing_parent_stays_human_error(self, runner: CliRunner, transfer_project: Path) -> None:
        # Error path (no transfer context) stays human + exit 1, never JSON.
        result = runner.invoke(main, ["session", "transfer", "diff", "nope", "--json"])
        assert result.exit_code == 1
        assert "Error:" in result.output
        assert "show" in result.output  # recovery tip names the show path
        with pytest.raises(json.JSONDecodeError):
            json.loads(result.output)


class TestTransferCleanBreak:
    """The old top-level ``forge transfer`` group is gone (Slice 02 clean break)."""

    @pytest.mark.parametrize("sub", ["show", "regenerate", "edit", "diff"])
    def test_old_transfer_path_is_no_such_command(self, runner: CliRunner, sub: str) -> None:
        result = runner.invoke(main, ["transfer", sub, "planner"])
        assert result.exit_code == 2  # Click "No such command", no tombstone
        assert "No such command" in result.output
