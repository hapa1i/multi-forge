# Supervisor Cascade — cheap tier-1 plan check before the frontier supervisor

**Status**: Doing (branch `supervisor-cascade`).

## Problem

The semantic supervisor checks every throttle-missing Write/Edit (PreToolUse hook) by invoking
`claude -p --resume <planning-session> --fork-session` — a frontier-model call over the planning session's full
~100-200K-token context. Most checks come back "aligned": the action is a routine step the plan already covers, and the
frontier's depth buys nothing. Every one of those routine checks still pays full frontier latency and cost.

## Design

Route checks through a cheap tier first; reserve the frontier for genuine uncertainty:

```text
PreToolUse Write/Edit (cascade ON)
  PolicyEngine.evaluate()
    +- deterministic bundles (unchanged)
    +- PlanCheckPolicy ("semantic.plan_check", regular policy)
    |    one cheap core.llm call: action vs approved-plan snapshot text
    |    -> allow (clearly aligned; cached via throttle window)  -> frontier never runs
    |    -> needs_review (uncertain / divergent-looking / ANY tier-1 error)
    +- resolver hop (only when needs_review && no deny):
         SemanticSupervisorPolicy registered as RESOLVER -> allow/warn/deny
cascade OFF (default): byte-identical to today -- supervisor runs as a regular policy.
```

Key decisions:

- **Tier-1 is a stateless `core.llm` direct call** (tagger pattern: `get_client` + `SyncAdapter`, gemini-flash-class
  default, ~$0.001, 1-2s). It judges only the approved-plan snapshot text plus the action in the prompt — no tools, no
  session context. The frontier keeps the resumed planning-session context.
- **Opt-in** via `forge policy supervise --cascade`. Conservative default until checker quality is measured.
- **Tier-1 never denies or warns.** It emits only `allow` or `needs_review`. Every tier-1 failure (LLM error, parse
  failure, unreadable plan) escalates — the system degrades to frontier-always, never to unsupervised, and the user is
  never blocked by tier-1 alone.
- **Tier-1 decisions carry reasons as low-severity violations, never `warnings`** — the hook prints composite
  `all_warnings` on the allow path, so a warning-bearing escalation decision would leak tier-1 noise on every
  successfully-resolved escalation. Violations persist into the decision log without printing on resolved allows.
- **The engine resolves `needs_review` via a registered resolver**, invoked only on escalation (and skipped when a
  deterministic deny already blocks). With no resolver, `needs_review` still blocks as unresolved — the existing
  contract.
- **Plan text precondition**: tier-1 requires `plan_override_path`. Enabling cascade auto-resolves it via the `--reload`
  supervision-graph search and fails with an actionable error if no approved snapshot exists.
- **Measurement built in**: `plan-check` usage-ledger events (session-tagged) show uncached call volume, tokens, and
  errors; decision-log-derived `plan_check_allow`/`plan_check_escalated` counters in `forge activity` give short-circuit
  vs escalation rates (cached allows included — the log records them; the ledger cannot).

## Risks

- Tier-1 false "aligned" silently skips the frontier. Mitigations: conservative prompt (aligned only when clearly
  consistent; uncertainty escalates), opt-in default, measurement to validate quality before any default flip.
- Old forge binaries cannot read manifests carrying the new `SupervisorConfig` fields (strict dacite read). Established
  precedent (`plan_override_path`, `suspended` were added the same way); no mitigation planned.
- Escalation stacks tier-1 latency (~2s) on the supervisor's 45s budget — within the 60s hook budget; timeout tuning is
  out of scope here.
- Supervisors configured with a raw UUID (`forge session set policy.supervisor.resume_id`) may have no resolvable plan
  snapshot; the wiring-time error covers this.
- Allow decisions carry no reason field, so the checker's aligned rationale is debug-logged only. Truly validating
  false-aligned rates needs shadow-sampling (run both tiers on a sample, compare verdicts) — follow-up idea, not built
  here.

## Deferred

- Cascade flag at `%policy supervise <target>` time (set the target first, then `%policy supervise cascade on`).
- Default-on cascade (gated on measured checker quality).
- Shadow-sampling mode for false-aligned measurement.
