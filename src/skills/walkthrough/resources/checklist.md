# Forge Walkthrough Checklist

<!-- version: 2.0.0 -->

<!-- test-count: 145 assertions -->

<!-- last-updated: 2026-09-02 -->

<!-- aligned-with: v1.0.0 -->

<!-- default-human-checkpoints: 7 -->

<!-- default-paid-operations: 2 -->

This is an educational Day 1 journey, not a release-QA matrix. Session A runs automatic checks through the packaged
sandbox wrapper. The user works in one already-sandboxed Terminal and one managed Claude session. Section 12 is
optional; cleanup in section 13 always remains selected.

---

## 0. Establish the Sandbox

### 0.1 Snapshot the Real Extension Paths

<!-- auto -->

Capture privacy-preserving facts for the six real Claude/Codex extension targets. The snapshot records existence, type,
mode, and a content/tree digest; it never copies settings, credentials, or directory listings.

```bash
bash "$SCRIPTS/run-in-repo.sh" python3 "$SCRIPTS/protected-paths.py" capture .forge/walkthrough/real-system.json
```

- [ ] The helper reports `status: captured` and exactly six protected targets
- [ ] The saved snapshot contains facts and digests but no source bytes or absolute home paths

### 0.2 Prove the Generated Repository

<!-- auto -->

```bash
bash "$SCRIPTS/run-in-repo.sh" bash -c '
set -euo pipefail
test -f .forge-walkthrough-marker
test -f .forge/walkthrough/env.sh
test -f CLAUDE.md
test "$PWD" = "$FORGE_TEST_REPO"
printf "sandbox=%s\\n" "$PWD"
'
```

- [ ] The marker, generated environment, and walkthrough repository files exist
- [ ] The wrapper enters the canonical `$FORGE_TEST_REPO`
- [ ] No command target resolves to the real home or another denylisted root

### 0.3 Verify Packaged Helpers

<!-- auto -->

```bash
test -x "$SCRIPTS/run-in-repo.sh"
test -x "$SCRIPTS/claude-wrapper.sh"
test -x "$SCRIPTS/walkthrough-state.py"
test -x "$SCRIPTS/protected-paths.py"
test -x "$SCRIPTS/package-identity.py"
test -x "$SCRIPTS/walkthrough-report.py"
test -x "$SCRIPTS/cleanup-owned.sh"
bash "$SCRIPTS/run-in-repo.sh" claude --version
```

- [ ] The sandbox wrapper and native-Claude settings shim are executable
- [ ] The state engine is executable
- [ ] The protected-path, package-identity, report, and cleanup helpers are executable

---

## 1. Open the Sandboxed Terminal

### 1.1 Activate and Verify the Current Shell

<!-- human:guided -->

Open one Terminal window and run the following. Keep this shell open for the rest of the walkthrough.

```
cd "$FORGE_TEST_REPO"
source .forge/walkthrough/env.sh
test -f .forge-walkthrough-marker
test "$PWD" = "$FORGE_TEST_REPO"
test "$FORGE_HOME" = "$FORGE_TEST_REPO/.forge-home"
test "$CLAUDE_HOME" = "$FORGE_TEST_REPO/.claude-user"
test "$CODEX_HOME" = "$FORGE_TEST_REPO/.codex-user"
```

- [ ] The Terminal is inside the marked walkthrough repository
- [ ] `FORGE_HOME` points at the sandbox
- [ ] `CLAUDE_HOME` points at the sandbox
- [ ] `CODEX_HOME` points at the sandbox

---

## 2. Enable Forge in the Sandbox

### 2.1 Inspect the Answering Installation

<!-- auto -->

```bash
bash "$SCRIPTS/run-in-repo.sh" forge extension doctor --json
```

- [ ] Doctor identifies the Forge launcher and install kind
- [ ] The launcher is reachable on `PATH`
- [ ] Dispatcher status is explicit; accept `current`, and require recovery advice for `missing` or `stale`

