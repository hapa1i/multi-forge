<!-- prereq: 0.3, 10.1 -->

## 12. Search (`forge search`)

### 12.1 Check Index Status

<!-- auto -->

```bash
forge search status
```

- [ ] Shows index statistics (document count, store health)
- [ ] Shows index location

### 12.2 Build/Rebuild Index

<!-- auto -->

```bash
# Full rebuild from all transcript artifacts
forge search rebuild-index
```

- [ ] Rebuilds index from `.forge/artifacts/`
- [ ] Reports number of documents indexed

### 12.3 Search Transcripts

<!-- auto -->

```bash
# Search for a keyword (human table by default)
forge search query "hello world"

# Machine-readable JSON for scripting
forge search query "hello world" --json

# Limit results
forge search query "test" -n 3

# Search all projects
forge search query "hello world" --scope all --json
```

- [ ] Bare query prints a human table (Score / Session / Snippet) with a `Found N result(s)` footer
- [ ] `--json` returns JSON results with session_name, score, snippet
- [ ] `--scope all` searches indexed projects (including the current project)
- [ ] Results ranked by BM25 relevance

### 12.4 Clean Orphaned Entries

<!-- auto -->

```bash
forge search clean          # preview (default)
forge search clean --yes    # actually prune
```

- [ ] Bare `clean` previews ("Would prune ...") without removing
- [ ] `--yes` removes entries for deleted transcripts
- [ ] Reports removed/pruned count or "No orphaned entries found."

---
