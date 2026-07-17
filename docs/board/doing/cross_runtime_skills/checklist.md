# Execution checklist: `cross_runtime_skills`

**Branch**: `cross-runtime-skills` · **Card**: [`card.md`](card.md) · **Activated**: 2026-07-16

> **Execution approved 2026-07-16.** Implement and verify the ratified shape below, but keep this card in `doing/` after
> completion until the user reviews the result.

## Current focus

Execute the approved Axis 1 contract: a typed neutral compiler, runtime-specific skill targets and tracking, and the
portable skill tranche. Keep Axis 2 worker dispatch and all other explicit scope boundaries separate, and retain the
card in the active lane for post-implementation review.

## Scope boundary for review

**In scope for Axis 1:**

- A runtime-neutral authoring contract and capability vocabulary for Forge skills.
- Deterministic Claude and Codex/spec package compilation.
- Runtime-specific skill scopes, installation targets, tracking, sync, disable, status, and clean-install behavior.
- A reviewed first skill tranche followed by explicitly classified deeper migrations.
- Claude package fidelity and Codex-native discovery/invocation evidence.

**Out of scope unless Phase 0 explicitly changes it:**

- Axis 2 fan-out worker dispatch. `panel`, `analyze`, `debate`, and `consensus` still execute the existing `claude -p`
  workflow workers; runtime-neutral worker dispatch requires a separate card and engine contract.
- `walkthrough` and `qa`, which orchestrate Claude Code-specific interactive/manual-test behavior.
- Sidecar user-skill parity and Codex-in-sidecar. Preserve existing project-scoped Claude skill visibility through the
  mounted workspace; do not add host-user skill-home mounts or alter the Claude-only sidecar image/entrypoint. A
  runtime-aware container skill-staging model requires separate work.
- A family-by-runtime resource matrix. Runtime bindings must not be copied into every OpenAI/Gemini/Anthropic rubric.
- General plugin-marketplace distribution. Phase 0 must decide whether Forge's direct filesystem installer remains the
  delivery surface or whether a Codex plugin artifact is additionally warranted; it must not silently broaden Axis 1.

## Grounding verified 2026-07-16

- `src/skills/` contains 11 skills, and all 11 checked-in `SKILL.md` files currently use `name: forge:<skill>`.
- The coupling inventory is broader than the original "near-neutral" wording. `challenge` still uses `$ARGUMENTS`,
  Claude tool names, and the `/forge:` naming convention. `smoke-test` uses `${CLAUDE_SKILL_DIR}`, and its bundled
  script inspects Claude-specific install paths. They remain useful shallow-coupling candidates, not neutral artifacts.
- Current skill packages contain Claude-only frontmatter and body/resource tokens including `$ARGUMENTS`,
  `${CLAUDE_SKILL_DIR}`, inline `` !`forge ...` `` pre-steps, `Agent`/`Explore`, `subagent_type`, and `AskUserQuestion`.
  The inventory must scan the whole package, not only `SKILL.md`.
- `Installer.init()` still copies the `SKILLS` module under the single Claude target root. `installed.json` tracks files
  by target path under one installation row and has no explicit per-runtime skill-package model.
- `RuntimeSpec` still models runtime participation through `install_scopes`; it has no `skill_scopes` or equivalent
  per-feature capability.
- The current Agent Skills specification still requires a directory-matching lowercase/hyphenated `name`, defines the
  top-level fields `name`, `description`, `license`, `compatibility`, `metadata`, and experimental `allowed-tools`, and
  specifies relative file references from the skill root.
- The current Codex manual confirms repository discovery from `.agents/skills` on the CWD-to-repository-root chain, user
  discovery from `$HOME/.agents/skills`, admin discovery from `/etc/codex/skills`, duplicate-name non-merging, and
  optional `agents/openai.yaml` invocation policy. It now recommends plugins for reusable distribution beyond local or
  repository authoring; that recommendation must be reconciled with Forge's cross-runtime installer rather than ignored.
- Host `codex-cli 0.144.5` is available for a real discovery/invocation probe. A version banner warning about PATH-alias
  creation is environmental and does not prevent the version probe.

## Activation bookkeeping

