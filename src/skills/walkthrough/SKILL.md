---
name: walkthrough
description: Interactive Forge Day 1 walkthrough in a hermetic test environment. Use after installing or upgrading Forge to learn the managed-session workflow and verify the installation.
disable-model-invocation: true
argument-hint: '[--setup-only] [--reset] [--report] [--from <id>] [--codex] [--codex-auth <path>] [--sidecar]'
allowed-tools: Read, Bash, Glob  # AskUserQuestion is intentionally omitted because declaring it can trigger Claude Code auto-approval behavior. It remains available for checkpoints.
---

# Walkthrough

Teach Forge's Day 1 managed-session loop in an isolated repository. Session A is the guide. The user opens one sandboxed
Terminal and launches one managed Claude child from it. Codex and sidecar are optional subjects under test; this skill
remains a Claude-hosted frontend.

## Usage

```text
/walkthrough
/walkthrough --setup-only
/walkthrough --reset --report
/walkthrough --from 10.2 --report
/walkthrough --codex
/walkthrough --codex --codex-auth ~/.codex/auth.json
/walkthrough --sidecar
```

| Argument              | Meaning                                                                                                           |
| --------------------- | ----------------------------------------------------------------------------------------------------------------- |
| `--setup-only`        | Create the sandbox, prove all wrapper gates, record package identity, then stop.                                  |
| `--reset`             | Reclaim walkthrough-owned state and recreate the sandbox baseline before a fresh run.                             |
| `--report`            | Preserve identity, state, selected options, outputs, logs, metrics, and a transcript claim outside cleanup scope. |
| `--from <id>`         | Resume an existing run after validating its prefix; accepts a section or exact step id.                           |
| `--codex`             | Select the optional direct Codex chapter.                                                                         |
| `--codex-auth <path>` | On a fresh Codex run, copy exactly one auth file into the isolated Codex home.                                    |
| `--sidecar`           | Select the optional Docker sidecar chapter.                                                                       |

The default journey has exactly seven human checkpoints and two intentional model completions. Its hard ceiling is eight
checkpoints and three completions; selected optional chapters report their additions separately. A duration over 30
minutes is review evidence, not an automatic failure.

## Non-negotiable Safety Rules

1. Resolve resources from `CLAUDE_SKILL_DIR`. Never substitute checkout copies.
2. `setup-test-repo.sh` is the only mutation allowed before the wrapper proves the sandbox.
3. After setup, every Forge or sandbox-mutating command run by Session A goes through packaged `run-in-repo.sh`. Pure
   reads of packaged resources and writes to the validated host report directory may run directly.
4. Bare `forge` is allowed only in the user's Terminal after step 1.1 proves the marker, current directory, and all
   three isolated homes.
5. Never print credential values, inspect native Codex auth implicitly, or put an auth source path/copy in state,
   reports, step logs, or debug snapshots.
6. Cleanup section 13 stays selected after success, failure, skipped optional infrastructure, or resume.
7. Stop on parser/state errors. Never hand-edit progress to make a run continue.

## 1. Parse Arguments Before Mutation

Interpret `$ARGUMENTS` as the flags above. Reject, before running setup:

- unknown arguments;
- duplicate flags or duplicate values;
- a missing value for `--from` or `--codex-auth`;
- `--codex-auth` without `--codex`;
- `--from` with `--reset` or `--setup-only`;
- a non-regular `--codex-auth` source on a fresh run.

Track booleans `SETUP_ONLY`, `RESET`, `REPORT`, `CODEX`, and `SIDECAR`, plus optional `FROM_STEP` and
`CODEX_AUTH_SOURCE`. The canonical coverage identity is exactly:

```text
codex=<true|false>,sidecar=<true|false>
```

Adding `--report` does not change coverage identity.

Tell the user the shape of the selected journey: Session A guides, one sandboxed Terminal hosts the managed Claude
child, and additional windows exist only when sidecar is selected. Do not describe a bare launcher as managed.

## 2. Resolve Packaged Paths and Host Artifacts

```bash
SCRIPTS="${CLAUDE_SKILL_DIR}/scripts"
CHECKLIST="${CLAUDE_SKILL_DIR}/resources/checklist.md"
JOURNEY_MAP="${CLAUDE_SKILL_DIR}/resources/journey-map.md"
SETUP_SCRIPT="$SCRIPTS/setup-test-repo.sh"
FORGE_TEST_REPO="${FORGE_TEST_REPO:-${FORGE_HOME:-$HOME/.forge}/manual-testing/walkthrough/test-repo}"
```

