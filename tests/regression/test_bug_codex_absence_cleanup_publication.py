"""Post-turn absence handling must not sweep a concurrently published session."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from forge.core.ops.codex_session import _update_manifest_if_present
from forge.session import IndexStore, SessionStore, create_session_state
from forge.session.exceptions import SessionFileNotFoundError
from tests.fixtures.session_state import delete_published_session, publish_session

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("publication_boundary", ["before-error-handling", "during-shell-inspection"])
def test_absence_handler_preserves_replacement_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, publication_boundary: str
) -> None:
    index = IndexStore()
    store = SessionStore(str(tmp_path), "executor")
    previous = publish_session(index, create_session_state("executor", worktree_path=str(tmp_path)), tmp_path)
    assert previous.instance_id is not None
    replacement_files: dict[str, bytes] = {}
    replacement_index: list[bytes] = []
    inspection_armed = False

    def publish_replacement() -> None:
        if replacement_index:
            return
        replacement = create_session_state("executor", worktree_path=str(tmp_path), runtime="codex")
        entry = publish_session(index, replacement, tmp_path)
        assert entry.instance_id != previous.instance_id
        replacement_files.update(
            {path.name: path.read_bytes() for path in store.session_dir.iterdir() if path.is_file()}
        )
        replacement_index.append(index.index_path.read_bytes())

    original_scandir = os.scandir

    def scandir_then_publish(path: Any) -> Any:
        nonlocal inspection_armed
        if not inspection_armed or str(path) != str(store.session_dir):
            return original_scandir(path)
        inspection_armed = False
        with original_scandir(path) as scanner:
            entries = list(scanner)
        # The old sweep classified this snapshot, then rescanned and unlinked the
        # new publication's files. Publication here owns both manifest and row.
        publish_replacement()
        return iter(entries)

    monkeypatch.setattr(os, "scandir", scandir_then_publish)
    original_transaction = IndexStore.run_session_instance_txn

    def missing_after_transaction(self: IndexStore, *args: Any, **kwargs: Any) -> bool:
        nonlocal inspection_armed
        try:
            return original_transaction(self, *args, **kwargs)
        except SessionFileNotFoundError:
            # The failed writer has released the publication lock. A delete and
            # replacement can now complete before its exception handler returns.
            assert delete_published_session(index, "executor", tmp_path)
            store.session_dir.mkdir()
            store.manifest_path.with_suffix(".json.lock").touch()
            if publication_boundary == "before-error-handling":
                publish_replacement()
            else:
                inspection_armed = True
            raise

    def missing_update(**kwargs: Any) -> None:
        raise SessionFileNotFoundError(str(store.manifest_path))

    monkeypatch.setattr(IndexStore, "run_session_instance_txn", missing_after_transaction)
    monkeypatch.setattr(store, "update", missing_update)
    warnings: list[str] = []
    assert not _update_manifest_if_present(
        store,
        mutate=lambda state: None,
        warnings=warnings,
        session="executor",
        expected_instance_id=previous.instance_id,
    )
    # With no destructive sweep, publication is free to finish immediately after
    # the handler. The same transaction must work whether it overlaps or follows it.
    inspection_armed = False
    publish_replacement()

    assert store.manifest_path.exists(), "The absence handler removed the replacement manifest"
    assert {path.name: path.read_bytes() for path in store.session_dir.iterdir() if path.is_file()} == replacement_files
    assert index.index_path.read_bytes() == replacement_index[0]
    assert store.review_identity() != previous.instance_id
    assert any("skipped post-exit manifest update" in warning for warning in warnings)
