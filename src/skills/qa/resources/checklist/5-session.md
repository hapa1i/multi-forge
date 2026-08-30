<!-- prereq: 0.3 -->

## 5. Session Management

### 5.1 Start a Session

<!-- auto -->

```bash
cd $FORGE_TEST_REPO

# Clean up from previous runs
forge session delete test-session-1 --yes --force 2>/dev/null || true

# Start a new session
forge session start test-session-1 --no-launch

# Verify session created
ls -la .forge/sessions/
cat .forge/sessions/test-session-1/forge.session.json | jq '.'
```

- [ ] Session directory created at `.forge/sessions/test-session-1/`
- [ ] `forge.session.json` contains `intent` section
- [ ] `--no-launch` prevents Claude from opening (useful for testing)

### 5.2 List Sessions

<!-- auto -->

```bash
# List all sessions
forge session list
```

- [ ] Shows `test-session-1` with status
- [ ] Shows session directory and last-used timestamp

### 5.3 Show Session Details

<!-- auto -->

```bash
# Show session details
forge session show test-session-1
```

- [ ] Shows intent, overrides, confirmed sections
- [ ] Shows proxy info if running with proxy

### 5.4 Set Session Overrides

<!-- auto -->

```bash
# Set a mid-session override
forge session set memory.auto_update.enabled true --session test-session-1

# Verify override applied
cat .forge/sessions/test-session-1/forge.session.json | jq '.overrides'
```

- [ ] Override written to `overrides` section
- [ ] Original intent unchanged

### 5.5 Reset Overrides

<!-- auto -->

```bash
# Reset overrides to intent
forge session reset --session test-session-1

# Verify reset
cat .forge/sessions/test-session-1/forge.session.json | jq '.overrides'
```

- [ ] Overrides section cleared or empty

### 5.6 Fork a Session (default, same directory)

<!-- prereq: 2.4, 4.2 -->

<!-- requires: api_key -->

<!-- human:guided -->

<!-- paid-operations: 2 -->

In the **container shell**, start the parent session routed through the proxy provisioned in 4.2 (Claude will launch --
interact briefly, then exit with `/exit`). Then fork it **without `--worktree`** (the default). The fork stays in the
same directory, so Claude's `--resume --fork-session` finds the parent conversation and carries it over. Ask "where were
we?" to confirm the conversation context carried over, then exit (`/exit`).

```
# Clean up from previous runs
forge session delete test-session-parent --yes --force 2>/dev/null || true
forge session delete test-session-forked --yes --force 2>/dev/null || true

# Start the parent session through the proxy provisioned in 4.2.
# Interact briefly ("hello"), then exit (/exit).
forge session start test-session-parent --proxy "$FORGE_QA_OPENAI_PROXY"

# Fork the parent session (default: same directory, no worktree).
# Claude should resume the conversation via --fork-session.
# Disable auto-memory so "where were we?" tests Forge transfer, not CC memory.
# Ask "where were we?" to confirm, then exit (/exit).
CLAUDE_CODE_DISABLE_AUTO_MEMORY=1 forge session fork test-session-parent --name test-session-forked

# Verify fork lives in the same directory as parent
forge session show test-session-forked
cat "$FORGE_TEST_REPO/.forge/sessions/test-session-forked/forge.session.json" | \
  jq '{is_fork, parent_session, worktree: (.worktree | {path, is_worktree}), confirmed: (.confirmed | {claude_session_id})}'
```

- [ ] Forked session created in same directory (`$FORGE_TEST_REPO`)
- [ ] `forge session show` reports type as Fork
- [ ] Claude conversation carries over (asking "where were we?" reflects parent context)
- [ ] No `Worktree:` line in fork output (no git worktree created)
- [ ] Manifest at `$FORGE_TEST_REPO/.forge/sessions/test-session-forked/` (not a separate worktree dir)
- [ ] Manifest has `is_fork: true`, `parent_session` pointing to parent, `is_worktree: false`
- [ ] `confirmed.claude_session_id` is populated after fork

### 5.7 Fork a Session with Worktree (`--worktree`)

<!-- prereq: 2.4, 4.2 -->

<!-- requires: api_key -->

<!-- human:guided -->

Fork the parent session again, this time with `--worktree` for code isolation. The fork gets its own git worktree and
branch. Because conversations are project-scoped, the fork starts a fresh Claude session in the new worktree and
automatically injects a parent transfer context file. Confirm that the fresh Claude UI opens after Forge names the
transfer context, then exit immediately without sending a prompt. Content accuracy is asserted from the generated file
and by the automated transfer owners; this human checkpoint covers real-runtime delivery without another model call.

Note: `fork --worktree` gives the forked session its own Forge root in the new worktree. The fork manifest and parent
transfer context should both live under the forked worktree's `.forge/` directory.

```
# Clean up from previous runs
forge session delete test-session-forked-wt --yes --force 2>/dev/null || true
WORKTREE_PATH="${FORGE_TEST_REPO}-test-session-forked-wt"
git worktree remove "$WORKTREE_PATH" --force 2>/dev/null || true
git branch -D test-session-forked-wt 2>/dev/null || true

# Fork with --worktree (creates isolated worktree + branch).
# Starts fresh Claude with parent transfer context (no --resume attempt).
# Confirm the Context line and fresh Claude UI, then exit without sending a prompt.
CLAUDE_CODE_DISABLE_AUTO_MEMORY=1 forge session fork test-session-parent --name test-session-forked-wt --worktree --extensions

# Verify fork
forge session show test-session-forked-wt
WORKTREE_PATH=$(forge session show test-session-forked-wt --json | jq -r '.worktree.path')
# Manifest lives inside the forked worktree's Forge root
cat "$WORKTREE_PATH/.forge/sessions/test-session-forked-wt/forge.session.json" | \
  jq '{is_fork, parent_session, worktree: (.worktree | {path, is_worktree}), confirmed: (.confirmed | {claude_session_id})}'
cat "$WORKTREE_PATH/.forge/prev_sessions/test-session-parent/children/test-session-forked-wt.md"
```

- [ ] Worktree fork created at `${FORGE_TEST_REPO}-test-session-forked-wt`
- [ ] `forge session show` reports type as Fork with worktree info
- [ ] Fork output shows `Extensions:` line confirming auto-install in worktree
- [ ] Fork output shows `Context:` line with parent transfer file
- [ ] A fresh Claude UI opens in the worktree and exits without a model prompt
- [ ] Manifest at `${FORGE_TEST_REPO}-test-session-forked-wt/.forge/sessions/test-session-forked-wt/`
- [ ] Manifest has `is_fork: true`, `parent_session`, `is_worktree: true`
- [ ] `confirmed.claude_session_id` is populated
- [ ] Parent transfer file exists at
  `${FORGE_TEST_REPO}-test-session-forked-wt/.forge/prev_sessions/test-session-parent/children/test-session-forked-wt.md`

