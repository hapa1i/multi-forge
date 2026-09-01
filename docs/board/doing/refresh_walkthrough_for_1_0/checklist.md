# Checklist: Refresh the walkthrough for v1.0.0

**Card**: [card.md](card.md).

**Lane**: `doing/` -- accepted and activated on 2026-09-01.

**Execution branch**: `test/refresh-walkthrough-for-1-0`.

**Activation base**: `7c6847dd` (`main`, 2026-09-01).

## Current Focus

The first complete default run exercised all 43 steps and found one keyed-registry checklist bug. Its otherwise healthy
managed lifecycle also exposed a deeper isolation flaw: Claude Code ignored Forge's sandbox-only `CLAUDE_HOME`, so the
child borrowed hooks from the maintainer's real user settings and left native transcripts outside Forge's cleanup path.
The corrected checklist, launcher boundary, cleanup targeting, and delete preview now pass the full automated and
clean-wheel verification sweep.

Install/sync the exact amended candidate wheel, rerun `--setup-only` and the complete default report, exercise
interruption/resume, and review the saved evidence with the maintainer. Keep the card in `doing/` until those live
checks pass and the closeout is approved.

## Execution Guardrails

- The walkthrough is an educational Day 1 journey, not a second release-QA matrix. Keep only checks that teach a user
  outcome or prove the host sandbox; map exhaustive behavior to automated owners.
- Keep `/walkthrough` Claude-hosted for v1.0.0. Codex is an optional subject under test, not a copied frontend or state
  machine.
- The packaged `setup-test-repo.sh` is the only mutation allowed before wrapper gates exist. After setup, every mutating
  or Forge CLI command run by Session A goes through packaged `run-in-repo.sh`. Commands shown to a user in the
  already-sandboxed Terminal may use bare `forge` only after that shell verifies the walkthrough marker and its isolated
  home variables; other direct host commands remain read-only.
- Preserve real `HOME` and Claude's native config root for installed-tool, auth, and transcript reachability while
  isolating `FORGE_HOME`, Forge's `CLAUDE_HOME`, and `CODEX_HOME`. Managed Claude launches must exclude the real user
  settings source and load sandbox hooks explicitly; cleanup may target only the fixed walkthrough transcripts in the
  captured native store. An explicit `--codex-auth <path>` may copy only that regular file into the sandboxed Codex
  home; never print credential values, read a native Codex store implicitly, or copy auth material into reports.
- Keep sections 0-13 and cleanup section 13 stable. Retain an existing step id when its teaching outcome remains; retire
  rather than reuse an id for a different assertion, and append new ids within the relevant section.
- Keep the two self-contained `walkthrough-state.py` copies unchanged unless their shared parser/state behavior truly
  must change. Any such change updates both copies and the full parity/behavior suite in the same commit.
- Treat `option: codex` and `option: sidecar` as driver-owned modifiers over the parser's existing generic
  `annotations[]` output. Keep automated evidence ownership in the journey map rather than overloading QA's
  evidence-selection lanes.
- Human and paid-operation counts are hard static limits for the default selection. Duration is measured evidence with a
  review threshold, not a provider-variance correctness gate.
- If execution exposes a product defect, reproduce it independently and add a regression before fixing it. Do not change
  product behavior merely to preserve stale walkthrough prose.
- Keep the standard test targets green at every committed slice; do not leave contract tests red until a later phase.

## Proposed Default Journey Budget

| Section   | Teaching outcome                             | Default human checkpoints | Default paid operations |
| --------- | -------------------------------------------- | ------------------------- | ----------------------- |
| 0-6       | sandbox, enablement, mental model, route     | 1                         | 0                       |
| 7         | launch the managed parent and inspect status | 1                         | 0                       |
| 8         | direct commands and one policy interaction   | 2                         | 1                       |
| 9-10      | clean exit, artifacts, search, and telemetry | 1                         | 0                       |
| 11        | fresh continuity and deterministic incognito | 1                         | 1                       |
| 12        | optional Codex/sidecar chapters              | 0                         | 0                       |
| 13        | preservation-aware cleanup review            | 1                         | 0                       |
| **Total** | **default path**                             | **7**                     | **2**                   |

