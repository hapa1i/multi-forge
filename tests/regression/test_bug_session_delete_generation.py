"""Regression: a second stale deleter removed a same-name replacement."""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.session.index import IndexStore
from forge.session.models import create_session_state
from forge.session.store import SessionStore
from tests.fixtures.session_state import publish_session

pytestmark = pytest.mark.regression


def _publish(tmp_path: Path, index: IndexStore) -> tuple[SessionStore, str]:
    root = tmp_path / "project"
    root.mkdir(exist_ok=True)
    state = create_session_state("worker", worktree_path=str(root))
    entry = publish_session(index, state, root)
    assert entry.instance_id is not None
    return SessionStore(str(root), "worker"), entry.instance_id


def test_stale_second_deleter_cannot_remove_same_name_replacement(
    tmp_path: Path,
) -> None:
    index = IndexStore(tmp_path / "index.json")
    store, original = _publish(tmp_path, index)
    assert index.delete_session_txn(
        "worker",
        str(store.forge_root),
        expected_instance_id=original,
        delete_manifest=lambda: store.delete_locked(),
    )
    replacement, current = _publish(tmp_path, index)
    manifest_before = replacement.manifest_path.read_bytes()
    called: list[bool] = []

    assert not index.delete_session_txn(
        "worker",
        str(store.forge_root),
        expected_instance_id=original,
        delete_manifest=lambda: called.append(True),
    )

    assert current != original
    assert called == []
    assert replacement.manifest_path.read_bytes() == manifest_before
    assert index.get_session("worker", str(store.forge_root)).instance_id == current
