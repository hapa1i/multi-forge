# Checklist: Refresh release QA for v1.0.0

**Card**: [card.md](card.md).

**Lane**: `doing/` -- accepted and activated directly from `proposed/` on 2026-08-25 because acceptance and branch
creation happened in the same decision.

**Execution branch**: `test/refresh-release-qa-for-1-0`.

**Activation base**: `e0a45f22` (`main`, 2026-08-25).

## Current Focus

Awaiting checklist review. No QA implementation has started. Phase 0 freezes the evidence, artifact, runtime, budget,
section-placement, and Codex-delivery contracts before checklist content or state-machine behavior changes.

## Execution Guardrails

- `/forge:qa` remains a Claude-hosted frontend. Claude and Codex are subjects under test; this card does not create a
  Codex-hosted QA package.
- The release verdict comes from one exact wheel installed outside the checkout. `/forge`, editable environments, and
  `PYTHONPATH` may provide fixtures but may not satisfy Forge imports or packaged-resource discovery.
- Automated suites remain authoritative for exhaustive edge-case matrices. Every removed QA assertion must name its
  automated owner or an intentional replacement in the coverage map.
- Keep section numbers 0-20 stable. New probes append after the existing steps in their mapped section; do not insert
  steps, renumber existing ids, or add section 21+. Preserve category, `--from`, `--to`, prerequisite, resume,
  artifact-save, and cleanup semantics unless Phase 0 explicitly ratifies a compatible extension.
- A state-machine behavior change updates both self-contained `walkthrough-state.py` copies and their full behavior and
  parity tests in the same commit. QA-only wording or checklist changes must not touch the walkthrough copy.
- The blocking lane must finish with at most 12 human checkpoints and at most 8 paid model completions. These
  deterministic counts are hard gates. End-to-end duration is recorded; exceeding the 45-minute review threshold sets
  `budget_review_required` and requires maintainer disposition, but does not by itself change a correctness result.
  `latest` compatibility evidence never changes the pinned blocking verdict.
- Keep the standard test targets green at every committed slice. A structural contract assertion lands with the
  checklist/report data that satisfies it; budget assertions land only after the blocking selection and counting model
  exist.

## Phase 0 -- Freeze the Runner Contracts

- [ ] Produce `docs/board/doing/refresh_release_qa_for_1_0/baseline-inventory.json` with a versioned JSON schema and one
  record for each of the 188 current steps. **Assertion**: every record includes section/step id, execution class,
  prerequisites, paid/live-runtime use, current assertion count, proposed keep/merge/move/remove outcome, target
  section, evidence lane, and automated owner where applicable; the inventory reconciles 150 `auto`, 32 `human:guided`,
  6 `human:confirm`, and 636 parsed assertions without omissions.
- [ ] Ratify the evidence/selection contract before changing annotations. **Proposed contract for review**:
  `resources/coverage-map.md` classifies contracts as `automated-suite`, `clean-wheel-smoke`, `human-acceptance`, or
  `extended-exploratory`; `/forge:qa` runs the blocking clean-wheel/human set by default, while one `--extended` switch
  includes exploratory steps. Do not expose four runner modes or overload category names with evidence semantics.
  **Assertion**: default, category, range, resume, and extended selection have deterministic, regression-tested
  inclusion rules.
- [ ] Ratify the artifact-input contract. **Proposed contract for review**: default developer QA builds one wheel once;
  `--wheel <path>` consumes a prebuilt release-candidate wheel; release sign-off requires the explicit prebuilt path. A
  legacy source/editable run, if retained, is labelled development-only and cannot emit a release-pass verdict.
  **Assertion**: the report identifies exactly one wheel by canonical path, filename, version, and SHA-256, and its
  `forge-qa-release` image identity cannot collide with the editable integration image even when revision and runtime
  versions match.
