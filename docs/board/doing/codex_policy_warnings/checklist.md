# Codex policy warnings checklist

Card: [card.md](card.md). Epic: [Codex supervisor](../epic_codex_supervisor/card.md), member **B3**.

## Current focus

Selected 2026-10-10 on `feat/codex-policy-warnings`, based on clean local `main` at `d54dba63` (B2 closeout above merged
PR #261, `2a15c087`). This checklist plans implementation; product code and runtime configuration are unchanged. B1 and
B2 are done. B4, B5, and the Jev cards remain proposed.

Deliver bounded, attributed policy warnings to the Codex model after allowed patches, with an independent operator
warning channel. The user selected the source-only opt-in: verified plan passages and fixed Forge diagnostics may enter
model context while reviewer-generated wording remains in durable evidence. Preserve verdicts, catch-all artifact
authority, hook deadlines, and atomic patch-state persistence.

### Verified starting point

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
- `DeterministicPolicy._warn()` and permissive TDD currently discard available intent/violation detail. Audit producers
  before promising substantive feedback. `PolicyDecision.fail_open` and `failure_type` distinguish unavailable reviews
  from alignment; do not infer success from an allow verdict or absence of violations.
- B1's `PlanSnapshot` holds the reviewed text and digest. Existing citation parsing checks shape, not whether a quote
  occurs in that snapshot. Source-only formatting needs explicit validation against that same read.

## 0. Activation

- [x] Create the separate execution branch from `d54dba63`; move B3 from `proposed/` to `doing/` with `git mv`.
- [x] Add this checklist; update the epic's active member, B1/B2 prerequisites, and inbound B1/Jev links.
- [x] Record the user's choice to include source-only mode. Keep B4/B5, Jev inference, and native-fork review outside
  this card's implementation scope.
- [x] Validate this planning change with Markdown, size, repository-link, and staged/working-tree diff checks.

## 1. Pin the delivery and compatibility contract

- [ ] On a supported executor, serialize one JSON object for an allowed action with feedback. The measured model
  candidate is `{"hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":"..."}}`; omit explicit
  `permissionDecision: "allow"`. Put operator `systemMessage` at its measured top-level location. Verify the combined
  shape, operator-only shape, and model-only control independently; B2 tested the channels separately.
- [ ] Define the output matrix before implementation: clean allow stays silent on stdout; warning/degraded allow may
  carry feedback; summary-off omits `additionalContext` but retains substantive operator warnings and durable records.
  Deny and unresolved review keep their blocking wire and precedence. Silent unmanaged, irrelevant-event, non-patch,
  malformed-input, and disabled-policy paths remain silent after the existing authority guard runs.
- [ ] Separate delivery admission from the general validated ceiling and blocking QA pin. Use 0.161.0 as the minimum
  measured candidate; specify behavior for older, unknown/unparseable, stale, tested, and newer-than-validated executor
  versions. An unsupported feedback channel must not change policy verdicts or claim in-session delivery. Preserve
  existing preflight readiness and re-probe semantics; this feature does not revalidate the release pin.
- [ ] Establish how the hook obtains the active executor's binary/version identity for headless, TUI start, and resume.
  Reuse launch/preflight facts where valid, with invalidation for executable changes and an explicit unknown case. The
  reviewer readiness cache is not automatically executor identity. Do not run `codex doctor`, a model call, or a fresh
  version subprocess on every policy action. Record this choice and tests before enabling the channel.
- [ ] Select and document the explicit source-only configuration key, values, default, ownership, and read/set surfaces.
  Keep `policy_summary_feedback` as the existing on/off injection control; a format option must not override it. Default
  substantive feedback preserves normal warning details; source-only is opt-in. Scope the new formatting to Codex and
  preserve Claude output unless a separately documented shared contract change is required.

## 2. Collect and render feedback without changing policy decisions

- [ ] Collect findings from every evaluated file and its individual decisions. Preserve file path, policy/rule ID,
  severity when present, policy intent, violation message, evidence, citations, and suggested fix where supplied. Keep
  plain warning strings attributable to their owning policy. Carry existing intent/evidence through permissive warning
  producers rather than reconstructing or inventing it in the responder; retain verdict semantics.
- [ ] Deduplicate by attributed finding, with deterministic file/rule order. Equal text on different paths/rules remains
  distinguishable. A clean first file must not hide a later warning. Keep formatter logic separate from evaluation and
  stdout emission; no new reviewer call may be needed to format existing results.
- [ ] Set named per-field, per-finding, finding-count, and total serialized-byte limits, then pin them in tests. Bound
  `additionalContext` and `systemMessage` independently, account for JSON escaping/Unicode, and reserve space for an
  omitted/truncated count plus an inspection command. Do not truncate serialized JSON or misattribute omitted files.
- [ ] Label policy evidence as quoted data with path/rule attribution. Arbitrary code, citations, and reviewer text must
  not become unlabeled Forge instructions. In normal mode retain substantive feedback; in source-only mode apply section
  3 before any model-visible serialization. A clean allow need not add repetitive success context.
- [ ] Emit one stdout response after cross-file composition. Preserve `deny > needs_review > warn/allow`, exit codes,
  authority-first evaluation, tests-first ordering, and the no-matcher 60-second registration. Keep diagnostics on
  stderr; neither formatting nor evidence-write failure may replace a computed denial with an allow.
- [ ] Preserve one decision-log entry per evaluated file and aggregated state in one manifest update. Blocked patches
  persist audit entries but no optimistic file state. Formatting, deduplication, truncation, and summary-off must not
  mutate stored decisions, discard review evidence, or record a synthetic successful review.
- [ ] Render fail-open/unavailable review outcomes as unreviewed or unavailable using structural status. Include the
  failure reason without labelling the patch aligned; preserve status/activity visibility. Keep existing engine-build,
  evaluation-error, unresolved-review, and configured fail-mode behavior. Cover partial and all-file evaluation errors.

## 3. Implement the source-only opt-in

- [ ] Use the exact immutable plan text/digest supplied to that action's reviewer, including cascade and cache paths.
  Carry the needed provenance to the formatter explicitly; do not reread a mutable plan path after review or trust a
  reviewer-provided filename/hash. Audit resumed-conversation sources: without an available verified snapshot, emit
  fixed Forge diagnostics and state that source text could not be verified.
- [ ] Validate nonempty quoted passages against that snapshot before inclusion, retaining source/digest attribution.
  Define allowed normalization narrowly and test it. Reject invented text and wrong-snapshot matches; citation labels or
  file paths alone do not verify a quotation. Missing/unreadable source never authorizes a prose fallback.
- [ ] Exclude reviewer-generated explanation, evidence prose, suggested fixes, and free-form warnings from every Codex
  model-visible warning and block field in this mode. Use verified source passages plus fixed Forge diagnostics;
  deterministic rule intent/evidence remains attributed according to its provenance. Apply the choice to deny and
  unresolved-review text as well as allowed warnings, independently of the summary toggle. Verdicts remain unchanged.
- [ ] Keep full original findings and review evidence available through existing inspection surfaces. Formatting is a
  presentation choice, not a new verdict, quota policy, lane binding, or claim that quoted text has no watermark. Bound
  and deduplicate verified passages through the same renderer contract as ordinary feedback.
- [ ] Verify option validation, default behavior, persistence/reload, and config show/set output. If the chosen owner
  changes manifest/config schemas, add compatibility and migration tests and update the relevant design/user guide;
  avoid changing shared consumer-lane formats for an output preference.

## 4. Establish fresh product evidence

### Fixture and quota gates

- [ ] At execution start, resolve and retain the complete installed Codex package; record path, SHA-256, version,
  model/effort, OS, Forge revision, and relevant source hashes. Use that copy throughout; a binary update starts a
  separately identified capture set. B2's dated 0.161.0 evidence is the baseline, not proof about a future installation.
- [ ] Use an independent login and private homes with a clean launcher that strips API credentials and disables dotenv.
  Never copy host `auth.json`. Set `FORGE_DEV` in every terminal, assert the doctor's effective dispatcher override, and
  record the actual hook launcher/module paths. Keep login state through all stages; reset baseline config only before
  enrollment or with an explicit invalidation and fresh ceremony.
- [ ] Record `forge runtime preflight codex --json`, doctor auth/billing facts, current hook registration, and the
  `--verify-enrollment` observation receipt. Use real user-scope enrollment without a hook-trust bypass. Capture host
  config hashes before/after if claiming byte equality; file equality does not establish refresh-token validity.
- [ ] Record the execution budget before live calls. Proposed cap: **32 reserved Codex turns**: 4 enrollment/checks, 12
  headless controls, 4 source-only controls, 4 TUI controls, 4 wheel/start/resume checks, and 4 failed-attempt/retry
  allowance. Reserve every attempt, including extra enrollment on each advisory launch/resume, against the same cap;
  rebalance before a group or obtain a budget extension before exceeding it. No paid API inference or Jev call is
  needed. Use no real Claude reviewer: deterministic findings and an admission-compatible local Claude stub supply
  review cases.
- [ ] Use bounded outer execution and descendant cleanup: TERM, then KILL, then a fixture-owned process sweep covering
  detached groups. Preserve completed and failed captures separately. A failed model turn is not negative delivery
  evidence. Commit the harness/helpers used for the final captures and retain their hashes, including exporter sources;
  later edits require affected reruns or an explicit drift qualification.

### Required controls

- [ ] Exercise the installed product dispatcher on a permissive deterministic warning and an injected rule-pack-shaped
  finding with a marker known only to the hook fixture. The action must land and a later model response must demonstrate
  marker consumption. Retain hook stdout/stderr/exit code, native injected message and role, turn result, and file
  bytes. Keep markers out of the task prompt, readable checkout, skills, and other context; use fresh threads for
  negative arms.
- [ ] Repeat with feedback off: the action still lands, `additionalContext` and the model-context marker are absent,
  while operator warnings and persisted decisions remain. Verify `systemMessage` independently in the interactive TUI,
  then test the combined product response. Do not claim headless event-stream visibility unless actually observed.
- [ ] Run multi-file/later-warning and warning-plus-deny controls. The first aggregates all attributed warnings into one
  response; the second blocks the entire patch and leaves prior state intact. Include an authority-denied non-patch
  request to prove the catch-all guard remains effective, and an unmanaged control that remains quiet.
- [ ] Exercise source-only mode with an exact approved-plan quote and a private reviewer-prose nonce. Verify that Codex
  consumes the permitted source marker, while reviewer prose is absent from the handler's model-visible fields and the
  retained native context. Keep the source marker in the reviewer's private snapshot, outside the executor prompt,
  checkout, and prior thread context. Include malformed/fabricated quotes and a changed-on-disk plan after the reviewer
  snapshot; full review evidence remains inspectable. Cover block formatting with deterministic/stub controls as well.
- [ ] Check unavailable/timed-out reviewer feedback with an admitted stub and an actual dispatch-start marker. Verify
  allowed work is described as unreviewed, existing failure/attempt records survive, and formatter work adds no reviewer
  calls. Preserve the B1 whole-hook deadline; do not repeat B2's full lifetime experiment without a relevant change.
- [ ] Verify headless start/resume and the interactive TUI path from the final implementation. Run the selected real
  Codex integration via the standard runner with the explicitly supplied isolated home; no silent auth fallback or skip
  may stand in for the required delivery proof. Record the observed binary's compatibility result separately from the
  feature's older/unknown-version unit controls.

## 5. Acceptance tests and owners

Existing files are starting owners; add focused files where that keeps responsibilities clear. Every bug regression
belongs under `tests/regression/test_bug_b3_*.py` with the regression mark. Publish coherent indexed sessions through
`tests.fixtures.session_state`. New integration test paths below are planned, not existing evidence.

| ID  | Fixture                                                                         | Required assertion                                                      | Test owner                                                                                        |
| --- | ------------------------------------------------------------------------------- | ----------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| T1  | Clean allow; warning; deny; unresolved review                                   | One valid response or documented silence; verdict precedence            | `tests/src/cli/hooks/test_codex_policy.py`, `test_codex_policy_check.py`                          |
| T2  | Clean first file; warnings on later files; duplicate text                       | All path/rule attribution retained; stable deduplication                | New `tests/src/cli/hooks/test_codex_policy_feedback.py`; B3 regression                            |
| T3  | Large findings; quotes; Unicode; empty optional fields                          | Explicit output bounds; valid JSON; visible omissions                   | Feedback formatter tests                                                                          |
| T4  | Feedback on/off; combined/model-only/operator-only responses                    | Context toggle independent of operator warning and audit                | Feedback command tests; live delivery fixture                                                     |
| T5  | Denied atomic test+implementation patch; allowed equivalent                     | Blocked patch adds no optimistic state; allowed state aggregates        | `test_codex_policy_check.py`; `tests/regression/test_bug_blocked_action_persists_policy_state.py` |
| T6  | Authority-denied Bash; unmanaged/irrelevant/disabled paths                      | Authority precedes filtering; other no-op paths quiet                   | Authority unit tests; `tests/integration/docker/test_policy_hooks.py`                             |
| T7  | Partial/all evaluation failures; unavailable review; persistence/format failure | Existing failure policy and computed denial survive; no false alignment | Command tests; B3 regressions; B1 deadline tests                                                  |
| T8  | Older/unknown/newer version; changed binary; stale/missing identity             | Explicit admission/diagnostic policy; no hot-path CLI probe             | Runtime/launch tests where identity is owned; feedback tests                                      |
| T9  | Source-only quotes; fabricated/wrong-source citation; plan reload/cache         | Exact snapshot used; reviewer prose absent; verdict/evidence preserved  | New source-only tests; `tests/src/policy/semantic/test_b1_contracts.py`; B3 regressions           |
| T10 | Config default/opt-in/off; malformed values; reload                             | Stable option contract; summary-off still wins                          | `tests/src/test_runtime_config.py`, `tests/src/cli/test_config_cli.py`, or selected schema owner  |
| T11 | Trusted real Codex and hook-only marker                                         | Allowed action plus independent model-consumption proof                 | New `tests/integration/core/test_codex_policy_feedback.py`; retained rollout                      |
| T12 | Interactive warning with model feedback off                                     | Operator sees notice; model lacks warning context                       | Scripted/manual TUI capture in B3 evidence                                                        |
| T13 | Installed candidate wheel; durable launcher; no `FORGE_DEV`                     | Hook imports installed artifact and emits validated response            | Clean-wheel dispatcher capture and selected integration                                           |
| T14 | Claude policy hooks; manual file/diff checks                                    | Existing Claude wire, CLI streams, and verdict semantics preserved      | `test_policy_feedback.py`, `test_responder.py`, policy Docker/CLI integrations                    |

## 6. Verification, docs, and closeout

- [ ] Run focused unit and regression tests as each slice lands. Use `make` prerequisites before direct pytest reruns.
  Run affected integration paths during implementation through
  `./scripts/test-integration.sh tests/integration/docker/test_policy_hooks.py tests/integration/cli/test_policy_cli_contract_integration.py`;
  add the new real Codex feedback integration once its fixture exists. Use `PYTHON_DOTENV_DISABLED=1` and the isolated
  launcher for subscription probes; inspect Docker/provider requirements before invoking any model-backed tests.
- [ ] Exercise `forge policy check --bundle coding_standards --file <fixture>` and a controlled diff piped to
  `forge policy check --bundle coding_standards --diff`. Inspect `forge policy supervisor status --json`, session policy
  records, and `forge telemetry activity <session>` for the degraded-review control. Add CLI stream tests if new public
  read/set diagnostics change their stdout/stderr contract.
- [ ] Update `docs/design_workflows.md` for feedback/source-only semantics and `docs/design_session_execution.md` for
  Codex delivery/version facts. Update `docs/end-user/policy.md` for configuration, operator/model distinctions,
  enrollment, compatibility, and actionable inspection commands. Sync configuration/installation or subprocess design
  only if those ownership contracts change; remove stale allow-is-unprobed wording in touched code and tests.
- [ ] Build and test a clean installed wheel: dispatcher provenance, warning/deny wire, source-only/off settings, and a
  trusted delivery control. Disable checkout overrides for that check and record wheel hash. Keep the general ceiling,
  blocking QA pin, shared validation revision/date, and proxy floor unchanged unless separately justified and
  revalidated.
- [ ] Run aggregate `make test-unit`, `make test-regression`, and full `make pre-commit`; verify board links and diffs.
  Retain commands, results, skips/failures, exact tested source, runtime/artifact hashes, and sanitized captures in B3's
  evidence. Final evidence must account for any helper or product edits after its capture revision.
- [ ] Before opening the B3 PR, fetch `origin/main` and publish local B2 closeout `d54dba63` by a normal fast-forward
  push if still missing. Reconcile divergence first; never force-push. Verify the PR base excludes B2 closeout and the
  diff contains only B3 work. Keep all work on this separate execution branch.
- [ ] Record B3's warning/formatting contract and limits in the epic and Jev A2 handoff. Keep B4/B5 and Jev cards
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

Only activation assertions are complete. The source-only setting and executor-version admission design remain section 1
tasks, to be settled before implementation.
