# Epic: Budgeted review guards

**Epic** -- coordinating card for the member cards below (see `board_contract.md` "Epics"). Lane: `proposed/` --
incident-driven guardrail design, not yet accepted for execution.

**Origin**: a session incident on 2026-07-08. The user intended to exercise Forge's conservative review path but
accidentally approved Claude Code's native/built-in code review behavior. Letting it run showed the failure mode: a
review-shaped command can consume a large fraction of a weekly subscription allotment without an explicit budget, scope
estimate, or stop-before-spend checkpoint.

## Problem

Code review sounds bounded. Users reasonably expect "look at the target/diff and report findings," not an unmetered
repository exploration that burns subscription quota.

Forge's own `/forge:review` skill is already prompt-conservative: it preflights, selects one instruction resource,
scopes the target, and delegates to a bounded Explore-style pass. The incident was not caused by that skill. It came
from a native Claude Code review path that bypassed Forge's review discipline.

The deeper product problem is that Forge has no enforced admission envelope around expensive review-like work:

- native Claude Code review can be approved by mistake and begin spending before Forge can steer it;
- instruction-only skills can request subagents but have no numeric agent or token cap;
- workflow skills can fan out across multiple workers unless the engine enforces a budget;
- direct subscription sessions do not produce proxy cost rows, so users may only discover the burn after the fact.

There is also a structural gap: Forge's policy system protects **the plan** (supervisor, TDD) through session-owned,
opt-in enforcement. A surprise-cost guard protects **the user who configured nothing**, and session-opt-in enforcement
structurally cannot reach that user. Closing that gap is this epic's shared substrate (M0).

## Incident Evidence

The observations that motivate this epic:

- The session ran direct Claude (no Forge proxy), so `forge telemetry activity` showed subagent activity but no proxy
  spend rows -- Forge's cost ledger could neither see nor cap the burn.
- Transcript usage counters showed multi-million-token activity for a single review command, dominated by cache-read
  tokens across many fresh subagent contexts. These are transcript counters, not Forge proxy billing records, but the
  lesson holds: a native review path can create multi-million-token activity outside the proxy.
- A partial run (stopped after the finder phase) consumed a double-digit percentage of a weekly subscription allotment
  -- an API-rate-equivalent cost on the order of a monthly plan price from one mistaken approval.

This pricing inversion matters for safety. A flat subscription plan and an API-rate plan expose different economic
realities for the same underlying work: consumer quota hides the dollar cost until the cap is hit, while API-rate usage
would make the cost visible before or after each run. Guardrails should therefore report both subscription-quota impact
and API-equivalent cost when possible. "No invoice" is not "no spend"; it is a spend against scarce capacity.

### Executor-side mechanics (general observations from inside the session)

- **Skill-selection collision steered the routing.** The session exposed three review-shaped skills: Forge's `review`,
  the built-in PR `review`, and the built-in `code-review`. The built-in PR skill's own description says "for your
  working diff use /code-review", so prose like "review the current changes in the branch" routes to the native
  `code-review` skill ahead of Forge's. The guard cannot assume the model picks the conservative skill when names
  collide.
- **The expensive shape is encoded in the skill protocol, not chosen adaptively.** At `xhigh` effort the native protocol
  mandates 10 parallel finder agents, one verifier agent per surviving candidate (~40 were pending), and a sweep agent
  -- fixed counts regardless of diff size. The user's stop landed after the finder phase, so the observed burn is
  roughly half of the protocol's full course.
- **Cost scales as agents x context floor.** Each finder independently loaded repo instructions, source files, and a
  roughly 4,000-line diff before doing any work; the finders with visible counters each spent on the order of 100k
  subagent tokens, dominated by cache reads across fresh contexts. Total agent count, not concurrency, is the cost
  driver.
- **The consent moment carried no cost semantics.** The approval dialog named a skill ("code-review"), which reads as
  "look at the diff and report findings" -- nothing at the decision point said "this will spawn ~50 agents". Every input
  for a preflight estimate (diff size, protocol agent counts, per-agent context floor) was available as plain arithmetic
  before fan-out.

## Control-Plane Requirements