- [x] Create branch `cross-runtime-skills` from clean, synchronized `main`.
- [x] Move the card with `git mv` from `proposed/cross_runtime_skills/` to `doing/cross_runtime_skills/`.
- [x] Update the card lane, branch, activation posture, closed-epic relationship, and checklist link.
- [x] Repoint the inbound board reference in `done/epic_global_forge_runtime/checklist.md` to the active lane.
- [x] **Human review gate:** user approved Phase 0 and execution on 2026-07-16, with a required review hold in `doing/`
  after completion.

## Phase 0 -- decisions and decomposition (blocking)

- [x] **Card shape:** decide whether Axis 1 remains one card or becomes `epic_cross_runtime_skills` with independently
  shippable member cards. If split, define member boundaries and sequencing, create the member cards, and update every
  link before production edits.
  - _Recommendation for review:_ coordinate neutral-authoring/compiler, installer/runtime/tracking, and skill-migration
    slices separately. They have distinct rollback and verification boundaries.
- [x] **Axis 2:** confirm fan-out worker-runtime dispatch is a separate proposed card. Record the boundary here and in
  that card; do not let Axis 1 imply that a Codex-hosted `panel` has Codex workers.
- [x] **Authoring source:** choose the single editable source shape, such as neutral `content.md` plus runtime adapter
  data, or a typed/annotated source parsed by the compiler. Reject any design that asks contributors to edit generated
  Claude and Codex `SKILL.md` files independently.
  - _Assertion:_ one author edit changes both packages through a deterministic build; generated artifacts identify their
    source and are never accepted as an independent source of truth.
- [x] **Generated-artifact policy:** decide whether runtime packages are built in memory during install, materialized in
  a package-data build directory, or checked in. Account for copy and symlink install modes: no tracked symlink may
  point into an ephemeral build directory.
- [x] **Capability vocabulary:** define the smallest neutral vocabulary for task arguments, read-only resource loading,
  packaged script execution/skill-root resolution, model family selection, exploration/subagents, invocation policy,
  user interaction, and Forge CLI calls. Treat executable resolution as a first-class binding rather than assuming it
  follows prose-link behavior. Specify which capabilities may degrade, which exclude a runtime, and which fail
  compilation.
- [x] **Adapter interface:** decide whether one typed adapter covers shallow frontmatter/path transforms and behavioral
  capability bindings. Keep runtime bindings outside model-family resources.
  - _Assertion:_ adding a runtime does not create `*-<family>-<runtime>.md` files.
- [x] **Runtime capability shape:** define `RuntimeSpec.skill_scopes` or an equivalent per-feature declaration rather
  than overloading `install_scopes`. Specify runtime values independently.
- [x] **Scope mapping and privacy:** ratify Codex `user -> $HOME/.agents/skills` and
  `project -> <forge_root>/.agents/skills`; reject or explicitly define Forge `local` for Codex. Never map personal
  local scope onto a shared/committed project directory.
- [x] **Delivery surface:** reconcile direct filesystem installation with the current Codex recommendation to use
  plugins for reusable distribution. Decide whether Forge remains the installer for locally built cross-runtime
  packages, additionally emits a plugin, or splits plugin distribution into later work.
- [x] **Name and invocation model:** ratify per-runtime names (`forge:<skill>` for Claude, directory-matching `<skill>`
  for Codex/spec) and define how users invoke each without promising a shared textual namespace that the runtimes do not
  support.
- [x] **Arguments:** probe explicit `$skill-name ...` task delivery under current Codex and define the neutral argument
  contract. Do not assume Claude's `$ARGUMENTS` substitution exists.
- [x] **Packaged script invocation:** from an arbitrary nested repository CWD, probe whether Codex exposes a selected
  skill-root variable, anchors relative executable paths to the selected package, or needs an installer/runtime-created
  absolute binding. Prove that `smoke-test` executes the exact installed user- or project-scope script without depending
  on the source checkout or process CWD. Classify its internal Claude-home probes separately from locating the script.
- [x] **Invocation policy:** map Claude `disable-model-invocation` semantics to Codex
  `agents/openai.yaml::policy.allow_implicit_invocation` only where behavior truly matches; document mismatches.
- [x] **Duplicate discovery:** define conflict behavior when the same built skill name exists at multiple Codex scan
  levels. Enable/sync must not create ambiguous duplicate selectors silently.
