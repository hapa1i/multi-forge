<!-- prereq: 0.3, 5.1, 10.1 -->

## 16. Handoff Agent

### 16.1 Configure Memory and Passports

<!-- requires: api_key -->

<!-- auto -->

```bash
cd $FORGE_TEST_REPO

# Seed target docs with content.
mkdir -p .forge/memory
cat > .forge/memory/debugging.md <<'EOF'
# Debugging Notes
EOF

# Author a project passport (sessionless).
forge memory track .forge/memory/debugging.md --as debugging
head -5 .forge/memory/debugging.md | grep -q 'forge_memory'

# Enable memory for the session.
forge memory enable --session test-session-1
forge session set memory.auto_update.min_turns 1 --session test-session-1

# List passported docs (sessionless scan).
forge memory list --json | jq -e '
  length >= 1
  and any(.[]; .path == ".forge/memory/debugging.md" and .strategy == "debugging")
'

# Verify session config.
cat .forge/sessions/test-session-1/forge.session.json | jq '.overrides.memory'
```

- [ ] `forge memory track` writes a passport into the doc (sessionless)
- [ ] `forge memory enable --session` sets activation override
- [ ] `forge memory list` discovers passported docs via scan
- [ ] Handoff config written to session overrides (`enabled`, `min_turns`)

### 16.2 Run Handoff Manually (Direct Update)

<!-- prereq: 16.1 -->

<!-- requires: api_key -->

<!-- auto -->

```bash
cd $FORGE_TEST_REPO

# Create a deterministic transcript artifact with clear debugging takeaways.
mkdir -p .forge/artifacts/test-session-1/transcripts
cat > .forge/artifacts/test-session-1/transcripts/manual-handoff-direct.jsonl <<'EOF'
{"requestId":"handoff-1","message":{"role":"user","content":[{"type":"text","text":"Pytest failed with ModuleNotFoundError for tomlkit."}]}}
{"requestId":"handoff-1","message":{"role":"assistant","content":[{"type":"text","text":"The root cause was a missing dependency in the dev environment. Running uv sync fixed it."}]}}
{"requestId":"handoff-2","message":{"role":"user","content":[{"type":"text","text":"Please capture that debugging note for next time."}]}}
{"requestId":"handoff-2","message":{"role":"assistant","content":[{"type":"text","text":"Noted: if tests fail with ModuleNotFoundError for tomlkit, run uv sync before retrying."}]}}
EOF

BEFORE_LINES=$(wc -l < .forge/memory/debugging.md)

forge handoff run \
  --session-name test-session-1 \
  --worktree-path $FORGE_TEST_REPO \
  --transcript-rel .forge/artifacts/test-session-1/transcripts/manual-handoff-direct.jsonl

AFTER_LINES=$(wc -l < .forge/memory/debugging.md)

echo "before=$BEFORE_LINES after=$AFTER_LINES"
cat .forge/memory/debugging.md

ls .forge/artifacts/test-session-1/handoff/review-*.md
forge session handoff show test-session-1 --latest

test "$AFTER_LINES" -gt "$BEFORE_LINES"
```

- [ ] `forge handoff run` succeeds with the transcript artifact path provided
- [ ] Passported docs are discovered via scan and updated with session takeaways
- [ ] Handoff agent stdout is persisted and visible via `forge session handoff show --latest`

### 16.3 Shadow Handoff (`suggested` + `shadows`)

<!-- prereq: 16.1 -->

<!-- requires: api_key -->

<!-- auto -->