- [ ] Ratify the runtime identity contract whose repository authority will be
  `src/skills/qa/resources/runtime-matrix.json`. **Proposed contract for review**: the resource owns a schema version,
  pinned Claude/Codex versions, probe commands/results/dates, runtime track, and the Forge revision that accepted the
  pair; `--runtime-track latest` remains a separately labelled compatibility run. Do not derive the Claude pin from
  `MIN_CLAUDE_CODE_VERSION` or test-local evidence markers. Select Codex at or above
  `CODEX_PROXY_CONTRACT_VALIDATED = 0.141.0` and run the general preflight/probe suite at that version; Phase 1 records
  the pair and raises `CODEX_VERSION_VALIDATED` from `0.139.0` in one test-backed slice. **Assertion**: both clients
  have fresh release-probe evidence, and an absent pin, `latest`, or version mismatch cannot masquerade as the pinned
  blocking run.
- [ ] Ratify the blocking-budget counting units. **Proposed contract for review**: one included `human:guided` or
  `human:confirm` step is one human checkpoint; one intentionally requested subject-under-test model completion is one
  paid operation. A panel counts each worker, consensus/debate count every worker in every round, every prompted
  managed-session turn counts separately, `runtime preflight codex --verify-enrollment` counts one only when it runs its
  real probe turn, and AI-curated transfer generation counts one when curation runs. Static status/preflight that
  short-circuits without a turn counts zero. Exclude the Claude-hosted checklist driver's own orchestration and report
  it separately. **Assertion**: the same fixtures produce the same counts before execution and in the saved report; the
  hard limits are 12 human checkpoints and 8 paid operations, with no minimum.
- [ ] Ratify duration semantics. **Proposed contract for review**: record wall-clock time for the complete `/forge:qa`
  invocation from artifact validation through final report save. A run over 45 minutes sets
  `budget_review_required: true` and needs explicit maintainer disposition before sign-off, but duration alone does not
  fail an otherwise correct run. **Assertion**: reports cannot omit duration or silently treat the review threshold as a
  product-test failure.
- [ ] Ratify the append-only landing map. **Proposed contract for review**: append extension lifecycle probes to section
  2; backend/provider trace to 4; managed runtimes, routing, adoption/repair, and consumer lanes to 5; runtime hook
  readiness to 6; billing/telemetry to 7; direct commands to 9; transfer/rewind/ancestry to 10; and authority/policy
  source modes to 13. Record the final target and future step id in `baseline-inventory.json` before editing fragments.
  **Assertion**: no existing step id or section address moves, no section 21+ appears, and report categories remain
  stable.
- [ ] Ratify Codex context-delivery ownership. **Proposed contract for review**: blocking live QA proves
  `initial-message`; enrolled hook firing is owned by `tests/integration/docker/test_real_authority.py`, while staged
  hook receipt/delivery remains owned by `tests/integration/docker/test_policy_hooks.py`. An optional `--extended`
  enrolled hook probe must require `--verify-enrollment` success and recorded `session_start_hook` evidence. A trust
  recovery diagnostic is a failed/negative probe, not a passing branch. **Assertion**: each selected environment has one
  known expected outcome and no either/or assertion can pass forever on recovery output.
- [ ] Reconcile the accepted decisions into `card.md`, `SKILL.md` argument semantics, the container interface, and the
  test plan before implementation proceeds. Record any rejected alternative and why it would weaken reproducibility or
  add state-machine complexity.

## Phase 1 -- Lock Checklist and Harness Contracts with Tests

- [ ] Repair the two current structural inputs and add `tests/src/skills/test_qa_checklist_contract.py` in the same
  green slice. **Assertion**: update the current declared count from 632 to the parsed 636 and add the missing Costs row
  before enabling assertions that the index metadata parses, its declared `test-count` equals all 21 fragments, section
  and step ids are unique, every step has exactly one supported execution class, referenced section files exist, and
  report categories match the index. Every later checklist-content slice recomputes the count in that same slice.
- [ ] Create the accepted runtime matrix and its schema/invariant contract alongside the Codex ceiling update.
  **Assertion**: the matrix contains one pinned pair with fresh probe provenance, the Codex pin is at or above the proxy
  floor and no higher than `CODEX_VERSION_VALIDATED`, and tests that intentionally asserted the old ceiling/floor split
  are updated in the same green slice.
