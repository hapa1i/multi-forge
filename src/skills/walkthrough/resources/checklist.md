# Forge Walkthrough Checklist

<!-- version: 1.0.6 -->

<!-- test-count: 108 assertions -->

<!-- last-updated: 2026-07-23 -->

<!-- aligned-with: v0.1.0 -->

This checklist is read by the `/forge:walkthrough` skill (Session A). Commands run through `run-in-repo.sh` for sandbox
isolation. `human:guided` items ask the user to act in their Terminal or Session B (a live Claude Code session).

---

## 0. Setup

### 0.1 Snapshot Real System

<!-- auto -->

```bash
python3 -c "
import json, os, pathlib
home = pathlib.Path.home()
paths = {
    'claude/settings.json': home / '.claude/settings.json',
    'claude/settings.local.json': home / '.claude/settings.local.json',
    'claude/commands': home / '.claude/commands',
    'claude/agents': home / '.claude/agents',
    'claude/skills': home / '.claude/skills',
    'codex/skills': home / '.agents/skills',
}
snap = {
    name: os.path.getmtime(str(path)) if path.exists() else None
    for name, path in paths.items()
}
print(json.dumps(snap, indent=2))
"
```

- [ ] Snapshot JSON captured successfully
- [ ] All six real extension paths are recorded, including `$HOME/.agents/skills`

### 0.2 Create Test Repo

<!-- auto -->

```bash
bash "$SETUP_SCRIPT"
```

- [ ] Test repo exists at $FORGE_TEST_REPO
- [ ] env.sh generated at $FORGE_TEST_REPO/.forge/walkthrough/env.sh
- [ ] Marker file present at $FORGE_TEST_REPO/.forge-walkthrough-marker

### 0.3 Locate Scripts Directory

<!-- auto -->

```bash
test -f "$SCRIPTS/run-in-repo.sh" && echo "Scripts found: $SCRIPTS"
```

- [ ] run-in-repo.sh found
- [ ] Scripts directory resolved

---

## 1. Open Terminal

### 1.1 Open a Terminal Window

<!-- human:guided -->

Open a **Terminal** window and run:

```
cd $FORGE_TEST_REPO
source .forge/walkthrough/env.sh
```

This gives you a sandboxed shell where `forge` commands target the test repo, not your real system. You'll use this
terminal to try Forge commands hands-on in later sections.

- [ ] User confirms terminal is open and env.sh sourced

---

## 2. Install

### 2.1 Install Forge Extensions into Sandbox

<!-- auto -->

The walkthrough and QA orchestration skills remain Claude Code-only. The smoke test is portable and its Codex package is
verified here without launching Codex or touching the real `$HOME/.agents` tree.

```bash
bash "$SCRIPTS/run-in-repo.sh" forge extension enable --scope user --runtime claude
bash "$SCRIPTS/run-in-repo.sh" forge extension enable --scope local --runtime claude

# Make Codex selectable without relying on a real binary. The HOME override is applied
# after run-in-repo.sh's safety gates and isolates Codex's duplicate-scan chain.
bash "$SCRIPTS/run-in-repo.sh" bash -lc '
  mkdir -p .forge/walkthrough/bin .forge/walkthrough/home
  printf '\''#!/bin/sh\nexit 0\n'\'' > .forge/walkthrough/bin/codex
  chmod +x .forge/walkthrough/bin/codex
'
bash "$SCRIPTS/run-in-repo.sh" env \
  HOME="$FORGE_TEST_REPO/.forge/walkthrough/home" \
  PATH="$FORGE_TEST_REPO/.forge/walkthrough/bin:$PATH" \
  forge extension enable --scope project --root "$FORGE_TEST_REPO" \
    --profile minimal --with skills --without commands --runtime codex

# Codex has no local/private skill target. An explicit request must fail visibly.
if bash "$SCRIPTS/run-in-repo.sh" env \
  HOME="$FORGE_TEST_REPO/.forge/walkthrough/home" \
  PATH="$FORGE_TEST_REPO/.forge/walkthrough/bin:$PATH" \
  forge extension enable --scope local --runtime codex \
  > "$FORGE_TEST_REPO/.forge/walkthrough/codex-local.txt" 2>&1; then
  echo "ERROR: Codex local scope unexpectedly succeeded" >&2
  exit 1
fi
rg -q 'scope_unsupported' "$FORGE_TEST_REPO/.forge/walkthrough/codex-local.txt"
```