- [x] **First tranche:** choose it from a whole-package coupling inventory, not from the original near-neutral labels.
  Classify at least:
  - instruction/argument coupling (`challenge`),
  - script/path/install coupling (`smoke-test`),
  - behavioral rubric coupling (`review`, `review-docs`, `understand`),
  - Claude-worker workflow frontends (`panel`, `analyze`, `debate`, `consensus`), and
  - Claude-by-nature manual-test skills (`walkthrough`, `qa`).
- [x] **Live Codex probe:** on `codex-cli 0.144.5`, verify user and nested repository discovery, duplicate-name
  behavior, explicit invocation/task text, implicit-invocation policy, resource/script resolution, symlink behavior, and
  reload expectations. Build the reproducible harness under `scripts/experiments/codex-skills/`, following the
  `codex-hooks` precedent with a README, versioned preflight, named stages, and sanitized committed verdicts rather than
  raw captures.
- [x] Record all ratified decisions in the card, revise the later phases to match, and obtain explicit approval to lift
  the implementation hold. Reconcile the card's `${CLAUDE_SKILL_DIR}` Axis 1 row, **Slice by coupling depth**,
  **Non-goals / must-not-break**, and **Metric / falsifiable prediction** explicitly; none may retain the unproved
  `challenge`/`smoke-test` first-tranche commitment.

## Phase 1 -- characterize existing contracts before refactoring

- [x] Add a complete Claude package golden or structural manifest for all in-scope skills, including frontmatter,
  resources, references, scripts, executable modes, and profile gates.
  - _Assertion:_ the Claude compiler/adapter can be compared against today's installed package without omitting nested
    files or modes.
- [x] Characterize Claude `extension enable`, `sync`, `disable`, conflict, force, copy, symlink, project, local, user,
  and wheel-installed paths before changing the `SKILLS` module.
- [x] Build a machine-readable whole-tree coupling inventory with an explicit allowlist per runtime package.
  - _Assertion:_ a prohibited runtime-specific token in any nested runtime-neutral or Codex file fails validation with
    its path and rule; a deliberate Claude adapter token remains allowed only in Claude output.
- [x] Define separate emitted-package validation contracts at Forge's build boundary. Preserve and validate the current
  Claude-specific package shape; for Codex/spec output, enforce parent-directory/name equality, name and description
  limits, the closed Agent Skills top-level field set, metadata value shape, `allowed-tools` format, and required files.
  Validate reference containment/resolution, runtime-token isolation, and `agents/openai.yaml` separately as Forge
  portability policies.
- [x] Decide whether Forge calls `skills-ref` or owns a dependency-free validator. If external validation remains part
  of release verification, pin how it is installed and keep unit tests hermetic.
- [x] Characterize `installed.json` as a shared strict state contract before one logical module can produce files in
  multiple runtime targets. Inventory enable/update, sync, status, disable, strict `cleanup-project` row validation,
  `doctor`'s best-effort tracking-dependent choice of hook recovery command, and both hook-migration rewrite paths. Pin
  legacy, current, unsupported-newer, unknown-field, corrupt/unreadable, upgrade, uninstall, partial-conflict, and
  stale-file semantics before changing the schema.
  - _Assertion:_ `cleanup-project` preview remains side-effect-free and fails before mutation on unreadable state;
    `doctor` remains exit-zero and falls back to user-sync advice when tracking cannot be read. Runtime-package health
    remains on `extension status`; doctor does not claim to expose tracking degradation or `skill_packages`.

## Phase 2 -- neutral compiler and runtime adapters

- [x] Implement a dependency-light typed skill source/manifest and deterministic compiler with no installer I/O.
  - _Assertion:_ identical source + adapter inputs produce byte-identical paths, bytes, and modes in stable order.
- [x] Implement the Claude adapter first and prove fidelity against the Phase 1 contract.
  - _Assertion:_ every unchanged Claude skill remains behaviorally equivalent; required `/forge:<skill>` names,
    frontmatter, model-family selection, resources, and `Agent`/`Explore` behavior are preserved.
- [x] Implement the Codex/spec adapter with directory-matching names, spec-only top-level frontmatter, relative resource
  paths, and optional `agents/openai.yaml` policy/UI metadata.
