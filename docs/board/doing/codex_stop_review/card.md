# Once-per-turn Stop review

Epic: [Codex supervisor](../../doing/epic_codex_supervisor/card.md). Member **B4**. Depends on
[B1: plan-file supervision](../../done/plan_file_supervision/card.md),
[B2: Codex runtime test round](../../done/codex_0160_validation/card.md), and
[B3: bounded, source-aware feedback](../../done/codex_policy_warnings/card.md); all have shipped.

Activated 2026-10-11 on `codex/codex-stop-review` from published `main` at `897ed95c` (B3 closeout). The
[execution checklist](checklist.md) records the implementation plan and fresh runtime gates. The
[runtime gate](evidence/README.md) passed on 2026-10-11 for retained Codex 0.162.1. The opt-in implementation,
installed-wheel controls and regression suite are complete. [Validation](evidence/validation.md) records the completed
checks and measured limits for [PR #263](https://github.com/hapa1i/multi-forge/pull/263). The card remains active until
merge and closeout.

The [PR review follow-up](evidence/review-followup.md) adds explicit recovery for interrupted/incomplete turns,
preserves enrollment receipts, reserves completion time, and avoids full CLI startup for inactive turn hooks.

Execution starts with the checklist's runtime go/no-go gate. Product configuration, schema, CLI, and installed-hook
changes follow only after that gate passes. Non-default Stop trigger state requires manifest v4; ordinary per-edit
sessions retain compatible v2/v3 serialization. Codex children use `session start --runtime codex --resume-from`, with
their supervisor configured explicitly; incompatible inherited Stop mode is refused before child creation or inference.

## Problem and outcome

Per-edit supervision can consume substantial quota and interrupt execution repeatedly. Add an opt-in review at the end
of a Codex turn, using B1's configured supervisor and approved plan. The ordinary budget is at most one supervisor
review per user-initiated turn, including its automatic continuations.

Count actual frontier model dispatches, including uncertain dispatch outcomes. Stop mode excludes per-edit semantic
checks, cascade, and shadow sampling so the one-review cap is meaningful. Default per-edit supervision remains
available.

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
  the next explicit user turn includes outstanding changes in its review scope. A single-file manual review does not
  clear whole-turn status. Do not reuse an old allow for new work.
- Preserve B3's Codex source-only preference, finding provenance, and bounded presentation in Stop feedback, including
  its user-authority block reason. B3's PreToolUse response shape and version admission do not establish Stop delivery;
  verify that separately. Full reviewer wording remains durable evidence under the existing source-only contract.
- Timeouts, exhausted quota, missing evidence and interrupted reviews remain visible as unavailable or incomplete. Keep
  the existing supervisor failure policy; never label a skipped review successful. Background informational delivery is
  an alternative only where it meets the chosen feedback contract, not a way to enforce Stop decisions. Use B1's durable
  attempt records and status/activity surfaces even if Codex kills the hook before feedback can be emitted.

## Acceptance and validation

- Several edits in one user turn produce one semantic supervisor invocation; no-change turns without outstanding
  unreviewed work and recursive hook execution produce none. Repeated Stop and automatic correction events preserve the
  call cap.
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

## B4 implementation handoff

The tested trigger is opt-in, host Codex 0.162.1 only, with separate empirical receipts for the required event set.
Ordinary manifests retain v2/v3 encoding; a stored non-default trigger uses v4. The session review journal owns spending
and survives telemetry reset. One divergent review can request one source-aware correction; later changes carry to the
next explicit turn and remain visibly unreviewed until that exact snapshot is assessed.

B5 can reuse B4's approved-plan snapshot and reviewer-lane contract without inheriting another session's allowance. The
native Codex child path still creates fresh supervisor policy. Stop's block reason carries user authority, so B3's
source-only restriction applies there. Keep default per-edit and Claude Stop behavior separate. See the
[product evidence](evidence/README.md) for failures retained, cleanup boundaries and the single real-review
qualification.