### 5.8 Incognito Session

<!-- prereq: 4.2 -->

<!-- requires: proxy -->

<!-- auto -->

Incognito sessions auto-delete on exit, so `--incognito` requires a launch. A no-op Claude fixture exercises launcher
cleanup without spending a model turn.

```bash
# Clean up from previous runs
forge session delete test-incognito --yes --force 2>/dev/null || true

mkdir -p /tmp/forge-qa-noop-bin
cat > /tmp/forge-qa-noop-bin/claude <<'EOF'
#!/usr/bin/env bash
if [[ "${1:-}" == "--version" ]]; then echo "2.1.245 (Forge QA fixture)"; fi
exit 0
EOF
chmod +x /tmp/forge-qa-noop-bin/claude
PATH="/tmp/forge-qa-noop-bin:$PATH" forge session incognito test-incognito --proxy "$FORGE_QA_OPENAI_PROXY"

# After exiting Claude, verify auto-cleanup removed the session
forge session list
# Expected: test-incognito should NOT appear (auto-deleted on exit)
```

- [ ] Incognito launcher exits successfully without a model completion
- [ ] Session auto-deleted after exit (not in `forge session list`)
- [ ] No `.forge/sessions/test-incognito/` directory remains

### 5.9 Delete a Session

<!-- auto -->

```bash
set -euo pipefail

# Clean up from previous runs
forge session delete test-session-delete-me --yes --force 2>/dev/null || true

# Create a disposable session to delete
forge session start test-session-delete-me --no-launch

# Delete a test session (non-interactive)
forge session delete test-session-delete-me --yes --force

# Verify deletion
forge session list
```

- [ ] Session removed from listing
- [ ] Session directory removed

Ref-count delete guard: verify that deleting a co-resident session preserves the shared worktree.

```bash
set -euo pipefail

# Create a worktree session (owns the worktree)
forge session delete test-refcount-owner --yes --force 2>/dev/null || true
forge session delete test-refcount-guest --yes --force 2>/dev/null || true
git worktree remove "${FORGE_TEST_REPO}-test-refcount-owner" --force 2>/dev/null || true
git branch -D test-refcount-owner 2>/dev/null || true

forge session start test-refcount-owner --worktree --no-launch
WORKTREE_PATH=$(forge session show test-refcount-owner --json | jq -r '.worktree.path')

# Owner manifest lives centrally (root-level project, --worktree keeps parent forge_root)
OWNER_JSON="$FORGE_TEST_REPO/.forge/sessions/test-refcount-owner/forge.session.json"
jq '.confirmed.claude_session_id = "fixture-refcount"' "$OWNER_JSON" > /tmp/rc.json && mv /tmp/rc.json "$OWNER_JSON"

# --into requires Forge enabled in the target worktree
cd "$WORKTREE_PATH" && forge extension enable --scope local && cd "$FORGE_TEST_REPO"

# Fork into the same worktree (guest, does not own)
forge session fork test-refcount-owner --name test-refcount-guest --into "$WORKTREE_PATH" --no-launch

# Delete the guest — both the preview and mutation must preserve the shared worktree.
forge session delete test-refcount-guest --yes --force 2>&1 | tee /tmp/qa-refcount-delete.out
rg 'Worktree will be kept' /tmp/qa-refcount-delete.out
! rg 'Worktree will be removed' /tmp/qa-refcount-delete.out

# Verify worktree still exists
test -d "$WORKTREE_PATH" && echo "WORKTREE_PRESERVED=true" || echo "WORKTREE_PRESERVED=false"
forge session list | grep test-refcount-owner
```

- [ ] Guest session deleted successfully
- [ ] Delete preview says the shared worktree will be kept and does not claim it will be removed
- [ ] Worktree directory preserved (owner session still holds a reference)
- [ ] Owner session still listed and functional

### 5.10 Worktree Session (Isolation)

<!-- auto -->

```bash
# Clean up from previous runs
forge session delete test-session-worktree --yes --force 2>/dev/null || true

# Create a session with a git worktree (no Claude launch)
forge session start test-session-worktree --worktree --no-launch

# Root-level Forge projects keep manifests centrally in the project root's
# .forge/sessions/, not inside the worktree. The worktree is only the working
# directory for code isolation.
WORKTREE_PATH=$(forge session show test-session-worktree --json | jq -r '.worktree.path')
MANIFEST="$FORGE_TEST_REPO/.forge/sessions/test-session-worktree/forge.session.json"

# Verify worktree recorded in manifest
cat "$MANIFEST" | jq '.worktree'

# Verify the worktree path exists on disk
test -d "$WORKTREE_PATH" && echo "WORKTREE_EXISTS=true" || echo "WORKTREE_EXISTS=false"

# Verify it is marked as a worktree session
cat "$MANIFEST" | jq '.worktree.is_worktree'
```

- [ ] Worktree session created
- [ ] Manifest at `$FORGE_TEST_REPO/.forge/sessions/test-session-worktree/` (central)
- [ ] Manifest contains worktree path + branch
- [ ] Worktree path exists on disk
- [ ] `worktree.is_worktree` is `true`

### 5.11 System Prompt Generation

<!-- prereq: 5.8 -->

<!-- requires: api_key -->

<!-- auto -->

System prompts are injected at launch time (`--system-prompt` is mutually exclusive with `--no-launch`). The no-op
Claude fixture from 5.8 exercises generation without a model completion.

```bash
# Clean up from previous runs
forge session delete test-session-system-prompt --yes --force 2>/dev/null || true

PATH="/tmp/forge-qa-noop-bin:$PATH" forge session start test-session-system-prompt \
  --proxy "$FORGE_QA_OPENAI_PROXY" --system-prompt "FORGE_MANUAL_TEST_SYSTEM_PROMPT"

# After exiting Claude, verify the generated file
test -f .claude/forge.system-prompt.generated.md && echo "FILE_EXISTS=true" || echo "FILE_EXISTS=false"
grep -c "FORGE_MANUAL_TEST_SYSTEM_PROMPT" .claude/forge.system-prompt.generated.md
```

- [ ] Generated system prompt file created at `.claude/forge.system-prompt.generated.md`
- [ ] Generated file contains the provided prompt text

### 5.12 Session Show

<!-- auto -->

```bash
# Show session by name
forge session show test-session-1

# Show session via FORGE_SESSION env var
FORGE_SESSION=test-session-1 forge session show

# No name and no env var -> guidance message
forge session show
```

- [ ] `forge session show <name>` displays session details
- [ ] `forge session show` without name or env var shows guidance message

### 5.13 Fork with `--strategy` (Context Assembly)

<!-- prereq: 5.1 -->

<!-- auto -->

Verify that `--strategy` controls transfer content density on worktree forks.

