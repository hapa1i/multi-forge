# Execution checklist: forge_project_compat_mutator_sweep

Card: [`card.md`](card.md). Standalone follow-up split from T7
[`forge_project_compat`](../../done/forge_project_compat/card.md); not a member of
[`epic_global_forge_runtime`](../../doing/epic_global_forge_runtime/card.md).

## Current focus

**Closed on `main` 2026-07-12 after PR #98 merged at `aa45114d`.** D1-D8 and every classified mutator shipped. Unit,
pre-commit, and all runnable targeted integration checks passed; the isolated real-Codex bridge remains credential-gated
as recorded below, with its no-skip contract intact and no product change pending.

## Completion contract (binding for closeout)

The card requires every remaining project-state mutator to be **guarded or narrowly exempted with rationale**
([`card.md`](card.md) Goal). Classification categories are therefore exactly: **already-guarded**,
**wire-in-this-sweep**, and **exemption-with-rationale**. There is **no deferred category**: any family this card will
not cover requires (a) an accepted follow-up card linked at its current board path and (b) an explicit goal narrowing
recorded on this card -- both before the card may move to `done/`.

## Accepted framing (from T7 -- do not relitigate)

- `required_forge` is a fail-clear guardrail, not a version manager (epic D1). Missing `.forge/project.toml` is
  compatible/unconstrained -- no warning, no auto-create.
- D-T7-a matrix: command paths fail closed; session/context hook readers fail open with a degraded diagnostic; doctor is
  the authoritative user-facing surface.
- Reuse `src/forge/install/project_compat.py`; no reparsing of `.forge/project.toml` at call sites. Small named guard
  points, not checks embedded in leaf mutation bodies.
- T8 resolved: `FORGE_DEV` adds no compatibility bypass; hook-path pin enforcement is this sweep's scope.
- **Strict reader is not an enforcer.** A refusal path must call `enforce_project_compatibility()`, or call
  `check_project_compatibility()` and explicitly reject `compatible=False`. `try/except` around the strict reader alone
  is incorrect because a valid version mismatch returns a result rather than raising. The lenient
  `check_project_compatibility_for_hook()` helper is only usable for warn-and-proceed paths.

## Scope rules (binding)

1. **Target-state-owner rule:** a mutation check keys on the Forge root that owns the state being changed, never merely
   the caller's CWD. Named session operations resolve workspace-wide; Codex resume is cross-CWD by design; `fork --into`
   mutates the equivalent Forge root in another checkout.
2. **Three postures:** explicit command paths fail closed; session/context hooks proceed after one debug diagnostic per
   invocation; background/detached work refuses the incompatible write without changing an unrelated foreground
   command's exit status.
3. **Operation semantics beat transport:** `%` mutations and WorktreeCreate arrive through hook commands but are
   explicit user-requested mutations, so they use the command posture. Read-only `%` commands remain unaffected.
4. **Multi-root commands:** skip each incompatible root, continue compatible roots, report every refusal, and exit
   nonzero if any requested target was refused or failed. Report structured refusal fields wherever the command already
   has a JSON surface. Automatic retention uses the same per-root skip without changing the foreground command's exit.
   `--force` never bypasses `required_forge`.
5. **Global-only state:** proxy/backend registries and read-time self-healing of the derived session/active indexes are
   not Forge-root-owned durable state and are narrowly exempt. Paired index writes still inherit the guard of the
   project mutation that causes them. When a mixed operation such as `forge clean` includes global and project-owned
   objects, only the project-owned objects are compatibility gated.

## Grounding (verified against code, 2026-07-12)