- [ ] Replace the host-derived-version assumptions in `tests/regression/test_bug_qa_runtime_image_tag_parity.py` with
  the ratified pinned/latest identity contract. **Assertion**: the integration shell runner and Python fixture retain
  one editable-image tag identity, but wheel-backed QA deliberately uses the distinct `forge-qa-release` namespace and
  cannot share their full tag or revision-only reuse key. Runtime-version serialization/build-argument shape remains
  aligned where useful, while runtime versions, artifact digests, and tracks prevent release-QA collisions.
- [ ] Add focused shell/container contract coverage for `start-container.sh`. **Assertion**: missing/invalid wheel
  paths, ambiguous wheel sets, version/digest mismatch, stale container reuse, provider-profile mismatch, runtime-track
  mismatch, and unknown flags fail before a container is reused or started.
- [ ] If Phase 0 requires parser support, update both parity-locked state scripts test-first. **Assertion**: index,
  step, init, record, report, prerequisite resolution, `--from` validation, and checklist hashing behave identically in
  both copies; otherwise leave both scripts byte-unchanged.

## Phase 2 -- Make the Exact Wheel the QA Subject

- [ ] Implement one build-or-consume artifact preparation path owned by the QA harness. **Assertion**: it resolves one
  wheel, verifies the filename/version metadata, computes SHA-256 once, and passes immutable identity into image and
  container startup; rebuild/reuse never silently selects another artifact.
- [ ] Install the wheel and its resolved dependencies into a clean environment outside `/forge`. **Assertion**:
  `command -v forge`, `forge --version`, `import forge`, distribution metadata, and `importlib.resources` all resolve
  from the wheel environment while the working directory is `/workspace` and the checkout is absent from `sys.path`.
- [ ] Preserve checkout access only for explicit fixtures and test commands. **Assertion**: temporarily making the
  checkout's Forge package unavailable does not break installed CLI or extension-resource discovery, and deliberately
  substituting checkout-only content cannot satisfy the provenance preflight.
- [ ] Make container identity and reuse artifact-aware. **Assertion**: the distinct release-QA tag and labels/status
  include Forge revision, wheel digest/version, provider profile, Claude version, Codex version, and runtime track; it
  cannot reuse the editable integration image, and any same-lane mismatch yields an actionable reset/restart refusal
  before tests run.
- [ ] Add isolated Codex readiness/auth ingress without copying unrelated host state. **Assertion**: `CODEX_API_KEY` or
  an explicitly selected isolated Codex credential source reaches only the container, secret values never enter logs or
  reports, `forge codex status` and `forge runtime preflight codex` explain missing readiness, and the blocking run
  cannot count a skipped managed-Codex turn as a pass.
- [ ] Keep `scripts/test-wheel-runtime.sh` as the independent dependency-resolution/LiteLLM smoke and preserve the
  editable Docker target used by automated integration tests. **Assertion**: adding the QA artifact lane does not turn
  the general integration fixture into a wheel-only environment or duplicate the existing LiteLLM smoke logic.

## Phase 3 -- Restore Checklist Truth

- [ ] Fix authentication step 3.4. **Assertion**: human and JSON views account for all six registered credentials,
  including `codex-api`, with secret and connection-value masking still distinguished.
- [ ] Fix telemetry vocabulary in steps 7.11 and 7.14. **Assertion**: paths and output assertions consistently use
  `downstream`; no live QA text calls that store `requests`.
- [ ] Replace or correct hook step 6.11. **Assertion**: the command actually exercises the claimed Claude WorktreeCreate
  behavior, or the step is reclassified to its real Forge-owned worktree contract; it does not expect a project/local
  runtime-hook block when runtime hooks are user-scoped.
- [ ] Correct incremental-disable assertions in sections 18 and 19. **Assertion**: runtime-scoped removal checks only
  the selected ownership, preserves omitted runtimes and unrelated bytes, and describes user/project/local ownership
  exactly as `extension status --json` reports it.
