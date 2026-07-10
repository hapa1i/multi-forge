# Execution checklist: T6 `forge_hook_migration_cleanup`

Execution plan for migrating pre-T5 hook installations to the user-scoped dispatcher model. The shared contract and
sequencing live in the epic [`card.md`](../epic_global_forge_runtime/card.md); this member's problem framing is
[`card.md`](card.md).

> **Drafted 2026-07-10 on branch `forge-hook-migration-cleanup`; revised through follow-up review.** No product
> implementation has started. Phase 0 decisions still require approval before Phase 1 begins.

## Current focus

Review this checklist, especially the explicit project-mutation boundary and the conservative fallback rule. T6 is the
last member on the T3 -> T4 -> T5 -> T6 critical path. T5 already changed new installations; T6 must provide a safe,
visible path for migrating old tracked and legacy state without deleting user-owned configuration or claiming that an
unresolved root is clean.

## Scope boundary

**In:**

- Discover tracked project/local migration candidates from `~/.forge/installed.json` without enrolling them; enroll only
  the explicitly cleaned root, as the final activation step, with `enrollment_source="backfill"`.
- Remove pre-T5 Claude hooks from project/local settings while preserving status line, permissions, files, unrelated
  hooks, and the remaining installation record.
- Remove safely identifiable untracked legacy Claude hook entries, including the removed standalone writer's old output,
  with a backup before every changed settings file.
- Remove project/local Codex managed blocks by their markers while preserving unrelated TOML and reporting manual
  registrations outside the block.
- Complete the transition to user-scoped dispatcher hooks in remove-first order, with honest reporting of the transient
  hooks-off window and Codex re-trust requirement.
- Replace T5's placeholder doctor/status-line guidance with actionable migration state and the shipped cleanup command.

**Out:**

- Hook registration ownership and dispatcher bytes for new installs (T5/T4, shipped).
- Sidecar hook staging and image resolution (T10, shipped).
- `statusLine` ownership (epic D3: project/local, unchanged).
- Any new migration-state fields in `forge extension status`; T5's “doctor/status” contract means doctor plus the opt-in
  status line.
- A version manager or bypass for `.forge/project.toml` (T7/T8).
- Automatic deletion of ambiguous manual hook entries or Codex registrations outside Forge markers.
- T8's checkout-local developer runtime override.

## Grounding and premise corrections (verified 2026-07-10)

- `TrackingStore.list_installations()` already exposes `(scope, project_path, Installation)` rows, and
  `make_installation_key()` stores project/local roots as `<scope>:<absolute-path>`. Old v1 bare scope keys can still
  parse with `project_path=None`; they are not recoverable roots and must be reported, not guessed.
- `ProjectRegistryStore.enroll(root, "backfill")` already supplies locked read-modify-write, canonicalization,
  idempotency, and provenance preservation. T6 must reuse it for the selected root rather than writing `projects.json`
  directly.
- T5 already preserves filtered project/local hook tracking in both `Installation.settings_entries` and the newest
  `.settings*.forge.added.*` payload. It also removes tracked legacy **user-scope** bytes before merging dispatcher
  entries. T6 should consume those seams, not recreate the T5 byte cutover.
- Claude hook removal is full-entry canonical equality. `merge_hooks`, `smart_unmerge`, and the hook branch of `unmerge`
  compare canonical entry JSON; hook `stable_id` stores that identity but is not independently consulted by the removal
  branch. The old card's "remove by stable_id" wording was corrected.
- `forge_hook_handler()` / `is_forge_hook_command()` already map both `forge hook <handler>` and `forge-hook <handler>`
  to one logical handler without substring matching. `find_forge_hook_registrations()` and
  `has_forge_hook_double_fire()` already detect cross-scope and same-file duplicates by `(event, matcher, handler)`.
- T2 was skipped. Forge did not ship a T2 host-absolute command migration, although an absolute path whose executable
  basename is `forge` still matches the shared token predicate and may be handled as legacy input.
- `remove_codex_block()` already removes only the marker-delimited block, deletes a whitespace-only file, preserves
  unrelated TOML, and reports logical Forge commands outside the block. It does not make a new backup itself; the T6
  mutation path must do so before applying a removal.