Resolve `FORGE_TEST_REPO` to an absolute canonical path before displaying it. State lives at
`$FORGE_TEST_REPO/.forge/walkthrough/progress.json`.

Host-side artifacts live outside the sandbox:

```text
${FORGE_HOME:-$HOME/.forge}/manual-testing/walkthrough/runs/<UTC timestamp>/
```

Set `WT_STATE_DIR=${FORGE_HOME:-$HOME/.forge}/manual-testing/walkthrough`. For `--report`, choose `WT_RUN_DIR` as a new
UTC-timestamped path under `$WT_STATE_DIR/runs/` without deleting older runs, but do not create it before the wrapper
proof. Set `RUN_STARTED_EPOCH` before setup. After the wrapper succeeds, create the run directory and its `step-logs/`
and `forge-logs/pre-clean/` children. Keep final report files there. Never use a sandbox path as the report root.

## 3. Fresh Setup, Setup-only, or Resume

### Fresh run

Before invoking setup, inspect only whether the canonical target already exists and carries the walkthrough marker. If
it does and `--reset` was not supplied, explain that a fresh setup would replace its progress/auth baseline and ask
whether to reclaim it with reset or stop. Do not call setup, inspect target-controlled files, or silently discard state
before that choice. An unmarked existing target is never eligible for reset.

Build setup arguments from the approved `--reset` and `--codex-auth`, then run the packaged setup script. Reset must
reclaim tracked installations and managed sessions through the wrapper before discarding their evidence. Candidate wheel
installation and extension sync happen beforehand from a normal shell, never from the walkthrough Terminal with its
isolated `FORGE_HOME`. Setup refuses before cleanup if that isolated registry contains any installation other than the
walkthrough's own user row and local sandbox row, or if either row records a mode, runtime, or target outside its
sandbox boundary; do not delete the registry to bypass this ownership failure.

After setup, prove all six wrapper gates with:

```bash
bash "$SCRIPTS/run-in-repo.sh" true
```

Record package identity using the installed skill package, never the checkout:

```bash
python3 "$SCRIPTS/package-identity.py" --skill-root "$CLAUDE_SKILL_DIR"
```

The identity command must report both `package_tree_matches_marker: true` and
`package_matches_answering_distribution: true`. This rejects a coherent but stale installed skill package. In report
mode save the exact JSON as `package-identity.json`. If `answering_distribution_issue` is `editable-install`, stop and
explain that the candidate wheel must be installed, its extension package synced, and Claude restarted with that wheel's
launcher first on `PATH`. Never substitute checkout resources for this release-candidate gate. A
`walkthrough-payload-missing` issue requires reinstalling the candidate wheel rather than continuing.

If `--setup-only` was selected, stop here. Do not initialize checklist state, enable extensions, probe a runtime, or run
a checklist step.

For a normal fresh run, initialize state with `--force` through `run-in-repo.sh`, then record these variables through
the same wrapper with `walkthrough-state.py var`:

```bash
bash "$SCRIPTS/run-in-repo.sh" python3 "$SCRIPTS/walkthrough-state.py" "$CHECKLIST" init "$STATE_FILE" --force
```

- `RUN_SCOPE`: a fresh UUID;
- `RUN_OPTIONS`: the canonical coverage identity;
- `RUN_STARTED_EPOCH`;
- `CODEX_AUTH_MODE`: read only `FORGE_WALKTHROUGH_CODEX_AUTH_MODE` through the wrapper;
- `DECLARED_HUMAN_CHECKPOINTS=7`;
- `DECLARED_PAID_OPERATIONS=2`;
- `HUMAN_CHECKPOINTS_OBSERVED=0`;
- `PAID_OPERATIONS_OBSERVED=0`;
- `SIDECAR_MAY_EXIST=false`.

### Resume with `--from`

Do not run setup and do not initialize with `--force`. Require the existing marker, wrapper, and state file. Read
`RUN_OPTIONS` and refuse if it differs from the requested Codex/sidecar selection. Name `/walkthrough --reset` as the
recovery.