| Fact                                                                                                                                               | Evidence                                                                                                                                                                                                                                                      |
| -------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Existing enforcer callers cover session CWD guards + extension lifecycle                                                                           | `cli/guards.py:53,70,114,125`; `cli/extensions.py:588,765,890,960,1066`                                                                                                                                                                                       |
| Strict mismatch returns `compatible=False`; malformed/unreadable/unsupported states raise                                                          | `install/project_compat.py:75-127`; enforcer `:172-191`                                                                                                                                                                                                       |
| The lenient hook helper has zero production callers                                                                                                | `install/project_compat.py:138`; only install-unit tests use it                                                                                                                                                                                               |
| Hook manifest writes flow through `SessionStore.update`, but hook project writes also include artifacts, semantic shadow files, and Codex receipts | `cli/hooks/commands.py:129,177,329,446,836,872,924,1108`; `session/hooks/session_start.py:352,439,468`; `cli/hooks/verification.py:171-253`; `policy/semantic/plan_check.py:591-610`; `policy/semantic/shadow.py:212-293`; `session/codex_handoff.py:136-202` |
| `resolve_session_store` serves hook reads, hook writes, Codex receipts, and `%` mutations with different contracts                                 | `session/hooks/session_start.py:177-203`; `%` handlers `cli/hooks/direct_commands.py:682-985,1275-1329`                                                                                                                                                       |
| Mutating `%policy supervisor` forms write through shared policy ops                                                                                | `cli/hooks/direct_commands.py:754-920`; `core/ops/policy.py:195,230,241,254,288,320,348`                                                                                                                                                                      |
| Named session resolution is workspace-wide and returns the target store                                                                            | `core/ops/session.py:302-326`; `core/ops/resolution.py:37-110`                                                                                                                                                                                                |
| Startup index drain writes `.forge/search-index` before the requested leaf command                                                                 | `cli/main.py:174-247`, invoked at `:401-407`                                                                                                                                                                                                                  |
| Queue handlers can only succeed/delete or raise/increment; processing slices a sorted batch before dispatch                                        | `core/workqueue/types.py:55-60`; `core/workqueue/queue.py:375-385,469-495`                                                                                                                                                                                    |
| Session clean/retention, named delete, and top-level clean use three distinct mutation loops                                                       | `session/cleanup.py:109-208`; `cli/session_manage.py:203-279`; `core/ops/gc.py:761-871`                                                                                                                                                                       |
| Managed `--worktree` creation checks only the source before creating/remapping a target and writing state                                          | `session/manager.py:459-554,629-665,1218-1254,1320-1348`                                                                                                                                                                                                      |
| WorktreeCreate creates the checkout before enrollment/install; this repo ignores `.forge/` and the config copier excludes the pin                  | `cli/hooks/commands.py:932-1043`; `.gitignore:84`; `session/worktree/config_copy.py:21-33`                                                                                                                                                                    |
| Session/active index reads can prune stale global rows before applying project filters                                                             | `session/index.py:160-232`; `session/active.py:209-263`                                                                                                                                                                                                       |
| Team-supervisor hooks can freeze a lane in the resolved project store                                                                              | `cli/hooks/commands.py:1743-1779`; `cli/consumer_lane_freeze.py:42-67`                                                                                                                                                                                        |
| Memory-writer `run_cmd` is a Click callback: normal return exits 0; worker failure raises `SystemExit(1)`                                          | `cli/memory_writer.py:39-72,113-132`                                                                                                                                                                                                                          |
| Memory-writer project writes are reports/docs plus a possible lane freeze                                                                          | `session/memory_writer.py:750-782`; `cli/consumer_lane_freeze.py:42-67`                                                                                                                                                                                       |
| Proxy/backend registry writes are global `~/.forge` state, not Forge-root state                                                                    | `proxy/proxies.py:216,254`; `proxy/proxy_orchestrator.py:153`; `backend/registry.py:113`; `backend/creation.py:13`                                                                                                                                            |
| `fork --into` derives `target_checkout_root / parent.relative_path`, while routing proxies may start before the manager call                       | `session/manager.py:1135-1173`; `cli/session_fork.py:573-576,651-666`                                                                                                                                                                                         |
| No full-CLI test currently exercises the pin through `require_repo_root`/`require_main_repo_root`                                                  | `tests/src/cli/test_guards.py` tests CWD/worktree validation only                                                                                                                                                                                             |

## Mutator classification (Phase 0 decision record)