- `_print_codex_completion()` already prints trust-ceremony guidance when a Codex block is installed or updated. T6
  should add migration-specific wording only if the existing output does not honestly describe the transition.
- `forge extension doctor` currently emits `runtime_hooks.{scopes,double_fire_risk}` and names
  `forge extension cleanup-project` as future work. The cleanup leaf does not yet exist.
- The removed standalone writer could leave bare hooks in project `.claude/settings.local.json` or legacy user
  `~/.claude/settings.local.json` without `installed.json` ownership. Those entries are the primary value-based fallback
  fixture.
- Project-scope `.claude/settings.json` is team-shared and checked in under the scope contract. A user-scope lifecycle
  command therefore has no implied authority to edit it, especially in a different tracked checkout.
- The released legacy writer inventory checked from the initial preset through its removal has one observed structural
  generation for event, matcher, timeout, wrapper, and handler. T6 still needs a frozen additive historical inventory so
  a future preset change cannot make genuinely Forge-written legacy bytes ambiguous.
- `has_forge_hook_double_fire()` reports only duplicate `(event, matcher, handler)` registrations. A lone legacy source
  is not currently mislabeled `HOOKx2`; cleanup-required detection must be independent and additive.
- Dispatcher `_should_dispatch()` returns true when `FORGE_SESSION` is set or the current Forge root is enrolled. An
  unenrolled legacy root therefore remains legacy-only for ambient sessions even when the user dispatcher exists;
  enrolling it before cleanup activates the dispatcher and creates ambient double-fire.

## Phase 0 — Decisions for review

- [ ] **D1 — Untracked Claude fallback. Recommended: exact known-released Forge-only auto-removal; ambiguity stays
  report-only.** Freeze an additive migration inventory of released legacy direct-hook shapes. Normalize only the
  recognized command form, then require the event, matcher, timeout, wrapper shape, and handler to match one historical
  shape exactly. Do not derive the historical set solely from the current preset or replace old fixtures when current
  hook bytes change. Auto-remove an eligible entry after backup. Leave and report wrappers with mixed Forge/non-Forge
  commands, extra semantic fields, unknown shapes, changed matchers/timeouts, malformed structures, or unrecognized
  commands. Never use substring matching.
  - _Assertion:_ every frozen legacy-writer generation remains removable after later inventory changes, while every byte
    of an ambiguous manual entry is preserved.
- [ ] **D2 — Cross-repo mutation and visibility boundary. Recommended: user-scope `enable`/`sync` never edit
  project/local roots; `cleanup-project` owns all repository mutation.** User lifecycle commands may consolidate safe
  legacy siblings in user settings, install/update the user dispatcher, and list tracked roots with exact
  `forge extension cleanup-project --root <path>` guidance. They must not open cross-root settings/config for migration,
  change project/local tracking rows, or enroll those roots in `projects.json`. `cleanup-project` handles one selected
  root plus the conservative untracked fallback under D3's explicit preview/apply contract. A future multi-root apply
  needs its own explicit flag and aggregate failure contract; it must not be smuggled into ordinary enable/sync.
  - _Assertion:_ user-scope enable/sync may change user Forge files, but never produces a repository diff or changes
    ambient dispatcher eligibility in another root; each root mutation and enrollment requires a separately visible
    `cleanup-project --yes` invocation.
- [ ] **D3 — `cleanup-project` mutation UX. Recommended: preview by default; `--yes` applies; optional `--root` selects
  one Forge project.** The preview lists exact settings/config paths, tracked versus fallback removals, registry
  enrollment as the final activation, user-hook action, backups, and unresolved entries. A later `--yes` invocation
  recomputes the plan rather than applying state captured by a prior preview. No `--json` in v1: this is a destructive
  migration leaf, while `doctor --json` is the scriptable read surface.
- [ ] **D4 — Completing the transition. Recommended: cleanup ensures only the runtime-hook modules at user scope without
  changing unrelated user modules.** For an existing user installation, union the required runtime modules into its
  tracked module set; for no user installation, create a tracked runtime-hooks-only installation. Do not reinstall a
  full profile or remove existing commands/skills/permissions. Add `codex-hooks` when a Codex project block is migrated;
  otherwise do not introduce Codex configuration merely because Claude hooks were present.