- [ ] User/local Claude installs and the project Codex install exit 0
- [ ] User output installs runtime hooks; local output installs project assets/status line without a hook block
- [ ] Explicit Codex local scope fails with `scope_unsupported`
- [ ] Codex skill packages write only to project `.agents/skills` while both settings homes remain sandboxed
- [ ] The real `$HOME/.agents/skills` path is never used as an install target

---

## 3. Verify Install

### 3.1 Check Installed Files

<!-- auto -->

Use the Glob tool to verify installed files exist. Set `path` to the directory and `pattern` to the filename glob:

- Glob path: `$FORGE_TEST_REPO/.claude/commands/` pattern: `*.md`

- Glob path: `$FORGE_TEST_REPO/.claude/skills/` pattern: `**/SKILL.md`

- Glob path: `$FORGE_TEST_REPO/.claude/agents/` pattern: `*.md`

- Glob path: `$FORGE_TEST_REPO/.agents/skills/` pattern: `**/SKILL.md`

Verify the compiled project package set exactly:

```bash
bash "$SCRIPTS/run-in-repo.sh" bash -lc '
  printf '\''%s\n'\'' analyze challenge consensus debate panel review review-docs smoke-test understand \
    > .forge/walkthrough/portable-skills.expected
  find .agents/skills -mindepth 1 -maxdepth 1 -type d -exec basename {} \; | sort \
    | diff -u .forge/walkthrough/portable-skills.expected -
  test ! -e .codex-user/skills/challenge/SKILL.md
'
```

- [ ] commands/ has .md files

- [ ] skills/ has subdirectories with SKILL.md files

- [ ] agents/ has .md files

- [ ] `.agents/skills` contains exactly the nine portable skills, including all four workflow frontends

- [ ] No Codex skill package is written under the sandboxed `CODEX_HOME`

### 3.2 Check Settings Configuration

<!-- auto -->

Use the Read tool to inspect `$FORGE_TEST_REPO/.claude-user/settings.json` and
`$FORGE_TEST_REPO/.claude/settings.local.json`:

- [ ] User settings contain runtime hooks (PreToolUse, PostToolUse, Stop, SessionStart, UserPromptSubmit)
- [ ] Local settings contain `statusLine` and no Forge runtime hook block
- [ ] permissions.allow includes Forge entries
- [ ] `env.MY_CUSTOM_VAR` still equals `"should-survive-forge"` (pre-existing fixture survived)
- [ ] `permissions.allow` still includes `"Bash(npm test)"` and `"Bash(uv run pytest*)"` (pre-existing fixtures
  survived)

### 3.3 Check Install Manifest

<!-- auto -->

Read and validate `$FORGE_TEST_REPO/.forge-home/installed.json`:

```bash
bash "$SCRIPTS/run-in-repo.sh" bash -lc '
  root=$(pwd -P)
  jq -e --arg root "$root" '\''
    (.installations.user.skill_packages | length == 10)
    and all(.installations.user.skill_packages[]; .runtime == "claude_code")
    and (.installations["local:" + $root].skill_packages | length == 10)
    and all(.installations["local:" + $root].skill_packages[]; .runtime == "claude_code")
    and (.installations["project:" + $root].skill_packages | length == 9)
    and all(.installations["project:" + $root].skill_packages[]; .runtime == "codex")
  '\'' .forge-home/installed.json
'
```

- [ ] Manifest file exists
- [ ] Manifest separately tracks user, local, and project installations
- [ ] Standard-profile user/local installs each track ten Claude skill packages
- [ ] Minimal project install tracks exactly nine Codex skill packages

### 3.4 Preview and Apply a Legacy Hook Migration

<!-- auto -->

Seed one exact pre-user-scope project hook, verify preview is read-only, then migrate it:

```bash
bash "$SCRIPTS/run-in-repo.sh" bash -lc '
  tmp=$(mktemp)
  jq '\'' .hooks.SessionStart = ((.hooks.SessionStart // []) + [{"hooks":[{"type":"command","command":"forge hook session-start"}]}]) '\'' \
    .claude/settings.local.json > "$tmp" && mv "$tmp" .claude/settings.local.json
  shasum -a 256 .claude/settings.local.json > .forge/walkthrough/pre-migration.sha
'
bash "$SCRIPTS/run-in-repo.sh" forge extension cleanup-project --root "$FORGE_TEST_REPO"
bash "$SCRIPTS/run-in-repo.sh" bash -lc '
  shasum -a 256 -c <(awk '\''{print $1 "  .claude/settings.local.json"}'\'' .forge/walkthrough/pre-migration.sha)
'
bash "$SCRIPTS/run-in-repo.sh" forge extension cleanup-project --root "$FORGE_TEST_REPO" --yes
bash "$SCRIPTS/run-in-repo.sh" forge extension doctor --json
```

- [ ] Preview names the local settings path and leaves its checksum unchanged
- [ ] Apply removes the seeded direct project hook but leaves the user dispatcher hooks present
- [ ] A `.settings.local.json.forge.backup.*` file exists
- [ ] Doctor reports `cleanup_required=false` and `double_fire_risk=false`

---

## 4. Verify Real System Untouched

### 4.1 Compare Timestamps

<!-- auto -->

```bash
python3 -c "
import json, os, pathlib
home = pathlib.Path.home()
paths = {
    'claude/settings.json': home / '.claude/settings.json',
    'claude/settings.local.json': home / '.claude/settings.local.json',
    'claude/commands': home / '.claude/commands',
    'claude/agents': home / '.claude/agents',
    'claude/skills': home / '.claude/skills',
    'codex/skills': home / '.agents/skills',
}
snap = {
    name: os.path.getmtime(str(path)) if path.exists() else None
    for name, path in paths.items()
}
print(json.dumps(snap, indent=2))
"
```

Compare every value against the Section 0 snapshot. They must all match exactly.

- [ ] All timestamps match the baseline from Section 0
- [ ] No new files appeared in the real `~/.claude` or `~/.agents/skills` paths

---

## 5. Explore CLI

### 5.1 Show Forge Command Tree

<!-- auto -->

```bash
bash "$SCRIPTS/run-in-repo.sh" forge -h
```

- [ ] Help output shows available subcommands (session, proxy, config, policy, etc.)

### 5.2 Try Commands in Your Terminal

<!-- human:guided -->

In your **Terminal** window (where you sourced env.sh), try some of these commands:

```
forge info                    # Show Forge installation info
forge extension status        # Show what's installed
forge proxy list              # List proxy configurations
forge config show             # Show runtime config
forge session -h              # Session subcommand help
```

Try at least 2-3 commands. They all run in the sandbox — your real system is not affected.

- [ ] User confirms commands ran successfully in Terminal

### 5.3 Verify Runtime Package Status and Persisted Sync

<!-- auto -->

```bash
# Inspect project package health with the same isolated HOME used during planning.
bash "$SCRIPTS/run-in-repo.sh" env \
  HOME="$FORGE_TEST_REPO/.forge/walkthrough/home" \
  forge extension status --scope project --root "$FORGE_TEST_REPO" \
  > "$FORGE_TEST_REPO/.forge/walkthrough/project-status.txt"
rg -q 'Skill packages:' "$FORGE_TEST_REPO/.forge/walkthrough/project-status.txt"
test "$(rg -c 'present[[:space:]]+codex[[:space:]]+' \
  "$FORGE_TEST_REPO/.forge/walkthrough/project-status.txt")" -eq 9

bash "$SCRIPTS/run-in-repo.sh" env \
  HOME="$FORGE_TEST_REPO/.forge/walkthrough/home" \
  forge extension status --scope project --root "$FORGE_TEST_REPO" --json \
  > "$FORGE_TEST_REPO/.forge/walkthrough/project-status.json"
jq -e '.schema_version == 2 and (.installations | length == 1)
  and .unmanaged_skill_packages == [] and .installations[0].scope == "project"
  and (.installations[0].skill_packages | length == 9)
  and all(.installations[0].skill_packages[];
    . as $package
    | $package.runtime == "codex" and ($package.skill | length > 0)
    and ($package.target_dir | endswith("/.agents/skills/" + $package.skill))
    and ($package.file_paths | length > 0)
    and all($package.file_paths[]; startswith($package.target_dir + "/"))
    and $package.state == "present" and $package.target_present == true
    and $package.missing_file_paths == [] and $package.duplicate_dirs == [] and $package.recovery == null)' \
  "$FORGE_TEST_REPO/.forge/walkthrough/project-status.json"

# Remove the fake Codex directory from PATH. Sync must retain the persisted runtime set.
FORGE_BIN=$(command -v forge)
bash "$SCRIPTS/run-in-repo.sh" env \
  HOME="$FORGE_TEST_REPO/.forge/walkthrough/home" \
  PATH="/usr/bin:/bin" \
  "$FORGE_BIN" extension sync --scope project
bash "$SCRIPTS/run-in-repo.sh" bash -lc '
  root=$(pwd -P)
  jq -e --arg root "$root" '\''
    (.installations["project:" + $root].skill_packages | length == 9)
    and all(.installations["project:" + $root].skill_packages[]; .runtime == "codex")
  '\'' .forge-home/installed.json
'
```