- [x] Encode capability bindings through typed adapter data rather than string-replacement denylist passes.
  - _Assertion:_ unknown or unbound required capability fails compilation; it never leaks a Claude token into Codex
    output or silently deletes behavior.
- [x] Keep OpenAI/Gemini/Anthropic content variants runtime-neutral and shared across runtime builds.
- [x] Validate the entire emitted package after composition with its runtime-specific validator, including nested
  resources/references/scripts and `agents/openai.yaml`; reject a partial or invalid package before installer planning.
- [x] Produce actionable diagnostics naming skill, runtime, source path, capability, and recovery path.

## Phase 3 -- runtime capability, installer, and tracking lifecycle

- [x] Add the reviewed per-runtime skill-scope capability to `RuntimeSpec`, runtime-list JSON, and tests without
  conflating it with hooks or general extension participation.
- [x] Extend installer planning so one logical `SKILLS` request computes package eligibility explicitly over
  `(scope, runtime, profile, skill)` after module selection and produces only the reviewed runtime packages.
  - _Assertion:_ the plan shows runtime, scope, and exact target for each package; status never claims an unwritten
    runtime package.
  - _Assertion:_ exercise the scope × runtime × profile matrix with portable, full-profile-only, and runtime-exclusive
    skills. Existing-package preservation is runtime-specific and cannot make a package for another runtime eligible;
    every omission has an explicit policy reason rather than a silent skip.
  - _Assertion:_ persist the requested/managed runtime-package set; temporary runtime-binary absence during automatic
    re-enable or sync cannot make a tracked package stale or delete it, and explicit narrowing preserves omitted tracked
    packages with visible plan rows.
- [x] Install Codex user skills only under `$HOME/.agents/skills` and project skills under the selected Forge root's
  `.agents/skills`. Enforce the reviewed local-scope decision before any write.
- [x] Define selection UX explicitly: automatic installed-runtime detection, explicit `--runtime`, or a separate module.
  Missing Codex must not make an otherwise valid Claude install fail unless the user explicitly requested Codex.
- [x] Make tracking runtime-aware with an explicit legacy-read/current-write migration, preserving new runtime-package
  fields through installer and both hook-migration rewrite paths. Decide and test the schema bump and older-reader
  behavior; do not add fields under the current version by accident.
- [x] Preserve the no-write-on-known-conflict preflight contract across runtime targets, and define rollback/recovery
  plus the tracking commit point for mid-apply failures. A conflict in one target must have a defined outcome; Forge
  must not report an untracked half-install as complete.
- [x] Make `enable`, `sync`, `disable`, status, dry-run, force, and stale-file cleanup idempotent per runtime package.
- [x] Preserve copy and symlink semantics without symlinking to transient compiler output.
- [x] Detect existing same-name skills in Codex's scan chain, classify valid packages across all Forge tracking rows
  with consistent path normalization, and apply the reviewed duplicate policy without deleting user-owned files.
  Other-scope managed packages remain conflicts with scope-aware disable recovery; only untracked matches get
  remove-or-rename guidance.
- [x] Package neutral sources, adapters, validation data, scripts, and resources into wheel/sdist runtime data. Verify
  all reads through `importlib.resources` where required.
- [x] Extend `forge extension status` and, if approved, `extension doctor --json` with truthful runtime-skill state,
  discovery conflicts, and recovery guidance.
- [x] Apply project-compatibility enforcement to project-owned `.agents/skills` mutations while keeping user-global
  skill state outside an unrelated project's pin.

## Phase 4 -- migrate the approved skill tranches

- [x] Migrate the approved shallow tranche through the neutral source and both adapters; do not infer that `challenge`
  or `smoke-test` is eligible until its actual argument/path/script couplings have explicit bindings.
- [x] Prove each migrated skill under Claude before enabling its Codex package.
- [x] Prove each Codex package through explicit invocation; test implicit invocation only where policy permits it.
- [x] Migrate `review`, `review-docs`, and `understand` only after the exploration, model-family, argument, and resource
  capabilities are implemented and tested across every family variant.
- [x] Decide whether workflow-front-end skills install under Codex while clearly declaring their Claude worker
  prerequisite, or remain Claude-only until Axis 2 ships. Do not label them Codex-native while they require `claude -p`
  workers.
