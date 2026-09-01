# Refresh release QA for v1.0.0

**Lane**: `done/` -- shipped in PR #247 (`35dd157d`) on 2026-09-01 with all five GitHub checks passing. It was accepted
and activated directly from `proposed/` on branch `test/refresh-release-qa-for-1-0`. This card completed before
[`refresh_walkthrough_for_1_0`](../../doing/refresh_walkthrough_for_1_0/card.md), so the walkthrough consumes the
release coverage boundaries instead of growing another product-contract suite.

**References**:

- [Interactive manual testing design](../../../design_installation.md#d-interactive-manual-testing)
- [Interactive manual testing guidelines](../../../developer/testing_guidelines.md#interactive-manual-testing-smoke-test-smoke-test-walkthrough-qa)
- [`cross_runtime_skills`](../../done/cross_runtime_skills/card.md)
- [`lock_walkthrough_state_parity`](../../done/lock_walkthrough_state_parity/card.md)
- [`model_first_session_routing`](../../done/model_first_session_routing/card.md)
- [`epic_session_authority_provenance`](../../done/epic_session_authority_provenance/card.md)

## Goal

Turn `/qa` into a bounded v1.0.0 release gate that validates the exact distribution artifact, exercises the real Claude
and Codex runtime seams, and reserves human checkpoints for behavior that cannot be judged deterministically. Remove
stale assertions and stop duplicating exhaustive contracts already owned by automated tests.

## Verified Baseline

Rechecked on `main` at `000cfc9c` on 2026-08-25:

- `pyproject.toml` still declares `0.9.4`; 214 commits follow tag `v0.9.4`.
- QA has 188 steps: 150 `auto`, 32 `human:guided`, and 6 `human:confirm`.
- The checklist header says 632 assertions, while the 21 section fragments contain 636 parsed checkbox assertions.
- `src/skills/qa/scripts/start-container.sh` builds `docker/Dockerfile.forge`; that image copies the checkout and runs
  `uv sync`, so QA exercises the editable `/forge/.venv`, not the wheel that will be published.
- The image tag derives Claude and Codex versions from the host and falls back to `latest`, so the blocking runtime
  matrix is not reproducible.
- No repository-owned Claude/Codex validation pair exists. Claude has a `2.1.78` minimum plus several test-local probe
  markers, while Codex currently has a `0.139.0` general-probe ceiling and a `0.141.0` proxy-contract floor. A valid
  release pin therefore requires fresh probes and a reconciled Codex ceiling; it cannot be inferred from current
  constants.
- The QA frontend is deliberately Claude-specific. Legacy skill sources default to Claude-only, and its checkpoint flow
  depends on `AskUserQuestion`. The Docker subject already includes both Claude and Codex CLIs.
- The two packaged `walkthrough-state.py` files are self-contained physical copies whose executable bodies may differ
  only in the two approved skill-identity lines. The complete behavioral suite and parity guard already cover them.

### Known correctness drift

The refresh must resolve at least these verified inconsistencies before adding coverage:

1. Authentication section 3.4 asserts five credentials; the registry exposes six, including `codex-api`.
2. Cost section 7.11 removes `~/.forge/telemetry/downstream/` fixtures but still calls the location `requests/`.
3. Cost section 7.14 prints `downstream=0` but asserts `requests=0`.
4. Hook section 6.11 starts a Forge-owned worktree directly, then claims Claude's WorktreeCreate hook created it and
   expects a local hook block. The command does not exercise that hook, and runtime hooks are user-scoped.
5. Incremental-disable assertions still describe project/local runtime hooks that no longer belong to that scope.
6. `resources/report-template.md` omits the Costs row.
7. `src/skills/qa/resources/checklist.md` still says `aligned-with: v0.1.0`; its phase labels and update prose mix
   historical implementation phases with current product language. The walkthrough card owns its own header metadata.

## Accepted Decisions

01. **One QA frontend.** Keep `/qa` Claude-hosted for v1.0.0. Codex is a subject under test, not a duplicated
    orchestration package. A successful managed Codex path is release evidence; a Codex-hosted copy of QA is not.
02. **Four evidence lanes.** Classify each retained contract as `automated-suite`, `clean-wheel-smoke`,
    `human-acceptance`, or `extended-exploratory`. A feature is represented when its release owner is explicit; it does
    not need another manual checklist matrix.
03. **Exact artifact first.** Build once, require the invoking host QA package to match that wheel, install the exact
    wheel into an isolated environment that cannot import the checkout, and record wheel and driver digests.
    Source-container QA remains useful for development but cannot be the distribution gate.
04. **Bound deterministic work.** Hard-cap the blocking lane at 12 included human checkpoints and 8 paid model
    completions. Count each worker/round, prompted managed-session turn, enrollment probe turn, and AI-curation call
    separately; exclude the Claude-hosted checklist driver and report it separately. Record end-to-end duration, with 45
    minutes as a review threshold rather than a correctness gate.
05. **Repository-owned runtime matrix.** Store the pinned Claude/Codex pair and probe evidence in
    `src/skills/qa/resources/runtime-matrix.json`. Establish both pins with fresh release probes; choose Codex at or
    above the proxy floor and raise the general-probe ceiling to the validated version in the same change. Exercise
    `latest` in a separately labelled compatibility lane whose failure does not rewrite the pinned verdict.
06. **Preserve deterministic bookkeeping.** Prefer checklist/resource changes that do not alter the state-machine
    contract. If the selection model requires a state-script change, update both copies and their parity/behavior tests
    in the same commit.
07. **Make Codex delivery evidence deterministic.** The blocking live journey uses the default `initial-message`
    delivery. Real enrolled hook firing and staged hook-delivery assertions remain required automated-suite evidence. An
    optional enrolled extended run may test `hook` delivery only when success is the expected result; trust-recovery
    output is negative evidence, never an alternative pass.
08. **Preserve section addressing.** Add v1.0.0 probes only by appending steps to their related sections 0-20. Do not
    insert, renumber, or create section 21+, so category and `--from`/`--to` meanings remain stable.
09. **Ratified v1.0.0 delta closure (invalidated 2026-08-31).** The maintainer initially chose not to repeat unaffected
    paid and human steps after the synchronized 2026-08-30 run. That run completed every blocking step with exact wheel,
    driver, and pinned-runtime identity, and every non-pass result was classified. Its non-pass results were closed with
    direct execution of each failed or skipped block, automated coverage of the sole product delta, and exact-wheel/
    driver verification of the rebuilt candidate. The saved run's native verdict remains `fail`; the decision was
    composite evidence, not a synthesized passing report. Its own terms required any later product or packaged QA change
    to invalidate the exception and require a new complete pinned run. Post-closure product and packaged-QA fixes on
    2026-08-31 triggered that condition, so this exception is now historical evidence and may not close the release
    gate.
10. **Standalone Claude skill identity.** Forge remains a direct filesystem installer, not a Claude plugin. Every
    `.claude/skills/<name>/SKILL.md` therefore carries `name: <name>` and is invoked as `/<name>`. A `/forge:<name>`
    namespace would require a real plugin manifest and lifecycle; frontmatter alone cannot create it.
11. **Final RC evidence disposition.** Accept the 2026-09-01 pinned run as the release gate under one explicit,
    non-generalizing budget exception: its native metrics record the eight annotated paid operations, while the report
    separately discloses one additional prompted completion during step 10.7. Preserve that discrepancy as nine actual
    subject completions; do not rewrite the report or relax the eight-completion contract for future runs. The run's
    stale 10.7 editor wording and 4.18.1's unexercised manual contrast are accepted documentation/coverage limitations,
    not product failures: durable notes-overlay behavior and required-ZDR direct callers remain covered by their design
    and automated owners. Board-only disposition does not invalidate the exact wheel or packaged driver.

## Scope

### 1. Restore checklist truth

- Fix every known inconsistency above and perform one complete assertion-to-command audit across all 21 sections.
- Retag only `src/skills/qa/resources/checklist.md` for the release. Recompute its `test-count` mechanically after edits
  and make stale metadata a test failure rather than review trivia.
- Remove historical phase names when they no longer explain a current user-visible contract.
- Align the report template, category names, skip propagation, and cleanup language with the resulting section set.

### 2. Assign coverage and remove duplicate matrices

Create a release coverage map beside the checklist or report contract. Each current feature names its authoritative test
command/path and, only when needed, its clean-wheel or human seam.

Trim these areas:

- Replace minimal, structured, full, and AI-curated live resume variants with deterministic
  `session transfer regenerate --strategy ...` inspection. Keep one live transfer delivery and one editor checkpoint.
- Keep one same-directory native fork and one cross-worktree transfer fork. These are different mechanisms; do not
  collapse both into one handoff test.
- Keep one portable skill invocation and one representative workflow frontend. Remove repeated live review, understand,
  panel, consensus, debate, and analyzer permutations from the blocking lane.
- Keep one rendered status-line review. Assert raw ANSI, breadcrumb, config variants, fixture costs, and lazy-source
  behavior automatically.
- Replace synthetic hook and direct-command matrices with their existing unit/integration owners. Keep one real Claude
  lifecycle hook, one live Codex preflight/`initial-message` seam, and the positive automated real-Codex hook owner.
- Automate editor, cap, header, logging, and confirmation checks that have deterministic process/file/output evidence;
  retain one representative interaction for each distinct UX mechanism.
- Move the three-session planner -> supervisor -> executor demonstration to the extended lane. The blocking gate uses
  the existing deterministic supervisor E2E and bounded real-Claude supervisor smoke.
- Remove exact template/package inventory assertions from human acceptance. Pin those catalogs through compiler,
  installer, and clean-wheel tests.

### 3. Represent the v1.0.0 product surface

| Surface                              | Blocking evidence                                                                     |
| ------------------------------------ | ------------------------------------------------------------------------------------- |
| Managed Claude lifecycle             | one clean-wheel managed session, real SessionStart/Stop evidence, transcript artifact |
| Managed Codex lifecycle              | successful preflight plus one managed start/resume turn and recorded thread state     |
| Model-first routing                  | clean-wheel `--model` route resolution plus `session model show/history` evidence     |
| Artifact authority                   | existing real-runtime enforcement test plus a clean-wheel set/show/deny smoke         |
| Native adoption and store repair     | targeted integration plus clean-wheel preview/apply CLI round trips                   |
| Rewind and ancestry depth            | existing native-contract Docker coverage; no repeated manual launches                 |
| Consumer lanes                       | live CLI set/show/clear and API/unknown/proxied evidence; automated keyless billing   |
| Policy single-source modes           | installed `--file` and piped `--diff` checks plus zero/two-source rejection           |
| Backend lifecycle and provider trace | backend/provider integrations plus installed list/show/explain surfaces               |
| Extension lifecycle                  | exact-wheel enable/status/sync/runtime-disable/cleanup/uninstall preservation         |
| Transfer strategies                  | deterministic generated-context matrix plus one human-visible delivery                |

The coverage map must include direct test references, not only feature names. Existing owners include:

- `tests/integration/core/test_codex_session_start.py`
- `tests/integration/docker/test_real_claude_hooks.py`
- `tests/integration/docker/test_session_routing.py`
- `tests/integration/docker/test_real_authority.py`
- `tests/integration/docker/test_adopt_native_conversation.py`
- `tests/integration/docker/test_rewind_native_contract.py`
- `tests/integration/backend/test_backend_cli.py`
- `tests/integration/proxy/test_provider_trace_e2e.py`
- `tests/src/core/usage/test_billing.py`

### 4. Add an exact-wheel QA lane

- Accept a specific prebuilt wheel or produce one once and pass its resolved path and digest into the QA environment.
- Give release QA a distinct `forge-qa-release` image identity. Keep editable integration shell/Python runners aligned
  with each other, but never let the wheel-backed QA image reuse their full tag or revision-only cache identity.
- Install it into a clean venv/tool environment outside `/forge`; run from `/workspace` with no checkout entry on
  `sys.path`.
- Assert the installed version, distribution metadata, `importlib.resources` extension inventory, CLI entry point, and
  runtime-loaded files before feature checks.
- Exercise the existing clean-wheel LiteLLM start/health/stop smoke through `scripts/test-wheel-runtime.sh`.
- Record install method, wheel filename, SHA-256, Forge version, Claude version, and Codex version in the report.
- Keep source checkout access only where a test fixture explicitly needs it; it must not satisfy imports or extension
  discovery for the installed-product lane.

### 5. Synchronize maintainer documentation

Update `docs/design_installation.md` and `docs/developer/testing_guidelines.md` if evidence lanes, invocation defaults,
runtime pins, artifact ownership, or report semantics change. Update end-user material only when execution changes a
user-facing install or recovery path.

## Human Acceptance Set

The blocking lane should need human judgment only for these distinct seams:

1. one hidden credential entry;
2. one editor and one destructive confirmation;
3. one rendered status-line review;
4. one managed Claude lifecycle with real hook output;
5. one same-directory native continuation;
6. one cross-worktree transfer continuation;
7. one managed Codex `initial-message` turn;
8. one portable skill plus one representative multi-worker workflow; and
9. final preservation-aware uninstall/cleanup review.

Combine checkpoints when one live journey produces several pieces of evidence. Do not spend another model call merely to
inspect a file or JSON record that the CLI can validate directly.

## Out of Scope

- A Codex-hosted clone of `/qa`.
- Replacing the self-contained state scripts with imports from the Forge package or repository checkout.
- Turning QA into the owner of exhaustive unit, malformed-input, concurrency, security, or rollback matrices.
- Making unpinned `latest` client behavior part of the reproducible v1.0.0 verdict.
- Changing product behavior solely to make an obsolete checklist assertion pass.

## Risks

- **False confidence**: a shorter checklist can hide coverage unless every removed assertion names its automated owner.
- **Artifact shadowing**: `/forge`, an editable venv, or `PYTHONPATH` can silently satisfy imports in the wheel lane.
- **Paid-run flakiness**: live multi-session demonstrations can fail for provider variance rather than Forge behavior.
- **Runtime drift**: host-derived or `latest` client versions make two release runs incomparable.
- **State drift**: a new selection annotation can break resume/prerequisite behavior if only one state-script copy
  changes.
- **Cleanup damage**: broader release fixtures must retain the existing marker, path, ownership, and report-preservation
  boundaries.

## Acceptance Tests

| Test                             | Fixture                                                          | Assertion                                                                                    | Test File                                                                                          |
| -------------------------------- | ---------------------------------------------------------------- | -------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| Checklist metadata truth         | all QA section fragments                                         | parsed assertion total equals the index count; every step has one supported execution class  | `tests/src/skills/test_qa_checklist_contract.py` (new)                                             |
| State-script parity              | QA and walkthrough packaged copies                               | only the two approved identity lines differ; both execute the full behavior matrix           | `tests/src/skills/test_walkthrough_state.py`, `tests/src/skills/test_walkthrough_state_parity.py`  |
| Runtime matrix                   | repository matrix plus runtime preflight fixtures                | both pins have release-baseline evidence; Codex meets its proxy floor and validated ceiling  | `tests/src/skills/test_qa_checklist_contract.py`, `tests/src/core/runtime/test_codex_preflight.py` |
| Exact wheel isolation            | prebuilt RC wheel, host QA driver, checkout also present         | driver matches the wheel; imports and resources resolve from the wheel, never `/forge`       | `tests/integration/docker/test_qa_release_artifact.py` (new)                                       |
| Managed Claude hook              | clean-wheel project and real Claude                              | session confirmation and transcript artifact are written by real lifecycle hooks             | `tests/integration/docker/test_real_claude_hooks.py`                                               |
| Managed Codex turn               | authenticated Codex and clean Forge project                      | preflight passes; default initial-message start/resume records the thread                    | `tests/integration/core/test_codex_session_start.py`                                               |
| Codex hook delivery              | enrolled real runtime plus staged receipt                        | real hook firing and staged delivery pass positively; recovery output is not a pass          | `tests/integration/docker/test_real_authority.py`, `tests/integration/docker/test_policy_hooks.py` |
| Model route evidence             | direct and proxy-capable catalog fixtures                        | explicit model selects the expected route; show/history report the committed event           | `tests/integration/docker/test_session_routing.py`                                                 |
| Authority enforcement            | advisory and producer sessions on both runtimes                  | covered mutation is denied or allowed according to role and journaled truthfully             | `tests/integration/docker/test_real_authority.py`                                                  |
| Session continuity matrix        | native, transfer, rewind, adoption, and repair fixtures          | each mechanism keeps its distinct state/artifact contract without repeated human launches    | existing targeted session Docker/integration tests                                                 |
| Backend and trace operator paths | authenticated backend plus one traced request                    | lifecycle commands succeed and trace list/show/explain join the request                      | existing backend/provider-trace integrations                                                       |
| Runtime budget                   | selected blocking steps plus complete QA report                  | human checkpoints are at most 12 and paid model completions are at most 8                    | `tests/src/skills/test_qa_checklist_contract.py` (new)                                             |
| Duration evidence                | complete blocking QA report                                      | end-to-end elapsed time is recorded; over 45 minutes requires explicit review, not test fail | `tests/src/skills/test_qa_checklist_contract.py` (new) plus recorded RC evidence                   |
| Clean uninstall                  | wheel-installed Claude/Codex ownership plus unrelated user bytes | selected Forge ownership is removed and unrelated content remains byte-identical             | `tests/integration/docker/test_installer.py`                                                       |

## Verification Requirements

- Focused checklist/state/compiler/profile tests.
- `make test-unit` and `make test-regression`.
- Targeted integration tests required by the session, hook, Codex, proxy, backend, installer, and authority changes;
  Codex real-runtime owners must observe CLI `0.149.1` before the pin is release-validated.
- `uv build` followed by `scripts/test-wheel-runtime.sh` and the new exact-wheel QA lifecycle.
- One complete pinned-runtime blocking QA run with saved report and artifacts. Accepted Decision 9 originally closed the
  post-run repairs with a bounded evidence bridge, but subsequent product and packaged-QA fixes invalidated that
  exception. A fresh complete run against the rebuilt exact wheel is required.
- One separately labelled `latest` compatibility run when network/runtime availability permits.
- `make pre-commit`, Markdown link checks, file-size checks, and `git diff --check`.

## Resolved Implementation Choices

- `--extended` is a QA-only selection layer over evidence annotations. The two parity-locked state scripts remain
  byte-unchanged because selection does not alter their parser, state, resume, or report commands.
- Release sign-off consumes an explicit `--wheel <path>`. Omitting the flag builds one development wheel for local QA,
  records it as `development-build`, and cannot produce a release-pass verdict.
- `src/skills/qa/resources/runtime-matrix.json` owns the pinned pair: Claude Code `2.1.245` and Codex CLI `0.149.1`.
  Codex `0.149.1` resolves the former proxy-floor/probe-ceiling conflict; `latest` remains non-blocking.