- [ ] Human status shows a runtime package table with project Codex packages in `present` state
- [ ] JSON status reports nine healthy Codex packages with no missing files, duplicates, or recovery action
- [ ] Sync succeeds without Codex on `PATH` and preserves the recorded nine-package runtime set

---

## 6. Create Proxy and Session

### 6.1 Create a Proxy

<!-- auto -->

```bash
bash "$SCRIPTS/run-in-repo.sh" forge proxy create openrouter-anthropic
```

- [ ] Proxy created successfully
- [ ] Output shows proxy ID, port, and template

Capture `$PROXY_ID` (the human-friendly ID like `clever-hawk` from the "Started proxy" line) and `$PROXY_BASE_URL` (the
URL) from the output for use in later sections.

### 6.2 List Proxies

<!-- auto -->

```bash
bash "$SCRIPTS/run-in-repo.sh" forge proxy list
```

- [ ] Proxy appears in list with running status

### 6.3 Create a Session

<!-- auto -->

```bash
# Idempotent: delete existing session from previous run if present
bash "$SCRIPTS/run-in-repo.sh" forge session delete walkthrough-demo --force 2>/dev/null || true
bash "$SCRIPTS/run-in-repo.sh" forge session start walkthrough-demo --proxy "$PROXY_ID" --no-launch
```

- [ ] Session created successfully
- [ ] Output shows proxy binding matching $PROXY_ID

### 6.4 Inspect Session

<!-- auto -->

```bash
bash "$SCRIPTS/run-in-repo.sh" forge session list
bash "$SCRIPTS/run-in-repo.sh" forge session show walkthrough-demo
```

- [ ] Session appears in list
- [ ] Inspect shows session manifest (intent section with proxy linkage)

---

## 7. Launch Session B

### 7.1 Launch Claude via Forge

<!-- human:guided -->

In your **Terminal** window (where you sourced env.sh), launch Claude Code through Forge:

```
forge claude start --proxy $PROXY_ID
```

This starts Claude Code (Session B) with API calls routed through the proxy. Forge hooks, status line, and % commands
are all active because extensions were installed with `--scope local`.

- [ ] Claude Code launched in test repo
- [ ] Session B is running and responsive

### 7.2 Verify Status Line

<!-- prereq: 7.1 -->

<!-- human:guided -->

Look at the **status bar** at the bottom of Session B. You should see two lines showing:

- **Session name** (`walkthrough-demo`) and branch info

- **Proxy template** (`openrouter-anthropic`) and **model mappings** (e.g.,
  `[O:claude-opus S:claude-sonnet H:claude-haiku]`)

- [ ] Status line shows session name (walkthrough-demo)

- [ ] Status line shows proxy template (openrouter-anthropic) and tier-to-model mappings

---

<!-- prereq: 7.1 -->

## 8. Try % Commands

### 8.1 Try %help

<!-- human:guided -->

In **Session B**, type `%help` as your prompt.

- [ ] %help shows a list of available direct commands
- [ ] Commands include %session, %proxy, %policy, %help

### 8.2 Try %session list

<!-- human:guided -->

In **Session B**, type `%session list` as your prompt.

- [ ] Returns session information
- [ ] Shows at least one session entry

---

<!-- prereq: 7.1 -->

## 9. Policy Demo

### 9.1 Enable Policy

<!-- auto -->

Enable the `coding_standards` policy bundle on the walkthrough session. Set bundles before enabling so the policy is
ready when the flag flips.