```bash
# Setup: create parent with a mock transcript for transfer generation
forge session delete test-strat-parent --yes --force 2>/dev/null || true
forge session delete test-fork-strat-min --yes --force 2>/dev/null || true
forge session delete test-fork-strat-struct --yes --force 2>/dev/null || true
git worktree remove "${FORGE_TEST_REPO}-test-fork-strat-min" --force 2>/dev/null || true
git worktree remove "${FORGE_TEST_REPO}-test-fork-strat-struct" --force 2>/dev/null || true
git branch -D test-fork-strat-min 2>/dev/null || true
git branch -D test-fork-strat-struct 2>/dev/null || true

forge session start test-strat-parent --no-launch

# Inject a fixture transcript so transfer has content to assemble
PARENT_JSON=".forge/sessions/test-strat-parent/forge.session.json"
TDIR=".forge/artifacts/test-strat-parent/transcripts"
mkdir -p "$TDIR"
cat > "$TDIR/fixture.jsonl" << 'JSONL'
{"requestId":"r1","timestamp":"2026-01-01T00:00:00Z","message":{"role":"user","content":[{"type":"text","text":"Create a hello function"}]}}
{"requestId":"r1","timestamp":"2026-01-01T00:00:01Z","message":{"role":"assistant","content":[{"type":"text","text":"I will create a hello function."},{"type":"tool_use","id":"t1","name":"Write","input":{"file_path":"hello.py","content":"def hello(): return 'hi'"}}]}}
{"requestId":"r1","timestamp":"2026-01-01T00:00:02Z","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"t1","content":"OK"}]}}
JSONL
jq --arg tp "$PWD/$TDIR/fixture.jsonl" \
  '.confirmed.transcript_path = $tp | .confirmed.claude_session_id = "fixture-strat"' \
  "$PARENT_JSON" > /tmp/s.json && mv /tmp/s.json "$PARENT_JSON"

# Fork with --strategy minimal
forge session fork test-strat-parent --name test-fork-strat-min --worktree --strategy minimal --no-launch
TRANSFER_MIN="${FORGE_TEST_REPO}-test-fork-strat-min/.forge/prev_sessions/test-strat-parent/children/test-fork-strat-min.md"
test -f "$TRANSFER_MIN" && echo "MIN_TRANSFER=true" || echo "MIN_TRANSFER=false"
wc -l < "$TRANSFER_MIN"

# Fork with --strategy structured
forge session fork test-strat-parent --name test-fork-strat-struct --worktree --strategy structured --no-launch
TRANSFER_STRUCT="${FORGE_TEST_REPO}-test-fork-strat-struct/.forge/prev_sessions/test-strat-parent/children/test-fork-strat-struct.md"
test -f "$TRANSFER_STRUCT" && echo "STRUCT_TRANSFER=true" || echo "STRUCT_TRANSFER=false"
wc -l < "$TRANSFER_STRUCT"
```

- [ ] Minimal transfer file created at expected path
- [ ] Structured transfer file created at expected path
- [ ] Structured transfer contains more content than minimal (higher line count)

### 5.14 Fork with `--inline-plan`

<!-- prereq: 5.1 -->

<!-- auto -->

Verify that `--inline-plan` inlines approved plan content in the transfer context file.

```bash
# Setup: create parent with a mock plan via confirmed.latest_plan_path
forge session delete test-plan-parent --yes --force 2>/dev/null || true
forge session delete test-fork-plan --yes --force 2>/dev/null || true
git worktree remove "${FORGE_TEST_REPO}-test-fork-plan" --force 2>/dev/null || true
git branch -D test-fork-plan 2>/dev/null || true

forge session start test-plan-parent --no-launch

# Create a mock plan file and wire it into the manifest
mkdir -p .claude/plans
cat > .claude/plans/test-plan.md << 'PLAN'
# Approved Plan

1. Create `src/demo.py` with a greet function
2. Add unit test in `tests/test_demo.py`
3. Run tests to verify
PLAN

PARENT_JSON=".forge/sessions/test-plan-parent/forge.session.json"
jq '.confirmed.latest_plan_path = ".claude/plans/test-plan.md" | .confirmed.claude_session_id = "fixture-plan"' \
  "$PARENT_JSON" > /tmp/p.json && mv /tmp/p.json "$PARENT_JSON"

# Fork with --inline-plan (plan content should appear in transfer)
forge session fork test-plan-parent --name test-fork-plan --worktree --inline-plan --no-launch

TRANSFER="${FORGE_TEST_REPO}-test-fork-plan/.forge/prev_sessions/test-plan-parent/children/test-fork-plan.md"
test -f "$TRANSFER" && echo "TRANSFER_EXISTS=true" || echo "TRANSFER_EXISTS=false"
grep -c "Approved Plan" "$TRANSFER"
grep -c "greet function" "$TRANSFER"
```

- [ ] Transfer file created in worktree fork
- [ ] Transfer contains plan heading ("Approved Plan")
- [ ] Transfer contains plan details ("greet function")

### 5.15 Fork `--into` (Existing Worktree)

<!-- prereq: 2.4, 4.2, 5.6 -->

<!-- requires: api_key -->

<!-- human:guided -->

<!-- evidence: automated-suite -->

Fork a session into an existing non-main worktree using `--into`. Unlike `--worktree` (which creates a new worktree),
`--into` reuses an existing one and marks the session as non-owning — the worktree is preserved when the session is
deleted. In the **container shell**, create a target worktree, fork into it, and interact briefly with Claude to confirm
parent context, then exit (`/exit`).

Note: `--into` targets have their own Forge installation (required), so manifests live in the target worktree's
`.forge/sessions/` — not centrally. Like `fork --worktree`, the fork manifest belongs to the destination checkout; this
differs from root-level `session start --worktree`, which keeps the session manifest in the project root's `.forge/`.

```
# Clean up from previous runs
forge session delete test-fork-into --yes --force 2>/dev/null || true
TARGET_WORKTREE="${FORGE_TEST_REPO}-test-into-target"
git worktree remove "$TARGET_WORKTREE" --force 2>/dev/null || true
git branch -D test-into-target 2>/dev/null || true

# Create a target worktree (simulating an existing feature branch)
git worktree add "$TARGET_WORKTREE" -b test-into-target

# Install Forge extensions in the target worktree (required for --into)
cd "$TARGET_WORKTREE" && forge extension enable --scope local
cd "$FORGE_TEST_REPO"

# Fork the parent session into the existing worktree.
# Claude will launch with parent transfer context.
# Disable auto-memory so "where were we?" tests Forge transfer, not CC memory.
# Ask "where were we?" to confirm parent context, then exit (/exit).
CLAUDE_CODE_DISABLE_AUTO_MEMORY=1 forge session fork test-session-parent --name test-fork-into --into "$TARGET_WORKTREE"

# Verify fork
forge session show test-fork-into
# Manifest lives in target worktree (--into targets are their own forge_root)
cat "$TARGET_WORKTREE/.forge/sessions/test-fork-into/forge.session.json" | \
  jq '{is_fork, parent_session, worktree: (.worktree | {path, is_worktree, owns_worktree})}'
```