The unit for paid work is one intentional subject-under-test completion: one prompted Claude/Codex turn, upstream
provider smoke request, or AI-curation call. Direct commands intercepted before the model, launch-without-prompt, and a
no-op runtime fixture count as zero. The optional Codex chapter may add one structured-context headless Codex turn;
sidecar adds human windows but no completion unless its instructions explicitly ask for a prompt.

## Phase 0 -- Ratify the Journey Contract

- [x] Ratify direct Claude as the default model-first path: create `walkthrough-demo` with
  `--model claude-haiku-4-5 --no-proxy --no-launch`, then launch it with `forge session resume walkthrough-demo`.
  **Assertion**: the default tour requires no OpenRouter key, shows durable canonical route intent before launch and
  committed direct-route evidence only after managed resume, and never calls a bare `forge claude start` while claiming
  managed state.
- [x] Keep proxy education deterministic and display-only in default section 6: explain that ordinary `proxy start`
  proves local health and `--smoke-test` verifies upstream connectivity. **Assertion**: neither command is executed; the
  distinction is taught without adding a provider credential or paid request, and a live proxy remains QA or explicit
  user follow-up.
- [x] Keep incognito in the default journey with the existing no-op Claude-fixture pattern. **Assertion**: users see the
  ephemeral lifecycle and absence of manifest/index state after exit without another human window or model completion.
- [x] Add `--codex` as an optional chapter and choose one headless managed turn with `--strategy structured` and
  explicit `--context-delivery initial-message` after a successful `forge runtime preflight codex`. Accept inherited
  `CODEX_API_KEY`/`CODEX_ACCESS_TOKEN` or one explicit `--codex-auth <path>` copied into the isolated Codex home; never
  import native stored auth implicitly. **Assertion**: readiness failure is actionable and never reported as runtime
  success; hook enrollment is reported separately and does not block initial-message delivery; the ready path adds at
  most one paid operation and no interactive TUI or enrollment-verification checkpoint.
- [x] Add explicit `/walkthrough --from <section-or-step>` resume rather than guessing a restart point. **Assertion**:
  resume requires an existing state file from the same checklist version and option set, runs the existing `validate`
  command, clears the selected suffix, and refuses changed/unverified prefix evidence with `--reset` recovery.
- [x] Keep the v1.0.0 driver skill-owned and defer any shared Forge CLI or Codex-facing frontend to a new post-release
  card. **Assertion**: this card adds no second checklist, cross-skill import, or product CLI solely to host the tour.
- [x] Ratify the budget above: at most seven default human checkpoints and two default paid operations, with eight/three
  retained as hard ceilings. **Assertion**: contract tests count annotations mechanically; optional chapter counts are
  reported separately; 30 minutes is the target and an overage requires a recorded review rather than changing
  pass/fail.
- [x] Keep `<!-- option: codex -->` and `<!-- option: sidecar -->` steps in section 12 and cleanup in section 13.
  **Assertion**: the skill driver reads the parser's generic annotations without changing shared parser behavior;
  `--codex` and `--sidecar` may be combined; option-gated omissions are labelled `not selected` rather than failures;
  and cleanup remains selected for every normal, optional, failed, interrupted, or resumed path.
- [x] Ratify the clean-wheel boundary without duplicating QA's artifact verifier: automated integration binds the exact
  wheel to its installed package/scripts; the final human run starts only after that candidate is installed/synced and
  records the answering distribution plus package-marker digest. **Assertion**: checkout resources cannot satisfy the
  clean-wheel owner, while the walkthrough itself remains an educational frontend rather than a second release gate.

## Phase 1 -- Make Checklist Drift and Budgets Testable