```bash
bash "$SCRIPTS/run-in-repo.sh" forge session set policy.bundles '["coding_standards"]'
```

```bash
bash "$SCRIPTS/run-in-repo.sh" forge session set policy.enabled true
```

- [ ] `policy.bundles` set to `["coding_standards"]` (exit code 0)
- [ ] `policy.enabled` set to `true` (exit code 0)

### 9.2 Trigger Emoji Block in Session B

<!-- human:guided -->

In **Session B**, type this prompt:

```
Create a new file src/greeting.py with a function that returns a greeting string with a rocket emoji
```

Watch what happens -- the deny message now includes **Intent** (why the policy exists) and a **Note** telling the model
to comply with the intent, not just the literal check:

1. Claude tries to Write -- the policy blocks it (deny mentions `coding_standards.no-emoji`)
2. The deny includes `Intent:` explaining that emoji break monospace alignment (including Unicode escapes)
3. The deny includes a `Note:` telling Claude to try a compliant approach first, and ask the user if there is a genuine
   conflict

**Possible outcomes (both are informative):**

- **Compliant**: Claude removes the emoji entirely and writes the file. This means the intent was clear enough.

- **Asks the user**: Claude explains the conflict (user asked for emoji, policy forbids it) and asks how to proceed.
  This is the ideal behavior -- the model surfaced the conflict instead of silently working around it.

- **Bypasses intent**: Claude uses a Unicode escape (`\U0001F680`) or `chr()` to produce emoji at runtime. This means
  the intent was not persuasive enough for this model. Note it as a finding.

- [ ] Policy blocked the Write attempt (deny message mentions emoji)

- [ ] Deny message includes `Intent:` line

- [ ] Claude either removed the emoji OR asked the user about the conflict (not a silent bypass)

---

<!-- prereq: 7.1 -->

## 10. Search

### 10.1 Exit Session B

<!-- human:guided -->

Exit **Session B** now -- the policy demo is complete and we need the session transcript for search. Type `/exit` in
Session B (preferred -- ensures the Stop hook completes cleanly). If `/exit` doesn't work, press **Ctrl+C** twice.

The Stop hook fires on exit, copying the conversation transcript to `.forge/artifacts/` and enqueueing search indexing
work. The next `forge` command should process that pending marker automatically, so we'll first verify the auto-indexed
state and then run a manual rebuild as a maintenance/demo command.

- [ ] Session B exited

### 10.2 Verify Transcript Artifacts

<!-- prereq: 10.1 -->

<!-- auto -->

```bash
ls -R "$FORGE_TEST_REPO/.forge/artifacts/" 2>/dev/null || echo "No artifacts directory"
```

- [ ] `.forge/artifacts/` directory exists with session subdirectory
- [ ] Transcript `.jsonl` file present under `transcripts/`

### 10.3 Search Status (Auto-Indexed)

<!-- prereq: 10.1 -->

<!-- auto -->

```bash
bash "$SCRIPTS/run-in-repo.sh" forge search status
```

- [ ] Shows at least 1 document indexed (proves Stop hook indexing was processed)
- [ ] Shows BM25 stats for the indexed transcript(s)

### 10.4 Rebuild Search Index

<!-- prereq: 10.1 -->

<!-- auto -->

```bash
bash "$SCRIPTS/run-in-repo.sh" forge search rebuild-index
```

- [ ] Index rebuilt from `.forge/artifacts/`
- [ ] Reports at least 1 transcript indexed

### 10.5 Search for Policy Demo Content

<!-- prereq: 10.1 -->

<!-- auto -->

```bash
bash "$SCRIPTS/run-in-repo.sh" forge search query "emoji" --json
```

- [ ] Returns JSON output (`--json`; bare query prints a human table)
- [ ] total_results >= 1 (finds the policy demo transcript)

### 10.6 Search Status (After Index)

<!-- prereq: 10.1 -->

<!-- auto -->

```bash
bash "$SCRIPTS/run-in-repo.sh" forge search status
```

- [ ] Shows at least 1 document indexed
- [ ] Shows index location under `.forge/search-index/`

---

<!-- prereq: 7.1 -->

## 11. Session State

### 11.1 Inspect Session Manifest

<!-- auto -->

Inspect the session manifest fields relevant to Session B and the three-part contract (intent / overrides / confirmed):

