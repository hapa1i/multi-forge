# Checklist: Unmanaged Skill Packages — Detection and Cleanup

**Card**: [card.md](card.md) — the normative contract. This checklist sequences it; where they disagree, the card wins.

**Branch**: `unmanaged-skill-packages` (from `main` at `e3f0f405`)

## Current Focus

Phases 0–7 and the Phase 8 audit/verification are complete. Review ratified the fail-closed whole-target-root behavior
with a human root-level diagnostic: the scanner never traverses an unsafe root and never invents the skill name required
by the fixed JSON package record. Review remediation also restored the displaced runtime-selection assertion and removed
status/clean's dependency on fully parsed skill sources. The card remains in `doing/` pending the next review pass.

## Phase 0: Acceptance

- [x] Execution branch `unmanaged-skill-packages` created from `main`

- [x] Card moved `proposed/` -> `doing/` via `git mv`; `**Lane**` header updated; no inbound links existed to repoint
  (verified by repo-wide grep at acceptance)

- [x] Checklist written; revised across two review rounds

- [x] Checklist reviewed by user; acceptance committed on the execution branch

  - Verification recorded: acceptance review completed; execution branch and checklist links were checked against the
    board contract.

## Phase 1: Provenance sentinel (compiler / cache / ledger / install mode)

Foundation for every later phase; ships the compiled-cache digest clean break (card §Provenance sentinel).

- [x] 1.1 Sentinel emitter in `src/forge/install/skill_compiler.py` writes `<package>/.forge-package.json`: canonical
  UTF-8 JSON, `schema_version: 1`, `producer: multi-forge`, `runtime`, `skill`, `files[]` sorted by relative POSIX path
  with `sha256` (lowercase hex) + `mode`; no timestamps, absolute paths, cache locations, or Forge version.
  - Assertion: two compiles of identical source produce byte-identical sentinels; the sentinel is excluded from its own
    `files[]`; path rules enforced (normalized, relative, unique, nonempty, no `.`/`..` components).
- [x] 1.2 Sentinel is a first-class emitted file: participates in the compiled-cache digest (`skill_cache.py`), install
  file ledger, tracking checksum, sync, and disable.
  - Assertion: cache digest changes exactly once for unchanged source (the intentional clean break); sync and disable
    round-trip the sentinel; covered in `tests/src/install/test_skill_cache.py`, `test_tracking.py`, and
    `test_cross_runtime_skills.py`.
- [x] 1.3 Per-file effective install mode, end to end. Today the planner and executor carry only the installation-wide
  `InstallMode` (`_plan_compiled_file(..., mode)`, `_execute_file(file_plan, mode)`), and `_installed_file_record`
  stamps that one mode onto every `InstalledFile` row — there is no seam for one copied file inside a symlink install.
  Introduce a per-file effective mode from planning through execution to the ledger row, with the sentinel pinned to
  copy.
  - Assertion (plan): in symlink mode the sentinel's `FilePlan` is a copy operation, and skip detection classifies an
    existing regular-file sentinel as correct rather than as symlink drift.
  - Assertion (execute + ledger): a symlink-mode install produces payload symlinks plus a regular-file sentinel whose
    `InstalledFile.mode` records the copy; disable removes both kinds. Existing best-effort apply-failure rollback
    removes newly created files of both kinds; it does not promise restoration of overwritten tracked files.
  - Assertion (idempotence): a second symlink-mode sync with unchanged source plans `skip` for every file including the
    sentinel, and tracking still records the sentinel as copied.
- [x] 1.4 Claude and Codex whole-tree validators (`skill_validation.py`) accept the hidden sentinel file in emitted
  packages.
  - Assertion: validation passes with the sentinel present for both runtimes; `test_skill_validation.py`.
- [x] 1.5 Doc sync (board contract: design docs update with the phase): `docs/design.md` §5.1 and
  `docs/design_appendix.md` §C describe the sentinel as an emitted, always-copied ledger file and record the one-time
  cache-digest change.
  - Verification recorded: 675 install unit tests passed with 1 skipped, 20 Docker installer tests passed, and mypy
    completed successfully after the Phase 1 changes.

## Phase 2: Skill-name universe

