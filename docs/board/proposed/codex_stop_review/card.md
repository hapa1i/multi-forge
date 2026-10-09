# Once-per-turn Stop review

Epic: [Codex supervisor](../../doing/epic_codex_supervisor/card.md). Member **B4**. Depends on
[B1: plan-file supervision](../../done/plan_file_supervision/card.md) and
[B2: Codex runtime test round](../../done/codex_0160_validation/card.md).

## Problem and outcome

Per-edit supervision can consume substantial quota and interrupt execution repeatedly. Add an opt-in review at the end
of a Codex turn, using B1's configured supervisor and approved plan. The ordinary budget is at most one supervisor
review per user-initiated turn, including its automatic continuations.

This matches the maintainer's manual review habit. It reviews changes that have already happened; it cannot prevent an
edit from landing or roll it back. Deterministic PreToolUse enforcement remains independent.

## Scope

- Register and deliver a Codex Stop hook using only the behavior B2 verifies. Update installer ownership, enrollment
  guidance, installed hook dispatch and status surfaces alongside the product change. Choose and document its timeout
  from measured review latency and B2's timeout behavior; it is part of the exact trusted registration. Validate the
  supervisor budget against it and require enrollment after timeout changes.
- Capture bounded evidence of the turn's changes relative to a known start state, including relevant working-tree
  changes and action outcomes. Existing dirty work must not be attributed to this turn. Identify missing/unsupported
  evidence instead of claiming full review from only the final assistant message or current `git diff`.
- Define stable turn ownership and an idempotent review record using B2's observed IDs and continuation markers.
  Duplicate Stop events, hook retries, nested supervisor hooks and automatic continuation must not spend another review.
  A no-change turn can skip the call with an explicit reason.
- Use B1's model, plan identity, read-only execution, subscription-only route, deadline and verdict handling. Selecting
  Stop supervision must not accidentally leave the expensive semantic reviewer running on every edit as well. Bound the
  whole Stop invocation, including evidence capture, retries and recording, with a completion margin below its
  registered timeout; do not reuse the PreToolUse limit without an explicit choice.
- Deliver findings through the tested Stop response. A requested correction may continue Codex, but must not create an
  automatic review loop. If the continuation changes files after the reviewed snapshot, mark those changes unreviewed;
  the next explicit user turn or manual review can request a new assessment. Do not reuse an old allow for new work.
- Timeouts, exhausted quota, missing evidence and interrupted reviews remain visible as unavailable or incomplete. Keep
  the existing supervisor failure policy; never label a skipped review successful. Background informational delivery is
  an alternative only where it meets the chosen feedback contract, not a way to enforce Stop decisions. Use B1's durable
  attempt records and status/activity surfaces even if Codex kills the hook before feedback can be emitted.

## Acceptance and validation

- Several edits in one user turn produce one semantic supervisor invocation; no-change turns and recursive hook
  execution produce none. Repeated Stop and automatic correction events preserve the call cap.
- Unit/regression tests cover turn identity, dirty baseline, missing/truncated evidence, changed plan, interruption,
  duplicate hooks, continuation changes, reviewer failure and stale-result rejection. Test budget validation, a
  controlled supervisor timeout, a runtime-killed Stop hook, child cleanup and incomplete-attempt recovery.
- A trusted Codex integration run demonstrates one completed review, one controlled correction, no recursion, and
  accurate reporting of any work after the assessed snapshot. Prove the review inspects the executor checkout.
- Verify the no-API everyday route and truthful activity/usage attribution. Exercise runtime-scoped extension
  enable/status/sync/disable and a clean installed hook path for the new registration.
- Sync workflow, session, installation and end-user policy docs with the reviewed-at-Stop guarantee and its limits.

## Boundary

The exact identity and evidence collection mechanics depend on B2; implementation must not guess them. This card does
not introduce arbitrary background monitoring, native fork supervision, or automatic approval of every post-review
correction. Those are separate behavioral contracts.

## B2 handoff (2026-10-09)

Codex 0.161.0 emitted two Stop events for one controlled block, with the same thread/turn IDs and `stop_hook_active`
changing false to true; only one `UserPromptSubmit` and one turn completion were observed. The block reason entered
native context as a user-role message inside `<hook_prompt hook_run_id="stop:22:<fixture-config-path>">`. Retain this
continuation marker and control the reason text: it carries user authority in the executor context. The one observed
block does not establish the ID's uniqueness or stability across retries or launches; validate those before using it for
deduplication. Ordinary B1 timeout and native hook expiry both cleaned the admitted stub descendants; interrupted
attempts remained incomplete. Background context could reach the next explicit user turn without an observed autonomous
idle turn. These are measured limits, not a Stop-supervisor implementation. See
[Stop evidence](../../done/codex_0160_validation/evidence/stop.json),
[lifetime evidence](../../done/codex_0160_validation/evidence/lifetime.json), and
[results](../../done/codex_0160_validation/evidence/README.md). `update_plan` was absent from the tested inventory; do
not make plan-event availability or agent plan text an approval prerequisite.
