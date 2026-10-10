# Codex supervisor coordination checklist

Epic: [card.md](card.md). Evidence and unresolved runtime claims: [research.md](research.md). Member implementation
belongs in each member's checklist.

## Current focus

B1 [plan-file supervision](../../done/plan_file_supervision/card.md) and both documentation prerequisites are closed
after the stack merged through [PR #258](https://github.com/hapa1i/multi-forge/pull/258) as `56d4b8f5` on 2026-10-08.
The merged tree matches tested head `2a3e7279`, with all five GitHub checks passing. B1's
[closeout](../../done/plan_file_supervision/checklist.md#merged-closeout) records the runtime evidence and limitations.

B2's broader runtime experiment closed on 2026-10-10 after [PR #261](https://github.com/hapa1i/multi-forge/pull/261)
merged as `2a15c087`, matching tested head `29ee539d` with all five GitHub checks passing. Its
[closeout](../../done/codex_0160_validation/checklist.md#merged-closeout) and
[2026-10-09 evidence](../../done/codex_0160_validation/evidence/README.md) record the 0.161.0 round, general-ceiling
update, and source-drift limits.

B3 closed on 2026-10-11 after [PR #262](https://github.com/hapa1i/multi-forge/pull/262) merged as `f1019f6c`, matching
tested head `81c14448` with all five GitHub checks passing. Its
[closeout](../../done/codex_policy_warnings/checklist.md#merged-closeout) records the user-selected source-only mode,
delivery limits, and fixture teardown. B4-B5 remain proposed. The epic remains active until Stop and native-fork
outcomes also ship.

## Activation

- [x] Identify the selected epic and first member from the epic's B1-B5 table.
- [x] Create the B1 branch from clean `main`; move the epic and B1 from `proposed/` to `doing/` with `git mv`.
- [x] Give B1 its own execution checklist and repoint epic, sibling, and Jev dependency links for the lane moves.
- [x] Record passing Markdown, size, link, and diff checks for this planning change.

Activation evidence, 2026-10-06: base `6e0d1f4c`; branch `feat/plan-file-supervision`; the selected directories are
under `doing/`. B2-B5 remain under `proposed/`. No shared implementation batch is authorized by this checklist.

Validation: `make pre-commit-md` passes, including file-size limits; `./scripts/check-markdown-links.py` passes for 635
Markdown sources; working-tree and staged `git diff --check` pass.

Revision evidence, 2026-10-07: B1/card contracts and prerequisites reconciled with verified review findings. No product
code or runtime probes changed. `make pre-commit-md` passes; the link audit passes for 636 Markdown sources;
working-tree/staged diff checks pass. B1 retains the unresolved runtime gates in its own checklist.

B2 activation, 2026-10-08: the user selected B2 and requested its checklist. Created its separate execution branch from
`79563944`, moved the card from `proposed/` to `doing/`, and repointed inbound links. The base includes the B1 closeout
commit above merged stack `56d4b8f5`. B2's checklist records planning validation; B3-B5 are not activated.

B3 activation, 2026-10-10: selected separately from clean local `main` at B2 closeout `d54dba63`, above merged PR #261
(`2a15c087`). Moved B3 to `doing/` and created its execution checklist. The user selected the explicit source-only mode,
making B1's shipped approved-plan snapshot contract an explicit prerequisite alongside B2's delivery evidence. Both
prerequisites are done. B4-B5 and the Jev cards are not activated.

B3 review revision, 2026-10-10: source-only controls Codex hook injection while full evidence remains readable. The B3
checklist now specifies structured warning provenance, audience filtering, the Codex-only global format setting,
launch-time identity, and trusted fixture/wheel enrollment continuity. `policy_summary_feedback` gains substantive Codex
semantics; A2 owns the later Claude extension. The reserved live budget is 32 Codex turns, including 8 retries, plus one
subscription-only Claude quote-quality attempt. Product implementation and live probes have not started.

B2 publication, 2026-10-10: fast-forwarded remote `main` from `2a15c087` to existing closeout `d54dba63`; B3 remains on
its separate branch. Refresh and verify the B3 PR base before opening it.

## Sequence and ownership

| Member                                             | State    | Dependency | Owned outcome                                                  |
| -------------------------------------------------- | -------- | ---------- | -------------------------------------------------------------- |
| [B1](../../done/plan_file_supervision/card.md)     | Done     | None       | Plan source, reviewer selection, isolation, deadline, outcomes |
| [B2](../../done/codex_0160_validation/card.md)     | Done     | None       | Current-runtime probe evidence                                 |
| [B3](../../done/codex_policy_warnings/card.md)     | Done     | B1, B2     | Allowed-action feedback and source-only formatting             |
| [B4](../../proposed/codex_stop_review/card.md)     | Proposed | B1, B2     | Bounded review at turn completion                              |
| [B5](../../proposed/codex_fork_supervisor/card.md) | Proposed | B1, B2     | Native Codex source context                                    |

- [x] Ship B1 independently, with its own current-runtime `apply_patch` deny, auth, isolation, and deadline evidence.
- [x] Complete the [session](../../done/partition_session_design/card.md) and
  [runtime](../../done/partition_runtime_design/card.md) design partitions on separate documentation branches before
  B1's normative updates; reconcile links after merging them. B1's probe work can proceed first.
- [x] Select B2 separately; keep B1's narrow required runtime checks distinct from B2's broader experiment.
- [x] Before activating B3-B5, link the B2 captures each card relies on; parser help alone is insufficient evidence.
- [x] Activate B3 on its own branch with a checklist; record B1's shipped snapshot dependency for source-only feedback
  here and on B3. B1 already handed that option to B3; its completed implementation scope is unchanged.
- [ ] Activate B4 and B5 separately with their own checklists. Record any changed dependency here and in the affected
  member cards before implementation relies on it.
- [x] Keep Jev A3's dependency on B1's escalation contract current. B1 does not introduce Jev or team supervision.
- [x] Confirm B1 preserves the shared `LaneRecord` and four-consumer resolution contracts; no separate model-format
  member was needed. Any later change still requires its own accepted member and dependency decision.

## Member contract closeout

The [epic card's shared contract](card.md#shared-contract) is the single contract source. Check each item when that
member closes, linking its tested head, applicable contract evidence, limitations, and downstream handoff; these are
member closeout checks, not assertions that every later member already ships.

- [x] B1 closeout: review its checklist evidence against the shared contract and record the B3-B5/Jev handoff.
- [x] B2 closeout: review runtime captures and record the supported versions and claims later members may rely on; see
  the [B2 handoff](#b2-handoff) and [merged closeout](../../done/codex_0160_validation/checklist.md#merged-closeout).
- [x] B3 closeout: review delivery evidence against the shared contract and record its operator/model-context limits;
  see the [B3 handoff](#b3-handoff) and
  [merged closeout](../../done/codex_policy_warnings/checklist.md#merged-closeout).
- [ ] B4 closeout: review Stop budget/failure evidence against the shared contract and record unreviewed-work behavior.
- [ ] B5 closeout: review source-context/checkout evidence against the shared contract and record independence limits.

## B1 handoff

- **B2** is now selected separately. B1's Claude 2.1.291 / Codex 0.160.1 captures establish only the tested enforcement,
  auth, read-only, and deadline paths; broader delivery and native-fork claims still need B2.
- **B3** owns allowed-action model context and operator warnings. B1 supplies status/activity evidence; optional
  source-only feedback is deferred to B3 and makes no measured watermark claim.
- **B4** can use the plan-source, reviewer, attempt, and shared-deadline contracts. It must choose and verify its own
  Stop budget and continuation rules; post-edit review cannot undo an edit or replace the existing pre-edit deny.
- **B5** can reuse explicit reviewer/model selection and action-checkout inspection. Native context acquisition and
  reduced independence for a shared source remain unimplemented and depend on B2's captures.
- **Jev A3** can consume B1's Claude escalation contract after its own dependencies. Jev remains an explicit paid API
  route, outside subscription-only review; Jev A2 still depends on B3 for Codex-visible feedback.

The [B1 evidence](../../done/plan_file_supervision/evidence/2026-10-08-review-fixes.md) records inherited-credential
compatibility, supported runtime admission, legacy-state migration, sidecar refusals, and live/audit separation. The
host subscription probe did not measure invoice or quota changes; unverified auth combinations refuse. No shared lane
format change or team-supervisor feature was introduced.

## B2 handoff

The [Codex 0.161.0 results](../../done/codex_0160_validation/evidence/README.md) support the selected existing runtime
paths and raise only the general ceiling. The blocking QA pin remains 0.149.1; shared QA provenance and the proxy floor
are unchanged. Live quota-exhaustion detection is unverified. The
[publication audit](../../done/codex_0160_validation/evidence/validation.md#harness-and-publication-provenance) records
that the committed harness post-dates the captures; optional stage 88/97 rechecks were not performed before merge.

- **B3** receives the measured bare `additionalContext` response and its developer-role rollout message. Explicit allow
  did not deliver its nonce; historical hook stdout/exit status was not captured. `systemMessage` was an operator
  notice. Preserve those qualifications and the catch-all authority guard when implementing feedback.
- **B4** receives one Stop block's same-turn continuation and user-role `hook_prompt` marker, plus deadline,
  cancellation, and background-delivery observations. Control the reason text's user authority and verify marker
  stability before deduplication; `update_plan` was absent from this inventory.
- **B5** receives read-only ephemeral/schema fork evidence on short sources. Shared-source forks inherited
  implementation reasoning. Depth suppression prevented recursion but mutated the parent Forge manifest; isolate hook
  state before reuse. Earlier-turn selection and general concurrent-source guarantees remain unverified.

The three member cards retain the detailed evidence links. B3 subsequently shipped; B4-B5 remain proposed. Closing B2
did not implement those features or satisfy the epic's integrated outcome.

## B3 handoff

The [feedback evidence](../../done/codex_policy_warnings/evidence/README.md) establishes separate model and operator
delivery on retained Codex 0.162.1, with source-only snapshot quotations, fixed unavailable-review text, unchanged
verdicts, and clean-wheel provenance. The feature admits 0.161.0 and 0.162.1 only with verifiable managed-process
identity; B2's historical 0.161.0 qualifications still apply. The general ceiling and blocking QA pin are unchanged.

- **Jev A2** can supply structured findings to the shipped Codex formatter. It still owns substantive Claude warnings
  and its own rule/evidence provenance. Summary-off retains operator/audit output; source-only retains full readable
  evidence while excluding reviewer prose from Forge's model-visible fields. This is not access isolation or a measured
  watermark property.
- **B4/B5** can reuse the audience, bounds, and unavailable-review conventions. B3's PreToolUse evidence does not
  establish Stop continuation semantics or native-fork isolation. Each still needs its own activation and runtime
  evidence.

PR #262's 31 affected Docker cases passed after repairing an exported-image binary; both auth-isolation controls used
Claude 2.1.294. The two explicitly authorized Haiku API checks are separate from the one subscription quote-quality
review. The 32-turn Codex product round is closed, with no new closeout inference. Its isolated login was removed while
captured evidence and runtime artifacts were retained.

## Closeout

- [ ] Every live member is shipped and verified; record any retirement or scope change explicitly before counting the
  epic outcome complete. A retired member is not shipped credit.
- [ ] Verify the integrated plan-file, allowed-feedback, Stop, and opted-in native-fork paths, including quota/failure
  outcomes, checkout selection, and existing Claude supervision.
- [ ] Run applicable integrated unit, regression, targeted integration, pre-commit, and board/link checks; retain exact
  versions, commands, and sanitized evidence in the member checklists.
- [ ] Synchronize the relevant design and end-user docs with shipped behavior, then record completed work in the
  changelog. Promote durable implementation notes only after human review.
- [ ] Move the epic to `done/` after its coordinated outcome ships, and repoint inbound links.
