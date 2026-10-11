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
delivery limits, and fixture teardown. B4 closed on 2026-10-11 after
[PR #263](https://github.com/hapa1i/multi-forge/pull/263) merged as `2045aea1`, matching tested head `5eecc6ff` with all
five GitHub checks passing. Its [closeout](../../done/codex_stop_review/checklist.md#merged-closeout) records turn
attribution and evidence limits. B5 implements the user-approved
[native source/login/trigger contract](../codex_fork_supervisor/gate-decision.md) on `codex/codex-fork-supervisor`,
rebased onto `225ab3dd`. Its [product evidence](../codex_fork_supervisor/evidence/product.md) records installed
allow/deny, shared active Stop, source-only feedback, global-ignore composition and clean-wheel verification. The ledger
is closed at 60/60 native starts and 3/4 authorized API starts; both fixture logins are removed. Aggregate validation
passes and the per-card PR is ready for review. The epic remains active until its native-fork outcome ships and the
merged tree is verified.

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

B4 activation, 2026-10-11: selected separately from clean, synchronized `main` at B3 closeout `897ed95c`. Created
`codex/codex-stop-review`, moved B4 to `doing/`, and added its checklist. B3 is now an explicit dependency for
source-only feedback and provenance; B4 still needs independent Stop delivery, turn identity, and timeout evidence. The
one-review cap counts actual frontier dispatches and excludes cascade/shadow work in Stop mode. Product work and live
probes have not started. B5 and Jev remain unactivated.

B4 review revision, 2026-10-11: the runtime go/no-go gate now precedes product work. The checklist specifies conditional
manifest v4 serialization, the supported Codex child/setup path, refusal of incompatible inherited Stop mode, and reuse
of the session-event journal with atomic reservation and bounded history. Private Git snapshots remain conditional on
filter/helper isolation. No product work or live inference was performed for this revision.

B5 activation, 2026-10-11: selected separately from clean, synchronized `main` at B4 closeout `5613b185`. Created
`codex/codex-fork-supervisor`, moved B5 to `doing/`, and added its
[execution checklist](../codex_fork_supervisor/checklist.md). B1/B2 remain the prerequisites; shipped B3/B4 contracts
are integration constraints. The user requested review before implementation. Parent hook-state isolation, source
boundaries, source/auth configuration, and the native budget remain review or runtime gates. Jev stays proposed.

B5 review revision, 2026-10-11: verified B2's argv-only, same-route evidence and B4's approved-plan/deadline contract.
The revised gate covers stdin, model changes, billing routes, long and compacted context, lineage and both isolation
candidates, with 60 total Codex starts allocated by case. Native caching is disabled; PreToolUse eligibility awaits
measurements. B4's effective-config fix is already merged. A synthetic fixture confirmed lost global-ignore exclusions;
the separate [proposed correction](../../done/preserve_stop_global_ignores/card.md) is required before native Stop
product admission. No product implementation or live inference is authorized by this planning revision.

B5 execution, 2026-10-11: the user approved continuation after PR #264 merged. Rebased B5 onto `225ab3dd`, removed the
duplicate fix proposal and linked the completed correction. Runtime probes precede product changes; the 60-start
allocation applies and API slots retain their explicit paid-route gate.

B5 runtime findings, 2026-10-11: the user separately authorized four API starts and completed two independent fixture
logins. The [evidence](../codex_fork_supervisor/evidence/README.md) establishes native context, source/parent
preservation in the measured cases, isolated hooks, read-only writes and actual trigger boundaries. Copied ancestry,
dedicated reviewer-home ownership, cancellation of detached native tools and inherited-token counters require the
[contract supplement](../codex_fork_supervisor/gate-decision.md). This is not product acceptance or epic closeout.

B5 product verification, 2026-10-11: the user approved the supplement. Six installed native reviews exercised the
separate-source allow/deny path, shared active Stop, approved-plan precedence and source-only feedback. Both Stop
controls requested exactly one correction; final-wheel review excluded the globally ignored sentinel. Each reviewer
emitted one attributed new-review usage delta. The Claude control used a synthetic adapter payload with a real Codex
reviewer; API product configuration used a dummy key, with live route evidence from the earlier gate. Targeted
integration passed 14 tests with eleven explicit legacy-native deselections; regression passed 1,546. The final wheel's
installed source hashes match the working tree. Aggregate unit passes 10,770 tests, with 117 deselected; full pre-commit
passes after the approved three-guide token-count refresh. Review, CI and shipped-tree closeout remain outstanding.

## Sequence and ownership

| Member                                         | State               | Dependency | Owned outcome                                                  |
| ---------------------------------------------- | ------------------- | ---------- | -------------------------------------------------------------- |
| [B1](../../done/plan_file_supervision/card.md) | Done                | None       | Plan source, reviewer selection, isolation, deadline, outcomes |
| [B2](../../done/codex_0160_validation/card.md) | Done                | None       | Current-runtime probe evidence                                 |
| [B3](../../done/codex_policy_warnings/card.md) | Done                | B1, B2     | Allowed-action feedback and source-only formatting             |
| [B4](../../done/codex_stop_review/card.md)     | Done                | B1, B2, B3 | Bounded review at turn completion                              |
| [B5](../codex_fork_supervisor/card.md)         | Doing; verification | B1, B2     | Native Codex source context                                    |

- [x] Ship B1 independently, with its own current-runtime `apply_patch` deny, auth, isolation, and deadline evidence.
- [x] Complete the [session](../../done/partition_session_design/card.md) and
  [runtime](../../done/partition_runtime_design/card.md) design partitions on separate documentation branches before
  B1's normative updates; reconcile links after merging them. B1's probe work can proceed first.
- [x] Select B2 separately; keep B1's narrow required runtime checks distinct from B2's broader experiment.
- [x] Before activating B3-B5, link the B2 captures each card relies on; parser help alone is insufficient evidence.
- [x] Activate B3 on its own branch with a checklist; record B1's shipped snapshot dependency for source-only feedback
  here and on B3. B1 already handed that option to B3; its completed implementation scope is unchanged.
- [x] Activate B4 separately with its own checklist; record the B3 feedback dependency here and in B4/B3's cards.
- [x] Activate B5 separately with its own checklist. Record any changed dependency here and in the affected member cards
  before implementation relies on it.
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
- [x] B4 closeout: review Stop budget/failure evidence against the shared contract and record unreviewed-work behavior;
  see the [B4 handoff](#b4-handoff) and [merged closeout](../../done/codex_stop_review/checklist.md#merged-closeout).
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

The three member cards retain the detailed evidence links. B3 and B4 subsequently shipped; B5 is now executing its
reviewed runtime gate. Closing B2 did not implement those features or satisfy the epic's integrated outcome.

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
  establish Stop continuation semantics or native-fork isolation. B4 supplied its separate Stop evidence; B5 still needs
  its own runtime evidence under the approved checklist.

PR #262's 31 affected Docker cases passed after repairing an exported-image binary; both auth-isolation controls used
Claude 2.1.294. The two explicitly authorized Haiku API checks are separate from the one subscription quote-quality
review. The 32-turn Codex product round is closed, with no new closeout inference. Its isolated login was removed while
captured evidence and runtime artifacts were retained.

## B4 handoff

[B4's closeout](../../done/codex_stop_review/checklist.md#merged-closeout) verifies the shipped one-dispatch and
one-correction contract on admitted host Codex 0.162.1. The operational journal survives telemetry reset and belongs to
a session-creation owner. Each prompt uses current checkout context; pending work carries only through observed
tool/Stop endpoints, while manual between-turn changes remain unattributed. Partial reviews cannot correct omitted
scope, and historical exclusions stay unreviewed after later complete reviews.

The [latest evidence](../../done/codex_stop_review/evidence/attribution-followup.md) retains native-source drift and
automated coverage for subsequent missing-tracking fixes. Quota exhaustion remains unverified, and native cancellation
was not repeated after its cleanup fix. B5 can reuse plan snapshots and reviewer lanes; it still must isolate reviewer
hooks from parent state, establish native-source boundaries, and record reduced independence for shared sources. No B5
or Jev work is activated by this closeout.

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