### 2.2 Enable User Runtime Hooks

<!-- auto -->

```bash
bash "$SCRIPTS/run-in-repo.sh" forge extension enable --scope user --runtime claude
bash "$SCRIPTS/run-in-repo.sh" forge extension doctor --json
```

- [ ] User-scope Claude enablement exits zero
- [ ] Runtime hooks are registered under the sandboxed Claude user home
- [ ] Post-enable doctor reports a current dispatcher with a usable Forge launcher

### 2.3 Enable Local Project Assets

<!-- auto -->

```bash
bash "$SCRIPTS/run-in-repo.sh" forge extension enable --scope local --root "$FORGE_TEST_REPO" --runtime claude
```

- [ ] Local enablement exits zero
- [ ] Status-line and project assets are installed in the walkthrough repository
- [ ] The pre-existing local settings file remains valid JSON

---

## 3. Understand Extension Ownership

### 3.1 Inspect Both Installation Scopes

<!-- auto -->

```bash
bash "$SCRIPTS/run-in-repo.sh" forge extension status --all --json
```

- [ ] Status reports one user installation and one local installation
- [ ] Both installations report Claude as a tracked runtime
- [ ] Runtime-package health is reported by extension status
- [ ] No native user/project extension path is listed as a target

### 3.2 Inspect the User/Local Split

<!-- auto -->

```bash
bash "$SCRIPTS/run-in-repo.sh" python3 -c '
import json
from pathlib import Path
root = Path.cwd()
user = json.loads((root / ".claude-user/settings.json").read_text())
local = json.loads((root / ".claude/settings.local.json").read_text())
print(json.dumps({
    "user_has_hooks": bool(user.get("hooks")),
    "local_has_status_line": bool(local.get("statusLine")),
    "local_has_custom_env": local.get("env", {}).get("MY_CUSTOM_VAR") == "should-survive-forge",
}))
'
```

- [ ] User scope owns runtime hooks
- [ ] Local scope owns the status line
- [ ] Local scope retains the pre-existing `MY_CUSTOM_VAR`
- [ ] The ownership explanation does not assign runtime hooks to local scope

### 3.3 Verify the Installation Registry

<!-- auto -->

```bash
bash "$SCRIPTS/run-in-repo.sh" python3 -c '
import json
import os
from pathlib import Path
data = json.loads((Path(os.environ["FORGE_HOME"]) / "installed.json").read_text())
installations = data.get("installations")
if not isinstance(installations, dict) or any(not isinstance(row, dict) for row in installations.values()):
    raise SystemExit("unexpected installation registry shape")
rows = list(installations.values())
scopes = [row.get("scope") for row in rows]
if any(not isinstance(scope, str) for scope in scopes):
    raise SystemExit("installation registry row has no scope")
print(json.dumps({"rows": len(rows), "scopes": sorted(set(scopes))}))
'
```

- [ ] The sandbox registry contains the expected tracked installation rows
- [ ] Registry inspection exposes only scope/count facts, not unrelated settings content

---

## 4. Verify the Real System Is Untouched

### 4.1 Compare Protected Path Digests

<!-- auto -->

```bash
bash "$SCRIPTS/run-in-repo.sh" python3 "$SCRIPTS/protected-paths.py" compare .forge/walkthrough/real-system.json
```

- [ ] All six real Claude/Codex targets match the section 0 snapshot
- [ ] The comparison reports labels only and does not print source content

---

## 5. Learn the Command Shape

### 5.1 Inspect the Top-Level CLI

<!-- auto -->

```bash
bash "$SCRIPTS/run-in-repo.sh" forge --help
```

- [ ] Help exposes session, extension, policy, search, and telemetry command groups
- [ ] Read commands and mutating commands use explicit leaf verbs
- [ ] The walkthrough does not depend on exact command or package counts

### 5.2 Distinguish Managed and Bare Launches

<!-- auto -->