Validate preserved Codex ingress before any checklist command:

- `explicit-file`: `$CODEX_HOME/auth.json` must remain one regular file, mode `0600`, beneath a mode-`0700`
  `$CODEX_HOME`; competing Codex key/token variables remain scrubbed by generated `env.sh`;
- `environment`: `CODEX_API_KEY` or `CODEX_ACCESS_TOKEN` must still resolve in the wrapper environment;
- `none`: no auth file is imported from native `$HOME/.codex`.

The user does not need to re-supply the original auth source on resume. If `--codex-auth` is present, use it only to
confirm the stored mode was `explicit-file`; do not recopy or record its path.

First prove the wrapper:

```bash
bash "$SCRIPTS/run-in-repo.sh" true
```

For `--report`, after the wrapper proof and before validation, generate a new identity file for this resumed run rather
than expecting it in the new timestamped directory:

```bash
python3 "$SCRIPTS/package-identity.py" --skill-root "$CLAUDE_SKILL_DIR" > "$WT_RUN_DIR/package-identity.json"
```

Require both identity booleans to be true exactly as for a fresh run. Stop before checklist execution if the command
fails or its identity does not match the answering distribution.

Then validate the resume point:

```bash
bash "$SCRIPTS/run-in-repo.sh" python3 "$SCRIPTS/walkthrough-state.py" "$CHECKLIST" validate "$STATE_FILE" --from "$FROM_STEP"
```

Append `--report` to the validation command when report mode is active. The validator combines that active selection
with the persisted `RUN_OPTIONS`, so any continuation it prints retains `--codex`, `--sidecar`, and `--report` as
applicable.

`status: refused` exits non-zero and leaves state byte-identical. Stop and show its exact `recovery` value. A requested
resume point that skips otherwise valid unrecorded prefix steps names `first_unrecorded_step` and recovers with that
step plus the original active options. Changed, unverifiable, or orphaned evidence recovers through
`/walkthrough --reset`. Structurally malformed state instead reports `recovery_kind: manual-state-inspection`. Never
recommend or invoke reset for this refusal, because reset deliberately refuses malformed ownership evidence. Leave that
sandbox unchanged, show `recovery_state_path`, and offer either manual inspection/preservation or setting
`FORGE_TEST_REPO` to a different empty path and running `alternate_fresh_command`. Do not choose a replacement path or
abandon the old sandbox on the user's behalf. `status: ok` preserves verified prefix evidence and clears only the
selected suffix. Keep the original start time and observed counters.

## 4. Optional Infrastructure Selection

Do not probe Docker or Codex in a default run.

When `--sidecar` is selected, resolve `sidecar_image` through a wrapped Forge config read, then probe the Docker daemon
and exact image through `run-in-repo.sh --no-cd`. Also inspect `forge auth status --json` through the wrapper for a
configured `openrouter` credential without printing its secret. Store `SIDECAR_IMAGE`, `INFRA_DOCKER=true|false`, and
`INFRA_OPENROUTER_AUTH=true|false`. Missing Docker, image, or OpenRouter auth makes the sidecar chapter unavailable; it
does not alter default results.

Immediately before presenting selected step 12.4, set `SIDECAR_MAY_EXIST=true` through the wrapped state `var` command.
Do not set it merely because `--sidecar` was selected or because step 12.1 was unavailable. Keep it true until cleanup
passes, so interruption after the launch prompt remains conservative.

Codex readiness is evaluated by checklist step 12.8, not during setup. Capture its JSON even when preflight exits
non-zero. Store `INFRA_CODEX_READY=true` only for a genuine ready result. Do not use `--proxy`, `--verify-enrollment`,
or hook delivery. Initial-message delivery deliberately does not require trust enrollment.

## 5. Build and Execute the Checklist

Parse the index once:

```bash
python3 "$SCRIPTS/walkthrough-state.py" "$CHECKLIST" index
```

For each step, fetch its details with `step <id>`. The parser owns IDs, annotations, code blocks, assertions, and
prerequisites; do not count Markdown manually.

### Selection order

1. Read `annotations[]` from the step result.
2. An `option: codex` or `option: sidecar` step is selected only by that flag. If not selected, label it `not selected`,
   record every assertion as `s`, and do not inspect its infrastructure.
