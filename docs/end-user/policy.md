# Forge Policies — Code Quality Gates

Policies enforce coding rules at Write/Edit boundaries. When Claude Code is about to write or edit a file, Forge
evaluates registered policies and blocks or warns based on the result.

- Canonical architecture: [`docs/design_workflows.md` §1](../design_workflows.md#1-policy-enforcement)
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

Policy hooks use the lifecycle-hook compatibility posture: before policy/shadow state can be written, Forge checks the
resolved session root and any separate shadow-artifact root once per invocation. A bad `.forge/project.toml` adds one
debug diagnostic but does not alter allow/deny output, stderr feedback, or the Codex JSON wire. Explicit policy
mutations are strict instead: CLI `enable`/`disable` and supervisor lifecycle commands, plus their mutating `%` forms,
refuse before proxy startup or manifest writes. Read-only status/check surfaces remain available.

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

### Removed experimental `workflow` bundle

The former manifest-only `workflow` bundle was removed. Existing sessions that still contain `workflow` in
`policy.bundles` or retain `policy.bundle_config.workflow` fail policy-engine construction with a recovery diagnostic;
the hook allows the action rather than silently running a partial policy set.

The old activation instructions allowed `forge session set`, which stores overrides that win over policy intent. Clear
all policy overrides first:

```bash
forge session reset policy
```

Then choose the policy intent you want:

```bash
forge policy enable --bundle tdd
forge policy enable --bundle tdd --bundle coding_standards
# Or turn enforcement off:
forge policy disable
```

The reset returns policy settings to intent. A following terminal `forge policy enable` replaces stale intent bundle and
configuration fields; `forge policy disable` turns enforcement off. Setting `policy.bundles` or `policy.bundle_config`
to `null` is not a recovery path because those fields are non-nullable.

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

Choose exactly one content source: `--file` / `-f` or `--diff`. Passing both is a usage error; Forge does not choose one
and ignore the other. `--diff` splits a multi-file patch into per-file action contexts and evaluates them tests-first
through one policy engine. JSON output includes `files_checked`, and each violation names its `file_path`.

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

For the full list of `%` commands, see [`hook.md`](hook.md#in-session-commands-commands).

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

The semantic supervisor validates Write/Edit actions against an approved plan. Claude continues a planning conversation
when a target is configured, or starts fresh for a plan file alone. Both paths are read-only. The runtime is selectable
(see [Supervisor runtime (lane)](#supervisor-runtime-lane) below).

Configured in the session manifest under `policy.supervisor`:

- `resume_id` — supervisor target (a Forge planning-session name or Claude session UUID). The Claude arm resumes it; the
  Codex arm uses the resolved approved-plan snapshot in-band.
- `proxy` — proxy for supervisor LLM calls (optional, defaults to session proxy)
- `timeout_seconds` — reviewer limit from 1 to 45 seconds (default: 45s), including auth and retries. Set at configure
  time with `forge policy supervisor set <target> --timeout N`, or adjust a live session with
  `forge session set policy.supervisor.timeout_seconds N`
- `throttle_seconds` — cache window for repeated checks (default: 30s)

The supervisor only blocks when the verdict is "divergent" with **high confidence (≥0.8) and citations** referencing the
plan. Low confidence or missing citations produce a warning instead. Timeouts, errors, and unparseable responses also
result in a warning, not a block.

**Picking a supervisor model.** With a planning target, Claude reads the planner's conversation via `--resume` and must
locate and cite specific plan items. Plan-only Claude and all Codex reviews receive the approved snapshot in-band.
Select the reviewer with `--model`; the requested selector and any observed runtime model are recorded separately. For
per-family Claude-lane supervisor picks (including the Opus 4.6 vs 4.8 split, when to cross-route to Gemini for mid-long
or multimodal planning sessions, and DeepSeek V4 Pro as a cost-efficient alternative), see
[model_selection.md](model_selection.md).

### Review an approved plan file

For a host Claude or Codex executor, configure the current session without a planning conversation:

```bash
forge policy supervisor set --plan ./approved-plan.md --model sonnet --auth-mode subscription-only
forge policy supervisor status --json
forge telemetry activity
```

This explicit mode requires a compatible Claude 2.x (at least 2.1.248 with all review flags), a personal Pro/Max CLI
login, and **usage credits disabled on the Claude account**. Forge cannot inspect that account setting. It strips
competing API/cloud/proxy credentials, skips Forge credential hydration and user/project/local settings, and verifies
the same child auth configuration used for review. The CLI must identify a personal Pro/Max subscription through current
auth status or supported legacy account metadata; an unclassified login is refused. Missing/expired login, quota
failure, managed policy, active/default profiles, alternate config directories, and unverified organization/gateway
routes produce unavailable review with no API fallback. No login tokens are read or copied. Runtime capability checks
refresh after auto-updates; setup and status report incompatibility. This proves route selection, not a measured invoice
or quota decrement.

For an explicit paid direct route, use `--auth-mode inherit --no-supervisor-proxy`; an existing environment or Forge
credential remains available, as do user-settings `apiKeyHelper` and auth environment settings from user or explicitly
trusted project settings. Move any project-only helper to user settings or export its credential; checkout-controlled
helpers cannot run in the reviewer. Other customizations stay disabled. Select a proxy with
`--supervisor-proxy <id-or-template>` and use its `opus`, `sonnet`, or `haiku` tier. For a Codex reviewer, run
`forge runtime preflight codex`, then set
`--plan ... --runtime codex --model <supported-model> --supervisor-effort <level>` with inherited auth. Stale readiness
produces an actionable unavailable result; hooks do not run readiness probes.

The plan must be readable, nonempty UTF-8. Target plus `--plan` resumes the target but makes the file authoritative.
Claude resumes from the planner directory and receives the action checkout as an additional directory; action paths are
absolute. Fresh Claude and Codex review in the action checkout. Claude reviewers expose only inspection tools; Codex
reviewers use a read-only sandbox. Plan-backed and subscription-only supervision refuse sidecars, including inherited
configurations. Legacy conversation-only sidecar review keeps its route and gains read-only restrictions. A stale
sidecar image refuses launch with rebuild guidance before mounting user state.

`off` preserves configuration, `on` re-enables it, and `remove` clears the frozen binding. Bare `reload` on plan-only
configuration revalidates the stored file; `reload --from <path>` changes it atomically. Content hashes invalidate
cached verdicts even if timestamps and file sizes match. Status keeps suspended/unusable configuration visible and
reports the latest live completed, unavailable, or incomplete attempt. Background shadow verdicts remain audits and
never replace the live verdict. Admitted managed Codex executors receive bounded allowed-action warnings; clean allows
remain silent. The summary toggle controls allowed model context independently of operator warnings and audit evidence.

Upgrades leave existing frozen `claude-max` bindings on inherited auth. Opting in or changing a frozen model/effort
requires `forge policy supervisor remove` followed by `set`. Legacy timeouts over 45 seconds migrate to 45. Ordinary
writes retain schema v2 compatibility; explicit model/auth fields require v3 and a matching sidecar image. Retain a
pre-upgrade backup for downgrades. Old or incomplete shadow candidates finish unavailable without dispatch; complete v6
candidates freeze source, effective model, effort, auth, and lane. Supervisor replacement preserves tuning overrides.
`%policy` lifecycle commands work with these configurations, while new setup options belong to the terminal CLI;
one-shot `evaluate -r` remains conversation-based.

### Supervisor runtime (lane)

The supervisor runs on `claude_code` (the default `claude -p --resume` path) unless you pin a different runtime. The
only other shipped runtime is `codex`, which routes the check to OpenAI's Codex (`codex exec`, direct — no proxy)
instead of Claude:

```bash
# Pin at configure time (--supervisor-runtime requires --supervise on start/fork)
forge session fork planner --supervise --supervisor-runtime codex

# Or on an existing supervised session
forge policy supervisor set planner --runtime codex
```

The chosen runtime is **frozen on the first registered policy check**, the supervisor's commitment point; the check can
freeze an explicit lane even when preflight or plan validation prevents a runtime dispatch. After that,
`forge policy supervisor set <target> --runtime <other>` refuses to change it (re-pinning the *same* lane is a no-op).
To use a different lane, start or fork a fresh session, or run `forge policy supervisor remove` first — remove clears
the binding so a later re-add starts from the default again. `forge policy supervisor status` shows the bound
`(runtime, backend, model)` lane.

A project compatibility refusal happens before the registered check reaches or persists its commitment write and
therefore cannot freeze the lane. Recover by running a Forge version satisfying `required_forge`, or edit/reset project
state. If the hook binary comes from `FORGE_DEV`, relaunch after changing it; a sidecar must carry the satisfying Forge
version in its image.

**If your codex subscription runs out mid-session**, Forge degrades the supervisor to the default `claude -p` lane for
the rest of the session instead of failing every check open — real plan-enforcement keeps working. The codex binding
itself stays put (it resets next session; clear it now with `forge policy supervisor remove` or re-pin with
`set --runtime`, and a fresh resume retries codex in case your quota refilled). While it is routed around,
`forge policy supervisor status` and `forge session lane show` mark the lane `degraded`.

### Claude Max subscription billing (`--backend claude-max`)

By default the `claude_code` lane uses the `anthropic-direct` backend. A direct run with a resolvable key is labeled
`api`; a keyless run on that default backend remains `unknown`. If you run on a Claude Max/Pro subscription and want
headless checks attributed to it, pin the lane's **backend** (`claude-max` and the default share the `claude_code`
runtime, so `--runtime` alone can't select it):

```bash
forge policy supervisor set planner --backend claude-max
```

For a check to actually ride the subscription, the run must be **keyless and direct**: no resolvable `ANTHROPIC_API_KEY`
(env or `~/.forge/credentials.yaml`) and no proxy. Then the check authenticates via your Claude login and its usage
event is labeled `billing_mode=subscription_quota`. A resolvable key always wins (labeled `api`), and a proxied run
stays `unknown` — Forge never guesses. Cost stays `unavailable` for subscription runs (no per-token dollar figure is
fabricated); only the label changes. Like `--runtime`, the backend is **frozen on the first check**.

**Other Forge LLM-work can ride the subscription too.** The memory writer, shadow curation, and the team supervisor take
the same backend pin through the general `forge session lane` surface:

```bash
forge session lane set --consumer memory-writer --backend claude-max
forge session lane set --consumer shadow-curation --backend claude-max
forge session lane set --consumer team-supervisor --backend claude-max
forge session lane show          # requested vs frozen lane per consumer
```

Same rules as the supervisor: the run must be **keyless and direct** to be labeled `subscription_quota` (a resolvable
key → `api`, a proxy → `unknown`), and the lane freezes on that consumer's first dispatch. A `--backend claude-max`
binding stays on the default `claude_code` runtime, so that particular pin changes only the billing label. Separately,
memory writer and shadow curation accept `--runtime codex` as a real `codex exec` dispatch lane; team supervisor has no
Codex lane and remains billing-only.

The team event tagger also fails open if its model cannot be reached. That failure emits a diagnostic naming the model
and is not cached, so the next eligible team event retries instead of silently inheriting a routine verdict.

### Cascade: a cheap first pass before the supervisor (opt-in)

Every supervisor check replays the planning session's full context — expensive when most checks come back "aligned". The
cascade adds a lower-cost tier-1 check against the approved plan snapshot and reserves the full supervisor for uncertain
actions:

```bash
# Enable when setting the supervisor, or toggle later
forge policy supervisor set planner --cascade
forge policy supervisor cascade on          # enable on existing config
forge policy supervisor cascade off       # disable (supervisor checks every action again)

# Optional: pick the tier-1 route
forge policy supervisor cascade on --checker-provider litellm-local
forge policy supervisor cascade on --checker-model google/gemini-3.8-flash

# Advanced: tune the persisted checker prompt budget
forge session set policy.supervisor.checker_budget_tokens 64000
```

How it behaves:

- The tier-1 checker evaluates the action against the **approved plan snapshot** text only (no session context). It
  needs a plan file: enabling cascade auto-resolves the latest approved plan (the same search
  `forge policy supervisor reload` uses) and fails with instructions when none exists.
- The default checker model is Gemini 3.8 Flash through OpenRouter (`google/gemini-3.8-flash`), local LiteLLM
  (`gemini/gemini-3.8-flash`), or remote LiteLLM (`vertex_ai/gemini-3.8-flash`), with an approximate 32K-token total
  budget for the tier-1 checker prompt. Forge always requires ZDR for the direct OpenRouter call; proxy-level non-ZDR
  opt-outs do not apply. Local LiteLLM backend configs are one-time copies: backends generated before the 3.8 route was
  added need their materialized `litellm` config updated or deleted/recreated, then restarted — restart alone re-reads
  the old copy. Until then, select a model the existing backend serves, such as
  `--checker-model gemini/gemini-3.7-flash` for the preceding generated config. A remote LiteLLM operator must add the
  `vertex_ai/gemini-3.8-flash` route to that server.
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

### Artifact authority runs before policy

Artifact authority is a separate session-intent boundary, not a policy bundle or a policy fail mode. In a launch-marked
advisory session, the raw authority guard runs before tool filtering, path normalization, `policy.enabled`, bundle and
supervisor gates, and the runtime-specific policy adapter. A covered request is denied even when policy is disabled,
permissive, absent, or configured to fail open.

An authority decline is not an `allow`: runtime permissions and ordinary policy still evaluate afterward. A producer
designation likewise grants no policy exemption; it only lets the request reach the existing permission/policy path.
Consequently, `%policy disable`, `forge policy disable`, and supervisor toggles cannot unblock an authority denial. The
human must stop the session and use `forge session authority set|clear` from another terminal. See
[Artifact authority for managed sessions](session.md#artifact-authority-for-managed-sessions).

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
- Verify the hook is installed: check your user settings file for `PreToolUse` entries with `forge-hook policy-check`
  (see [`hook.md`](hook.md) for which settings file applies to your scope)

### Blocked but tests were written

The TDD policy tracks state across hook invocations. If you wrote tests in a *previous* session, the current session
doesn't know about it (state is session-scoped).

- Check state: `%policy status` shows `tests_touched` set
- If starting fresh: write at least one test file in the current session before `src/` files

### Supervisor timeout

The reviewer limit is 1–45 seconds. Both executors retain 60-second hook registration; Forge budgets all files and
cascade stages together within 55 seconds, reserving five seconds for completion. Auth checks and format retries share
the remaining time. A detached watchdog terminates the reviewer and its descendants on deadline or hook death, with a
0.5-second termination grace before force-kill. Timeouts preserve fail-open behavior and record unavailable/incomplete
review. Already dispatched upstream work can still incur cost.

Check `forge policy supervisor status --json` and `forge telemetry activity <session>`. Refresh Codex readiness when
requested, repair a missing plan with `reload --from`, or choose a faster reviewer. Oversized timeout values, including
generic session overrides and stale saved values, are refused. Forge does not extend trusted hook registration.

### Shadow audit marker failed compatibility

Shadow sampling may enqueue a detached audit marker after a policy hook. The worker strict-checks the shadow artifact's
Forge root before spawning. A refusal follows the normal bounded work-queue retries and eventually moves the marker to
`~/.forge/pending-work/failed/`; it never changes the foreground policy decision. After recovery, a later compatible
policy check can enqueue the candidate again, or a compatible worker run can process an available candidate.

---

## Inspecting policy decisions

`forge policy status` shows the current policy config and evaluation counts. For the full decision audit trail
(verdicts, violations, citations, timestamps), use:

```bash
forge session show <name> --field confirmed.policy
forge session show <name> --json | jq '.confirmed.policy.decisions'
```

The human-readable `forge session show <name>` includes a "Policy Evals:" summary line under Confirmed State.

To turn off Claude's count summary and Codex's allowed-action model feedback:

```bash
forge config set policy_summary_feedback=off
```

Codex warnings normally reach the model as attributed `additionalContext` after an allowed patch. The independent
`systemMessage` channel supplies the operator's Hook notice. `off` omits allowed-action model context and stderr
summaries; blocking reasons, substantive operator notices, and audit records remain. A clean allow produces no Codex
hook output. A failed or unavailable final review is described as unreviewed, never as aligned. A tier-1 failure
resolved by the supervisor remains in audit and does not label the completed review unreviewed.

Codex also supports a global format preference:

```bash
forge config set codex_policy_feedback_format=source-only
```

The default is `normal`. `source-only` keeps reviewer-written explanations, fixes, and unverified citations out of
model-visible hook fields. It selects verbatim quotations verified against the plan snapshot actually reviewed, plus
fixed Forge diagnostics and attributed deterministic-policy findings. Only surrounding citation whitespace is ignored.
Missing or fabricated quotes never change a verdict: a blocked reviewer finding without a verified quote tells the
executor to stop and ask the operator. Inspection commands stay in the operator channel. `policy_summary_feedback=off`
takes precedence for allowed-action context. Claude output is unchanged by the Codex format setting; there is no session
override.

Full reviewer findings remain in session evidence, which the executor can still read from the workspace. This setting
controls Forge's hook emissions, not file access or the authority of developer-role context. Both channels are bounded;
notices report omitted/truncated findings and offer inspection commands. Repeated actions may repeat a finding.

Feedback requires user-scope hook enrollment (`forge runtime preflight codex --verify-enrollment`). Forge records
executor identity at each managed start/resume and enables new channels only for feature-tested versions whose hook
process can be tied to that launch. Nested runtimes cannot reuse inherited admission. Older, unknown, or untested
executors retain blocking behavior and stderr diagnostics. The same conservative behavior applies when an OS process
lookup fails or a launcher forks Codex instead of replacing itself. Such launchers still run normally; their new
feedback channels stay off. Relaunch existing sessions after updating Forge's launch-record schema. This feature
admission is separate from the general QA ceiling and release pin; see
[Codex runtime guards](../design_session_execution.md#i3-codex-operational-guards-probe-churn-enrollment).

## Files to inspect (debugging)

| File                                                     | Purpose                                      |
| -------------------------------------------------------- | -------------------------------------------- |
| `<forge_root>/.forge/sessions/<name>/forge.session.json` | Session manifest (policy config + state)     |
| Claude settings file for your scope                      | Hook config (`PreToolUse` -> `policy-check`) |
| `~/.forge/logs/`                                         | Proxy logs (if supervisor uses a proxy)      |