```bash
bash "$SCRIPTS/run-in-repo.sh" forge session --help
```

- [ ] Managed `session start|resume` is introduced as the path with manifests and lifecycle state
- [ ] Bare `claude start` and `codex start` are identified as sessionless proxy launchers
- [ ] Continuity, artifacts, search, and session telemetry are attributed only to managed sessions

---

## 6. Choose a Route and Create a Managed Session

### 6.1 Learn Local Health Versus Upstream Validation

<!-- auto -->

These commands are display-only. Ordinary start proves that the local proxy process is healthy. `--smoke-test` also
calls the upstream provider, so it needs credentials and may incur cost.

```
forge proxy start <proxy-id>
forge proxy start <proxy-id> --smoke-test
```

- [ ] The local-health and upstream-connectivity checks are distinguished
- [ ] Neither proxy command is executed by the default walkthrough
- [ ] Provider credentials and a live proxy request remain explicit follow-up work

### 6.3 Create the Direct Managed Parent

<!-- auto -->

```bash
bash "$SCRIPTS/run-in-repo.sh" forge session start walkthrough-demo --model claude-haiku-4-5 --no-proxy --no-launch
```

- [ ] `walkthrough-demo` is created without launching Claude
- [ ] The model alias resolves successfully
- [ ] Direct/no-proxy intent is persisted
- [ ] No model completion is consumed

### 6.4 Inspect Intent Before Launch

<!-- prereq: 6.3 -->

<!-- auto -->

```bash
bash "$SCRIPTS/run-in-repo.sh" forge session model show walkthrough-demo --json
```

- [ ] `route_intent.requested_model` is canonical `claude-haiku-4-5-20251001`
- [ ] `route_intent.kind` is `direct`
- [ ] Intent template and proxy id are null
- [ ] `route_commit` is null before launch
- [ ] The output distinguishes durable intent from runtime evidence

---

## 7. Launch the Managed Parent

### 7.1 Resume the Parent and Check the Status Line

<!-- prereq: 6.4 -->

<!-- human:guided -->

In the sandboxed Terminal, run:

```
forge session resume walkthrough-demo
```

Wait for Claude Code to open. Confirm that the status line names `walkthrough-demo`, then leave this managed child open
for sections 8 and 9.

- [ ] Managed resume opens Claude Code in the walkthrough repository
- [ ] The status line names `walkthrough-demo`
- [ ] The child remains open for direct-command and policy exercises

### 7.3 Verify Hook Confirmation and Route Commitment

<!-- prereq: 7.1 -->

<!-- auto -->

```bash
bash "$SCRIPTS/run-in-repo.sh" forge session show walkthrough-demo --json
bash "$SCRIPTS/run-in-repo.sh" forge session model show walkthrough-demo --json
```

- [ ] `confirmed.confirmed_at` is non-null after launch
- [ ] `confirmed.confirmed_by` begins with `hook:SessionStart:`
- [ ] Routing history is supported and committed evidence is direct
- [ ] The pre-seeded Claude id is treated as correlation data, not launch proof

---

## 8. Use Direct Commands

### 8.1 Inspect Help and the Current Model Route

<!-- prereq: 7.1 -->

<!-- human:guided -->

In the managed Claude session, enter these prompts one at a time:

```
%help
%session model show
```

- [ ] `%help` is intercepted and lists Forge direct commands
- [ ] `%session model show` names `walkthrough-demo`
- [ ] The route output distinguishes requested model from committed direct evidence
- [ ] Neither direct command consumes a model completion

---

## 9. See Policy Intent in Context

### 9.1 Enable the Coding-Standards Bundle

<!-- prereq: 7.1 -->

<!-- auto -->

```bash
bash "$SCRIPTS/run-in-repo.sh" forge policy enable --session walkthrough-demo --bundle coding_standards
```

- [ ] The coding-standards bundle is attached to `walkthrough-demo`
- [ ] Policy enforcement is enabled before the prompted turn
- [ ] The Policy CLI updates the named managed session rather than global config

