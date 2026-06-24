# Forge Policies — Code Quality Gates

Policies enforce coding rules at Write/Edit boundaries. When Claude Code is about to write or edit a file, Forge
evaluates registered policies and blocks or warns based on the result.

- Canonical architecture: [`docs/design.md` §4.1](../design.md)
- Sessions (policy is session-owned): [`session.md`](session.md)
- Hooks (enforcement mechanism): [`hook.md`](hook.md)
- Workflows (multi-model gating via `--check`): [`workflow.md`](workflow.md)

---

## Quick start

```bash
# Enable TDD enforcement for the current session
forge policy enable --bundle tdd

# Check what's active
forge policy status

# Disable all policies
forge policy disable
```

Or from within a Claude Code session (no terminal needed):

```
%policy enable --bundle tdd
%policy status
%policy disable
```

---

## How policies work

Policies run inside the `PreToolUse` hook, which fires before every Write or Edit tool call:

```
Claude calls Write or Edit
  → PreToolUse hook fires
  → PolicyEngine evaluates all applicable policies
  → deny  → tool call blocked (stderr feedback to Claude)
  → warn  → tool call proceeds (warning recorded; see "Seeing warn verdicts" below)
  → needs_review → semantic supervisor resolves it; unresolved requests block
  → allow → tool call proceeds silently
```

Policies are **session-scoped** — enabling policies in one session doesn't affect others. State (like which test files
have been touched) persists in the session manifest between hook invocations.