- [ ] Retag only `src/skills/qa/resources/checklist.md` for v1.0.0, recompute `test-count` mechanically, and replace the
  historical update diary with concise current-contract metadata. Keep `test-count` synchronized in every slice that
  changes assertions; the walkthrough card retains sole ownership of the walkthrough header.
- [ ] Remove historical phase labels from current user-facing section/step titles. **Assertion**: titles describe the
  shipped command or behavior and do not imply obsolete implementation phases.
- [ ] Complete an assertion-to-command audit across sections 0-20. **Assertion**: every invoked command exists in
  current CLI help, every output claim is observable from that command, destructive and infrastructure annotations are
  accurate, and partial-run prerequisites still resolve all required fixture state.

## Phase 4 -- Publish Coverage Ownership and Cut Human Noise

- [ ] Add `src/skills/qa/resources/coverage-map.md` using the ratified four-lane vocabulary. **Assertion**: every v1.0.0
  surface in the card names its authoritative command/test path, clean-wheel seam when needed, human seam only when
  judgment is irreducible, and an explicit reason for any exploratory-only status.
- [ ] Replace live resume steps 10.2-10.5 with a transfer-regeneration matrix over `minimal`, `structured`, `full`, and
  `ai-curated`. **Assertion**: generated frontmatter/body, warnings/fallback, child-snapshot preservation, and target
  runtime are checked without four child launches; retain one real delivery and one editor interaction.
- [ ] Reduce fork handoffs to one same-directory native continuation and one cross-worktree transfer continuation.
  **Assertion**: both distinct mechanisms remain covered, while repeated "where were we?" launches and already-owned
  generated-file variants leave the blocking lane.
- [ ] Reduce live skill/workflow coverage to one portable skill invocation and one representative multi-worker frontend.
  **Assertion**: package compilation/invocation and real fan-out remain visible, while review, understand, panel,
  consensus, debate, and analyzer permutations rely on their CLI/compiler/integration owners.
- [ ] Keep one rendered status-line review and automate raw ANSI, breadcrumb, config, fixture-cost, and lazy-source
  assertions. **Assertion**: palette/layout judgment remains human; deterministic content checks do not prompt.
- [ ] Replace synthetic hook matrices with unit/integration owners and retain one real Claude lifecycle, one live Codex
  preflight/`initial-message` seam, and the positive automated real-Codex hook owner. **Assertion**: removal references
  the owning tests and does not erase the clean-runtime failure class that manual QA is meant to catch.
- [ ] Convert deterministic editor, cap, header, logging, and confirmation checks to automatic evidence. **Assertion**:
  `EDITOR=true`, exit status, JSON, filesystem, and grep checks replace prompts wherever they fully decide the claim;
  one representative editor and destructive confirmation remain.
- [ ] Move the planner -> supervisor -> executor demonstration and redundant catalog matrices to the extended lane.
  **Assertion**: the blocking gate retains deterministic supervisor, compiler, installer, and package-health owners;
  default `/forge:qa` does not launch the three-session demonstration.
- [ ] Recount the resulting gate and extend `tests/src/skills/test_qa_checklist_contract.py` for evidence selection and
  budgets in the same green slice as the final blocking metadata. **Assertion**: every retained contract has one lane
  and an existing owner path; default and extended steps remain distinguishable without changing section ids; computed
  human checkpoints are at most 12 and paid operations are at most 8 under the ratified units; every removed assertion
  has a named owner; and no reduction is credited merely by relabelling a human step `auto`. Do not enable the budget
  assertions against the pre-trim 38-step human baseline.

## Phase 5 -- Cover the Missing v1.0.0 Surfaces

- [ ] Add installed managed-Claude lifecycle evidence. **Assertion**: one clean-wheel session produces real
  SessionStart/Stop confirmation and a transcript artifact; synthetic hook calls remain automated-suite evidence.
