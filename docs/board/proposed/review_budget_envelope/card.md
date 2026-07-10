# Review budget envelope -- bounded admission for review-shaped work

**Epic**: [epic_budgeted_review_guards](../epic_budgeted_review_guards/card.md) (M2 -- shared schema; workflow
enforcement).

**Lane**: `proposed/`. Depends on M0's normalized Claude fan-out lifecycle. This member owns the schema and state
contract M1 consumes; M1 does not ship `budget-required` before M2.

## Goal

Define one budget envelope schema for review-like work and enforce it at every point that can multiply cost:

```yaml
budget:
  max_estimated_tokens: 250000
  max_total_agents: 3
  max_parallel_agents: 3
  reserve_for_synthesis: 0.20
  max_wall_minutes: 20
  degrade_order:
    - changed_files
    - targeted_paths
    - triage_only
    - summary_only
```

`max_total_agents` is a hard admission cap: Forge can deny a launch before it starts. `max_parallel_agents` is a hard
simultaneous-admission cap only on surfaces with a probe-pinned completion event and stable invocation correlation;
otherwise it is estimate-only. `max_estimated_tokens` is an admission ceiling, not a provider hard cap. Forge estimates
before launch, records observed usage after completion when available, and stops later scheduling when the estimate or
observed total exhausts the remaining budget. It cannot terminate an already-running direct subscription turn at an
exact token boundary.

**`max_wall_minutes` caveat**: enforcement is event-driven, not timer-driven -- there is no daemon watching the clock.
The bound is checked at the next tool event or worker-scheduling decision after expiry, so it is a "stop scheduling new
work" rule, not a hard kill. The docs and receipt must say so.

## Enforcement checkpoints

The envelope combines hard worker admission with conservative token/time estimates. It is checked before launching work
that can multiply cost:

- before `Agent`/subagent launch (via M1's guard on the hook path);
- before workflow fan-out worker launch (workflow CLI preflight, alongside the existing `WorkerRoutingPlan` resolution);
- before a Forge-owned workflow or skill begins a broad cwd/repo-wide target;
- before continuing when remaining budget would threaten the synthesis reserve.

## Precedence and placement

Envelope values resolve: **invocation flag > session intent > global runtime config > built-in preset** -- the same
layering as the guard mode (epic D2). Global defaults live beside `policy.guards` in `~/.forge/config.yaml`; a skill or
workflow invocation may tighten (or with an explicit flag, loosen) them. “Invocation flag” applies only to Forge-owned
skill/CLI surfaces; opaque native review receives session/global/default values.

## Agent-budget state

M2 owns one locked, versioned guard-operation record under `get_forge_home()/guard-state/`, mode `0600`, keyed by
runtime plus the M0-probed guarded Skill operation id -- **not** by Claude's rolling `session_id`. The record keeps
runtime session ids as aliases/observations and, for managed sessions, records the stable Forge session identity. That
gives managed and enrolled sessionless Claude hooks one operation counter without charging unrelated Agent work in the
same session or resetting totals on `/compact`. It contains total admitted agents, active invocation ids,
estimated/observed token totals, start/update times, and the resolved envelope fingerprint.

- PreToolUse admission updates total/active counters atomically before allowing a launch.
- The existing `SubagentStop` hook is the primary completion candidate. If its `agent_id` correlates to the launch, it
  releases the active invocation id; duplicate completion is idempotent. Failure/cancellation delivery is probe-gated.
- `SessionStart(source=compact)` records the new runtime session-id alias without changing the guard-operation key or
  counters. A later launch or SubagentStop under the new UUID resolves the existing operation record. For an enrolled
  sessionless run, this requires the probed Skill/Agent operation id to survive compact; otherwise native enforcement is
  not claimed for that runtime shape.
- Guarded Skill completion or Stop removes the live record after emitting its receipt; startup/next-hook GC removes
  records older than `max_wall_minutes` plus a fixed grace period. GC does not pretend unmanaged runtime liveness is
  directly observable.
- Sidecars may keep this state container-local for the life of the session; durable receipts use the existing mounted
  telemetry/project state. The counters need cross-hook-process visibility, not cross-session persistence.
- If parent-operation correlation is not reliable, no native operation-scoped counter is enforced. If only completion
  correlation is unreliable, native total-agent admission remains enforceable but its active counter is estimate-only.
  Workflow-engine totals and parallelism remain enforceable because Forge owns that scheduler.

## Defaults

- Forge `/forge:review`: allowed, but inherits a generous default envelope when the target is cwd or a directory.
- Workflow fan-out skills (`panel`, `analyze`, `debate`, `consensus`): require an envelope or use a conservative preset.
- Direct subscription sessions: warn that proxy spend caps do not apply and hook guards are the enforcement layer.

## Open Questions

- **Observed token source**: probe which completion/Stop payloads carry per-subagent counters and their cache-token
  semantics. Missing counters do not weaken worker admission; receipts label token totals `estimated` or `observed`
  instead of presenting estimates as measurements.
- **Preset scope**: which skills beyond `review`, `review-docs`, `understand`, `panel`, `analyze`, `debate`, and
  `consensus` opt into the first budget preset?
- **Receipt plumbing**: where do guard/budget decisions land for `forge telemetry activity` in direct sessions --
  upstream outcomes keyed by run tree, or a new lightweight guard-event record?

## Acceptance Criteria

- Workflow fan-out refuses to start workers that would exceed `max_total_agents`, at invocation preflight, before any
  worker spawns.
- Concurrent hook invocations cannot over-admit total slots; parallel slots are released idempotently on correlated
  completion, with failure/cancellation and stale-state tests. If correlation fails the Phase 0 probe, JSON and docs
  mark the native parallel cap `estimate_only`.
- Compact between Agent admission and SubagentStop does not restart total counters or strand active slots: the new
  Claude session UUID aliases the same operation record, subsequent launches see the pre-compact total, and completion
  under the new UUID releases the original reservation. Cover managed and enrolled-sessionless outcomes separately.
- A run whose estimated or observed remaining budget reaches the synthesis reserve stops scheduling new work and still
  produces a synthesis; no exact provider token cutoff is claimed.
- Envelope resolution honors the precedence chain, and the resolved envelope is visible in the invocation's JSON output
  (the `resolved_models` pattern).
- The final report names what was reviewed, what was skipped, and which cap forced the narrowing.
- Direct-runtime runs record enough guard/usage events to explain why work was blocked, narrowed, or allowed, and label
  token accounting as estimated versus observed.
