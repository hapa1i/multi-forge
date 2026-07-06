"""Regression: search store read OSError is unreadable, not corruption."""

from __future__ import annotations

import builtins
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from forge.cli.search import search_cmd
from forge.core.state import StateCorruptedError, StateUnreadableError
from forge.search.bm25_store import BM25IndexStore
from forge.search.content_store import ContentStore
from forge.search.exceptions import (
    BM25IndexCorruptedError,
    BM25IndexUnreadableError,
    ContentStoreCorruptedError,
    ContentStoreUnreadableError,
    IndexStateCorruptedError,
    IndexStateUnreadableError,
    SearchDocumentStoreCorruptedError,
    SearchDocumentStoreUnreadableError,
)
from forge.search.index_state import IndexStateStore
from forge.search.store import SearchDocumentStore

pytestmark = pytest.mark.regression


StoreFactory = Callable[[Path], tuple[Callable[[], object], type[StateUnreadableError], type[StateCorruptedError]]]


def _matches_path(file: Any, target: Path) -> bool:
    try:
        value = os.fspath(file)
    except TypeError:
        return False
    if isinstance(value, bytes):
        value = value.decode()
    return Path(value) == target


def _document_store(path: Path) -> tuple[Callable[[], object], type[StateUnreadableError], type[StateCorruptedError]]:
    return (
        SearchDocumentStore(store_path=path).read,
        SearchDocumentStoreUnreadableError,
        SearchDocumentStoreCorruptedError,
    )


def _content_store(path: Path) -> tuple[Callable[[], object], type[StateUnreadableError], type[StateCorruptedError]]:
    return ContentStore(store_path=path).read_all, ContentStoreUnreadableError, ContentStoreCorruptedError


def _bm25_store(path: Path) -> tuple[Callable[[], object], type[StateUnreadableError], type[StateCorruptedError]]:
    return BM25IndexStore(store_path=path).read, BM25IndexUnreadableError, BM25IndexCorruptedError


def _index_state_store(
    path: Path,
) -> tuple[Callable[[], object], type[StateUnreadableError], type[StateCorruptedError]]:
    return IndexStateStore(state_path=path).read, IndexStateUnreadableError, IndexStateCorruptedError


@pytest.mark.parametrize("factory", [_document_store, _content_store, _bm25_store, _index_state_store])
def test_search_store_oserror_is_unreadable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, factory: StoreFactory
) -> None:
    path = tmp_path / "store.json"
    path.write_text("{}", encoding="utf-8")
    read, unreadable_error, _corrupted_error = factory(path)
    real_open = builtins.open

    def open_spy(file: Any, *args: Any, **kwargs: Any) -> object:
        if _matches_path(file, path):
            raise OSError("permission denied")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", open_spy)

    with pytest.raises(unreadable_error) as exc_info:
        read()

    assert isinstance(exc_info.value, StateUnreadableError)
    assert not isinstance(exc_info.value, StateCorruptedError)


@pytest.mark.parametrize("factory", [_document_store, _content_store, _bm25_store, _index_state_store])
def test_search_store_invalid_json_stays_corrupted(tmp_path: Path, factory: StoreFactory) -> None:
    path = tmp_path / "store.json"
    path.write_text("{not json", encoding="utf-8")
    read, _unreadable_error, corrupted_error = factory(path)

    with pytest.raises(corrupted_error):
        read()


def test_search_clean_json_routes_unreadable_as_check_retry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "project"
    store_path = project / ".forge" / "search-index" / "documents.json"
    store_path.parent.mkdir(parents=True)
    store_path.write_text(json.dumps({"schema_version": 1, "documents": []}), encoding="utf-8")
    real_open = builtins.open

    def open_spy(file: Any, *args: Any, **kwargs: Any) -> object:
        if _matches_path(file, store_path):
            raise OSError("permission denied")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", open_spy)
    monkeypatch.chdir(project)

    result = CliRunner().invoke(search_cmd, ["clean", "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.stderr)
    assert "unreadable" in payload["error"].lower()
    assert "retry" in payload["hint"].lower()
    assert "rebuild" not in payload["hint"].lower()
