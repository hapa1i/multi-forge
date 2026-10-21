"""Malformed derivation evidence refuses cleanup without deleting or guessing ownership."""

import json
from pathlib import Path

import pytest

from forge.session import (
    ForgeSessionError,
    IndexStore,
    SessionManager,
    SessionStore,
    create_session_state,
)
from tests.fixtures.session_state import publish_session

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("bad", ["oops", 123, 4.5, ["uuid"], True])
def test_malformed_derivation_refuses_without_mutation(tmp_path: Path, bad: object) -> None:
    root = tmp_path / "project"
    root.mkdir()
    state = create_session_state("broken", worktree_path=str(root))
    index = IndexStore()
    publish_session(index, state, root)
    store = SessionStore(str(root), "broken")
    raw = json.loads(store.manifest_path.read_bytes())
    raw["confirmed"]["derivation"] = bad
    store.manifest_path.write_text(json.dumps(raw))
    before = store.manifest_path.read_bytes()

    with pytest.raises(ForgeSessionError, match="[Mm]anifest"):
        SessionManager(index).delete_session("broken", forge_root=str(root), force=True)

    assert store.manifest_path.read_bytes() == before
    assert index.peek_session("broken", forge_root=str(root)) is not None