| Family                        | Entry points                                                                                                            | Classification           | Guard/rationale                                                                                                                                                                                       |
| ----------------------------- | ----------------------------------------------------------------------------------------------------------------------- | ------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Extension lifecycle           | `extension enable/sync/cleanup-project/disable`                                                                         | already-guarded          | Direct enforcer calls at the selected project root.                                                                                                                                                   |
| Same-root session creation    | local `session start`, `incognito`, and same-root fork                                                                  | already-guarded          | Existing repo-root guards check the state-owning CWD before creation. Full-CLI coverage is still owed.                                                                                                |
| Managed worktree creation     | Claude/Codex session start or incognito with `--worktree`; `session fork --worktree`                                    | wire-in-this-sweep       | Before stale force replacement, check its root, exact future commit, and branch safety; after creation, recheck the target before config/state/install writes and roll back refusal.                  |
| Targeted session lifecycle    | local Claude `session resume`/`--fresh`/rewind; cross-CWD Codex resume                                                  | wire-in-this-sweep       | Strict-check the resolved target session store's Forge root before any manifest/artifact/routing mutation. Claude resume remains project-scoped; Codex resume may target its recorded root cross-CWD. |
| Session settings              | `session set/reset`, `session memory enable/disable`, `session lane set/clear`                                          | wire-in-this-sweep       | Strict-check the resolved target store, including named cross-CWD operations.                                                                                                                         |
| Transfer state                | `session transfer regenerate/edit`                                                                                      | wire-in-this-sweep       | Strict-check the parent/notes target root before generation or launching the editor.                                                                                                                  |
| Policy CLI state              | `policy enable/disable`; supervisor `set/off/on/remove/reload/cascade`                                                  | wire-in-this-sweep       | Strict-check the resolved target store before proxy start or store update. Recovery-shaped leaves remain strict because an incompatible serializer is the corruption risk the pin protects against.   |
| Project memory authoring      | `memory track`, `memory passport remove`                                                                                | wire-in-this-sweep       | Strict-check the current Forge root before editing repo docs or creating shadow files.                                                                                                                |
| Shadow curation               | `memory shadows review --curate`                                                                                        | wire-in-this-sweep       | Strict-check the resolved session/report root before dispatch, lane freeze, or report write. Reads from other roots remain reads.                                                                     |
| Search mutation               | `search rebuild-index`, `search clean --yes`                                                                            | wire-in-this-sweep       | Strict-check the current Forge root before replacing/pruning stores. Dry-run remains readable and labels what apply would refuse.                                                                     |
| Session deletion              | named `session delete` and project-scoped `--all`                                                                       | wire-in-this-sweep       | Single target refuses atomically; multi-target uses the binding per-root partial-result rule.                                                                                                         |
| Session cleanup               | `session clean --yes`, automatic retention                                                                              | wire-in-this-sweep       | Shared cleanup core skips incompatible roots; explicit command reports + exits nonzero, automatic retention logs and preserves foreground exit.                                                       |
| Top-level cleanup             | `forge clean --yes` (`project/workspace/all`)                                                                           | wire-in-this-sweep       | Gate every project-owned item by its owning root; global-only categories remain eligible. Text and JSON report skipped roots.                                                                         |
| Existing-worktree fork        | `session fork --into`                                                                                                   | wire-in-this-sweep       | Strict-check `target_checkout_root / relative_path` before proxy-producing preflight and again in the manager before target mutation.                                                                 |
| Hook lifecycle/project writes | SessionStart, plan/artifact capture, Stop/verification, compaction, subagent/team hooks, policy confirmed/shadow writes | wire-in-this-sweep       | Lenient check once per hook invocation against the resolved target root; proceed with debug diagnostic and unchanged wire.                                                                            |
| Codex SessionStart files      | pending-context consume, delivery/observation receipts                                                                  | wire-in-this-sweep       | Same lenient invocation check; preserve the explicit no-stderr contract.                                                                                                                              |
| Direct `%` mutations          | policy enable/disable/supervisor forms; `%cancel-verification`                                                          | wire-in-this-sweep       | Strict-check the resolved store and return the existing `decision:block` JSON with a compatibility reason; no write. Read-only `%` forms are unaffected.                                              |
| WorktreeCreate hook           | checkout creation, config copy, project enrollment, extension install                                                   | wire-in-this-sweep       | Command posture. Strict source-root precheck before `git worktree add`; target-root postcheck before project writes, with rollback on target refusal. Never auto-copy the pin.                        |
| Memory writer                 | detached `memory-writer run`                                                                                            | wire-in-this-sweep       | Intentional exit-0 refusal with recorded state-specific skip; no runner, lane freeze, report, or doc write.                                                                                           |
| Startup index drain           | pending `index` marker                                                                                                  | wire-in-this-sweep       | Strict-check synchronously before store writes; refusal follows the existing bounded retry-to-failed queue contract.                                                                                  |
| Detached shadow drain         | pending `shadow` marker and hidden worker entry                                                                         | wire-in-this-sweep       | Strict-check before `Popen` and again at worker entry; refusal follows the existing bounded retry-to-failed queue contract.                                                                           |
| Proxy/backend registries      | proxy create/edit/set/delete; backend create/start/stop/delete/reconcile                                                | exemption-with-rationale | These mutate global `~/.forge` runtime/catalog state and have no Forge-root owner. Characterization tests pin the exemption.                                                                          |
| Global index self-healing     | stale-row pruning in `IndexStore.list_sessions` and `ActiveSessionStore.get/list`                                       | exemption-with-rationale | These derived global caches prune only rows proven stale. Filtered reads may self-heal another root; paired add/remove operations remain ordered behind the owning project's guard.                   |