3. For selected steps, map `requires: docker`, `requires: openrouter-auth`, and `requires: codex-ready` to
   `INFRA_DOCKER`, `INFRA_OPENROUTER_AUTH`, and `INFRA_CODEX_READY`. Missing infrastructure is `unavailable`, records
   `s`, and includes the exact recovery.
4. Run `prereq-check`. A failed, skipped, stale, or unrecorded prerequisite blocks the step and records `s`.
5. Section 13 remains selected despite failures or optional-chapter fallout. Its internal prerequisites still apply:
   never run steps 13.2 or 13.3 unless the user passed cleanup approval at 13.1.

### Execution classes

| Annotation      | Behavior                                                                                                  |
| --------------- | --------------------------------------------------------------------------------------------------------- |
| `auto`          | Run each runnable Bash block as one Bash call. Classify every assertion from output and durable evidence. |
| `human:guided`  | Show all instructions and display-only blocks first, then ask the user to perform/observe them.           |
| `human:confirm` | Show the complete plan first and ask for approval before any destructive follow-up step.                  |

`option:`, `requires:`, and `paid-operations:` are modifiers, not execution classes. Unknown annotations are a driver
error. Walkthrough ownership is documented in `journey-map.md`; do not interpret QA `evidence:` lanes here.

Before every human question, print the full action, expected observations, one short buffer line, and at least three
blank lines so the dialog does not hide instructions. Offer context-appropriate `Done/Pass`, `Fail`, `Skip`, and stop
choices. Increment `HUMAN_CHECKPOINTS_OBSERVED` only when a selected checkpoint is actually presented. Increment
`PAID_OPERATIONS_OBSERVED` only when an annotated completion is actually attempted.

Record exactly one result per assertion:

```bash
bash "$SCRIPTS/run-in-repo.sh" python3 "$SCRIPTS/walkthrough-state.py" "$CHECKLIST" record "$STATE_FILE" <id> <p,f,s,...>
```

Never convert an unverified assertion into a pass. A non-zero automatic command normally fails its affected assertions;
step 12.8 is the sole compatibility exception because an actionable not-ready result is its asserted outcome. Continue
toward cleanup after ordinary failures unless doing so would be unsafe.

### Command execution and evidence

- Substitute only `$SCRIPTS`, `$SETUP_SCRIPT`, `$FORGE_TEST_REPO`, `$SIDECAR_IMAGE`, and state variables named by the
  checklist.
- Runnable blocks containing Forge or mutation already begin with `run-in-repo.sh`; do not strip the wrapper.
- Non-`bash` fences are display-only.
- Save raw stdout/stderr for each selected step as `<run-dir>/step-logs/<id>.log` in report mode. Redact nothing by
  copying credentials in the first place; if output unexpectedly contains a secret, stop artifact publication and report
  the leak.
- Use stable CLI surfaces for lifecycle evidence. A pre-seeded Claude UUID does not prove launch; require
  `confirmed_at`, `confirmed_by=hook:SessionStart:*`, status-line observation, and later transcript evidence.
- Before launch, route intent is canonical and `route_commit` is null. After managed resume, require supported direct
  committed evidence.
- The policy prompt and fresh-continuation prompt are the only two default paid operations.

## 6. Cleanup and Interruption

Before presenting step 13.1 in report mode, copy the current progress file, selected option facts, package identity,
step logs, and sandbox Forge logs into the host run directory. Do not copy `$CODEX_HOME`, `env.sh`, credential
environment, settings contents, or auth material.

After cleanup, copy final logs and state again. If a user stops before section 13, clearly say owned resources remain.
Use the ordered checklist index and recorded state to identify the first unrecorded step, then offer either continuation
with `--from <first-unrecorded-step>` while retaining the active `--codex`, `--sidecar`, and `--report` selections, or
`/walkthrough --reset`. If every step before section 13 is recorded, section 13 is that continuation point. Reset must
reclaim resources before it discards their manifests; if ownership cannot be proven, it refuses rather than guessing.