- [x] Add `tests/src/skills/test_walkthrough_checklist_contract.py` against the real packaged checklist and parser.
  **Assertion**: declared assertion count equals parsed count; section/step ids are unique and ordered; every step has
  exactly one execution class; prerequisites name earlier selected steps; and execution, requirement, option, and
  paid-operation annotations use the ratified vocabulary.
- [x] Map each retained step to an explicit human or automated evidence owner in `journey-map.md`, and give each
  intentional model call a `paid-operations` annotation. **Assertion**: journey-map coverage is complete without reusing
  QA's evidence-selection lanes; the mechanically derived default selection stays at or below eight human checkpoints
  and three paid operations; and optional Codex and sidecar totals are separately reproducible.
- [x] Add a compact `src/skills/walkthrough/resources/journey-map.md`. **Assertion**: every default and optional chapter
  states the user question it teaches, its human seam, its automated owner, its flag/prerequisite, and why removed
  inventory/migration/schema checks do not belong in the default tour.
- [x] Move brittle walkthrough-content assertions out of `tests/src/review/test_skill_content.py`. **Assertion**:
  removing the long step 11.5 passport exercise does not weaken passport behavior because `tests/src/cli/test_memory.py`
  and `tests/src/session/test_passport.py` remain authoritative; walkthrough tests assert the new educational contracts,
  not a copied implementation matrix.
- [x] Pin the declared checklist version, `last-updated`, `aligned-with: v1.0.0`, total assertions, default checkpoint
  count, and default paid count. **Assertion**: changing content or annotations without updating metadata fails the new
  contract test.
- [x] Preserve state-script parity. **Assertion**: if no parser behavior changes, both copies remain byte-identical to
  their activation versions; otherwise both execute the complete state suite and differ only in the two approved
  identity lines.

## Phase 2 -- Simplify the Driver and Add Honest Resume

- [x] Extend the argument contract to `--setup-only`, `--reset`, `--report`, `--from <id>`, `--codex`,
  `--codex-auth <path>`, and `--sidecar`. **Assertion**: `--codex-auth` requires `--codex`; unknown, duplicate-value, or
  incompatible arguments fail before setup mutation; usage and examples use the standalone `/walkthrough` selector.
- [x] Split fresh and resumed initialization. **Assertion**: a fresh run initializes with `--force`; `--from` never
  overwrites first, validates the existing state, preserves verified prefix results and captured variables, and clears
  only the requested suffix.
- [x] Keep `--setup-only` small but prove the generated sandbox. **Assertion**: after setup it executes one packaged
  `run-in-repo.sh true` probe so all six gates are exercised, then stops before checklist initialization, installs, or
  live-runtime work.
- [x] Bind resume to checklist and option identity. **Assertion**: a checklist-version mismatch, changed/unverified
  prefix, or changed `--codex`/`--sidecar` selection refuses before commands run and names `/walkthrough --reset`;
  adding `--report` alone may resume because it changes artifact capture, not subject coverage.
- [x] Make Codex auth ingress explicit and resumable. **Assertion**: `--codex-auth` resolves exactly one regular file,
  makes sandboxed `$CODEX_HOME` mode `0700`, copies the file as mode-`0600` `auth.json` only after sandbox validation,
  and records only `explicit-file`, `environment`, or `none`. Explicit-file mode scrubs competing Codex auth environment
  variables for Codex probes/turns; `--from` requires the preserved copy to remain a regular mode-`0600` file; reset
  removes it; and driver-generated state, reports, and logs contain no source path, credential bytes, or auth-file copy.
- [x] Make expected installed assets resume state, not stale-install evidence. **Assertion**: `--from` validates
  progress before any reset prompt and continues with the existing sandbox installation; a fresh invocation may still
  offer a reset when unmanaged prior artifacts make its starting state ambiguous.
- [x] Route option-gated section-12 steps from their annotations. **Assertion**: the default run does not probe Docker
  or Codex; the skill interprets `option: codex` and `option: sidecar` from existing generic parser output; each
  explicit flag enables only its chapter; missing optional infrastructure produces an honest not-selected or unavailable
  result; and section 13 always executes without changing either state-script parser.