### 9.2 Ask for a Policy-Conflicting Edit

<!-- prereq: 9.1 -->

<!-- human:guided -->

<!-- paid-operations: 1 -->

In the managed Claude session, enter this one prompted turn:

```
Create src/greeting.py with a function that returns a greeting containing a rocket emoji.
```

Watch for a deny naming the no-emoji rule and its intent. The useful outcomes are a compliant alternative or an explicit
question about the conflict; silently hiding the emoji behind an escape is not compliant.

- [ ] The policy denies an attempted emoji write and names its rule or intent
- [ ] Claude chooses a compliant alternative or asks about the conflict
- [ ] Exactly one intentional model completion is used

---

## 10. Exit, Search, and Inspect Telemetry

### 10.1 Exit the Managed Parent Cleanly

<!-- human:guided -->

In the managed Claude session, type `/exit` and wait until the Terminal prompt returns. This gives the Stop and
SessionEnd hooks time to publish transcript evidence.

- [ ] The managed Claude process exits and the Terminal prompt returns

### 10.2 Verify Transcript Evidence

<!-- prereq: 10.1 -->

<!-- auto -->

```bash
bash "$SCRIPTS/run-in-repo.sh" forge session show walkthrough-demo --json
```

- [ ] `confirmed.transcript_path` is non-null after exit
- [ ] At least one transcript artifact exists for `walkthrough-demo`
- [ ] The transcript evidence is exposed through `session show --json`
- [ ] The evidence belongs to the managed session name used throughout the journey

### 10.4 Rebuild the Search Index

<!-- prereq: 10.2 -->

<!-- auto -->

```bash
bash "$SCRIPTS/run-in-repo.sh" forge search rebuild-index
```

- [ ] Search rebuild reads the published transcript artifacts
- [ ] At least one walkthrough transcript is indexed

### 10.5 Search the Parent Conversation

<!-- prereq: 10.4 -->

<!-- auto -->

```bash
bash "$SCRIPTS/run-in-repo.sh" forge search query emoji --json
```

- [ ] Search returns stable JSON with at least one result
- [ ] A result resolves to `walkthrough-demo`

### 10.7 Inspect Forge Activity

<!-- prereq: 10.2 -->

<!-- auto -->

```bash
bash "$SCRIPTS/run-in-repo.sh" forge telemetry activity walkthrough-demo --period all --json
```

- [ ] The operation-outcomes pane reports the policy interaction when attributable
- [ ] The main interactive Claude harness is not misrepresented as complete model-call telemetry
- [ ] An empty or sparse model-calls pane is explained as honest absence, not zero provider usage

### 10.8 Inspect Proxy-Scoped Costs

<!-- auto -->

```bash
bash "$SCRIPTS/run-in-repo.sh" forge telemetry costs show --period all --json
```

- [ ] The costs command is presented as the authoritative proxy-scoped spend view
- [ ] Direct interactive spend is not invented or attributed to a proxy
- [ ] Empty, zero, or unavailable cost evidence is reported honestly

---

## 11. Continue with Fresh Context

### 11.1 Build and Inspect Structured Transfer Context

<!-- prereq: 10.2 -->

<!-- auto -->

```bash
bash "$SCRIPTS/run-in-repo.sh" forge session transfer regenerate walkthrough-demo --strategy structured
bash "$SCRIPTS/run-in-repo.sh" forge session transfer show walkthrough-demo
```

- [ ] Structured transfer regeneration completes without an AI-curation call
- [ ] Transfer output contains grounded context from the parent conversation
- [ ] The transfer surface is distinguished from project memory

### 11.2 Launch One Fresh Continuation

<!-- prereq: 11.1 -->

<!-- human:guided -->

<!-- paid-operations: 1 -->

In the sandboxed Terminal, launch the named child:

```
forge session resume walkthrough-demo --fresh --child-name walkthrough-continuation --strategy structured
```

