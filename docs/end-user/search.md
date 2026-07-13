# Forge Search — Transcript Search Guide

Search past session transcripts by keyword. Forge indexes transcripts automatically via the Stop hook and stores a
per-project BM25 index for fast lookup.

- Canonical architecture: [`docs/design.md`](../design.md)
- Sessions (unit of work): [`session.md`](session.md)
- Hooks (lifecycle events): [`hook.md`](hook.md)

---

## Quick start

```bash
# Search for a keyword or phrase (human-readable table)
forge search query "timeout config"

# Machine-readable JSON for scripting
forge search query "timeout config" --json

# Limit results
forge search query "proxy routing" -n 5

# Search across all indexed projects (not just current)
forge search query "auth refactor" --scope all
```

By default `query` prints a table (`Score`, `Session`, `Snippet`) with a `Found N result(s)` footer. Pass `--json` for
the scripting shape: an object with `query`, `total_results`, and a `results` array whose entries carry `session_name`,
`session_id`, `score`, `snippet`, `transcript_path`, and `metadata` (including timestamps).

---

## How indexing works

Forge indexes transcripts **automatically** via the Stop hook pipeline:

```
Session stops
  → Stop hook copies transcript to <forge_root>/.forge/artifacts/
  → Stop hook enqueues "index" work marker
  → (session ends)

Next forge command (any)
  → Work queue processes pending markers
  → Transcript is extracted, tokenized, and added to the BM25 index
```

Indexing is **incremental** — only new or modified transcripts are processed. The index is per-project, stored at
`<forge_root>/.forge/search-index/`.

The startup worker strict-checks that project's `.forge/project.toml` before changing the index. A compatibility refusal
increments the marker's normal attempt count and records the error; after the bounded retry limit the marker moves to
`~/.forge/pending-work/failed/`. Queue processing never turns that refusal into failure of the foreground command, and
later compatible markers continue to run. After installing a Forge version satisfying `required_forge` (or
editing/resetting the pin), run `forge search rebuild-index` to rebuild explicitly.

---

## CLI reference

### Search

```bash
forge search query <query> [-n <limit>] [--scope project|all] [--json]
```

- `<query>` — search terms (quote phrases with spaces)
- `-n` / `--limit` — max results to return
- `--scope` — `project` (default, current project only) or `all` (all indexed projects)
- `--json` — emit the machine-readable JSON shape instead of the default table

### Index management

```bash
# Show index statistics (document count, last indexed, index health)
forge search status

# Full rebuild from all transcript artifacts
forge search rebuild-index

# Preview orphaned entries (transcripts that were deleted); --json for scripting; --yes to prune
forge search clean
forge search clean --json
forge search clean --yes
```

`status`, `query`, and `search clean` preview/JSON reads remain available under an incompatible pin. `rebuild-index` and
`search clean --yes` strict-check the current Forge root before replacing or pruning index state; preview output labels
targets that apply would refuse. `--yes` and other force/confirmation controls do not bypass `required_forge`.

---

## What gets indexed

| Content                              | Indexing               |
| ------------------------------------ | ---------------------- |
| User messages                        | Fully indexed          |
| Assistant messages                   | Fully indexed          |
| Tool inputs (commands, paths)        | Truncated to 100 chars |
| Tool results (file contents, output) | Truncated to 500 chars |

Truncation yields ~20-50x compression over raw transcripts while keeping terms searchable. Full transcripts remain in
`<forge_root>/.forge/artifacts/` for direct inspection.

---

## Index location

The search index is **per-project**, stored at:

```
<project_root>/.forge/search-index/
├── documents.json      # Document metadata (session names, timestamps)
├── bm25_index.json     # Precomputed BM25 term frequencies + tokenizer version
└── content.json        # Extracted text snippets (loaded only for top-K results)
```

The three-file split keeps queries fast (~300KB loaded vs ~5MB for full content).

---

## Troubleshooting

### "No results" for a term you know exists

- Check if the index is built: `forge search status`
- If not built or stale: `forge search rebuild-index`
- Search uses BM25 keyword matching — exact terms work best. Try shorter or more specific queries.

### "Index not built"

The index builds automatically when sessions end (via Stop hook). If you haven't ended any sessions since installing
Forge, build manually:

```bash
forge search rebuild-index
```

### "Orphaned documents"

If you deleted transcript files but the index still references them (previews by default; `--yes` to prune):

```bash
forge search clean         # preview what would be pruned
forge search clean --json  # preview as JSON
forge search clean --yes   # actually prune
```

### "Index corrupted"

If search returns errors about store mismatches:

```bash
forge search rebuild-index
```

A full rebuild reconstructs all three store files from the source transcripts.

---

## Files to inspect (debugging)

| File                                               | Purpose                                    |
| -------------------------------------------------- | ------------------------------------------ |
| `<forge_root>/.forge/search-index/documents.json`  | Indexed document metadata                  |
| `<forge_root>/.forge/search-index/bm25_index.json` | BM25 term index                            |
| `<forge_root>/.forge/search-index/content.json`    | Extracted text content                     |
| `<forge_root>/.forge/artifacts/*/transcripts/`     | Source transcripts (index input)           |
| `~/.forge/pending-work/`                           | Work queue markers (index markers pending) |
| `~/.forge/pending-work/failed/`                    | Markers that exhausted bounded retries     |