- [x] Keep `walkthrough` and `qa` Claude-only unless a later card designs a different runtime-neutral human-interaction
  contract.
- [x] Add per-skill compile/discovery/invocation coverage and a full-package prohibited-token scan.

## Acceptance tests

| Test                       | Fixture                                                             | Assertion                                                                                      | Test File                                                                                                     |
| -------------------------- | ------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| Claude package fidelity    | all in-scope source skills + Claude adapter                         | compiled files, modes, and behavior contract match the characterized Claude package            | `tests/src/install/test_skill_compiler.py`                                                                    |
| Codex spec conformance     | each Codex package                                                  | directory/name match; only allowed frontmatter; relative references and `openai.yaml` validate | `tests/src/install/test_skill_compiler.py`                                                                    |
| Whole-tree isolation       | nested resources, references, and scripts with one prohibited token | validation fails with runtime, path, and violated rule                                         | `tests/src/install/test_skill_validation.py`                                                                  |
| No family x runtime matrix | all model-family rubric variants                                    | runtime bindings are absent from family resources; output count does not multiply by runtime   | `tests/src/install/test_skill_compiler.py`                                                                    |
| User discovery             | isolated `$HOME`, Codex user install                                | skill appears once from `$HOME/.agents/skills` and can be explicitly invoked                   | `tests/integration/docker/test_installer.py` + `scripts/experiments/codex-skills/stages/10-user-discovery.sh` |
| Nested project discovery   | nested CWD under an enabled Forge project                           | applicable `.agents/skills` package is discovered up to the repository root                    | `scripts/experiments/codex-skills/stages/20-project-discovery.sh`                                             |
| Local-scope privacy        | local Forge install with Codex requested                            | reviewed refusal/convention applies; no personal skill is written to shared `.agents/skills`   | `tests/src/install/test_cross_runtime_skills.py`                                                              |
| Duplicate safety           | same skill name already present at another Codex scan level         | reviewed conflict/warning is deterministic; user-owned file is untouched                       | `tests/src/install/test_cross_runtime_skills.py`                                                              |
| Invocation policy          | explicit-only skill with `allow_implicit_invocation: false`         | implicit prompt does not select it; explicit `$skill` remains usable                           | `scripts/experiments/codex-skills/stages/40-invocation-policy.sh`                                             |
| Packaged script resolution | user and project `smoke-test` installs invoked from unrelated CWDs  | exact installed script runs without checkout/CWD coupling and probes runtime-correct homes     | `scripts/experiments/codex-skills/stages/50-script-resolution.sh`                                             |
| Runtime-aware lifecycle    | Claude + Codex packages tracked for one scope                       | enable/sync/status/disable are idempotent and remove only tracked files                        | `tests/src/install/test_cross_runtime_skills.py`                                                              |
| Package-root substitution  | tracked package directory replaced by a symlink to a sibling        | status is invalid; sync/disable preserve sibling bytes and tracking                            | `tests/regression/test_bug_runtime_skill_package_symlink_escape.py`                                           |
| Partial conflict           | user-owned target conflicts in one runtime                          | plan/apply follows the reviewed atomicity rule and records no half-install as complete         | `tests/src/install/test_cross_runtime_skills.py`                                                              |
| Copy and symlink modes     | compiled package installed in both modes                            | targets are stable and no symlink points into temporary build output                           | `tests/src/install/test_cross_runtime_skills.py`                                                              |
| Wheel clean install        | isolated wheel/sdist tool install                                   | packaged sources/adapters compile and install both runtime packages without checkout paths     | `tests/integration/docker/test_installer.py` + release smoke                                                  |
| Claude-worker limitation   | Codex-hosted workflow frontend before Axis 2                        | UI/docs name the `claude` worker prerequisite; no Codex-native claim is made                   | `tests/src/review/test_skill_content.py`                                                                      |

## Post-implementation review remediation (2026-07-17)

- [x] Preserve and refresh every managed runtime during plain automatic `enable`; make explicit runtime narrowing emit
  package-level preservation rows and retain exact file/package ownership, including a genuine v1 tracking upgrade.
