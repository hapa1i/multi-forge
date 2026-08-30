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
set -euo pipefail
cd "$FORGE_TEST_REPO"

# Create one real indexed transcript, then remove only its source so clean has a
# deterministic orphan without hand-writing internal search-store schemas.
ORPHAN_DIR=.forge/artifacts/qa-search-clean/transcripts
ORPHAN_PATH="$ORPHAN_DIR/qa-orphan.jsonl"
mkdir -p "$ORPHAN_DIR"
cat >"$ORPHAN_PATH" <<'EOF'
{"timestamp":"2026-08-30T00:00:00Z","message":{"role":"user","content":[{"type":"text","text":"qa orphan cleanup fixture"}]}}
EOF
forge search rebuild-index
rm -f "$ORPHAN_PATH"

forge search clean | tee /tmp/qa-search-clean-preview-1.txt
rg -q 'Would prune' /tmp/qa-search-clean-preview-1.txt
# A second preview must still see the orphan, proving preview was non-mutating.
forge search clean | tee /tmp/qa-search-clean-preview-2.txt
rg -q 'Would prune' /tmp/qa-search-clean-preview-2.txt

forge search clean --yes | tee /tmp/qa-search-clean-apply.txt
rg -q 'Pruned' /tmp/qa-search-clean-apply.txt
forge search clean | tee /tmp/qa-search-clean-final.txt
rg -q 'No orphaned entries found' /tmp/qa-search-clean-final.txt

rmdir "$ORPHAN_DIR" "$(dirname "$ORPHAN_DIR")" 2>/dev/null || true
rm -f /tmp/qa-search-clean-preview-{1,2}.txt /tmp/qa-search-clean-{apply,final}.txt
```

- [ ] Bare `clean` previews ("Would prune ...") without removing
- [ ] `--yes` removes entries for deleted transcripts
- [ ] Reports removed/pruned count or "No orphaned entries found."

### 12.5 Corrupt Reads Fail Consistently

<!-- prereq: 12.2 -->

<!-- auto -->

Temporarily replace the BM25 store with malformed JSON, exercise both read leaves and output modes, then restore the
byte-identical store before asserting the captured results.

```bash
cd "$FORGE_TEST_REPO"
D017_SEARCH_DIR="$FORGE_TEST_REPO/.forge/search-index"
D017_BM25="$D017_SEARCH_DIR/bm25_index.json"
D017_BACKUP="$(mktemp /tmp/forge-d017-bm25.XXXXXX)"
test -f "$D017_SEARCH_DIR/documents.json"
test -f "$D017_BM25"
cp "$D017_BM25" "$D017_BACKUP"
printf '%s\n' 'not valid json {{{' >"$D017_BM25"

set +e
forge search query d017-corruption >/tmp/forge-d017-query-human.stdout 2>/tmp/forge-d017-query-human.stderr
D017_QUERY_HUMAN_EXIT=$?
forge search query d017-corruption --json >/tmp/forge-d017-query-json.stdout 2>/tmp/forge-d017-query-json.stderr
D017_QUERY_JSON_EXIT=$?
forge search status >/tmp/forge-d017-status-human.stdout 2>/tmp/forge-d017-status-human.stderr
D017_STATUS_HUMAN_EXIT=$?
forge search status --json >/tmp/forge-d017-status-json.stdout 2>/tmp/forge-d017-status-json.stderr
D017_STATUS_JSON_EXIT=$?
cp "$D017_BACKUP" "$D017_BM25"
D017_RESTORE_EXIT=$?
rm -f "$D017_BACKUP"
set -e

test "$D017_RESTORE_EXIT" -eq 0
test "$D017_QUERY_HUMAN_EXIT" -ne 0
test "$D017_QUERY_JSON_EXIT" -ne 0
test "$D017_STATUS_HUMAN_EXIT" -ne 0
test "$D017_STATUS_JSON_EXIT" -ne 0
test ! -s /tmp/forge-d017-query-human.stdout
test ! -s /tmp/forge-d017-query-json.stdout
test ! -s /tmp/forge-d017-status-human.stdout
test ! -s /tmp/forge-d017-status-json.stdout
jq -s -e 'length == 1 and .[0].error and (.[0].hint | contains("rebuild-index"))' \
  /tmp/forge-d017-query-json.stderr
jq -s -e 'length == 1 and .[0].error and (.[0].hint | contains("rebuild-index"))' \
  /tmp/forge-d017-status-json.stderr
grep -q 'Search index corrupted or outdated' /tmp/forge-d017-query-human.stderr
grep -q 'rebuild-index' /tmp/forge-d017-query-human.stderr
grep -q 'Search index corrupted or outdated' /tmp/forge-d017-status-human.stderr
grep -q 'rebuild-index' /tmp/forge-d017-status-human.stderr
```

- [ ] Query corruption exits non-zero with empty stdout in human and JSON modes
- [ ] Status corruption exits non-zero with empty stdout in human and JSON modes
- [ ] Each JSON failure is one stderr object with rebuild guidance
- [ ] Each human failure uses the shared stderr error/tip path

---
