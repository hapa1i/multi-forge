---
name: forge:walkthrough
description: Interactive Forge verification walkthrough in a hermetic test environment. Use after installing or upgrading Forge to verify everything works.
disable-model-invocation: true
argument-hint: '[--setup-only] [--reset] [--report] [--sidecar]'
allowed-tools: Read, Bash, Glob  # AskUserQuestion deliberately omitted — listing it triggers CC auto-approve bug (github.com/anthropics/claude-code/issues/29547). The tool remains available; omitting it preserves the interactive dialog.
---

# Walkthrough

Interactive verification of Forge installation and features in an isolated test environment. Your real `~/.claude/` is
never touched.

## Usage

```
/forge:walkthrough                   Interactive walkthrough (default)
/forge:walkthrough --setup-only      Create/reset test repo, then stop
/forge:walkthrough --reset           Reset test repo to clean baseline
/forge:walkthrough --report          Save run artifacts (report, state, logs, transcript)
/forge:walkthrough --sidecar         Include sidecar section (requires Docker)
```

## Arguments

| Argument       | Description                                                                                                                  |
| -------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| `--setup-only` | Create or reset the test repo and generate env.sh, then stop.                                                                |
| `--reset`      | Reset test repo to clean baseline before running.                                                                            |
| `--report`     | Save report, state, step logs, Forge debug logs, and transcript marker to a timestamped run directory after the walkthrough. |
| `--sidecar`    | Include sidecar section (section 12). Requires Docker + sidecar image.                                                       |

## Execution

Follow these steps in order. Do not skip steps.

### Step 1: Parse Arguments and Route

Parse `$ARGUMENTS` to extract flags: `--setup-only`, `--reset`, `--report`, `--sidecar`. Track them as booleans
(`SETUP_ONLY`, `RESET`, `REPORT`, `SIDECAR`) for later phases.

**Greet the user:**

"I'll walk you through a functional verification of Forge in an isolated test environment. This is **Session A** — we
work together here. I run automated checks, you watch and ask questions. Later, I'll ask you to open a **Terminal** for
hands-on commands, and then launch **Session B** — a separate Claude Code instance where you experiment with Forge
features (hooks, status line, % commands) while I stay here to guide you. I'll install Forge extensions into a hermetic
sandbox, verify your real `~/.claude/` was not touched, then clean up."

If `--setup-only`: "I'll create the isolated test environment and stop -- no tests will run."

If `--report`: add "I'll also capture raw step output plus sandbox Forge debug logs and save them with the report when
we finish."

### Step 2: Walkthrough Mode

The walkthrough is a **checklist-driven** interactive demo. You read `checklist.md` section by section, run commands
through `run-in-repo.sh`, and check assertions. The checklist defines what to run and check; you provide educational
narration and handle user interactions.

**Safety rule:** ALL `forge` CLI invocations MUST go through `run-in-repo.sh` -- even seemingly read-only ones like
`forge info` can write caches or state files to the real system. Only pure filesystem reads (`ls`, `cat`, `stat`,
`python3` for reading files, the Read tool) are safe to run directly. NEVER construct raw `forge` commands outside the
wrapper.

#### Phase 1: Setup

**Set the setup script** from the skill's own location:

```bash
SETUP_SCRIPT="${CLAUDE_SKILL_DIR}/scripts/setup-test-repo.sh"
```

**Handle special modes** before proceeding:

- `--setup-only`: run `bash "$SETUP_SCRIPT"` (add `--reset` if that flag is also set), print the env file path, and
  stop. No checklist execution.
- `--reset` (without `--setup-only`): run `bash "$SETUP_SCRIPT" --reset`, then continue to the walkthrough.

**Set the scripts directory** from the skill's own location:

```bash
SCRIPTS="${CLAUDE_SKILL_DIR}/scripts"
```

**Resolve `$FORGE_TEST_REPO`**: use the env var if set, otherwise default to
`~/.forge/manual-testing/walkthrough/test-repo` (or `$FORGE_HOME/manual-testing/walkthrough/test-repo` if `FORGE_HOME`
is set).

