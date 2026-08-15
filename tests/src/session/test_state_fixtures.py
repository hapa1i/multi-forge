"""Unit contracts for invariant-preserving durable session test builders."""

import ast
from collections import Counter
from pathlib import Path

import pytest

from forge.session.exceptions import UuidAlreadyBoundError
from forge.session.identity import make_scoped_key
from forge.session.index import IndexStore
from forge.session.models import create_session_state
from forge.session.store import SessionStore
from tests.fixtures.session_state import (
    delete_published_session,
    publish_session,
    remove_index_row_only,
    seed_row_only_session,
)

_LEGACY_MUTATOR_CONTRACTS = Counter(
    {
        ("add_session", "TestIndexStoreAddSession.test_add_session_basic"): 1,
        ("add_session", "TestIndexStoreAddSession.test_add_session_with_flags"): 1,
        ("add_session", "TestIndexStoreAddSession.test_add_session_duplicate"): 2,
        ("add_session", "TestIndexStoreAddSession.test_add_session_invalid_name"): 1,
        ("add_session", "TestIndexStoreRemoveSession.test_remove_session_existing"): 1,
        (
            "remove_session",
            "TestIndexStoreRemoveSession.test_remove_session_existing",
        ): 1,
        (
            "remove_session",
            "TestIndexStoreRemoveSession.test_remove_session_not_found",
        ): 1,
        (
            "remove_session",
            "TestIndexStoreRemoveSession.test_remove_session_invalid_name",
        ): 1,
        (
            "add_from_state",
            "TestIndexStoreAddFromManifest.test_add_from_state_basic",
        ): 1,
        (
            "add_from_state",
            "TestIndexStoreAddFromManifest.test_add_from_state_with_worktree",
        ): 1,
        (
            "add_from_state",
            "TestIndexStoreAddFromManifest.test_add_from_state_with_flags",
        ): 1,
        ("add_session", "TestProjectScopedNames.test_remove_session_scoped"): 2,
        ("remove_session", "TestProjectScopedNames.test_remove_session_scoped"): 1,
        (
            "add_session",
            "TestProjectScopedNames.test_remove_session_unscoped_ambiguous_raises",
        ): 2,
        (
            "remove_session",
            "TestProjectScopedNames.test_remove_session_unscoped_ambiguous_raises",
        ): 1,
    }
)


def test_publish_session_writes_row_before_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    index = IndexStore(tmp_path / "index.json")
    state = create_session_state("planner", worktree_path=str(project))
    original = SessionStore.create_exclusive
    observations: list[tuple[bool, bool]] = []

    def observe_then_write(store: SessionStore, manifest) -> None:
        key = make_scoped_key(state.name, str(project))
        observations.append((key in index.read().sessions, store.exists()))
        original(store, manifest)

    monkeypatch.setattr(SessionStore, "create_exclusive", observe_then_write)

    publish_session(index, state, project, forge_root=project)

    assert observations == [(True, False)]
    assert SessionStore(str(project), state.name).read() == state


def test_publish_session_compensates_when_manifest_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    index = IndexStore(tmp_path / "index.json")
    state = create_session_state("planner", worktree_path=str(project))

    def fail_write(_store: SessionStore, _manifest) -> None:
        raise OSError("injected manifest failure")

    monkeypatch.setattr(SessionStore, "create_exclusive", fail_write)

    with pytest.raises(OSError, match="injected manifest failure"):
        publish_session(index, state, project, forge_root=project)

    assert index.read().sessions == {}
    assert not SessionStore(str(project), state.name).exists()


def test_publish_session_preserves_binding_uniqueness(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    index = IndexStore(tmp_path / "index.json")
    first = create_session_state("first", worktree_path=str(project))
    first.confirmed.claude_session_id = "shared-uuid"
    second = create_session_state("second", worktree_path=str(project))
    second.confirmed.claude_session_id = "shared-uuid"

    publish_session(
        index, first, project, forge_root=project, require_uuid_unbound=True
    )
    with pytest.raises(UuidAlreadyBoundError):
        publish_session(
            index, second, project, forge_root=project, require_uuid_unbound=True
        )

    assert not SessionStore(str(project), second.name).exists()


def test_delete_published_session_removes_manifest_before_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    index = IndexStore(tmp_path / "index.json")
    state = create_session_state("planner", worktree_path=str(project))
    publish_session(index, state, project, forge_root=project)
    original = SessionStore.delete
    observations: list[tuple[bool, bool]] = []

    def observe_then_delete(store: SessionStore) -> bool:
        key = make_scoped_key(state.name, str(project))
        observations.append((key in index.read().sessions, store.exists()))
        return original(store)

    monkeypatch.setattr(SessionStore, "delete", observe_then_delete)

    assert delete_published_session(index, state.name, project)

    assert observations == [(True, True)]
    assert index.read().sessions == {}
    assert not SessionStore(str(project), state.name).exists()


def test_row_only_helpers_make_the_invalid_dimension_explicit(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    index = IndexStore(tmp_path / "index.json")
    state = create_session_state("residue", worktree_path=str(project))

    seed_row_only_session(index, state, project, forge_root=project)
    assert index.session_exists(state.name, forge_root=str(project))
    assert not SessionStore(str(project), state.name).exists()

    SessionStore(str(project), state.name).create_exclusive(state)
    assert remove_index_row_only(index, state.name, project)
    assert not index.session_exists(state.name, forge_root=str(project))
    assert SessionStore(str(project), state.name).exists()


def test_publish_session_rejects_manifest_index_root_mismatch(tmp_path: Path) -> None:
    project = tmp_path / "project"
    other = tmp_path / "other"
    project.mkdir()
    other.mkdir()
    index = IndexStore(tmp_path / "index.json")
    state = create_session_state("planner", worktree_path=str(project))
    state.forge_root = str(project)

    with pytest.raises(ValueError, match="does not match indexed forge_root"):
        publish_session(index, state, project, forge_root=other)

    assert index.read().sessions == {}


def test_legacy_index_mutators_are_confined_to_direct_contract_tests() -> None:
    """Ordinary fixtures cannot silently reintroduce the APIs reserved for order 15."""
    repo = Path(__file__).resolve().parents[3]
    found: Counter[tuple[str, str]] = Counter()
    paths: set[str] = set()
    names = {"add_session", "add_from_state", "remove_session"}

    for path in (repo / "tests").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parents = {
            child: node
            for node in ast.walk(tree)
            for child in ast.iter_child_nodes(node)
        }
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in names
            ):
                continue
            scopes: list[str] = []
            current = node
            while current in parents:
                current = parents[current]
                if isinstance(
                    current, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
                ):
                    scopes.append(current.name)
            found[(node.func.attr, ".".join(reversed(scopes)))] += 1
            paths.add(str(path.relative_to(repo)))

    assert paths == {"tests/src/session/test_index.py"}
    assert found == _LEGACY_MUTATOR_CONTRACTS
