"""Creation compensation cannot remove a checkout adopted by a replacement instance."""

from copy import deepcopy
from pathlib import Path

import pytest

from forge.session import IndexStore, SessionManager, SessionStore, create_session_state
from forge.session.exceptions import ForgeSessionError
from tests.fixtures.session_state import delete_published_session, publish_session

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("operation", ["start", "fork"])
def test_failed_creation_preserves_replacement_checkout(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    monkeypatch.chdir(git_repo)
    (git_repo / ".forge").mkdir(exist_ok=True)
    index = IndexStore()
    manager = SessionManager(index)
    if operation == "fork":
        manager.start_session("parent", direct=True)
    original = index.run_session_instance_txn
    replacement_paths: list[tuple[str, Path, str]] = []

    def replace_before_creation_event(name, root, **kwargs):
        if name == "subject" and not replacement_paths:
            store = SessionStore(root, name)
            old = store.read()
            assert old.worktree is not None
            delete_published_session(index, name, root)
            replacement = create_session_state(name, worktree_path=old.worktree.path)
            replacement.worktree = deepcopy(old.worktree)
            replacement.forge_root = root
            publish_session(index, replacement, git_repo, forge_root=root)
            token = store.review_identity()
            assert token is not None
            replacement_paths.append((root, Path(old.worktree.path), token))
        return original(name, root, **kwargs)

    monkeypatch.setattr(index, "run_session_instance_txn", replace_before_creation_event)
    with pytest.raises(ForgeSessionError, match="now referenced by session"):
        if operation == "start":
            manager.start_session("subject", create_worktree=True, direct=True)
        else:
            manager.fork_session("parent", "subject", create_worktree=True, direct=True)

    root, checkout, token = replacement_paths[0]
    assert checkout.is_dir()
    assert SessionStore(root, "subject").review_identity() == token
    assert index.get_session("subject", root).instance_id == token
