<!-- prereq: 0.3, 2.1, 5.1 -->

## 10. Session Resume

### 10.1 Create Parent Session Artifacts

<!-- auto -->

```bash
# Create a mock transcript artifact for testing resume
SESSION_JSON=".forge/sessions/test-session-1/forge.session.json"
SESSION_ID=$(jq -r '.confirmed.claude_session_id // "fixture-transcript"' "$SESSION_JSON")
TRANSCRIPT_REL=".forge/artifacts/test-session-1/transcripts/${SESSION_ID}.jsonl"
TRANSCRIPT_ABS="$FORGE_TEST_REPO/${TRANSCRIPT_REL}"

mkdir -p "$(dirname "$TRANSCRIPT_ABS")"
cat > "$TRANSCRIPT_ABS" << 'EOF'
{"requestId":"req-1","timestamp":"2026-03-16T00:00:00Z","message":{"role":"user","content":[{"type":"text","text":"Create a hello world function"}]}}
{"requestId":"req-1","timestamp":"2026-03-16T00:00:01Z","message":{"role":"assistant","content":[{"type":"text","text":"I'll create a simple hello world function for you."},{"type":"tool_use","id":"tool-1","name":"Write","input":{"file_path":"src/hello.py","content":"def hello():\n    return 'Hello, World!'"}}]}}
{"requestId":"req-1","timestamp":"2026-03-16T00:00:02Z","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"tool-1","content":"File written successfully"}]}}
{"requestId":"req-2","timestamp":"2026-03-16T00:00:03Z","message":{"role":"user","content":[{"type":"text","text":"Now add a test"}]}}
{"requestId":"req-2","timestamp":"2026-03-16T00:00:04Z","message":{"role":"assistant","content":[{"type":"text","text":"I'll add a test for the hello function."},{"type":"tool_use","id":"tool-2","name":"Write","input":{"file_path":"tests/test_hello.py","content":"from src.hello import hello\n\ndef test_hello():\n    assert hello() == 'Hello, World!'"}}]}}
{"requestId":"req-2","timestamp":"2026-03-16T00:00:05Z","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"tool-2","content":"File written successfully"}]}}
EOF

# Update session file with a realistic transcript artifact entry
jq \
  --arg transcript_abs "$TRANSCRIPT_ABS" \
  --arg transcript_rel "$TRANSCRIPT_REL" \
  --arg session_id "$SESSION_ID" \
  '
  .confirmed.transcript_path = $transcript_abs
  | .confirmed.artifacts = ((.confirmed.artifacts // {}) + {
      transcripts: [{
        captured_at: "2026-03-16T00:00:00Z",
        reason: "stop",
        source_path: $transcript_abs,
        session_id: $session_id,
        copied_path: $transcript_rel,
        copied: true
      }]
    })
  ' "$SESSION_JSON" > /tmp/session.json && mv /tmp/session.json "$SESSION_JSON"
```

- [ ] Transcript artifact created under `.forge/artifacts/test-session-1/transcripts/`
- [ ] Session file updated with transcript path and `confirmed.artifacts.transcripts[]`

### 10.2 Resume with Minimal Strategy

<!-- prereq: 10.1 -->

<!-- auto -->

```bash
CHILD_DIR=.forge/prev_sessions/test-session-1/children
mkdir -p "$CHILD_DIR"
printf 'frozen child snapshot\n' > "$CHILD_DIR/matrix-sentinel.md"
SENTINEL_SHA=$(sha256sum "$CHILD_DIR/matrix-sentinel.md" | cut -d' ' -f1)

forge session transfer regenerate test-session-1 --strategy minimal --target-runtime claude
forge session transfer show test-session-1 --json \
  | jq -e '.frontmatter.strategy == "minimal" and .frontmatter.target_runtime == "claude"'
test "$SENTINEL_SHA" = "$(sha256sum "$CHILD_DIR/matrix-sentinel.md" | cut -d' ' -f1)"
```

- [ ] Minimal regeneration records `strategy=minimal` and `target_runtime=claude`
- [ ] Existing child snapshots remain byte-identical