Cleanup is idempotent and names only walkthrough-owned sessions, `walkthrough-sidecar-proxy`, and the exact walkthrough
sidecar container. Missing owned resources are success. Foreign same-port proxies, containers, sessions, listeners, and
installation rows are never cleanup targets. The isolated `projects.json` grants hook trust but owns no checkout files:
after a strict read, extension cleanup deletes that complete sandbox registry without touching any enrolled root. A
malformed or non-regular registry refuses before runtime cleanup. A valid standalone dispatcher may remain, so step 2.1
accepts `current` and requires recovery only when doctor reports `missing` or `stale`. Disposable fake binaries register
an `EXIT` trap immediately after their path is chosen.

## 7. Summary and Report

Always obtain structural results from:

```bash
python3 "$SCRIPTS/walkthrough-state.py" "$CHECKLIST" report "$STATE_FILE"
```

In report mode, after section 13 is recorded, build deterministic metrics and report files with:

```bash
python3 "$SCRIPTS/walkthrough-report.py" \
  --checklist "$CHECKLIST" \
  --parser "$SCRIPTS/walkthrough-state.py" \
  --state "$STATE_FILE" \
  --package-identity "$WT_RUN_DIR/package-identity.json" \
  --output-dir "$WT_RUN_DIR" \
  --ended-epoch "$(date +%s)"
```

Render per-section pass/fail/skip counts, then separately state:

- selected options;
- default failures, unavailable steps, and missing steps;
- each selected optional chapter's `pass`, `fail`, `unavailable`, or `incomplete` compatibility status;
- optional steps omitted as `not selected`;
- human checkpoints observed versus the seven-checkpoint default and any selected optional ceiling;
- paid operations observed versus the two-operation default and any selected optional ceiling;
- package-tree identity;
- elapsed seconds and whether the 1,800-second review threshold was crossed.

Pass requires every default assertion to pass, no default gaps, valid observed counts, exact package-tree identity, and
successful cleanup. Optional Codex/sidecar failures or unavailable infrastructure are reported as compatibility evidence
without changing the default verdict. Not-selected optional assertions are excluded. Duration overage changes only
`duration_review_required`.

For `--report`, save:

```text
report.md
run-metrics.json
state.json
selected-options.json
package-identity.json
step-logs/
forge-logs/pre-clean/
forge-logs/final/
```

Generate a transcript claim token and write the marker so only this Session A transcript can be copied after it ends:

```bash
TRANSCRIPT_TOKEN="forge-walkthrough-transcript-token:$(python3 - <<'PY'
import uuid
print(uuid.uuid4())
PY
)"
python3 - <<'PY' "$WT_RUN_DIR" "$WT_STATE_DIR/.pending-transcript" "$TRANSCRIPT_TOKEN"
import json
import os
import sys
from pathlib import Path

run_dir, marker_path, token = sys.argv[1:4]
marker = Path(marker_path)
marker.parent.mkdir(parents=True, exist_ok=True)
temporary = marker.with_suffix(".tmp")
temporary.write_text(
    json.dumps({"run_dir": run_dir, "transcript_contains": token}) + "\n",
    encoding="utf-8",
)
os.replace(temporary, marker)
PY
```

Tell the user that the Session A transcript will be attached only after this walkthrough session ends, and print the
claim token in the final message so it appears in that transcript. The marker contains the run directory and random
claim token, never auth facts.

End with current follow-ups: `/smoke-test` for a quick non-interactive check, `/qa` for containerized release QA, and
the session, transfer, model-selection, memory, and manual-testing guides for deeper paths.

## Wrapper Safety Gates

`run-in-repo.sh` canonicalizes and deny-lists unsafe roots before it sources target-controlled code, then proves:

1. generated `env.sh` exists;
2. the walkthrough marker exists;
3. `FORGE_HOME` is the sandbox `.forge-home`;
4. `CLAUDE_HOME` is the sandbox `.claude-user`;
5. `CODEX_HOME` is the sandbox `.codex-user`;
6. `.forge/walkthrough/` and `CLAUDE.md` establish the generated repository.

Any gate failure stops the run. Never weaken or bypass a gate to finish a walkthrough.

The sandbox also puts its generated `claude` shim first on `PATH`. The shim invokes the native Claude binary recorded at
setup, excludes the real user settings source, and loads `$CLAUDE_HOME/settings.json` explicitly. Native Claude auth and
transcript storage remain in the captured `CLAUDE_CONFIG_DIR` (normally `~/.claude`); cleanup redirects Forge's
native-transcript deletion there only for the fixed walkthrough parent and continuation.