## Phase 0 decisions D1-D8

- [x] **D1a -- lifecycle/Codex hook writes (lenient).** After resolving the target store/root and before the first
  project-owned write, call one named lenient diagnostic helper per invocation. Missing/compatible is silent;
  incompatible/malformed/unreadable/unsupported state emits one `logger.debug` event and proceeds. Never write the
  diagnostic to stdout/stderr: Codex non-delivery paths stay byte-silent, and doctor remains the authoritative
  user-facing surface. The invocation check covers manifest updates, artifact copies, semantic shadow/cascade files, and
  Codex pending-context/receipt writes. It does not live in `SessionStore.update` or unconditionally in
  `resolve_session_store`, which also serve strict commands and reads.
- [x] **D1b -- `%` command mutations (strict).** Cover `%policy enable|disable`, every mutating supervisor form
  (`<target>`, `on`, `off`, `remove`, `reload`, `cascade on|off`), and `%cancel-verification`. Use the strict enforcer
  at the resolved store root before any op call. The existing "must work when state is broken" cancel contract refers to
  malformed session overrides; it does not authorize a version-pin bypass. Refusal uses the existing
  `{"decision":"block"}` transport, names the pin/state and recovery, and writes nothing.
- [x] **D2 -- memory-writer refusal.** Immediately after `effective_root`, call the strict enforcer before manifest
  reads or dispatch. Any refusal records an upstream `skipped` outcome with reason code `project_compatibility_refused`
  and the actual compatibility state (`incompatible`, `malformed`, `unsupported_schema`, or `unreadable`), then returns
  normally (exit 0). No `run_memory_writer`, lane freeze, report, or doc write occurs.
- [x] **D3 -- global registry/derived-cache exemptions.** Proxy/backend registry mutations remain available under an
  incompatible CWD pin because their state owner is `~/.forge`, not the CWD project. Read-time pruning of stale global
  session/active rows is also exempt: it is derived-cache repair, not a project-local write, and must not read pins for
  unrelated roots before applying filters. Pin both registry families plus cross-root stale-row pruning. Paired
  index/active writes remain behind the owning operation's guard. Startup side effects are governed independently by
  D7/D6.
- [x] **D4 -- `fork --into` target-root pin.** Resolve the parent index entry early, derive
  `target_checkout_root / parent.relative_path`, and enforce before routing/supervisor proxy preflight. Retain a
  manager-level defense before stale-target cleanup or writes. Refusal is atomic: no proxy start, child manifest, global
  index/active row, transfer/rewind artifact, target replacement, or other orphaned state.
- [x] **D5 -- lenient helper disposition.** D1a gives `check_project_compatibility_for_hook` production callers. If the
  implementation instead introduces an equivalent named wrapper, the wrapper must delegate to that helper; do not leave
  two lenient contracts.
- [x] **D6 -- multi-root behavior.** Single-target commands abort before mutation. Explicit batches skip every
  incompatible root, continue compatible roots, report each skipped target, and exit 1 when any target was
  skipped/failed. Existing JSON surfaces include structured target/root/state fields; no new JSON option is implied.
  Preview output marks targets apply would refuse. Automatic retention skips/logs per root and never changes the
  foreground exit. `--force` does not bypass the pin. `forge clean` may still clean global-only
  proxy/backend/dead-installation categories while refusing project-owned items.
- [x] **D7 -- background marker behavior.** Index and shadow queue handlers run the strict check synchronously. A
  refusal raises a compatibility error through the existing queue path: `attempt_count` increments, `last_error` records
  the pin/state, and the marker moves to `failed/` at `MAX_ATTEMPTS`. This is bounded and preserves queue fairness; no
  new leave-in-place/deferred outcome is introduced. The foreground command remains successful. Recovery after
  installing a compatible Forge is explicit: rebuild search with `forge search rebuild-index`; shadow candidates remain
  available for the next Stop/re-enqueue or a compatible worker run. The memory-writer handoff is different: its marker
  is already consumed when the detached process performs D2's recorded exit-0 skip.