- [ ] Add installed managed-Codex evidence. **Assertion**: static status and preflight pass, one bounded managed
  start/resume turn records the thread, and default `initial-message` delivery works. Do not claim that this live step
  proves hook delivery.
- [ ] Preserve deterministic Codex hook coverage through its automated owners. **Assertion**:
  `tests/integration/docker/test_real_authority.py` positively demonstrates enrolled real-runtime hook firing and
  `tests/integration/docker/test_policy_hooks.py` demonstrates staged hook receipt/delivery. If the optional enrolled
  extended lane is selected, `runtime preflight codex --verify-enrollment` must report enrolled and the managed turn
  must record `session_start_hook`; documented recovery output fails that step and remains diagnostic evidence only.
- [ ] Add model-first routing evidence. **Assertion**: `--model` resolves the expected direct/proxy route and
  `forge session model show`, `history`, and `%session model show` report the committed event rather than only intent.
- [ ] Add authority evidence without duplicating the real-runtime matrix. **Assertion**: installed set/show plus one
  allowed/denied mutation agree with the journal; exhaustive Claude/Codex advisory/producer combinations remain owned by
  `tests/integration/docker/test_real_authority.py`.
- [ ] Add native-adoption and session-repair CLI round trips. **Assertion**: adoption preview/id binding and ambiguous
  evidence fail-closed; repair preview/apply is root-scoped, degraded records remain visible, and neither flow destroys
  native transcripts or recreates worktrees.
- [ ] Add rewind and ancestry-depth installed probes. **Assertion**: resume and fork accept valid rewind/drop-last and
  fresh/depth forms, reject invalid flag combinations, and leave the full native continuity matrix to the existing
  Docker integration owner.
- [ ] Add consumer-lane evidence. **Assertion**: lane set/show/clear covers each supported consumer, supervisor status
  reflects the effective lane, and the keyed QA container verifies live `api` plus available unknown/proxied evidence.
  The keyless direct `claude-max` -> `subscription_quota` branch remains explicitly owned by
  `tests/src/core/usage/test_billing.py`; injected `ANTHROPIC_API_KEY` must not be removed merely to synthesize that
  branch in live QA.
- [ ] Complete backend and provider-trace operator paths. **Assertion**: backend list/show/test-auth/start/stop/delete
  and reconcile use correct source/adapter/runtime ids; trace list/show/explain joins one real request and emits stable
  JSON/human output.
- [ ] Add both policy single-source modes. **Assertion**: an installed
  `forge policy check --bundle coding_standards --file <path>` and piped `--diff` succeed, while zero sources and
  `--file` plus `--diff` fail atomically with actionable diagnostics.
- [ ] Reconcile extension and transfer coverage against the exact wheel. **Assertion**: enable/status/sync,
  runtime-scoped disable, unmanaged cleanup, uninstall preservation, transfer strategy generation, and one human-visible
  delivery all execute from packaged resources without checkout fallback.

## Phase 6 -- Orchestration, Reporting, and Documentation

- [ ] Update `src/skills/qa/SKILL.md` for the ratified artifact, runtime-track, and extended-selection arguments.
  **Assertion**: parsing rejects unknown/conflicting values before Docker mutation; category and range examples remain
  accurate; the execution loop runs only checklist commands and always saves artifacts after partial or failed runs.
- [ ] Update `report-template.md` and report assembly. **Assertion**: the report records artifact path/digest/install
  method, Forge/checklist versions, runtime pins/observed versions/track, provider profile, evidence lane, duration,
  `budget_review_required`, human checkpoint count, paid-operation count, separately reported driver orchestration,
  per-section results, gaps, and preserved debug/transcript artifacts.
- [ ] Keep state and report semantics honest for automated-suite owners. **Assertion**: referenced automated tests are
  not counted as commands executed by the manual run; skipped prerequisites and non-blocking latest failures cannot
  inflate the blocking pass total.
- [ ] Update `docs/design_installation.md` and `docs/developer/testing_guidelines.md` with the settled evidence lanes,
  exact-artifact boundary, runtime identity, budgets, and state-script rule. Update `docs/end-user/manual_testing.md`
  only for public invocation/recovery changes.
