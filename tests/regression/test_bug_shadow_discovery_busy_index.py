"""Shadow discovery must not report an incomplete session snapshot as complete."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.core.state import file_lock_for_target
from forge.session import IndexStore
from forge.session.passport import synthesize_passport, write_passport
from tests.fixtures.session_state import publish_session_from_fields

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("scope", ["workspace", "all"])
def test_shadow_discovery_refuses_incomplete_index_snapshot(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch, scope: str
) -> None:
    current = git_repo / "current"
    (current / ".forge").mkdir(parents=True)
    sibling = git_repo / "sibling"
    _write_shadow_project(sibling)
    monkeypatch.chdir(current)
    index = IndexStore()
    publish_session_from_fields(
        index, "legacy", git_repo, git_repo, forge_root=sibling, checkout_root=git_repo, relative_path="sibling"
    )
    # A complete legacy session may still have an unstamped index row.
    legacy = index.read()
    next(iter(legacy.sessions.values())).instance_id = None
    index.write(legacy)
    original = index.index_path.read_bytes()
    runner = CliRunner()
    args = ["memory", "shadows", "list", "--scope", scope, "--json"]

    before = runner.invoke(main, args)
    assert before.exit_code == 0, before.output
    assert [row["forge_root"] for row in json.loads(before.stdout)] == [str(sibling)]
    with file_lock_for_target(target_path=index.index_path, timeout_s=1):
        busy = runner.invoke(main, args)
    assert busy.exit_code == 1, busy.output
    assert busy.stdout == ""
    assert any(word in busy.stderr.lower() for word in ("retry", "rerun"))
    after = runner.invoke(main, args)
    assert after.exit_code == 0, after.output
    assert json.loads(after.stdout) == json.loads(before.stdout)
    assert index.index_path.read_bytes() == original


def test_project_shadow_discovery_remains_available_with_busy_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    _write_shadow_project(project)
    monkeypatch.chdir(project)
    with file_lock_for_target(target_path=IndexStore().index_path, timeout_s=1):
        result = CliRunner().invoke(main, ["memory", "shadows", "list", "--scope", "project", "--json"])
    assert result.exit_code == 0, result.output
    assert result.stderr == ""
    assert [row["forge_root"] for row in json.loads(result.stdout)] == [str(project)]


def _write_shadow_project(root: Path) -> None:
    shadow = root / ".forge/memory/shadow_notes.md"
    shadow.parent.mkdir(parents=True)
    shadow.write_text("# Proposed change\n")
    official = root / "docs/notes.md"
    official.parent.mkdir()
    official.write_text("# Notes\n")
    write_passport(
        official,
        synthesize_passport(strategy="generic", update_mode="shadow-only", shadow_path=".forge/memory/shadow_notes.md"),
    )