```bash
cd $FORGE_TEST_REPO

# Create a shadow doc pair via passport.
mkdir -p .forge/memory docs
cat > docs/team-standards.md <<'EOF'
# Team Standards

- Prefer small, reviewable patches.
EOF

cat > .forge/memory/suggested_standards.md <<'EOF'
# Suggested Standards
EOF

# Author a shadow-only passport (sessionless).
forge memory track docs/team-standards.md \
  --propose \
  --shadow-path .forge/memory/suggested_standards.md

forge memory list --json | jq -e '
  any(.[]; .path == ".forge/memory/suggested_standards.md" and .strategy == "suggested")
'

mkdir -p .forge/artifacts/test-session-1/transcripts
cat > .forge/artifacts/test-session-1/transcripts/manual-handoff-shadow.jsonl <<'EOF'
{"requestId":"shadow-1","message":{"role":"user","content":[{"type":"text","text":"We kept fixing bugs caused by giant mixed-purpose commits."}]}}
{"requestId":"shadow-1","message":{"role":"assistant","content":[{"type":"text","text":"A new standard could require small focused commits with clear intent."}]}}
{"requestId":"shadow-2","message":{"role":"user","content":[{"type":"text","text":"Please propose that as guidance rather than editing the official standards directly."}]}}
{"requestId":"shadow-2","message":{"role":"assistant","content":[{"type":"text","text":"I will suggest it in the shadow file for human review."}]}}
EOF

cp docs/team-standards.md /tmp/team-standards.before
SHADOW_BEFORE=$(wc -l < .forge/memory/suggested_standards.md)

forge handoff run \
  --session-name test-session-1 \
  --worktree-path $FORGE_TEST_REPO \
  --transcript-rel .forge/artifacts/test-session-1/transcripts/manual-handoff-shadow.jsonl

SHADOW_AFTER=$(wc -l < .forge/memory/suggested_standards.md)

cat .forge/memory/suggested_standards.md

cmp -s docs/team-standards.md /tmp/team-standards.before
test "$SHADOW_AFTER" -gt "$SHADOW_BEFORE"
```

- [ ] Shadow-only passport discovered via scan
- [ ] Handoff runs successfully against the shadow doc pair
- [ ] Shadow file gains proposed additions for later human review
- [ ] Official document is not edited in-place

### 16.4 Queued Handoff on Next CLI Startup

<!-- prereq: 16.1 -->

<!-- requires: api_key -->

<!-- auto -->

```bash
cd $FORGE_TEST_REPO

# Ensure direct-update config for the queued-path test.
forge session set memory.auto_update.mode augment --session test-session-1

cat > .forge/memory/debugging.md <<'EOF'
# Debugging Notes
EOF

mkdir -p .forge/walkthrough
cat > .forge/walkthrough/handoff-queued-source.jsonl <<'EOF'
{"requestId":"queued-1","message":{"role":"user","content":[{"type":"text","text":"Ruff failed because generated fixtures were not formatted."}]}}
{"requestId":"queued-1","message":{"role":"assistant","content":[{"type":"text","text":"Running make format fixed the generated fixtures and the follow-up lint pass succeeded."}]}}
{"requestId":"queued-2","message":{"role":"user","content":[{"type":"text","text":"Please preserve that debugging note for the next session."}]}}
{"requestId":"queued-2","message":{"role":"assistant","content":[{"type":"text","text":"I will capture that this failure mode is resolved by re-running make format before lint."}]}}
EOF

SESSION_ID=$(cat .forge/sessions/test-session-1/forge.session.json | jq -r '.confirmed.claude_session_id')
BEFORE_LINES=$(wc -l < .forge/memory/debugging.md)
MARKER="${FORGE_HOME:-$HOME/.forge}/pending-work/handoff-${SESSION_ID}.json"

STOP_INPUT=$(jq -nc \
  --arg sid "$SESSION_ID" \
  --arg transcript ".forge/walkthrough/handoff-queued-source.jsonl" \
  '{hook_event_name:"Stop",session_id:$sid,transcript_path:$transcript}')

STOP_OUTPUT=$(echo "$STOP_INPUT" | FORGE_SESSION=test-session-1 forge hook stop)
echo "$STOP_OUTPUT" | jq '.'
echo "$STOP_OUTPUT" | jq -e '.queued_handoff == true'

test -f "$MARKER"

# Any later Forge CLI startup should process the queued marker and spawn handoff in the background.
forge session list >/tmp/handoff-queue-trigger.log

for _ in $(seq 1 30); do
  AFTER_LINES=$(wc -l < .forge/memory/debugging.md)
  if [ ! -f "$MARKER" ] && [ "$AFTER_LINES" -gt "$BEFORE_LINES" ]; then
    break
  fi
  sleep 1
done

AFTER_LINES=$(wc -l < .forge/memory/debugging.md)
echo "before=$BEFORE_LINES after=$AFTER_LINES marker=$MARKER"
cat .forge/memory/debugging.md

test ! -f "$MARKER"
test "$AFTER_LINES" -gt "$BEFORE_LINES"
```

- [ ] Stop hook reports `queued_handoff: true`
- [ ] Handoff marker is created under `~/.forge/pending-work/`
- [ ] A later Forge CLI startup processes the queued handoff automatically
- [ ] Background handoff updates passported docs without a direct `forge handoff run`
- [ ] Pending handoff marker is gone after processing completes

---