- [ ] Verify packaged-resource/compiler ownership. **Assertion**: the wheel contains the QA checklist fragments,
  coverage map, runtime matrix, report template, scripts, and updated `SKILL.md`; Claude installation exposes QA, Codex
  installation still omits it, and no new cross-skill runtime dependency is introduced.

## Phase 7 -- Verification and Release-Candidate Evidence

- [ ] Run focused skill/checklist tests, including the new contract tests and both state-script behavior/parity suites.
- [ ] Run the updated QA image-identity regression and focused installer/compiler/profile tests.
- [ ] Run the targeted Docker/integration owners named in the acceptance table for Claude hooks, Codex sessions, model
  routing, authority, adoption/repair, rewind, backend lifecycle, provider trace, policy source modes, and installer
  lifecycle.
- [ ] Run `make test-unit`, `make test-regression`, and `make pre-commit` with no unexplained failures or new skips.
- [ ] Run `uv build`, `scripts/test-wheel-runtime.sh`, and the exact-wheel isolation/lifecycle integration gate against
  the same candidate artifact.
- [ ] Run one complete pinned-runtime blocking QA pass from a prebuilt release-candidate wheel. **Assertion**: report
  and artifacts are saved, all blocking sections pass, runtime and artifact identities match, human checkpoints are at
  most 12, paid operations are at most 8, duration is recorded, any over-45-minute run has explicit maintainer
  disposition without being reclassified as a product failure solely for elapsed time, and cleanup preserves unrelated
  bytes.
- [ ] Run one separately labelled `latest` compatibility pass when runtime/network availability permits. Record a skip
  or failure as compatibility evidence without changing the pinned verdict.
- [ ] Run Markdown links, repository file-size checks, and `git diff --check`; review the final diff for accidental
  walkthrough changes, secret material, stale paths, and checklist claims not backed by executed evidence.

## Acceptance Tests