- [ ] **D5 — Operation-scoped persistent-duplicate guard. Recommended: an unresolved registration blocks completion only
  for the root being cleaned, not for unrelated tracked roots or plain user enable/sync.** The selected root plus any
  user settings named in its plan form the cleanup gate. If an ambiguous selected-root registration remains,
  retain/report it, skip a new user write from that cleanup, exit non-zero on `--yes`, and provide the exact recovery
  path. An unresolved entry elsewhere degrades to reported cleanup/doctor state and never prevents the user's own
  dispatcher from being installed. If a user dispatcher already exists, report the selected root's still-present risk
  rather than claiming cleanup success.
- [ ] **D6 — Candidate discovery and selected-root activation. Recommended: discovery never enrolls; successful cleanup
  enrolls the selected root last.** Report missing/unrecoverable tracking rows without changing `projects.json`. For an
  unenrolled, compatibility-readable selected root, remove legacy state, verify the user dispatcher/Codex transition,
  then call `ProjectRegistryStore.enroll(root, "backfill")` as the final activation write. Do not turn stale tracking
  keys into registry entries. If the selected root is already enrolled, preserve its provenance and make legacy removal
  the first mutation rather than temporarily unenrolling it.

## Phase 1 — Migration inventory and plan model

- [ ] Add dependency-light `src/forge/install/hook_migration.py` with typed, UI-agnostic plan/result records. Keep
  Click/Rich output in `cli/extensions.py`; no `%` direct-command mirror is needed.
- [ ] Define the additive known-released legacy shape inventory in migration-owned code and mirror every supported
  generation with a frozen golden fixture. Do not generate historical eligibility dynamically from the current
  `get_builtin_preset()` output; changes require intentionally appending a fixture.
- [ ] Build one strict inventory for:
  - project `.claude/settings.json` and `.claude/settings.local.json`;
  - legacy user `~/.claude/settings.local.json` and current user `~/.claude/settings.json`;
  - project/local `Installation.settings_entries`, module fields, `.forge-added` payloads, and tracked Codex path;
  - project `.codex/config.toml` marker state and outside-marker Forge registrations. Inventory is operation-scoped:
    cleanup reads the selected root plus named user targets; user enable/sync reads user targets and global tracking but
    does not inventory another root's Claude/Codex files.
- [ ] Separate **logical detection** from **mutation eligibility**. Detection may use
  `forge_hook_handler()`/`find_forge_hook_registrations()`; auto-removal additionally requires D1's canonical Forge-only
  shape. Dispatcher entries and legacy entries with the same handler are not interchangeable mutation targets.
- [ ] Apply strict failure boundaries at the state that failed:
  - corrupt/unreadable/newer shared `projects.json` aborts `cleanup-project` before selected-root removal, but does not
    block user enable/sync because those commands neither read nor write the registry;
  - invalid global installation tracking aborts an operation that must read/update it before any mutation;
  - malformed/unreadable selected-root settings, config, tracked add-payloads, or compatibility state abort that root
    before any write; single-root `cleanup-project --yes` exits non-zero;
  - malformed user settings/config named in the transition plan aborts before selected-root removal, preventing a
    foreseeable hooks-off failure;
  - read-only discovery failures in other roots are reported and do not block user enable/sync. Any future explicit
    batch apply must skip failed roots, continue eligible roots, aggregate them, and exit non-zero. Doctor remains the
    fail-open/read-only diagnostic surface.
- [ ] The preview plan names every intended write and classifies it as tracked removal, safe fallback removal, registry
  enrollment/final activation, Codex block removal, user-hook install/update, or report-only ambiguity.
- [ ] Recompute and revalidate the plan under `--yes`; do not trust file contents captured by a prior preview.

## Phase 2 — Candidate discovery and selected-root activation

- [ ] Enumerate project/local tracking rows through `TrackingStore.list_installations()`; never parse installation keys
  again in the migration layer.