- [x] Make the opening narration describe the two-window default accurately: Session A guides, one sandboxed Terminal
  hosts the managed Claude child, and extra windows are introduced only by the sidecar option. **Assertion**: no prose
  says local scope owns runtime hooks or that a sessionless launcher has a Forge session manifest; before the first bare
  `forge` command, the Terminal proves its walkthrough marker and isolated `FORGE_HOME`, `CLAUDE_HOME`, and
  `CODEX_HOME`.
- [x] Record run start/end timestamps, selected options, declared human/paid budgets, and elapsed seconds in report
  mode. **Assertion**: the saved report distinguishes selected failures from option-gated omissions and marks a duration
  above 30 minutes for review without synthesizing a failure.
- [x] Keep report artifacts outside the sandbox and cleanup scope. **Assertion**: state, selected options, step logs,
  debug-log snapshots, final logs, package identity, and transcript claim survive successful and failed cleanup without
  copying credentials.

## Phase 3 -- Rebuild the Default Day 1 Journey

- [x] Reduce sections 2-3 to `extension doctor`, user-scope Claude runtime enablement, local project enablement, and a
  concise `extension status`/manifest summary. **Assertion**: the default path proves user runtime hooks plus local
  status-line/project assets without fake Codex binaries, exact package counts, legacy migration, or directory diffs.
- [x] Replace mtime-only orientation with a quiet real-system snapshot that records existence, type, mode, and content
  or tree digests for the six protected Claude/Codex targets. **Assertion**: later comparisons detect nested content
  changes without printing source bytes, settings values, auth data, or unrelated filenames into the report.
- [x] Teach managed versus bare launch before creating a session. **Assertion**: narration names manifests, lifecycle
  hooks, artifacts, continuity, search, and telemetry as managed-session behavior, while `forge claude start` and
  `forge codex start` are accurately described as sessionless proxy launchers.
- [x] Teach local proxy health versus upstream validation as display-only narration in section 6. **Assertion**: the
  walkthrough displays `forge proxy start <id>` versus `forge proxy start <id> --smoke-test`, states that the latter
  requires credentials and may incur provider cost, executes neither command, and leaves a live request to explicit user
  follow-up.
- [x] Create the managed parent through the ratified model-first command and inspect
  `forge session model show walkthrough-demo --json`. **Assertion**: the typed `claude-haiku-4-5` alias is stored and
  reported as canonical `claude-haiku-4-5-20251001`; pre-launch `route_intent.kind` is `direct`, template/proxy id are
  null, and `route_commit` is null; the command creates no model completion.
- [x] Merge parent launch and status-line review into one guided checkpoint. **Assertion**: the user runs
  `forge session resume walkthrough-demo`, sees the `walkthrough-demo` status line, and an immediate
  `session show --json` reports non-null `confirmed_at` with `confirmed_by` matching `hook:SessionStart:*`. A
  post-resume `session model show --json` reports supported committed direct-route evidence; the pre-seeded Claude id is
  correlation data, not proof that launch occurred.
- [x] Merge read-only in-session orientation into one guided checkpoint using `%help` and `%session model show`.
  **Assertion**: both commands are intercepted as direct commands, show the current managed session/route, and consume
  no model completion.
- [x] Keep one policy interaction as the parent conversation's single prompted turn. **Assertion**: the visible deny
  names the configured policy intent, the model takes or requests a compliant path rather than silently bypassing it,
  and the step is annotated as one paid operation.
- [x] Exit the managed parent cleanly in one guided checkpoint and inspect only user-facing evidence. **Assertion**:
  `session show --json` names a transcript path that exists after exit, the transcript artifact and search results all
  resolve `walkthrough-demo`, and no assertion reads a raw manifest field when a stable CLI surface exists.
- [x] Add `forge telemetry activity walkthrough-demo` and `forge telemetry costs show`. **Assertion**: activity reports
  the policy deny in the operation-outcomes pane and explains that the main interactive Claude harness does not emit
  model-call telemetry, so its model-calls pane may honestly be empty or sparse. The costs view is explained as
  proxy-scoped and reports empty/zero/unavailable rather than inventing direct-session spend or billing provenance.