- [x] **D8 -- recovery wording.** Centralize provenance-neutral base wording: run a Forge version satisfying the pin, or
  edit/reset project state. Callers in `project_compat.py`, `cli/guards.py`, and `cli/extensions.py` must share it
  rather than hard-code "global Forge." When detectable, add context: a `FORGE_DEV` change requires relaunch; a sidecar
  must use an image containing a satisfying Forge. Tests pin normal, `FORGE_DEV`, and sidecar wording without printing
  secrets.

## Phase 1 -- Hook-wire mutators: lifecycle writes (D1a) + `%` commands (D1b)

- [x] Add the named D1a invocation diagnostic and wire all classified lifecycle/Codex project-write paths. Assertions:
  incompatible/malformed state proceeds; one debug event per invocation; missing/compatible is silent; stdout, stderr,
  exit code, and JSON contracts are unchanged.
- [x] Wire D1b before every mutating direct-command op. Assertions: each incompatible/malformed target returns
  `decision:block` with recovery; no override/intent write; read-only `%policy status/check/supervisor` and other
  read-only direct commands retain current behavior.
- [x] Unit tests: new `tests/src/cli/hooks/test_project_compat_hooks.py`, existing Codex hook suites,
  `tests/src/cli/test_artifact_hooks.py`, `tests/src/cli/hooks/test_new_hooks.py`, `tests/src/cli/test_hooks.py`, and
  `tests/src/cli/test_user_prompt_dispatcher.py`. Parameterize every mutating hook entry point: SessionStart,
  plan/exit-plan, Stop/StopFailure, pre/post-compact, subagent-stop, teammate-idle/task-completed, policy hooks, and
  Codex receipts. Parameterize `%policy enable`, `%cancel-verification`, one supervisor set/on path, and one off/remove
  path. Cover SessionStart compact/rollover so multiple writes do not duplicate the diagnostic.
- [x] Extend and run integration in phase:
  `./scripts/test-integration.sh tests/integration/cli/test_artifact_hooks_integration.py`,
  `./scripts/test-integration.sh tests/integration/cli/test_user_prompt_dispatcher_integration.py`, and
  `./scripts/test-integration.sh tests/integration/docker/test_policy_hooks.py`.

## Phase 2 -- Detached/background mutators (D2 + D7)

- [x] Guard `memory-writer run` per D2 and expose/reuse one outcome-recording seam. Assert exit 0, state-specific
  `project_compatibility_refused`, no runner call, no lane freeze, and no doc/report writes for incompatible, malformed,
  unsupported-schema, and unreadable pins; compatible/missing reaches existing behavior.
- [x] Guard startup index work before the first store write. Assert foreground exit unchanged, attempts/last-error
  update, move to `failed/` at the normal limit, and later compatible markers are not permanently starved.
- [x] Guard the shadow marker before spawn and the hidden worker at entry. Assert no `Popen` or candidate rename/write
  on refusal; the queue records the same bounded failure state.
- [x] Unit tests: `tests/src/cli/test_memory_writer_cli.py`, `tests/src/cli/test_startup_queue.py`,
  `tests/src/core/workqueue/test_queue.py`, and `tests/src/cli/test_policy_shadow.py`.
- [x] Repair the startup integration baseline before extending it: corrupt JSON moves immediately to `failed/`, and the
  foreground assertion must require a known-success command to exit 0 (not the tautology `returncode >= 0`).
- [x] Extend and run integration in phase:
  `./scripts/test-integration.sh tests/integration/cli/test_handoff_integration.py` and
  `./scripts/test-integration.sh tests/integration/cli/test_startup_queue_integration.py`.

## Phase 3 -- Explicit command mutators + target-root enforcement

- [x] Add one reusable strict target-root guard and apply it to targeted session lifecycle/settings, transfer, policy,
  memory/passport, curation, and search families in the classification table. Guard before proxy dispatch, editor
  launch, lane freeze, or filesystem write. Do not place it in shared read resolution or `SessionStore.update`.
- [x] Split lifecycle CWD-shape validation from compatibility enforcement where necessary. Named cross-CWD resume must
  still validate its invocation context, but must not let an incompatible caller pin preempt the resolved target-root
  decision; local start/incognito/fork continue treating CWD as their target root.
- [x] Add both target-root directions where the command supports cross-CWD targeting: incompatible target + compatible
  caller refuses; compatible target + incompatible caller proceeds. Cover named `session set`, Codex resume, policy
  mutation, transfer, and curation; cover local Claude resume separately and preserve its project-scoped refusal.
