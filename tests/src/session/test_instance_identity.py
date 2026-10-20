"""Session generations bind destructive actions and detached writes to one creation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from forge.session.cleanup_state import cleanup_state_path
from forge.session.exceptions import (
    IndexCorruptedError,
    ManifestChangedError,
    SessionFileNotFoundError,
)
from forge.session.identity import make_scoped_key
from forge.session.index import IndexStore
from forge.session.models import INDEX_VERSION, create_session_state
from forge.session.store import SessionStore
from tests.fixtures.session_state import publish_session, seed_row_only_session


def _publish(tmp_path: Path, index: IndexStore) -> tuple[SessionStore, str]:
    root = tmp_path / "project"
    root.mkdir(exist_ok=True)
    state = create_session_state("worker", worktree_path=str(root))
    entry = publish_session(index, state, root)
    assert entry.instance_id is not None
    return SessionStore(str(root), "worker"), entry.instance_id


def _legacy_index(index: IndexStore) -> None:
    data = json.loads(index.index_path.read_text())
    data["version"] = 1
    for entry in data["sessions"].values():
        entry.pop("instance_id")
    index.index_path.write_text(json.dumps(data))


def test_new_publication_and_stop_owner_share_identity(tmp_path: Path) -> None:
    index = IndexStore(tmp_path / "index.json")
    store, token = _publish(tmp_path, index)

    assert len(token) == 32
    assert store.review_identity() == token
    assert index.read().version == INDEX_VERSION
    assert index.get_session("worker", str(store.forge_root)).instance_id == token


def test_legacy_preview_does_not_bind_or_write(tmp_path: Path) -> None:
    index = IndexStore(tmp_path / "index.json")
    store, token = _publish(tmp_path, index)
    _legacy_index(index)
    before = index.index_path.read_bytes()
    manifest_before = store.manifest_path.read_bytes()

    entry = index.peek_session("worker", str(store.forge_root))

    assert entry is not None and entry.instance_id is None
    assert store.review_identity() == token
    assert index.index_path.read_bytes() == before
    assert store.manifest_path.read_bytes() == manifest_before
    assert index.migrate_session_identity("worker", str(store.forge_root)) == token
    assert index.get_session("worker", str(store.forge_root)).instance_id == token
    assert store.manifest_path.read_bytes() == manifest_before


def test_migration_initializes_ownerless_legacy_session(tmp_path: Path) -> None:
    index = IndexStore(tmp_path / "index.json")
    store, _ = _publish(tmp_path, index)
    _legacy_index(index)
    (store.session_dir / "review-identity").unlink()

    token = index.migrate_session_identity("worker", str(store.forge_root))

    assert token == store.review_identity()
    assert token == index.get_session("worker", str(store.forge_root)).instance_id


def test_migration_refuses_ownerless_review_history(tmp_path: Path) -> None:
    index = IndexStore(tmp_path / "index.json")
    store, _ = _publish(tmp_path, index)
    _legacy_index(index)
    owner = store.session_dir / "review-identity"
    owner.unlink()
    history = store.forge_root / ".forge/artifacts/worker/review"
    history.mkdir(parents=True)
    (history / "journal.json").write_text("{}")
    before = index.index_path.read_bytes()

    with pytest.raises(ValueError, match="history has no session owner"):
        index.migrate_session_identity("worker", str(store.forge_root))

    assert index.index_path.read_bytes() == before
    assert not owner.exists()


def test_migration_refuses_row_only_state(tmp_path: Path) -> None:
    index = IndexStore(tmp_path / "index.json")
    root = tmp_path / "project"
    root.mkdir()
    state = create_session_state("worker", worktree_path=str(root))
    # Deliberately omit the manifest to model interrupted row-first publication.
    seed_row_only_session(index, state, root)
    before = index.index_path.read_bytes()

    with pytest.raises(SessionFileNotFoundError):
        index.migrate_session_identity("worker", str(root))

    assert index.index_path.read_bytes() == before
    assert not SessionStore(str(root), "worker").session_dir.exists()


def test_migration_refuses_changed_preview_manifest(tmp_path: Path) -> None:
    index = IndexStore(tmp_path / "index.json")
    store, _ = _publish(tmp_path, index)
    _legacy_index(index)
    digest = hashlib.sha256(store.manifest_path.read_bytes()).hexdigest()
    store.update(timeout_s=1, mutate=lambda state: setattr(state, "last_accessed_at", "changed"))
    before = index.index_path.read_bytes()

    with pytest.raises(ManifestChangedError):
        index.migrate_session_identity("worker", str(store.forge_root), expected_manifest_sha256=digest)

    assert index.index_path.read_bytes() == before


def test_detached_writer_refuses_deleted_and_replaced_instances(tmp_path: Path) -> None:
    index = IndexStore(tmp_path / "index.json")
    store, original = _publish(tmp_path, index)
    writes: list[bool] = []

    def persist() -> None:
        writes.append(True)

    assert index.run_session_instance_txn(
        "worker", str(store.forge_root), expected_instance_id=original, callback=persist
    )
    assert index.delete_session_txn(
        "worker",
        str(store.forge_root),
        expected_instance_id=original,
        delete_manifest=lambda: store.delete_locked(),
    )
    assert not index.run_session_instance_txn(
        "worker", str(store.forge_root), expected_instance_id=original, callback=persist
    )
    replacement, _ = _publish(tmp_path, index)
    assert not index.run_session_instance_txn(
        "worker", str(store.forge_root), expected_instance_id=original, callback=persist
    )
    with pytest.raises(ManifestChangedError):
        replacement.update(timeout_s=1, expected_instance_id=original, mutate=lambda state: None)
    assert writes == [True]


def test_interrupted_cleanup_retains_generation_after_manifest_removal(
    tmp_path: Path,
) -> None:
    index = IndexStore(tmp_path / "index.json")
    store, token = _publish(tmp_path, index)

    def interrupted() -> None:
        store.delete_locked()
        raise OSError("cleanup interrupted")

    with pytest.raises(OSError, match="interrupted"):
        index.delete_session_txn(
            "worker",
            str(store.forge_root),
            expected_instance_id=token,
            delete_manifest=interrupted,
        )
    assert index.read().sessions[make_scoped_key("worker", str(store.forge_root))].instance_id == token
    assert index.delete_session_txn(
        "worker",
        str(store.forge_root),
        expected_instance_id=token,
        delete_manifest=lambda: None,
    )
    assert index.read().sessions == {}


def test_pending_cleanup_reserves_name_without_manifest(tmp_path: Path) -> None:
    index = IndexStore(tmp_path / "index.json")
    store, _ = _publish(tmp_path, index)
    store.delete()
    inventory = cleanup_state_path(store.forge_root, "worker")
    inventory.parent.mkdir(parents=True, exist_ok=True)
    inventory.write_text("{}")
    before = index.index_path.read_bytes()

    with pytest.raises(ValueError, match="unfinished cleanup"):
        _publish(tmp_path, index)

    assert index.get_session("worker", str(store.forge_root)).instance_id is not None
    assert [name for name, _entry in index.list_sessions()] == ["worker"]
    assert [name for name, _entry in index.peek_sessions()] == ["worker"]
    assert index.index_path.read_bytes() == before
    assert not store.exists()


def test_pending_cleanup_refuses_writes_before_manifest_is_removed(tmp_path: Path) -> None:
    index = IndexStore(tmp_path / "index.json")
    store, token = _publish(tmp_path, index)
    inventory = cleanup_state_path(store.forge_root, "worker")
    inventory.parent.mkdir(parents=True, exist_ok=True)
    inventory.write_text("{}")
    writes: list[bool] = []

    assert not index.run_session_instance_txn(
        "worker", str(store.forge_root), expected_instance_id=token, callback=lambda: writes.append(True)
    )
    with pytest.raises(ManifestChangedError):
        store.update(timeout_s=1, expected_instance_id=token, mutate=lambda state: writes.append(True))
    assert writes == []


@pytest.mark.parametrize("bad_token", ["", "a" * 31, "G" * 32, 1, False])
def test_index_rejects_malformed_instance_identity(tmp_path: Path, bad_token: object) -> None:
    index = IndexStore(tmp_path / "index.json")
    _publish(tmp_path, index)
    data = json.loads(index.index_path.read_text())
    next(iter(data["sessions"].values()))["instance_id"] = bad_token
    index.index_path.write_text(json.dumps(data))

    with pytest.raises(IndexCorruptedError, match="invalid instance_id"):
        index.read()


def test_dependency_binding_refuses_replaced_source(tmp_path: Path) -> None:
    from tests.fixtures.session_state import (
        delete_published_session,
        publish_session_from_fields,
    )

    index = IndexStore()
    source = publish_session_from_fields(index, "planner", tmp_path, tmp_path)
    executor = publish_session_from_fields(index, "executor", tmp_path, tmp_path)
    assert source.instance_id is not None and executor.instance_id is not None
    writes: list[bool] = []
    delete_published_session(index, "planner", tmp_path)
    publish_session_from_fields(index, "planner", tmp_path, tmp_path)

    assert not index.run_session_instance_txn(
        "executor",
        str(tmp_path),
        expected_instance_id=executor.instance_id,
        required_instances=((str(tmp_path), "planner", source.instance_id),),
        callback=lambda: writes.append(True),
    )
    assert writes == []