When Claude opens, ask one parent-grounded question, such as `Which coding-standard conflict did the parent encounter?`
Confirm the answer uses transferred context, then type `/exit`.

- [ ] A fresh managed child named `walkthrough-continuation` opens
- [ ] The child receives structured parent context
- [ ] One grounded answer demonstrates continuity
- [ ] The child exits cleanly after exactly one intentional completion

### 11.3 Inspect the Child Relationship

<!-- prereq: 11.2 -->

<!-- auto -->

```bash
bash "$SCRIPTS/run-in-repo.sh" forge session show walkthrough-continuation --json
```

- [ ] The child names `walkthrough-demo` as its parent
- [ ] The child has its own confirmed runtime evidence
- [ ] The child transcript is separate from the frozen transfer snapshot
- [ ] The parent remains available after the child exits

### 11.4 Remove the Continuation

<!-- prereq: 11.3 -->

<!-- auto -->

```bash
bash "$SCRIPTS/run-in-repo.sh" bash -c \
  'CLAUDE_HOME="$FORGE_WALKTHROUGH_CLAUDE_CONFIG_DIR" forge session delete walkthrough-continuation --yes --force'
```

- [ ] The continuation session is removed
- [ ] The parent session and its transcript remain

### 11.5 Orient Project Memory as Further Reading

<!-- auto -->

```bash
bash "$SCRIPTS/run-in-repo.sh" forge memory --help
bash "$SCRIPTS/run-in-repo.sh" forge session memory report --help
```

- [ ] Project memory is described as curated project-lifetime documentation
- [ ] Session transfer is described as per-session continuation context
- [ ] Current memory passport and report commands are shown without editing a document

### 11.6 Prove Incognito Ephemerality

<!-- auto -->

```bash
bash "$SCRIPTS/run-in-repo.sh" bash -c '
set -euo pipefail
fixture="$FORGE_TEST_REPO/.forge/walkthrough/noop-bin"
cleanup() { rm -rf "$fixture"; forge session delete walkthrough-incognito --yes --force >/dev/null 2>&1 || true; }
trap cleanup EXIT
rm -rf "$fixture"
mkdir -p "$fixture"
printf "%s\\n" "#!/usr/bin/env bash" "if [ \"\${1:-}\" = --version ]; then echo \"2.1.245 (walkthrough fixture)\"; fi" "exit 0" > "$fixture/claude"
chmod +x "$fixture/claude"
PATH="$fixture:$PATH" forge session incognito walkthrough-incognito --no-proxy
if forge session list --include-incognito --json | grep -q walkthrough-incognito; then exit 1; fi
test ! -d .forge/sessions/walkthrough-incognito
'
```

- [ ] The no-op launcher exits without a model completion
- [ ] The incognito session is absent from the session index
- [ ] No incognito session directory remains
- [ ] The disposable launcher is removed even if the block aborts

---

## 12. Optional Runtime Chapters

### 12.1 Prepare Sidecar Prerequisites

<!-- auto -->

<!-- option: sidecar -->

<!-- requires: docker -->

<!-- requires: openrouter-auth -->

```bash
bash "$SCRIPTS/run-in-repo.sh" --no-cd docker info --format '{{.ServerVersion}}'
bash "$SCRIPTS/run-in-repo.sh" --no-cd docker image inspect "$SIDECAR_IMAGE" --format '{{.Id}}'
bash "$SCRIPTS/run-in-repo.sh" bash -c '
set -euo pipefail
proxy_id=walkthrough-sidecar-proxy
proxy_dir="$FORGE_HOME/proxies/$proxy_id"
if [ -e "$proxy_dir" ] || [ -L "$proxy_dir" ]; then
  test -d "$proxy_dir"
  test ! -L "$proxy_dir"
  forge proxy validate "$proxy_id"
  forge proxy start "$proxy_id"
else
  forge proxy create openrouter-anthropic --name "$proxy_id" --json
fi
forge proxy show "$proxy_id" --json | python3 -c '\''import json,sys; row=json.load(sys.stdin); assert row["proxy_id"] == "walkthrough-sidecar-proxy"; assert row["template"] == "openrouter-anthropic"'\''
'
```

