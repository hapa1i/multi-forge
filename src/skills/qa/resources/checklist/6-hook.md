<!-- prereq: 0.3, 2.1, 5.1 -->

## 6. Hooks Testing

Note: Runtime hooks are installed once at user scope with `forge extension enable --scope user`.

### 6.1 Verify Hook Configuration

<!-- auto -->

```bash
# Check user-scope runtime hooks. Project/local extension installs no longer
# write hook blocks.
cat $CLAUDE_HOME/settings.json | jq '.hooks'
```

- [ ] `PreToolUse` hooks configured (policy-check)
- [ ] `PostToolUse` hooks configured (plan-write)
- [ ] `Stop` hook configured
- [ ] `UserPromptSubmit` hook configured
- [ ] `SessionStart` hook configured

### 6.2 Install Hooks Only (Optional)

<!-- auto -->

```bash
# Start clean, then install both runtime-owned halves of hooks (no commands/skills).
forge extension disable --scope user --yes
HOOK_RUNTIME_BIN=$(mktemp -d)
printf '#!/bin/sh\nexit 0\n' > "$HOOK_RUNTIME_BIN/codex"
chmod +x "$HOOK_RUNTIME_BIN/codex"
PATH="$HOOK_RUNTIME_BIN:$PATH" forge extension enable --scope user --profile minimal \
  --with hooks --without commands --runtime all
jq -e '.installations.user.module_owners
    == [{"module":"hooks","runtime":"claude_code"},{"module":"hooks","runtime":"codex"}]
  and .installations.user.skill_packages == []' "$FORGE_HOME/installed.json"

# Restore the full Claude package set required by the later live-skill checks.
forge extension enable --scope user --symlink --profile full --runtime claude
jq -e '(.installations.user.skill_packages | length == 11)
  and all(.installations.user.skill_packages[]; .runtime == "claude_code")' \
  "$FORGE_HOME/installed.json"
```

- [ ] Hooks-only install writes only tracked hook modules and records no runtime skill packages
- [ ] Full-profile restore records eleven Claude packages for the later live-skill checks

### 6.3 Test Hook Manually

<!-- auto -->

<!-- evidence: automated-suite -->

```bash
cd $FORGE_TEST_REPO

# Test the status-line command with the real stdin contract.
BASE_URL=$(jq -r '.intent.proxy.base_url // empty' .forge/sessions/test-session-1/forge.session.json)
mkdir -p .forge/walkthrough
cat > .forge/walkthrough/status-line-transcript.jsonl <<EOF
{"requestId":"req-001","message":{"role":"user","content":[{"type":"text","text":"Read the config file."}]}}
{"requestId":"req-001","message":{"role":"assistant","content":[{"type":"text","text":"I'll inspect it."},{"type":"tool_use","id":"tool-001","name":"Read","input":{"file_path":"${FORGE_TEST_REPO}/config.yaml"}}]}}
{"requestId":"req-001","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"tool-001","content":"timeout: 10"}]}}
{"requestId":"req-002","message":{"role":"user","content":[{"type":"text","text":"Update the timeout and run tests."}]}}
{"requestId":"req-002","message":{"role":"assistant","content":[{"type":"tool_use","id":"tool-002","name":"Edit","input":{"file_path":"${FORGE_TEST_REPO}/config.yaml"}},{"type":"tool_use","id":"tool-003","name":"Bash","input":{"command":"uv run pytest"}}]}}
EOF
STATUS_INPUT=$(jq -nc \
  --arg cwd "$FORGE_TEST_REPO" \
  --arg transcript "$FORGE_TEST_REPO/.forge/walkthrough/status-line-transcript.jsonl" \
  '{
    workspace: {current_dir: $cwd},
    model: {display_name: "Opus 4.6"},
    transcript_path: $transcript
  }')

echo "$STATUS_INPUT" | FORGE_SESSION=test-session-1 ANTHROPIC_BASE_URL="$BASE_URL" forge status-line

# Test user-prompt-submit with a %help command
echo '{"prompt": "%help"}' | FORGE_SESSION=test-session-1 forge hook user-prompt-submit
```

- [ ] Status line outputs session/model info (and proxy info if available)
- [ ] `%help` returns help text (or decision payload)

### 6.4 Smoke Test SessionStart Hook

<!-- auto -->

<!-- evidence: automated-suite -->

```bash
cd $FORGE_TEST_REPO

# Use the candidate UUID already stored in the session manifest
SESSION_ID=$(cat .forge/sessions/test-session-1/forge.session.json | jq -r '.confirmed.claude_session_id')

echo "{\"session_id\":\"$SESSION_ID\",\"transcript_path\":\".forge/walkthrough/mock-transcript.jsonl\",\"source\":\"startup\"}" | FORGE_SESSION=test-session-1 forge hook session-start

# Verify manifest updated
cat .forge/sessions/test-session-1/forge.session.json | jq '.confirmed.transcript_path'
```