- [ ] Keep user-scope candidate discovery behaviorally read-only with respect to every root: use global installation
  tracking to print cleanup candidates, but do not open their Claude/Codex/compatibility files, change project/local
  tracking rows, read or write `projects.json`, or enroll anything.
- [ ] Report stale paths, v1 project/local rows with no recoverable path, and tracking paths that no longer identify a
  Forge project. Do not invent roots from CWD or delete tracking during discovery. These visibility results do not turn
  a successful user dispatcher install into a failed root migration because no root migration was attempted.
- [ ] For explicit cleanup, enforce the selected root's `.forge/project.toml` with the normal command-path strict
  posture and strictly validate `projects.json` before the first removal. An incompatible/malformed pin or corrupt
  registry aborts that root without touching it; an unrelated tracked root cannot affect the result.
- [ ] After selected-root legacy removal, tracking reconciliation, post-clean scan, and user dispatcher/Codex transition
  succeed, enroll the selected root with `ProjectRegistryStore.enroll(root, "backfill")`. Preserve existing provenance
  when already enrolled and canonicalize through the registry API.
- [ ] Treat new enrollment as the final ambient-dispatch activation write, not as preliminary bookkeeping. A failed
  final enrollment exits non-zero in the documented hooks-off recovery state. Concurrent enrollment uses the existing
  lock and remains idempotent; an already-enrolled root proceeds directly to legacy removal without an
  unenroll/re-enroll cycle.

## Phase 3 — Claude settings cleanup and tracking reconciliation

- [ ] For ownership-proven tracked hooks, remove only entries whose current full canonical value matches a tracked hook
  entry. Preserve user-modified tracked entries and report them as unresolved rather than removing by handler alone.
- [ ] For D1-eligible untracked legacy entries, remove only the Forge-only nested command/entry after backing up the
  exact settings file. Preserve unrelated event entries, matchers, non-command hooks, and user keys byte-for-byte at the
  semantic JSON level.
- [ ] Assign legacy user-scope sibling cleanup to the shared user-scope `enable`/`sync` transition: remove safe
  bare/absolute `forge hook` entries while preserving the current dispatcher entry. `cleanup-project` may call that same
  transition only when its preview names the user-file action; it must not grow a second user-settings cleaner. Never
  remove a valid user dispatcher merely because a legacy sibling exists.
- [ ] Write each changed settings file once through `write_settings()` after `backup_settings()`, then run
  `cleanup_empty_settings()` so empty hook containers do not linger. No partial per-entry writes.
- [ ] Reconcile each project/local `Installation` without disabling the installation:
  - remove `hooks` from `modules_enabled`;
  - remove only migrated hook `settings_entries`;
  - preserve status line, permissions/env, commands, skills, agents, files, `installed_at`, and scope metadata; set
    `updated_at` to the migration time;
  - rewrite the newest `.forge-added` payload so a later `extension disable` neither resurrects nor re-removes migrated
    hooks.
- [ ] Persist physical cleanup before dropping its tracking record. If the tracking write then fails, a retry sees stale
  ownership metadata over already-removed bytes, which is safer and idempotent; never drop ownership first and strand an
  active hook.
- [ ] Post-clean, scan the selected root plus user scope by `(event, matcher, handler)`. The selected-root apply result
  is successful only when that root's registrations are gone and user scope contains at most one logical registration
  per trigger. Registrations in other roots remain independent diagnostic state and do not block this result.

## Phase 4 — Codex block migration and trust posture

- [ ] For a tracked project/local Codex path, validate it against that scope's expected mapping before editing. Back up
  the file, then call `remove_codex_block()`; do not duplicate marker parsing.
- [ ] For an untracked block at the selected project's `.codex/config.toml`, exact balanced Forge markers are sufficient
  ownership for removal after backup. A partial/malformed marker pair is report-only and blocks successful completion.
- [ ] Preserve unrelated TOML exactly outside the removed block. A whitespace-only Forge-created file may be deleted
  only after its backup exists.
- [ ] Never auto-remove Forge-looking Codex commands outside the managed markers. Surface the event and config path as
  manual cleanup, without printing secrets or unrelated TOML.
- [ ] Clear `codex_config_path`, `codex_commands`, and `codex-hooks` from the project/local tracking row only after the
  block is removed or the tracked file is confirmed absent. Preserve tracking when removal is ambiguous or fails.
