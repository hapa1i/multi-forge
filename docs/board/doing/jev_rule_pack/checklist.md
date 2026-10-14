# A2: Jev rule pack execution checklist

## Current focus

Planning only. A2 is active on `codex/jev-rule-pack`, based on `main` at `f7ce7a9a45f2e208d0fd72c74454750f4fd30e1f`
after A1's closeout on 2026-10-14. No A2 implementation or paid evaluation has run. The [card](card.md) owns scope; the
[epic checklist](../epic_jev_support/checklist.md) owns sequencing. A3 remains proposed and will use a separate
execution branch.

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

## Slice 1: reviewed rules and offline evaluation contract

- [ ] Establish `src/forge/policy/rule_pack/` as the proposed home for pack definitions, evidence preparation and the
  warning policy. Use `jev_rule_pack` as the explicit bundle name. Keep pack semantics separate from the transport and
  from the plan supervisor; no general rule-authoring framework or new vendor SDK.
- [ ] Start with one reviewed semantic rule for compatibility wrappers, expanding only if the same evidence contract
  supports another rule. Give each rule a stable ID, version, authoritative source, intent, applicability, required
  context, atomic question and complete Noul true/false criteria. Version the pack and decision rule separately.
- [ ] Bind the candidate to [coding standards §5](../../../developer/coding_standards.md#5-interface-changes), including
  justified exceptions and surface distinctions. A missing marker comment is not itself a violation. Define positive,
  compliant and insufficient-context examples before coding; exclude rules whose required facts the hook cannot supply.
- [ ] Define the consumer outcomes: not applicable, evaluated without a warning, warning, uncertain and unavailable.
  Only a covered, valid answer can support an assessed outcome. Give uncertainty and unavailable evidence visible fixed
  diagnostics without inventing a violation, model justification, denial or review request.
- [ ] Build a local corpus manifest from candidate historical changes, with source revisions, reconstructed action
  context, rule versions and labels supplied by human adjudication. Include compliant wrappers, justified exceptions,
  missing context, injected instructions, multilingual comments and changes the deterministic baseline misses.
- [ ] Split calibration and held-out examples by originating change before tuning; keep sibling hunks and repeated
  variants together. Record disagreements and exclusions. Merged history and another model's verdict are not labels.
- [ ] Declare minimum sample counts, per-rule false-positive/miss limits, coverage floor and pack-wide warning-rate
  ceiling before looking at held-out results. Choose thresholds on calibration data, not a transferred probability of
  0.8. Record uncertainty intervals and the response to a failed gate: revise/re-evaluate, narrow scope or stop
  shipping.
- [ ] Add a dry-run/fixture-first evaluation harness under `scripts/experiments/jev/`, with tests flat in
  `tests/src/scripts/` using `tests.fixtures.codex_probe.load_script`. Store corpus methodology, manifests, labels and
  eventual sanitized results under this card's `evidence/`; keep fake transports in tests/the harness.

**Decision gate:** review the initial rule and required context before wiring it into hooks. Numeric quality gates and
human labels are still outstanding; record them in `evidence/evaluation-plan.md` before live evaluation. Offline work
may proceed with clearly provisional examples. The A1 captures are transport fixtures, not A2 quality evidence.

## Slice 2: complete action evidence and bounded dispatch

- [ ] Add a small action-scoped preparation seam shared by hooks and the explicit CLI check. Collect the whole native
  action before legacy presentation truncation, while retaining deterministic per-file evaluation and test-first order.
  A prepared result maps each question back to its rule and file; per-file policy calls do not dispatch again.
- [ ] Represent full action identity, evaluated evidence identity, file/path attribution and completeness separately.
  For Claude, preserve Write content and Edit old/new text plus replacement semantics. For Codex/CLI patches, retain
  file boundaries, rename metadata and the relevant hunks. Never treat a truncated prefix or a fingerprint as coverage.
- [ ] Admit only the rule's declared evidence scope. Missing context, unsupported/binary/combined patches, unsafe paths,
  ambiguity and oversized actions produce explicit unavailable coverage. Record deletions and other non-applicable
  operations as such; do not count them as reviewed. Do not read arbitrary repository files to fill gaps implicitly.
- [ ] Batch all applicable file/rule questions over one bounded state. The first implementation permits at most one
  physical Jev request per native action, `max_attempts=1`, with no automatic splitting. If the complete eligible batch
  exceeds A1 admission, send nothing and identify the uncovered action; no silent subset of files or rules.
- [ ] Set and document a positive consumer timeout and upper bound before implementation, allowing hook preparation,
  persistence and any independently configured supervisor to finish within the registered hook timeout. Start one
  monotonic action deadline before preparation; enforce the remaining allowance through credentials and dispatch. No
  budget restarts per file, per rule or on a cache miss. Insufficient remaining time means no request.
- [ ] Bridge the synchronous entry point to A1's async client once per action. Keep loop ownership explicit, propagate
  cancellation and release resources; do not wrap A1 in the text-completion interface or introduce nested event loops.
  Exercise deadline exhaustion before dispatch and during I/O through injected clock/transport fixtures.
- [ ] Treat state text as data. Fixed rule instructions and immutable IDs cannot be replaced by comments, filenames or
  content in the action. Validate exact question coverage and file/rule mapping before composing any warning.
- [ ] Convert A1 errors and unexpected consumer evaluation failures into bounded unavailable diagnostics even under
  engine `fail_mode=closed`. Preserve any independently valid attempt accounting. Keep cancellation distinct from a
  clean assessment; a missing response or malformed answer cannot populate the clean-result cache.

**Admission gate:** fixtures must prove whole-action coverage and the physical request limit before any hook inference.
The exact timeout is a consumer choice, not an A1 latency guarantee. If coexistence cannot fit the existing hook budget,
skip A2 visibly for that action rather than extending the hook or changing the independent reviewer contract.

## Slice 3: activation, cache and audit

- [ ] Generalize bundle registration at `policy/registry.py` if needed, delegating existing deterministic bundles to
  their current implementations. Update engine construction, CLI list/choices and `core/ops/policy.py` together.
  Validate all bundle names, config owners, pack versions and field types before registering anything; reject unknown
  settings.
- [ ] Persist opt-in through session policy intent and the existing terminal/direct activation owner. Ordinary sessions,
  existing `coding_standards`, supervisor setup, list/status and imports remain zero-inference paths. Explicit
  `forge policy check --bundle jev_rule_pack` must clearly disclose its paid behavior and use the same bounded runner.
- [ ] Define the finite supported config fields and defaults, including model/pack version, timeout and cache TTL;
  reject invalid values atomically. Keep evaluated thresholds in the versioned decision rule. Preserve the shared
  activation contract for the explicitly supplied bundle set and unrelated intent; never enable it across sessions.
- [ ] Use the existing credential chain with environment/file precedence and `auth_ignore_env`; verify missing auth and
  no-`.env` behavior offline. Every physical attempt retains mandatory ZDR. Disabled/not-applicable/local-refusal paths
  make no network request; no direct TypeSafe or subscription fallback.
- [ ] Key cached validated results by session, canonical full action, exact evidence/coverage, pack/rule/question
  versions, endpoint/requested model and decision-rule version. Retain resolved model identity and declare how model
  drift expires reuse. Bound TTL/entries and invalidate stale/malformed entries without losing independent policy state.
- [ ] Cache reuse must reproduce the attributed outcome without a new provider attempt or charge. Do not cache
  unavailable/partial results as clean; observed answer variance prevents claiming fresh inference is deterministic.
  Preserve Codex's existing rule that a denied atomic patch does not advance policy state.
- [ ] Add the bounded rule-evaluation record missing from today's decision serializer: raw typed answer/distribution,
  requested/resolved model, rule/source version, action/evidence identity, assessed excerpt, coverage, outcome and
  attempt IDs. Preserve old audit readability and make local evidence inspectable through session show. A source
  citation is separate from proof of a violation; do not fabricate supervisor `VerifiedCitation` objects.
- [ ] Link attempt/run identity to existing hook/session telemetry and identify this consumer through A1's command
  field. Keep known/unknown cost, cached assessments, actual attempts and independent reviewer calls distinct. Reuse
  existing telemetry schemas; no raw source text in usage records and no parallel billing ledger.
- [ ] Run the focused policy/CLI and telemetry integration checks during this slice. Confirm trace show/explain, costs
  by model/verb and session activity agree on injected attempts, with no synthetic proxy traffic or double charge.

## Slice 4: warnings the model and operator can inspect

- [ ] Produce structured `warning_findings` with stable rule/path attribution and legacy warning strings; keep
  `violations` for denials. Fixed rule text may use `provenance=policy`; action excerpts remain attributed input data.
  Do not turn a Jev probability into a verified quotation, free-form explanation or ground-truth assertion.
- [ ] Extend Claude's formatter so `policy_summary_feedback=on` includes bounded rule text/intent, source and assessed
  action evidence in `additionalContext`. Define its output bound and omission notices. Remove explicit allow from this
  warning path so feedback cannot override the runtime's normal permission handling.
- [ ] Feed the existing B3 Codex renderer, retaining its audience budgets, provenance rules, source-only preference and
  executor admission. Keep inspection commands in operator output under source-only; never introduce a new explicit
  `permissionDecision=allow`. Count omissions rather than silently dropping findings.
- [ ] With feedback off, suppress allowed-action model context while retaining substantive operator diagnostics and
  audit. Unknown/unsupported Codex executors retain B3's existing channel restrictions. Clean A2 results add no warning;
  unavailable assessments cannot be labeled aligned. Do not change unrelated supervisor summaries.
- [ ] Exercise warning-only and unavailable outcomes with no supervisor, a regular supervisor and a cascade resolver. A2
  creates no resolver request or extra supervisor call; independently configured checks still run. Existing denials
  retain priority, blocking reasons and TDD state behavior with either feedback setting.
- [ ] Add injected-client hook integrations for both runtimes, then verify native delivery using a separate bounded
  trial plan. Model receipt of the substantive rule/evidence must be observed; stderr or an operator `Hook` notice alone
  is insufficient. Preserve the distinction between native-runtime quota and Jev API cost in the run record.

## Slice 5: authorized quality evaluation and release decision

- [ ] Prepare the exact evaluation manifest after offline checks pass: approved corpus selection/sanitization, payload
  hashes, versions, calibration/held-out split, repetitions, timeout, maximum physical requests and dated price
  assumptions. Include all controls and retries in the bound; the proposed first pass disables retries.
- [ ] Obtain explicit data-sharing and paid-run authorization for that manifest. A1's four-request and 25-request
  approvals are exhausted and do not authorize repository data. Use an isolated `FORGE_HOME`, clear cached runtime
  configuration and copy no user telemetry/session history into it.
- [ ] Run the authorized cases with ZDR, a physical request cap and a reported-cost stop check. Missing cost remains
  unknown; estimated spend and a post-response check are not a guaranteed invoice cap. Persist interrupted/failed
  attempts and stop rather than silently repeating them under the same allowance.
- [ ] Report per-rule confusion counts, false-positive/miss rates, calibration, coverage/uncertainty, aggregate warning
  frequency, sample counts, latency and reported cost against the deterministic baseline on the same corpus. Separate
  tune/held-out results and repeated-input variability; do not tune against the held-out set and still call it held out.
- [ ] Apply the predeclared quality gates. Publish a supported-rule/context matrix and failures in `evidence/`; remove
  or narrow rules that fail, with a fresh evaluation when needed. Offline transport/formatter tests alone cannot close
  this acceptance gate. A later opted-in warning trial remains separately authorized and cannot imply quota savings.

## Acceptance fixtures

Paths under `tests/src/policy/rule_pack/` and the A2 harness/integration test names below are planned additions.

| Test               | Fixture                                      | Assertion                                          | Test file                                                                             |
| ------------------ | -------------------------------------------- | -------------------------------------------------- | ------------------------------------------------------------------------------------- |
| Atomic activation  | Unknown pack/field; invalid timeout          | No partial engine or intent write                  | `tests/src/core/ops/test_policy_ops.py`; `tests/src/policy/test_engine.py`            |
| Rule semantics     | Wrapper, exception, missing context          | Versioned applicability; explicit coverage         | `tests/src/policy/rule_pack/test_definitions.py`                                      |
| Evidence integrity | Long Edit; rename; multi-file patch          | Full identity and declared evaluated scope         | `tests/src/policy/rule_pack/test_evidence.py`                                         |
| Batch limit        | Several files/rules; oversized batch         | One request, or zero with unavailable result       | `tests/src/policy/rule_pack/test_runner.py`                                           |
| Deadline/failure   | Expired clock; 402/413/524; malformed answer | No retry or Jev block; retained attempt usage      | `tests/src/policy/rule_pack/test_runner.py`                                           |
| Injection          | Instructions in content/path/comment         | Fixed questions and attribution preserved          | `tests/src/policy/rule_pack/test_evidence.py`                                         |
| Composition        | Warning/error plus TDD deny or supervisor    | Denial preserved; no A2 escalation                 | `tests/src/policy/test_engine.py`; `tests/src/cli/hooks/test_policy_check_cascade.py` |
| Cache/audit        | Same action; changed rule/model/hidden tail  | Correct reuse/invalidation; inspectable evidence   | `tests/src/policy/rule_pack/test_policy.py`                                           |
| Auth/defaults      | No key; disabled pack; environment/file keys | Actionable unavailable result; no incidental calls | `tests/src/policy/rule_pack/test_runner.py`                                           |
| Claude feedback    | Finding/unavailable; feedback on/off         | Bounded content or operator/audit only             | `tests/src/cli/hooks/test_policy_feedback.py`                                         |
| Codex feedback     | Multi-file; source-only; unadmitted executor | B3 bounds and permissions preserved                | `tests/src/cli/hooks/test_codex_policy_feedback.py`                                   |
| CLI parity         | File/diff; terminal/direct activation        | Same pack vocabulary and content-source rules      | `tests/integration/cli/test_policy_cli_contract_integration.py`                       |
| Hook accounting    | Injected success/cache/failure in a session  | One attempt joins trace/cost/activity              | `tests/integration/core/test_jev_rule_pack.py`                                        |
| Evaluation         | Labeled/split corpus; bounded manifest       | Reproducible metrics; dry-run makes no calls       | `tests/src/scripts/test_jev_rule_pack_eval.py`                                        |

## Verification and documentation

- [ ] Run `make deps` before targeted unit work, then focused rule-pack, engine, action-identity, adapter, feedback,
  shared activation and CLI tests. Add a regression for each discovered bug; ordinary tests use injected transports.
- [ ] Run relevant hook and CLI integrations through `./scripts/test-integration.sh`, including
  `tests/integration/docker/test_policy_hooks.py`, `tests/integration/cli/test_policy_cli_contract_integration.py` and
  the new injected-client accounting integration. Use `PYTHON_DOTENV_DISABLED=1` for the no-`.env` checks. Do not
  accidentally launch credential-backed native tests as ordinary fixture tests.
- [ ] Verify the authorized native Claude/Codex warning paths with feedback on/off, supported executor enrollment and
  the evidence-inspection commands. Record runtime versions, exact request/quota limits and observed delivery. Reuse
  B3's probe conventions without assuming its TDD/stub evidence proves A2's formatter output.
- [ ] Check `forge policy list`, `status`, `check --bundle coding_standards --file <path>` and
  `git diff | forge policy check --bundle coding_standards --diff`, plus fixture-backed Jev equivalents. Read outputs
  stay on stdout, diagnostics on stderr; keep `tests/src/cli/test_output_streams.py` coverage for changed read surfaces.
- [ ] Sync `docs/design_workflows.md` for the first-class rule pack, action preparation, composition and state
  ownership; `docs/design_session_execution.md` for hook delivery/budgets; and runtime/telemetry design for consumer
  admission and audit links. Update `docs/design.md` if registry/operation ownership changes.
- [ ] Update `docs/end-user/policy.md`, `docs/end-user/config.md`, `docs/end-user/authentication.md`,
  `docs/cli_reference.md` and runtime-config help with explicit paid opt-in, model/pack support, timeout/cache behavior,
  unavailable diagnostics, feedback settings and inspection. Update installation guidance if credentials/resources or
  extension delivery changes. Normative docs describe only implemented behavior.
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
- [ ] Open the A2 PR with concise scope, limitations and actual validation. After review/merge, record the merged head,
  finish design/end-user sync, add the completed-work change-log entry and propose durable notes for human review.
- [ ] Move A2 to `done/` only when its acceptance gates are satisfied and the code is merged; repoint inbound links and
  update the epic's next-member decision.

## Planning verification

2026-10-14: `make pre-commit-md`, the Markdown link audit for 677 sources and `git diff --check` passed with the
activation links and checklist staged. No implementation, human-label adjudication, native trial or paid Jev evaluation
is claimed by this planning checkpoint.