Any agentic loop that can autonomously continue work, spawn workers, or expand scope must have a control plane before
the loop starts, and approval is not meaningful consent unless the user can see it at the decision point:

- **scope estimate**: what paths, docs, diffs, tools, and workers can be touched;
- **budget estimate**: expected token range, admission ceiling, and synthesis reserve;
- **concurrency limit**: maximum parallel workers and maximum total workers -- total is the cost cap, parallelism only
  the burn rate;
- **adaptive plan**: how the loop narrows when the budget is insufficient;
- **stop rule**: an admission rule that stops scheduling before estimated remaining work spends the reserve;
- **receipt**: final accounting for reviewed scope, skipped scope, and observed usage;
- **fallback**: a clear degrade path when the cap is too small for the requested scope.

Guard testing must include constrained-user scenarios, because budget bugs are invisible to internal power users with
high quota tolerance: a small remaining weekly balance, colliding review-skill names, an accidental repo-wide target, a
multi-agent path where fan-out drives the burn, and a direct-runtime path where proxy spend caps do not apply.

## Decisions

- **D1 -- ambient activation scope, not a new policy type and not a dedicated hook handler.** The guard is an ordinary
  deterministic policy; what is new is its activation **scope** (global default-on, session opt-out) alongside the
  existing session-scoped opt-in bundles. Implementing it inside the policy engine reuses contracts that already exist
  and are regression-pinned -- the three-tier deny message with `Intent:`, runtime responders for tools each runtime
  actually exposes, upstream/decision-log observability, and the `forge policy check` diagnostic surface. A dedicated
  handler would be fewer lines now and four parallel drift surfaces forever. (`read-hygiene` is prior art for the
  one-off-handler shape; it becomes a migration candidate once M0 exists, not a pattern to repeat.)
- **D2 -- guard config home is global runtime config; opt-out is a session override.** Defaults live in a
  `policy.guards:` section of `~/.forge/config.yaml` (strict `forge config set`/`edit` gate, fail-open loader -- the
  established runtime-config pattern). The ownership test is "who reads it": the guard must be readable by a hook with
  no session manifest (bare `claude` in an enrolled repo) and by managed sessions alike; only runtime config satisfies
  both. Session opt-out rides the existing overrides mechanism, so the opt-out is discoverable and auditable in the
  manifest. Precedence: session override > global config > built-in default. Today only proxied sidecars mount
  `~/.forge/config.yaml`; M0 must move the read-only config mount into the common sidecar path so direct-subscription
  sidecars receive the same guard configuration.
- **D3 -- warn-first default ramp.** Guard modes are `block | warn | budget-required | allow`. Ship with default `warn`
  (visible preflight estimate on every native-review fan-out, no blocking), then flip the default to `budget-required`
  once the deny message and opt-out UX have been exercised in real sessions. A blocking default before the escape hatch
  is proven is how a guardrail becomes the next incident report.

### Resolved operational decisions

- **`%policy disable` disables both scopes for that session.** M0 adds an explicit `policy.ambient_guards_disabled`
  session override; `%policy disable` sets it while disabling session bundles, and `%policy enable` clears it when
  re-enabling policy. Per-guard escape uses `%policy guard disable|enable <guard>` backed by `policy.disabled_guards`.
  The guard posture `block` is therefore never confused with opt-out state.
- **Malformed guard config fails open independently of defaults.** A missing `policy.guards` section receives built-in
  defaults. A present but malformed section is marked invalid and evaluates no ambient guards for that load, even after
  the built-in default later flips to `budget-required`; `forge config set`/`edit` remain strict. The invalid state is
  also visible from `forge extension doctor [--json]` and `forge policy status`, not only a hook-time warning.
- **Terminal and direct-command ambient mutations share command-core ops.** Today `forge policy enable|disable` authors
  intent while `%policy enable|disable` authors overrides; that existing baseline distinction remains intentional. M0
  extracts shared ops for `ambient_guards_disabled` and `disabled_guards`, and both surfaces call those ops so the new
  ambient semantics cannot drift.
- **Token ceilings are admission estimates, not provider hard caps.** Hard guarantees cover worker-count admission and,
  once lifecycle probes pass, simultaneous-worker admission. Direct-runtime token usage is observed after completion and
  can stop later scheduling, but cannot terminate an already-running provider turn.