- [ ] After project/local cleanup, install/update the user Codex managed block only when D4 requires it. Reuse T5's
  logical event+handler dedupe, preserve the module's best-effort conflict posture, and print the one-time re-trust
  ceremony whenever command bytes or config location changed. Never claim enrollment was verified.

## Phase 5 — Orchestration, CLI, and diagnostics

- [ ] Add `forge extension cleanup-project [--root <dir>] [--yes]` as an explicit leaf on the existing lifecycle group.
  Resolve the selected Forge root with the same project identity rules as extension enable; reject `--root` inside
  `.claude/` and fail loudly outside a Forge project.
- [ ] Implement D2's user-scope `enable`/`sync` transition at one orchestration seam. Validate the user/tracking
  targets, report candidate roots from global installation tracking, consolidate safe user-file siblings, and
  install/update the user dispatcher. Print one exact cleanup command per affected root, but do not read or write its
  Claude/Codex targets or `projects.json`. Root cleanup need or staleness remains report/doctor state and must not
  suppress the user dispatcher write. Do not bury this orchestration inside `settings_merge.py`.
- [ ] Preserve remove-first ordering within explicit `cleanup-project --yes`:
  1. strict registry/tracking/config preflight and immutable plan;
  2. selected-root tracked/safe legacy cleanup and tracking reconciliation;
  3. selected-root plus user-scope post-clean scan, aborting on unresolved selected-root state;
  4. user dispatcher/Codex registration;
  5. selected-root enrollment as the final ambient-dispatch activation write;
  6. selected-root final scan and result rendering.
- [ ] Report the unavoidable cross-file hooks-off window honestly. If user installation or final enrollment fails after
  removal, exit non-zero, retain backups/tracking truth, and print the exact recovery command; do not roll project hooks
  back after a partially successful migration. A newly installed dispatcher remains ambient-inactive until enrollment,
  so this failure is hooks-off rather than double-fire.
- [ ] Make preview and apply idempotent. A fully migrated root previews no destructive actions; repeated `--yes` neither
  creates duplicate registry rows nor rewrites settings/config unnecessarily.
- [ ] Extend `forge extension doctor --json` with stable additive cleanup state under `runtime_hooks` (for example,
  `legacy_registrations` and `cleanup_required`) without removing T5's `scopes`/`double_fire_risk`. Human output names
  actual paths and the now-shipped cleanup command.
- [ ] Add an independent cleanup-required detector for the opt-in status-line hook warning. Do not broaden or replace
  `has_forge_hook_double_fire()`: `HOOKx2` remains true only for duplicate `(event, matcher, handler)` registrations,
  while a reviewed, distinct indication represents a lone legacy source. Both states may coexist. Keep the segment
  fail-open and default-off.
- [ ] Keep `forge extension status` unchanged. In this epic's T5/T6 terminology, “doctor/status” means doctor plus the
  opt-in status line; installation/tracking status is not a third migration diagnostic surface.
- [ ] Keep primary preview/result output on stdout and diagnostics/errors/prompts on stderr. Route recovery through
  `forge.cli.output`; new normal-flow strings must pass the `FORGE_*` vocabulary guard without teaching internal env
  variables.

## Phase 6 — Tests and verification

Acceptance table (fixture-grounded; exact file placement may be refined during implementation while preserving the
assertions):