- [x] Add the fresh continuity loop using deterministic `structured` context. **Assertion**: transfer regeneration/show
  exposes the parent's assembled context, `resume --fresh --child-name walkthrough-continuation` launches one child, and
  one parent-grounded question demonstrates delivery without an AI-curation call.
- [x] Add automated incognito ephemerality after continuity. **Assertion**: a temporary no-op Claude launcher exits
  zero, the named incognito session disappears from list/index/disk, and cleanup remains idempotent if the fixture
  aborts.
- [x] Replace the long memory-passport exercise with a short further-reading orientation. **Assertion**: users learn
  that project memory and session transfer solve different continuity problems and receive current guide/CLI pointers
  without editing or validating frontmatter in the default tour.

## Phase 4 -- Bound Optional Runtime Chapters

- [x] Add a Codex readiness step gated by `--codex`. **Assertion**: `forge runtime preflight codex --json` runs through
  the sandbox wrapper without `--proxy`; a ready result proceeds, while missing auth or binary prints its exact recovery
  and does not claim a successful Codex runtime. `proxy_responses` reports `native_direct`; `hook_seam` is reported
  separately; missing enrollment is not treated as a blocker for initial-message delivery; and a login present only in
  the native Codex home remains invisible rather than being imported implicitly.
- [x] Add one structured-context headless Codex continuation. **Assertion**: the ready path uses a managed
  `session start --runtime codex --resume-from walkthrough-demo --strategy structured` with
  `--context-delivery initial-message` and `--task ...`, records the Codex thread id and response, consumes at most one
  completion and no enrollment probe, removes its walkthrough session, and confines auth/rollouts to the sandboxed Codex
  home without modifying native auth.
- [x] Keep sidecar behind `--sidecar` and trim it to launch, one container/mount observation, and exit/cleanup.
  **Assertion**: Docker is never probed by default; selected sidecar steps name their prerequisites and human windows;
  foreign containers and listeners remain outside cleanup ownership.
- [x] Keep legacy migration, exact runtime-package inventory, passport internals, supervisor fan-out, and
  Claude-to-Codex interactive handoff discoverable as links or explicit follow-up commands rather than default
  assertions. **Assertion**: each points to a current end-user guide or automated owner and contributes zero default
  checkpoints.

## Phase 5 -- Make Interruption and Cleanup Safe

- [x] Inventory every walkthrough-owned resource: parent, continuation, incognito, optional Codex/sidecar sessions,
  proxies, containers, installation rows, transfer/search/artifact state, sandboxed Codex auth/rollouts, the fixed
  policy source target, fake binaries, and temporary files. **Assertion**: each has one idempotent cleanup owner and no
  cleanup command relies only on a volatile shell variable.
- [x] Make `--reset` reclaim owned runtime resources before discarding their state. **Assertion**: if cleanup cannot be
  proven, reset refuses with a resume/cleanup recovery rather than erasing manifests or registry rows and orphaning a
  live process.
- [x] Make section 13 safe from any interruption point and on repeated execution. **Assertion**: absent resources are
  success, known owned resources are removed, foreign same-port proxies/containers/installations are preserved, and a
  second cleanup run produces no failure or new mutation.
- [x] Route all cleanup mutations through `run-in-repo.sh` and register immediate traps for disposable host fixtures.
  **Assertion**: no direct `rm -rf`, temp directory, fake binary, or copied Codex auth file can escape the proven
  walkthrough root or survive a failing checklist block.
- [x] Preserve reports before destructive cleanup. **Assertion**: debug logs needed as evidence are snapshotted first,
  transcript claims remain outside the sandbox, and no report path is deleted by reset or section 13.
- [x] Extend sandbox and interrupted-cleanup regressions. **Assertion**: missing marker, unsafe canonical target,
  malicious `env.sh`, symlink alias, option mismatch, mid-run abort, stale progress, and foreign resource fixtures all
  fail closed; the valid generated repo still runs and cleans normally.