**Check for stale install artifacts**: If `$FORGE_TEST_REPO/.claude/commands/` exists (leftover from a previous run),
ask the user: "Previous walkthrough artifacts detected. Reset the test repo?" If yes, run
`bash "$SETUP_SCRIPT" --reset`.

The setup script already scrubs walkthrough-derived volatile state on reruns (`.forge/artifacts/`,
`.forge/search-index/`, and `.forge-home/logs`), so a full reset is only needed when installed extensions or repo
contents drift.

**Ensure test repo exists** (for Phase 2 state init):

```bash
# First run: create the test repo (Section 0.2 will re-run idempotently with tracked assertions)
# Re-run: setup script preserves the repo baseline and scrubs volatile walkthrough state
if [ ! -f "$FORGE_TEST_REPO/.forge-walkthrough-marker" ]; then
  bash "$SETUP_SCRIPT"
fi
mkdir -p "$FORGE_TEST_REPO/.forge/walkthrough"
```

**Resolve host-side walkthrough artifact paths**. These live outside the sandboxed `FORGE_HOME` used by
`run-in-repo.sh`, so reports from Session A stay under the user's normal manual-testing directory:

```bash
WT_STATE_DIR_RAW="${FORGE_HOME:-$HOME/.forge}/manual-testing/walkthrough"
WT_STATE_DIR=$(python3 -c 'import os,sys; print(os.path.abspath(os.path.expanduser(os.path.expandvars(sys.argv[1]))))' "$WT_STATE_DIR_RAW")
WT_STEP_LOGS_DIR="$WT_STATE_DIR/logs"
WT_FORGE_LOG_SNAPSHOTS="$WT_STATE_DIR/forge-logs-snapshots"
```

If `--report` was passed, clear any previous run-local step logs / snapshots before execution:

```bash
if [ "$REPORT" = true ]; then
  rm -rf "$WT_STEP_LOGS_DIR" "$WT_FORGE_LOG_SNAPSHOTS"
  mkdir -p "$WT_STEP_LOGS_DIR" "$WT_FORGE_LOG_SNAPSHOTS"
fi
```

#### Phase 1b: Docker Infrastructure Probe (only if `--sidecar`)

If `--sidecar` was passed, probe Docker availability before building the checklist index. If `--sidecar` was NOT passed,
skip this entirely (no Docker dependency for the default walkthrough).

```bash
# 1. Resolve sidecar image from runtime config (respects user overrides)
SIDECAR_IMAGE=$(bash "$SCRIPTS/run-in-repo.sh" forge config show --raw 2>/dev/null \
  | grep '^sidecar_image:' | awk '{print $2}')
SIDECAR_IMAGE="${SIDECAR_IMAGE:-forge-sidecar:latest}"
```

Store `$SIDECAR_IMAGE` via `walkthrough-state.py var set SIDECAR_IMAGE <value>` for use in checklist variable
substitution.

```bash
# 2. Probe Docker daemon + image
docker info --format '{{.ServerVersion}}' >/dev/null 2>&1 && \
docker image inspect "$SIDECAR_IMAGE" --format '{{.Id}}' >/dev/null 2>&1 && \
echo "true" || echo "false"
```

Store result via `walkthrough-state.py var set INFRA_DOCKER <true|false>`.

#### Phase 2: Build Checklist Index

**Set the walkthrough checklist** from the skill's own location:

```bash
CHECKLIST="${CLAUDE_SKILL_DIR}/resources/checklist.md"
```

Run the checklist parser to get the full structure:

```bash
python3 "$SCRIPTS/walkthrough-state.py" "$CHECKLIST" index
```

This returns JSON with all sections, subsections, annotations, and assertion counts. Store this as the checklist index.

Initialize progress tracking (always `--force` -- this is the start of a fresh run):

```bash
python3 "$SCRIPTS/walkthrough-state.py" "$CHECKLIST" init --force "$FORGE_TEST_REPO/.forge/walkthrough/progress.json"
```

Store the state file path as `$STATE_FILE` for Phase 3.

#### Phase 3: Execute Checklist (Main Loop)

For each subsection in the index, get its details:

```bash
python3 "$SCRIPTS/walkthrough-state.py" "$CHECKLIST" step <N.X>
```