- [ ] The selected sidecar chapter can reach Docker and the configured image
- [ ] OpenRouter auth is configured without exposing its value
- [ ] A healthy fixed-id `walkthrough-sidecar-proxy` uses the packaged `openrouter-anthropic` template
- [ ] Default runs do not probe Docker or provider auth

### 12.4 Launch a Sidecar Session

<!-- prereq: 12.1 -->

<!-- human:guided -->

<!-- option: sidecar -->

In the sandboxed Terminal, run the following and leave the child open:

```
forge session start walkthrough-sidecar --sidecar --proxy walkthrough-sidecar-proxy
```

- [ ] The managed sidecar child opens through the packaged OpenRouter template
- [ ] The child remains running for the automated mount observation

### 12.5 Observe the Container Boundary

<!-- prereq: 12.4 -->

<!-- auto -->

<!-- option: sidecar -->

<!-- requires: docker -->

```bash
bash "$SCRIPTS/run-in-repo.sh" --no-cd docker ps --filter name=forge-walkthrough-sidecar --format '{{.Names}} {{.Status}}'
bash "$SCRIPTS/run-in-repo.sh" forge session show walkthrough-sidecar --json
```

- [ ] The walkthrough-owned sidecar container is running
- [ ] The managed session reports sandboxed execution
- [ ] The project is mounted at the documented container workspace

### 12.7 Exit the Sidecar Session

<!-- prereq: 12.5 -->

<!-- human:guided -->

<!-- option: sidecar -->

<!-- requires: docker -->

In the sidecar child, type `/exit` and wait for the sandboxed Terminal prompt to return.

- [ ] The sidecar child exits
- [ ] Its walkthrough-owned container stops or auto-removes

### 12.8 Check Direct Codex Readiness

<!-- auto -->

<!-- option: codex -->

```bash
bash "$SCRIPTS/run-in-repo.sh" forge runtime preflight codex --json
```

- [ ] Preflight checks native-direct Codex without a proxy
- [ ] `proxy_responses` is reported as `native_direct`
- [ ] Hook registration/enrollment is reported separately from headless readiness
- [ ] Ready proceeds; not-ready prints an exact recovery without claiming success
- [ ] Native stored Codex auth remains invisible to the isolated Codex home

### 12.9 Run One Headless Codex Continuation

<!-- prereq: 12.8 -->

<!-- auto -->

<!-- option: codex -->

<!-- requires: codex-ready -->

<!-- paid-operations: 1 -->

```bash
bash "$SCRIPTS/run-in-repo.sh" forge session start walkthrough-codex --runtime codex --resume-from walkthrough-demo --strategy structured --context-delivery initial-message --task "In one sentence, name the coding-standard conflict in the parent context."
bash "$SCRIPTS/run-in-repo.sh" forge session show walkthrough-codex --json
```

- [ ] Context delivery is explicitly `initial-message`
- [ ] One headless Codex turn completes without an enrollment probe
- [ ] The managed session records a Codex thread id and response evidence
- [ ] Auth and rollout state remain inside the sandboxed Codex home
- [ ] The optional branch consumes at most one model completion

---

## 13. Clean Up Safely

### 13.1 Review the Cleanup Plan

<!-- human:confirm -->

Review the owned resources before cleanup: `walkthrough-demo`, any continuation/incognito/Codex/sidecar sessions,
`walkthrough-sidecar-proxy`, the walkthrough sidecar container, the sandbox's user/local installation rows and isolated
project-trust registry, generated transfer/search/artifact state, `src/greeting.py`, and sandbox Codex auth/rollouts.
Cleanup must preserve foreign resources and the six real-system targets.