### Decisions owed

- **Exact PreToolUse tool names for the fan-out matchers** (owner M0). The incident observed `PreToolUse` on the Skill
  and Agent tools; the registered matcher strings must match the runtime's actual tool names across Claude versions --
  pin by probe before registering.
- **Review/agent correlation through existing `SubagentStop`** (owner M0 probe, M2 state contract). Forge already
  registers observe-only `SubagentStop` and receives `agent_id`; pin whether that id correlates to the launching
  PreToolUse Agent call and whether the event fires for failure/cancellation. Also pin the guarded Skill operation id
  and how Agent launches identify that parent. If Forge cannot distinguish review-owned agents from unrelated agents in
  the same session, native review caps cannot ship as operation-scoped enforcement. If only completion correlation is
  missing, native `max_parallel_agents` must remain an estimate.
- **User-typed `/review` visibility** (owner M1, phase 0 probe). Assistant-initiated review is observable today; the
  user-typed slash-command path is unprobed.

## Members

| Id  | Card                                                            | Delivers                                                                         | Depends on |
| --- | --------------------------------------------------------------- | -------------------------------------------------------------------------------- | ---------- |
| M0  | [ambient_policy_scope](../ambient_policy_scope/card.md)         | Engine second activation scope, `policy.guards` config, opt-out UX, new matchers | --         |
| M1  | [native_review_guard](../native_review_guard/card.md)           | The native-review guard policy (`block/warn/budget-required/allow`)              | M0, M2     |
| M2  | [review_budget_envelope](../review_budget_envelope/card.md)     | Budget schema, agent-counter state, and workflow preflight enforcement           | M0         |
| M3  | [adaptive_review_behavior](../adaptive_review_behavior/card.md) | Single-agent narrowing, workflow batch scheduling, and coverage receipts         | M2         |

**Sequencing**: M0 first -- activation and hook vocabulary before enforcement. M2 follows with the envelope schema,
agent-counter state contract, and workflow admission checks. M1 then consumes both M0 and M2 for native-review policy;
M3 can proceed after M2 in parallel with M1 because it adapts Forge-owned review surfaces rather than native review.

## Shared-Contract Seams (drift watch)

- **Seam 1** -- `policy.guards` runtime-config schema + the precedence rule (session override > global > built-in).
  Owner M0; M1 reads.
- **Seam 2** -- budget envelope schema. Owner M2; M1 (`budget-required` mode) and M3 (adaptive narrowing) read.
- **Seam 3** -- registered PreToolUse matcher rows for the fan-out tools. Owner M0. Byte-identity is the API: new rows
  in the registered-command contract golden, delivered to existing installs via `forge extension sync`.
- **Seam 4** -- deny-message contract (three-tier + `Intent:`) stays engine-owned; members supply intent text only.
- **Seam 5** -- agent-budget state: rollover-stable guard-operation key, runtime-session-id aliases, invocation
  correlation id, locked total/active counters, `SubagentStop` decrement, compact migration, stale-state cleanup, and
  Stop cleanup. M2 owns the state contract; M1 consumes it.
- **Seam 6** -- ambient mutation and diagnostics: terminal/direct commands share command-core ops; invalid guard config
  is consistently visible through doctor and policy status. Owner M0.

## Out of Scope

- Exact upstream Claude subscription billing math. Forge can record observed usage counters and guard decisions, but it
  cannot infer Anthropic's private allotment accounting perfectly.
- TLS or API interception for subscription traffic.
- Rewriting `/forge:review` from scratch. It should be hardened with enforcement, not replaced.

## References

- Forge review skill: `src/skills/review/content.md`, `src/skills/review/forge-skill.yaml`,
  `src/skills/review/resources/code.md`.
- Policy engine and composition: `docs/design_workflows.md` sections 1-2.
- Registered hook inventory: `src/forge/install/preset.py`; contract golden
  `tests/src/install/test_registered_commands_contract.py`.
- Hook ownership/card context: `docs/board/done/user_scope_hook_ownership/card.md`.
- Incident session transcript: local `.forge` artifacts (not committed).

## Closeout

(pending)