### 10.3 Resume with Structured Strategy

<!-- prereq: 10.1 -->

<!-- auto -->

```bash
forge session transfer regenerate test-session-1 --strategy structured --target-runtime codex
forge session transfer show test-session-1 --json \
  | jq -e '.frontmatter.strategy == "structured"
      and .frontmatter.target_runtime == "codex"
      and any(.sections[]; .title == "Runtime Hints")'
rg 'Target runtime: codex|codex exec|sandbox' .forge/prev_sessions/test-session-1/generated.md
```

- [ ] Structured regeneration writes the parent cache without launching a child
- [ ] Codex target frontmatter and runtime hints are present

### 10.4 Resume with Full Strategy

<!-- prereq: 10.1 -->

<!-- auto -->

```bash
forge session transfer regenerate test-session-1 --strategy full --target-runtime claude
forge session transfer show test-session-1 --json \
  | jq -e '.frontmatter.strategy == "full" and .frontmatter.target_runtime == "claude"'
for expected in 'Create a hello world function' 'File written successfully' 'Now add a test'; do
  rg -F "$expected" .forge/prev_sessions/test-session-1/generated.md
done
```

- [ ] Full regeneration records the full strategy and Claude target
- [ ] Complete fixture turns and tool result text are retained

### 10.5 Resume with AI-Curated Strategy

<!-- prereq: 10.1 -->

<!-- requires: openrouter -->

<!-- evidence: extended-exploratory -->

<!-- paid-operations: 1 -->

<!-- auto -->

`ai-curated` is the matrix's one paid transfer operation. It calls the external curation provider but does not launch a
child runtime.

```bash
forge session transfer regenerate test-session-1 --strategy ai-curated --target-runtime claude \
  2>&1 | tee /tmp/qa-ai-curated-transfer.out
forge session transfer show test-session-1 --json \
  | jq -e '.frontmatter.strategy == "ai-curated" and .frontmatter.target_runtime == "claude"'
rg -i 'external|OpenRouter|transcript content' /tmp/qa-ai-curated-transfer.out
test -f .forge/prev_sessions/test-session-1/children/matrix-sentinel.md
rm -f /tmp/qa-ai-curated-transfer.out
```

- [ ] Parent transcript fixture from 10.1 exists
- [ ] Security warning shown about sending transcript content to OpenRouter
- [ ] Transfer frontmatter records `ai-curated` and the Claude target
- [ ] With the required OpenRouter credential, curation produces LLM-selected highlights rather than an auth fallback
- [ ] No `No transcript available; using minimal strategy` warning
- [ ] Existing child snapshots remain byte-identical

### 10.6 `forge session transfer` (Inspect / Reshape Transfer Context)

<!-- prereq: 10.1 -->

<!-- auto -->

`forge session transfer` is the read/reshape surface for resume/fork context, keyed by a parent session. Uses the parent
transcript fixture from 10.1.

```bash
cd $FORGE_TEST_REPO

# Rebuild the parent cache (generated.md) from the parent's transcript -- never touches children/notes
forge session transfer regenerate test-session-1

# Show the parent cache
forge session transfer show test-session-1 >/dev/null; echo "SHOW_EXIT=$?"

# JSON view (frontmatter + sections + content) -- must be valid JSON with a parent field
forge session transfer show test-session-1 --json | jq -e '.parent' >/dev/null && echo "JSON_VALID=true"

# Seed a frozen child snapshot so diff/edit have a child to operate on
CHILD_DIR=".forge/prev_sessions/test-session-1/children"
mkdir -p "$CHILD_DIR"
printf '# Parent Context\n\nOlder snapshot body.\n' > "$CHILD_DIR/xfer-child.md"

# diff: parent cache vs the child's frozen snapshot
forge session transfer diff test-session-1 --child xfer-child >/dev/null; echo "DIFF_EXIT=$?"

# edit: opens the child's notes overlay in $EDITOR. EDITOR=true is a non-interactive smoke
# that exits immediately; it must create the notes file.
EDITOR=true forge session transfer edit test-session-1 --child xfer-child
test -f "$CHILD_DIR/xfer-child.notes.md" && echo "NOTES_CREATED=true" || echo "NOTES_CREATED=false"
```