This returns JSON with:

- `annotation` / `annotations`: step type(s)
- `prereqs`: prerequisite step/section IDs, if any
- `code_blocks`: list of `{code, runnable}` objects -- run entries where `runnable` is `true`; show others as
  display-only
- `instructions`: prose for the user (human:guided items)
- `assertions`: list of assertion texts to verify
- `assertion_count`: number of assertions (deterministic -- do not count manually)
- `next`: ID of the next step (or null if last)

01. **For each step**, call the parser to get its details. The parser handles all markdown parsing -- the agent never
    reads raw checklist markdown during execution.

    **Before presenting the step**, check prerequisites:

    ```bash
    python3 "$SCRIPTS/walkthrough-state.py" "$CHECKLIST" prereq-check "$STATE_FILE" <N.X>
    ```

    If `ok` is `false`, do **not** run or ask about the blocked step. Render it as skipped, include a short reason such
    as `Skipped -- blocked by prereq: 7.1 (skipped)` or `Skipped -- blocked by prereq: 10.1 (not_run)`, record all its
    assertions as `s`, and continue. A skipped prerequisite is blocking; do **not** treat it as success.

02. **Annotations** map to step types. Never show raw HTML comments in output.

    | Annotation               | Step type     | Preamble                                                       |
    | ------------------------ | ------------- | -------------------------------------------------------------- |
    | `<!-- auto -->`          | `[Automatic]` | "Automatic step -- sit back while I check a few things."       |
    | `<!-- human:confirm -->` | `[Review]`    | "I'll run this and show you the output for review."            |
    | `<!-- human:guided -->`  | `[Hands-on]`  | "Your turn -- here's what to do in your Terminal / Session B." |

03. **Step presentation format**: Every subsection follows a visual pattern so progress is easy to scan.

    **Glue calls are silent.** The `walkthrough-state.py step`, `record`, and `var` calls between steps are bookkeeping.
    Do NOT print commentary around them -- just call the tool and move on. The user should see a clean flow of steps
    without JSON output or "now let me fetch the next step" narration.

    **Step layout:**

    ```
    --- N.X Step Title [Type] -------------------------
    <preamble from annotation table above>

    <body: commands, output, or instructions>

    Results:
      ✔ First assertion passed
      ✘ Second assertion FAILED: reason
      o Third assertion skipped
    ----------------------------------------------------
    ```

    **`[Hands-on]` body template** -- guided steps use a fixed inner layout so every run looks the same:

    ```
    --- N.X Step Title [Hands-on] -------------------------
    Your turn -- here's what to do in your Terminal / Session B.

    In your Terminal (or Session B):

    1. First action
    ```

    command-to-run

    ```

    2. Second action
    ```

    another-command

    ```

    Expected:
    - First assertion text from checklist
    - Second assertion text from checklist

    If something goes wrong: <failure cue from checklist, if any>

    Review the instructions above, then answer below.



    <AskUserQuestion>
    ```

    Rules for the template:

    - **"In your Terminal:"** (or **"In Session B:"** for live Claude steps) -- always anchor where
    - **Numbered steps** with flush-left code blocks -- no indentation so copy-paste has no leading spaces
    - **"Expected:"** bullet list pulled from the checklist assertions -- tells the user what to look for
    - **Failure cue** line only if the checklist includes one
    - Never rephrase checklist instructions as prose -- copy the structure, fill in runtime values
    - The buffer line and blank lines before AskUserQuestion are mandatory (rule 9)

    **Section boundaries** appear between sections (not between steps within a section):

    ```
    Section N Complete: X/Y passed

    <educational narration from narration table>

    ====================================================

    --- M.1 First Step [Type] -------------------------
    ```

    Use `---` (thin) for step boundaries, `===` (thick) as a single separator line between sections. This gives the user
    a clear visual hierarchy: sections are major milestones, steps are work items within them.

    Use ✔ for pass, ✘ for fail, o for skip. Each `- [ ]` line in the checklist = one result line. Include a brief note
    in brackets when useful (e.g., `V run-in-repo.sh found [needed for sandbox isolation]`).