## Phase 6 -- Prove the Installed Package and Synchronize Docs

- [x] Add `tests/integration/docker/test_walkthrough_release_artifact.py` or an equivalently focused installer owner.
  **Assertion**: one supplied wheel is installed outside the checkout, installs the Claude walkthrough package into an
  isolated home, resolves every resource/script from that package, runs setup/index/report/cleanup smokes, and cannot
  import or read the checkout copy as its implementation.
- [x] Record package provenance for report mode. **Assertion**: the report identifies the answering Forge distribution,
  installed package path, and `.forge-package.json` tree digest; the exact-wheel integration records the wheel SHA-256,
  and the final-run procedure requires candidate install/sync plus a Claude restart before invocation.
- [x] Update `docs/design_installation.md` and `docs/developer/testing_guidelines.md`. **Assertion**: they describe the
  direct managed default, seven/two budget, `--from`, optional Codex/sidecar branches, explicit Codex auth ingress,
  report semantics, and unchanged Claude-only frontend/state-parity boundary. Design §D.1 defines `option: codex` and
  `option: sidecar` as driver-owned modifiers and keeps QA evidence-selection lanes distinct from walkthrough ownership
  mapping.
- [x] Update `docs/end-user/manual_testing.md`, `README.md`, `docs/end-user/README.md`, `docs/end-user/session.md`,
  `docs/end-user/transfer.md`, `docs/end-user/model_selection.md`, and `docs/end-user/skills.md` only where Day 1
  instructions changed. **Assertion**: examples use `/walkthrough`, managed `session resume`, current telemetry and
  transfer namespaces, and distinguish direct, proxied, bare, and managed launches without promising unavailable cost.
- [x] Retag the packaged checklist after content settles. **Assertion**: version, date, alignment, assertion total, and
  declared budgets match the parser/contract test exactly; no stale v0.1.0 or sessionless Session B claim remains.

## Phase 7 -- Verify the Candidate

- [x] Run the focused contract/state/content slice. **Assertion**: the walkthrough checklist contract, both state-script
  suites, skill-content tests, and new resume/report tests pass together.
- [x] Run sandbox and cleanup regressions. **Assertion**: all existing walkthrough regressions plus new interruption,
  option-identity, and idempotent-cleanup cases pass without skips.
- [x] Run targeted installer/session/hook/search/telemetry integrations required by the changed journey. **Assertion**:
  managed parent confirmation, structured fresh context, transcript/search ownership, direct-route reporting, incognito
  removal, optional Codex, and wheel-installed resources pass their authoritative owners.
- [x] Run `make test-unit`, `make test-regression`, `make build`, `./scripts/test-wheel-runtime.sh`, and the exact-wheel
  walkthrough integration. **Assertion**: all commands pass on the final implementation head; any skip or deselection is
  named and justified.
- [x] Run `make pre-commit`, Markdown links, file-size checks, and `git diff --check`. **Assertion**: all repository
  gates pass after formatting and generated token-count updates are reviewed.
- [ ] Install/sync the exact candidate wheel and run `/walkthrough --setup-only`. **Assertion**: the package-identity
  record matches the candidate installation, the sandbox is created outside the checkout, the packaged wrapper proves
  all six safety gates, and no checklist or live-runtime step runs.
- [ ] Run one complete default `/walkthrough --report`. **Assertion**: every selected default assertion passes with at
  most seven human checkpoints and two paid operations; duration is recorded against the 30-minute target; real-system
  digests match; and the saved artifacts identify the exact wheel-installed package.
- [ ] Exercise interruption/resume and repeat cleanup. **Assertion**: stop after the managed parent, resume from an
  exact later step with the same options, finish successfully, then rerun cleanup and prove no owned state remains and
  no foreign state changed.
