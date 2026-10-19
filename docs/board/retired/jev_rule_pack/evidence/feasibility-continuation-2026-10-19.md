# A2 feasibility continuation

The owner's 2026-10-19 instruction to continue the investigation to an answer, using paid calls as needed, authorizes
this bounded continuation. It follows the
[availability-first proposal](bounded-feasibility-plan.md#separate-availability-first-proposal-and-remaining-gates) and
the [offline admission review](offline-retention-admission.md). Historical captures, human labels and their failed
screens remain unchanged. This is a decision study, not runtime activation.

## Fixed acquisition and decision order

1. Take one new metadata snapshot: index and active index at most 8 MiB each, at most 24 matching manifests of at most
   256 KiB, and at most 24 confirmed source-path metadata checks. Use this repository and verified Git worktrees only.
   Check availability within that fixed recency cohort before selecting at most three inactive sources per runtime.
   Retain the frozen selection and every exclusion privately. Do not search for replacement paths or enlarge the cohort.
2. Inspect the resulting counts before reading native content. If sources are available, the continuation permits only
   those frozen sources, up to six files at 20 MiB each/120 MiB total, with a 1 MiB record cap. Verify native identity,
   CWD and a supported completed-turn boundary before admitting actions. Use actions from October 1 inclusive through
   October 18 exclusive, 2026 UTC; select at most the latest 20 named mutations per source/120 total. Inherit all
   exclusions, stable-read, local secret-screen and private-retention rules from the
   [original study](feasibility-study-plan.md#local-sanitization-and-retention). No surrounding repository files,
   earlier turns or Git before-images may repair incomplete action evidence. No private actions enter a provider request
   or PR.
3. Use the frozen actions to assess structural evidence availability before considering model selection. Keep source
   failures outside action denominators, unknown governance separate, and deterministic candidates separate from
   semantic warnings. An empty sample is unmeasured coverage, not zero coverage. A conditional clean-break assumption
   cannot establish actual applicability.
4. Stop this investigation with a proceed, revise or stop recommendation. Another paid study is justified only if it
   resolves a decision left open by the local evidence: whether a fixed semantic-only candidate, after automatic host
   admission, adds useful discrimination beyond the AST baseline within the proposed five-second stage. It would need
   frozen selection, human labels, outcome rules, model configuration and request/spend caps before dispatch. Private
   native actions are excluded from this paid permission; using any of them would require a separately reviewed
   provider-safe evidence selection and data-sharing decision. Do not rerun the known-broken prompts, spend the consumed
   allowances again, or initiate another tuning round after a failure.

The original numerical gates remain proposals; this continuation does not silently adopt or relax them. The existing
model failures already preclude proceeding with A2 as specified. Local evidence can establish whether a revised design
is worth pursuing, but cannot turn that failed result into a pass. Agent structural observations are not human quality
labels. Broader claims require new real families and separate warning-usefulness review.

## Results

The single availability-first snapshot found 88 matching index rows and considered the fixed newest 24. One active entry
was excluded. Of the remaining 23 confirmed paths, 15 were missing and eight Claude sources were available. Three Claude
sources were selected, totaling 17,745,038 bytes by file metadata; the other five did not replace or expand the selected
cohort. No Codex source was available within this cohort. The private ledger records every disposition.

The [aggregate report](feasibility-continuation-summary.json) records the subsequent source audit. It read the three
frozen files once each, 17,745,038 bytes total, without a read failure or identity/CWD conflict. It retained only
allowlisted schema counters and private identity/hash receipts: no prose, tool arguments or complete transcript copies.
The files contained 948, 4,289 and 450 records. In the recognized top-level assistant `message.content` shape, only the
second source contained named mutations: 71 `Edit` and six `Write` blocks. These are observed blocks, not deduplicated,
completion-verified or sanitized action samples. The audit classified 613, 2,948 and 323 records as `other`; it did not
establish whether those unrecognized shapes carry additional proposals.

All three contained explicit `end_turn` values, plus `turn_duration` and `stop_hook_summary` records. The
[Messages API contract](https://platform.claude.com/docs/en/build-with-claude/handling-stop-reasons#end_turn) defines
`end_turn` as natural model-response completion; that alone does not verify a successful native Stop or this study's
completed-turn boundary. No completion interpretation or action extractor was added. The audit reports completion as
unverified and admits zero actions.

Even granting every later completion and content check, the **recognized shape** could yield at most 20 selected named
actions from one session under the per-source cap. That observed subset cannot supply the proposed 60-action cohort or
its two-session-per-runtime minimum. This is not a source-wide upper bound: proposals in unrecognized shapes remain
unmeasured. No completion-verified native sample was established. Stop this bounded acquisition without lowering the
proposed minima, replacing sessions or interpreting unknown shapes after seeing the result. Zero extracted actions does
not mean zero coverage: structural sufficiency, governance, exception mapping and warning usefulness remain unmeasured.
The missing Codex stratum and availability bias remain explicit limitations.

## Decision: stop the current implementation path

Do not proceed to A2 runtime wiring or run another synthetic prompt-tuning capture. This is a recommendation about the
current Jev-backed compatibility-wrapper rule and supplied-action hook contract, not a proof that every semantic rule or
future Jev formulation is infeasible.

- The [first three-question capture](calibration-2026-10-16/README.md) cannot recover the two required-boundary
  no-warning labels. After the [instruction-only follow-up](calibration-boundary-2026-10-17/README.md), all three human
  no-warning cases are unrecoverable under the allowed settings. Threshold tuning cannot fix this pairing.
- The [decomposed capture](bounded-diagnostic-2026-10-18/README.md) stopped Jev after the same explicit definition fact
  was wrong twice. Moving structural facts to host code is a sensible proposed responsibility split, but does not
  establish Jev's remaining semantic quality or automatic target selection.
- Opus matched 94 of 95 question identities on all three repetitions. Its remaining disagreement exposes an implicit
  evidence dependency, as the [offline review](offline-retention-admission.md) explains. Preserve the failed frozen
  result; a prospective clarification cannot retroactively pass it. More decisively for the current runtime proposal, 21
  of 36 calls exceeded five seconds (median 5.330 seconds). A smaller semantic-only request is untested, not an admitted
  replacement.
- The native audit has not established a cohort that supports the proposed feasibility study. Its recognized subset is
  too small, and unknown shapes and completion remain unresolved. The AST baseline finds structural candidates on
  constructed examples, but has no demonstrated warning usefulness or selection coverage on real actions. It must not
  become a warning emitter merely because model admission failed.

These findings are enough to stop this implementation path without spending on another model capture. **Additional
provider requests: zero; additional model spend: $0.** The paid permission was available, but no remaining bounded call
could repair the missing native-quality evidence. The earlier capture allowance remains consumed.

Preserve A1's client, the review/evaluation tools and the evidence. Keep `jev_rule_pack` reserved, settings unset and
runtime slices unstarted. A2's board disposition remains for the owner to review; this study does not mark the card
shipped or silently narrow it to local helpers. A3 receives no quality endorsement from A1's transport readiness or
Opus's constructed diagnostic result.

If broader wrapper review remains a priority, the justified next proposal is an explicit diff review with complete
before/after evidence, host structural admission and a separately evaluated semantic step. That would change the current
action-only, five-second product contract and needs its own scope and evidence; it is not another tuning round within
this completed investigation.

## Verification

The 152 focused inventory, source-audit, bounded-runner and offline-comparison tests pass. The deadline regression now
uses controlled elapsed time and real cancellation instead of depending on a 0.3-second local-I/O window. Repository
pre-commit, full mypy/pyright, the 721-source link audit, size checks and whitespace checks pass; the EOF hook ran
separately on edited files. Provider token-count fallback was restricted to loopback throughout these checks. Frozen
model captures, questions and human labels are unchanged. Published implementation hashes match the source audit that
ran.