| Test                                   | Fixture                                                                                              | Assertion                                                                                                                                    | Test File                                              |
| -------------------------------------- | ---------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------ |
| Cross-repo behavioral consent          | two unenrolled legacy roots, then `forge extension enable --scope user`                              | roots get exact cleanup guidance, but checkouts/project tracking/registry do not change and ambient dispatcher calls still no-op             | `tests/src/install/test_hook_dispatcher.py`            |
| Tracked-root candidate discovery       | existing local + project tracking rows, empty registry                                               | valid roots are reported once with cleanup commands; repeat leaves `projects.json` absent/empty and never opens root hook files              | `tests/src/install/test_hook_migration.py`             |
| User tracking strict abort             | unreadable/invalid global installation tracking plus a writable user target                          | user enable/sync fails before changing user settings or tracking                                                                             | `tests/src/install/test_hook_migration.py`             |
| Registry isolated from user enable     | corrupt/newer registry plus a valid user target and tracked legacy root                              | user transition/reporting does not read or write the registry; dispatcher retains its existing fail-open behavior                            | `tests/src/cli/test_extension_enable.py`               |
| Registry strict at cleanup             | corrupt/newer registry plus a selected legacy root                                                   | cleanup exits non-zero before selected-root, user, tracking, or registry writes                                                              | `tests/src/cli/test_extension_enable.py`               |
| Stale tracking row                     | missing root and v1 row with no project path                                                         | row is reported, not enrolled, guessed, or deleted; user dispatcher installation is not suppressed                                           | `tests/src/install/test_hook_migration.py`             |
| Selected-root strict abort             | incompatible pin or malformed/unreadable selected-root settings/config plus a healthy unrelated root | `cleanup-project --root ... --yes` exits non-zero before selected-root/user writes and never opens or changes the unrelated root             | `tests/src/cli/test_extension_enable.py`               |
| Final activation ordering              | unenrolled legacy root plus an installed user dispatcher                                             | call order is legacy removal -> clean scan -> user transition -> enrollment; ambient dispatch becomes active only at enrollment              | `tests/src/cli/test_extension_enable.py`               |
| Historical shape retention             | frozen released legacy shape while the current preset fixture has different matcher/timeout bytes    | historical entry remains eligible by the additive migration inventory; unknown shapes remain report-only                                     | `tests/src/install/test_hook_migration.py`             |
| Tracked Claude cleanup                 | project settings with tracked bare hooks plus status line, permissions, and unrelated hook           | only canonical tracked hook entries disappear; all non-hook state and installation files/modules survive                                     | `tests/src/install/test_hook_migration.py`             |
| User-modified tracked entry            | tracking value differs from current matcher/timeout/shape                                            | entry is retained and reported unresolved; no handler-only deletion                                                                          | `tests/src/install/test_hook_migration.py`             |
| Legacy-writer fallback                 | selected root with an untracked exact known-released direct-hook shape                               | eligible Forge-only entries are removed after backup; current dispatcher and unrelated entries remain                                        | `tests/src/install/test_hook_migration.py`             |
| Operation-scoped ambiguity guard       | ambiguous selected-root wrapper plus another ambiguous tracked root                                  | selected cleanup preserves the wrapper, exits non-zero, and does not claim success; the other root is untouched and cannot block user enable | `tests/src/cli/test_extension_enable.py`               |
| Tracking/add-payload reconciliation    | tracked project installation with hooks plus status line                                             | hook module/entries disappear from manifest and newest `.forge-added`; later disable removes only remaining owned state                      | `tests/src/install/test_installer.py`                  |
| Same-user-file duplicate               | `enable --scope user` and `sync --scope user` with a safe bare user hook beside the dispatcher       | each entry point uses the shared user transition; legacy sibling is removed and one logical user registration remains                        | `tests/src/cli/test_extension_enable.py`               |
| Codex marker cleanup                   | selected project config with balanced Forge block plus unrelated TOML                                | backup exists; only marker block is removed; unrelated bytes remain                                                                          | `tests/src/install/test_codex_hooks.py`                |
| Codex malformed/manual state           | partial marker or Forge command outside markers                                                      | state is retained and reported; no blind command deletion or false success                                                                   | `tests/src/install/test_codex_hooks.py`                |
| User module preservation               | existing user installation with commands/skills plus migrated runtime hooks                          | runtime modules are unioned without deleting or reinstalling unrelated modules/files                                                         | `tests/src/install/test_installer.py`                  |
| Remove-first failure                   | selected-root cleanup succeeds, then user dispatcher write or final enrollment fails                 | command exits non-zero, reports hooks-off recovery, backups remain, and no new ambient double-fire is created                                | `tests/src/cli/test_extension_enable.py`               |
| Preview/apply contract                 | migratable root, first without and then with `--yes`                                                 | preview changes no bytes; apply performs listed actions; third run is an idempotent no-op                                                    | `tests/src/cli/test_extension_enable.py`               |
| Doctor cleanup state                   | unresolved legacy-only, duplicate, coexistence, and clean fixtures                                   | human/JSON expose independent cleanup-required and double-fire state while keeping existing fields stable                                    | `tests/src/install/test_doctor.py`                     |
| Status-line cleanup state              | lone legacy source, genuine duplicate, coexistence, and clean fixtures                               | lone legacy is not `HOOKx2`; duplicate remains `HOOKx2`; the independent cleanup indication stays fail-open/default-off                      | `tests/src/cli/statusline/test_statusline_registry.py` |
| Full Docker migration                  | pre-T5 project/user settings + tracking + Codex block in isolated home                               | legacy source is removed before selected-root enrollment; afterward one user dispatcher source runs and unrelated state stays coherent       | `tests/integration/docker/test_installer.py`           |
| Host hook reachability after migration | migrated project followed by a managed real-Claude session                                           | dispatcher-backed SessionStart/Stop effects occur from user scope; no project hook block is required                                         | `tests/integration/docker/test_real_claude_hooks.py`   |