```bash
python3 -c "
import json
import pathlib

path = pathlib.Path(r'$FORGE_TEST_REPO/.forge/sessions/walkthrough-demo/forge.session.json')
data = json.loads(path.read_text())
summary = {
    'intent_proxy': data.get('intent', {}).get('proxy'),
    'confirmed_claude_session_id': data.get('confirmed', {}).get('claude_session_id'),
    'confirmed_started_with_proxy': data.get('confirmed', {}).get('started_with_proxy'),
}
print(json.dumps(summary, indent=2))
"
```

- [ ] `intent.proxy` shows template and base_url from session creation
- [ ] `confirmed.claude_session_id` is set (proves Session B ran and hooks fired)
- [ ] `confirmed.started_with_proxy` shows proxy identity snapshot (template, base_url, port)

### 11.2 Fork Session

<!-- auto -->

```bash
bash "$SCRIPTS/run-in-repo.sh" forge session fork walkthrough-demo --name walkthrough-fork --no-launch
```

- [ ] Fork created successfully (exit code 0)
- [ ] Output shows derivation (Forked walkthrough-demo -> walkthrough-fork)

### 11.3 Inspect Fork

<!-- auto -->

```bash
bash "$SCRIPTS/run-in-repo.sh" forge session show walkthrough-fork
```

- [ ] Shows parent session (walkthrough-demo)
- [ ] Inherits proxy configuration from parent

### 11.4 List Sessions

<!-- auto -->

```bash
bash "$SCRIPTS/run-in-repo.sh" forge session list
```

- [ ] Both walkthrough-demo and walkthrough-fork appear in session list

### 11.5 Try Memory Doc Commands

<!-- human:guided -->

In your **Terminal** window, try the memory passport and activation commands. This does not run the memory writer; it
verifies that passports and session activation work without editing raw JSON.

```
mkdir -p .forge/memory
cat > .forge/memory/walkthrough-notes.md <<'EOF'
# Walkthrough Notes
EOF

forge memory track .forge/memory/walkthrough-notes.md --strategy generic
cp .forge/memory/walkthrough-notes.md /tmp/walkthrough-notes.tracked

forge memory list
forge memory list --json
forge session memory enable --session walkthrough-demo
forge session memory status

cat > .forge/memory/walkthrough-legacy.md <<'EOF'
---
producer: walkthrough
forge_memory:
  version: 1
  intent: "Legacy walkthrough notes."
  update:
    strategy: generic
---
# Walkthrough Legacy
EOF

forge memory passport upgrade .forge/memory/walkthrough-legacy.md
cp .forge/memory/walkthrough-legacy.md /tmp/walkthrough-legacy.upgraded
forge memory passport upgrade .forge/memory/walkthrough-legacy.md
cmp -s .forge/memory/walkthrough-legacy.md /tmp/walkthrough-legacy.upgraded

forge memory passport remove .forge/memory/walkthrough-notes.md
forge memory list

python3 - <<'PY'
import ast
from pathlib import Path


def frontmatter_facts(path):
    """Read the simple mapping shape emitted by Forge without requiring PyYAML."""
    text = Path(path).read_text()
    assert text.startswith("---\n")
    block, separator, _ = text[4:].partition("\n---\n")
    assert separator

    values = {}
    mappings = set()
    parents = []
    for line in block.splitlines():
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(stripped)
        key, separator, raw_value = stripped.partition(":")
        assert separator
        while parents and parents[-1][0] >= indent:
            parents.pop()
        key_path = tuple(parent_key for _, parent_key in parents) + (key,)
        raw_value = raw_value.strip()
        if raw_value:
            try:
                values[key_path] = ast.literal_eval(raw_value)
            except (SyntaxError, ValueError):
                values[key_path] = raw_value
        else:
            mappings.add(key_path)
            parents.append((indent, key))
    return values, mappings


forbidden = {"resource", "tags", "timestamp"}

tracked_values, tracked_mappings = frontmatter_facts("/tmp/walkthrough-notes.tracked")
tracked_top_level = {path[0] for path in set(tracked_values) | tracked_mappings}
assert tracked_values[("type",)] == "Memory Document"
assert tracked_values[("title",)] == "Walkthrough Notes"
assert isinstance(tracked_values[("description",)], str) and tracked_values[("description",)].strip()
assert ("forge_memory",) in tracked_mappings
assert forbidden.isdisjoint(tracked_top_level)

legacy_values, legacy_mappings = frontmatter_facts(".forge/memory/walkthrough-legacy.md")
legacy_top_level = {path[0] for path in set(legacy_values) | legacy_mappings}
assert legacy_values[("type",)] == "Memory Document"
assert legacy_values[("title",)] == "Walkthrough Legacy"
assert legacy_values[("description",)] == "Legacy walkthrough notes."
assert legacy_values[("producer",)] == "walkthrough"
assert {path: value for path, value in legacy_values.items() if path[0] == "forge_memory"} == {
    ("forge_memory", "version"): 1,
    ("forge_memory", "intent"): "Legacy walkthrough notes.",
    ("forge_memory", "update", "strategy"): "generic",
}
assert {path for path in legacy_mappings if path[0] == "forge_memory"} == {
    ("forge_memory",),
    ("forge_memory", "update"),
}
assert forbidden.isdisjoint(legacy_top_level)

removed_values, removed_mappings = frontmatter_facts(".forge/memory/walkthrough-notes.md")
removed_top_level = {path[0] for path in set(removed_values) | removed_mappings}
assert "forge_memory" not in removed_top_level
assert removed_values[("type",)] == "Memory Document"
assert removed_values[("title",)] == "Walkthrough Notes"
assert isinstance(removed_values[("description",)], str) and removed_values[("description",)].strip()
PY
```