- [ ] Hook returns JSON success
- [ ] Manifest has `confirmed.transcript_path` set to the provided value

### 6.5 Smoke Test plan-write Hook (Plan Path Recorded)

<!-- auto -->

<!-- evidence: automated-suite -->

```bash
cd $FORGE_TEST_REPO

SESSION_ID=$(cat .forge/sessions/test-session-1/forge.session.json | jq -r '.confirmed.claude_session_id')

mkdir -p .claude/plans
echo "# Test Plan" > .claude/plans/test-plan.md

echo "{\"hook_event_name\":\"PostToolUse\",\"tool_input\":{\"file_path\":\".claude/plans/test-plan.md\"},\"session_id\":\"$SESSION_ID\"}" | FORGE_SESSION=test-session-1 forge hook plan-write

# Verify manifest recorded latest plan path
cat .forge/sessions/test-session-1/forge.session.json | jq '.confirmed.latest_plan_path'
```

- [ ] Hook returns `action: recorded`
- [ ] Manifest has `confirmed.latest_plan_path` pointing to `.claude/plans/test-plan.md`

### 6.6 Smoke Test exit-plan-mode Hook (Approved Snapshot)

<!-- auto -->

<!-- evidence: automated-suite -->

```bash
cd $FORGE_TEST_REPO

SESSION_ID=$(cat .forge/sessions/test-session-1/forge.session.json | jq -r '.confirmed.claude_session_id')

echo "{\"hook_event_name\":\"PreToolUse\",\"session_id\":\"$SESSION_ID\"}" | FORGE_SESSION=test-session-1 forge hook exit-plan-mode

# Verify snapshot exists
ls -la .forge/artifacts/test-session-1/plans/ | head -50
```

- [ ] Hook returns `action: snapshotted`
- [ ] Snapshot file created under `.forge/artifacts/test-session-1/plans/`

### 6.7 Smoke Test Stop Hook (Transcript Copy + Queue Markers)

<!-- auto -->

<!-- evidence: automated-suite -->

```bash
cd $FORGE_TEST_REPO

SESSION_ID=$(cat .forge/sessions/test-session-1/forge.session.json | jq -r '.confirmed.claude_session_id')

cat > .forge/walkthrough/mock-stop-transcript.jsonl << 'EOF'
{"type":"assistant","message":{"content":"(mock transcript)"}}
EOF

echo "{\"hook_event_name\":\"Stop\",\"session_id\":\"$SESSION_ID\",\"transcript_path\":\".forge/walkthrough/mock-stop-transcript.jsonl\"}" | FORGE_SESSION=test-session-1 forge hook stop

# Verify transcript snapshot copied into artifacts
ls -la .forge/artifacts/test-session-1/transcripts/ | head -50
test -f ".forge/artifacts/test-session-1/transcripts/${SESSION_ID}.jsonl"
```

- [ ] Hook returns JSON success
- [ ] Transcript copied to `.forge/artifacts/test-session-1/transcripts/<session_id>.jsonl`

### 6.8 Smoke Test pre-compact Hook (Transcript Capture)

<!-- auto -->

<!-- evidence: automated-suite -->

```bash
# pre-compact captures transcript before compaction (always exit 0)
jq -nc --arg cwd "$FORGE_TEST_REPO" \
  '{session_id: "test-uuid", transcript_path: "/tmp/test.jsonl", cwd: $cwd}' \
  | FORGE_SESSION=test-session-1 forge hook pre-compact
echo "exit=$?"
```

- [ ] Exit code is 0

### 6.9 Smoke Test policy-check Hook (Fail-Open)

<!-- auto -->

<!-- evidence: automated-suite -->

```bash
# Default session has policy disabled, so this should allow (exit 0)
echo '{"hook_event_name":"PreToolUse","tool_name":"Write","tool_input":{"file_path":"src/example.py","content":"x"}}' | FORGE_SESSION=test-session-1 forge hook policy-check
echo "exit=$?"
```

- [ ] Exit code is 0 (allowed)

### 6.10 End-to-End Stop Hook (Paid Conversation Reuse)

<!-- prereq: 4.2, 5.6 -->

<!-- requires: api_key -->

<!-- auto -->

Reuse the parent conversation from 5.6, which already paid for one real turn and exited through the installed-wheel
launcher. Anthropic's `Stop` event is a turn boundary, so an empty launch-and-exit is not a valid transcript-capture
fixture. This step adds no model completion.