- [ ] Focused unit suite:
  `uv run pytest tests/src/install/test_hook_migration.py tests/src/install/test_hook_dispatcher.py tests/src/install/test_installer.py tests/src/install/test_hooks.py tests/src/install/test_codex_hooks.py tests/src/cli/test_extension_enable.py tests/src/install/test_doctor.py tests/src/cli/statusline/test_statusline_registry.py -q`.
- [ ] Command-tree/output/env-vocabulary guards:
  `uv run pytest tests/src/cli/test_command_tree_invariants.py tests/src/cli/test_output.py tests/src/cli/test_output_streams.py tests/src/cli/test_env_vocabulary.py -q`.
- [ ] Full unit suite: `make test-unit`.
- [ ] Required installer integration: `./scripts/test-integration.sh tests/integration/docker/test_installer.py -v`.
- [ ] Required targeted real-Claude hook integration:
  `./scripts/test-integration.sh tests/integration/docker/test_real_claude_hooks.py -k migration -v` (name the final
  test so the selector is stable).
- [ ] Full quality gate: `make pre-commit`.

## Phase 7 — Documentation and closeout

- [ ] Update `design.md` §3.10/§5.1 with the shipped migration ordering, explicit per-root mutation boundary,
  operation-scoped duplicate guard, and transient hooks-off recovery contract.
- [ ] Update `design_appendix.md` §C.2–C.6 with tracked-root candidate discovery, final selected-root enrollment, Claude
  tracked/fallback cleanup, Codex marker cleanup, tracking reconciliation, and re-trust behavior.
- [ ] Add `forge extension cleanup-project` to `docs/cli_reference.md` and document preview/`--yes` behavior.
- [ ] Update wheel-user Day 1/recovery guidance in `docs/end-user/README.md`, `docs/end-user/hook.md`, and
  `docs/end-user/config.md`; update QA/walkthrough extension-hook checks for a pre-T5 migration fixture.
- [ ] Update the epic checklist: mark T6 shipped, record member-level evidence for seams 1/2/4, and advance the
  remaining cursor to T8 (or record the epic closeout decision if T8 stays parked/out of the live member set). Do not
  tick the epic seam boxes during member closeout; those boxes tick only when the epic itself closes.
- [ ] Add a compact `docs/board/change_log.md` entry only after implementation is complete, with Goal / Key changes /
  Verification.
- [ ] Propose any durable migration invariant for `docs/board/impl_notes.md`; promote it only after human review.
- [ ] After merge, move this card `doing/ -> done/`, repoint the epic forward-link and every inbound board link, and run
  a relative-link/stale-lane sweep.

## Review blockers

- Phase 0 D1–D6 require maintainer approval.
- In particular, D2 now withholds cross-repository mutation authority from user-scope lifecycle commands; D1 freezes
  historical eligibility, D5 scopes the completion guard to the selected operation, and D6 treats enrollment as the
  final activation write rather than discovery bookkeeping. Implementation must not widen or reorder those boundaries
  from the old card alone.
- The checklist intentionally stops before product code until that review is complete.