- [ ] The cleanup targets are confined to the marked walkthrough repository and its tracked sandbox rows
- [ ] Reports are saved outside the sandbox before destructive cleanup
- [ ] The user approves cleanup

### 13.2 Remove Walkthrough Runtime State

<!-- prereq: 13.1 -->

<!-- auto -->

```bash
WALKTHROUGH_SIDECAR_MAY_EXIST="$SIDECAR_MAY_EXIST" bash "$SCRIPTS/run-in-repo.sh" bash "$SCRIPTS/cleanup-owned.sh" runtime
```

- [ ] All walkthrough-owned managed sessions are absent or removed
- [ ] The fixed-id walkthrough sidecar proxy is absent or removed
- [ ] The walkthrough-owned sidecar container is absent or removed
- [ ] Transcript, structured-transfer, and search state owned by this walkthrough is removed
- [ ] Missing resources are treated as idempotent success
- [ ] No foreign session, container, proxy, or listener is targeted

### 13.3 Disable Sandbox Extensions and Remove Copied Auth

<!-- prereq: 13.1 -->

<!-- auto -->

```bash
bash "$SCRIPTS/run-in-repo.sh" bash "$SCRIPTS/cleanup-owned.sh" extensions
```

- [ ] Local project assets are removed or already absent
- [ ] User-scope Claude runtime hooks are removed or already absent, and isolated project trust is cleared
- [ ] Sandboxed Codex auth and rollout state is removed and its private home is recreated empty
- [ ] Pre-existing unrelated local settings remain intact
- [ ] The walkthrough-owned `src/greeting.py` is absent

### 13.4 Verify Preservation and Repeatability

<!-- prereq: 13.2, 13.3 -->

<!-- auto -->

```bash
bash "$SCRIPTS/run-in-repo.sh" python3 "$SCRIPTS/protected-paths.py" compare .forge/walkthrough/real-system.json
bash "$SCRIPTS/run-in-repo.sh" bash -c '
set -euo pipefail
for session_name in \
    walkthrough-codex \
    walkthrough-sidecar \
    walkthrough-continuation \
    walkthrough-incognito \
    walkthrough-demo; do
    test ! -e ".forge/sessions/$session_name"
    test ! -e ".forge/artifacts/$session_name"
    test ! -e ".forge/prev_sessions/$session_name"
done
python3 - << "PY"
import json
from pathlib import Path

owned = {
    "walkthrough-codex",
    "walkthrough-sidecar",
    "walkthrough-continuation",
    "walkthrough-incognito",
    "walkthrough-demo",
}
documents_path = Path(".forge/search-index/documents.json")
if documents_path.exists():
    documents = json.loads(documents_path.read_text(encoding="utf-8")).get("documents")
    assert isinstance(documents, list)
    assert all(isinstance(row, dict) and row.get("session_name") not in owned for row in documents)
PY
test ! -e "$FORGE_HOME/projects.json"
test ! -e "$CODEX_HOME/auth.json"
test -d "$CODEX_HOME"
test "$(find "$CODEX_HOME" -mindepth 1 -print -quit)" = ""
python3 -c "import os,stat; assert stat.S_IMODE(os.stat(os.environ[\"CODEX_HOME\"]).st_mode) == 0o700"
test ! -e src/greeting.py
test "$(git status --porcelain -- src/greeting.py)" = ""
python3 -c "import json; d=json.load(open(\".claude/settings.local.json\")); assert d[\"env\"][\"MY_CUSTOM_VAR\"] == \"should-survive-forge\""
'
```

- [ ] All six real-system protected targets still match the baseline
- [ ] All fixed-name walkthrough session directories are absent
- [ ] Walkthrough-owned transcript, transfer, and search state are absent while foreign project state is preserved
- [ ] The sandboxed Codex home is empty and private, and its Forge project-trust registry is absent
- [ ] The pre-existing local setting survives
- [ ] The walkthrough-owned source fixture is absent
- [ ] Re-running section 13 is safe and produces no new mutation