- [x] 2.1 Append-only `FORGE_SKILL_NAME_HISTORY` in `skill_planning.py`, seeded with the pre-feature baseline; a union
  helper (current shipped/compilable names ∪ history) exposed for the scanner.
  - Assertion (non-tautological): the test pins the immutable pre-feature baseline as exactly `analyze`, `challenge`,
    `consensus`, `debate`, `panel`, `qa`, `review`, `review-docs`, `smoke-test`, `understand`, `walkthrough`, then
    requires that baseline to remain a subset of history. An empty or shrunken history fails regardless of the union;
    later append-only additions remain valid. A separate assertion checks every current candidate name is in the union.
  - Baseline derivation rule (verified at acceptance): seed only names whose `src/skills/` compiler sources shipped. Do
    NOT derive the baseline from a repo-wide "every skill directory ever" sweep — this repo's own `.agents/skills/`
    contains hand-authored project skills (`gather-context`, `refactor-audit`, `simplicity-audit`) that were never Forge
    output; seeding them would make the scanner warn on user content (the card's "historical Forge name" row).
  - Review remediation: status/clean use names-only candidate discovery and fall back to history if the source root is
    unavailable; installer planning retains full parsing and checkout Git-eligibility gating.

## Phase 3: Detection core op (scanner)

One UI-agnostic operation shared by installer planning, status, and GC (card §Detection operation).

- [x] 3.1 New module `src/forge/install/unmanaged.py` (mirror test `tests/src/install/test_unmanaged.py`) returning
  immutable records with the fixed 12-field shape (`runtime` … `recovery`) from the card. `recovery` is `str | null` — a
  rendered human recovery line matching the `SkillPackageStatus.recovery: str | None` precedent; machine-readable state
  stays in `cleanup_eligible`/`cleanup_reason`/`cleanup_scope`.
- [x] 3.2 Tracking input contract: the op accepts an optional pre-validated tracking snapshot — status and installer
  planning already load tracking and inject theirs, so the managed set and their own rendering come from one coherent
  read — and owns exactly one read when none is supplied (GC, standalone). Managed paths derive from coherent schema-v2
  rows only; canonicalization matches `skill_planning.py` (resolve parent components, preserve the final path entry).
- [x] 3.3 Tracking failure is a no-scan boundary: missing manifest means no managed rows; a corrupt, unsupported, or
  unreadable manifest propagates the existing state error and is never treated as empty tracking.
- [x] 3.4 `lstat`-first direct-child scan of selected writable targets only; observed-entry rules per card §Identity and
  classification (name in universe ∪ sentinel-bearing; files, root symlinks, and partial directories visible as
  report-only unsafe shapes; unknown unmarked names ignored as user content).
- [x] 3.5 Provenance classification `marked | unmarked | invalid-marker | unsupported-marker | modified`; strict
  sentinel parsing (unknown fields, invalid shapes, newer schemas are report-only, never guessed).
- [x] 3.6 Cleanup proof implements card §Provenance sentinel checks 1–5 exactly, including the live-cache-link rule and
  the narrow dangling-cache-link reconstruction for reset packages; any mismatch sets `cleanup_eligible: false` with a
  concrete `cleanup_reason` (never downgraded to user-owned, never a best-effort subset).
- [x] 3.7 Collision detection via Codex visibility roots (applicable ancestor `.agents/skills`, `/etc/codex/skills`) as
  `visibility-only`; `collision_dirs` sorted and excluding the record's own path; collision never affects eligibility.
  - Phase assertion: scanner unit tests cover the ownership/collision cross-product, historical names, partial entries,
    strict marker parsing, modified trees, canonical identity, live and dangling cache links, and `lstat`/symlink
    containment.

## Phase 4: Status surface

- [x] 4.1 `forge extension status` renders a separate "Unmanaged runtime skill packages" section from the same records,
  even when the selected scope has no installation row; scope semantics per card (`--scope user` = two fixed user
  targets; `--scope project|local [--root]` = that root's writable targets; `--all` = user + effective current root;
  auto-detection = whichever scopes status would display). Tracked packages keep their existing four states —
  `SkillPackageStatus.state` gains no `unmanaged` value.
- [x] 4.1a A selected target root that cannot be scanned safely produces a human `Root not scanned` diagnostic without
  traversal. The fixed schema-v2 JSON arrays remain unchanged because no package skill name is observable.
- [x] 4.2 JSON clean break in `cli/extensions.py::status_cmd`: top-level versioned object
  `{schema_version: 2, installations: [...], unmanaged_skill_packages: [...]}`; absent values are JSON `null`, not
  omitted; stdout carries only the JSON document, diagnostics stay on stderr.
- [x] 4.3 Contract-test migration in this phase: existing status `--json` assertions that index the bare array (e.g.
  `test_cross_runtime_skills.py` `payload[0][...]`) move to the object shape deliberately; migration edits touch
  assertions only, no behavior.
- [x] 4.3a QA assertion migration: update the `/forge:qa` extension checklist's jq probes (including
  `src/skills/qa/resources/checklist/2-extension.md`) from bare-array indexing to the versioned object shape, and add
  assertions for `schema_version`, `installations`, and `unmanaged_skill_packages`.