- [ ] `forge session transfer regenerate` rewrites `generated.md` (names strategy/depth; children unchanged)
- [ ] `forge session transfer show` prints the cache (exit 0); `--json` is valid JSON with a `parent` field
- [ ] `forge session transfer diff --child` reports drift or `No drift` cleanly (exit 0)
- [ ] `EDITOR=true forge session transfer edit --child` creates the child notes overlay (`children/<child>.notes.md`)

### 10.7 Resume `--fresh --review` (Edit Context Before Launch)

<!-- prereq: 10.1 -->

<!-- requires: api_key -->

<!-- human:guided -->

`--review` opens the generated child context in `$EDITOR` before Claude launches (transfer mode only; rejected with
`--resume-mode native`). In the **container shell**, run the resume, edit/save the context in the editor, then exit
Claude (`/exit`).

```
# Opens the assembled child context in $EDITOR; save and close to continue to launch.
forge session resume test-session-1 --fresh --review --child-name test-resumed-review
```

- [ ] `$EDITOR` opens with the generated child transfer context before Claude launches
- [ ] Saving and closing the editor proceeds to launch the child session
- [ ] Editor edits are reflected in the launched child's context

### 10.8 Rewind and Ancestry Depth

<!-- prereq: 10.1 -->

<!-- auto -->

Use a no-op Claude launcher so valid resume/fork forms cross the installed CLI and write their derivation records
without a model call. A separate plain-text transcript keeps rewind from invoking code-delta curation.