| Test                     | Fixture                                                                | Assertion                                                                                            | Test File                                                                                                                                                                                |
| ------------------------ | ---------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Checklist metadata truth | 21 QA fragments and index                                              | declared count, ids, execution classes, categories, and parsed assertions agree                      | `tests/src/skills/test_qa_checklist_contract.py` (new)                                                                                                                                   |
| Evidence selection       | blocking and extended fixtures with category/range/resume              | selection is deterministic and budgets count only included steps                                     | `tests/src/skills/test_qa_checklist_contract.py`; state tests if parser changes                                                                                                          |
| State-script parity      | both packaged state scripts                                            | only the two approved identity lines differ and the full behavior matrix passes                      | `tests/src/skills/test_walkthrough_state.py`, `tests/src/skills/test_walkthrough_state_parity.py`                                                                                        |
| Runtime matrix           | repository matrix plus Claude/Codex preflight fixtures                 | pins have fresh probe evidence; Codex pin meets the proxy floor and general ceiling                  | `tests/src/skills/test_qa_checklist_contract.py`, `tests/src/core/runtime/test_codex_preflight.py`                                                                                       |
| Artifact identity        | supplied RC wheel plus checkout with distinguishable content           | CLI, import, metadata, and resources resolve only from the recorded wheel                            | `tests/integration/docker/test_qa_release_artifact.py` (new)                                                                                                                             |
| Container reuse identity | editable and release builds sharing revision/runtime versions          | full image identities differ; changed release digest/profile/track rejects stale reuse               | `tests/src/skills/test_qa_start_container.py` (new), `tests/regression/test_bug_qa_runtime_image_tag_parity.py`                                                                          |
| Managed Claude lifecycle | clean-wheel project and real Claude                                    | SessionStart/Stop confirmation and transcript artifact are produced                                  | `tests/integration/docker/test_real_claude_hooks.py`                                                                                                                                     |
| Managed Codex lifecycle  | authenticated Codex and clean-wheel project                            | preflight plus one `initial-message` start/resume records a thread                                   | `tests/integration/core/test_codex_session_start.py`                                                                                                                                     |
| Codex hook delivery      | enrolled real runtime plus staged hook receipt                         | real hook firing and staged delivery pass positively; recovery output is not a pass                  | `tests/integration/docker/test_real_authority.py`, `tests/integration/docker/test_policy_hooks.py`                                                                                       |
| Model route evidence     | direct and proxy-capable catalog fixtures                              | explicit model resolves expected route and show/history report its event                             | `tests/integration/docker/test_session_routing.py`                                                                                                                                       |
| Native adoption          | Claude/Codex evidence plus ambiguous and already-bound ids             | binding follows on-disk runtime evidence and preserves the native transcript                         | `tests/integration/docker/test_adopt_native_conversation.py`                                                                                                                             |
| Store repair             | orphan and degraded manifests in one Forge root                        | preview/apply restores valid rows without recreating worktrees or accepting corruption               | `tests/integration/docker/test_session_lifecycle.py`                                                                                                                                     |
| Rewind and depth         | native parent lineage plus valid/invalid fresh flags                   | resume/fork preserves rewind and ancestry contracts                                                  | `tests/integration/docker/test_rewind_native_contract.py`                                                                                                                                |
| Transfer generation      | four strategies, child snapshot, and notes overlay                     | regeneration changes only the parent cache and reports strategy/runtime honestly                     | `tests/src/session/test_transfer.py`, `tests/src/cli/test_transfer_cli.py`                                                                                                               |
| Consumer lanes           | four consumers plus keyed/direct, keyless/direct, and proxied fixtures | live lane/status and API/unknown/proxied agree; automated keyless Claude Max is `subscription_quota` | `tests/src/cli/test_session_lane.py`, `tests/src/cli/test_policy_supervisor.py`, `tests/src/core/usage/test_billing.py`, `tests/integration/session/test_shadow_curation_codex_smoke.py` |
| Authority enforcement    | advisory and producer fixtures on both runtimes                        | mutation outcome and journal agree with authority                                                    | `tests/integration/docker/test_real_authority.py`                                                                                                                                        |
| Backend and trace paths  | authenticated backend and one traced request                           | lifecycle ids are correct and trace list/show/explain join the request                               | `tests/integration/backend/test_backend_cli.py`, `tests/integration/proxy/test_provider_trace_e2e.py`                                                                                    |
| Policy source modes      | one file, one piped diff, zero sources, and both sources               | exactly one source succeeds; invalid source counts fail before evaluation                            | `tests/integration/cli/test_policy_cli_contract_integration.py` plus QA installed probe                                                                                                  |
| Runtime budget           | selected blocking steps plus complete blocking report                  | human checkpoints are at most 12 and paid model completions are at most 8                            | `tests/src/skills/test_qa_checklist_contract.py`                                                                                                                                         |
| Duration evidence        | complete blocking report                                               | elapsed time is recorded; over 45 minutes sets review-required without changing test verdict         | `tests/src/skills/test_qa_checklist_contract.py` plus recorded RC evidence                                                                                                               |
| Clean uninstall          | wheel-owned Claude/Codex surfaces plus unrelated bytes                 | selected ownership is removed and unrelated content remains byte-identical                           | `tests/integration/docker/test_installer.py`                                                                                                                                             |

## Closeout

- [ ] Review the complete implementation and RC evidence with the maintainer; close every review finding or record an
  explicit accepted limitation before release sign-off.
- [ ] Add the compact completed-work entry to `docs/board/change_log.md`; promote only human-approved durable evidence
  lane, artifact-boundary, or runtime-identity decisions through `docs/board/impl_notes.md`.
- [ ] Confirm design and end-user documentation describe shipped behavior, then move this card to `done/` and repoint
  the walkthrough card's inbound link to the final lane.
- [ ] Commit the reviewed implementation in a reviewable series, push the execution branch, open the PR with exact
  verification evidence, and merge only after the release-candidate gate and required checks pass.