> **Seeing `warn` verdicts.** A `warn` does not block, and Claude Code does **not** surface non-blocking hook output to
> you at the terminal (it goes to the model as context, not your console). So a warning is effectively invisible
> mid-session. Forge records every verdict; review them after the fact with
> [`forge telemetry activity [session]`](session.md#what-a-session-did-forge-telemetry-activity--session-end-summary)
> (supervisor allow/warn/deny plus recent warning text) or the one-line session-end summary the launcher prints on exit.

---

## Available bundles

### `tdd` — Test-driven development

| Policy ID               | What it checks                                          |
| ----------------------- | ------------------------------------------------------- |
| `tdd.tests-before-impl` | Must write to `tests/` before writing to `src/`         |
| `tdd.no-skip-tests`     | Blocks `pytest.skip`, `@pytest.mark.skip`, and variants |

Enable with permissive mode to warn instead of block:

```bash
forge policy enable --bundle tdd --permissive
```

### `coding_standards` — Code conventions

| Policy ID                             | What it checks                                      |
| ------------------------------------- | --------------------------------------------------- |
| `coding_standards.no-type-checking`   | Blocks `if TYPE_CHECKING:` imports                  |
| `coding_standards.no-backward-compat` | Blocks backward-compatibility wrappers and adapters |

### `workflow` — LLM-based review pipelines (advanced)

Config-driven pipelines that classify code changes via a cheap LLM tagger, then route through filter → checker →
reviewer stages. Only actions flagged as "architectural" or "migration" reach the expensive reviewer.

> **Note:** The `workflow` bundle is not available via `forge policy enable`. Enable it by setting `policy.bundles` and
> `policy.bundle_config` in the session manifest (e.g., via `forge session set`). See [`design.md` §4.1.2](../design.md)
> for the configuration schema.

---

## CLI reference

### `forge policy enable`

```bash
forge policy enable --bundle <name> [--bundle <name>] [--fail-mode open|closed] [--permissive]
```

- `--bundle` / `-b` — bundle to enable (repeatable). Values: `tdd`, `coding_standards`
- `--fail-mode` — `open` (default: allow on engine errors) or `closed` (deny on engine errors)
- `--permissive` — TDD permissive mode: warn instead of deny (`bundle_config.tdd.strict=false`)

### `forge policy disable`

```bash
forge policy disable
```

Disables all policy enforcement for the current session.

### `forge policy status`

```bash
forge policy status
```

Shows: enabled/disabled, active bundles, fail mode, active rules, and per-policy state (e.g., which test files have been
touched for TDD).

### `forge policy check`

Evaluate policies on demand against a file or git diff. Unlike hook-triggered checks, this runs explicitly and defaults
to fail-mode=closed.

```bash
forge policy check --bundle <name> --file <path>
forge policy check --bundle <name> --bundle <name> -f src/foo.py --json
git diff | forge policy check --bundle coding_standards --diff
```

- `--bundle` / `-b` — bundle to evaluate (repeatable, required)
- `--file` / `-f` — file to evaluate against
- `--diff` — read git diff from stdin instead of a file
- `--fail-mode` — `closed` (default) or `open`
- `--json` — structured JSON output

Exit codes: 0 (passed or warnings only), 1 (policy violation), 2 (usage error or engine failure).

### `forge policy supervisor evaluate`

Evaluate a file against an approved plan via the semantic supervisor. Fail-closed with 3-way exit codes.

```bash
forge policy supervisor evaluate -f src/foo.py -r <session-uuid>
forge policy supervisor evaluate -f src/foo.py -r <session-uuid> --proxy openrouter-openai --json
```

- `--file` / `-f` — file to evaluate (required)
- `--resume-id` / `-r` — Claude session UUID of the planning session (required)
- `--proxy` — proxy for supervisor LLM calls (optional)
- `--timeout` / `-t` — supervisor timeout in seconds (default: 45)
- `--json` — structured JSON output

Exit codes: 0 (aligned), 1 (divergent), 2 (could not evaluate — infra failure, timeout, or parse error).

---

## In-session commands

These work inside Claude Code without switching to a terminal:

| Command                                      | Effect                                                    |
| -------------------------------------------- | --------------------------------------------------------- |
| `%policy status`                             | Show policy config and state                              |
| `%policy enable --bundle tdd`                | Enable TDD enforcement                                    |
| `%policy enable --bundle tdd --permissive`   | Enable TDD in warn-only mode                              |
| `%policy disable`                            | Disable all policies                                      |
| `%policy check [--staged] [--bundle <name>]` | Evaluate git diff against policies (diagnostic, not gate) |

`%policy check` runs `git diff` (or `git diff --staged` with `--staged`), splits per file, evaluates each file against
the specified bundles (or session-configured bundles if omitted), and reports pass/fail with violations. It reads
session config even when enforcement is disabled — useful for verifying fixes before re-enabling.

> **Note:** `%policy enable/disable` applies session overrides that persist until changed or reset. The CLI command
> `forge policy enable/disable` mutates the session intent.

For the full list of `%` commands, see [`hook.md`](hook.md#in-session-commands--commands).

---

## Configuration

### Fail modes

| Mode     | On engine error     | On policy evaluation error |
| -------- | ------------------- | -------------------------- |
| `open`   | Allow the tool call | Allow the tool call        |
| `closed` | Block the tool call | Block the tool call        |

Default is `open`. Use `closed` for high-stakes sessions where you'd rather block on uncertainty than risk a bad write.

### Permissive mode (TDD)

`--permissive` sets `bundle_config.tdd.strict=false`. The `tdd.tests-before-impl` policy emits a warning instead of
blocking. The `tdd.no-skip-tests` policy is unaffected (always blocks skip patterns).

### Semantic supervisor (advanced)

The semantic supervisor is an LLM session that validates Write/Edit actions against an approved plan. It uses
`claude -p --resume <session_id>` to continue a planning session in a read-only advisory role.

Configured in the session manifest under `policy.supervisor`:

- `resume_id` — Claude session UUID of the planning session
- `proxy` — proxy for supervisor LLM calls (optional, defaults to session proxy)
- `timeout_seconds` — max wait for supervisor response (default: 45s). Set at configure time with
  `forge policy supervisor set <target> --timeout N`, or adjust a live session with
  `forge session set policy.supervisor.timeout_seconds N`
- `throttle_seconds` — cache window for repeated checks (default: 30s)

The supervisor only blocks when the verdict is "divergent" with **high confidence (≥0.8) and citations** referencing the
plan. Low confidence or missing citations produce a warning instead. Timeouts, errors, and unparseable responses also
result in a warning, not a block.

**Picking a supervisor model.** The supervisor reads the planner's full conversation via `--resume` and must locate and
cite specific plan items — that's multi-needle retrieval over a long context, not code writing. SWE-bench Verified is
the wrong benchmark for this role. For per-family supervisor picks (including the Opus 4.6 vs 4.8 split, when to
cross-route to Gemini for mid-long or multimodal planning sessions, and DeepSeek V4 Pro as a cost-efficient
alternative), see [model_selection.md](model_selection.md).

### Cascade: a cheap first pass before the supervisor (opt-in)

Every supervisor check replays the planning session's full context — expensive when most checks come back "aligned". The
cascade adds a fast, cheap tier-1 check that approves clearly-aligned actions and reserves the full supervisor for the
uncertain ones:

```bash
# Enable when setting the supervisor, or toggle later
forge policy supervisor set planner --cascade
forge policy supervisor cascade on          # enable on existing config
forge policy supervisor cascade off       # disable (supervisor checks every action again)

# Optional: pick the tier-1 route
forge policy supervisor cascade on --checker-provider litellm-local
forge policy supervisor cascade on --checker-model google/gemini-3.5-flash

# Advanced: tune the persisted checker prompt budget
forge session set policy.supervisor.checker_budget_tokens 64000
```

How it behaves:

- The tier-1 checker evaluates the action against the **approved plan snapshot** text only (no session context). It
  needs a plan file: enabling cascade auto-resolves the latest approved plan (the same search `--reload` uses) and fails
  with instructions when none exists.
- The default checker route is OpenRouter `google/gemini-3.5-flash` with an approximate 32K-token total budget for the
  tier-1 checker prompt. Use `--checker-provider litellm-local` to use the local LiteLLM default
  (`gemini/gemini-3.5-flash`) when OpenRouter is unavailable. Local LiteLLM backends generated before that model was
  added to the default backend config may need their `litellm` backend config recreated or updated; otherwise use
  `--checker-model gemini/gemini-2.5-flash` until the backend serves the 3.5 model.
- `checker_budget_tokens` is intentionally a session config setting rather than a `forge policy supervisor cascade`
  flag; use `forge session set policy.supervisor.checker_budget_tokens <tokens>` when you need to tune it.
- Long plans and actions are packed with head+tail excerpts. Unified diffs keep hunk/file headers, Edit checks include
  the old/new fragments, Write checks include target existence metadata, and the prompt explicitly marks whether plan or
  action text was truncated.
- Tier-1 can only approve or escalate — it never blocks on its own. Anything uncertain, plus **every** checker failure
  (model unreachable, unparseable output, missing plan file), escalates to the full supervisor. Worst case the cascade
  degrades to exactly the non-cascade behavior; supervision is never silently skipped.
- `%policy supervisor cascade on` / `%policy supervisor cascade off` toggles it in-session.

Reading the results in `forge telemetry activity`: the **Plan check (tier-1)** line shows allow vs needs-review counts
(your short-circuit rate), the **Supervisor** line shows what the frontier decided when it ran, and the **Model calls**
pane shows tier-1 call volume, tokens, and errors. The two lines can differ: a needs-review verdict that coincides with
a deterministic block (for example TDD) never reaches the supervisor. When recent frontier checks fail open, the
**Supervisor** line also appends `failing open: N timeout, N error` — a window aggregate, distinct from the status
line's `SUP!N` consecutive streak.

### Why supervision matters (beyond TDD)

Deterministic policies like `tdd` enforce **process** — tests before implementation. The semantic supervisor enforces
**intent** — does this change match what was agreed?

The difference matters for subtle drift. An executor might make a reasonable design decision (say, making a dataclass
frozen) that isn't in the approved plan. Tests pass, the code is correct, deterministic policies are satisfied. But the
plan didn't call for it — it's an unreviewed design judgment that compounds over a long implementation session.

The supervisor catches this because it has the full planning conversation in its `--resume` context. It can cite the
specific plan section and explain the divergence, giving the executor enough information to self-correct.

**Surfacing plan gaps.** Supervision works bidirectionally. When the executor hits a supervisor block and the plan
genuinely didn't account for something (a dependency, an interface constraint), the executor stops and surfaces the
conflict. This forces **explicit plan evolution** via `%policy supervisor reload` instead of silent improvisation. Each
reload is an auditable moment where the plan's authority changed.

**Explicit deviation.** When a multi-model review (see [`workflow.md`](workflow.md)) recommends an improvement that
wasn't in the plan, you can turn the supervisor off (`%policy supervisor off`), apply the change, and optionally reload
an updated plan. The deviation goes through *you* — not silently absorbed by the executor.

---

## Stuck playbook (when policies block repeatedly)

When a policy blocks the agent repeatedly and you need to unblock:

```
1. Disable enforcement   →  %policy disable
2. Fix the issue         →  (work with agent or edit manually)
3. Verify fix passes     →  %policy check                      (optional)
4. Re-enable enforcement →  %policy enable --bundle tdd
```

Step 3 is diagnostic — it evaluates without gating. If the check passes, re-enabling enforcement (step 4) lets the next
Write/Edit proceed.

**From a terminal** (alternative to `%` commands):

```bash
# Disable
forge policy disable

# Check a specific file
forge policy check --bundle tdd --file src/foo.py

# Check all unstaged changes
git diff | forge policy check --bundle tdd --diff

# Re-enable
forge policy enable --bundle tdd
```

---

## What happens when a policy blocks

When a policy returns `deny`, the PreToolUse hook exits with code 2 and prints the violation to stderr. Claude Code sees
the error and adjusts its approach.

Example stderr output when TDD blocks a write to `src/` without tests:

```
Policy violation(s):
  [tdd.tests-before-impl] Implementation changes require test changes first
    Fix: Write or update tests in tests/ directory before modifying src/ code
```

**To unblock:**

- Write tests first (the TDD way)
- Switch to permissive mode: `%policy enable --bundle tdd --permissive`
- Disable policies entirely: `%policy disable`

---

## Troubleshooting

### Policies not evaluating

- Check that policies are enabled: `forge policy status`
- Policies only evaluate on `Write` and `Edit` tool calls — `Bash`, `Read`, etc. are not checked
- Verify the hook is installed: check your settings file for `PreToolUse` entries with `forge hook policy-check` (see
  [`hook.md`](hook.md) for which settings file applies to your scope)

### Blocked but tests were written

The TDD policy tracks state across hook invocations. If you wrote tests in a *previous* session, the current session
doesn't know about it (state is session-scoped).

- Check state: `%policy status` shows `tests_touched` set
- If starting fresh: write at least one test file in the current session before `src/` files

### Supervisor timeout

The semantic supervisor has a 45s default timeout. If it exceeds this:

- The action is allowed with a warning (fail-open) — but the upstream provider may still bill the check, since the
  request usually completes after Forge stops waiting
- Check proxy connectivity: is the supervisor's proxy running?
- Reduce supervisor response time: use a faster model via `proxy`
- Raise the budget for slow models: `forge policy supervisor set <target> --timeout 90` at configure time, or
  `forge session set policy.supervisor.timeout_seconds 90` on a live session. Note the hook that invokes the supervisor
  has its own 60s budget; timeouts above ~55s won't take effect end-to-end

---

## Inspecting policy decisions

`forge policy status` shows the current policy config and evaluation counts. For the full decision audit trail
(verdicts, violations, citations, timestamps), use:

```bash
forge session show <name> --field confirmed.policy
forge session show <name> --json | jq '.confirmed.policy.decisions'
```

The human-readable `forge session show <name>` includes a "Policy Evals:" summary line under Confirmed State.

To silence the post-evaluation summary lines printed after each Write/Edit check:

```bash
forge config set policy_summary_feedback=off
```

This suppresses the `[forge] Policy: checked ...` summary and `additionalContext`. Deny messages and substantive
warnings stay visible regardless.

## Files to inspect (debugging)

| File                                                     | Purpose                                      |
| -------------------------------------------------------- | -------------------------------------------- |
| `<forge_root>/.forge/sessions/<name>/forge.session.json` | Session manifest (policy config + state)     |
| Claude settings file for your scope                      | Hook config (`PreToolUse` -> `policy-check`) |
| `~/.forge/logs/`                                         | Proxy logs (if supervisor uses a proxy)      |
