"""Orphaned manifests require repair before instance-bound deletion."""

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.session import IndexStore, SessionStore, create_session_state
from tests.fixtures.session_state import publish_session, remove_index_row_only

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("options", [[], ["--yes"], ["--yes", "--force"]])
def test_delete_refuses_orphan_with_actionable_repair(tmp_path, monkeypatch, options):
    root = tmp_path / "project"
    root.mkdir()
    state = create_session_state("orphan", worktree_path=str(root))
    state.forge_root = str(root)
    index = IndexStore()
    publish_session(index, state, root, forge_root=root)
    # Deliberate crash residue: retain the manifest while losing publication authority.
    remove_index_row_only(index, "orphan", root)
    path = SessionStore(str(root), "orphan").manifest_path
    before = (path.read_bytes(), index.index_path.read_bytes())
    monkeypatch.chdir(root)
    result = CliRunner().invoke(main, ["session", "delete", "orphan", *options], input="y\n")
    assert result.exit_code == 1, result.output
    assert "forge session repair" in " ".join(result.output.split())
    assert (path.read_bytes(), index.index_path.read_bytes()) == before


def test_delete_reports_missing_session_without_creating_project_state(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(main, ["session", "delete", "absent", "--yes", "--force"])
    assert result.exit_code == 1, result.output
    assert "not found" in result.output
    assert not (tmp_path / ".forge").exists()
