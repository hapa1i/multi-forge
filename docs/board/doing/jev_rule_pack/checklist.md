# A2: Jev rule pack execution checklist

## Current focus

The offline outcome/evaluation slice shipped through [PR #271](https://github.com/hapa1i/multi-forge/pull/271), merged
as `791d9872` on 2026-10-15. The [merge handoff](#offline-evaluation-merge-and-next-gate) records its verified scope. It
builds on [PR #270](https://github.com/hapa1i/multi-forge/pull/270)'s explicit evaluation identity, session consent and
override guards. Human review shipped through [PR #272](https://github.com/hapa1i/multi-forge/pull/272) as `64317485`.
Execution continues in [draft PR #274](https://github.com/hapa1i/multi-forge/pull/274) on
`codex/jev-rule-pack-feasibility` from that merged `main` head.

All 17 constructed cases now have [human adjudications](evidence/human-review.md): 12 calibration and five held-out. The
[feasibility checkpoint](evidence/corpus-feasibility.md) records seven families, empty historical strata and only one
held-out positive family. Its scenarios and proposals were visible during draft-3 development; held-out model outputs
can support only a limited check, not unseen-scenario generalization. Select question bands on calibration responses
only.

The next [feasibility gate](#slice-2-feasibility-before-runtime-work) precedes declaration, dispatch, activation and
feedback implementation. It measures real-action evidence coverage, exception mapping and warning usefulness against the
[evaluation plan](evidence/evaluation-plan.md). The [current checkpoint](evidence/feasibility-progress.md) records the
approved inventory's missing-source shortfall and constructed baseline signals. The
[runtime evidence proposal](evidence/runtime-evidence-contract.md) remains unimplemented and selects no production
authority. The [wrapper evidence contract](evidence/initial-rule-review.md) retains broader wrappers and advisory
supplied-evidence semantics. No paid A2 evaluation has run or bundle been enabled. The [card](card.md) owns scope; the
[epic checklist](../epic_jev_support/checklist.md) owns sequencing. A3 remains proposed.

Build an explicitly enabled, warnings-only policy over a small reviewed rule pack. A finding or unavailable check must
never introduce a Jev denial or `needs_review`. An independently configured policy or supervisor retains its existing
behavior. This card does not adjudicate plan alignment, change Stop review, or claim avoided supervisor calls.

## Activation and verified starting points

- [x] Verify A1 merged through [PR #268](https://github.com/hapa1i/multi-forge/pull/268) as `9778007a`; close it on
  `main` as `f7ce7a9a`. Its closeout passed 116 focused tests, full pre-commit and the 676-source link audit.
- [x] Create the A2 branch, move the card from `proposed/` to `doing/`, and select it in the epic. A1 and
  [B3](../../done/codex_policy_warnings/checklist.md#merged-closeout) are shipped prerequisites.
- [x] Inspect policy composition, bundle activation, action adapters, state serialization and both feedback paths at the
  branch base. The constraints below come from code, not from assuming the proposed interfaces already exist.

| Existing owner                                                                                                                        | A2 responsibility                            |
| ------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------- |
| [`core.judgments`](../../../../src/forge/core/judgments/openrouter.py)                                                                | Typed transport, ZDR, attempt accounting     |
| [`policy.engine`](../../../../src/forge/policy/engine.py)                                                                             | Atomic registration and warning composition  |
| [`deterministic.registry`](../../../../src/forge/policy/deterministic/registry.py)                                                    | Current bundle vocabulary/factory            |
| [`ops.policy`](../../../../src/forge/core/ops/policy.py)                                                                              | Shared terminal/direct activation            |
| [`session.manager`](../../../../src/forge/session/manager.py), [`overrides`](../../../../src/forge/session/overrides.py)              | Session-bound acknowledgment and derivation  |
| [`semantic.deadline`](../../../../src/forge/policy/semantic/deadline.py)                                                              | Existing shared hook budget                  |
| [`reactive.env`](../../../../src/forge/core/reactive/env.py)                                                                          | Evaluation run ancestry                      |
| [`ActionContext`](../../../../src/forge/policy/types.py), [`action_identity`](../../../../src/forge/policy/action_identity.py)        | Evidence coverage and cache identity         |
| [`Claude adapter`](../../../../src/forge/cli/hooks/policy.py), [`Codex adapter`](../../../../src/forge/cli/hooks/codex_policy.py)     | Native action normalization                  |
| [`hook commands`](../../../../src/forge/cli/hooks/commands.py), [`policy CLI`](../../../../src/forge/cli/policy.py)                   | Action lifetime and evaluation orchestration |
| [`Codex feedback`](../../../../src/forge/cli/hooks/codex_policy_feedback.py), [`policy.store`](../../../../src/forge/policy/store.py) | Audience rendering and bounded audit         |

The synchronous engine currently builds all bundles through the deterministic registry. It evaluates every regular
policy, then invokes a resolver only for unresolved review without a denial. An uncaught policy exception becomes a
denial under `fail_mode=closed`; A2 must contain unavailable-check failures at its own boundary. Do not weaken the
engine's fail mode or route warnings through the plan supervisor.

Both hook adapters truncate presentation content at 5,000 characters. Codex also truncates update diffs and evaluates
patch files separately; deletion-only operations are skipped. Full action fingerprints are computed before truncation,
but a hash does not restore missing evidence. The CLI diff path has similar bounded views. Coverage must become explicit
before those views can support semantic judgments.

The A1 handoff is [measured transport readiness](../../done/jev_client_probes/checklist.md#merged-closeout): mandatory
ZDR, a 30,000-byte serialized request screen, optional cost, observed answer variance and an async caller-deadline API.
Its default permits two attempts; A2 will explicitly request one. The measurements do not establish decision quality or
a safe hook timeout. Keep the existing downstream v2/usage v1 schemas and `core_llm` route.

Review at `de7009d7` confirmed that derived sessions copy policy intent, relaunch also copies overrides, and raw
`policy`, `policy.bundles` and `policy.bundle_config` overrides pass key validation. **User decision, 2026-10-14:**
every derived session needs a fresh acknowledgment of paid repository-data sharing. Resuming the same session retains
its acknowledgment. Configuration inheritance alone cannot authorize dispatch.

Both policy hooks already use `hook_review_budget`: 55 seconds shared across context loading, files and review stages,
with five seconds reserved before the 60-second native timeout. A1 reads run identity from the environment; its emitter
already accepts an explicit `RunIdentity`. Consumer invocation accounting needs a small extension to `judge()`.

## Separate prerequisite: Claude feedback permissions

The [Claude feedback permissions prerequisite, PR #269](https://github.com/hapa1i/multi-forge/pull/269), merged as
`e9c144eb`; its [closeout](../../done/claude_policy_feedback_permissions/checklist.md#merged-closeout) is on `main` at
`18b5670e`. This branch includes both through the 2026-10-15 rebase. The fix removes the shared responder's explicit
allow for all policy users. Its regression matrix covers injected outcomes through the shared response/audit path,
without claiming individual policy evaluation or supervisor registration coverage. Read-hygiene retains its documented
input-correction exception.

The user authorized merge after choosing to skip paid native testing. Native Claude receipt/permission evidence remains
absent; B3's Codex trial does not prove it. A2's native warning-delivery gate stays open, and this rebase authorizes no
native trial or paid Jev request. Keep only the merged `done/` card when consuming this prerequisite.

## Slice 1: reviewed rules and offline evaluation contract

- [ ] Establish `src/forge/policy/rule_pack/` as the proposed home for pack definitions, evidence preparation and the
  warning policy. Use `jev_rule_pack` as the explicit bundle name. Keep pack semantics separate from the transport and
  from the plan supervisor; no general rule-authoring framework or new vendor SDK.
- [x] Record the user-selected family: broader compatibility wrappers, including module functions, methods, aliases,
  decorators and callbacks; do not impose the rejected local-helper-only scope. Revise the
  [evidence contract](evidence/initial-rule-review.md) to separate compatibility retention, independent boundary
  responsibilities and trusted surface/exception facts. A warning does not establish that deletion is safe.
- [x] Bind the candidate to [coding standards §5](../../../developer/coding_standards.md#5-interface-changes), including
  justified exceptions and surface distinctions. A missing marker comment is not itself a violation. Define positive,
  compliant and insufficient-context examples before coding; exclude rules whose required facts the hook cannot supply.
- [x] Define the consumer outcomes: not applicable, evaluated without a warning, warning, uncertain and unavailable.
  Only a covered, valid answer can support an assessed outcome. Give uncertainty and unavailable evidence visible fixed
  diagnostics without inventing a violation, model justification, denial or review request.
- [x] Retain a versioned manifest of 17 constructed hook-shaped actions with reconstruction assumptions, provenance and
  human outcomes/question labels. It covers adapters/decorators, exceptions, missing context, injection and a
  multilingual variant. Keep related mutations within their seven families and each family within one split. These
  fixtures establish neither real-world prevalence nor warning quality; no historical cohort is implied.
- [x] Add a dry-run/fixture-first evaluation harness under `scripts/experiments/jev/`, with tests flat in
  `tests/src/scripts/`. Follow A1's path-based loader in `tests/src/scripts/test_jev_probe.py`; the existing
  `codex_probe.load_script` is fixed to `codex-hooks/`. Store methodology, manifests, labels and sanitized results under
  this card's `evidence/`; keep fake transports in tests/the harness.

The preparation stage is implemented in `scripts/experiments/jev/rule-pack-eval.py`: it validates native action shapes,
keeps source families in one split, binds adjudications to evidence and semantic criteria, excludes labels and reviewer
notes from model inputs, and applies the declared host applicability table before building size-checked A1 payloads.
Prompt wording has a separate identity. The saved-response evaluator now binds corpus membership/splits, predictions,
settings and adjudications independently; it reports per-cohort/per-repetition confusion, abstentions, coverage,
question calibration, latency and known/unknown cost. Question changes invalidate the corresponding payload hashes. The
outcome combiner requires explicit question bands and preserves coverage gaps and contradictions. There is no live mode
or quality acceptance verdict. Constructed labels are now complete; real predictions and numerical gates remain open.

The 2026-10-15 review follow-up passed 148 focused outcome, harness, regression and label-isolation tests. Coverage
includes distinct per-question bands, shared host diagnostics, held-out edits preserving calibration captures,
model-snapshot mismatches, host-label conflicts and misses, malformed JSON, transport admission, missing latency,
source-family counts and exact interval endpoints. The original preparation report still reproduces byte-for-byte. These
are implementation fixtures, not calibration results. See [rule-pack design](../../../design_rule_packs.md) for
implemented ownership.

Saved-prediction schema 2 requires the expected resolved model plus original HTTP status and response byte size. Reports
retain bounded failure text, reason counts, separate host-label comparisons and pipeline misses, and evaluator source
hashes. Corpus identity binds membership/families/splits; observations bind the content actually scored. This replaces
schema 1's draft fixture format; this card records no paid A2 captures. Rule and decision versions validate against
their shared owners. Constructed adjudication is complete; representative evidence and quality acceptance remain open.

Aggregate validation passed: `make test-unit` (11,076 passed, 117 deselected), `make test-regression` (1,924 passed) and
`make pre-commit`. The CLI fixture smoke kept three host decisions separate from nine model candidates, marked eight
absent responses unavailable and reported no accuracy result for the unadjudicated corpus. The exact-file token cache
regression also passed. The user approved the updated design overview's token count on 2026-10-15; its refreshed cache
records 20,757 provider tokens. No paid A2 request or native trial ran.

The first full unit run failed the existing `test_deadline_reports_timeout` assertion once. Its six-test watchdog module
and the full unit rerun passed without source or test changes.

### Human review and runtime evidence continuation

- [x] Prepare a review packet bound to current rule semantics, corpus membership/splits and exact case evidence.
  Withhold proposed outcomes, reviewer rationales, reconstruction notes, prior human labels and model responses; retain
  IDs and provenance without claiming a fully blinded independent study.
- [x] Validate human review import into a new corpus: pending rows preserve prior labels, explicit replacements require
  acknowledgment, and changed evidence or unresolved disputes/exclusions stop the import. Retain notes in the review
  ledger, with the corpus referencing it; do not promote authored proposals to human truth.
- [x] Record the current cohort/family inventory and prepare a concrete runtime evidence proposal against the existing
  owners. The proposal remains unimplemented; it does not satisfy action preparation or activation checks below.
- [x] Import all 17 human constructed outcomes, retaining unknown question answers, reviewer references and notes.
  Recount positive/negative families in the [feasibility checkpoint](evidence/corpus-feasibility.md); no review remains
  pending. AI-assisted judgments do not imply independently blinded review.
- [ ] Decide additional acquisition scope versus a constructed-only smoke-test claim at the feasibility gate below.
- [x] Revise the rule to advisory supplied-evidence semantics and version its criteria, review packet and decision
  settings. Keep structural gaps unavailable and materially ambiguous boundary evidence uncertain; do not import model
  proposals as human labels.

2026-10-15 continuation verification: 235 focused rule-pack, probe, evaluation, review and integrity tests passed. The
tracked packet matches regenerated JSON content; importing its 17 pending rows preserves the source corpus exactly as
JSON without creating labels. The original preparation report still reproduces byte-for-byte. Independent review found
an attribution/output-size amplification edge; bounded reviewer/reference fields and an exact emitted-size check now
cover completed and pending imports, including Unicode expansion and empty stdout on failure. The stale-adjudication
recovery is documented in the review guide. No runtime policy code or provider call is part of this slice.

2026-10-16 advisory revision: rule `draft-3`, evidence contract 4 and decision version `draft-2` replace the previous
semantic standard. Warnings identify covered retention without a justification established in the supplied evidence;
they do not prove an unseen requirement absent. Required names/signatures/identities may justify pure aliases, while an
ordinary caller using an old name does not alone establish that requirement. The runtime proposal replaces exact-file
enumeration with a project default and scoped exceptions; its resolver and runtime scope representation remain pending.
Packet-label correctness and practical warning usefulness require separate evaluation.

Verification: 238 focused rule-pack, probe, evaluator, review, host-diagnostic and integrity tests passed. The new
regression rejects prior labels, review packets, captures and settings after a semantic revision. Regenerated packet and
preparation JSON reproduce, pending import preserves the corpus, and worksheet/source hashes match. At that checkpoint,
all 17 action, scope, provenance and split records were unchanged and unadjudicated. Independent review verified these
identities and found a stale checklist scope requirement and ambiguous absent-justification prose; both are corrected.
No paid request or native trial ran.

2026-10-16 human review: eight retained ledgers complete all 17 constructed outcomes across seven families. The
[review guide](evidence/human-review.md) links each batch and its exact judgments, question answers and notes; the
[feasibility checkpoint](evidence/corpus-feasibility.md) records counts and limits. Each question has nine known
calibration answers. Held-out has four known coverage answers and three known retention/boundary answers; `partial-edit`
retains two unknown answers. Four host reviews have null answer objects. Held-out has only one positive family.

The user confirmed these judgments after AI-assisted discussion, not independent blinded review. The blank packet
remains reproducible; each import preserves earlier labels and all action, scope, provenance, split and payload
identities. No model answer sheet supplies human labels. These constructed judgments establish neither historical
accuracy nor model quality, and do not satisfy runtime admission.

Pre-merge verification: 239 focused tests pass, including
[`test_bug_272_jev_review_relocation.py`](../../../../tests/regression/test_bug_272_jev_review_relocation.py).
Corpus-relative ledger references survive a card move with replayed labels and adjudication identity unchanged. The
[review guide](evidence/human-review.md) records the reference migration and remaining provenance limits.

Validation note: the seventh batch pushed this checklist above the local token screen. The size checker automatically
obtained an Anthropic token count before failing for missing cached evidence; that document-specific request had not
been separately approved. The repeated review summaries were then condensed below the local screen, preserving the
ledgers. Subsequent token checks use the network-restricted sandbox and already-prepared dependencies. The local
end-of-file hook runs separately because the sandbox forbids its write-mode reads of unchanged `.agents` files. No Jev
evaluation or native trial was dispatched.

## Slice 2: feasibility before runtime work

- [x] Review a bounded local real-action acquisition scope before collection: revisions or selected native actions,
  reconstruction/sanitization, retained data, exclusions and source-family splits. Keep CLI whole diffs separate. No
  transcript inspection, repository collection or provider dispatch is authorized by this checklist.
- [ ] Measure supplied interface evidence, trusted governance and symbol-exception mapping on that cohort before
  implementing the runtime proposal. Count covered, unknown, ambiguous, unsupported and refused actions with reasons;
  missing context cannot be filled by undeclared repository reads. Finalize rule/contract versions against these
  results.
- [ ] Compare existing marker checks and a bounded AST baseline on identical evidence and applicability. Obtain a
  separate human caller/contract review of warning usefulness; keep that extra context out of model inputs and the
  original packet labels. Require usefulness as well as coverage, misses and warning burden.
- [ ] Review minimum positive/negative family counts and numerical gates under the
  [evaluation plan](evidence/evaluation-plan.md#before-real-evaluation-or-runtime-admission), including interval
  treatment and failed-gate responses. Empty strata cannot pass; no thresholds are selected here.
- [ ] Prepare a separately authorized synthetic calibration capture for the nine model candidates, then select bands
  from calibration responses only and freeze settings. Prepare a separately authorized capture for the four held-out
  model candidates afterward. Record exact manifests, repetitions, caps and isolated homes; exhausted A1 approvals do
  not apply. These exposed scenarios permit a limited output check, not unseen-scenario generalization.
- [ ] Review the evidence and choose proceed, revise/narrow or stop before Slices 3–5. Constructed-only results support
  a smoke test, not runtime quality. Any runtime go-ahead requires representative action coverage, attributable policy
  facts and useful warnings meeting the predeclared feasibility gates.

The user approved the [bounded local study scope](evidence/feasibility-study-plan.md) on 2026-10-16: up to six inactive
managed sessions and 120 sanitized native actions, retained privately. This approval excludes provider requests,
publication, wider caller reads and the plan's draft numerical gates. The
[synthetic calibration proposal](evidence/calibration-run-plan.md) has a separate manifest and spend decision. The
selected native paths were missing, so no actions were collected; coverage and usefulness remain unmeasured.

## Slice 3: complete action evidence and bounded dispatch

- [ ] After the feasibility decision, implement and verify the owner-approved project default, scoped exceptions and
  pinned-authority limits. Same effective applicability may batch across surfaces; ambiguous exception mapping or mixed
  applicability remains unavailable. Version runtime scope explicitly. Reconcile the coding-standards `future 1.0` /
  `0.x` wording before selecting a production default; this proposal selects none.

- [ ] Add a small action-scoped preparation seam shared by hooks and the explicit CLI check. Retain a bounded complete
  action envelope before legacy presentation truncation. Run existing policies/resolvers once per file in their current
  test-first order, then compose the whole action before A2 dispatch. Register A2 as an explicit deferred warning phase,
  not another eager regular policy. Merge its attributed decisions/state without rerunning earlier policies.

- [ ] Skip A2 entirely when any file already denies or leaves unresolved `needs_review`, including an independent
  supervisor denial. Record `skipped_blocked`, zero attempts and no assessed verdict. For a multi-file atomic patch, an
  otherwise clean first file cannot trigger Jev before a later denial is known. Preserve existing audit and state
  persistence rules; the skip must not suppress a blocking diagnostic or imply that A2 reviewed the action.

- [ ] Represent full action identity, evaluated evidence identity, file/path attribution and completeness separately.
  For Claude, preserve Write content and Edit old/new text plus replacement semantics. For Codex/CLI patches, retain
  file boundaries, rename metadata and the relevant hunks. Never treat a truncated prefix or a fingerprint as coverage.

- [ ] Admit only the rule's declared evidence scope. Missing context, unsupported/binary/combined patches, unsafe paths,
  ambiguity and oversized actions produce explicit unavailable coverage. Record deletions and other non-applicable
  operations as such; do not count them as reviewed. Do not read arbitrary repository files to fill gaps implicitly.

- [ ] Resolve effective applicability and scoped exceptions from an attributed host-owned policy source and bind their
  exact content to the evaluated evidence identity. Preserve actual surface facts where supported; a complete approved
  project default can establish applicability without fabricating a surface class. Unknown governance or ambiguous
  exception mapping remains unavailable. The fixture corpus's invented scope facts are not a production source. Broader
  wrapper support does not authorize repository crawling or an undisclosed expansion beyond supplied action evidence.

- [ ] Batch all applicable file/rule questions over one bounded state. The first implementation permits at most one
  physical Jev request per native action, `max_attempts=1`, with no automatic splitting. If the complete eligible batch
  exceeds A1 admission, send nothing and identify the uncovered action; no silent subset of files or rules.

- [ ] Reuse `hook_review_budget` through `review_deadline`/`review_scope`; do not start a second hook deadline. A2 runs
  after existing reviews and uses only their remaining allowance. Set a conservative five-second A2 stage default and
  maximum, including A2 preparation, credentials and I/O; this is a product limit, not a measured latency guarantee. It
  can only shorten the shared 55-second window. No remaining allowance means no dispatch; no reset per file/rule. Give
  an explicit CLI check its own bounded scope using the same stage limit.

- [ ] Bridge the synchronous entry point to A1's async client once per action. Keep loop ownership explicit, propagate
  cancellation and release resources. Follow `SyncAdapter._check_no_running_loop` before creating a coroutine, without
  using its text-completion API. Exercise an already-running loop, exhausted shared budget and expiry during I/O through
  clock/transport fixtures; no thread escape or nested event loop may extend the deadline.

- [ ] Treat state text as data. Fixed rule instructions and immutable IDs cannot be replaced by comments, filenames or
  content in the action. Validate exact question coverage and file/rule mapping before composing any warning.

- [ ] Convert A1 errors and unexpected consumer evaluation failures into bounded unavailable diagnostics even under
  engine `fail_mode=closed`. Preserve any independently valid attempt accounting. Keep cancellation distinct from a
  clean assessment; a missing response or malformed answer cannot populate the clean-result cache.

**Admission gate:** fixtures must prove whole-action coverage and the physical request limit before any hook inference.
The stage limit is a consumer choice, not an A1 latency guarantee. Running A2 last preserves the existing reviewer
budget; it may reduce A2 coverage on slow reviews. Report that skip without extending the hook or relabeling completed
independent reviews as unavailable. Measure the coverage/latency tradeoff in the evaluation.

## Slice 4: activation, cache and audit

- [ ] Add a new `src/forge/policy/registry.py` if needed to generalize registration, delegating deterministic bundles to
  their current implementations. Update engine construction, CLI list/choices and `core/ops/policy.py` together.
  Validate all bundle names, config owners, pack versions and field types before registering anything; reject unknown
  settings.
- [ ] Extend the shared terminal/direct activation owner with an explicit acknowledgment, proposed
  `--acknowledge-paid-data-sharing`: disclose API charges and that supplied repository action content goes to OpenRouter
  and its selected TypeSafe provider with ZDR required. Persist a versioned acknowledgment bound to the target session
  instance and admitted provider/data scope. No interactive prompt inside a hook. A one-shot
  `forge policy check --bundle jev_rule_pack` requires its own acknowledgment and does not enable future session calls.
- [ ] Keep A2 disabled in fork, fresh-resume and relaunch children until their own acknowledgment. Strip inherited A2
  activation/acknowledgment from both intent and overrides, retaining other policy configuration. Bind validation to
  session identity/creation as well as project scope so copied grants cannot activate another instance. Cover every
  child-creation path, including native/transfer/rewind variants; reopening the same Forge session instance retains a
  matching grant only when no child is created. Missing/stale acknowledgments produce zero calls and operator recovery.
- [ ] Guard raw overrides by parsed value and effective result: reject unvalidated Jev activation or acknowledgment
  through `policy.bundles`, `policy.bundle_config`, parent `policy` objects, dotted paths or wildcard expansion,
  directing the operator to the validating activation command. Preserve unrelated policy overrides. Independently
  validate the acknowledgment before dispatch so inherited/stale settings or hand-edited bundle lists alone cannot
  authorize a call.
- [ ] Ordinary sessions, existing `coding_standards`, supervisor setup, list/status and imports remain zero-Jev paths.
  Existing manifests without the new acknowledgment remain readable and disabled for A2; document strict session-schema
  compatibility. Revocation and scope changes invalidate the grant before the next dispatch.
- [ ] Define the finite supported config fields and defaults, including model/pack version, timeout and cache TTL;
  reject invalid values atomically. Keep evaluated thresholds in the versioned decision rule. Preserve the shared
  activation contract for the explicitly supplied bundle set and unrelated intent; never enable it across sessions.
- [ ] Use the existing credential chain with environment/file precedence and `auth_ignore_env`; verify missing auth and
  no-`.env` behavior offline. Resolve and check the effective Decisions URL against the acknowledged endpoint before
  sending any action: A1 supports custom gateway bases, but the current acknowledgment covers canonical OpenRouter only.
  A changed credential/base-URL setting must not silently widen that scope. Every physical attempt retains mandatory
  ZDR. Disabled/not-applicable/local-refusal paths make no network request; no direct TypeSafe or subscription fallback.
- [ ] Key cached validated results by session, canonical full action, exact evidence/coverage, pack/rule/question
  versions, endpoint/requested model and decision-rule version. Retain resolved model identity and declare how model
  drift expires reuse. Bound TTL/entries and invalidate stale/malformed entries without losing independent policy state.
- [ ] Cache reuse must reproduce the attributed outcome without a new provider attempt or charge. Do not cache
  unavailable/partial results as clean; observed answer variance prevents claiming fresh inference is deterministic.
  Preserve Codex's existing rule that a denied atomic patch does not advance policy state.
- [ ] Keep new A2 data in each persisted decision entry at or below 4 KiB of encoded JSON, including summaries and
  references; the existing 100-entry log must not embed 30-KB excerpts. Store full evaluated evidence and raw typed
  answers in content-addressed local artifacts outside the manifest lock. Record model, rule/source, action/evidence
  identity, coverage, outcome and attempt/run IDs; bound artifact size/count/retention and make missing artifacts
  inspectable without inventing evidence. Persist only bounded metadata/references in cache state too, without duplicate
  excerpts. Add deletion/reset ownership and old-audit readability to the design.
- [ ] Expose an optional explicit `RunIdentity` on A1's `judge()` while retaining its environment fallback for current
  callers. Mint one child run via `derive_child_run_identity` per uncached A2 batch, retaining parent/root ancestry;
  pass it without mutating global environment. A1 already threads identity into `emit_attempt`. Join policy audit to
  that same run and distinguish cached assessments, skipped actions, attempts and independent reviewer calls.
- [ ] Use A1's consumer command field and existing telemetry schemas. Two actual evaluations in one session must appear
  as two verb invocations, while retries share their evaluation run and retain distinct request IDs. A cache hit makes
  no new provider invocation. Reconcile the API change with the epic/A3 before merge; no raw source in usage records or
  parallel billing ledger. Rule citations and assessed evidence remain separate; no fabricated `VerifiedCitation`.
- [ ] Run the focused policy/CLI and telemetry integration checks during this slice. Confirm trace show/explain, costs
  by model/verb and session activity agree on injected attempts, with no synthetic proxy traffic or double charge.

## Slice 5: warnings the model and operator can inspect

- [ ] Produce structured `warning_findings` with stable rule/path attribution and legacy warning strings; keep
  `violations` for denials. Fixed rule text may use `provenance=policy`; action excerpts remain attributed input data.
  Do not turn a Jev probability into a verified quotation, free-form explanation or ground-truth assertion.
- [ ] Extend Claude's formatter so `policy_summary_feedback=on` includes bounded rule text/intent, source and assessed
  action evidence in `additionalContext`. Define its output bound and omission notices. Consume the separately shipped
  permission fix; A2 must not reintroduce an explicit allow or silently change every existing policy's permissions.
- [ ] Extend feedback classification with A2-owned diagnostics for missing acknowledgment/auth, insufficient action
  evidence, uncertainty, exhausted budget, transport/response failure and skipped blocked actions. Keep
  `evidence_unavailable` reserved for persistence failure. Say which rule-pack check was unavailable without calling
  other policy reviews unreviewed. Use distinct codes such as `jev_insufficient_evidence`, `jev_auth_unavailable` and
  `jev_deadline`; test mixed A2 failure plus successful supervisor review.
- [ ] Render owner-specific operator recovery and inspection: `forge auth login -c openrouter` only for relevant auth
  failures; `forge telemetry trace show <request_id>` only when an attempted request has that ID; session/audit
  inspection for local refusal or missing context. Replace the unconditional supervisor-status footer for A2-only
  output. Model context contains the assessment scope, not operator recovery commands in source-only mode.
- [ ] Feed the existing B3 Codex renderer, retaining its audience budgets, provenance rules, source-only preference and
  executor admission. Keep inspection commands in operator output under source-only; never introduce a new explicit
  `permissionDecision=allow`. Policy-authored findings already bypass B3's plan-quotation branch; preserve that path and
  keep legacy/unattributed A2 warnings from acquiring reviewer wording or fabricated quotations. Count omissions rather
  than silently dropping findings.
- [ ] With feedback off, suppress allowed-action model context while retaining substantive operator diagnostics and
  audit. Unknown/unsupported Codex executors retain B3's existing channel restrictions. Clean A2 results add no warning;
  unavailable assessments cannot be labeled aligned. Do not change unrelated supervisor summaries.
- [ ] Exercise warning-only and unavailable outcomes with no supervisor, a regular supervisor and a cascade resolver. A2
  creates no resolver request or extra supervisor call; independently configured checks still run. Existing denials
  retain priority, blocking reasons and TDD state behavior with either feedback setting.
- [ ] Add injected-client hook integrations for both runtimes, then verify native delivery using a separate bounded
  trial plan. Model receipt of the substantive rule/evidence must be observed; stderr or an operator `Hook` notice alone
  is insufficient. Preserve the distinction between native-runtime quota and Jev API cost in the run record.

## Slice 6: release decision

- [ ] Reconcile final runtime behavior with the pre-runtime evidence, approved quality gates and supported-context
  matrix. Publish failures and any required new evaluation under `evidence/`; runtime contract/model changes invalidate
  affected results. Do not duplicate or silently relax the [evaluation plan](evidence/evaluation-plan.md).
- [ ] Require the integration, native-delivery and documentation checks below before release. A later opted-in warning
  trial remains separately authorized; transport/formatter fixtures cannot establish quality or quota savings.

## Acceptance fixtures

Paths under `tests/src/policy/rule_pack/` and the A2 harness/integration test names below are planned additions.

| Test               | Fixture                                                    | Assertion                                                 | Test file                                                                                                   |
| ------------------ | ---------------------------------------------------------- | --------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| Atomic activation  | Unknown pack/field; invalid timeout                        | No partial engine or intent write                         | `tests/src/core/ops/test_policy_ops.py`; `tests/src/policy/test_engine.py`                                  |
| Acknowledgment     | Fork/fresh-resume/relaunch; same-session resume            | New children disabled; same instance retained             | `tests/src/session/test_manager_integration.py`; new `tests/regression/test_bug_jev_consent_inheritance.py` |
| Override bypass    | Parent/dotted/wildcard policy edits; copied grant          | No grant creation or unauthorized dispatch                | `tests/src/session/test_overrides.py`; `tests/src/core/ops/test_policy_ops.py`                              |
| Rule semantics     | Wrapper, exception, missing context                        | Versioned applicability; explicit coverage                | `tests/src/policy/rule_pack/test_definitions.py`                                                            |
| Evidence integrity | Long Edit; rename; multi-file patch                        | Full identity and declared evaluated scope                | `tests/src/policy/rule_pack/test_evidence.py`                                                               |
| Batch limit        | Several files/rules; oversized batch                       | One request, or zero with unavailable result              | `tests/src/policy/rule_pack/test_runner.py`                                                                 |
| Deadline/failure   | Expired clock; 402/413/524; malformed answer               | No retry or Jev block; retained attempt usage             | `tests/src/policy/rule_pack/test_runner.py`                                                                 |
| Shared budget      | 45-second reviewer; exhausted 55-second hook; running loop | A2 runs last, at most five seconds; no deadline extension | `tests/src/policy/rule_pack/test_runner.py`; `tests/src/cli/hooks/test_policy_check_cascade.py`             |
| Injection          | Instructions in content/path/comment                       | Fixed questions and attribution preserved                 | `tests/src/policy/rule_pack/test_evidence.py`                                                               |
| Composition        | Warning/error plus TDD deny or supervisor                  | Denial preserved; no A2 escalation                        | `tests/src/policy/test_engine.py`; `tests/src/cli/hooks/test_policy_check_cascade.py`                       |
| Blocked action     | Literal compat marker; later-file deny; reviewer denial    | Zero Jev attempts for the entire action                   | `tests/src/policy/rule_pack/test_runner.py`; `tests/src/cli/hooks/test_codex_policy_check.py`               |
| Cache/audit        | Same action; changed rule/model/hidden tail                | Correct reuse/invalidation; inspectable evidence          | `tests/src/policy/rule_pack/test_policy.py`                                                                 |
| Audit size         | 100 near-limit inputs; missing artifact                    | A2 entry at most 4 KiB; explicit evidence availability    | `tests/src/policy/rule_pack/test_policy.py`                                                                 |
| Auth/defaults      | No key; disabled pack; environment/file keys               | Actionable unavailable result; no incidental calls        | `tests/src/policy/rule_pack/test_runner.py`                                                                 |
| Claude feedback    | Finding/unavailable; feedback on/off                       | Bounded content or operator/audit only                    | `tests/src/cli/hooks/test_policy_feedback.py`                                                               |
| Codex feedback     | Multi-file; source-only; unadmitted executor               | B3 bounds and permissions preserved                       | `tests/src/cli/hooks/test_codex_policy_feedback.py`                                                         |
| Diagnostic owner   | Jev timeout/insufficient input plus completed supervisor   | Accurate A2 scope/recovery; no false plan notice          | `tests/src/cli/hooks/test_codex_policy_feedback.py`; `tests/src/cli/hooks/test_policy_feedback.py`          |
| CLI parity         | File/diff; terminal/direct activation                      | Same pack vocabulary and content-source rules             | `tests/integration/cli/test_policy_cli_contract_integration.py`                                             |
| Hook accounting    | Two evaluations, cache hit and failed attempt              | Distinct evaluation runs; unchanged ancestry/schema       | `tests/integration/core/test_jev_rule_pack.py`; `tests/src/core/judgments/test_usage.py`                    |
| Evaluation         | Historical/constructed hook actions; empty positive split  | Separate metrics; no leakage or unsupported quality pass  | `tests/src/scripts/test_jev_rule_pack_eval.py`                                                              |

## Verification and documentation

- [ ] Run `make deps` before targeted unit work, then focused rule-pack, engine, action-identity, adapter, feedback,
  shared activation and CLI tests. Add a regression for each discovered bug; ordinary tests use injected transports.
- [ ] Run relevant hook and CLI integrations through `./scripts/test-integration.sh`, including
  `tests/integration/docker/test_policy_hooks.py`, `tests/integration/cli/test_policy_cli_contract_integration.py` and
  the new injected-client accounting integration. Extend `tests/integration/docker/test_session_lifecycle.py` for
  derived-session acknowledgment and retained ordinary policy inheritance. Use `PYTHON_DOTENV_DISABLED=1` for the
  no-`.env` checks. Do not accidentally launch credential-backed native tests as ordinary fixture tests.
- [ ] Verify the authorized native Claude/Codex warning paths with feedback on/off, supported executor enrollment and
  the evidence-inspection commands. Record runtime versions, exact request/quota limits and observed delivery. Reuse
  B3's probe conventions without assuming its TDD/stub evidence proves A2's formatter output.
- [ ] Check `forge policy list`, `status`, `check --bundle coding_standards --file <path>` and
  `git diff | forge policy check --bundle coding_standards --diff`, plus fixture-backed Jev equivalents. Read outputs
  stay on stdout, diagnostics on stderr; keep `tests/src/cli/test_output_streams.py` coverage for changed read surfaces.
- [ ] Sync `docs/design_workflows.md` for the first-class rule pack, action preparation, composition and state
  ownership; `docs/design_session_execution.md` for hook delivery/budgets; and runtime/telemetry design for consumer
  admission, explicit A1 run identity and bounded evidence storage. Update session design for acknowledgment
  inheritance, plus `docs/design.md` if registry/operation ownership changes. Sync both consumers at the epic handoff.
- [ ] Update `docs/end-user/policy.md`, `docs/end-user/config.md`, `docs/end-user/authentication.md`,
  `docs/cli_reference.md` and runtime-config help with explicit paid opt-in, model/pack support, timeout/cache behavior,
  data-sharing acknowledgment, derived-session behavior, unavailable diagnostics, feedback settings and inspection.
  Update installation guidance if credentials/resources or extension delivery changes. Normative docs describe only
  implemented behavior.
- [ ] Build and smoke a clean wheel if rule definitions become package resources or this changes bundled extensions,
  installer/runtime assets or packaging. Pure Python policy additions alone do not trigger that requirement.
- [ ] Run `make test-unit`, `make test-regression`, full `make pre-commit`, Markdown link/file-size checks and
  `git diff --check` on the integrated A2 head. Refresh tracked token counts only for changed documents needing them.
  Record failures/skips as well as passing evidence; paid native checks remain governed by their own run plans.

## Closeout

- [ ] Link the approved rule/evaluation contract, corpus provenance, quality results, native-delivery evidence and
  telemetry verification. Record unsupported contexts and any unsatisfied gate explicitly.
- [ ] Reconcile shared cache/audit and A1 contract changes with the epic/A3; A2 results do not validate A3 plan
  alignment. Keep the epic active and A3 unactivated unless separately selected.
- [x] Open the draft A2 PR with concise implemented scope, limitations, actual validation and outstanding acceptance
  gates. [PR #270](https://github.com/hapa1i/multi-forge/pull/270) and
  [PR #271](https://github.com/hapa1i/multi-forge/pull/271) shipped the foundations; human review shipped through
  [PR #272](https://github.com/hapa1i/multi-forge/pull/272).
- [ ] After review/merge, record the merged head, finish design/end-user sync, add the completed-work change-log entry
  and propose durable notes for human review.
- [ ] Move A2 to `done/` only when its acceptance gates are satisfied and the code is merged; repoint inbound links and
  update the epic's next-member decision.

## Foundation merge and continuation

2026-10-15: [PR #270](https://github.com/hapa1i/multi-forge/pull/270) merged as
`9442c1e5503ea66f9761a995e71c428230d4d49f`, with the same tree as reviewed head `55ce6e24`. All five GitHub checks
passed. The final independent review passed 215 focused tests and seven fixture-backed policy CLI integrations and
reproduced the offline preparation report. The implementation also records 11,001 unit tests, 1,889 regressions and 46
distinct targeted integrations below. Session, telemetry and end-user policy docs describe the shipped foundation.

A2 remained `doing/` and continued on `codex/jev-rule-pack-evaluation` with the offline outcome contract and evaluation
harness, subsequently merged in [PR #271](#offline-evaluation-merge-and-next-gate). A3 can use A1's optional explicit
run identity without changing existing ambient callers or schemas; its own evaluation and acceptance remain separate.

## Offline evaluation merge and next gate

2026-10-15: [PR #271](https://github.com/hapa1i/multi-forge/pull/271) merged as
`791d9872bb39631a8b769ed739c680fdd07e688a`, with the same tree as reviewed head `cd008613`. All five GitHub checks
passed. Local validation passed 148 focused tests, 11,076 unit tests (117 deselected), 1,924 regressions and full
`make pre-commit`. The first unit run hit the existing watchdog timeout test; its six-test module and the full unit
rerun passed unchanged. The schema-2 CLI fixture smoke retained three host decisions, nine model candidates, one saved
observation and eight missing observations without claiming accuracy. Offline preparation reproduced byte-for-byte.

Shared rule definitions, host applicability, fixed diagnostics and saved-response evaluation are shipped. The
[rule-pack design](../../../design_rule_packs.md) records ownership, and the
[evaluation plan](evidence/evaluation-plan.md) records identity, metric denominators and limitations. This slice adds no
activation command or hook dispatch and changes no A1 API or telemetry schema. No paid A2 evaluation or native trial
ran.

A2 and the epic remain `doing/`; A3 remains proposed. The 2026-10-16 continuation completes constructed human review and
the runtime evidence proposal. The next [feasibility gate](#slice-2-feasibility-before-runtime-work) measures
representative evidence coverage and useful warnings before implementing that proposal. Numerical gates, runtime
activation, audit/cache integration and native delivery remain open. This handoff authorizes no collection or paid run.

## Human review merge and feasibility continuation

2026-10-16: [PR #272](https://github.com/hapa1i/multi-forge/pull/272) merged as
`64317485a8564684ab790974744be0ee978d3804`, with the reviewed changes from `53834cbd` and all five CI checks passing.
Local verification passed 239 focused tests, all pre-commit hooks across the sandboxed run and separate local EOF rerun,
the 691-source link audit and `git diff --check`. Eight retained ledgers reproduce all 17 judgments; the relocation
regression preserves references, payloads and report identity after a card move.

A2 and the epic remain `doing/`. `codex/jev-rule-pack-feasibility` starts from the merge to prepare bounded local
acquisition, structural comparisons and a synthetic calibration capture. Human label provenance and held-out exposure
limits remain unchanged. Collection and paid dispatch require their concrete scope decisions; runtime implementation
waits for the Slice 2 decision. The prior token-count incident remains recorded above. No new A2 quality or native
delivery claim follows from this merge.

## Execution evidence

2026-10-14: `make deps` passed. A1 now accepts `judge(run_identity=...)`, retaining the environment fallback for
existing callers. The client suite passed 53 offline tests. The required no-`.env` integration command,
`PYTHON_DOTENV_DISABLED=1 ./scripts/test-integration.sh tests/integration/core/judgments/test_observability.py`, passed
five tests, including two evaluations in one interactive run: four distinct attempts, two verb invocations, unchanged
environment and retained parent/root ancestry. The harness warned about missing `GEMINI_API_KEY`; these five tests use
an injected transport and passed without it. A2 child-run creation and cache behavior remain pending.

The explicit-identity change was originally committed as `e0d02ed4`; full `make pre-commit` passed before committing.
Consent helpers now bind the existing bundle-config acknowledgment to the session instance and settings without a
manifest schema bump. The raw override guards cover parent objects, bundle/config writes, wildcard expansion, effective
activation and resets that would uncover old intent. Disabling through raw overrides revokes both grant layers. These
are preparatory guards; the validating activation command, rule registry and dispatch remain unimplemented.

The consent foundation was originally committed as `1a029213`. The independent Claude permission fix began at `a281be33`
and later merged through [PR #269](https://github.com/hapa1i/multi-forge/pull/269) as `e9c144eb`. On 2026-10-15 the user
selected broader wrappers and chose to skip paid native testing. Human labels and quality gates remain open; neither the
A2 draft nor the merged permission fix establishes native delivery.

The focused consent/override/CLI tests and inheritance/direct-command regressions passed 165 tests. Docker integration
passed all six derivation paths (same-directory fork, new worktree, existing worktree, native resume, transfer resume
and relaunch), plus four policy CLI contract tests. The first integration run exposed a missing project-enrollment step
in the existing-worktree fixture; a later run caught an import cycle introduced while moving a consent import. Both were
fixed, and the final ten-test run passed. Rewind-specific orchestration and native delivery remain open acceptance
items.

Aggregate checks for this consent foundation passed: `make test-unit` (10,947 passed, 117 integration tests deselected),
`make test-regression` (1,855 passed), and the existing policy hook integrations (28 passed). Combined with the five
judgment-observability and ten lifecycle/CLI integrations above, 43 selected integration tests passed with no live
inference. These results do not satisfy the remaining rule-quality or native-delivery gates.

2026-10-15: the user selected broader wrappers and declined the paid Claude native trial. The revised evidence contract
separates compatibility retention from required boundary behavior, admits module/method/callback/alias candidates, and
requires attributed surface/exception facts. No local-helper-only restriction or safe-deletion claim remains.

The offline preparation harness validates 14 constructed cases in nine source families (nine calibration, five
held-out), all unadjudicated. It keeps labels outside model state, rejects split leakage and stale rule/evidence
annotations, preserves complete supplied inputs or rejects oversized requests, and has no live mode.
`uv run pytest tests/src/scripts/test_jev_rule_pack_eval.py tests/src/scripts/test_jev_probe.py -q` passed 32 tests. The
[preparation report](evidence/wrapper-preparation.json) records request hashes and sizes with zero dispatches and
quality acceptance false. Host-owned fact resolution, human labels, numeric gates, prediction/metric evaluation and hook
wiring remain unimplemented.

Full `make pre-commit`, the reproducible offline preparation report and `git diff --check` pass for this update. No
runtime policy code changed in this update; the aggregate and integration results above apply to the foundations.

2026-10-15 rebase: all six A2 commits rebased without conflicts onto `main` at `18b5670e`, including the merged Claude
permission fix and its closeout. The A2 diff under `src/`, `tests/` and `scripts/` is byte-for-byte unchanged from the
previous PR head, `f5d57f1d`. The focused consent, override, judgment, feedback and probe suites passed 318 tests. The
no-`.env` integration rerun passed all 43 selected judgment-observability, session-derivation, policy CLI and
policy-hook tests, using injected responses and fixture runtimes. Full `make pre-commit` passed, and the offline
preparation report reproduced exactly. The follow-up reconciles prerequisite links and status; no paid/native test ran,
and quality and native-delivery gates remain open.

2026-10-15 review corrections: all policy disable entry points now revoke both acknowledgment layers, including repeated
raw disable. Terminal disable also removes a conflicting enabled override. Raw set/reset still cannot activate Jev;
refusals now name the working disable-then-reset recovery. The consent record's trusted-writer boundary is documented.

The revised corpus has 17 constructed, unadjudicated cases across seven source families: 12 calibration and five
held-out. Related module/multi-file variants share their calibration family. Required callback and validation adapters
carry supplied consumer contracts, alongside redundant-validation and return-shape counterexamples. Reviewer scope notes
no longer enter model input. The applicability table resolves four cases on the host and prepares 13 model inputs; these
counts are preparation coverage, not a quality result. Annotation identity retains semantic criteria and evidence while
instruction wording has a separate prompt hash. Per-question human answers are supported but remain unset.

Validation: the 300 focused consent/override tests and 38 harness/leakage tests passed. The selected Docker suites
covered 46 distinct tests with injected responses and fixture runtimes. The initial run passed 44 and exposed two
recovery-test assertions that compared Rich-wrapped command text literally; after comparing and executing parsed argv,
all three disable/recovery cases passed the targeted rerun. No runtime correction was needed for those two assertions.
The runner reported the expected missing-Gemini-key warning; these tests make no paid inference requests.

The integrated review corrections passed `make test-unit` (11,001 passed; 117 integration tests deselected) and
`make test-regression` (1,889 passed). Full `make pre-commit`, `git diff --check` and both file/diff forms of
`forge policy check --bundle coding_standards` passed. The offline preparation report reproduces byte-for-byte. The
telemetry document's required provider token-count cache was refreshed; no paid model evaluation or native trial ran.

## Planning verification

2026-10-14 initial activation: `make pre-commit-md`, the Markdown link audit for 677 sources and `git diff --check`
passed at `de7009d7`. The review revision verified inheritance/override behavior, shared deadlines, feedback ownership,
run accounting and loader paths against that head. Marker/delegation history searches are candidate discovery, not
human-adjudicated counts of semantic violations. A2 is not the first OpenRouter action-data consumer: the existing plan
checker already sends supplied action evidence. The new acknowledgment must disclose that data flow explicitly.

Review revision, 2026-10-14: `make pre-commit-md`, the Markdown link audit for 678 sources and `git diff --check`
passed. No implementation, human-label adjudication, native trial or paid Jev evaluation is claimed by this planning
checkpoint.