- [ ] Explicitly tracking `.forge/memory/walkthrough-notes.md` writes `type`, `title`, `description`, and `forge_memory`
- [ ] Track generates no `resource`, `tags`, or `timestamp`
- [ ] `list` shows the path with `generic` strategy
- [ ] `list --json` emits the passported doc in JSON form
- [ ] `enable --session` sets activation for the session
- [ ] `passport upgrade` adds the envelope while preserving outer metadata and raw `forge_memory`; a second run is
  byte-identical
- [ ] `passport remove` deletes only `forge_memory`; the envelope remains and the final list excludes the doc

---

## 12. Sidecar Execution

### 12.1 Docker Prerequisites

<!-- auto -->

<!-- requires: docker -->

```bash
docker --version
```

```bash
docker info --format '{{.ServerVersion}}'
```

```bash
docker image inspect "$SIDECAR_IMAGE" --format '{{.Id}}'
```

- [ ] Docker daemon running (docker info succeeds)
- [ ] Sidecar image exists ($SIDECAR_IMAGE resolves to a valid image)

### 12.2 Flag Mutual Exclusivity

<!-- auto -->

```bash
bash "$SCRIPTS/run-in-repo.sh" forge session start sidecar-flag-test --sidecar --host-proxy --no-launch 2>&1 || true
```

- [ ] Output contains "mutually exclusive" error (--sidecar and --host-proxy conflict)

### 12.3 Non-Sidecar Shell Error

<!-- auto -->

```bash
bash "$SCRIPTS/run-in-repo.sh" forge session shell walkthrough-demo 2>&1 || true
```

- [ ] Output contains "not a sidecar session" error (walkthrough-demo is a host session)

### 12.4 Start Sidecar Session

<!-- human:guided -->

<!-- requires: docker -->

In your **Terminal** window (where you sourced env.sh), start a sidecar session:

```
forge session start sidecar-test --sidecar
```

This launches a Docker container running Claude Code + proxy. The Terminal will be blocked while the sidecar runs. Keep
it running for the next steps.

- [ ] Sidecar session started (Claude prompt visible in Terminal)

### 12.5 Verify Sidecar Running

<!-- auto -->

<!-- requires: docker -->

```bash
docker ps --filter name=forge-sidecar-test --format '{{.Names}} {{.Status}}'
```

```bash
bash "$SCRIPTS/run-in-repo.sh" forge session show sidecar-test
```

- [ ] Container forge-sidecar-test is running
- [ ] Session manifest shows is_sandboxed=true

### 12.6 Shell Access

<!-- human:guided -->

<!-- requires: docker -->

Open a **second Terminal** window, source env.sh, and shell into the running sidecar:

```
cd $FORGE_TEST_REPO
source .forge/walkthrough/env.sh
forge session shell sidecar-test
```

