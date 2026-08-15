"""Tests for `forge session repair` (CLI leaf over the repair op)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.session import IndexStore, SessionStore, create_session_state
from forge.session.identity import make_scoped_key
from tests.fixtures.session_state import publish_session


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A Forge project root the command runs inside (no git needed for the CLI paths)."""
    root = tmp_path / "proj"
    (root / ".forge").mkdir(parents=True)
    monkeypatch.chdir(root)
    return root


def seed_orphan(root: Path, name: str, *, claude_id: str | None = None) -> None:
    state = create_session_state(name, worktree_path=str(root))
    if claude_id:
        state.confirmed.claude_session_id = claude_id
    SessionStore(str(root), name).write(state)


def seed_live(root: Path, name: str, *, claude_id: str | None = None) -> None:
    state = create_session_state(name, worktree_path=str(root))
    if claude_id:
        state.confirmed.claude_session_id = claude_id
    publish_session(IndexStore(), state, root, forge_root=root)


class TestSessionRepair:
    def test_outside_project_errors(self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        outside = tmp_path / "not-a-project"
        outside.mkdir()
        monkeypatch.chdir(outside)

        result = runner.invoke(main, ["session", "repair"])

        assert result.exit_code == 1
        assert "no Forge project found" in result.output

    def test_no_orphans_preview(self, runner: CliRunner, project: Path) -> None:
        result = runner.invoke(main, ["session", "repair"])

        assert result.exit_code == 0
        assert "No orphaned session manifests found" in result.output

    def test_preview_lists_orphan_and_is_read_only(self, runner: CliRunner, project: Path) -> None:
        seed_orphan(project, "orphan")

        result = runner.invoke(main, ["session", "repair"])

        assert result.exit_code == 0
        assert "orphan" in result.output
        assert "repairable" in result.output
        assert "Use --yes to repair." in result.output
        assert make_scoped_key("orphan", str(project)) not in IndexStore().read().sessions

    def test_yes_repairs(self, runner: CliRunner, project: Path) -> None:
        seed_orphan(project, "orphan")

        result = runner.invoke(main, ["session", "repair", "--yes"])

        assert result.exit_code == 0
        assert "Repaired 1: orphan" in result.output
        assert make_scoped_key("orphan", str(project)) in IndexStore().read().sessions

    def test_yes_collision_exits_1(self, runner: CliRunner, project: Path) -> None:
        seed_live(project, "live-one", claude_id="uuid-taken")
        seed_orphan(project, "orphan", claude_id="uuid-taken")

        result = runner.invoke(main, ["session", "repair", "--yes"])

        assert result.exit_code == 1
        assert "Refused orphan" in result.output
        assert make_scoped_key("orphan", str(project)) not in IndexStore().read().sessions

    def test_json_preview_shape(self, runner: CliRunner, project: Path) -> None:
        seed_orphan(project, "orphan")

        result = runner.invoke(main, ["session", "repair", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["forge_root"] == str(project)
        assert payload["compatibility"]["compatible"] is True
        assert payload["apply"] is None
        assert payload["apply_error"] is None
        (record,) = payload["records"]
        assert record["name"] == "orphan"
        assert record["classification"] == "repairable"
        assert record["identity"]["worktree_path"] == str(project)

    def test_json_yes_populates_apply(self, runner: CliRunner, project: Path) -> None:
        seed_orphan(project, "orphan")

        result = runner.invoke(main, ["session", "repair", "--yes", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["apply"]["repaired"] == ["orphan"]
        assert payload["apply"]["refused"] == []
        assert payload["apply"]["failed"] == []

    def test_incompatible_pin_preview_warns_apply_fails(self, runner: CliRunner, project: Path) -> None:
        seed_orphan(project, "orphan")
        (project / ".forge" / "project.toml").write_text('schema_version = 1\nrequired_forge = ">=99.0"\n')

        preview = runner.invoke(main, ["session", "repair"])
        assert preview.exit_code == 0
        assert "compatibility pin" in preview.output

        apply = runner.invoke(main, ["session", "repair", "--yes"])
        assert apply.exit_code == 1
        assert make_scoped_key("orphan", str(project)) not in IndexStore().read().sessions
