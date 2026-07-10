# Native review guard -- block or budget Claude Code's built-in review paths

**Epic**: [epic_budgeted_review_guards](../epic_budgeted_review_guards/card.md) (M1 -- first guard on the M0 substrate).

**Lane**: `proposed/`. Depends on [ambient_policy_scope](../ambient_policy_scope/card.md) (M0) and the schema/state
contract from [review_budget_envelope](../review_budget_envelope/card.md) (M2).

## Goal

Ship the first ambient guard: a deterministic policy that intercepts Claude Code's native/built-in review paths
(`code-review`, the PR `review` skill) before they spend, with a configurable posture:

```yaml
# ~/.forge/config.yaml (policy.guards section, M0)
policy:
  guards:
    native_review:
      mode: warn # block | warn | budget-required | allow
```

Semantics:

- `block`: deny native review before expensive behavior starts; the deny message points at `/forge:review`.
- `warn`: allow, but emit a visible preflight estimate (agent-count range, diff size, context floor) at the Skill
  boundary before fan-out -- the shipped default per epic D3. It does not enforce an envelope.
- `budget-required`: deny unless the session supplies an explicit budget envelope (schema owned by M2).
- `allow`: preserve current runtime behavior without estimates or cap enforcement.

Session opt-out is separate vocabulary: `%policy guard disable native_review` suppresses this guard for the current
session. It never changes the global mode and cannot be confused with `block`.

## Implementability (honest status)

The incident probed the assistant-initiated half: when the assistant initiates the review, the invocation is an ordinary
`PreToolUse` event on the Skill tool (`tool_input.skill = "code-review"`), visible **before any spend**, and every
subsequent fan-out is a `PreToolUse` event on the Agent tool. So the **events are observable today** -- but the guard is
not "implementable today" without M0: it needs the new PreToolUse matcher registrations (contract-golden rows plus
`forge extension sync` on existing installs) and the fan-out tool vocabulary at the adapter boundary. The guard itself
is then a deterministic policy class supplying `policy_id`, `description`, and `intent` text plus M2's budget-state
admission calls. Deny formatting, composition, and telemetry come from the engine. This is a Claude-native guard; it
does not claim a corresponding Codex Skill/Agent path.

The unprobed half is the **user-typed** `/review` path.

## Phase 0 probe (user-typed path)

- Does `UserPromptSubmit` receive raw `/review`, or an already-expanded native-review prompt?
- Does hook input carry command metadata distinguishing native review from ordinary prose?
- If the command is expanded before `UserPromptSubmit`, which early `PreToolUse` calls reliably identify the review
  path?

Do not claim a true "disable the slash command" unless the probe proves the command is visible before it spends. If it
is opaque, implement an **effective** disable: block the first review-shaped expensive operation (broad read, subagent
launch) attributable to the native protocol.

## Agent caps

In `budget-required` mode, the guard uses M2's locked guard-operation state at the fan-out boundary. A `PreToolUse`
Agent launch attributed to the guarded Skill operation atomically reserves a total and active slot before start;
correlated `SubagentStop.agent_id` releases the active slot. A launch exceeding `max_total_agents` is denied. If Phase 0
cannot separate review-owned agents from unrelated Agent work, native caps do not ship as operation-scoped enforcement.
`max_parallel_agents` additionally requires reliable completion correlation, including failure/cancellation; otherwise
it remains a reported estimate. Stop and TTL cleanup prevent abandoned reservations from poisoning later sessions.
`block` denies the Skill before fan-out, while `warn` and `allow` do not enforce caps. In `budget-required` mode,
missing parent-operation correlation is a capability failure: deny the native review at the Skill boundary with an
actionable `/forge:review` fallback instead of accepting a budget Forge cannot enforce.

## Acceptance Criteria

Split by probe status (epic "Decisions owed"):

Provable now (assistant-initiated path):

- With `mode: block`, an assistant-initiated native review (Skill-tool invocation) is denied before broad reads or
  subagent fan-out; the deny message names `/forge:review` and carries the guard's intent.
- With `mode: warn`, the review proceeds and a preflight estimate is visibly emitted before fan-out.
- With `mode: budget-required`, no envelope means denial before fan-out. With an envelope and proven parent-operation
  correlation, launches beyond its total-agent cap are denied; parallel-agent denial additionally requires reliable
  active-slot release. Without parent-operation correlation, the Skill is denied with an enforceability explanation and
  `/forge:review` fallback.
- With `mode: allow`, no estimate or agent-budget enforcement changes native behavior.
- A session opt-out override suppresses the guard for that session only and is auditable.
- `/forge:review` is unaffected in every mode and still starts with its current preflight summary.

Conditional on the Phase 0 probe (user-typed path):

- If the user-typed `/review` is visible pre-spend: same guarantees as assistant-initiated.
- If opaque: the effective-disable fallback blocks the first review-shaped expensive operation, and the card's docs say
  so plainly (no "disabled" overclaim).

## Out of Scope

- Workflow-engine enforcement (M2); this card consumes but does not define the envelope/state contract.
- Adaptive in-budget review behavior (M3).
- Guarding non-review skills; the generalization question belongs to M2's preset scope.