- [x] 4.4 `forge extension doctor` untouched: no `skill_packages`, no unmanaged data (existing invariant test stays
  green unchanged).
- [x] 4.5 Doc sync: `docs/cli_reference.md` documents the new status JSON object as a research-preview clean break.
- [x] 4.6 QA-checklist sync and manual coverage: update the tracked QA checklist and its index/`last-updated` metadata
  for the status JSON v2 object, add the sentinel emission/always-copy and cache-reset checks to the manual extension
  steps, and run the checklist parser to verify every jq assertion against the shipped CLI.

## Phase 5: Installer recovery (enable/sync)

- [x] 5.1 Skill-package planning consumes scanner records before reducing a runtime package to a conflict or automatic
  skip; `SkillPackagePlan` and the human conflict renderer carry a per-package recovery string.
- [x] 5.2 Recovery split per card §Enable and sync recovery: a marked `cleanup_eligible` orphan names the exact path,
  preview command, apply command (`--yes`), and rerun of the original enable/sync (user targets:
  `forge clean --scope all --verbose`; project targets: `cd <root> && forge clean --scope project --verbose`); every
  other provenance keeps exact-path remove-or-rename guidance. Never suggest `forge clean` for a record its current
  scope would not list.
- [x] 5.3 No-write boundary, duplicate safety, and `--force` **behavior** unchanged: no adoption, overwrite, tracking
  repair, or automatic removal. Existing enable/duplicate tests keep their behavioral assertions; only their status-JSON
  shape (migrated in Phase 4) and recovery-text expectations change, and each such edit is deliberate.
- [x] 5.4 Multiple conflicts keep per-package recovery; mixed safe and unknown entries are never collapsed into one
  global tip.
- [x] 5.5 Doc sync: duplicate-classification recovery language in `docs/cli_reference.md` (Installation section),
  `docs/design.md` §5.1, and the `docs/end-user/README.md` Day 1 extension flow updated to the
  clean-preview/apply/rerun-vs-remove-or-rename split.

## Phase 6: GC cleanup category

- [x] 6.1 `unmanaged_skill_packages` added to `OrphanCategory` (`core/ops/gc.py`); the report contains only entries that
  passed the full cleanup proof — report-only observations remain exclusive to `extension status`.
- [x] 6.2 Scope mapping per card table: `project` = current `forge_root`'s project/local targets (never user);
  `workspace` = project/local targets for GC-known roots in the logical workspace (never user); `all` adds the two fixed
  user targets. Missing target roots skipped; paths canonicalized and deduplicated before counting.
- [x] 6.3 `_project_owner` handles the new category explicitly: project-owned for project/local paths, global for user
  paths; a compatibility refusal stays in the preview category/count, renders through `skipped_project_compatibility`,
  and is excluded from apply.
  - Assertion: an incompatible project candidate remains in the preview category/count and appears in
    `skipped_project_compatibility`; apply leaves it untouched and exits nonzero, while user/global candidates remain
    independent of project compatibility.
