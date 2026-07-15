# Forge Workflow Design

Normative architecture for Forge policy, skills, workflow runners, and project memory. Core state, proxy/session, and
runtime contracts live in [design.md](design.md); schemas and runtime references live in
[design_appendix.md](design_appendix.md); command inventories live in [cli_reference.md](cli_reference.md).

---

## 1. Policy (Enforcement)

Forge Policy is an **enforcement system** with three types:

1. **Deterministic Policy**: Static checks, file mapping, dependency rules (Fast/Free).
2. **Semantic Policy (Supervisor)**: LLM-based alignment checks against plans (Smart/Context-aware).
3. **Verification Policy**: Outcome-based checks at session boundaries (Feedback loop).

| Policy Type   | Boundary               | Question                         |
| ------------- | ---------------------- | -------------------------------- |
| Deterministic | PreToolUse             | "Is this action allowed?"        |
| Semantic      | PreToolUse (throttled) | "Is this aligned with the plan?" |
| Verification  | Stop                   | "Did it achieve the goal?"       |

**Definition:** a policy is an **enforcement function** that runs at a well-defined boundary (hook, proxy, commit hook)
and returns an **action decision** with an explanation.

At minimum:

- **Input**: an *action context* (what is about to happen)
- **Output**: `allow | warn | deny | needs_review` plus human-readable reasons. `needs_review` is an intermediate
  decision: the semantic supervisor must resolve it to `allow`, `warn`, or `deny`; if no configured supervisor resolves
  it, the hook blocks as unresolved.
- **Intent**: every policy declares *why* it exists — shown to models on deny so they can distinguish good workarounds
  (satisfy the goal) from bad ones (defeat it)

### 1.1 Deterministic Policy (Forge Policy)

Forge Policy is designed to support **deterministic policies first**.