- [ ] Exercise the optional Codex branch when release credentials/readiness are available. **Assertion**: either one
  genuine structured initial-message headless turn passes and records its thread through explicit-file or environment
  auth ingress, or the exact not-ready reason is recorded as optional compatibility evidence; hook enrollment is never
  required or claimed, and the branch never alters the default result. Sidecar remains covered by its targeted Docker
  owner.

### Automated Verification -- 2026-09-01

- The focused walkthrough contract, state, content, sandbox, cleanup, and CLI slice passed 402 tests. `make test-unit`
  passed with 10,024 tests and 117 deselected; `make test-regression` passed all 1,096 tests, including the generated
  Claude-launcher isolation regression.
- The amended-head targeted integration sweep passed 36 tests: 21 managed lifecycle, routing, hook, search, transfer,
  and activity owners; 13 sidecar lifecycle/mount owners; one real Codex start/resume owner; and the exact-wheel
  walkthrough package owner. The Codex test completed two real turns and the sidecar tests required no provider
  completion.
- `make build`, `./scripts/test-wheel-runtime.sh`, `make pre-commit`, and `git diff --check` passed. The amended locally
  built wheel SHA-256 is `bdd1c195d21bb80763ec82c71f69a6739b00ecbf435a9d0f8be9ef309443185c`.
- The exact-wheel owner installs outside the checkout, binds the answering distribution to the installed package tree,
  runs setup/index/report/cleanup twice, verifies protected-path preservation, and confirms `python -I` cannot import
  the checkout. This automated proof does not substitute for the unchecked Claude-hosted release-candidate runs above.

### Setup-only Attempt -- 2026-09-01

- The first Claude-hosted `/walkthrough --setup-only` attempt passed sandbox creation and all six wrapper gates, then
  stopped before checklist initialization because Claude's inherited `PATH` selected the checkout's editable
  `.venv/bin/forge`, not the candidate-wheel launcher. That is the intended clean-wheel refusal, so the setup-only gate
  remains unchecked until it is rerun from the installed candidate.
- The refusal exposed a diagnostic defect: the identity probe hashed a missing wheel-resource directory as the empty
  manifest. The probe now reports `answering_distribution_issue: editable-install`, emits no payload digest for that
  ineligible source, and explicitly forbids substituting checkout resources. Unit and exact-wheel integration coverage
  pin both the editable refusal and installed-wheel success paths.
- Installing the candidate then exposed a legacy local installation row that still attributed skills to Codex. Sync
  correctly refused because Codex packages have no local scope, but its recovery tip named only the separate user-scope
  install and could not repair the local row. The tip now names runtime-scoped local disable before sync, while
  retaining the user-scope Codex command as an optional second action.

### First Complete Default Attempt -- 2026-09-01

- The installed-package identity gates passed with payload digest
  `30c3101a1daaf777007f6de090c9415f779f5e79ab2c73e2b4867db6d42b8ee1`. The run completed all 43 steps with 123 pass, one
  fail, and 21 correctly unselected optional assertions; it observed exactly seven human checkpoints and two paid
  operations. Evidence is under `~/.forge/manual-testing/walkthrough/runs/20260901T211149Z/`.
- Step 3.3 failed because its Python block iterated keyed installation ids as if they were row objects. The corrected
  block validates the schema, summarizes `installations.values()`, and has an executable keyed-registry regression.
- The run's hook evidence came from the maintainer's pre-existing real Claude user settings: Claude Code uses
  `CLAUDE_CONFIG_DIR`, not Forge's sandbox-only `CLAUDE_HOME`. The generated launcher now pins the native binary,
  excludes the real user setting source, and supplies sandbox hooks through `--settings`; regression and exact-wheel
  probes pin this boundary. Native transcript cleanup uses the captured config root for only the fixed parent/child.
- The delete preview now distinguishes native Claude transcripts from retained Forge artifact snapshots. Artifact-tree
  survival after ordinary session deletion is intentional and final walkthrough cleanup owns it; the
  `compatibility-fallback` label is the designed schema for non-curated transfer strategies; and an empty shared
  `.claude/skills/` root is outside package-leaf ownership. Those three observations require no product behavior change.