- [ ] Fork created in existing worktree at `${FORGE_TEST_REPO}-test-into-target`
- [ ] `forge session show` reports type as Fork with worktree info
- [ ] Manifest at `${FORGE_TEST_REPO}-test-into-target/.forge/sessions/test-fork-into/` (target's forge_root)
- [ ] Manifest has `is_fork: true`, `is_worktree: true`, `owns_worktree: false`
- [ ] Parent transfer context file present in target worktree
- [ ] Asking "where were we?" reflects parent context from 5.6

### 5.16 Subprocess Proxy (Direct + Proxied Subprocesses)

<!-- prereq: 2.4, 4.2 -->

<!-- auto -->

```bash
# Clean up from previous runs
forge session delete test-subprocess-proxy --yes --force 2>/dev/null || true

# Create a session with --subprocess-proxy (direct main, proxied subprocesses)
forge session start test-subprocess-proxy --subprocess-proxy "$FORGE_QA_GEMINI_PROXY" --no-launch

# Verify intent recorded in session manifest
jq '.intent.subprocess_proxy' .forge/sessions/test-subprocess-proxy/forge.session.json

# Verify session is direct mode (no proxy routing for main session)
jq '{proxy: .intent.proxy, started_with_proxy: .confirmed.started_with_proxy}' \
  .forge/sessions/test-subprocess-proxy/forge.session.json
```

- [ ] Session created with `--subprocess-proxy` flag (exit 0)
- [ ] `intent.subprocess_proxy` matches `$FORGE_QA_GEMINI_PROXY` in session manifest
- [ ] `intent.proxy` is null (main session is direct mode)
- [ ] `confirmed.started_with_proxy` is null (no proxy for main session)

### 5.17 Subprocess Proxy Mutual Exclusivity

<!-- auto -->

```bash
# Try combining --subprocess-proxy with --proxy (should error)
forge session start test-invalid-subproxy \
  --subprocess-proxy "$FORGE_QA_GEMINI_PROXY" --proxy "$FORGE_QA_OPENAI_PROXY" --no-launch 2>&1
echo "EXIT=$?"
```

- [ ] Error message about mutual exclusivity of `--subprocess-proxy` and `--proxy`
- [ ] Exit code is non-zero

### 5.18 Subprocess Proxy Inheritance (Fork)

<!-- prereq: 5.16 -->

<!-- auto -->

```bash
# Seed confirmed.claude_session_id so fork guard passes
PARENT_JSON=".forge/sessions/test-subprocess-proxy/forge.session.json"
jq '.confirmed.claude_session_id = "fixture-subproxy"' "$PARENT_JSON" > /tmp/sp.json \
  && mv /tmp/sp.json "$PARENT_JSON"

# Fork the session
forge session delete test-fork-subproxy --yes --force 2>/dev/null || true
forge session fork test-subprocess-proxy --name test-fork-subproxy --no-launch

# Verify forked session inherits subprocess_proxy
jq '.intent.subprocess_proxy' .forge/sessions/test-fork-subproxy/forge.session.json

# Clean up
forge session delete test-subprocess-proxy --yes --force 2>/dev/null || true
forge session delete test-fork-subproxy --yes --force 2>/dev/null || true
```

- [ ] Forked session inherits `subprocess_proxy` from parent
- [ ] Child `intent.subprocess_proxy` matches `$FORGE_QA_GEMINI_PROXY`
- [ ] Both test sessions cleaned up

### 5.19 Native-Relocate Fork Preflight Rejections

<!-- auto -->

Verify the `--resume-mode native-relocate` preflight guards reject before any fork/worktree is created. These exit
non-zero during preflight and never launch Claude (no live transcript needed). A live byte-faithful resume is covered by
the Docker contract test, not here.

```bash
cd $FORGE_TEST_REPO

# Clean up from previous runs
forge session delete nr-parent --yes --force 2>/dev/null || true
forge session delete nr-sidecar-parent --yes --force 2>/dev/null || true

# Host parent with no transcript (no Claude launch)
forge session start nr-parent --no-launch

# native-relocate resumes at launch -> --no-launch is rejected
forge session fork nr-parent --worktree --resume-mode native-relocate --no-launch 2>&1; echo "NOLAUNCH_EXIT=$?"

# Parent has no Claude transcript to relocate (exits in preflight, does not launch)
forge session fork nr-parent --worktree --resume-mode native-relocate 2>&1; echo "NOTRANSCRIPT_EXIT=$?"

# Sidecar parent: relocation writes to the host ~/.claude store -> host mode only
forge session start nr-sidecar-parent --sidecar --no-launch
forge session fork nr-sidecar-parent --worktree --resume-mode native-relocate 2>&1; echo "SIDECAR_EXIT=$?"

# Clean up
git worktree prune 2>/dev/null || true
forge session delete nr-parent --yes --force 2>/dev/null || true
forge session delete nr-sidecar-parent --yes --force 2>/dev/null || true
```

- [ ] `--resume-mode native-relocate --no-launch` rejected (exit non-zero) with the `omit --no-launch` tip
- [ ] native-relocate with no parent transcript rejected with `has no Claude transcript to relocate` (no launch)
- [ ] native-relocate with a sidecar parent rejected with `not supported with sidecar mode` (host mode only)

### 5.20 Native-Relocate `--into` Same-Dir Data-Loss Guard

<!-- auto -->

Just-fixed data-loss guard: a `--into` target that encodes to the parent's OWN Claude project dir is rejected, so a
no-op relocate can never make later child-deletion unlink the parent's original transcript.

```bash
cd $FORGE_TEST_REPO

# Clean up from previous runs
forge session delete nr-into-parent --yes --force 2>/dev/null || true
NR_WT="${FORGE_TEST_REPO}-nr-into-target"
if [ -d "$NR_WT" ]; then
  (cd "$NR_WT" && forge extension disable --scope local --yes) \
    || { echo "ERROR: could not remove stale local extension ownership" >&2; exit 1; }
fi
git worktree remove "$NR_WT" --force 2>/dev/null || true
git branch -D nr-into-target 2>/dev/null || true

# Target worktree (with Forge enabled -- required for --into)
git worktree add "$NR_WT" -b nr-into-target
cd "$NR_WT" && forge extension enable --scope local && cd "$FORGE_TEST_REPO"

# Parent whose claude_project_root IS that worktree, with a real transcript there.
forge session start nr-into-parent --no-launch
PJSON=".forge/sessions/nr-into-parent/forge.session.json"
jq --arg cwd "$NR_WT" \
  '.confirmed.claude_project_root = $cwd | .confirmed.claude_session_id = "fixture-nr-into"' \
  "$PJSON" > /tmp/nri.json && mv /tmp/nri.json "$PJSON"

# Create the exact transcript file the CLI preflight checks (encoding-agnostic via the real helper).
TP=$(/opt/forge-qa/bin/python -c "from forge.session.claude.paths import get_transcript_path; print(get_transcript_path('$NR_WT','fixture-nr-into'))") \
  || { echo "ERROR: wheel interpreter could not resolve the parent transcript" >&2; exit 1; }
test -n "$TP" || { echo "ERROR: parent transcript path is empty" >&2; exit 1; }
mkdir -p "$(dirname "$TP")"
printf '%s\n' '{"type":"thinking","signature":"x"}' > "$TP"

# Fork --into the parent's own dir -> rejected (requires a different CWD than the parent)
forge session fork nr-into-parent --into "$NR_WT" --resume-mode native-relocate 2>&1; echo "INTO_GUARD_EXIT=$?"

# The parent's original transcript must be untouched.
test -f "$TP" && echo "PARENT_TRANSCRIPT_PRESERVED=true" || echo "PARENT_TRANSCRIPT_PRESERVED=false"

# Clean up extension ownership before removing its root.
(cd "$NR_WT" && forge extension disable --scope local --yes) \
  || { echo "ERROR: could not remove local extension ownership" >&2; exit 1; }
git worktree remove "$NR_WT" --force 2>/dev/null || true
git branch -D nr-into-target 2>/dev/null || true
forge session delete nr-into-parent --yes --force 2>/dev/null || true
```

- [ ] `fork --into <parent's own dir> --resume-mode native-relocate` rejected (exit non-zero) with
  `requires a different CWD than the parent`
- [ ] Parent's original transcript is preserved (not relocated or unlinked)

### 5.21 Session-End Activity Summary

<!-- prereq: 5.8 -->

<!-- requires: api_key -->

<!-- auto -->

The launcher reads the same durable usage ledger as `forge telemetry activity`. Seed one session-scoped event and use
the no-op Claude fixture to exercise the exit renderer without a model completion.

```bash
set -euo pipefail

cleanup_session_end_fixture() {
  forge session delete test-session-end --yes --force >/dev/null 2>&1 || true
  rm -f "$FORGE_HOME/usage/events/qa-session-end_99999.jsonl" /tmp/qa-session-end.out
}
trap cleanup_session_end_fixture EXIT

forge session delete test-session-end --yes --force 2>/dev/null || true
SESSION_END_BIN=/tmp/forge-qa-session-end-bin
mkdir -p "$SESSION_END_BIN"
cat > "$SESSION_END_BIN/claude" <<'EOF'
#!/usr/bin/env bash
if [[ "${1:-}" == "--version" ]]; then
  echo "2.1.245 (Forge QA fixture)"
  exit 0
fi
mkdir -p "$FORGE_HOME/usage/events"
# The launcher lower-bound has subsecond precision; cross the next second before
# writing a whole-second fixture timestamp so it is unambiguously in-run.
sleep 1
TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
printf '%s\n' \
  "{\"schema_version\":1,\"run_id\":\"qa-session-end-run\",\"root_run_id\":\"qa-session-end-run\",\"runtime\":\"claude_code\",\"command\":\"supervisor\",\"status\":\"error\",\"session\":\"test-session-end\",\"attribution_granularity\":\"verb\",\"confidence\":\"reported\",\"cost_micro_usd\":40000,\"ts\":\"$TS\"}" \
  > "$FORGE_HOME/usage/events/qa-session-end_99999.jsonl"
exit 0
EOF
chmod +x "$SESSION_END_BIN/claude"
PATH="$SESSION_END_BIN:$PATH" forge session start test-session-end \
  --proxy "$FORGE_QA_OPENAI_PROXY" 2>&1 | tee /tmp/qa-session-end.out
rg 'Forge this session.*failing open: 1 error.*\$0\.04' /tmp/qa-session-end.out

forge telemetry activity test-session-end

# Clean up
cleanup_session_end_fixture
trap - EXIT
```

- [ ] The launcher prints a `Forge this session` summary before the reconnect tip
- [ ] The line reports `failing open: 1 error` and exact reported cost `$0.04` without an estimate marker
- [ ] `forge telemetry activity test-session-end` reports the same session activity
- [ ] Fixture event, output, and session are removed

### 5.22 Same-Directory Transfer Fork (`--resume-mode transfer` + auto-switch)

<!-- prereq: 5.1 -->

<!-- auto -->

Transfer mode is decoupled from worktree isolation: a **same-directory** fork can run a curated transfer launch (fresh
child session + assembled parent context), not just native `--resume --fork-session`. Explicit `--resume-mode transfer`
opts in; bare `--strategy`/`--inline-plan` on a same-dir fork **auto-switch** it to transfer (the old path silently
dropped those flags). No `--worktree` is created -- the child shares the parent's checkout.

```bash
cd $FORGE_TEST_REPO

# Clean up from previous runs
forge session delete sd-xfer-parent sd-xfer-explicit sd-xfer-auto sd-xfer-native --yes --force 2>/dev/null || true

forge session start sd-xfer-parent --no-launch

# Seed a parent transcript so transfer has content to assemble (same dir = project root).
PJSON=".forge/sessions/sd-xfer-parent/forge.session.json"
TP=$(/opt/forge-qa/bin/python -c "from forge.session.claude.paths import get_transcript_path; print(get_transcript_path('$FORGE_TEST_REPO','fixture-sd-xfer'))") \
  || { echo "ERROR: wheel interpreter could not resolve the parent transcript" >&2; exit 1; }
test -n "$TP" || { echo "ERROR: parent transcript path is empty" >&2; exit 1; }
mkdir -p "$(dirname "$TP")"
printf '%s\n' '{"requestId":"r1","timestamp":"2026-01-01T00:00:00Z","message":{"role":"user","content":[{"type":"text","text":"hello from sd parent"}]}}' > "$TP"
jq --arg tp "$TP" '.confirmed.transcript_path = $tp | .confirmed.claude_session_id = "fixture-sd-xfer"' \
  "$PJSON" > /tmp/sdx.json && mv /tmp/sdx.json "$PJSON"

# (A) Explicit same-dir transfer -- no --worktree
forge session fork sd-xfer-parent --name sd-xfer-explicit --resume-mode transfer --no-launch 2>&1 | tee /tmp/sd-explicit.out
grep -c "Worktree:" /tmp/sd-explicit.out                                          # expect 0 (no worktree created)
CTX_E=".forge/prev_sessions/sd-xfer-parent/children/sd-xfer-explicit.md"
test -f "$CTX_E" && echo "EXPLICIT_CTX=true" || echo "EXPLICIT_CTX=false"
jq -r '.confirmed.derivation.resume_mode' ".forge/sessions/sd-xfer-explicit/forge.session.json"   # expect: transfer

# (B) Auto-switch: bare --strategy on a same-dir fork flips to transfer (status notice, flag not dropped)
forge session fork sd-xfer-parent --name sd-xfer-auto --strategy structured --no-launch 2>&1 | tee /tmp/sd-auto.out
grep -c "switched to transfer mode" /tmp/sd-auto.out                              # expect 1 (auto-switch notice)
jq -r '.confirmed.derivation.resume_mode' ".forge/sessions/sd-xfer-auto/forge.session.json"        # expect: transfer

# (C) Control: a plain same-dir fork stays native (no transfer file, no notice)
forge session fork sd-xfer-parent --name sd-xfer-native --no-launch 2>&1 | tee /tmp/sd-native.out
jq -r '.confirmed.derivation.resume_mode' ".forge/sessions/sd-xfer-native/forge.session.json"      # expect: native
test -f ".forge/prev_sessions/sd-xfer-parent/children/sd-xfer-native.md" && echo "NATIVE_CTX=true" || echo "NATIVE_CTX=false"

# Clean up
forge session delete sd-xfer-parent sd-xfer-explicit sd-xfer-auto sd-xfer-native --yes --force 2>/dev/null || true
```

- [ ] Explicit `--resume-mode transfer` same-dir fork prints no `Worktree:` line (`grep -c` = 0)
- [ ] Explicit transfer fork generates the context file at
  `.forge/prev_sessions/sd-xfer-parent/children/sd-xfer-explicit.md` (`EXPLICIT_CTX=true`)
- [ ] Explicit transfer fork manifest records `derivation.resume_mode == "transfer"`
- [ ] Bare `--strategy` on a same-dir fork prints the auto-switch notice (`switched to transfer mode`, `grep -c` = 1)
- [ ] Auto-switched fork manifest records `derivation.resume_mode == "transfer"`
- [ ] Plain same-dir fork (no flags) manifest records `derivation.resume_mode == "native"`
- [ ] Plain same-dir fork generates no transfer context file (`NATIVE_CTX=false`)

### 5.23 Workspace Worktree View

<!-- auto -->

The workspace view is Git-derived, so it includes empty and currently unavailable registered worktrees alongside Forge
session occupancy. Use a disposable linked worktree and restore it before cleanup.

```bash
cd "$FORGE_TEST_REPO"

WORKSPACE_QA_WT="${FORGE_TEST_REPO}-qa-workspace-view"
WORKSPACE_QA_AWAY="${WORKSPACE_QA_WT}-away"

# Recover an interrupted previous run before starting.
if test -d "$WORKSPACE_QA_AWAY" && ! test -e "$WORKSPACE_QA_WT"; then
  mv "$WORKSPACE_QA_AWAY" "$WORKSPACE_QA_WT"
fi
git worktree remove "$WORKSPACE_QA_WT" --force 2>/dev/null || true
git branch -D qa-workspace-view 2>/dev/null || true
forge session delete qa-workspace-main --yes --force 2>/dev/null || true

forge session start qa-workspace-main --no-launch
git worktree add "$WORKSPACE_QA_WT" -b qa-workspace-view

forge workspace worktrees
forge workspace worktrees --json | tee /tmp/forge-workspace-live.json
jq -e '
  (.primary_root | type == "string") and
  (.common_dir | type == "string") and
  ([.worktrees[] | select(.is_primary and .sessions >= 1)] | length == 1) and
  ([.worktrees[] | select(.branch == "qa-workspace-view" and .sessions == 0 and .active == 0)] | length == 1)
' /tmp/forge-workspace-live.json

# Make the registered path unavailable without deleting its Git metadata.
mv "$WORKSPACE_QA_WT" "$WORKSPACE_QA_AWAY"
forge workspace worktrees | tee /tmp/forge-workspace-missing.txt
forge workspace worktrees --json | tee /tmp/forge-workspace-missing.json
grep -F 'missing (prunable)' /tmp/forge-workspace-missing.txt
jq -e '[.worktrees[] | select(.branch == "qa-workspace-view" and (.path_exists | not) and .is_prunable)] | length == 1' \
  /tmp/forge-workspace-missing.json

# Non-Git paths degrade to one directory member with no common directory.
WORKSPACE_QA_NON_GIT=$(mktemp -d)
(cd "$WORKSPACE_QA_NON_GIT" && forge workspace worktrees --json) | \
  jq -e '.common_dir == null and (.worktrees | length == 1) and .worktrees[0].is_primary'
rmdir "$WORKSPACE_QA_NON_GIT"

# Restore and remove the disposable worktree cleanly.
mv "$WORKSPACE_QA_AWAY" "$WORKSPACE_QA_WT"
git worktree remove "$WORKSPACE_QA_WT" --force
git branch -D qa-workspace-view
forge session delete qa-workspace-main --yes --force
```

- [ ] Human output lists both the primary and empty linked worktree
- [ ] JSON exposes `primary_root`, `common_dir`, and the pinned worktree fields
- [ ] The main checkout reports at least one session; the empty linked worktree reports zero sessions and zero active
- [ ] Moving the checkout away preserves its row and renders `missing (prunable)`
- [ ] Missing-row JSON keeps `path_exists=false` and Git's independent `is_prunable=true` fact
- [ ] A non-Git directory returns one primary member and `common_dir=null`

### 5.24 Managed Codex with Default Context Delivery

<!-- prereq: 2.4 -->

<!-- requires: codex -->

<!-- paid-operations: 1 -->

<!-- auto -->

Create a small parent transcript, run one bounded Codex turn through the installed wheel, and require Codex to recover
an oracle that exists only in the generated transfer. That proves the default delivery mode put the parent context in
the initial message. This step does not claim Codex hook enrollment.

```bash
set -euo pipefail

cd "$FORGE_TEST_REPO"
forge session delete qa-codex-parent qa-codex-initial --yes --force 2>/dev/null || true
forge session start qa-codex-parent --no-launch

CODEX_PARENT_UUID=11111111-2222-4333-8444-555566667777
CODEX_PARENT_TRANSCRIPT=$(/opt/forge-qa/bin/python -c \
  "from forge.session.claude.paths import get_transcript_path; print(get_transcript_path('$FORGE_TEST_REPO', '$CODEX_PARENT_UUID'))")
mkdir -p "$(dirname "$CODEX_PARENT_TRANSCRIPT")"
cat > "$CODEX_PARENT_TRANSCRIPT" <<'EOF'
{"requestId":"qa-codex-parent","message":{"role":"user","content":[{"type":"text","text":"The release token is CEDAR."}]}}
{"requestId":"qa-codex-parent","message":{"role":"assistant","content":[{"type":"text","text":"Recorded CEDAR for the handoff."}]}}
EOF
jq --arg uuid "$CODEX_PARENT_UUID" --arg transcript "$CODEX_PARENT_TRANSCRIPT" \
  '.confirmed.claude_session_id = $uuid | .confirmed.transcript_path = $transcript' \
  .forge/sessions/qa-codex-parent/forge.session.json > /tmp/qa-codex-parent.json
mv /tmp/qa-codex-parent.json .forge/sessions/qa-codex-parent/forge.session.json

forge runtime preflight codex --json | jq -e '.ready == true'
forge session start qa-codex-initial \
  --runtime codex \
  --resume-from qa-codex-parent \
  --strategy structured \
  --sandbox read-only \
  --task 'Read the supplied parent context. Reply with FORGE_CODEX_ followed immediately by its release token. Do not modify files.' \
  2>&1 | tee /tmp/qa-codex-initial.out
rg 'FORGE_CODEX_CEDAR' /tmp/qa-codex-initial.out

CODEX_MANIFEST=.forge/sessions/qa-codex-initial/forge.session.json
jq -e '
  .intent.launch.runtime == "codex"
  and (.confirmed.codex.thread_id | type == "string" and length > 0)
  and .confirmed.codex.context_delivery == "initial_message"
  and (.confirmed.codex.rollout_path | type == "string" and length > 0)
  and .confirmed.derivation.parent_session == "qa-codex-parent"
  and .confirmed.derivation.context_file == ".forge/prev_sessions/qa-codex-parent/children/qa-codex-initial.md"
  and .confirmed.route_commit != null
' "$CODEX_MANIFEST"
test -f "$(jq -r '.confirmed.codex.rollout_path' "$CODEX_MANIFEST")"
test -f .forge/prev_sessions/qa-codex-parent/children/qa-codex-initial.md
rm -f /tmp/qa-codex-initial.out
```

- [ ] Static Codex preflight is ready in the isolated QA identity
- [ ] One bounded installed-wheel Codex turn succeeds and returns the parent-context oracle text
- [ ] The manifest records runtime `codex`, a real thread id, rollout path, and route commitment
- [ ] `confirmed.codex.context_delivery` is exactly `initial_message`
- [ ] The derivation points at the parent and the named child transfer snapshot

### 5.25 Model Route and Artifact Authority

<!-- prereq: 2.4, 4.2 -->

<!-- auto -->

Use a no-op Claude executable as the launcher boundary. It invokes the installed authority hook from inside the marked
advisory run, proving a read is allowed and a write is denied without spending a model turn.

```bash
cd "$FORGE_TEST_REPO"
forge session delete qa-route-authority --yes --force 2>/dev/null || true
forge session start qa-route-authority \
  --proxy "$FORGE_QA_OPENAI_PROXY" \
  --model gpt-5.6-sol \
  --no-launch
forge session authority set qa-route-authority --role advisory

mkdir -p /tmp/forge-qa-authority-bin
cat > /tmp/forge-qa-authority-bin/claude <<'EOF'
#!/usr/bin/env bash
if [[ "${1:-}" == "--version" ]]; then
  echo "2.1.245 (Forge QA fixture)"
  exit 0
fi
payload() {
  jq -nc --arg cwd "$FORGE_FORGE_ROOT" --arg tool "$1" \
    '{session_id:"qa-authority",hook_event_name:"PreToolUse",cwd:$cwd,tool_name:$tool,tool_input:{file_path:"src/main.py"}}'
}
payload Read | forge hook authority-check
READ_RC=$?
set +e
payload Write | forge hook authority-check >/tmp/qa-authority-write.stdout 2>/tmp/qa-authority-write.stderr
WRITE_RC=$?
set -e
printf 'read=%s write=%s\n' "$READ_RC" "$WRITE_RC" > /tmp/qa-authority-hook.rc
test "$READ_RC" -eq 0
test "$WRITE_RC" -eq 2
exit 0
EOF
chmod +x /tmp/forge-qa-authority-bin/claude
PATH="/tmp/forge-qa-authority-bin:$PATH" forge session resume qa-route-authority

test "$(cat /tmp/qa-authority-hook.rc)" = 'read=0 write=2'
rg 'Artifact authority denied' /tmp/qa-authority-write.stderr
forge session model show qa-route-authority --json | jq -e '
  .route_intent.requested_model == "gpt-5.6-sol"
  and .route_intent.kind == "proxy"
  and .route_commit.kind == "proxy"
  and .route_commit.evidence_source == "route_commit"
'
forge session model history qa-route-authority --json | jq -e '
  (.events | length) == 1
  and .events[0].event_type == "launch_routing_committed"
  and .events[0].payload.route.kind == "proxy"
'
forge session authority show qa-route-authority --json | jq -e '
  .role == "advisory"
  and .tier == "shell_closed"
  and .observed_denials.count == 1
'
```

- [ ] `--model gpt-5.6-sol` resolves to and commits the selected proxy route
- [ ] Model show and history expose the committed event rather than intent alone
- [ ] Authority set/show reports the advisory `shell_closed` contract
- [ ] The launch-marked hook allows Read, denies Write with exit 2, and journals one denial

### 5.26 Native Adoption and Store Repair

<!-- auto -->

Create native evidence without launching a model, adopt it by full id, prove a dual-runtime match fails closed, then
deliberately remove one coherent session's global index row and repair it from the authoritative manifest.

```bash
set -euo pipefail

cd "$FORGE_TEST_REPO"
forge session delete qa-adopted qa-adopt-ambiguous qa-repair --yes --force 2>/dev/null || true

NATIVE_UUID=22222222-3333-4444-8555-666677778888
NATIVE_TRANSCRIPT=$(/opt/forge-qa/bin/python -c \
  "from forge.session.claude.paths import get_transcript_path; print(get_transcript_path('$FORGE_TEST_REPO', '$NATIVE_UUID'))")
mkdir -p "$(dirname "$NATIVE_TRANSCRIPT")"
printf '%s\n' \
  "{\"type\":\"user\",\"cwd\":\"$FORGE_TEST_REPO\",\"message\":{\"content\":\"adopt the release investigation\"}}" \
  "{\"type\":\"assistant\",\"cwd\":\"$FORGE_TEST_REPO\",\"message\":{\"model\":\"claude-opus-4-8\"}}" \
  > "$NATIVE_TRANSCRIPT"

forge session adopt --json | jq -e --arg id "$NATIVE_UUID" \
  'any(.candidates[]; .conversation_id == $id and .user_turns == 1)'
forge session adopt "$NATIVE_UUID" --name qa-adopted --yes
jq -e --arg id "$NATIVE_UUID" '
  .confirmed.claude_session_id == $id
  and .confirmed.adoption.source_runtime == "claude_code"
' .forge/sessions/qa-adopted/forge.session.json
test -f "$NATIVE_TRANSCRIPT"

AMBIGUOUS_UUID=33333333-4444-4555-8666-777788889999
AMBIGUOUS_TRANSCRIPT=$(/opt/forge-qa/bin/python -c \
  "from forge.session.claude.paths import get_transcript_path; print(get_transcript_path('$FORGE_TEST_REPO', '$AMBIGUOUS_UUID'))")
mkdir -p "$(dirname "$AMBIGUOUS_TRANSCRIPT")" "$CODEX_HOME/sessions/2026/08/26"
printf '%s\n' "{\"type\":\"user\",\"cwd\":\"$FORGE_TEST_REPO\",\"message\":{\"content\":\"ambiguous\"}}" \
  > "$AMBIGUOUS_TRANSCRIPT"
AMBIGUOUS_ROLLOUT="$CODEX_HOME/sessions/2026/08/26/rollout-2026-08-26T00-00-00-$AMBIGUOUS_UUID.jsonl"
printf '%s\n' \
  "{\"type\":\"session_meta\",\"payload\":{\"id\":\"$AMBIGUOUS_UUID\",\"cwd\":\"$FORGE_TEST_REPO\"}}" \
  > "$AMBIGUOUS_ROLLOUT"
set +e
forge session adopt "$AMBIGUOUS_UUID" --name qa-adopt-ambiguous --yes \
  >/tmp/qa-adopt-ambiguous.stdout 2>/tmp/qa-adopt-ambiguous.stderr
AMBIGUOUS_RC=$?
set -e
test "$AMBIGUOUS_RC" -ne 0
tr '\n' ' ' </tmp/qa-adopt-ambiguous.stderr | rg 'matches both.*Refusing to guess'
test ! -d .forge/sessions/qa-adopt-ambiguous
rm -f "$AMBIGUOUS_TRANSCRIPT" "$AMBIGUOUS_ROLLOUT" \
  /tmp/qa-adopt-ambiguous.stdout /tmp/qa-adopt-ambiguous.stderr

forge session start qa-repair --no-launch
/opt/forge-qa/bin/python - <<'PY'
from forge.session import IndexStore
from forge.session.identity import make_scoped_key

store = IndexStore()
index = store.read()
key = make_scoped_key("qa-repair", "/workspace")
assert key in index.sessions
del index.sessions[key]  # Deliberately violate manifest/index coherence for repair QA.
store.write(index)
PY
forge session repair --json | jq -e \
  'any(.records[]; .name == "qa-repair" and .classification == "repairable") and .apply == null'
forge session repair --yes --json | jq -e \
  '.apply.repaired == ["qa-repair"] and .apply.refused == [] and .apply.failed == []'
forge session list --scope workspace --json | jq -e 'any(.[]; .name == "qa-repair")'
```

- [ ] Adoption preview finds the exact-CWD native conversation and adoption binds its full id
- [ ] Adoption preserves the native transcript and records Claude provenance
- [ ] Matching Claude and Codex evidence for one id fails closed without creating a session
- [ ] Repair preview is root-scoped and classifies the manifest-only record as repairable
- [ ] Repair apply republishes the existing manifest without recreating a worktree

### 5.27 Consumer Lane Placement

<!-- prereq: 5.6 -->

<!-- requires: anthropic_api -->

<!-- paid-operations: 1 -->

<!-- auto -->

Exercise every supported consumer through the installed CLI. Configure the semantic supervisor as well so its status
surface proves the same effective lane; the exhaustive dispatch and billing matrix stays with the automated owners.

```bash
cd "$FORGE_TEST_REPO"
forge session delete qa-consumer-lanes --yes --force 2>/dev/null || true
forge session start qa-consumer-lanes --no-launch

for consumer in supervisor memory_writer shadow_curation team_supervisor; do
  forge session lane set \
    --session qa-consumer-lanes \
    --consumer "$consumer" \
    --runtime claude_code \
    --backend anthropic-direct
done
forge session lane show --session qa-consumer-lanes --json | tee /tmp/qa-consumer-lanes.json
jq -e '
  (.consumers | length) == 4
  and all(.consumers[]; .requested.runtime == "claude_code" and .requested.backend == "anthropic-direct")
  and all(.consumers[]; .frozen == null and .drift == false)
' /tmp/qa-consumer-lanes.json

forge policy supervisor set test-session-parent \
  --session qa-consumer-lanes \
  --no-supervisor-proxy \
  --runtime claude_code \
  --backend anthropic-direct
forge policy supervisor status --session qa-consumer-lanes --json | jq -e '
  .supervisor.resume_id == "test-session-parent"
  and .supervisor.lane.runtime == "claude_code"
  and .supervisor.lane.backend == "anthropic-direct"
'

# One real direct supervisor check proves the keyed container resolves this lane as API-billed.
SUPERVISOR_INPUT=$(jq -nc --arg cwd "$FORGE_TEST_REPO" '
  {
    session_id: "qa-consumer-lanes",
    hook_event_name: "PreToolUse",
    cwd: $cwd,
    tool_name: "Write",
    tool_input: {file_path: "src/main.py", content: "def hello():\n    return \"world\"\n"}
  }
')
set +e
printf '%s\n' "$SUPERVISOR_INPUT" \
  | FORGE_SESSION=qa-consumer-lanes forge hook policy-check \
  >/tmp/qa-consumer-policy.stdout 2>/tmp/qa-consumer-policy.stderr
SUPERVISOR_RC=$?
set -e
[[ "$SUPERVISOR_RC" -eq 0 || "$SUPERVISOR_RC" -eq 2 ]]
forge telemetry activity qa-consumer-lanes --period all --json | jq -e '
  any(.downstream.rows[];
    .command == "supervisor"
    and .runtime == "claude_code"
    and .billing_mode == "api"
    and .calls >= 1)
'

for consumer in supervisor memory_writer shadow_curation team_supervisor; do
  forge session lane clear --session qa-consumer-lanes --consumer "$consumer"
done
forge session lane show --session qa-consumer-lanes --json | jq -e '
  all(.consumers[]; .requested == null and .drift == false)
  and (.consumers[] | select(.consumer == "supervisor")
    | .frozen.runtime == "claude_code" and .frozen.backend == "anthropic-direct")
  and all(.consumers[]; .consumer == "supervisor" or .frozen == null)
'
forge policy supervisor remove --session qa-consumer-lanes
rm -f /tmp/qa-consumer-lanes.json /tmp/qa-consumer-policy.stdout /tmp/qa-consumer-policy.stderr
```

- [ ] Lane set/show covers all four consumers with the requested direct API-capable lane
- [ ] No consumer is prematurely frozen and no drift is reported
- [ ] Supervisor status resolves the same effective lane as the general lane surface
- [ ] One keyed direct supervisor call is reported as `claude_code/api`
- [ ] Lane clear drops every request without mutating the supervisor's frozen binding
- [ ] Unknown/proxied variants and keyless `claude-max` subscription labeling remain owned by automated billing tests

---