- [x] Implement D4 at the early CLI seam plus manager defense. Use a nested-Forge-project fixture and assert the
  complete no-side-effect set, including no proxy start.
- [x] Implement WorktreeCreate's source precheck and target postcheck. Derive the source Forge root and its path
  relative to the checkout; use the corresponding target root for project enrollment/install. Do not copy ignored
  `.forge/project.toml`. Source refusal creates nothing; target refusal rolls back the new checkout/branch.
- [x] Add the same post-create target defense to manager-created worktrees for Claude/Codex start, incognito, and fork.
  Run it after checkout creation but before runtime-config copy, manifest/index creation, enrollment, or extension
  install. A tracked target pin may differ from an uncommitted source working copy; refusal rolls back checkout/branch.
- [x] Guard memory/passport and search writes at their current-root seam. Dry-run/read leaves stay readable; apply
  leaves refuse before the first write.
- [x] Unit tests: `tests/src/cli/test_session_overrides.py`, `test_session_resume.py`, `test_session_codex.py`,
  `test_session_rewind_cli.py`, `test_session_memory.py`, `test_session_lane.py`, `test_transfer_cli.py`,
  `test_policy_enable.py`, `test_policy_supervisor.py`, `test_memory.py`, `test_search.py`, `hooks/test_new_hooks.py`,
  `test_session_fork.py`, `tests/src/session/test_fork_into.py`, and `tests/src/session/test_manager_integration.py` as
  relevant to the touched seams.
- [x] Run the Phase 3 integration matrix and record any environment-gated result:
  `./scripts/test-integration.sh tests/integration/cli/test_session_commands_integration.py`,
  `./scripts/test-integration.sh tests/integration/cli/test_search_workflow_integration.py`, and
  `./scripts/test-integration.sh tests/integration/docker/test_project_identity.py`. Also run
  `./scripts/test-integration.sh tests/integration/docker/test_rewind_native_contract.py`; for Codex resume, run
  `uv run forge runtime preflight codex` followed by
  `./scripts/test-integration.sh tests/integration/core/test_claude_to_codex_resume.py`. Validation on 2026-07-12 passed
  the session, search, project-identity, and rewind suites plus host Codex preflight. The real bridge command was
  invoked but failed at the test's Codex readiness gate before the bridge body ran: its isolated `CODEX_HOME` requires
  `CODEX_API_KEY`, and subscription auth from the host Codex store is intentionally unavailable there. This accepted
  closeout limitation changes no product behavior; the no-skip test was not weakened.

## Phase 4 -- Multi-root commands + global exemption + owed coverage

- [x] Implement D6 separately in named delete, shared age cleanup/automatic retention, and top-level GC. Add explicit
  `skipped_project_compatibility` fields to the respective result shapes, carrying target/root/state; preserve stable
  text output and the existing `forge clean --json` recovery shape.
- [x] For `forge clean`, associate each project-owned item with its owning Forge root before deletion; global-only items
  remain eligible. Assert mixed global/project cleanup never widens or silently deletes a refused project item.
- [x] Record and pin D3: `forge proxy create <template> --no-start` and `forge model backend create litellm` succeed
  under an incompatible CWD pin. Add cross-root characterization showing a filtered session/active-index read may prune
  a proven-stale global row for an incompatible root, while paired rows for a refused live mutation remain unchanged.
- [x] Close the T7 coverage gap with a full-CLI incompatible `forge session start` test. Assert exit 1, shared recovery
  wording, and no manifest/index/active entry.
- [x] Unit tests: `tests/src/cli/test_session_start_delete.py` (named/batch delete + start),
  `tests/src/cli/test_session_list_show.py` and `tests/src/session/test_cleanup.py` (manual/automatic cleanup),
  `tests/src/cli/test_gc.py` and `tests/src/core/ops/test_gc.py` (text + JSON GC), `tests/src/session/test_index.py`,
  `tests/src/session/test_active.py`, plus proxy/backend command tests. Cover named delete and project-scoped `--all`;
  cover `session clean` preview and `forge clean` human/JSON previews as well as apply.
- [x] Extend and run integration in phase:
  `./scripts/test-integration.sh tests/integration/cli/test_session_commands_integration.py` and
  `./scripts/test-integration.sh tests/integration/docker/test_session_lifecycle.py`.

## Phase 5 -- Design-doc + end-user sync