04. **Handle by annotation type**:

    | Annotation               | Action                                                                                                                                                                            |
    | ------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
    | `<!-- auto -->`          | Run bash block (with variable substitution). Check assertions against output. Show results block.                                                                                 |
    | `<!-- human:confirm -->` | Run bash block via wrapper, show output to user. Use AskUserQuestion: "Does this look correct?" (Pass / Fail / Skip). Show results block.                                         |
    | `<!-- human:guided -->`  | Show instructions and bash snippet from the checklist. Do NOT run the bash block yourself. Use AskUserQuestion with context-appropriate framing (see rule 8). Show results block. |
    | `<!-- requires: X -->`   | Check infrastructure probe result for `X`. Skip if unavailable (see below).                                                                                                       |
    | No annotation            | Treat as `<!-- human:confirm -->`.                                                                                                                                                |

    A subsection can have multiple annotations. Apply all that match. `requires` is checked first (skip before
    attempting anything else).

    **`requires:` parsing**: The parser returns annotations as raw strings (e.g., `"requires: docker"`). To handle them:

    1. Check `annotations[]` for any string starting with `requires:`.
    2. Extract the requirement name after the colon (e.g., `docker`).
    3. Look up `INFRA_<NAME>` (uppercased) via `walkthrough-state.py var get` (e.g., `INFRA_DOCKER`).
    4. If the value is `false` (or the variable doesn't exist), skip the subsection: show `[Skipped -- requires: X]` and
       record all its assertions as `s` (skip).

    The sidecar section (section 12) uses `<!-- requires: docker -->`. The `INFRA_DOCKER` probe is set in Phase 1b (only
    when `--sidecar` is passed).

    **`prereq:` handling**: Prerequisites are not step types; they come back in `prereqs[]` and are checked with the
    `prereq-check` command above. The walkthrough uses them to skip Session B-dependent sections cleanly when Session B
    was not launched, and to skip Search follow-up steps when the user chose not to exit Session B.

05. **Variable substitution**: Replace these variables in bash blocks before running:

    | Variable           | Source                                            |
    | ------------------ | ------------------------------------------------- |
    | `$SCRIPTS`         | Resolved scripts directory (Phase 1)              |
    | `$SETUP_SCRIPT`    | Resolved setup script path (Phase 1)              |
    | `$FORGE_TEST_REPO` | Resolved test repo path (Phase 1)                 |
    | `$PROXY_ID`        | Captured from section 6.1 proxy creation output   |
    | `$PROXY_BASE_URL`  | Captured from section 6.1 proxy creation output   |
    | `$SIDECAR_IMAGE`   | Resolved sidecar image name (Phase 1b, if probed) |

    When a command outputs a proxy ID or base URL, persist it in the state file:

    ```bash
    python3 "$SCRIPTS/walkthrough-state.py" "$CHECKLIST" var "$STATE_FILE" set PROXY_ID <value>
    ```

    Retrieve with `var ... get PROXY_ID` when needed for substitution.

    For blocks that start with `bash "$SCRIPTS/run-in-repo.sh"`, the wrapper handles CWD and env. For blocks without the
    wrapper prefix (e.g., python3 mtime snapshots, `ls`, `test`), run directly -- these are read-only host operations.

06. **Executing code blocks**: For each entry in the parser's `code_blocks` array where `runnable` is `true`, run `code`
    as **one** Bash tool call. A single fenced block = one call, even if it spans multiple lines (e.g.,
    `python3 -c "..."`). Entries where `runnable` is `false` are display-only snippets -- show them to the user in
    `human:guided` steps but do not execute them.

    **Default debug logging**: the walkthrough sandbox exports `FORGE_DEBUG=1` via `.forge/walkthrough/env.sh`, so Forge
    commands write debug logs to `$FORGE_TEST_REPO/.forge-home/logs/...`.

    **Before a block that contains `forge logs clean --yes`** and only when `--report` is enabled, snapshot the current
    sandbox Forge logs so evidence survives the cleanup step:

    ```bash
    SNAP="$WT_FORGE_LOG_SNAPSHOTS/N.X/pre-clean"
    rm -rf "$SNAP"
    if [ -d "$FORGE_TEST_REPO/.forge-home/logs" ]; then
      mkdir -p "$SNAP"
      cp -R "$FORGE_TEST_REPO/.forge-home/logs/." "$SNAP"/
    fi
    ```

    **When `--report` is enabled**, save raw command output to a per-step host-side log file:

    ```bash
    mkdir -p "$WT_STEP_LOGS_DIR"
    cat > "$WT_STEP_LOGS_DIR/N.X.log" <<'EOF'
    <raw output>
    EOF
    ```

    **After classifying each step's assertions**, record results in the state file:

    ```bash
    python3 "$SCRIPTS/walkthrough-state.py" "$CHECKLIST" record "$STATE_FILE" <N.X> <results>
    ```

    Where `<results>` is comma-separated: `p` (pass), `f` (fail), `s` (skip) -- one per assertion. Example:
    `record "$STATE_FILE" 6.1 p,p` for a step where both assertions passed. The output shows progress:
    `6.1: 2/2 pass | Section 6: 2/7 | Overall: 27/51`.

07. **Flag gate** -- If `--sidecar` was NOT passed, skip section 12 (Sidecar) entirely. Record all its assertions as `s`
    (skip) and move directly to section 13 (Cleanup).

08. **Gate rules** -- check after each section completes:

    | If section fails... | Then...                           |
    | ------------------- | --------------------------------- |
    | 0 (Setup)           | Stop. Setup is broken.            |
    | 2 (Install)         | Skip Section 3 (can't verify).    |
    | 6 (Proxy/Session)   | Skip Sections 7-11 (no proxy).    |
    | Any section         | Section 13 (Cleanup) always runs. |

09. **For `human:guided` items**: CRITICAL -- print the full instructions and bash snippet from the checklist **before**
    calling AskUserQuestion. Do **not** end immediately on the last instruction line or code fence: Claude Code's dialog
    overlays the bottom few terminal lines. After the real instructions, print one short disposable buffer line such as
    `Review the instructions above, then answer below.` and then print **at least three blank lines** before calling
    AskUserQuestion. Treat that buffer line and blank space as sacrificial padding. The user must see what to do BEFORE
    being asked to confirm. The instructions appear in the step body between the opening preamble and the
    AskUserQuestion call. If you put instructions after the question, the user sees only the question with no context.

    **Match question framing and options to the step type:**

    | Step asks user to...              | Question style                  | Options                            |
    | --------------------------------- | ------------------------------- | ---------------------------------- |
    | Perform an action (open, launch)  | "Have you [action]?"            | Done / Skip / Stop walkthrough     |
    | Verify something (status, output) | "[Expected result] visible?"    | Yes / No, something's wrong / Skip |
    | Both (run command + check result) | "Did [expected result] appear?" | Yes / No, something's wrong / Skip |

    Keep the AskUserQuestion prompt itself short enough to fit on one line when possible. Put detail in the printed
    instructions, not in the dialog. Don't use "Done" as an answer to a yes/no question. "Did %help show commands?"
    needs Yes/No, not Done.

    The user acts in their Terminal window or Session B. If they choose "Stop walkthrough", skip all remaining sections
    and go to Phase 4 (Summary).

    **Do not invent Claude availability failures**: For guided steps that involve a live Claude Code session
    (`forge claude start`, `forge session start`, Session B, status line checks, `%` commands, etc.), do **not**
    recommend "Skip" merely because the agent cannot drive the TUI itself. Recommend "Skip" only when you have concrete
    evidence that live Claude launching is unavailable:

    - A direct probe fails, for example:

      ```bash
      command -v claude >/dev/null 2>&1
      ```

    - The user reports an actual launch failure such as `claude: command not found`.

    If the current walkthrough already contains evidence that Claude launched successfully, treat live Claude as
    available and continue guiding the user instead of steering them toward `Skip`.

10. **Educational narration**: after each `## N.` section completes, print a brief explanation:

| After Section      | Say                                                                                                                                                                         |
| ------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 0 (Setup)          | "Test repo ready. Your real `~/.claude/` timestamps are recorded as a baseline."                                                                                            |
| 1 (Terminal)       | "You now have a sandboxed terminal. Commands there target the test repo, not your real system."                                                                             |
| 2 (Install)        | "Extensions installed. The wrapper enforced 4 safety gates before running the install."                                                                                     |
| 3 (Verify)         | "Hooks, skills, commands all landed correctly. Pre-existing settings survived the install."                                                                                 |
| 4 (Untouched)      | "Real system confirmed untouched -- all timestamps match the baseline."                                                                                                     |
| 5 (CLI)            | "You've seen the Forge CLI surface -- sessions, proxies, config, policy, all managed through `forge`."                                                                      |
| 6 (Proxy/Session)  | "Proxies route API calls; sessions track your workspace. Together they let you switch models without changing code."                                                        |
| 7 (Session B)      | "A live Claude session with Forge hooks, status line, and % commands active."                                                                                               |
| 8 (% Commands)     | "Direct commands let you control Forge from inside a Claude session without leaving the conversation."                                                                      |
| 9 (Policy)         | "The policy engine enforces coding policies at tool boundaries. Deny messages include intent (why the policy exists) so models comply with the goal, not just the check."   |
| 10 (Search)        | "Search indexes your session transcripts for later retrieval. The BM25 engine works per-project -- no external service needed."                                             |
| 11 (Session State) | "The session manifest captures intent (what you wanted), overrides (live changes), and confirmed (what hooks observed). Forking shows how sessions derive from each other." |
| 12 (Sidecar)       | "Sidecar bundles proxy + Claude in Docker -- lifecycle coupling, port isolation, no host proxy needed."                                                                     |
| 13 (Cleanup)       | "Sandbox cleaned. Everything removed, real system still pristine."                                                                                                          |

#### Common Mistakes (DON'T)

- **DON'T count assertions manually.** Use `walkthrough-state.py record` and `report` for all counting. LLMs get
  arithmetic wrong.
- **DON'T combine multiple Bash commands in one call.** Run each `code_blocks` entry as a separate Bash call. Piped
  multi-command blocks fail silently in the Bash tool.
- **DON'T put instructions after AskUserQuestion.** The user sees the question modal immediately -- anything you print
  after it appears below their answer, not above the question. Print instructions BEFORE the tool call.
- **DO add a real visual buffer before AskUserQuestion.** Use a short sacrificial buffer line plus at least three blank
  lines so the dialog covers padding, not the instructions or command snippet.
- **DON'T assume Claude Code is unavailable without evidence.** For `human:guided` live-session steps, only recommend
  `Skip` after a real failed probe (`command -v claude`) or an actual user-reported launch error.
- **DON'T invent CLI commands.** Run ONLY commands from the checklist's `code_blocks`. If a command doesn't exist, the
  walkthrough will show a confusing error.
- **DON'T use `$HOME` in Bash tool calls.** Use fully resolved absolute paths (e.g.,
  `/Users/.../.forge/manual-testing/walkthrough/test-repo` not `$HOME/.forge/manual-testing/walkthrough/test-repo`). The
  Bash tool's environment may not expand shell variables reliably.
- **DON'T run `forge` commands without the wrapper.** Even `forge info` can write caches. Use `run-in-repo.sh` for
  everything except pure filesystem reads (Read tool, Glob tool, `python3`, `test`, `ls`).
- **DON'T modify files during the walkthrough.** This skill has Read, Bash, and Glob only -- no Write or Edit. The
  walkthrough is verification, not modification.
- **DON'T ignore script failures.** If `walkthrough-state.py` exits with a non-zero code, STOP. The error message on
  stderr tells you what went wrong (count mismatch, hash drift, corrupt state). Do not proceed with stale data.

#### Phase 4: Summary

Get the final report from the state file:

```bash
python3 "$SCRIPTS/walkthrough-state.py" "$CHECKLIST" report "$STATE_FILE"
```

This returns JSON with per-section pass/fail/skip counts, failures list, gaps, and totals. Render it as the results
table. The script provides all numbers -- do not count manually.

```
Walkthrough Results
====================================
  Section                    Pass  Fail  Skip  Expected
  -----------------------------------------------------
  0. Setup                     7     0     0       7
  ...
  -----------------------------------------------------
  TOTAL                       N      0     0       N

  Failures: (none)
  Gaps: (none)
====================================
```

#### Phase 4b: Save Run Artifacts (`--report` only)

When `--report` is set, do not stop after printing the summary. Continue directly into artifact save.

```bash
RUN_DIR="$WT_STATE_DIR/runs/$(date +%Y-%m-%d-%H%M%S)"
mkdir -p "$RUN_DIR"
```

1. Generate the final report with `walkthrough-state.py report` and write the rendered markdown to `$RUN_DIR/report.md`.

2. Copy the state file:

   ```bash
   cp "$STATE_FILE" "$RUN_DIR/state.json"
   ```

3. Copy raw step logs when present:

   ```bash
   if [ -d "$WT_STEP_LOGS_DIR" ]; then
     cp -R "$WT_STEP_LOGS_DIR" "$RUN_DIR/step-logs"
   fi
   ```

4. Copy any pre-clean Forge log snapshots when present:

   ```bash
   if [ -d "$WT_FORGE_LOG_SNAPSHOTS" ]; then
     cp -R "$WT_FORGE_LOG_SNAPSHOTS" "$RUN_DIR/forge-logs-snapshots"
   fi
   ```

5. Copy the current sandbox Forge debug logs when present:

   ```bash
   if [ -d "$FORGE_TEST_REPO/.forge-home/logs" ]; then
     mkdir -p "$RUN_DIR/forge-logs/final"
     cp -R "$FORGE_TEST_REPO/.forge-home/logs/." "$RUN_DIR/forge-logs/final"
   fi
   ```

6. Generate a transcript claim token and write the marker so only this walkthrough session can copy the transcript here
   when it ends:

```bash
WT_TRANSCRIPT_TOKEN="forge-walkthrough-transcript-token:$(python3 - <<'PY'
import uuid
print(uuid.uuid4())
PY
)"
python3 - <<'PY' "$RUN_DIR" "$WT_STATE_DIR/.pending-transcript" "$WT_TRANSCRIPT_TOKEN"
import json
import sys

run_dir, marker_path, token = sys.argv[1:4]
with open(marker_path, "w", encoding="utf-8") as handle:
    json.dump({"run_dir": run_dir, "transcript_contains": token}, handle)
    handle.write("\n")
PY
```

Tell the user: "Walkthrough artifacts saved to `$RUN_DIR`. Forge step logs and debug logs were copied when present.
Transcript claim token: `$WT_TRANSCRIPT_TOKEN`. Transcript will be added when this walkthrough session ends."

Tip: "For a quick non-interactive check, use `/forge:smoke-test`. For the full QA checklist in Docker, use `/forge:qa`
(requires `forge extension enable --profile full`)."

## Safety Model

| Tier        | Scripts involved                | What can go wrong           | Mitigation                                |
| ----------- | ------------------------------- | --------------------------- | ----------------------------------------- |
| Walkthrough | `run-in-repo.sh` (agent-driven) | Install targets real system | 4 safety gates + agent mtime verification |

### Safety Gates (run-in-repo.sh)

Every command in the walkthrough passes through these gates:

1. **Denylist** -- refuses FORGE_TEST_REPO = empty, `/`, `$HOME`, `/Users`, `/tmp`, `/var`, etc.
2. **Gate 1** -- env.sh exists (test repo not deleted)
3. **Gate 2** -- marker file exists (this is actually a test repo)
4. **Gate 3** -- FORGE_HOME isolation: FORGE_HOME points to `$FORGE_TEST_REPO/.forge-home` (not real `~/.forge/`)
5. **Gate 4** -- structure check: `.forge/walkthrough/` and `CLAUDE.md` exist

Any gate failure = loud error message + exit 1. No silent fallthrough.

## Tips

- **Quick check**: For a quick non-interactive health check, use `/forge:smoke-test`.
- **Full QA**: For the full QA checklist in Docker, use `/forge:qa` (requires `--profile full`).
- **Robustness principle**: The user should never see an error you could have avoided. If something is known to fail,
  use the working alternative directly.
