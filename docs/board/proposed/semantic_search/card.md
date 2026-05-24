# Semantic Search — Design Sketch

**Status**: Reference only. Extracted from the deleted `search-history` skill before removal. Not implemented in
`forge search` yet.

**Context**: Forge has BM25 keyword search (`forge search`). The `search-history` skill had a working semantic search
prototype using vector embeddings + RRF fusion. This doc preserves the architectural approach for when semantic search
is added to `forge search`.

---

## Architecture: Three-Retriever Pipeline

The prototype used a three-stage retrieval pipeline with Reciprocal Rank Fusion:

```
Query
  ├── Vector retriever (embedding similarity)  ──┐
  ├── BM25 retriever (keyword matching)         ──┼── RRF Fusion ── Reranker ── Results
  └── (forge search already has BM25)           ──┘
```

**Reciprocal Rank Fusion (RRF)** merges ranked lists from different retrievers:

```
score(doc) = Σ  1 / (k + rank_i(doc))    for each retriever i
```

Where `k = 60` (standard constant). Documents found by multiple retrievers get boosted scores.

## Model Choices (Tested)

| Component  | Model                    | Size   | Notes                                        |
| ---------- | ------------------------ | ------ | -------------------------------------------- |
| Embeddings | `BAAI/bge-small-en-v1.5` | ~130MB | Good quality/size tradeoff for local use     |
| Reranker   | `BAAI/bge-reranker-base` | ~560MB | Cross-encoder reranker, optional second pass |

Both models run locally (no API calls). Apple Silicon MPS acceleration works with `float16` dtype.

## Key Parameters (Tuned)

```python
CHUNK_SIZE = 512        # Tokens per chunk for splitting conversations
CHUNK_OVERLAP = 50      # Overlap between chunks
EMBED_BATCH_SIZE = 64   # Batch size for embedding generation
RRF_K = 60              # RRF constant (standard value)
RERANK_TOP_N = 20       # Reranker considers top 20 RRF results
```

## Device Detection

Apple Silicon MPS requires validation (some ops fail silently):

```python
def get_device() -> str:
    if torch.backends.mps.is_available():
        # Validate MPS actually works (some operations can fail)
        test_tensor = torch.randn(10, 10, dtype=torch.float16).to("mps")
        _ = test_tensor @ test_tensor.T
        return "mps"
    elif torch.cuda.is_available():
        return "cuda"
    return "cpu"
```

## Integration Notes for `forge search`

When adding semantic search to the existing search infrastructure:

1. **Index storage**: Extend the three-file store (`documents.json`, `bm25_index.json`, `content.json`) with a fourth
   file for vector embeddings, or use a separate vector store alongside.

2. **Auto-indexing**: The stop hook already triggers BM25 indexing via the work queue. Embedding generation should
   piggyback on the same pipeline (generate embeddings at index time, not query time).

3. **Dependency weight**: `llama-index` + `torch` + `sentence-transformers` are heavy (~2GB). Consider making semantic
   search an optional extra (`uv sync --extra semantic`) rather than a core dependency.

4. **Fallback**: Semantic search should degrade gracefully to BM25-only when dependencies are missing or index isn't
   built. The prototype handled this with `RAG_AVAILABLE` flag.

5. **Source data**: Must index Forge artifacts (`.forge/artifacts/`), not raw Claude JSONL. The prototype indexed raw
   JSONL which violates design decision #4.

## Dependencies (for reference)

```
llama-index-core
llama-index-embeddings-huggingface
llama-index-retrievers-bm25
llama-index-postprocessor-flag-embedding-reranker
torch
sentence-transformers
```
