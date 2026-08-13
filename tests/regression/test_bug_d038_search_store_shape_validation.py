"""D038 regressions for strict search-store container and element reads."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.search.bm25_store import BM25_INDEX_VERSION, TOKENIZER_ID, BM25IndexStore
from forge.search.content_store import CONTENT_STORE_VERSION, ContentStore
from forge.search.exceptions import (
    BM25IndexCorruptedError,
    ContentStoreCorruptedError,
    SearchDocumentStoreCorruptedError,
)
from forge.search.extractor import SearchDocumentMeta
from forge.search.store import DOCUMENT_STORE_VERSION, SearchDocumentStore

pytestmark = pytest.mark.regression


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _valid_bm25_payload() -> dict[str, Any]:
    return {
        "schema_version": BM25_INDEX_VERSION,
        "tokenizer_id": TOKENIZER_ID,
        "doc_keys": ["doc"],
        "doc_lens": [1],
        "term_freqs": [{"term": 1}],
        "doc_freqs": {"term": 1},
        "avgdl": 1.0,
        "k1": 1.5,
        "b": 0.75,
    }


@pytest.mark.parametrize(
    "documents",
    [
        pytest.param({}, id="wrong-container"),
        pytest.param(["not-an-object"], id="wrong-element"),
    ],
)
def test_document_store_rejects_wrong_container_or_element_type(tmp_path: Path, documents: object) -> None:
    store = SearchDocumentStore(store_path=tmp_path / "documents.json")
    _write_json(
        store.store_path,
        {"schema_version": DOCUMENT_STORE_VERSION, "documents": documents},
    )

    with pytest.raises(SearchDocumentStoreCorruptedError):
        store.read()


@pytest.mark.parametrize(
    "content",
    [
        pytest.param([], id="wrong-container"),
        pytest.param({"doc": 7}, id="wrong-value"),
    ],
)
def test_content_store_rejects_wrong_container_or_element_type(tmp_path: Path, content: object) -> None:
    store = ContentStore(store_path=tmp_path / "content.json")
    _write_json(
        store.store_path,
        {"schema_version": CONTENT_STORE_VERSION, "content": content},
    )

    with pytest.raises(ContentStoreCorruptedError):
        store.read_all()


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        pytest.param("doc_keys", [7], id="doc-key-element"),
        pytest.param("doc_lens", ["1"], id="doc-length-element"),
        pytest.param("term_freqs", [["term"]], id="term-frequency-container"),
        pytest.param("term_freqs", [{"term": "1"}], id="term-frequency-value"),
        pytest.param("doc_freqs", ["term"], id="document-frequency-container"),
        pytest.param("doc_freqs", {"term": "1"}, id="document-frequency-value"),
    ],
)
def test_bm25_store_rejects_wrong_container_or_element_type(
    tmp_path: Path,
    field: str,
    invalid_value: object,
) -> None:
    store = BM25IndexStore(store_path=tmp_path / "bm25_index.json")
    payload = _valid_bm25_payload()
    payload[field] = invalid_value
    _write_json(store.store_path, payload)

    with pytest.raises(BM25IndexCorruptedError):
        store.read()


def test_bm25_scalar_conversion_error_includes_rebuild_guidance(tmp_path: Path) -> None:
    store = BM25IndexStore(store_path=tmp_path / "bm25_index.json")
    payload = _valid_bm25_payload()
    payload["avgdl"] = "not-a-number"
    _write_json(store.store_path, payload)

    with pytest.raises(BM25IndexCorruptedError, match="rebuild-index"):
        store.read()


def test_malformed_bm25_element_reaches_cli_corruption_guidance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    (project / ".forge").mkdir(parents=True)
    monkeypatch.chdir(project)

    document_key = "/tmp/session/transcript.jsonl"
    SearchDocumentStore(forge_root=project).write(
        [
            SearchDocumentMeta(
                transcript_path=document_key,
                session_name="session",
                session_id="uuid",
                extracted_at="2026-08-13T00:00:00+00:00",
                metadata={},
            )
        ]
    )
    ContentStore(forge_root=project).write({document_key: "term"})
    bm25_store = BM25IndexStore(forge_root=project)
    payload = _valid_bm25_payload()
    payload["doc_keys"] = [document_key]
    payload["term_freqs"] = [["term"]]
    _write_json(bm25_store.store_path, payload)

    result = CliRunner().invoke(main, ["search", "query", "term"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Search index corrupted or outdated" in result.stderr
    assert "rebuild-index" in result.stderr