- [x] `design.md` project-identity paragraph: command mutations check the target state owner's root; hooks diagnose
  leniently; background work refuses without failing foreground; global-only registries are exempt; WorktreeCreate does
  not copy an ignored pin.
- [x] `design_appendix.md` Project compatibility pin: record strict-reader-versus-enforcer semantics, the three
  postures, D6 partial-result/exit contract, D7 bounded marker behavior, and D3 exemption.
- [x] End-user docs: update `config.md`, memory/session/hook guides, `search.md`, and `policy.md` for refusals,
  recovery, failed-marker behavior, WorktreeCreate, and global exemptions.
- [x] Implement D8's shared recovery formatter and update every caller/test. The T8 no-bypass resolution remains
  reflected in the T7 done card, and the reviewed target-owner/posture/recovery invariants are promoted to
  `impl_notes.md` at closeout.

## Acceptance tests

| Test                         | Fixture                                                         | Assertion                                                                           | Test file                                                                                                                   |
| ---------------------------- | --------------------------------------------------------------- | ----------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| Hook lifecycle fail-open     | incompatible/malformed pin; Claude artifact hook                | write proceeds; one debug diagnostic; wire unchanged                                | `tests/src/cli/hooks/test_project_compat_hooks.py`                                                                          |
| Hook non-manifest writes     | policy shadow + Codex receipt paths                             | lenient diagnostic covers write; Codex stdout/stderr byte-unchanged                 | `tests/src/cli/hooks/test_codex_session_start.py`; `test_codex_policy_check.py`                                             |
| Direct commands fail closed  | incompatible pin; policy enable + supervisor mutations + cancel | `decision:block`; no target-store mutation                                          | `tests/src/cli/test_user_prompt_dispatcher.py`                                                                              |
| Memory-writer refusal        | each strict refusal state                                       | exit 0; skipped outcome carries actual state; no runner/freeze/write                | `tests/src/cli/test_memory_writer_cli.py`                                                                                   |
| Queue bounded refusal        | five incompatible early markers + later compatible marker       | attempts/last-error/failed behavior is bounded; later work runs                     | `tests/src/core/workqueue/test_queue.py`; `tests/src/cli/test_startup_queue.py`                                             |
| Shadow no-spawn              | incompatible marker/root                                        | no `Popen`, rename, candidate write, or foreground failure                          | `tests/src/cli/test_startup_queue.py`; `tests/src/cli/test_policy_shadow.py`                                                |
| Target-root enforcement      | named `session set` from another CWD; both pin directions       | only the target root controls refusal                                               | `tests/src/cli/test_session_overrides.py`                                                                                   |
| Resume target guard          | local Claude target; Codex target outside caller root           | target pin refuses before launch/write; Codex inverse proceeds; Claude stays scoped | `tests/src/cli/test_session_resume.py`; `test_session_codex.py`                                                             |
| Command-family guards        | policy, transfer, memory/passport/curation, search              | first incompatible write/dispatch/editor launch is blocked                          | corresponding CLI suites named in Phase 3                                                                                   |
| Multi-name delete            | compatible + incompatible target roots                          | compatible deleted; incompatible kept/reported; exit 1; `--force` no bypass         | `tests/src/cli/test_session_start_delete.py`                                                                                |
| Manual/automatic cleanup     | old sessions across compatible/incompatible roots               | explicit partial report + exit 1; automatic skip preserves foreground exit          | `tests/src/cli/test_session_list_show.py`; `tests/src/session/test_cleanup.py`                                              |
| Top-level clean              | mixed project-owned + global items; text and JSON               | refused root untouched/reported; eligible global items handled                      | `tests/src/cli/test_gc.py`; `tests/src/core/ops/test_gc.py`                                                                 |
| `fork --into` atomic refusal | nested target Forge root; proxy flags supplied                  | exit 1 before proxy start; no child/index/transfer/target replacement               | `tests/src/cli/test_session_fork.py`; `tests/src/session/test_fork_into.py`; project-identity integration                   |
| Managed worktree refusal     | fresh mismatch; stale target/future HEAD/branch refusal         | fresh target rolls back; stale checkout/branch/dirty state survives every preflight | `tests/src/session/test_manager_integration.py`; `tests/src/session/test_fork_into.py`; session lifecycle integration       |
| WorktreeCreate refusal       | source mismatch; tracked target mismatch                        | source creates nothing; target failure rolls checkout/branch back; pin never copied | `tests/src/cli/hooks/test_new_hooks.py`                                                                                     |
| Family C proxy exemption     | incompatible CWD pin; proxy create `--no-start`                 | global registry mutation succeeds                                                   | `tests/src/cli/test_proxy_commands.py`                                                                                      |
| Family C backend exemption   | incompatible CWD pin; `backend create litellm`                  | global adapter config succeeds                                                      | `tests/src/cli/test_backend_commands.py`                                                                                    |
| Global self-heal exemption   | filtered read; stale row belongs to incompatible other root     | stale derived row is pruned; no project file or live paired row changes             | `tests/src/session/test_index.py`; `tests/src/session/test_active.py`                                                       |
| Cleanup previews             | incompatible roots in session-clean and top-level-clean preview | human/existing JSON output marks apply refusal; preview writes no project state     | cleanup + GC suites                                                                                                         |
| Session-start owed coverage  | incompatible current-root pin                                   | exit 1; no manifest/index/active entry                                              | `tests/src/cli/test_session_start_delete.py`                                                                                |
| Recovery wording             | normal + `FORGE_DEV` + sidecar contexts                         | shared neutral base wording plus applicable relaunch/image hint                     | `tests/src/install/test_project_compatibility.py`; `tests/src/cli/test_guards.py`; `tests/src/cli/test_extension_enable.py` |
| Doctor authority             | malformed/incompatible pin via `extension doctor --json`        | strict state and recovery visible even though hooks stay quiet                      | `tests/src/install/test_doctor.py`                                                                                          |
| Lenient helper has caller    | production tree after Phase 1                                   | helper has a production caller through the named D1a wrapper                        | Phase 1 wiring + install tests                                                                                              |