```bash
set -euo pipefail

MANIFEST=".forge/sessions/test-session-parent/forge.session.json"
SESSION_ID=$(jq -r '.confirmed.claude_session_id // empty' "$MANIFEST")
SESSION_ID_PREFIX=${SESSION_ID:0:12}
TRANSCRIPT_PATH=$(jq -r '.confirmed.transcript_path // empty' "$MANIFEST")

jq '.confirmed | {claude_session_id, transcript_path, confirmed_by, confirmed_at}' "$MANIFEST"
jq -e '.confirmed.claude_session_id | strings | length > 0' "$MANIFEST"
jq -e '.confirmed.transcript_path | strings | length > 0' "$MANIFEST"
jq -e '.confirmed.confirmed_by == "hook:stop"' "$MANIFEST"
test -s "$TRANSCRIPT_PATH"
test -s ".forge/artifacts/test-session-parent/transcripts/${SESSION_ID}.jsonl"
STOP_LOG=$(rg -F -l "stop: session_id=$SESSION_ID_PREFIX" ~/.forge/logs/hooks/stop.*.log 2>/dev/null | tail -1 || true)
test -n "$STOP_LOG" || { echo "ERROR: no matching Stop-hook log" >&2; exit 1; }
printf '%s\n' "$STOP_LOG"
```

- [ ] The paid parent from 5.6 has a real confirmed Claude session id
- [ ] Its confirmed transcript path exists and is non-empty
- [ ] `confirmed_by` is `hook:stop`
- [ ] The transcript snapshot exists under `.forge/artifacts/test-session-parent/transcripts/`
- [ ] A matching Stop-hook debug log exists

### 6.11 WorktreeCreate Hook (Claude-Native Worktree)

<!-- prereq: 4.2 -->

<!-- requires: api_key -->

<!-- human:guided -->

<!-- evidence: automated-suite -->

Verify that Claude Code's native worktree creation (via `--worktree` or the Agent tool with `isolation: "worktree"`)
triggers Forge's WorktreeCreate hook, which creates the worktree and auto-installs extensions.

In the **container shell**, clean up and start a worktree session:

```
forge session delete wt-hook-test --yes --force 2>/dev/null || true
WORKTREE_PATH="${FORGE_TEST_REPO}-wt-hook-test"
git worktree remove "$WORKTREE_PATH" --force 2>/dev/null || true
git branch -D wt-hook-test 2>/dev/null || true
forge session start wt-hook-test --worktree --proxy "$FORGE_QA_OPENAI_PROXY"
```

Inside the launched Claude session, verify the status line is visible and type `%help` (should list Forge direct
commands), then exit Claude (`/exit`).

After Claude exits, verify:

```bash
WORKTREE_PATH="${FORGE_TEST_REPO}-wt-hook-test"

# Worktree was created
ls -d "$WORKTREE_PATH" 2>/dev/null || echo "worktree not found"
git worktree list | grep wt-hook-test

# Forge extensions installed in the worktree
cat "$WORKTREE_PATH/.claude/settings.local.json" 2>/dev/null | jq '.hooks | keys'

# Cleanup
forge session delete wt-hook-test --yes --force
git worktree list | grep wt-hook-test && echo "FAIL: worktree not removed" || echo "OK: worktree cleaned up"
```

- [ ] Worktree created by Forge's WorktreeCreate hook (not Claude Code's default)
- [ ] Forge extensions installed in the worktree (hooks in settings.local.json)
- [ ] Status line visible in the worktree session
- [ ] Worktree cleaned up after session delete

### 6.12 Codex Hook Registration and Static Readiness

<!-- requires: codex -->

<!-- auto -->

Inspect registration and static readiness without consuming the one-turn enrollment probe. Positive enrolled hook firing
is release evidence from the automated real-runtime owners, not an either/or manual assertion.

```bash
forge extension enable --scope user --profile minimal \
  --with hooks --without commands --runtime codex --force
forge codex status --scope user --json | tee /tmp/qa-codex-status.json
forge runtime preflight codex --json | tee /tmp/qa-codex-preflight.json

jq -e '
  .runtime.id == "codex"
  and .runtime.installed == true
  and (.scopes | length) == 1
  and .scopes[0].scope == "user"
  and .scopes[0].registered == "yes"
  and any(.scopes[0].registered_pairs[]; contains("codex-session-start"))
  and any(.scopes[0].registered_pairs[]; contains("codex-policy-check"))
' /tmp/qa-codex-status.json
jq -e '
  .ready == true
  and (.version | type == "string" and length > 0)
' /tmp/qa-codex-preflight.json
rm -f /tmp/qa-codex-status.json /tmp/qa-codex-preflight.json
```

- [ ] Installed-wheel enable registers both Forge Codex hooks at user scope without duplicating project skills
- [ ] Static preflight is ready and records the observed Codex version
- [ ] No empirical enrollment turn is counted or mistaken for positive hook-firing evidence

---