```bash
cd "$FORGE_TEST_REPO"
forge session delete qa-rewind-parent qa-rewind-resume qa-rewind-fork qa-depth-parent qa-depth-all \
  --yes --force 2>/dev/null || true
git worktree remove "${FORGE_TEST_REPO}-qa-rewind-fork" --force 2>/dev/null || true
git branch -D qa-rewind-fork 2>/dev/null || true

mkdir -p /tmp/forge-qa-rewind-bin
cat > /tmp/forge-qa-rewind-bin/claude <<'EOF'
#!/usr/bin/env bash
if [[ "${1:-}" == "--version" ]]; then echo "2.1.245 (Forge QA fixture)"; fi
exit 0
EOF
chmod +x /tmp/forge-qa-rewind-bin/claude

forge session start qa-rewind-parent --no-launch
REWIND_UUID=44444444-5555-4666-8777-888899990000
REWIND_TRANSCRIPT=$(python3 -c \
  "from forge.session.claude.paths import get_transcript_path; print(get_transcript_path('$FORGE_TEST_REPO', '$REWIND_UUID'))")
mkdir -p "$(dirname "$REWIND_TRANSCRIPT")"
cat > "$REWIND_TRANSCRIPT" <<'EOF'
{"requestId":"rewind-1","message":{"role":"user","content":[{"type":"text","text":"remember alpha"}]}}
{"requestId":"rewind-1","message":{"role":"assistant","content":[{"type":"text","text":"alpha"}]}}
{"requestId":"rewind-2","message":{"role":"user","content":[{"type":"text","text":"remember beta"}]}}
{"requestId":"rewind-2","message":{"role":"assistant","content":[{"type":"text","text":"beta"}]}}
EOF
jq --arg uuid "$REWIND_UUID" --arg transcript "$REWIND_TRANSCRIPT" '
  .confirmed.claude_session_id = $uuid
  | .confirmed.transcript_path = $transcript
  | .confirmed.confirmed_by = "qa:fixture"
' .forge/sessions/qa-rewind-parent/forge.session.json > /tmp/qa-rewind-parent.json
mv /tmp/qa-rewind-parent.json .forge/sessions/qa-rewind-parent/forge.session.json

PATH="/tmp/forge-qa-rewind-bin:$PATH" forge session resume qa-rewind-parent \
  --fresh --child-name qa-rewind-resume --strategy rewind --drop-last 1
jq -e '
  .confirmed.derivation.resume_mode == "native-relocate"
  and .confirmed.derivation.strategy == "rewind"
  and .confirmed.derivation.dropped_turns >= 1
  and (.confirmed.derivation.rewind_relocated_session_id | type == "string" and length > 0)
' .forge/sessions/qa-rewind-resume/forge.session.json

PATH="/tmp/forge-qa-rewind-bin:$PATH" forge session fork qa-rewind-parent \
  --name qa-rewind-fork --worktree --strategy rewind --drop-last 1
REWIND_FORK_MANIFEST="${FORGE_TEST_REPO}-qa-rewind-fork/.forge/sessions/qa-rewind-fork/forge.session.json"
jq -e '
  .confirmed.derivation.resume_mode == "native-relocate"
  and .confirmed.derivation.strategy == "rewind"
  and .confirmed.derivation.dropped_turns >= 1
' "$REWIND_FORK_MANIFEST"

forge session fork test-session-1 --name qa-depth-parent --resume-mode transfer --no-launch
DEPTH_PARENT_UUID=55555555-6666-4777-8888-999900001111
DEPTH_PARENT_TRANSCRIPT=$(python3 -c \
  "from forge.session.claude.paths import get_transcript_path; print(get_transcript_path('$FORGE_TEST_REPO', '$DEPTH_PARENT_UUID'))")
mkdir -p "$(dirname "$DEPTH_PARENT_TRANSCRIPT")"
cat > "$DEPTH_PARENT_TRANSCRIPT" <<'EOF'
{"requestId":"depth-1","message":{"role":"user","content":[{"type":"text","text":"continue the lineage"}]}}
{"requestId":"depth-1","message":{"role":"assistant","content":[{"type":"text","text":"lineage continued"}]}}
EOF
jq --arg uuid "$DEPTH_PARENT_UUID" --arg transcript "$DEPTH_PARENT_TRANSCRIPT" '
  .confirmed.claude_session_id = $uuid
  | .confirmed.transcript_path = $transcript
  | .confirmed.confirmed_by = "qa:fixture"
' .forge/sessions/qa-depth-parent/forge.session.json > /tmp/qa-depth-parent.json
mv /tmp/qa-depth-parent.json .forge/sessions/qa-depth-parent/forge.session.json
PATH="/tmp/forge-qa-rewind-bin:$PATH" forge session resume qa-depth-parent \
  --fresh --child-name qa-depth-all --depth all
jq -e '
  .confirmed.derivation.depth == 2
  and .confirmed.derivation.lineage == ["qa-depth-parent", "test-session-1"]
' .forge/sessions/qa-depth-all/forge.session.json

set +e
forge session resume qa-rewind-parent --depth 2 >/tmp/qa-depth-invalid.out 2>&1
DEPTH_RC=$?
forge session resume qa-rewind-parent --strategy rewind --drop-last 1 >/tmp/qa-rewind-invalid.out 2>&1
REWIND_RC=$?
set -e
test "$DEPTH_RC" -ne 0
test "$REWIND_RC" -ne 0
rg -- '--depth requires --fresh' /tmp/qa-depth-invalid.out
rg -- '--strategy rewind requires --fresh' /tmp/qa-rewind-invalid.out

forge session delete qa-rewind-fork --yes --force
test ! -e "${FORGE_TEST_REPO}-qa-rewind-fork"
rm -f /tmp/qa-depth-invalid.out /tmp/qa-rewind-invalid.out
```

- [ ] Fresh resume records a rewind-native derivation and a truncated relocated id
- [ ] Worktree fork accepts rewind/drop-last and records the same strategy
- [ ] `--fresh --depth all` follows both ancestors and records depth two
- [ ] Explicit depth without fresh and rewind without fresh both fail with actionable diagnostics
- [ ] Rewind worktree cleanup removes the derived checkout without touching the parent transcript

---