## Review rounds

- **Round 1 (2026-07-12, maintainer)** -- removed deferred-as-complete; established target-root and background postures;
  added implicit mutators, strict memory-writer states, nested `fork --into` atomicity, in-phase integration, backend
  characterization, and end-user/design coverage.
- **Round 2 (2026-07-12, maintainer)** -- corrected strict-reader semantics; mapped every known family to a concrete
  classification/phase; added direct supervisor mutations; replaced the unsafe leave-in-place queue proposal with the
  bounded retry-to-failed contract; corrected WorktreeCreate's ignored-pin premise; fixed D1a Codex-silent diagnostics;
  pinned D6 exit/force behavior, early D4 enforcement, state-specific D2 outcomes, shared D8 wording, and distinct
  acceptance coverage for delete/cleanup/GC.
- **Round 3 (2026-07-12, maintainer)** -- reclassified managed fresh-worktree creation for a target postcheck +
  rollback; narrowly exempted global session/active-index self-healing while keeping paired writes behind project
  guards; made all mutating lifecycle/team hooks explicit; and added manager, dispatcher, rewind, Codex, preview, and
  startup-baseline verification.
- **Round 4 (2026-07-12, maintainer)** -- found that stale managed-worktree force replacement ran before its target-pin
  check. Added pre-destroy checks for the stale root, exact replacement commit, and branch refusal conditions; pinned
  creation to that commit; retained the post-create defense; and added checkout/branch/dirty-state preservation plus
  incomplete-rollback coverage. Also closed the background warning wire leak, cached search-document ownership during GC
  detection, and documented JSON cleanup's nonzero apply result.

## Verification limitation

- The real Claude-to-Codex bridge integration was credential-gated: pytest isolates `CODEX_HOME`, so the host's ready
  subscription login is not visible and the no-skip test requires `CODEX_API_KEY`. PR #98 merged with that limitation
  disclosed; no product change is pending on the result, and the test was not weakened.

## Closeout

- [x] Every classification row is already guarded, wired, or exemption-with-rationale; any narrowing is recorded on the
  card with a linked accepted follow-up per the completion contract.
- [x] All non-credential-gated phase assertions and acceptance tests pass; `make test-unit` passes; every required
  targeted integration command and the isolated bridge limitation are recorded; `make pre-commit` passes.
- [x] `change_log.md` entry, including `forge clean --yes --json` exiting 1 on failures/skips; durable lessons promoted
  to `impl_notes.md` after human review (target-state-owner rule, three-posture split, strict-reader/enforcer
  distinction, bounded background refusal, and global exemption).
- [x] Move `doing/forge_project_compat_mutator_sweep/ -> done/`; repoint every inbound link, including the epic and
  T7/T8 done cards/checklists.
