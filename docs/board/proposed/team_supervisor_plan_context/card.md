# team_supervisor_plan_context -- runtime-neutral plan/context for the team supervisor

**Lane**: `proposed/` -- design decisions are owed before execution (see "Design decisions owed"). Move to `todo/` once
the context-delivery mechanism is chosen.

**Origin**: carved out of the `consumer_lanes` epic at its closeout (2026-07-01) --
`docs/board/done/epic_consumer_lanes/`. This is deliberately **not** framed as unfinished consumer-lane work: the lane
epic proved and shipped the contract. A codex team-supervisor lane is blocked on a *different* abstraction --
runtime-neutral plan/context delivery -- which belongs to team-orchestration / context design, not the lane substrate.

**Related**: `docs/board/proposed/team_orchestration/` (sibling domain); `docs/board/done/codex_exec_supervisor_lane/`
and `docs/board/done/aux_consumer_codex_dispatch/` (the blind / in-band codex arms this consumer cannot copy).

---

## Problem

The team supervisor is the one repeated-dispatch Forge consumer whose supervision context is delivered by Claude's
**native session resume**, not by an in-band prompt. Consumer-lanes already gave it lane placement, `claude-max`
billing, freeze-on-real-dispatch, and observability -- but it has no codex lane, and adding one is not "one more aux
dispatch arm."

Verified in `src/forge/policy/team/handlers.py` (2026-07-01):

- `TEAM_SUPERVISOR_CONSUMER.allowed_lanes` is `(Lane("claude_code", "claude-max", "opus"),)` only -- **no codex lane**
  (`handlers.py:38-43`). `claude-max` shares the `claude_code` runtime, so it changes the billing label, not dispatch.
- The dispatch is `run_claude_session(prompt, resume_id=config.resume_id, ...)` (`handlers.py:267-269`); the approved
  plan / prior context reaches the supervisor **only** via `claude -p --resume <resume_id>`. With no `resume_id` the
  handler short-circuits to allow (`handlers.py:76-77`, `:132`) -- resume is load-bearing, not optional.

The three codex arms shipped in consumer_lanes -- semantic supervisor (T4), shadow-curation (T6b), memory-writer (T6c)
-- are all **blind / in-band**: `codex exec` has no `--resume`, so their context arrives inside the prompt (a
plan-override preamble, or, for the semantic supervisor, a curated transfer body). The team supervisor has **no
equivalent**: its context is whatever the resumed Claude conversation holds. So dropping
`Lane(codex, chatgpt, gpt-5-codex)` into `allowed_lanes` would dispatch a *plan-blind* codex turn -- worse supervision,
not a swappable lane.

## Goal

Make team-supervisor supervision independent of `claude -p --resume` by giving it an approved-plan snapshot / event
context package suitable for non-Claude runtimes. Only once that context is good enough, add a codex lane deliberately.

## Design decisions owed (resolve before execution)

- **How does the team supervisor get approved-plan text without `--resume`?** Today the plan lives in the resumed Claude
  conversation; a runtime-neutral arm needs it as inspectable text.
- **Reuse existing machinery or build a team-specific packet?** Three candidates to weigh:
  - the semantic supervisor's `--reload` / approved-plan-snapshot resolution (`plan_override_path`), or
  - the transfer machinery (`assemble_transfer_context`, ai-curated), or
  - a new team-specific context packet (team roster + task events + plan).
- **Only then** add `Lane(codex, chatgpt, gpt-5-codex)` to `TEAM_SUPERVISOR_CONSUMER.allowed_lanes` plus a runtime-keyed
  dispatch arm (mirroring `_dispatch_codex_*`), gated on the context being sufficient.

## Constraints (preserve)

- **Fail-open hook contract**: a team-supervisor eval failure degrades to allow (`return 0, ""`, design_workflows §1.2).
  The codex arm's degrade must not brick the team hook.
- **Escape-hatch / throttle behavior**: keep the existing cache/throttle and the `resume_id`-absent short-circuit.
- **Lane-contract parity**: keep the consumer-lane binding / freeze / observability the other three consumers have
  (already in place for team-supervisor at the `claude-max` level).

## Out of scope

Changing the shipped semantic-supervisor / shadow-curation / memory-writer codex arms; interactive team runtimes;
general team-orchestration redesign beyond the context-delivery seam.
