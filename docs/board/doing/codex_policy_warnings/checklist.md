# Codex policy warnings checklist

Card: [card.md](card.md). Epic: [Codex supervisor](../epic_codex_supervisor/card.md), member **B3**.

## Current focus

Selected 2026-10-10 on `feat/codex-policy-warnings`, based on clean local `main` at `d54dba63` (B2 closeout above merged
PR #261, `2a15c087`). B2 closeout `d54dba63` was published to `origin/main` on 2026-10-10. Implementation, live
evidence, and aggregate checks are complete, including PR #262 review corrections. See [results](evidence/README.md) and
[validation](evidence/validation.md). B1 and B2 are done. B4, B5, and the Jev cards remain proposed.

Deliver bounded, attributed policy warnings to the Codex model after allowed patches, with an independent operator
warning channel. The user selected the source-only opt-in: Forge injects verified plan passages and fixed diagnostics
while retaining reviewer-generated wording in durable evidence. This controls hook output; it does not prevent the
executor from reading that evidence. Preserve verdicts, catch-all artifact authority, hook deadlines, and atomic
patch-state persistence.

### Verified starting point (before implementation)

- B2's [feedback evidence](../../done/codex_0160_validation/evidence/feedback.json) and
  [results](../../done/codex_0160_validation/evidence/README.md) observed bare PreToolUse `additionalContext` as a
  developer-role `hooks.additional_context` message on Codex 0.161.0. The explicit-allow arm did not deliver its nonce.
  `systemMessage` appeared as a TUI Hook notice; exit-zero stderr was not observed in model or UI surfaces.
- The [publication audit](../../done/codex_0160_validation/evidence/validation.md#harness-and-publication-provenance)
  records harness drift and missing historical hook stdout/exit status. Offline replay does not prove that historical
  process outcome. B3 must capture the final product handler's stdout, stderr, exit status, rollout, and action result.
- `CodexHookResponder.allow_feedback()` still includes explicit `permissionDecision: "allow"`; the command never calls
  it. `codex_policy_check()` emits path-attributed warnings only on stderr. Its per-file results already support
  aggregation; flattening `all_warnings` alone loses rule, intent, and violation evidence.
- `DeterministicPolicy._warn()` and permissive TDD discard available intent/violation detail. Supervisor
  `verdict_to_decision()` drops citations when reducing a divergent finding to a warning string. Warnings also carry
  operational diagnostics; `fail_open`/`failure_type` identify many, but not all, such outcomes. Normal applicability
  checks filter unconfigured supervision before evaluation.
- B1's `PlanSnapshot` holds the reviewed text and digest. Existing citation parsing checks shape, not whether a quote
  occurs in that snapshot. Only clean allows are cached; tier-1 `PlanCheckPolicy` emits allow/needs-review, with reasons
  in low-severity violations rather than warnings. Neither is a source of verified reviewer quotations.
- `policy_summary_feedback` currently gates Codex's stderr summary and Claude's injected count summary. Extending it to
  substantive Codex context changes its documented meaning; current stderr warnings are not a measured operator channel.

## 0. Activation

- [x] Create the separate execution branch from `d54dba63`; move B3 from `proposed/` to `doing/` with `git mv`.
- [x] Add this checklist; update the epic's active member, B1/B2 prerequisites, and inbound B1/Jev links.
- [x] Record the user's choice to include source-only mode. Keep B4/B5, Jev inference, and native-fork review outside
  this card's implementation scope.
- [x] Validate this planning change with Markdown, size, repository-link, and staged/working-tree diff checks.
- [x] Publish the existing B2 closeout separately: remote `main` fast-forwarded from `2a15c087` to `d54dba63` on
  2026-10-10; B3 remains on its execution branch.

## 1. Pin the delivery and compatibility contract

- [x] On a supported executor, serialize one JSON object for an allowed action with feedback. The measured model
  candidate is `{"hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":"..."}}`; omit explicit
  `permissionDecision: "allow"`. Put operator `systemMessage` at its measured top-level location. Verify the combined
  shape, operator-only shape, and model-only control independently; B2 tested the channels separately.
- [x] Implement the audience matrix below, using producer/status metadata rather than string matching. Clean allow stays
  silent on stdout. Summary-off omits allowed-action `additionalContext`, retaining substantive operator warnings and
  durable records. Deny and unresolved review keep their blocking wire and precedence regardless of this toggle.
  Unmanaged, irrelevant-event, non-patch, malformed-input, and disabled-policy paths remain silent after the existing
  authority guard runs.
- [x] Separate delivery admission from the general validated ceiling and blocking QA pin. Use 0.161.0 as the minimum
  measured candidate. Older, unknown/unparseable, or invalid launch identity suppresses new model feedback; operator
  output requires independently supported channel behavior. Admit a newer-than-validated version only after a fresh
  delivery control, recording the feature's tested versions without moving the QA pin or general ceiling. Historical
  fail-open parsing is insufficient admission evidence. Record `emitted`, not `delivered`, unless delivery was observed;
  preserve verdicts and existing preflight readiness/re-probe semantics.
- [x] Pass secret-free executor identity in the child environment on every headless/TUI start and resume, tied to the
  resolved executable actually launched. Refresh facts at each launch and test replacement/invalidation before launch;
  an already-running process keeps its launch identity. Ignore inherited stale identity. Neither reviewer readiness nor
  rollout `session_meta.cli_version` identifies the current resumed executor. Do not parse account-bearing metadata or
  run a version/doctor subprocess or model call on each policy action.
- [x] Add global `RuntimeConfig.codex_policy_feedback_format` with values `normal` (default) and `source-only`, exposed
  through `forge config show --json` and `forge config set`. The name/help must explicitly scope it to Codex. It has no
  session override or consumer-lane ownership; Claude ignores this global preference and retains its existing output. Do
  not add an unsupported Claude session opt-in.
- [x] Retain `policy_summary_feedback`: document that B3 extends its Codex meaning to substantive allowed-action model
  feedback. `off` always omits that context; the format setting cannot override it. Preserve substantive operator
  warnings and audit records. Document Claude's existing summary behavior until Jev A2 extends that formatter.

| Outcome/source                           | Allowed-action model context    | Operator channel           | Durable evidence           |
| ---------------------------------------- | ------------------------------- | -------------------------- | -------------------------- |
| Substantive policy finding               | Bounded finding when on         | Attributed warning         | Full finding               |
| Review unavailable/timeout/quota/error   | Fixed unreviewed status when on | Actionable diagnostic      | Status and failure type    |
| Expected depth skip or unconfigured call | None                            | None                       | Outcome if evaluated       |
| Resolved tier-1 cascade reason           | None                            | None                       | Tier-1 reason              |
| Evidence persistence failure             | None                            | Verdict-preserving notice  | Best effort only           |
| Raw exception/provider error text        | None                            | Sanitized fixed diagnostic | Diagnostic detail if saved |

The unavailable row includes configuration/auth/parse failures. Source-only rendering always selects fixed diagnostics
from structural status, never raw exception or warning prose. The normal unconfigured path is filtered before
evaluation; the table also covers defensive direct calls. Blocking output is handled separately and always preserves the
verdict.

## 2. Collect and render feedback without changing policy decisions

- [x] Collect findings from every evaluated file and its individual decisions. Preserve file path, policy/rule ID,
  severity when present, policy intent, violation message, evidence, citations, and suggested fix where supplied. Keep
  plain warning strings attributable to their owning policy and apply the audience matrix before rendering. Enrich
  `_warn()`, permissive TDD, and supervisor `verdict_to_decision()` so non-blocking findings retain available structured
  evidence/citations. Citation-free warnings remain valid warnings; they cannot yield verified plan text.
- [x] Pin compatibility while enriching producers: preserve decision thresholds, `_policy_reason_code` and violation
  count semantics, and the manual `forge policy check --json` contract in which `violations` lists denials only. Test
  any new warning fields explicitly. Structured warning findings must not accidentally become blocking violations or
  expose a resolved tier-1 reason. Keep original evidence in storage; no formatter reconstructs missing evidence.
- [x] Deduplicate by attributed finding, with deterministic file/rule order. Equal text on different paths/rules remains
  distinguishable. A clean first file must not hide a later warning. Keep formatter logic separate from evaluation and
  stdout emission; no new reviewer call may be needed to format existing results. B3 accepts bounded feedback on each
  evaluated action, including repeated findings; deduplication is within one response, with no session suppression
  state.
- [x] Set named per-field, per-finding, finding-count, and total serialized-byte limits, then pin them in tests. Bound
  `additionalContext` and `systemMessage` independently, account for JSON escaping/Unicode, and reserve space for an
  omitted/truncated count. Reserve an inspection command in operator output; in source-only mode no model-visible field
  directs the executor to reviewer evidence. Do not truncate serialized JSON or misattribute omitted files.
- [x] Label policy evidence as quoted data with path/rule attribution. Arbitrary code, citations, and reviewer text must
  not become unlabeled Forge instructions. In normal mode retain substantive feedback; in source-only mode apply section
  3 before any model-visible serialization. Test quotations containing instructions and delimiter escapes. Attribution
  and escaping are output controls, not evidence of prompt-injection immunity in developer-role context.
- [x] Emit one stdout response after cross-file composition. Preserve `deny > needs_review > warn/allow`, exit codes,
  authority-first evaluation, tests-first ordering, and the no-matcher 60-second registration. Keep diagnostics on
  stderr; neither formatting nor evidence-write failure may replace a computed denial with an allow. A denied response
  contains the blocking files/findings; other files' warnings remain in audit evidence. Unresolved review likewise
  reports its unresolved files without adding unrelated warnings.
- [x] Preserve one decision-log entry per evaluated file and aggregated state in one manifest update. Blocked patches
  persist audit entries but no optimistic file state. Formatting, deduplication, truncation, and summary-off must not
  mutate stored decisions, discard review evidence, or record a synthetic successful review. Intentional producer/schema
  enrichment above is allowed and tested separately from renderer purity.
- [x] Render fail-open/unavailable review outcomes as unreviewed or unavailable using structural status. Include the
  fixed failure diagnostic selected from structural status without labelling the patch aligned; preserve status/activity
  visibility. Record raw details through diagnostics/evidence. Keep existing engine-build, evaluation-error,
  unresolved-review, and configured fail-mode behavior. Cover partial and all-file evaluation errors.

## 3. Implement the source-only opt-in

- [x] Validate inside the supervisor while the exact reviewed `PlanSnapshot` is still available, before conversion
  discards citation structure. Store Forge-verified passages/spans with source/digest attribution on structured
  findings; the formatter selects only those verified fields. Do not retain a mutable shared source or reread its path
  after review, and do not trust reviewer-provided filenames/hashes. Resumed-conversation sources without a verifiable
  snapshot use fixed diagnostics.
- [x] Validate nonempty quoted passages against that snapshot before inclusion, retaining source/digest attribution.
  Define allowed normalization narrowly and test it. Reject invented text and wrong-snapshot matches; citation labels or
  file paths alone do not verify a quotation. Require verbatim plan quotations in the reviewer prompt.
  Missing/unreadable source and missing/invalid quotes never authorize a prose fallback or change the existing block
  threshold.
- [x] Keep cache/cascade tests focused: cached clean allows carry no reviewer quotations; cached evidence-write failures
  still obey the audience matrix. Tier-1 reasons never leak after a resolved escalation. A frontier review reached
  through the cascade uses the same action snapshot; unresolved review uses the source-only fallback. Verify plan
  changes invalidate caches without inventing a warning-quotation cache path.
- [x] Exclude reviewer-generated explanation, evidence prose, suggested fixes, and free-form warnings from every Codex
  model-visible warning and block field in this mode. Use verified source passages plus fixed Forge diagnostics;
  deterministic rule intent/evidence remains attributed according to its provenance. Apply the choice to deny and
  unresolved-review text as well as allowed warnings, independently of the summary toggle. Verdicts remain unchanged.
- [x] Make a missing-quote deny actionable with fixed policy/path attribution: explain that the action remains blocked,
  no verified plan quotation is available, and the executor must stop and ask the operator before retrying. Keep the
  inspection command in `systemMessage` only. Apply equivalent fixed guidance to unresolved review without inventing a
  reviewer rationale.
- [x] Keep full original findings and review evidence available through existing inspection surfaces. Formatting is a
  presentation choice: workspace manifests remain executor-readable. Claim only exclusion from Forge's model-visible
  hook fields, with absence from a particular rollout conditional on checking other reads. Make no watermark or access
  isolation claim. Bound and deduplicate verified passages through the ordinary renderer contract.
- [x] Verify option validation, default behavior, persistence/reload, config show/set output, and unchanged Claude
  behavior when the global Codex preference is set. Test reading old stored decisions with absent provenance; they
  authorize no verified quotation. Add compatibility tests for enriched finding storage without changing shared
  consumer-lane formats.

## 4. Establish fresh product evidence

### Fixture and quota gates

- [x] At execution start, resolve and retain the complete installed Codex package; record path, SHA-256, version,
  model/effort, OS, Forge revision, and relevant source hashes. Use that copy throughout; a binary update starts a
  separately identified capture set. B2's dated 0.161.0 evidence is the baseline, not proof about a future installation.
- [x] Use an independent login and private homes with a clean launcher that strips API credentials and disables dotenv.
  Never copy host `auth.json`. Set `FORGE_DEV` in every terminal, assert the doctor's effective dispatcher override, and
  record the actual hook launcher/module paths. Keep login state through all stages; reset baseline config only before
  enrollment or with an explicit invalidation and fresh ceremony.
- [x] Record `forge runtime preflight codex --json`, doctor auth/billing facts, current hook registration, and the
  `--verify-enrollment` observation receipt. Use real user-scope enrollment without a hook-trust bypass. Capture host
  config hashes before/after if claiming byte equality; file equality does not establish refresh-token validity.
- [x] Give T11 a dedicated fixture that captures explicitly supplied independent `HOME`, `CODEX_HOME`, and `FORGE_HOME`
  before autouse isolation, then restores them together with the retained binary path and `FORGE_DEV`. Require fixture
  ownership/enrollment markers, subscription auth, and budget accounting; fail without these inputs, with no host-home
  fallback. Do not rewrite hook registrations or trust state during tests. Existing core subscription smokes do not
  exercise hook delivery; the Docker enrollment helper does, but requires API auth and is unsuitable for this round. An
  optional project-hook trust-bypass test is delivery-only evidence and cannot satisfy T11's trusted control.
- [x] Record the execution budget before live calls. Proposed cap: **32 reserved Codex turns**: 4 enrollment/checks, 8
  headless controls, 4 source-only controls, 4 TUI controls, 4 wheel/start/resume checks, and 8 failed-attempt/retry
  reserves. Reserve every attempt, including extra enrollment on each advisory launch/resume, against the same cap;
  rebalance before a group or obtain a budget extension before exceeding it. Use deterministic findings and an
  admission-compatible local Claude stub for repeatable controls.
- [x] Reserve **one real Claude reviewer attempt**, separately from the Codex cap, to assess whether the final verbatim
  quote prompt produces a usable verified citation for a controlled divergence. Use only `--auth-mode subscription-only`
  after admission/auth checks, with account usage credits disabled and no paid fallback. Record quota reservation,
  route, prompt, raw citations, and validation result; retries need a revised budget. Stub results alone do not
  establish real quotation quality. If this attempt cannot run or yields no usable quote, record the limitation and
  settle the usability gate explicitly before closeout. No paid API inference or Jev call is allowed in the round.
- [x] Use bounded outer execution and descendant cleanup: TERM, then KILL, then a fixture-owned process sweep covering
  detached groups. Preserve completed and failed captures separately. A failed model turn is not negative delivery
  evidence. Commit the harness/helpers used for the final captures and retain their hashes, including exporter sources;
  later edits require affected reruns or an explicit drift qualification.

### Required controls

- [x] Exercise the installed product dispatcher on permissive TDD. Its fixed warning cannot carry a private nonce: use
  the native `hooks.additional_context` message/role and landed action as primary delivery evidence, with any model echo
  secondary. Retain hook stdout/stderr/exit code, rollout, turn result, and file bytes.
- [x] Use an admitted stub supervisor's low-confidence divergent verdict to carry a hook-only nonce through the real
  producer/dispatcher. Require the native injected message and a subsequent model response showing consumption. Keep the
  nonce out of the task prompt, readable checkout, skills, and prior context; use fresh threads for negative arms.
  Permit one patch followed by an answer and inspect tool reads as in the source-only control. Test rule-pack-shaped
  findings at the formatter boundary; any live registry injection must be labelled instrumented and cannot replace
  product-path evidence.
- [x] Repeat with feedback off: the action still lands, `additionalContext` and the model-context marker are absent,
  while operator warnings and persisted decisions remain. Verify `systemMessage` independently in the interactive TUI,
  then test the combined product response. Do not claim headless event-stream visibility unless actually observed.
- [x] Run multi-file/later-warning and warning-plus-deny controls. The first aggregates all attributed warnings into one
  response; the second blocks the entire patch and leaves prior file state intact, with unrelated warnings only in audit
  evidence. Keep authority-denied non-patch and quiet unmanaged controls in unit/Docker coverage (T6); add a live
  authority rerun only if implementation changes that path, and rebalance the budget first.
- [x] Exercise source-only mode with an exact approved-plan quote and a private reviewer-prose nonce. Verify that Codex
  consumes the permitted source marker, while reviewer prose is absent from the handler's model-visible fields and the
  retained native context. Keep the source marker in the reviewer's private snapshot, outside the executor prompt,
  checkout, and prior thread context. Permit only the required `apply_patch`, then answer without additional tools;
  inspect all native tool calls/results for manifest or review-evidence reads. Such reads invalidate the hook-only
  source control, rather than proving a renderer leak. Include malformed/fabricated quotes and a changed-on-disk plan
  after the reviewer snapshot; full review evidence remains inspectable. Cover block formatting with deterministic/stub
  controls as well.
- [x] Check unavailable/timed-out reviewer feedback with an admitted stub and an actual dispatch-start marker. Verify
  allowed work is described as unreviewed, existing failure/attempt records survive, and formatter work adds no reviewer
  calls. Preserve the B1 whole-hook deadline; do not repeat B2's full lifetime experiment without a relevant change.
- [x] Verify headless start/resume and the interactive TUI path from the final implementation. Run the selected real
  Codex integration via the standard runner with the dedicated enrolled fixture; no silent auth fallback or skip may
  stand in for the required delivery proof. Record the observed binary's compatibility result separately from the
  feature's older/unknown-version unit controls.

## 5. Acceptance tests and owners

Existing files are starting owners; add focused files where that keeps responsibilities clear. Every bug regression
belongs under `tests/regression/test_bug_b3_*.py` with the regression mark. Publish coherent indexed sessions through
`tests.fixtures.session_state`. New integration test paths below are planned, not existing evidence.

| ID  | Fixture                                                                         | Required assertion                                                      | Test owner                                                                                        |
| --- | ------------------------------------------------------------------------------- | ----------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| T1  | Clean allow; warning; deny; unresolved review                                   | One valid response or documented silence; verdict precedence            | `tests/src/cli/hooks/test_codex_policy.py`, `test_codex_policy_check.py`                          |
| T2  | Later-file warnings; duplicates; repeated actions; warning plus deny            | Attribution; per-response dedup; blocking-only deny text                | New `tests/src/cli/hooks/test_codex_policy_feedback.py`; B3 regression                            |
| T3  | Large findings; instruction-bearing quotes; escapes; Unicode                    | Bounds; valid JSON; attribution; visible omissions                      | Feedback formatter tests                                                                          |
| T4  | On/off; channel combinations; substantive/operational/tier-1 findings           | Audience matrix; independent operator/audit output                      | Feedback command tests; live delivery fixture                                                     |
| T5  | Denied atomic test+implementation patch; allowed equivalent                     | Blocked patch adds no optimistic state; allowed state aggregates        | `test_codex_policy_check.py`; `tests/regression/test_bug_blocked_action_persists_policy_state.py` |
| T6  | Authority-denied Bash; unmanaged/irrelevant/disabled paths                      | Authority precedes filtering; other no-op paths quiet                   | Authority unit tests; `tests/integration/docker/test_policy_hooks.py`                             |
| T7  | Partial/all evaluation failures; unavailable review; persistence/format failure | Existing failure policy and computed denial survive; no false alignment | Command tests; B3 regressions; B1 deadline tests                                                  |
| T8  | Start/resume/TUI; older/unknown/newer version; executable replacement           | Launch identity; conservative admission; no per-action probe            | Runtime/launch tests where identity is owned; feedback tests                                      |
| T9  | Warn/deny quotes; absent/false/stale citation; cache/cascade; old records       | Verified provenance; fixed fallback; unchanged verdict and evidence     | New source-only tests; `tests/src/policy/semantic/test_b1_contracts.py`; B3 regressions           |
| T10 | Codex format default/opt-in/off; invalid value; reload; Claude executor         | Codex-only preference; summary-off wins; Claude unchanged               | `tests/src/test_runtime_config.py`, `tests/src/cli/test_config_cli.py`                            |
| T11 | Explicit enrolled homes; real Codex; TDD; stub-supervisor nonce                 | Native injected message; action lands; independent nonce consumption    | New `tests/integration/core/test_codex_policy_feedback.py`; dedicated fixture and rollout         |
| T12 | Interactive warning with model feedback off                                     | Operator sees notice; model lacks warning context                       | Scripted/manual TUI capture in B3 evidence                                                        |
| T13 | Wheel; stable enrolled dispatcher; no `FORGE_DEV`                               | Wheel imports; unchanged trust/registration; real delivery              | Clean-wheel dispatcher capture and selected integration                                           |
| T14 | Enriched warns; Claude hooks; manual file/diff checks                           | Reason/count/CLI contracts and Claude wire preserved                    | Verdict/engine tests; `test_policy_feedback.py`, `test_responder.py`; policy CLI integrations     |
| T15 | One subscription-only real reviewer; known plan divergence                      | Verbatim quote usability; raw-to-verified provenance; budget recorded   | Retained B3 reviewer capture; explicit limitation if unusable                                     |

## 6. Verification, docs, and closeout

- [x] Run focused unit and regression tests as each slice lands. Use `make` prerequisites before direct pytest reruns.
  Run affected integration paths during implementation through
  `./scripts/test-integration.sh tests/integration/docker/test_policy_hooks.py tests/integration/cli/test_policy_cli_contract_integration.py`;
  add the new real Codex feedback integration once its fixture exists. Use `PYTHON_DOTENV_DISABLED=1` and the isolated
  launcher for subscription probes; inspect Docker/provider requirements before invoking any model-backed tests.
- [x] Exercise `forge policy check --bundle coding_standards --file <fixture>` and a controlled diff piped to
  `forge policy check --bundle coding_standards --diff`. Inspect `forge policy supervisor status --json`, session policy
  records, and `forge telemetry activity <session>` for the degraded-review control. Add CLI stream tests if new public
  read/set diagnostics change their stdout/stderr contract.
- [x] Update `docs/design_workflows.md` for feedback/source-only semantics and `docs/design_session_execution.md` for
  Codex delivery/version facts. Update `src/forge/runtime_config.py` help/generated config comments and
  `docs/end-user/config.md` alongside `docs/end-user/policy.md`: name the new format preference, expanded summary
  toggle, temporary Claude/Codex difference, operator/model distinction, readable-evidence limit, enrollment, and
  compatibility. Keep source-only inspection commands operator-facing. Sync configuration/installation or subprocess
  design if ownership changes; remove stale allow-is-unprobed wording in touched code/tests.
- [x] Build and test a clean installed wheel: dispatcher provenance, warning/deny wire, source-only/off settings, and a
  trusted delivery control. Reuse the independently enrolled `FORGE_HOME`/`CODEX_HOME`; point `runtime.json` at a
  durable wheel launcher without changing the registered dispatcher command. Assert managed block/trust bytes are
  unchanged, `FORGE_DEV` is absent and ineffective, and hook imports resolve to the installed artifact, with no checkout
  import override. Record wheel/launcher hashes and restore fixture routing afterwards. A different home requires a
  fresh trust ceremony and budget reservation. Keep the general ceiling, blocking QA pin, shared validation
  revision/date, and proxy floor unchanged unless separately justified and revalidated.
- [x] Run aggregate `make test-unit`, `make test-regression`, and full `make pre-commit`; verify board links and diffs.
  Retain commands, results, skips/failures, exact tested source, runtime/artifact hashes, and sanitized captures in B3's
  evidence. Final evidence must account for any helper or product edits after its capture revision.
- [x] Before opening the B3 PR, refresh `origin/main` and verify it contains published B2 closeout `d54dba63`. Reconcile
  any divergence without force-pushing; verify the PR diff contains only B3 work. Keep B3 on its separate execution
  branch.
- [x] Record B3's warning/formatting contract and limits in the epic and Jev A2 handoff. Keep B4/B5 and Jev cards
  unactivated. Source-only must have explicit passing evidence or an explicit scope revision before B3 closes.
- [ ] After review/merge, record merge coordinates and completed work in the changelog; promote reviewed durable
  lessons. Move B3 to `done/`, repair all inbound links, and leave the epic active until its other members ship. Tear
  down only fixture-owned processes/auth after preserving evidence; record cleanup and host-state limitations
  accurately.

## Planning record

2026-10-10: inspected the B2 closeout and provenance qualifications, B1 snapshot/citation contracts, current Codex
responder and multi-file command, warning producers, state persistence, authority/dispatcher ownership, existing tests,
and normative feedback documentation. The user selected source-only mode. Local Codex reports 0.161.0 at
`/opt/homebrew/Caskroom/codex/0.161.0/bin/codex`, SHA-256
`12ac11d2c7eee27cfae34393986d7b7c9ed0dea537cb749831cdd7033893e6de`; this is a planning observation, not an execution
pin. No model turn, credential mutation, product-code change, or compatibility bump occurred.

Planning validation: `make pre-commit-md` passed after formatting, including repository size and secret checks.

The Markdown link audit passed for 648 sources; working-tree and staged `git diff --check` passed.

2026-10-10 review revision: accepted producer enrichment with telemetry/CLI compatibility checks; selected the
Codex-only global format key and explicit summary-toggle extension; specified audience filtering, launch identity,
trusted fixtures, wheel enrollment continuity, and corrected evidence oracles. Source-only limits hook emission and
retains readable full evidence. The plan reserves 32 Codex turns (including 8 retries) plus one subscription-only Claude
quote-quality attempt. B2 closeout `d54dba63` was pushed separately to `main`; product implementation and live probes
have not started.

The planning observations above are dated history. Implementation assertions below are backed by the execution record;
post-merge closeout remains pending.

## Execution record

2026-10-10: implemented feedback and source-only rendering in `2cb840ed`, followed by committed capture helpers. The
retained Codex package is 0.162.1, SHA-256 `74c6a6d263f40d65f99c27a815275f5b4ed0bcc2baecc396b4cf3255498bdfc0`; the
independent login and existing trusted dispatcher were retained throughout. The feature-specific admission set includes
this measured runtime and B2's 0.161.0; the QA ceiling, release pin, proxy floor, and shared validation date/revision
remain unchanged.

The evidence verifier passed all 16 selected product/channel/wheel controls plus the one real quote-quality review. The
round reserved 27/32 Codex turns and dispatched one real Claude inference. The real reviewer returned two exact plan
quotations, with source digest and spans verified before rendering. Its startup exposed missing legacy account metadata
in Claude 2.1.294; `9ea12b6a` accepts an explicitly verified personal Pro/Max auth status while continuing to refuse
unknown, conflicting, API-backed, or managed routes. The final clean wheel repeats source-only/off/deny with no checkout
override and unchanged enrollment bytes. Earlier failures and helper changes are retained in
[provenance](evidence/validation.md), including the manually closed initial TUI capture.

Aggregate checks passed: 10,640 unit tests (117 integration tests deselected), 1,416 regressions, and full pre-commit.
Targeted Docker results include the documented Claude 2.1.294 Linux ARM startup failure; both auth-isolation cases
passed on explicitly selected 2.1.291. The real 2.1.294 macOS review passed.

Full review/merge and fixture-auth teardown remain separate closeout work. Move inbound B3 links when the card moves to
`done/`; keep the epic active and B4/B5/Jev unactivated.

2026-10-10 PR review corrections: `fb26b011` preserves symlink launchers/child PATH lookup, streams hashing, binds
feedback admission to the invoking process, and strips inherited identity from Claude children. It restores shared
blocking guidance, excludes resolved tier-1 failures from unreviewed feedback, and scopes source-only stop-and-ask
instructions to unquoted reviewer findings. Tests exercise real launchers and the actual Codex hook wire.

Review validation passed 10,640 unit tests, 1,441 regressions, 32 Docker hook/manual-policy cases, and two Docker auth
isolation controls with the explicit 2.1.291 override. A fresh wheel repeated source-only/off/deny, and the TUI replay
confirmed both channels with schema-2 admission. `ab055ede` fixes delayed-terminal input and a cold-admission assumption
in the deadline fixture; failed attempts remain in evidence. Full pre-commit passed. The extended round used 32/32 Codex
reservations and still only one real Claude inference. Host configuration changed between the initial assertion report
and this replay; both hashes and the timing qualification are recorded in [provenance](evidence/validation.md).