- **Engine**: policy interfaces, composition, decisions
- **Adapters**: hook boundary (no-proxy) and proxy boundary (proxy-mode)
- **Policy bundles**: TDD is expressed as a set of deterministic policies (e.g., "tests must exist before
  implementation").

**Base class contract** (`DeterministicPolicy`):

| Abstract property | Type  | Purpose                                                              |
| ----------------- | ----- | -------------------------------------------------------------------- |
| `policy_id`       | `str` | Unique identifier (e.g., `tdd.tests-before-impl`)                    |
| `description`     | `str` | Human-readable description                                           |
| `intent`          | `str` | Why this policy exists — shown on deny so models understand the goal |

All three are **required** (abstract). The `intent` field was added after observing that models (e.g., GPT-5.5) would
find creative workarounds that pass the check but defeat the goal (Unicode escapes to bypass byte-level emoji
detection). Showing the intent alongside the violation steers models toward compliant approaches or surfacing conflicts
to the user.

**Why enforce coding standards via policy?** AI assistants tend to favor gradual migration and backward compatibility
over clean breaks—even when explicitly instructed otherwise. Patterns like `warn+ignore`, fallback logic, and
compatibility shims sneak into codebases despite best efforts. Deterministic policies can catch these at commit/hook
boundaries:

- Reject code containing `# backward compat`, `# legacy`, `# deprecated` comments
- Flag new `if TYPE_CHECKING:` blocks (circular import workaround)
- Detect `warn` + `strip`/`ignore` patterns in validation code

This doesn't require a stateful system—detecting backward compat patterns in a diff is a pattern-matching task that
Haiku handles fine.

**Policy bundles** group related rules:

| Bundle             | Rules                                            | Purpose                 |
| ------------------ | ------------------------------------------------ | ----------------------- |
| `tdd`              | tests-before-impl, no-skip-tests                 | Test-driven development |
| `coding_standards` | no-bsd-sed, no-type-checking, no-backward-compat | Platform/style rules    |

Bundles are enabled per-session:

```yaml
# In session intent
policy:
  bundles: [tdd, coding_standards]
  tdd_mode: strict  # off | permissive | strict
```

### 1.2 Semantic Policy (The Supervisor)

This enables **"Active Alignment"** checking using the **Side-Channel Architecture**.

Automatic promotion of the current session (`--fork-current`) is deferred so the building blocks (supervisor, panel,
session forking) can compose before Forge hardcodes a default. Configure persistent supervision with
`forge policy supervisor set <target>`; `forge session start ... --supervise <target>` and
`forge session fork <parent> --supervise` provide launch-time wiring.

**Mechanism: runtime-selectable side-channel supervision**

The `policy-check` hook resolves the supervisor's consumer lane. The default `claude_code` lane runs
`claude -p --resume <supervisor_uuid>` (plus `--model opus` when proxied). A pinned `codex` lane runs a fresh, read-only
`codex exec` in the action checkout. Codex cannot resume the Claude planning session, so this arm requires an approved
plan in `plan_override_path` (for example via `forge policy supervisor reload`) and receives that snapshot in-band. A
missing plan or cold, stale, or unready Codex preflight fails open with a warning.

1. **Configure**: `forge policy supervisor set <target> [--runtime claude_code|codex]` (or use launch/fork supervision).
2. **Check**: Runs at PreToolUse for Write/Edit, throttled via cache (default 30s).
3. **Enforce**:
   - **Aligned**: Silent success (cached for throttle window).
   - **Divergent + high confidence + citations**: Block the tool.
   - **Divergent + low confidence or no citations**: Warn via stderr, allow the tool.
   - **Unresolved review request**: Block the tool until a supervisor is configured or the user gives a new direction.

**Why this works:** On the Claude lane, native resume supplies the planning conversation; a plan override supersedes it
when present. On the Codex lane, the in-band approved snapshot is the authority. Executor and supervisor routing are
independent; specific model identities are lane/proxy choices, not architectural constants.

**Promotion readiness:** Depends on ground truth quality: explicit acceptance criteria, invariant constraints, resolved
ambiguities.

**Supervisor lifecycle controls:**

- `forge policy supervisor off|on|remove`: `off` sets `suspended=True` (config preserved, hook skips evaluation entirely
  — not registered in the policy engine); `on` resumes; `remove` is destructive. The direct equivalents are
  `%policy supervisor off|on|remove`. All three pre-check that a supervisor is configured before acting.
- `forge policy supervisor reload [--from <path>]`: Inject an updated plan into supervisor evaluation context. Without
  `--from`, reload searches the supervision graph in order: current supervised session, related forks (sessions in the
  same `forge_root` whose parent is the supervisor target), supervisor target session. Only approved snapshots are
  considered (no drafts). The plan content is prepended to each evaluation prompt with explicit supersession framing.
  `--from` takes an explicit file path (resolved relative to CWD, stored absolute). The direct equivalent is
  `%policy supervisor reload [path]`. Cache keys include a `path:mtime_ns:size` fingerprint so in-place edits invalidate
  cached verdicts.
- `plan_override_path` on `SupervisorConfig` stores the override. It can be set while the supervisor is suspended
  (configure the plan, then run `forge policy supervisor on`). Proxy routing is not re-seeded on `on` — the preserved
  config is used as-is.
- Auto-reload may succeed even if the supervisor target session has been deleted (the current session or a related fork
  may still hold the plan). Status always shows the configured supervisor target; when that target resolves, it adds the
  Claude UUID and source model facts that are available.

**Cascade (tier-1 plan check, opt-in):** `forge policy supervisor set <target> --cascade` or
`forge policy supervisor cascade on` routes checks through a cheap tier before the frontier. The direct toggle is
`%policy supervisor cascade on`. A stateless `core.llm` call (`PlanCheckPolicy`, `semantic.plan_check`, default
OpenRouter model `google/gemini-3.5-flash`, configurable per provider via `--checker-provider`/`--checker-model`, with a
configurable default prompt budget of roughly 32K tokens stored as `policy.supervisor.checker_budget_tokens`) evaluates
the action against the **approved-plan snapshot text** (`plan_override_path`, auto-resolved at wiring time via the
`--reload` machinery). The persistent `set ... --cascade` and `cascade on` commands fail with an actionable error when
no approved snapshot resolves. Launch-time `session start|fork --cascade` records the flag only; until a plan resolves,
the hook escalates to the frontier instead of treating the missing tier-1 input as an allow. Long plans and actions are
packed as head+tail excerpts rather than first-N slices, unified diffs retain file and hunk headers when truncated, and
prompt metadata explicitly marks whether the plan or action was truncated. Edit actions include the matched and
replacement fragments when available; Write actions include path and target existence context. Tier-1 emits only `allow`
(clearly aligned; cached per the throttle window) or `needs_review` — it never warns or denies, and **every** tier-1
failure (LLM error, parse failure, unreadable plan) escalates, so the system degrades to frontier-always, never to
unsupervised. In cascade mode the supervisor is registered as the engine's **resolver** (see §1.5): it is invoked only
when a policy emitted `needs_review` and nothing denied, so clearly-aligned actions never pay the frontier call. Tier-1
reasons ride in low-severity violations (persisted to the decision log, never printed on resolved allows). Measurement
is built in: session-tagged `plan-check` usage events plus decision-log-derived
`plan_check_allow`/`plan_check_needs_review` counters in `forge telemetry activity` expose the short-circuit rate; the
supervisor counters are the resolver runs (a tier-1 `needs_review` alongside a deterministic deny skips the resolver, so
the two can differ). Cascade off (the default) is exactly the pre-cascade behavior — the supervisor runs as a regular
policy on every throttle-missing check.

**Shadow sampling (audit, opt-in):** The cascade's blind spot is the **false-aligned** case — a tier-1 `allow` that
short-circuits a frontier check the frontier would have blocked. Shadow sampling measures that rate without slowing the
hook. When `policy.supervisor.shadow_sample_rate > 0`, a *fresh* (uncached) tier-1 `allow` is sampled by a deterministic
stable hash of `(shadow_seed, session, cache_key)` — no RNG, so it is reproducible and never depends on global state —
and, if selected, **frozen** to `.forge/artifacts/<session>/shadow/<hash>.json` (capped at `shadow_max_per_session`).
The candidate freezes the *raw* action inputs plus a copy of the plan (`<hash>.plan.md`) and a routing snapshot, because
the frontier builds its own prompt and reloads the plan at run time — the **capture/check split**. Capture runs no LLM,
never blocks, and is fully inert at rate 0 (the directory is not even created). The frontier replay is a post-hoc
**Stop-batch drain**: the Stop hook enqueues a `shadow` work marker, and a later CLI startup spawns a detached
`forge policy shadow run` worker (the memory-writer pattern) that claims each candidate atomically (`rename` to
`.processing`, bounding frontier billing to at-most-once), reconstructs the full `ActionContext`/`SupervisorConfig`,
runs the frontier, and classifies the verdict with the supervisor's **own** block bar: `agree` (frontier also aligned),
`disagree` (frontier would have blocked — high-confidence, cited), `inconclusive` (divergent below the bar), or `error`
(run failed or output unparseable, kept distinct from a real low-confidence `inconclusive`). It records the verdict and
renames `.processing` → `.done`; it **never enforces**. Spend is a separate `supervisor-shadow` usage row (the worker is
the sole emitter, re-rooted under the originating session). The read surface is `forge telemetry activity` (a Shadow
line with checked/disagree/pending counts), `forge policy shadow show` (the disagreement artifacts with citations), and
`forge policy shadow status` (the sample rate plus pending/done counts for one session).

**Supervisor stuck playbook:** When the supervisor blocks because the plan evolved:

- `%policy supervisor off` (suspend, config preserved)
- Make the approved changes
- `%policy supervisor reload` (searches current session, forks, then target) or `%policy supervisor reload <path>`
- `%policy supervisor on` (resume with updated plan context)

**The underspecification problem (biggest failure mode):** Supervision catches explicit divergence (plan says X, agent
did Y, citations are clear). Underspecification is harder: the plan is silent, the model picks a plausible default, and
neither agent nor supervisor can cite against it — so the verdict may be "aligned." The real divergence is between
unwritten human expectations and model assumptions. Mitigation: (a) more explicit plans (write down the implicit), (b)
multi-model review (different defaults expose gaps), (c) the human reformulation loop (make assumptions explicit,
rerun).

**Operational reliability constraints (normative):**

- **Citations required**: Every **Divergent** finding MUST cite (quote) the specific plan/design section it violates.
- **Structured verdict**: The Supervisor response SHOULD be parseable (even if implemented as plain text initially):
  - `verdict`: `aligned | divergent`
  - `violations[]`: `{ severity, evidence, suggested_fix, citations[] }`
- **Block only on high-confidence + cited rule**: Default behavior is **warn-only** unless the Supervisor provides a
  clear cited rule and a high-confidence violation.
- **Fail open vs fail closed**: Policies MUST define failure behavior per severity (e.g., CLI failure, proxy down,
  timeout). Default to **fail-open (warn-only)** for most checks. Fail-open for policy evaluations is a system-boundary
  rule (LLM output is external data), not an exception to coding-standards §5. See coding_standards.md §5 (boundary
  framework) for the general framework.
- **Subscription-exhaustion degrade (T7)**: the one sanctioned lane-fallback exception. When the supervisor's bound
  codex subscription lane exhausts mid-session (`failure_type="subscription_exhausted"`), the policy hook persists a
  sticky degrade overlay and routes subsequent checks to the default `claude -p` lane -- restoring real enforcement
  instead of a silent per-check fail-open. One hop only (codex -> default; no chains), still fail-open on the degrade
  path itself, sticky for the session (reset on `supervisor remove`/re-pin or a fresh process resume). This is the
  *only* general fallback the consumer-lane epic permits; see design_appendix §G for the overlay/reset mechanics.
- **Throttling + caching**: Supervisor checks SHOULD be throttled (e.g., every N turns, only on Write/Edit, only for
  configured path prefixes) and MAY cache the last verdict for identical diffs.

**On-demand invocation:** Deterministic bundles and the semantic supervisor can be evaluated manually without installing
hooks:

```bash
forge policy check --bundle tdd --file src/forge/session/store.py
git diff -- src/forge/session/store.py | forge policy check --bundle tdd --diff
forge policy supervisor evaluate --file src/forge/session/store.py --resume-id <planning-session-or-uuid>
```

The deterministic manual and hook paths share `PolicyEngine`; one-shot supervisor evaluation and hook enforcement share
`invoke_supervisor`. Forge does not expose one universal `forge policy check <policy-id>` registry surface.

**Primary use case: problem reformulation.** When a policy stops the agent, the cause is flawed problem representation
(too broad/contradictory/ambiguous), genuine agent failure, or an overzealous policy. On-demand checks are diagnostics:
citations and evidence show *what* failed. Reformulate, then re-check before resuming. The Claude lane's native resume
context or the Codex lane's in-band approved snapshot keeps the plan authority in view.

**Reactive Patterns (Shared Library)**

Several components react to hook events via external processing: semantic supervisor (`policy/semantic/supervisor.py`),
the memory writer (`session/memory_writer.py`), deterministic policies (`policy/deterministic/`), and the experimental,
manifest-only WorkflowPolicy. The shared pattern: take hook context, classify/evaluate, return a decision or side
effect. Three node types cover current and planned use cases:

| Node type      | Execution                              | Examples                                  | Cost / billing         |
| -------------- | -------------------------------------- | ----------------------------------------- | ---------------------- |
| Code           | Deterministic Python function          | TDD enforcement, path gating, file checks | Free                   |
| LLM call       | Stateless API call via `core.llm`      | Tagger (classification), checker          | Route-dependent        |
| Headless agent | `claude -p [--resume]` or `codex exec` | Supervisor, memory writer                 | Billing-mode dependent |

**Library, not framework**: Utilities live in a shared Python library (`core/reactive/`). Hook handlers are plain Python
functions that import what they need. No YAML workflow engine, no declarative config layer — the same developers who
would write YAML can write Python with less indirection and better debuggability.

The shared library provides utilities extracted from existing implementations: session runner, proxy resolution,
throttle cache, structured output parsing, tagger, env builder, fan-out runner, and adversarial runner. A developer
adding a new policy imports these utilities and writes a class.

> Shared library API table and example policy code in [§2](#2-policy-internals).

**WorkflowPolicy (tagger → branch → checker → reviewer)**: Plugs into PolicyEngine via existing
`Policy + StatefulPolicy` protocols (zero changes to the engine). Composes library utilities into a branching pipeline:
a shared tagger classifies the action, branches match by tags (first match wins), each branch has optional filter →
checker → reviewer stages. The tagger is called once per event and its tags route to all matching downstream checks —
avoiding redundant classification.

**Team extension**: The same library works for team hooks (`TeammateIdle`, `TaskCompleted`) by subscribing to different
events. See [team_design.md](board/proposed/team_orchestration/card.md) §3.

### 1.3 Verification Policy (Feedback Loop)

Verification policies check **outcomes** rather than **actions**. They run at the **Stop boundary** and can block
session exit until goals are achieved.

**The Ralph-Wiggum Pattern:**

Instead of external bash loops, verification uses the Stop hook to create a self-referential feedback loop:

1. User starts session with a completion promise
2. Claude works toward the goal
3. Stop hook checks: "Did Claude output the completion signal?"
4. If no → block exit, re-inject prompt, continue
5. If yes → allow exit

The prompt never changes between iterations, but Claude's previous work persists in files. Each iteration sees modified
files and git history, enabling autonomous improvement.

**Configuration:**

```yaml
# In session intent
verification:
  type: completion_promise    # or: test_suite, custom_command
  promise: "<done>COMPLETE</done>"
  max_iterations: 50          # safety limit
  on_incomplete: re_inject    # or: warn, allow
  re_inject_prompt: |
    Continue working. Output <done>COMPLETE</done> when all requirements met.
```

**Verification types:**

| Type                 | Verification method        | Use case          |
| -------------------- | -------------------------- | ----------------- |
| `completion_promise` | Look for text in output    | Goal-driven tasks |
| `test_suite`         | Run tests, check exit code | Code changes      |
| `custom_command`     | Run any command            | Domain-specific   |

**Completion promise correctness:**

To avoid false positives (promise appearing in quoted files, code examples, or earlier failed iterations):

1. **Check only the last assistant message** — ignore tool results and conversation history
2. **Require standalone line** — promise must appear on its own line, not embedded in prose

The re-inject prompt should instruct Claude accordingly:

```yaml
re_inject_prompt: |
  Continue working. When ALL requirements are met, output this on a standalone line:
  <done>COMPLETE</done>
```

This prevents false matches from `print("<done>COMPLETE</done>")` in code or discussion like "I'll output
`<done>COMPLETE</done>` when done."

**Escape hatches:** `%cancel-verification` direct command, `max_iterations` auto-bypass, `max_minutes` wall-clock limit,
or `forge session set verification.bypass true` from another terminal. The bypass is a session parameter (discoverable,
auditable). Both time limits matter: `max_iterations` catches fast-failing loops; `max_minutes` catches slow token burn.

**Why verification is policy, not a separate concept:**

- All three policy types share the same structure: boundary + check + action
- Verification just fires at a different boundary (Stop vs PreToolUse)
- Keeps the design unified under "Policy"

### 1.4 Action context

Policies operate on a normalized, origin-tagged view of what a runtime is doing (an `ActionContext`), for example:

- `origin` — which actor produced the action (`claude_code`, `codex`, or `forge_cli` for manual on-demand checks)
- hook event (`PreToolUse.Write`, `PreToolUse.Edit`, …)
- tool arguments (target path, content/diff metadata)
- repository/worktree path
- effective session config (intent + overrides)

Normalization happens at the **adapter boundary**: a runtime's hook adapter maps its payload into this shape and tags
`origin`; a hook **responder** serializes the composed decision back into the runtime's wire contract.
`PolicyEngine.evaluate` never branches on `origin`. Both halves match runtime-neutral `HookAdapter`/`HookResponder`
protocols (`src/forge/cli/hooks/protocols.py`); two pairs ship: **Claude** (`cli/hooks/policy.py`,
`forge hook policy-check`) and **Codex** (`cli/hooks/codex_policy.py`, `forge hook codex-policy-check`). The Codex
adapter normalizes each `apply_patch` file operation to the tool names every policy's `applies_to` gates on (Add File →
`Write`, Update File → `Edit`; deletions skipped; `Bash` passes through), keeping runtime truth in `origin="codex"` +
`tool_args`; files compose deny > needs_review > warn/allow, and unparseable patches fail open. Enforcement requires a
registered + trust-enrolled Codex PreToolUse hook: `forge extension enable` registers it (codex-hooks module, §5);
enrollment remains the user's one-time interactive trust ceremony, which Forge can neither perform nor verify.

### 1.5 Policy composition

Multiple policies may run for a single action:

- **Any deny** in enforce mode blocks the action
- warnings accumulate
- results can be logged for audit/debug
- `needs_review` is resolved by a registered **resolver** policy (the semantic supervisor in cascade mode), invoked only
  on escalation — after the regular pass, when a policy requested review and nothing denied. A supervisor registered as
  a regular policy (cascade off) resolves it the same way; with no resolution, `needs_review` blocks as unresolved
  (unchanged contract)

**Deny message format** (three-tier, shown to the model):

```
Policy violation(s):
  [rule_id] violation message
    Intent: why the policy exists
    Fix: suggested fix (if available)
    Note: This policy was configured by the project owner. First try a
    compliant approach that satisfies the intent above. If the user's
    request cannot be fulfilled without violating the intent, explain
    the conflict and ask how to proceed. Do not attempt bypasses that
    pass the check but defeat the goal.
```

The `Intent:` line appears once per denying policy (not per violation). The `Note:` uses project-owner framing so models
treat it as a constraint to respect, not an obstacle to circumvent. The reason text is composed once
(`format_deny_text`/`format_needs_review_text` in `cli/hooks/policy.py`); each responder owns only the wire framing:
Claude via stderr + exit 2, Codex via stdout JSON (`hookSpecificOutput.permissionDecisionReason`) + exit 0 (strict JSON
because Codex **fails open** on malformed output; allow emits no stdout). The `[forge] Policy: …` summary line is stderr
telemetry in the hook command, not part of either wire contract.

### 1.6 Policy state and ownership

Policy has two aspects with different ownership: **definition** (configuration — who sets the rules) and **state**
(runtime — what happened). Supervisor model and throttling are proxy-owned (routing decisions). TDD mode, policy
enabled/disabled, and verification config are session-owned (workflow decisions). All enforcement results are
hook-written to `confirmed.policy`.

**Policy provenance:** `confirmed.policy` records `forge_version`, `bundles`, `rules_active`, and `decisions` for
audit/debugging ("why did this block?").

**Ownership rationale:** Supervisor model = routing decision → proxy. TDD mode = workflow decision → session.
Enforcement results = observed facts → hook-written `confirmed`. Stateful policies (e.g., "tests touched") write only to
`confirmed.policy`.

> Full policy definition and state ownership tables in [§2](#2-policy-internals).

---

## 2. Policy Internals

Reference details for [Policy and Enforcement](#1-policy-and-enforcement).

### 2.1 Shared library scope (from §1.2)

| Utility            | Extracted from                      | API                                                                                   |
| ------------------ | ----------------------------------- | ------------------------------------------------------------------------------------- |
| Session runner     | `supervisor.py`, `memory_writer.py` | `run_claude_session(prompt, resume_id?, model?, base_url?, timeout, unset_env_vars?)` |
| Proxy resolution   | both                                | `resolve_base_url(proxy_id?, explicit_url?, fallbacks)`                               |
| Throttle cache     | `policy/store.py`                   | `ThrottleCache(ttl).check(key) / .update(key, value)`                                 |
| Structured output  | `verdict.py`                        | `extract_json_verdict(stdout, schema)`                                                |
| Tagger             | new                                 | `tag_action(context, model, prompt) -> tags[]`                                        |
| Env builder        | both                                | `build_claude_env(base_url?) -> dict`                                                 |
| Fan-out runner     | `src/forge/review/engine.py`        | `run_multi_review(prompt, models, per_worker_prompts?)`                               |
| Adversarial runner | `src/forge/review/adversarial.py`   | `run_adversarial(proposal, skill_resource, stances, models)`                          |

### 2.2 Example: Writing a new policy (from §1.2)

A developer adding a policy imports a few utilities and writes a class. Three abstract properties are required:
`policy_id`, `description`, and `intent` (see §1.1).

```python
# Example: block database migrations without review
from forge.core.reactive import tag_action, run_claude_session, ThrottleCache

class MigrationReviewPolicy(DeterministicPolicy):
    policy_id = "custom.migration_review"
    description = "Require review for database migrations"
    intent = "Prevent unreviewed schema changes from reaching production"

    def applies_to(self, ctx):
        return ctx.tool_name == "Write" and "migration" in (ctx.target_path or "")

    def _evaluate(self, ctx):
        tags = tag_action(ctx, model="haiku", prompt="Is this a schema migration? tags: migration | safe")
        if "migration" not in tags:
            return self._allow()
        verdict = run_claude_session(prompt=REVIEW_PROMPT.format(...), resume_id=config.resume_id)
        return verdict_to_decision(verdict)
```

On deny, the message includes the `intent` so models understand why the policy exists and can surface conflicts to the
user rather than working around the check.

### 2.3 Policy definition ownership (from §1.6)

| Setting                                             | Owner   | Location                                                                                                                                                   |
| --------------------------------------------------- | ------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Supervisor model (which model to use as supervisor) | Proxy   | `~/.forge/proxies/<id>/proxy.yaml`                                                                                                                         |
| Throttling settings (check frequency)               | Proxy   | `~/.forge/proxies/<id>/proxy.yaml`                                                                                                                         |
| TDD mode (off/permissive/strict)                    | Session | Session file `intent.tdd_mode`                                                                                                                             |
| Policy enabled/disabled                             | Session | Session file `intent.policy_mode`                                                                                                                          |
| Verification config                                 | Session | Session file `intent.verification`                                                                                                                         |
| Cascade on/off + tier-1 checker route/budget        | Session | `intent.policy.supervisor.cascade`/`.checker_provider`/`.checker_model`/`.checker_budget_tokens`                                                           |
| Checker + frontier reasoning effort                 | Session | `intent.policy.supervisor.checker_effort` (core.llm: `none/low/medium/high/xhigh`) / `.supervisor_effort` (`claude --effort`: `low/medium/high/xhigh/max`) |

### 2.4 Policy state ownership (from §1.6)

| State                                     | Owner           | Location                                         |
| ----------------------------------------- | --------------- | ------------------------------------------------ |
| Enforcement decisions                     | Session (hooks) | `confirmed.policy` in session file               |
| Cached verdicts (supervisor + plan-check) | Session (hooks) | `confirmed.policy.policy_states` in session file |
| "Tests touched" tracking                  | Session (hooks) | `confirmed.policy` in session file               |
| Verification iteration                    | Session (hooks) | `confirmed.verification.iterations`              |
| Last verification result                  | Session (hooks) | `confirmed.verification.last_result`             |

---

## 3. Skills Architecture

Skills are Forge's **scripting layer**: they teach Claude to compose Forge capabilities into workflows. Game engines
have Lua; editors have VimScript; Forge has skills. The `forge` CLI is the engine (proxy routing, session management,
`core.llm`). Skills are the instructions; the agent orchestrates.

Skills don't add tools—Claude already has Read/Write/Bash. Skills add the playbook for composing them with Forge
(multi-proxy routing, session forking, policy checks).

### 3.1 Reflective architecture

Forge installs skills about itself: `forge extension enable` deploys CLI commands (capabilities) and skills (how to use
them). The system teaches the agent about itself.

- Coherent upgrades: `forge extension sync` updates CLI + skills atomically
- No version drift between "what the tool can do" and "what the agent thinks the tool can do"
- Agents can modify skills (markdown files on disk)
- Matches hooks/status-line pattern: `forge` is the engine; extensions are instructions

### 3.2 Why skills over MCP

Forge uses skills (not MCP tools) for agent workflows. MCP servers remain useful for external data access (APIs,
databases, OAuth), but aren't the right abstraction for workflow orchestration.

| Aspect            | Skills                                    | MCP Tools                             |
| ----------------- | ----------------------------------------- | ------------------------------------- |
| Token cost        | Typically ~100 tokens metadata at startup | Often 3K-10K+ for tool definitions    |
| Context pollution | Full instructions load only when invoked  | Tool schemas persist in context       |
| Architecture      | Reflective — skills reference own install | External — separate server process    |
| Context passing   | Fork session (full context preserved)     | Summarize and send (information loss) |
| Determinism       | Agent interprets instructions each time   | Structured JSON-RPC interface         |

**Fork advantage:** Skills can fork the current session (`claude -p --resume <uuid>` on another proxy), giving reviewers
the **full conversation context** (files, decisions, rationale). MCP tools only see what the agent summarizes into tool
parameters.

### 3.3 Execution modes

Skills that invoke multi-model workflows support two **context modes**; the caller chooses based on the situation —
skills present options, not prescriptions.

**Resume context mode:** `claude -p --resume <session-uuid>` on another proxy; inherits full session context. Best when
conversation history matters. Requires Claude Code >= 2.1.80 for reliable parallel tool result handling (`--resume`
dropped parallel tool results in earlier versions).

**Blind context mode:** Fresh `claude -p` (no `--resume`); rely on the prompt + filesystem reads. Cheaper and
independent. Best for isolated reviews and quick checks.

**CLI contract:** Workflow CLIs expose this axis explicitly:

- `--context resume:<session-uuid>` → pass `--resume <id>` to each worker
- `--context blind` → do not pass `--resume` (workers are independent)

**CLI surface:** `forge workflow <workflow>` (e.g. panel/analyze/debate). Default is human-readable; `--check` produces
a policy-grade verdict (JSON + exit code).

### 3.4 Skill execution types

Skills vary in what they execute. Four types cover all current and planned cases:

| Type            | Execution                                   | Examples                                    |
| --------------- | ------------------------------------------- | ------------------------------------------- |
| Pure Python     | Deterministic function                      | TDD policy, pattern matching, `run_tests()` |
| Single LLM      | `core.llm` API call                         | Tagger, checker                             |
| Claude session  | `claude -p [--bare]` subprocess (has tools) | Reviewer, panel/analyze worker              |
| Pure text (.md) | Markdown instructions sent to `claude -p`   | Review resources, analyze, debate prompts   |

Claude session subprocesses use `--bare` when `ANTHROPIC_API_KEY` is in the environment (skips hooks, LSP, plugin sync,
skill walks for faster startup). `--bare` disables OAuth/keychain auth, so it is only safe when an explicit API key is
available. They are full Claude Code agents (Read/Grep/Bash/Write) but cannot invoke skills that spawn more subprocesses
(`FORGE_DEPTH` prevents recursion at depth >= 2 as defense-in-depth). Pure text (.md) is a markdown prompt run in that
environment.

Skills can declare `effort: high|medium|low` in their SKILL.md frontmatter (Claude Code 2.1.80+). This overrides the
model effort level when the skill is invoked -- useful for deep-analysis skills (`analyze`, `debate`) that benefit from
maximum reasoning. This is orthogonal to proxy-level `reasoning_effort` hyperparameters, which control the routed
model's behavior.

Forge injects `claude --effort` per-caller on its automated `claude -p` subprocesses (never the user's interactive
session). Each consumer carries its own optional effort field and, where a CLI exists, an `--effort` flag: the Claude
arm of the supervisor frontier (`supervisor_effort`), memory writer (`MemoryWriterConfig.effort`), shadow curation
(pass-through), team supervisor (`TeamSupervisorConfig.effort`), and the workflow fan-out
(`run_multi_review(reasoning_effort=...)`). For consumers with both Claude and Codex arms, this field affects only the
Claude dispatch; the Codex arm uses its own runtime configuration. The central Claude builder is `run_claude_session`
(`core/reactive/session_runner.py`); the review fan-out builds its argv in `review/engine.py:_prepare_worker`. These use
the `claude --effort` vocabulary (`low/medium/high/xhigh/max`), distinct from the tier-1 checker's `core.llm`
`reasoning_effort` (`none/low/medium/high/xhigh`) — the checker is an API call, not a `-p` subprocess. An older `claude`
that rejects `--effort` fails loud (no silent rerun at default), unlike the `--output-format` telemetry retry. There is
no global default effort knob; effort is per-caller by design.

This maps to the three reactive node types in §1.2 (Code, LLM call, headless agent). "Pure text" is a specialization: no
Python runtime deps, so the prompt is portable across models/runners (the execution environment still has tools).

### 3.5 Workflow runners

Multiple skills compose smaller skills into orchestrated loops. Forge recognizes a small set of **fundamental workflow
runners**: reusable Python functions in `core/reactive/` that each implement one loop pattern.

**Three-layer architecture:**

| Layer | What                 | Lives in                  | Examples                                         |
| ----- | -------------------- | ------------------------- | ------------------------------------------------ |
| 1     | Abstract runners     | `core/reactive/`          | Fan-out, adversarial, linear, actor/critic       |
| 2     | Skill resources      | `src/skills/*/resources/` | Review resource .md, analyze prompt, tagger      |
| 3     | Concrete invocations | `src/skills/*/SKILL.md`   | `/forge:panel`, `/forge:debate`, `/forge:review` |

Layer 3 entry points wire a runner (Layer 1) to specific resources (Layer 2). The same runner/resource can be combined
differently by different entry points.

**Four fundamental runners (conservative set):**

| Runner         | Loop pattern                                 | Status            | Current implementation                 |
| -------------- | -------------------------------------------- | ----------------- | -------------------------------------- |
| Linear         | A → B → C (sequential)                       | Exists            | WorkflowPolicy pipeline, Stop pipeline |
| Fan-out/Fan-in | N workers parallel → collect → synthesize    | Exists, enhancing | `run_multi_review()`                   |
| Adversarial    | N workers with stances, blinded → synthesize | Exists            | `run_adversarial()`                    |
| Actor/Critic   | Generate → critique → iterate                | Pattern exists    | Ralph-wiggum verification loop         |

**Design principles:**

- Python, not YAML — continues the "library, not framework" approach
- Each runner takes skills, returns structured output
- Callable from skills (on-demand) and policies (automatic)
- Conservative set: fundamental patterns only

The **fan-out runner** (`run_multi_review()`) shapes one already-routed `HeadlessRequest` per worker (model/proxy +
optional per-worker prompt) and delegates the parallel lifecycle -- per-worker process groups, `os.killpg`
SIGTERM->SIGKILL cleanup, `ThreadPoolExecutor`, and deterministic `result_map[idx]` ordering -- to a headless invoker
(`core/invoker/`). That lifecycle is now runtime-neutral: it lives in `_HeadlessLifecycleBase` (`_lifecycle.py`), and
two concrete invokers fill template hooks (`_prepare_argv`/`_build_result`/`_emit`/`_is_recoverable_format_rejection`).
`ClaudeHeadlessInvoker` (the review caller) requests capability-gated `--output-format json`; `CodexHeadlessInvoker`
runs `codex exec --json` and reduces its JSONL event stream via `parse_codex_jsonl_stream` (Codex's predicate is always
`False`, so the JSON-retry branch is dead for it). Both emit one per-worker usage event when a request carries
attribution (run/model/status/latency; cost null -- the verb aggregate holds the estimated total). The **adversarial
runner** constrains workers to review/eval skills with stance injection (`{stance_prompt}`), mandatory blinding (no peer
outputs), and evidence-weighted synthesis.

**Runtime registry (`core/runtime/`).** The capability half of the runtime seam (the invoker above is the lifecycle
half). A frozen `RuntimeSpec` per runtime in a module-level `RUNTIMES` table (mirrors `core/credential_registry.py`'s
`Credential`/`CREDENTIALS` pattern) answers seven capability questions without hard-coding Claude Code assumptions:
installed (`is_installed()` = PATH presence; `detect()` = best-effort `--version`), interactive, headless, hooks, usage
source, native resume, and install scopes (plus curated-transfer in/out). Limited or planned support is a multi-state
`Literal`, not a `bool` — a field-reading consumer never mistakes a Codex limit for Claude parity. Codex's load-bearing
declarations (`enrollment_gated` hooks, `partial` pretool policy, `default` interactive) are enumerated with their probe
evidence in [design_appendix.md §I.2](design_appendix.md#i2-codex-runtimespec-declarations).

`forge runtime list [--json]` renders the matrix. `CodexHeadlessInvoker` and the auth/runtime preflight read it (e.g.
`get_runtime("codex").headless_cmd` builds the `codex exec` argv; the preflight checks the version gate).

### 3.6 Relationship to policies (workflow unification)

Skills and policies are the **same building blocks with different triggers**:

|          | Policies                              | Skills                              |
| -------- | ------------------------------------- | ----------------------------------- |
| Trigger  | Hook event (automatic, on Write/Edit) | Agent/user invocation (on demand)   |
| Output   | Allow/deny decision                   | Information for agent to synthesize |
| Latency  | Adds overhead to every action         | Zero overhead until invoked         |
| Use case | Continuous enforcement                | Deliberate checks                   |

Both compose from the same primitives: `core/reactive/`, `core.llm`, and runtime-specific headless paths
(`run_claude_session()` / `CodexHeadlessInvoker`). Shared code is imported by both CLI commands and policy classes—no
workflow registry, no declarative config layer. Library, not framework.

**CLI surfaces (normative):** Forge uses two related command surfaces:

1. **Policy** — deterministic/semantic policies evaluated against an action context.

   - Hook surface: `forge hook …` invokes policies automatically.
   - Manual surfaces: `forge policy check …` evaluates deterministic bundles, while `forge policy supervisor evaluate …`
     runs one-shot semantic supervision (after a hook blocks you, or in CI).

   **Stuck playbook (target UX):** When a PreToolUse policy blocks repeatedly, give the human an escape hatch without
   uninstalling hooks.

   - **Disable enforcement in-session:** `%policy disable` (hook becomes a no-op for this session)
   - **Fix the issue:** work with the agent or edit manually while enforcement is disabled
   - **Confirm you're unblocked (optional):**
     - `%policy check`: defaults to `git diff` (unstaged), supports `--staged`, and uses the session's effective bundles
       when no `--bundle` is supplied.
     - Terminal fallback: `git diff | forge policy check --bundle tdd --bundle coding_standards --diff`
   - **Re-enable enforcement:**
     - `%policy enable --bundle tdd [--bundle coding_standards]`: explicitly sets the override bundles for the session;
       positional bundle names are also accepted. Bare `%policy enable` shows usage.
     - Terminal `forge policy enable` likewise requires at least one explicit `--bundle` and fails loud with none; it
       writes session intent, while the `%` form writes session overrides.

   `forge policy check` (and `%policy check`) are diagnostics; you're unstuck once enforcement is re-enabled and the
   next Write/Edit passes the hook.

2. **Run** -- multi-step workflow runners (fan-out, debate, etc.).

   - Default: `forge workflow <workflow>` returns a human-readable result.
   - Gate mode: `forge workflow <workflow> --check` forces a policy-grade verdict contract (structured JSON + exit
     code).

**No auto-promotion:** A workflow does not automatically appear as a Policy. If a Policy wants to use a workflow, it
invokes the workflow's `--check` surface explicitly.

**Workflow runners unify skills and policies.** The same runner is usable from:

- Skills (agent/user invoked)
- Hooks/policies (automatic gate via `--check`)
- CLI manual runs (human debugging)

### 3.7 Panel (fan-out reference skill)

Panel is the reference invocation of the fan-out runner. It fans out a review task to N models via different proxies and
collects independent findings for synthesis. Each reviewer is a full Claude Code agent (can read files, investigate,
find issues with real file:line evidence). The main agent synthesizes all N reviews -- identifying consensus findings,
unique insights, and conflicts -- with full project context to investigate disputes.

**Dual use:** The panel serves as both a skill (`/forge:panel src/session/ --code`) and a policy (automatic multi-model
gate before committing). Same `run_multi_review()` function, two callers -- the programmer wires both. `/forge:analyze`
is a degenerate fan-out (N=1) with an analyze-specific resource.

### 3.8 Debate (adversarial reference skill)

Debate is the reference invocation of the adversarial runner. It assigns stances (for/against/neutral) to workers,
blinds them from each other (separate `claude -p` processes, no `--resume`), and synthesizes by weighing agreement
against disagreement. Stances influence the evaluative lens, not honesty -- all stances include ethical guardrails. Only
review/evaluation skills are adversarial-compatible (runner checks for `{stance_prompt}` marker).

> Detailed runner configs, debate protocol, and operational constraints (recursion guard, JSON output contract, child
> process lifecycle, script dependency tiers) in [§4](#4-workflow-runner-and-skill-details).

---

## 4. Workflow Runner and Skill Details

Reference details for [Skills Architecture](#3-skills-architecture).

### 4.1 Fan-out runner details (from §3.5)

`run_multi_review()` in `src/forge/review/engine.py`:

- N workers, each with model/proxy via `ModelSpec`
- Per-worker prompt via `ModelSpec.prompt`
- Per-worker context: `--context resume:<id>` or `--context blind`
- Direct Claude workers use `ANTHROPIC_MODEL` plus `ANTHROPIC_DEFAULT_*_MODEL`, not Claude CLI `--model`
- Parallel via `ThreadPoolExecutor` + process group cleanup
- Workers receive pre-resolved `RoutingResult` from a `WorkerRoutingPlan` (see
  [design_appendix.md §G](design_appendix.md#g-subprocess-routing-reference))
- `/forge:analyze`: single-model fan-out with an analyze resource

### 4.2 Adversarial runner details (from §3.5)

Adversarial runner:

- Constrained to review/eval skills (stance injection)
- Inject stance via `{stance_prompt}` in resources
- Mandatory blinding: proposal + files only (no peer outputs)
- Stances: for/against/neutral with guardrails (lens, not honesty)
- Synthesize agreement vs disagreement; evidence-weighted recommendation

Adversarial-compatible skills include `{stance_prompt}` in their resource .md; `/forge:debate` enforces this.

### 4.3 Panel engine details (from §3.7)

Panel is the reference invocation of the fan-out runner. It fans out a review task to N models via different proxies and
collects independent findings for synthesis.

**Engine:** `forge workflow panel` CLI command.

Spawns N `claude -p` subprocesses, each with a different `ANTHROPIC_BASE_URL`. Routing for all panel workers is resolved
once at invocation start via `resolve_invocation_routing()` (see
[design_appendix.md §G](design_appendix.md#g-subprocess-routing-reference)). Each reviewer is a full Claude Code agent
-- it can read files, investigate, and find issues with real file:line evidence.

**Execution:** Fork mode gives each reviewer the main agent's full context. Summary mode sends a focused prompt.

**Target-based review:** Positional `target` argument loads a bundled review framework (docreview.md by default,
codereview.md with `--code`). Combined with per-worker prompt support (`ModelSpec.prompt`), this enables specialized
fan-out patterns -- code review, document review, security audit -- all using the same runner.

**Synthesis:** The main agent reads all N reviews and synthesizes -- identifying consensus findings (2+ models agree),
unique insights, and conflicts. Because the main agent has full project context, it can **investigate conflicts** by
reading the disputed code -- something external synthesis (which merges text without context) cannot do.

**`/forge:analyze` as degenerate fan-out:** Single-model fan-out with an analyze-specific resource. Same panel engine
with N=1. The resource instructs the model to act as a senior engineering collaborator with deep analysis guidelines.

**Dual use:** The panel serves as both a skill (`/forge:panel src/session/ --code`) and a policy (automatic multi-model
gate before committing). Same `run_multi_review()` function, two callers -- the programmer wires both.

### 4.4 Debate / adversarial reference skill (from §3.8)

Debate is the reference invocation of the adversarial runner. It assigns stances to workers, blinds them from each
other, and synthesizes by weighing agreement against disagreement.

**Stances:** Each worker receives a stance directive (for/against/neutral) injected via `{stance_prompt}` in the
evaluation template. Stances influence the evaluative lens, not honesty -- all stances include ethical guardrails that
override positional framing (a "for" evaluator must still flag genuine critical issues).

**Blinding:** Each worker sees only the original proposal + files + stance prompt. Workers never see other workers'
output. Achieved by spawning separate `claude -p` processes without `--resume` (no shared session context).

**Skill constraint:** Only review/evaluation skills are adversarial-compatible. The runner checks for a
`{stance_prompt}` marker in the evaluation resource and rejects resources without it. This prevents misuse (adversarial
code generation makes no sense).

**Templates:** Two debate evaluation frameworks (embedded in CLI): a proposal evaluation template (7-point: feasibility,
correctness, trade-offs, risks, completeness, alternatives, recommendation) and a code evaluation template (5-point:
quality, security, performance, architecture, risks). `--code` selects the code template. Both produce structured
verdict output (Verdict/Confidence/Key Findings).

**Execution flow:** Parse subject -> select template (proposal or code via `--code`) -> fill template with subject ->
write to temp file -> N x adversarial runner with stance injection -> collect results -> synthesize (agreement areas,
disagreement areas, evidence-weighted recommendation). Temp file cleaned up via try/finally.

### 4.5 Operational constraints

**Recursion guard:** Skills invoke `forge` commands. `forge` commands spawn `claude -p` subprocesses. Those subprocesses
trigger hooks. If a hook spawns another subprocess, you get recursion. `build_claude_env()` sets `FORGE_DEPTH` (starting
at 0, incremented per subprocess layer). Hooks that spawn subprocesses (supervisor, memory writer) skip at depth >= 2.

**Run-tree identity (attribution, orthogonal to the recursion guard):** alongside `FORGE_DEPTH`, `build_claude_env()`
stamps `FORGE_RUN_ID` (this process), `FORGE_PARENT_RUN_ID` (the spawner), and `FORGE_ROOT_RUN_ID` (the tree root). A
child inherits the root and sets its parent to the spawner's run_id; an interactive launch (session start/resume/fork,
bare `forge claude start`) and the sidecar instead mint a fresh root (`invoke._build_environment` / `container.py`, via
`derive_run_identity=False`). Depth guards recursion; identity records who-spawned-whom for the usage ledger — the two
are independent and `FORGE_DEPTH` is never reinterpreted. The queue-decoupled memory writer is the one spawn where env
inheritance breaks: the Stop hook snapshots the originating session's run id into the handoff marker
([design_appendix.md §B.1](design_appendix.md#b1-marker-schema-v2)) and the drain handler re-roots the detached process
under it, not under the unrelated draining CLI.

**JSON output contract:** `forge` commands invoked by skills must support `--json` for structured output. Skills should
never parse human-readable CLI text -- it drifts. JSON schemas are the API contract between skills and CLI.

**Child process lifecycle:** Parallel fan-out (panel runner) spawns N `claude -p` processes. If the parent is killed
(Ctrl+C), children must be terminated via process group signal (`os.killpg`). All child processes must have timeouts
(the `timeout_seconds` parameter in `run_claude_session()`).

**Skill script dependency tiers:** Skills are installed by file copy (`forge extension enable`), not as Python packages.
Scripts in `skills/*/scripts/` have no access to `forge.*` imports or third-party deps. Three tiers handle this:

| Tier               | When                                                | How                                                    | Example                                |
| ------------------ | --------------------------------------------------- | ------------------------------------------------------ | -------------------------------------- |
| Pure stdlib        | Script needs only Python builtins                   | `python3 script.py`                                    | `walkthrough-state.py`                 |
| Forge CLI command  | Script needs `forge.*` or third-party deps          | `forge <group> <cmd>`                                  | `forge hook stop`, `forge status-line` |
| `uv run` + PEP 723 | Script needs 1-2 external deps, not worth a CLI cmd | `uv run script.py` with inline `# /// script` metadata | --                                     |

**Graduation rule:** When a pure-stdlib script needs deps, promote it to a Forge CLI command (one step, no intermediate
stages). This follows the hooks pattern: `forge hook <name>` runs as a CLI command with full package deps, not as an
installed script. The same principle applies to skill scripts.

---

## 5. Designated Memory Docs

Cross-session continuity via designated markdown files that sessions keep updated—no knowledge graphs or async
synthesis.

Forge memory has three layers; this section covers **project memory** -- the designated docs the memory writer curates:

| Layer               | What it holds                                           | Location                  |
| ------------------- | ------------------------------------------------------- | ------------------------- |
| **Raw memory**      | Transcripts, plans, artifacts, reports (§3.8)           | `.forge/artifacts/`       |
| **Project memory**  | Passported docs (changelog, impl notes) -- this section | `docs/`, `.forge/memory/` |
| **Transfer memory** | Curated context for fork/resume (§3.9)                  | `.forge/prev_sessions/`   |

The **memory writer** curates project memory at Stop time; **transfer** (§3.9) assembles context for a child session.

The simplest memory system is:

1. Designated markdown files with templates
2. Sessions read them at start (via CLAUDE.md references)
3. Sessions update them before ending
4. Next session gets current state

### 5.1 Memory writer (automated doc maintenance)

The memory writer runs at session end to fill gaps automatically:

```
Stop hook → spawn memory writer → reads transcript + current docs → updates
```

The memory writer runs `claude -p` (headless prompt mode) on the full session transcript. It operates
**retrospectively**, selecting what mattered with full-session hindsight (higher signal than incremental capture).

```yaml
# In session intent (set via forge session memory enable or --memory on)
memory:
  auto_update:
    enabled: true
    mode: augment              # augment (add missing) | review-only (dry run)
    proxy: litellm-haiku       # cheap model for summarization
    min_turns: 5               # skip for very short sessions
```

**Multi-agent workflow:** In parallel runs, each agent spawns its own memory writer. `augment` mode stays additive (no
overwrites).

### 5.2 Memory doc passports

Each memory doc may include a `forge_memory` YAML frontmatter block -- the doc's **passport**. The passport is the
authoritative contract for that doc's intent, update strategy, and writer privileges. The memory writer re-reads
passports at Stop time. Newly tracked Markdown docs also receive a small outer metadata envelope that is structurally
compatible with the pinned OKF v0.1 concept shape:

```yaml
---
type: Memory Document
title: Change Log
description: Compact completed-work record for Forge implementation sessions.
forge_memory:
  version: 1
  intent: "Compact completed-work record for Forge implementation sessions."
  captures: [completed work, verification, deferred follow-ups]
  excludes: [pending task plans, raw session summaries]
  update:
    instruction: "Add compact newest-first entries with Goal, Key changes, and Verification."
    strategy: changelog
    mode: direct
    writers: all-sessions
    compact_when: "approaching documentation size limits"
---
```

`forge_memory` is the only marker of active Forge tracking. The outer `type`, `title`, and `description` keys describe
the document but do not make an OKF-only document Forge memory. Forge owns the `forge_memory` value; outer keys are
producer-owned and preserved at the parsed-value level when Forge rewrites frontmatter. On a new track, Forge adds
missing `type` (`Memory Document`), `title` (the first ATX H1 outside a fenced code block, then a filename fallback),
and `description` (the passport intent with whitespace collapsed). A present non-empty string `type` is preserved,
including an unknown value; a present null, non-string, empty, or whitespace-only `type` blocks envelope generation on a
new track or explicit upgrade.

Forge does not generate or maintain `resource`, `tags`, or `timestamp`. It cannot authoritatively timestamp meaningful
human and agent edits, and strategy-derived tags would become stale after later passport changes. Successful rewrites
preserve existing outer values semantically, but do not promise preservation of YAML comments, anchors, quoting, key
order, scalar spelling, or line endings.

**Ownership split**: passports own doc-level policy (strategy, intent, writers). Session manifests own activation state
(enabled, mode, min_turns). There are no session-scoped doc lists; all docs are discovered from passports at Stop time.
Editing a passport between sessions takes effect without re-running `forge memory track`.

**Writer semantics**: `all-sessions` and exact session-name writers are supported. `lineage:` and `role:` prefixes are
rejected with deferral messages. Writer access is checked at Stop time by the memory writer.

**Passport CLI**: `forge memory track --strategy <strategy>` synthesizes a passport and envelope for a Markdown doc
without a passport. Re-tracking an existing passport updates only the requested Forge contract; it never adds or repairs
the outer envelope. `forge memory passport upgrade <path>` is the explicit migration for an existing passport: it adds
only missing envelope fields while preserving the raw `forge_memory` value. `forge memory passport show <path>` displays
passport fields, and `remove` deletes only `forge_memory`, leaving outer metadata in place.

### 5.3 Two operating modes

The memory writer has two distinct modes:

**Mode 1: Direct Update** — agent updates the doc in place per strategy. Used for project docs the agent is allowed to
maintain.

**Mode 2: Shadow/Propose** — the agent is the proposer, the human is the author. `forge memory track --propose` derives
a shadow path under `.forge/memory/` (encoding the immediate parent directory for disambiguation). The agent reads
transcript + official doc, proposes additions to the shadow; the human reviews and merges at their own pace.

Shadow curation: `forge memory shadows review --for <doc> --curate` runs an LLM pass that reads the official doc plus
matching shadows, removes duplicates and already-promoted notes, groups related suggestions, and emits source-cited
output. Curation reports persist at `.forge/artifacts/<session>/memory/curation-{slug}-{hash}-{ts}.md`. Curation never
mutates official docs.

### 5.4 Memory activation on fork and fresh resume

Children inherit the parent's memory activation by default. The `--memory` flag overrides:

```bash
forge session fork parent                    # inherit parent's memory on/off
forge session fork parent --memory on        # force memory on in child
forge session fork parent --memory off       # force memory off in child

forge session resume parent --fresh          # inherit parent's memory on/off
forge session resume parent --fresh --memory off
```

Inheritance copies only `auto_update` (enabled, mode, min_turns, proxy). Other `MemoryIntent` fields do not propagate.
`--memory off` writes an explicit `MemoryWriterConfig(enabled=False)` so the child is deliberately off even if later
defaults change. `--memory on` reuses the parent's non-enabled config (mode, proxy, min_turns) or `MemoryWriterConfig`
defaults.

Memory docs are not inherited. Passports are git-tracked and discovered live at Stop time in whatever checkout the child
session runs in. This applies equally to same-checkout forks, `--worktree`, and `--into`.

### 5.5 Strategy registry

Per-doc strategies control how each file is updated. Strategies are defined in `MemoryStrategy` enum in
`src/forge/session/passport.py` (single source for CLI, passport, and memory-writer prompts).

**No file creation.** Designated docs must already exist; missing files are skipped. Humans choose which docs to
maintain; the agent maintains them. `forge memory track` enforces this at configuration time; runtime skip handling
remains for stale manifests.

Direct update strategies: `project-state`, `checklist`, `changelog`, `generic`. Shadow mode (`--propose`) works with any
strategy.

The memory writer resolves designated doc paths relative to `forge_root`, so git-tracked docs target the correct branch
in worktrees. Trackedness is controlled by path choice -- the writer doesn't distinguish.

**Relationship to Claude Code auto-memory:** Complementary, not competitive. Auto-memory captures during sessions
(incremental, free-form); the memory writer synthesizes after sessions (retrospective, per-doc strategies). The memory
writer deliberately does not read auto-memory — different targets, different information, occasional duplication is
cheaper than cross-format deduplication.

> Strategy tables, example config, worktree resolution details, and full auto-memory comparison in
> [§6](#6-memory-doc-reference).

### 5.6 Session-scoped activation

Memory activation is session-scoped. Each session decides whether the memory writer runs via
`intent.memory.auto_update.enabled` (or an override). There is no checkout-level config file.

```bash
forge session memory enable                    # resolves $FORGE_SESSION
forge session memory enable --session planner  # named session
forge session memory disable --session planner
forge session start planner --memory on
```

Both gates (Stop-hook enqueue in `src/forge/cli/hooks/commands.py` and the detached runner `forge memory-writer run`)
check `effective.memory.auto_update.enabled` directly. Incognito sessions never enqueue regardless of activation state.

**Stop-time discovery.** When activation is on, the detached runner scans hardcoded roots (`docs/` plus
`.forge/memory/`) for `forge_memory` passports the session is authorized to write, materializes shadow files for
shadow-only passports, and passes the result to `run_memory_writer()`. Capped at 50 docs after filtering. The Stop hook
only decides whether to enqueue; the scan runs in the background runner.

**Scan roots** are hardcoded: `DEFAULT_SCAN_ROOTS = ("docs/",)` plus always `.forge/memory/`. Configurable roots are
deferred.

### 5.7 CLI verbs

- **`forge memory track <path>`** authors a **passport** (project-lifetime, git-tracked frontmatter). On a new Markdown
  doc it also fills the missing `type`, `title`, and `description` envelope fields. Re-track never migrates an existing
  passport. `--propose` authors a shadow-only passport on the official doc; an auto-created shadow file receives no
  envelope of its own. A passported doc outside the scan roots is written but warns.
- **`forge memory passport upgrade <path>`** explicitly adds missing envelope fields to an existing valid passport. It
  preserves the raw `forge_memory` mapping and is a byte-identical, exit-0 no-op when the envelope is complete.
- **`forge memory passport remove <path>`** removes only `forge_memory`, preserving outer and unrelated frontmatter.
- **`forge session memory enable`** / **`disable`** sets session activation (`memory.auto_update.enabled`). Resolves
  `$FORGE_SESSION` when `--session` is omitted; errors outside a session without `--session`.
- **`forge memory list`** shows passported docs under scan roots (sessionless scan, no writer filtering).

**Shadow discovery** scans passports under the scan roots for shadow-only docs (unfiltered by writer).

New tracking and explicit upgrade require a logical project-relative path ending exactly in `.md`. Logical and resolved
official basenames are compared case-insensitively against the OKF-reserved `index.md` and `log.md` names before any
official or shadow write. Proposal shadow paths use the same logical/resolved reserved-name guard, including custom
git-tracked shadows; they do not use the official document's `.md` envelope-generation check. Existing legacy passports
on reserved or non-Markdown paths remain readable, removable, and re-trackable without envelope generation. Discovery
skips a hand-authored shadow-only passport whose write target is reserved, so bypassing CLI authoring cannot route the
memory writer into an OKF index or log.

---

## 6. Memory Doc Reference

Reference details for [Designated Memory Docs](#5-designated-memory-docs).

### 6.1 Strategy registry (from §5.5)

Strategies are defined in `MemoryStrategy` enum (`src/forge/session/passport.py`).

**Direct update strategies:**

| Strategy        | Behavior                                         |
| --------------- | ------------------------------------------------ |
| `project-state` | Update focus, active work, decisions, next steps |
| `checklist`     | Mark `[x]` completed, add discovered tasks       |
| `changelog`     | Add accomplishments, follow existing format      |
| `generic`       | Add any new information (default fallback)       |

Shadow mode (`--propose`) is orthogonal to strategy: any strategy works with `--propose`.

### 6.2 Passport example (from §5.2)

Memory doc passports are `forge_memory` YAML frontmatter blocks. The passport is the doc-level source of truth for
strategy, writers, and update mode; the surrounding concept metadata is descriptive and producer-owned.

```yaml
---
type: Memory Document
title: Implementation Notes
description: Human-approved durable implementation memory for future Forge sessions.
forge_memory:
  version: 1
  intent: "Human-approved durable implementation memory for future Forge sessions."
  captures: [stable decisions, non-obvious invariants, recurring bug causes]
  excludes: [raw session summaries, pending tasks, unverified hunches]
  update:
    strategy: generic
    mode: shadow-only
    writers: all-sessions
    approval: human-promoted
    shadow_path: .forge/memory/shadow_impl_notes.md
---
```

**CLI setup** (equivalent to the passport above):

```bash
# Passports are project-lifetime and sessionless:
forge memory track docs/board/change_log.md --strategy changelog
forge memory track docs/board/impl_notes.md \
  --propose --shadow-path .forge/memory/shadow_impl_notes.md

# Enable memory for a session:
forge session memory enable --session planner

# Verify:
forge memory passport show docs/board/change_log.md
forge memory list

# Explicitly add the envelope to an older passport:
forge memory passport upgrade docs/board/change_log.md
```

`forge memory track` is idempotent and sessionless: re-running with different flags updates the passport in place; with
no flags on an already-passported doc it is a no-op. Existing passports gain the outer envelope only through
`forge memory passport upgrade`; ordinary re-track does not migrate them. `forge memory passport remove <path>` removes
only `forge_memory`, so any outer `type`, `title`, `description`, and other producer metadata remain. One-off doc
updates that don't need a passport are ordinary agent instructions. All docs are processed in one `claude -p` call with
per-doc strategy instructions.

This is document-shape compatibility for newly tracked and explicitly upgraded Markdown docs, not a declaration of an
OKF bundle. Forge does not generate bundle metadata or maintain reserved `index.md` / `log.md` files. In proposal mode,
the envelope belongs to the explicitly tracked official document. An auto-materialized `.forge/memory/` shadow does not
receive one unless a user later tracks that shadow as a separate memory document.

### 6.3 Worktree resolution (extends §5.5)

Managed sessions always launch from `forge_root`. The memory writer resolves designated doc paths relative to
`forge_root`, so git-tracked docs (for example, a card checklist under `docs/board/doing/<slug>/checklist.md`) target
the correct branch when working in a worktree.

Trackedness is controlled by path choice; the agent doesn't distinguish:

- `docs/board/doing/<slug>/checklist.md` -> git-tracked, branch-specific (moves with the branch)
- `.forge/memory/debugging.md` -> untracked, per-Forge-project (`.forge/` is in `.gitignore`)
- `docs/suggested/coding_standards.md` -> git-tracked shadow doc (visible in PRs if desired)

Shadow docs also resolve relative to `forge_root`, so the agent reads the branch-correct official doc.

**Transcript path handling:** Transcripts live under `<forge_root>/.forge/artifacts/`. Because `cwd` is `forge_root`,
transcript paths in the prompt must be **absolute**; designated doc paths remain relative (resolved against `cwd`).

> **Note:** Artifacts (transcripts/plans) consolidate at `forge_root` for per-project visibility. Designated docs are
> working documents and belong with branch content.

### 6.4 Comparison with Claude Code auto-memory (from §5.5)

Claude Code (Feb 2026) ships **auto-memory**: Claude writes free-form notes to `~/.claude/projects/<project>/memory/`
during sessions. `MEMORY.md` (first 200 lines) loads at startup; topic files load on demand.

Forge's memory writer is complementary, not competitive:

| Aspect          | Auto-Memory                  | Memory Writer                              |
| --------------- | ---------------------------- | ------------------------------------------ |
| Timing          | During session (incremental) | After session (retrospective)              |
| Signal quality  | In-the-moment judgment       | Full-session hindsight                     |
| Structure       | Free-form, model-organized   | Per-doc strategies with constraints        |
| Target files    | User-local memory dir        | Project docs (repo-tracked, shareable)     |
| Curation        | None -- entries accumulate   | Shadow pattern provides human review gate  |
| Graduation path | None                         | Shadow doc -> human review -> official doc |

**Key design rationale:** Free-form capture relies on model judgment and tends to accumulate noise over time. The memory
writer reduces this via (a) retrospective synthesis, (b) per-doc topic constraints, and (c) the shadow pattern (human
curation gate).

Auto-memory is better for long-lived preferences; the memory writer is better for structured project docs and proposed
standards evolution.

**Deliberate non-integration:** The memory writer does not read auto-memory (`~/.claude/projects/<project>/memory/`) as
input. It's outside the project root (containment guard), is free-form (hard to dedupe against structured strategies),
and targets different information (preferences/patterns vs project state/standards). Occasional duplication is cheaper
than cross-format deduplication. If overlap becomes painful, a small prompt tweak can address it.

### 6.5 Session activation (from §5.6)

Memory activation is session-scoped. The effective `memory.auto_update.enabled` (intent + overrides via
`compute_effective_intent()`) is the sole gate. No checkout-level config file.

| Field                   | Type        | Default   | Meaning                                    |
| ----------------------- | ----------- | --------- | ------------------------------------------ |
| `auto_update.enabled`   | bool        | `false`   | Whether the memory writer runs at Stop     |
| `auto_update.mode`      | str         | `augment` | `augment` (edit) or `review-only` (report) |
| `auto_update.min_turns` | int         | `5`       | Skip sessions shorter than this            |
| `auto_update.proxy`     | str \| null | `null`    | Optional `proxy_id` for the memory writer  |

Scan roots are hardcoded: `DEFAULT_SCAN_ROOTS = ("docs/",)` plus always `.forge/memory/`. Configurable roots deferred.

**Stale `.forge/memory.yaml`**: existing checkouts may have this file from a previous version. It is no longer read.
Safe to delete.

**Stale `designated_docs` in manifests**: old session manifests may contain `designated_docs` entries. These are
stripped on read with a one-time `logger.warning()` per coding-standards §5. The field no longer exists on
`MemoryIntent`.

---
