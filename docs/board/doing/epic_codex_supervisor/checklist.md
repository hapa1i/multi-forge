# Codex supervisor coordination checklist

Epic: [card.md](card.md). Evidence and unresolved runtime claims: [research.md](research.md). Member implementation
belongs in each member's checklist.

## Current focus

B1 [plan-file supervision](../plan_file_supervision/card.md) is active for execution planning on
`feat/plan-file-supervision`, from `main` at `6e0d1f4c`. Its [checklist](../plan_file_supervision/checklist.md) starts
with auth isolation and resumed-review compatibility. This activation prepares the requested checklists; product
implementation and inference probes have not started.

Revised 2026-10-07 after source verification. B1 records an explicit subscription-only opt-in, host Claude executor
coverage, sidecar refusal, resumed checkout access, and proof gates for both runtimes' timeout/cleanup behavior. Its
[commit slices](../plan_file_supervision/checklist.md#commit-slices) keep implementation concerns separately reviewable.

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

## Sequence and ownership

| Member                                             | State    | Dependency | Owned outcome                                                  |
| -------------------------------------------------- | -------- | ---------- | -------------------------------------------------------------- |
| [B1](../plan_file_supervision/card.md)             | Planning | None       | Plan source, reviewer selection, isolation, deadline, outcomes |
| [B2](../../proposed/codex_0160_validation/card.md) | Proposed | None       | Current-runtime probe evidence                                 |
| [B3](../../proposed/codex_policy_warnings/card.md) | Proposed | B2         | Allowed-action feedback delivery                               |
| [B4](../../proposed/codex_stop_review/card.md)     | Proposed | B1, B2     | Bounded review at turn completion                              |
| [B5](../../proposed/codex_fork_supervisor/card.md) | Proposed | B1, B2     | Native Codex source context                                    |

- [ ] Ship B1 independently, with its own current-runtime `apply_patch` deny, auth, isolation, and deadline evidence.
- [ ] Complete the [session](../../doing/partition_session_design/card.md) and
  [runtime](../../todo/partition_runtime_design/card.md) design partitions on separate documentation branches before
  B1's normative updates; reconcile links after merging them. B1's probe work can proceed first.
- [ ] Select B2 separately; keep B1's narrow required runtime checks distinct from B2's broader experiment.
- [ ] Before activating B3-B5, link the B2 captures each card relies on; parser help alone is insufficient evidence.
- [ ] Activate each later member on its own branch and add its own checklist. Record any changed dependency here and in
  both affected cards before implementation relies on it.
- [ ] Keep Jev A3's dependency on B1's escalation contract current. B1 does not introduce Jev or team supervision.
- [ ] If B1 requires shared `LaneRecord` or four-consumer resolution changes, create and accept a separate member,
  record its dependency/order here, and give it its own branch, checklist, and PR before implementing that change.

## Member contract closeout

The [epic card's shared contract](card.md#shared-contract) is the single contract source. Check each item when that
member closes, linking its tested head, applicable contract evidence, limitations, and downstream handoff; these are
member closeout checks, not assertions that every later member already ships.

- [ ] B1 closeout: review its checklist evidence against the shared contract and record the B3-B5/Jev handoff.
- [ ] B2 closeout: review runtime captures and record the supported versions and claims later members may rely on.
- [ ] B3 closeout: review delivery evidence against the shared contract and record its operator/model-context limits.
- [ ] B4 closeout: review Stop budget/failure evidence against the shared contract and record unreviewed-work behavior.
- [ ] B5 closeout: review source-context/checkout evidence against the shared contract and record independence limits.

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