- [x] 6.4 `run_clean` performs a fresh scan rather than trusting the preliminary CLI report. A candidate that becomes
  managed before that scan is omitted from apply and left untouched without an apply failure. Each candidate returned by
  the fresh scan is revalidated immediately before removal; ownership, marker, contents, path-type, containment, or
  compatibility drift after the scan records a failure, leaves the entry untouched, and produces a nonzero apply result
  through the existing `CleanResult` contract. Removal targets only the exact validated package directory; traversal
  never follows symlinked roots or subdirectories.
  - Assertion: drift tests cover at minimum (a) pre-scan ownership change — a coherent tracking row claims the path
    before `run_clean`'s fresh scan, so the package is omitted and untouched without a package failure; (b) post-scan
    ownership drift before pre-delete revalidation, which fails nonzero; (c) contents drift — a file added or edited;
    (d) path-type drift — the package or a parent directory replaced by a symlink; and (e) compatibility drift.
- [x] 6.5 CLI coverage per card §Verification: `tests/src/cli/test_gc.py` (with `tests/src/core/ops/test_gc.py`) covers
  all three clean scopes, `%clean`, JSON counts, project compatibility, category-wide apply, the missing-manifest second
  pass (clean removes a corrupt `installed.json`; a second clean then lists the now-unclaimed packages), lost-root
  boundaries, and failure exit behavior.
- [x] 6.6 `%clean` inherits the same read-only report with no destructive path.
- [x] 6.7 Doc sync: `docs/cli_reference.md` clean contract (scope table + new category) and `docs/end-user/skills.md`
  tracking-reset recovery sequence (card §Tracking-reset recovery).

## Phase 7: Incident regression + integration

- [x] 7.1 Regression test for the motivating incident: `tests/regression/test_bug_20260719_unmanaged_skill_leak.py` (id
  = incident date, per the `test_bug_<id>_<description>` rule in `AGENTS.md`), with file-level
  `pytestmark = pytest.mark.regression`. Asserts untracked pre-marker packages with valid `SKILL.md` in a user target
  are reported by status with remove-or-rename recovery and never appear in any clean report.
- [x] 7.2 Docker installer integration (`tests/integration/docker/test_installer.py`): a wheel-installed package carries
  the marker; copy and symlink cache-reset cleanup paths; user and project cleanup + re-enable sequence.
  (Editable-source runs can hide packaging errors — the wheel path is the point.)
- [x] 7.3 `tests/conftest.py::isolate_home` guard retained; no test opts out of HOME isolation.

## Phase 8: Final audit + closeout

Doc updates ship with their phases (1.5, 4.5, 5.5, 6.7); this phase is the consistency audit and board closeout.

- [x] Consistency audit: `docs/design.md`, `docs/design_appendix.md`, `docs/cli_reference.md`, `docs/end-user/README.md`
  (Day 1 flow), and `docs/end-user/skills.md` reflect shipped behavior; no phase left checklist debt.
- [x] `docs/board/change_log.md` entry with Goal / Key changes / Verification, naming both research-preview clean
  breaks: the one-time compiled-cache digest change and the status `--json` schema-v2 object.
- [x] Durable lessons proposed via `.forge/memory/shadow_impl_notes.md` for human promotion (not directly to
  `impl_notes.md`).
- [x] Full verification recorded: focused suites, `make test-unit`, targeted Docker installer integration,
  `make pre-commit`.
  - Verification: focused acceptance (`289 passed`); related compiler/cache/tracking/validation (`170 passed`);
    `make test-unit` (`8230 passed, 1 skipped, 117 deselected`); `make test-regression` (`522 passed`); wheel-installed
    Docker lifecycle (`1 passed, 19 deselected`); `uv build`; `make pre-commit`; QA parser v1.0.31 / 592 assertions;
    walkthrough parser v1.0.5 / 108 assertions.
- [ ] Card moved `doing/` -> `done/`; inbound links repointed (none existed at acceptance; re-verify at closeout).

## Acceptance Tests

