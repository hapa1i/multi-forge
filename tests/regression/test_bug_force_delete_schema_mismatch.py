"""Force cannot authorize content cleanup from an unknown session schema."""

import json

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.session import IndexStore, SessionStore, create_session_state
from tests.fixtures.session_state import publish_session

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("corruption", ["future-schema", "missing-fields"])
@pytest.mark.parametrize("force", [False, True])
def test_delete_refuses_unknown_manifest_without_rewriting_state(tmp_path, monkeypatch, corruption, force):
    root = tmp_path / "project"
    root.mkdir()
    state = create_session_state("subject", worktree_path=str(root))
    state.forge_root = str(root)
    index = IndexStore()
    publish_session(index, state, root, forge_root=root)
    path = SessionStore(str(root), "subject").manifest_path
    raw = json.loads(path.read_text())
    if corruption == "future-schema":
        raw["schema_version"] = 999
    else:
        del raw["name"]
    path.write_text(json.dumps(raw))
    before = (path.read_bytes(), index.index_path.read_bytes())
    monkeypatch.chdir(root)
    result = CliRunner().invoke(main, ["session", "delete", "subject", "--yes", *(["--force"] if force else [])])
    assert result.exit_code == 1, result.output
    assert "Refused" in result.output
    assert (path.read_bytes(), index.index_path.read_bytes()) == before