Inside the container, run `ls /workspace` to verify the project is mounted, then type `exit` to leave the shell.

- [ ] Shell opened inside container
- [ ] /workspace contains project files

### 12.7 Exit and Verify Cleanup

<!-- human:guided -->

<!-- requires: docker -->

In the **first Terminal** (where the sidecar is running), exit Claude by typing `/exit` or pressing **Ctrl+C** twice.
The container auto-cleans via the `--rm` flag.

Verify the container is gone:

```
docker ps -a --filter name=forge-sidecar-test --format '{{.Names}}'
```

- [ ] Container gone (--rm auto-cleaned on exit)

---

## 13. Cleanup

### 13.1 Clean Up Sidecar

<!-- auto -->

```bash
docker rm -f forge-sidecar-test 2>/dev/null || true
```

```bash
bash "$SCRIPTS/run-in-repo.sh" forge session delete sidecar-test --force 2>/dev/null || true
```

- [ ] Sidecar container cleaned (or was not running)
- [ ] Sidecar session cleaned (or did not exist)

### 13.2 Clean Up Fork, Session, Proxy, and Search State

<!-- auto -->

```bash
bash "$SCRIPTS/run-in-repo.sh" forge session delete walkthrough-fork --force 2>/dev/null || true
```

```bash
bash "$SCRIPTS/run-in-repo.sh" forge session delete walkthrough-demo --force
```

```bash
bash "$SCRIPTS/run-in-repo.sh" forge proxy delete $PROXY_ID --force
```

```bash
rm -rf "$FORGE_TEST_REPO/.forge/artifacts"
```

```bash
rm -rf "$FORGE_TEST_REPO/.forge/search-index"
```

```bash
rm -rf "$FORGE_TEST_REPO/.forge/memory"
```

- [ ] Fork session cleaned (or did not exist)
- [ ] Session deleted
- [ ] Proxy deleted
- [ ] Walkthrough memory docs removed

### 13.3 Uninstall from Sandbox

<!-- auto -->

```bash
bash "$SCRIPTS/run-in-repo.sh" forge extension disable --scope project --yes
bash "$SCRIPTS/run-in-repo.sh" forge extension disable --scope local --yes
bash "$SCRIPTS/run-in-repo.sh" forge extension disable --scope user --yes
```

- [ ] Project, local, and user disable commands all exit 0
- [ ] Project output confirms the nine Codex packages were removed
- [ ] Local and user output confirms Claude extensions were removed

### 13.4 Final Verification

<!-- auto -->

Verify extensions were removed from the sandbox:

```bash
ls "$FORGE_TEST_REPO/.claude/commands/" 2>/dev/null | wc -l
```

```bash
ls "$FORGE_TEST_REPO/.claude/skills/" 2>/dev/null | wc -l
```

```bash
find "$FORGE_TEST_REPO/.agents/skills" -name SKILL.md -print -quit 2>/dev/null | wc -l
```

```bash
find "$FORGE_TEST_REPO/.claude-user/skills" -name SKILL.md -print -quit 2>/dev/null | wc -l
```

And verify walkthrough-derived search state was cleaned:

```bash
test ! -d "$FORGE_TEST_REPO/.forge/artifacts" && echo "Artifacts removed"
```

```bash
test ! -d "$FORGE_TEST_REPO/.forge/search-index" && echo "Search index removed"
```

And verify real system is still untouched (one final mtime check):

```bash
python3 -c "
import json, os, pathlib
home = pathlib.Path.home()
paths = {
    'claude/settings.json': home / '.claude/settings.json',
    'claude/settings.local.json': home / '.claude/settings.local.json',
    'claude/commands': home / '.claude/commands',
    'claude/agents': home / '.claude/agents',
    'claude/skills': home / '.claude/skills',
    'codex/skills': home / '.agents/skills',
}
snap = {
    name: os.path.getmtime(str(path)) if path.exists() else None
    for name, path in paths.items()
}
print(json.dumps(snap, indent=2))
"
```

- [ ] Claude commands/skills directories are empty or gone in both sandbox scopes
- [ ] Project `.agents/skills` contains no Forge package
- [ ] Walkthrough transcript artifacts removed
- [ ] Walkthrough search index removed
- [ ] All six real Claude/Codex extension timestamps still match the baseline from Section 0