| Test                                      | Fixture                                                                    | Assertion                                                                            | Test File                                                                       |
| ----------------------------------------- | -------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------- |
| Incident package visible, never deletable | untracked unmarked dir with valid `SKILL.md` in user Codex target          | status: unmanaged/unmarked + remove-or-rename; absent from every clean report        | `tests/regression/test_bug_20260719_unmanaged_skill_leak.py`                    |
| Marked orphan cleanup                     | compiled marked copy package; tracking row removed                         | `cleanup_eligible=true`; listed in matching scope; removed only with `--yes`         | `tests/src/core/ops/test_gc.py`                                                 |
| Cache-reset symlink package               | symlink-mode install; compiled cache deleted                               | `partial` + eligible; clean removes links without following them                     | `tests/src/core/ops/test_gc.py`                                                 |
| Modified marked package                   | marked package with one edited payload byte                                | `modified`; `cleanup_eligible=false` + mismatch reason; never listed by clean        | `tests/src/install/test_unmanaged.py`                                           |
| Corrupt tracking is no-scan               | malformed `installed.json`                                                 | scan propagates existing state error; clean fail-closed with zero package candidates | `tests/src/install/test_unmanaged.py`, `tests/src/core/ops/test_gc.py`          |
| Pre-scan ownership change                 | tracking row claims candidate after CLI report but before `run_clean` scan | fresh scan omits candidate; package untouched; no package failure                    | `tests/src/core/ops/test_gc.py`                                                 |
| Post-scan pre-delete drift                | ownership/content/path/compatibility changes after `run_clean` scan        | pre-delete revalidation fails; path preserved; apply exits nonzero                   | `tests/src/core/ops/test_gc.py`                                                 |
| Project compatibility refusal             | marked project orphan under an incompatible project pin                    | counted in preview + structured skip; excluded from apply; nonzero result            | `tests/src/core/ops/test_gc.py`, `tests/src/cli/test_gc.py`                     |
| Missing-manifest second pass              | clean removes corrupt `installed.json`; clean invoked again                | second pass lists the now-unclaimed marked packages; first pass listed none          | `tests/src/cli/test_gc.py`                                                      |
| Sentinel symlink-mode idempotence         | symlink-mode enable, then sync with unchanged source                       | sentinel is a regular file with ledger mode copy; second sync plans all-skip         | `tests/src/install/test_cross_runtime_skills.py`                                |
| Status JSON v2 shape                      | no installation row + one unmanaged entry                                  | top-level object with `schema_version: 2`; both arrays present; stdout is pure JSON  | `tests/src/cli/test_extension_enable.py`                                        |
| Unsafe selected runtime root              | selected user target is a symlink                                          | human root-not-scanned line; no traversal or synthetic JSON package row              | `tests/src/install/test_unmanaged.py`, `tests/src/cli/test_extension_enable.py` |
| Broken current skill source               | names-only source discovery unavailable                                    | status/clean retain history and unrelated cleanup categories continue                | `tests/src/cli/test_extension_enable.py`, `tests/src/core/ops/test_gc.py`       |
| Sentinel ledger round-trip                | copy + symlink installs                                                    | sentinel in cache digest, file ledger, tracking checksum; sync and disable handle it | `tests/src/install/test_cross_runtime_skills.py`                                |
| Enable recovery split                     | enable blocked by eligible marked orphan vs unmarked package               | conflict names exact path + clean preview/apply/rerun vs remove-or-rename            | `tests/src/cli/test_extension_enable.py`                                        |
| Wheel marker E2E                          | Docker: wheel install -> enable -> delete tracking -> clean -> re-enable   | marker present from wheel output; cleanup and re-enable succeed                      | `tests/integration/docker/test_installer.py`                                    |

## Review Decisions

Resolved across the two review rounds:

1. **Scanner module home** — `src/forge/install/unmanaged.py` (accepted; `core/ops/gc.py` already imports from
   `forge.install`, no new layering edge).
2. **`FORGE_SKILL_NAME_HISTORY` home** — `skill_planning.py`, with the seeded baseline pinned per Phase 2.1 (accepted
   with the baseline requirement).
3. **Unmanaged `recovery` JSON type** — `str | null` (rendered human line), matching the existing
   `SkillPackageStatus.recovery: str | None` precedent; machine-readable state remains in
   `cleanup_eligible`/`cleanup_reason`/`cleanup_scope` (accepted and promoted to the card).
4. **Regression id** — incident date as `<id>`: `test_bug_20260719_unmanaged_skill_leak.py` (accepted; satisfies the
   `AGENTS.md` naming rule without weakening it).