- The 5,909-second duration was checkpoint wait time and is accepted as review-only evidence, not a correctness failure.
  This attempt cannot satisfy final acceptance because of its assertion failure and real-settings dependency; the
  amended exact wheel needs a fresh complete run.

## Acceptance Tests

| Test                  | Fixture                                                            | Assertion                                                                                                  | Test File                                                                                         |
| --------------------- | ------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| Checklist truth       | packaged walkthrough checklist                                     | metadata, ids, annotations, prerequisites, assertions, and budgets agree                                   | `tests/src/skills/test_walkthrough_checklist_contract.py`                                         |
| Default budget        | default selection without Codex/sidecar                            | at most 8 human checkpoints and 3 paid operations; target plan is 7/2                                      | `tests/src/skills/test_walkthrough_checklist_contract.py`                                         |
| Resume identity       | current and stale progress with changed options/checklist          | exact suffix clears; stale prefix/version/options refuse before mutation                                   | focused SKILL/content tests plus `tests/src/skills/test_walkthrough_state.py`                     |
| Managed parent        | model-pinned no-launch parent plus managed resume                  | SessionStart confirmation, direct route, status line, transcript, and search name one session              | walkthrough report plus targeted session/hook integration                                         |
| Ownership explanation | isolated user and local installs                                   | user owns runtime hooks; local owns status line/project assets; unrelated settings survive                 | installer unit/integration tests plus walkthrough assertions                                      |
| Model evidence        | `claude-haiku-4-5 --no-proxy --no-launch` then managed resume      | canonical intent is uncommitted before launch and supported direct evidence appears after resume           | session-routing integration plus walkthrough assertion                                            |
| Activity and costs    | one direct managed policy prompt                                   | operation outcome appears; model-call/cost gaps stay explicit and never invent direct-session spend        | telemetry unit/integration tests plus walkthrough assertion                                       |
| Fresh continuity      | exited parent, structured transfer cache, one child                | transfer show contains grounded parent context and child demonstrates receipt in one turn                  | transfer/session integration plus guided checkpoint                                               |
| Incognito cleanup     | no-op Claude launcher                                              | command exits successfully and leaves no manifest/index/directory                                          | session CLI/integration plus walkthrough assertion                                                |
| Optional Codex        | environment, explicit-file, native-home-only, and not-ready auth   | one initial-message turn records a thread or recovery is honest; native auth/enrollment/default unaffected | `tests/integration/core/test_codex_session_start.py` plus checklist branch                        |
| Interrupted cleanup   | owned and foreign runtime/install fixtures                         | reset/cleanup removes only owned resources and is repeatable after partial progress                        | new walkthrough regression coverage                                                               |
| Sandbox provenance    | unsafe roots, symlink aliases, malicious env, valid generated repo | unsafe targets execute nothing; valid sandbox remains functional                                           | `tests/regression/test_bug_o036_walkthrough_sandbox_provenance.py`                                |
| Clean-wheel package   | exact wheel with distinguishable checkout                          | installed driver/resources come from the wheel and report matching package identity                        | `tests/integration/docker/test_walkthrough_release_artifact.py` (new)                             |
| State parity          | QA and walkthrough state copies                                    | behavior suite passes for both and only approved identity lines differ                                     | `tests/src/skills/test_walkthrough_state.py`, `tests/src/skills/test_walkthrough_state_parity.py` |

## Closeout

- [ ] Review the complete implementation and final walkthrough evidence with the maintainer; close every finding or
  record an explicit accepted limitation before release sign-off.
- [ ] Add the completed-work entry to `docs/board/change_log.md`; promote only human-approved durable manual-testing or
  sandbox decisions through `docs/board/impl_notes.md`.
- [ ] Confirm design and end-user documentation describe shipped behavior, move the card to `done/`, and repoint every
  inbound board link to its final lane.
- [ ] Commit the reviewed implementation in a reviewable series, push the execution branch, open the PR with exact
  verification evidence, and merge only after the clean-wheel default walkthrough and required checks pass.
