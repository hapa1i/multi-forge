"""Remove exact transcript keys from every persistent search representation."""

from __future__ import annotations

import json
from collections import Counter
from contextlib import ExitStack
from pathlib import Path

from forge.core.state import file_lock_for_target

from .bm25_store import BM25IndexStore
from .content_store import ContentStore
from .index_state import IndexState, IndexStateStore
from .store import SearchDocumentStore


def search_store_paths(forge_root: Path) -> tuple[Path, ...]:
    """Return all stores whose entries participate in one indexed document."""
    return (
        SearchDocumentStore(forge_root).store_path,
        ContentStore(forge_root).store_path,
        BM25IndexStore(forge_root).store_path,
        IndexStateStore(forge_root).state_path,
    )


def indexed_transcript_paths(forge_root: Path) -> set[str]:
    """Read all keys, including partially published or orphaned entries."""
    documents = SearchDocumentStore(forge_root).read()
    content = ContentStore(forge_root).read_all()
    bm25 = BM25IndexStore(forge_root).read()
    state = _read_state(IndexStateStore(forge_root))
    return (
        {doc.transcript_path for doc in documents}
        | set(content)
        | (set(bm25.doc_keys) if bm25 else set())
        | set(state.indexed_files)
    )


def remove_transcript_paths(forge_root: Path, transcript_paths: tuple[str, ...]) -> None:
    """Remove explicit keys under all store locks, preserving unrelated entries.

    Each replacement is atomic and the operation is retryable after an I/O
    failure between stores. The session cleanup coordinator retains its durable
    inventory until every store and file removal has completed.
    """
    if not transcript_paths:
        return
    paths = search_store_paths(forge_root)
    if not any(path.exists() for path in paths):
        return
    keys = set(transcript_paths)
    with ExitStack() as stack:
        for path in sorted(paths):
            stack.enter_context(file_lock_for_target(target_path=path, timeout_s=5.0))

        documents_store = SearchDocumentStore(forge_root)
        content_store = ContentStore(forge_root)
        bm25_store = BM25IndexStore(forge_root)
        state_store = IndexStateStore(forge_root)
        # Validate every representation before the first write.
        documents = documents_store.read()
        content = content_store.read_all()
        bm25 = bm25_store.read()
        state = _read_state(state_store)
        kept_documents = [doc for doc in documents if doc.transcript_path not in keys]
        kept_content = {key: value for key, value in content.items() if key not in keys}
        kept_state = {key: value for key, value in state.indexed_files.items() if key not in keys}

        if len(kept_documents) != len(documents):
            documents_store.write(kept_documents)
        if kept_content != content:
            content_store.write(kept_content)
        if bm25 and keys.intersection(bm25.doc_keys):
            keep = [index for index, key in enumerate(bm25.doc_keys) if key not in keys]
            bm25.doc_keys = [bm25.doc_keys[index] for index in keep]
            bm25.doc_lens = [bm25.doc_lens[index] for index in keep]
            bm25.term_freqs = [bm25.term_freqs[index] for index in keep]
            frequencies: Counter[str] = Counter()
            for terms in bm25.term_freqs:
                frequencies.update(term for term, count in terms.items() if count > 0)
            bm25.doc_freqs = dict(frequencies)
            bm25.avgdl = sum(bm25.doc_lens) / max(len(bm25.doc_lens), 1)
            bm25_store.write(bm25)
        if kept_state != state.indexed_files:
            state.indexed_files = kept_state
            state_store.write(state)


def _read_state(store: IndexStateStore) -> IndexState:
    """Do not let the ordinary incremental reader silently discard malformed rows."""
    if store.exists():
        raw = json.loads(store.state_path.read_text(encoding="utf-8"))
        entries = raw.get("indexed_files") if isinstance(raw, dict) else None
        if not isinstance(entries, dict) or any(
            not isinstance(key, str)
            or not isinstance(value, dict)
            or set(value) != {"mtime", "size", "indexed_at"}
            or type(value.get("mtime")) not in (int, float)
            or type(value.get("size")) is not int
            or not isinstance(value.get("indexed_at"), str)
            for key, value in entries.items()
        ):
            raise ValueError(f"Malformed search fingerprints at {store.state_path}; run 'forge search rebuild-index'")
    return store.read()