- [x] Classify cross-scope Codex duplicates from validated tracking provenance, normalize symlinked path components
  consistently, reject malformed ownership claims, and wire safe recovery through human and JSON status. For a
  user-scope target, inspect every present tracked project/local package even outside the current directory chain.
- [x] Treat package roots and descendant directories as real-directory ownership boundaries. Reject substituted symlinks
  during fresh enable, status, sync, apply, rollback, and disable while retaining leaf-file symlink mode.
- [x] Make `extension status --all` safe outside a project and distinguish policy conflicts that `--force` cannot
  override. Give Codex-only users a complete skills-only recovery command when Claude is absent.
- [x] Reject conflicting typed/Claude frontmatter declarations at manifest load, map cache materialization failures to a
  retryable installer error, canonicalize manual smoke-script invocation, and pin the Claude-worker limitation in tests.
- [x] Consolidate repeated installer test patches, isolate `HOME` automatically, remove host-dependent runtime probes,
  and replace the session-container asset mutation helper with a real-wheel, temp-only lifecycle harness.
- [x] Update lifecycle/operator docs and QA §2.13; regenerate the QA index to v1.0.28 / 585 assertions. Recheck the
  walkthrough install/status/sync/teardown path and retain its project-only Codex coverage because user-scope `.agents`
  mutation remains Docker-QA-only.
- [x] Run the targeted real-wheel Docker lifecycle for both Claude and Codex packages.
- [x] Run the final unit, build, pre-commit, Markdown, and diff-integrity gates and record the results below.

## Documentation and operator verification

- [x] Update `docs/design.md` when runtime/installer ownership changes.
- [x] Update `docs/design_appendix.md` §C scope/module/tracking contracts and the runtime reference.
- [x] Update `docs/design_workflows.md` §3 skills architecture, capability vocabulary, compile model, and Axis 2
  limitation.
- [x] Update `docs/cli_reference.md` for any runtime/scope selection, status, doctor, or error surfaces.
- [x] Update `docs/end-user/skills.md`, installation/Day-1 guidance, and relevant Codex runtime guidance for
  wheel-installed users.
- [x] Update `docs/end-user/manual_testing.md` for the runtime-specific skill install surfaces, the Claude-only
  `walkthrough`/`qa` boundary, and the safe division between host walkthrough and Docker QA coverage.
- [x] Update the QA checklist index and relevant sections -- at minimum §§0, 2, 15, 17, 18, and 19 -- for runtime-aware
  enable/install/status/sync/doctor/cleanup/disable/uninstall and Codex invocation. Recalculate the index assertion
  count and last-updated metadata as required by `docs/developer/testing_guidelines.md`.
- [x] Review and update walkthrough checklist §§0, 2, 3, 4, 5, and 13 plus its assertion count/date for project-scope
  Codex install verification. Do not exercise Codex user scope against the real `$HOME/.agents/skills`: keep it in
  Docker QA unless the walkthrough first gains full `HOME`/`.agents` isolation and matching safety gates.
- [x] Update `src/skills/review/references/skills-writing-guide.md` so contributors author neutral content and know
  which fields/capabilities belong to each runtime adapter.
- [x] Run focused unit suites for compiler, validation, runtime registry, installer planning/tracking, CLI streams, and
  skill content.
- [x] Run the required targeted installer integration through `./scripts/test-integration.sh`, including packaged Codex
  user/project skill targets.
- [x] Run `uv build`, then verify wheel and sdist in separate clean tool homes with `forge extension enable`,
  `extension status --json`, `extension doctor --json`, sync, and disable.
- [x] Run real `codex` discovery and explicit invocation for user and project scopes on the validated CLI version.
- [x] Run `make test-unit` and `make pre-commit`; record all failures, skips, and environment limits.

## Closeout

- [x] Confirm every accepted Phase 0 decision is reflected in code, tests, design docs, end-user docs, and the card.
- [x] Add a compact newest-first entry to `docs/board/change_log.md` with verification evidence.
- [x] Propose durable implementation lessons for human review; promote only approved invariants to
  `docs/board/impl_notes.md`.
- [x] Verify clean wheel/sdist behavior and the user-facing Day 1 path.
- [ ] After user review, move this card to its correct terminal lane, preserve the checklist, and repoint all inbound
  board links. Intentionally held in `doing/` at the requested review boundary.
