# Checklist -- Session Op Layer Extraction

Execution plan for `card.md` (this dir). Branch: `session-op-layer`. This card is a staged, behavior-preserving
extraction of Claude session launch/resume logic out of the CLI layer, mirroring the Codex core-ops split.

## Current Focus

**Slice 1 complete (2026-07-02):** characterization safety net added, launch system-prompt resolution extracted into
`forge.core.ops.claude_session`, and the CLI-free model-pin support cluster moved into `forge.session.model_pin`. This
slice intentionally did not touch the dangerous `invoke_claude`/launcher seam; the card remains in `doing/` for Slice 2.

**Slice 2 op landed (2026-07-02):** 2a `ba30b4ea`, 2b bridge `3858b0d8`, then `start_claude_session` extracted
(`ea668220`) with an incognito characterization guard (`be9a62e4`). The op owns creation -> mutation -> launch ->
incognito-cleanup; the CLI renders via a `ClaudeStartPresenter` (9 hooks). The one remaining 2b item -- the bulk
`invoke_claude`/`SessionManager` patch-site repoint -- is **deferred to Slice 5 by design**: the op injects
`invoke=`/`manager=` through the `_sess()` shim, so those patch sites still resolve; the parent count drops when the
shim is retired, not now.

**Slice 3 landed (2026-07-02):** `resume_claude_session -> ClaudeResumeResult` owns the shared routing/model/UUID/launch
tail for the six Claude resume dispatch targets. The CLI still owns validation, mode-specific creation/prompt assembly,
and rendering through `_ClaudeResumeCliPresenter`.

**Slice 4 landed (2026-07-02):** 4a.1 deleted `_launch_claude_for_session` (`83b341fb`); 4a.2 extracted
`fork_claude_session`, unifying the four host closures (`ddb5648a`, edge-case pins `1e90ba74`); 4b unified fork
supervisor wiring onto core `_apply_supervisor_wiring` and moved the sidecar `is_sandboxed` write after prep
(`f7304a82`). All reviewed and committed.

**Slice 5 planned (scope A confirmed):** retire the `_sess()` / `_session_cli()` shim -- checklist below. Highest-churn
slice (256 patch sites); execution not started.

## Verified Baseline

Rechecked against the current tree before work began. Use these values, not the stale counts in `card.md`.

| Fact                                                  | Verified value                                                                        | Card claimed |
| ----------------------------------------------------- | ------------------------------------------------------------------------------------- | ------------ |
| `session_lifecycle.py` size                           | 2,497 lines                                                                           | --           |
| Parent `patch("forge.cli.session.<name>")` sites      | 270 single-line (+11 multiline), 13 files                                             | 255          |
| Patch concentration                                   | `invoke_claude` 146 + `SessionManager` 54 = 200/270 (74%)                             | --           |
| Split-module patches                                  | 49                                                                                    | 47           |
| `def _sess()` defs                                    | 4: `session_lifecycle.py`, `session_fork.py`, `session_codex.py`, `session_manage.py` | 4            |
| `_apply_and_persist_direct_model_override` call sites | 7                                                                                     | 5            |
| `core/ops/` importing `forge.cli`                     | none                                                                                  | --           |
| Manifest characterization test                        | missing                                                                               | --           |

## Slice 1 Tasks

- [x] Reconcile board cursor before starting: close `rewind_resume_strategy` and move it `doing/ -> done/`.
- [x] Accept this proposal: move `proposed/session_op_layer_extraction` to `doing/session_op_layer_extraction`.
- [x] Create this checklist with the corrected Slice 1 scope and baseline.
- [x] Add manifest characterization coverage before code movement:
  - start path: `forge session start --no-launch`.
  - resume path: one reconnect/fresh branch that exercises the resume manifest surface without launching real Claude.
  - compare normalized JSON strings without `sort_keys` so dataclass field order is pinned.
- [x] Add `src/forge/core/ops/claude_session.py` with `resolve_and_validate_system_prompt`.
  - The helper is CLI-free, not pure: it may create `cwd/.claude/forge.system-prompt.generated.md`.
  - It returns `Path | None`; the CLI converts to `str | None` at the launcher boundary.
  - Do not import `ExecutionContext` until the module actually uses it.
  - `--no-launch` + system-prompt validation remains CLI-owned by the early launch guard; the op does not duplicate it.
- [x] Add `src/forge/session/model_pin.py` and move the CLI-free support cluster intact:
  - `_proxy_supports_model_pin`.
  - `_apply_direct_model_env_if_supported`.
  - `_validate_proxy_model_pin`.
  - `_validate_direct_model_pin_for_routing`.
- [x] Keep UI-tangled persistence in `cli/session_model_pin.py`; no re-export shims for the moved support functions.
- [x] Rewire CLI callers:
  - `session_lifecycle.py` host launcher `_apply_direct_model_env_if_supported`.
  - `session_lifecycle.py` start-path `_validate_proxy_model_pin`.
  - `session_lifecycle.py` resume-path `_validate_direct_model_pin_for_routing`.
  - `session_fork.py` `_apply_direct_model_env_if_supported`.
- [x] Repoint tests that import the moved support functions.
- [x] Record post-slice patch counts: parent patches remain 270 single-line hits across 13 files; split-module patches
  remain 49.

## Slice 1 Assertions

- [x] `src/forge/core/ops/claude_session.py` imports no CLI modules and contains no Click/Rich/rendering/`sys.exit`.
- [x] `src/forge/session/model_pin.py` imports no CLI modules and contains no Click/Rich/rendering/`sys.exit`.
- [x] `src/forge/cli/session_lifecycle.py` line count does not increase above the 2,497-line baseline (post-slice:
  2,496).
- [x] Manifest characterization test is green before and after the extraction.
- [x] Passthrough model-pin behavior remains covered and green.
- [x] Behavior stays unchanged: same error text, same ordering, same manifest shape.
- [x] Follow-up fix: removed the dead op-level `no_launch`/`ForgeOpError` branch so future CLI cleanup cannot expose an
  uncaught traceback.

## Acceptance Tests

- [x] Layering grep passed empty:
  `grep -rn "from forge.cli\|import forge.cli" src/forge/core/ops/ src/forge/session/model_pin.py`.
- [x] CLI-free helper grep passed empty:
  `grep -nE "click|rich|console|sys\.exit|print_error|print_tip" src/forge/core/ops/claude_session.py src/forge/session/model_pin.py`.
- [x] Characterization: `uv run pytest tests/src/session/test_claude_session_manifest_characterization.py -q` -- 2
  passed.
- [x] Focused units:
  `uv run pytest tests/src/session/test_claude_session_manifest_characterization.py tests/src/session/test_direct_model.py tests/src/cli/test_session_model_pins.py tests/src/cli/test_session_commands.py tests/regression/test_bug_passthrough_model_pin.py -q`
  -- 241 passed.
- [x] Integration: `./scripts/test-integration.sh tests/integration/docker/test_session_lifecycle.py -v` -- 21 passed.
- [x] Pre-commit: `make pre-commit` -- passed.

## Slice 2 -- `start_claude_session` (interactive-launch op)

**Status:** planned (grounded by read-only exploration 2026-07-02; anchors verified against the current tree).

### Design decision (resolved by precedent -- not a fork)

Claude start is **interactive** (blocking child + terminal handover), unlike headless `codex_session.py`. Mirror
**`core/ops/codex_interactive.py::start_interactive_codex_session`**; do **not** reuse `core/invoker/` (headless-only).

- Signature:
  `start_claude_session(*, ctx, name, <routing/launch params injected by CLI>, announce=None, invoke=None) -> ClaudeSessionStartResult`
  (resolve `invoke or invoke_claude` in the body -- see P5 below for why the default is `None`, not `invoke_claude`).
- The op **owns** the blocking `run_with_active_session(runner=lambda: invoke(...))`. Pre-launch output is **not one
  render** (Nit 1): current start emits an ordered sequence inside the region the op will own -- created/routing block
  (`session_lifecycle.py:1085`), extension auto-install (`:1103`, itself printing), then the `--no-launch` early-exit
  render + `return 0` (`:1113`), and only then launch. Behavior preservation needs a **staged event contract** (e.g.
  `on_created` -> `on_extensions` -> `on_no_launch`/launch), not a single "right before run" `announce`: a lone callback
  would render the created block *after* extension install (a reorder). The op owns the control flow -- including the
  `--no-launch` branch (fire the no-launch render event, then `return exit_code=0` without launching, per `:1113-1115`);
  the CLI owns **rendering only** (Nit 4). Post-exit summary renders from the returned result
  (`since = operation_started_at`).
- Failures `raise ForgeOpError`; `StateCorruptedError`/`StateUnreadableError` propagate bare; rollback applies only
  **before** launch -- after launch "the session is the user's" (reconcile-what-you-can + warnings).
- Several seams **stay in the CLI** because they render: `_resolve_routing_from_cli` (renders + `sys.exit`s; the CLI
  resolves routing and injects the result) **plus** the three status/warn helpers in the map below. The op stays
  render-free -- it triggers pre-launch output via the `announce` callback and returns `warnings`.
- **Signature (P5):** use `invoke: Callable[..., int] | None = None` and resolve `invoke or invoke_claude` **in the
  body** (a call-time module global), NOT `invoke=invoke_claude` as a default. A default binds `invoke_claude` at
  import, so `patch("forge.core.ops.claude_session.invoke_claude")` would not take effect and the 146-site repoint would
  silently no-op. Late-binding keeps the repoint working. Same rule for `SessionManager` (call-time global, never a
  default).

### Relocation map (start-path seams -- verified)

| Primitive                                                                                                                                  | Current location                  | Status                                       | Action                                                                                                                                     |
| ------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------- | -------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `invoke_claude`                                                                                                                            | `session/claude/invoke.py:13`     | already core                                 | inject via `invoke=None` seam, resolve `invoke or invoke_claude` in body (P5)                                                              |
| `run_with_active_session`                                                                                                                  | `session/active.py:331`           | already core                                 | call directly                                                                                                                              |
| `SessionManager` / `generate_unique_name`                                                                                                  | `session/…` / `core/naming.py:53` | already core                                 | call directly                                                                                                                              |
| `_build_session_env` (+ `_resolve_subprocess_proxy_launch_metadata`, `_container_reachable_url`)                                           | `cli/session.py:374`              | UI-free                                      | -> `forge.session.launch`                                                                                                                  |
| whole `launch_confirmation.py` (`_infer_launch_confirmation`, `record_launch_confirmed`, `read_proxy_cost_baseline*`, `_routing_mode_for`) | `cli/launch_confirmation.py`      | UI-free                                      | -> `forge.session.launch_confirmation`                                                                                                     |
| `_cwd_forge_root`                                                                                                                          | `cli/session.py:223`              | UI-free                                      | -> `forge.core` (beside `find_forge_root`)                                                                                                 |
| `_resolve_context_limit`                                                                                                                   | `cli/session.py:254`              | UI-free                                      | -> `forge.session`, **after** moving its dep `_get_context_limit_for_proxy` (+`_context_window_for_proxy_model`) out of `cli/claude.py:61` |
| `_resolve_routing_from_cli`                                                                                                                | `cli/session.py:81`               | **CLI-bound**                                | stays; inject `ResolvedRouting` into the op                                                                                                |
| `_prepare_sidecar_prompt_file`                                                                                                             | `cli/session.py:536`              | UI-free (pure path map)                      | -> `forge.session.launch`                                                                                                                  |
| `_warn_if_hooks_missing` (`session_lifecycle.py:256`), `_warn_if_version_outdated` (`:276`), `_auto_install_extensions` (`session.py:557`) | CLI                               | **UI-tangled** (`console.print`/`print_tip`) | stay CLI; split logic from render or trigger via `announce`/`warnings` -- the op never prints                                              |

**Start-path arithmetic (corrected):** ~3 already core (`invoke_claude`, `run_with_active_session`, `SessionManager`), 5
UI-free relocate (`_build_session_env`, `_prepare_sidecar_prompt_file`, `launch_confirmation.py`, `_cwd_forge_root`,
`_resolve_context_limit`), **~4 stay CLI-bound** (`_resolve_routing_from_cli` + the 3 render-warns/install above).

### Sub-slice 2a -- Clean-break relocations (repoint all callers, delete re-exports) [implemented]

- [x] Move the UI-free primitives above into `forge.session.*` / `forge.core` **verbatim**, carrying their private
  helpers.

- [x] **`launch_confirmation.py` (P1):** it is a standalone module imported by `session_lifecycle.py:19` **and**
  `session_fork.py:62`, with direct tests in `tests/src/cli/test_launch_confirmed.py` **and** an indirect import
  (`from forge.cli.session_lifecycle import _infer_launch_confirmation`) in
  `tests/regression/test_bug_delete_live_session.py`. Relocating it to `forge.session.launch_confirmation` must update
  **both** importers, repoint `test_launch_confirmed.py`, and keep `session_lifecycle` re-importing the names so the
  indirect regression import still resolves.

- [x] **Patch-migration policy (P3):** 2a is a clean break -- **no** lingering compat re-exports for these helpers -- so
  every test that patched `forge.cli.session.<helper>` must repoint to the new home in the same change. The false-green
  trap this avoids: a test still patching a CLI re-export passes while exercising the shim, not the moved code -- which
  is exactly why the re-exports are deleted rather than kept. Applies to `_build_session_env`, `_cwd_forge_root`,
  `_resolve_context_limit`, and the launch-confirmation helpers.

- [x] **Cross-path call-site migration (Nit 4):** these helpers are used well beyond the start path, via two import
  styles (late-bound `_sess().X()` and direct `from forge.cli.session import X`) -- both break the moment the symbol
  leaves `forge.cli.session` unless a re-export stays. **Decision: repoint every caller in 2a and delete each helper's
  CLI re-export** (clean break per `coding_standards.md` §5; avoids the false-green trap above and keeps the shim
  shrinking, not growing). Only the big symbols (`invoke_claude`/`SessionManager`) keep riding the shim until 2b/Slice
  5\. Inventory:

  - `_build_session_env`: `session_lifecycle.py:420`, `session_fork.py:843`.
  - `_resolve_context_limit`: `session_resume_modes.py:48,175`, `session_fork.py:646,814`,
    `session_lifecycle.py:1080,1909,2046,2114,2253`.
  - `_cwd_forge_root`: `session_lifecycle.py:939,1404,1652,2466`, `session_fork.py:429`, `session_codex.py:199`,
    `session_manage.py:134,801,1019` (+ direct import `:39`), `memory_report.py:44` (+ direct import `:25`).
  - launch-confirmation helpers: imports at `session_lifecycle.py:19-20` + `session_fork.py:62`; the parent-shim
    **call** `_sess()._infer_launch_confirmation(...)` at `session_lifecycle.py:706` (mutation-table row 11); the
    `session_lifecycle:162` re-export; **5** `patch("forge.cli.session._infer_launch_confirmation")` sites in
    `tests/regression/test_bug_nested_project_launch.py`; plus the indirect import in `test_bug_delete_live_session.py`
    (P1). All repoint when the module moves and the `forge.cli.session` re-export is deleted (Nit 3).

  If 2a's diff proves too large to review, the fallback is per-helper compat re-exports with a tracked cleanup task --
  but the default is repoint-all.

- [x] **Prereq -- `_get_context_limit_for_proxy` clean-break:** relocate it (+ its private dep
  `_context_window_for_proxy_model`) out of `cli/claude.py` **before** `_resolve_context_limit`, with its own inventory.
  It is shared beyond the relocating helper, so a naive move strands `forge claude` or leaves a hidden CLI alias:

  - `forge claude` command: `claude.py:279`.
  - `_resolve_routing_from_cli` (stays CLI -- imports from the new home): `session.py:98,142`.
  - `_resolve_context_limit` (also relocating): `session.py:271,282`.
  - regression tests importing `from forge.cli.claude import _get_context_limit_for_proxy`:
    `tests/regression/test_removal_patching_system.py:122,143,147,168`.

  `_context_window_for_proxy_model` is internal to `claude.py` (only `:82`); it moves as the private dep.

- [x] Execute the render-seam disposition from the map (no longer "unassessed"): relocate `_prepare_sidecar_prompt_file`
  (UI-free); keep the 3 UI-tangled warn/install helpers in the CLI.

- [x] Repoint **all** touched tests to the new locations -- start **and** the fork/resume/manage/codex/memory-report
  call sites in the inventory above, not just the start path.

- **Assertions:** pure moves complete (characterization test green; no error-text or mutation-order change); layering
  grep clean on every new module; `session_lifecycle.py` line count non-increasing (2,492 lines; was 2,496).

### Sub-slice 2b -- The op

- [x] Bridge carve-out: add frozen `ClaudeSidecarLaunch` + `ClaudeSessionLaunchResult`, extract the shared
  `_launch_claude_for_session` body into render-free `launch_claude_session(...)`, and keep the old CLI function as an
  adapter that renders hook/version warnings, sidecar status, warning lines, and post-exit summary.
- [x] Add frozen `ClaudeSessionStartResult` (`exit_code`, `session`, `manifest`, `did_run`, `store_exists`,
  `worktree_path`, `warnings`, `operation_started_at`). The single-`announce` payload evolved into typed presenter
  events (`ClaudeStartCreated`/`ClaudeStartExtensions`); see "Open items resolved" below. `store_exists` is captured
  **post-run but before the incognito cleanup `finally`** (`_launch_claude_for_session:708` reads `store.exists()` for
  `_post_exit_render`; the incognito delete runs later, at `:1138`). So it is **True** for incognito at capture -- it
  does **not** track incognito auto-delete; it flags a session **deleted during the run** (e.g. in-session
  `forge session delete`), which drives the "was deleted during this run" message (`:727`). The op must capture at the
  same point (Nit 5); the CLI cannot re-derive it without re-reading state.
- [x] Write `start_claude_session` mirroring `start_interactive_codex_session`: preserves the ordered mutation contract
  in the table below **exactly** (host and sidecar differ), the sidecar-vs-host branch, and the **staged pre-launch
  event sequence** (created/routing -> extensions -> no-launch) fired at its current anchors via the presenter.
- [x] The 3 UI-tangled warn/install helpers keep their pre-launch print timing: `before_launch(forge_root)` ->
  `_warn_before_claude_launch` (hooks/version warns) and `on_extensions` (auto-install) fire before the child, not
  collected into `warnings` (which would move the output to after the child exits -- a timing change).
- [x] Convert **every** CLI-error exit inside `_launch_claude_for_session` to `raise ForgeOpError` (Nit 2): the direct
  `sys.exit(1)` sites (`:468/487/495/629`) **and** the `print_error(...) + return 1` paths -- runtime-dispatch backstop
  (`:392`), direct-model env error (`:675`), proxy model-pin error (`:683`). The op cannot `print_error`; the CLI
  renders the `ForgeOpError` message.
- [x] **Shared-launcher compatibility (Nit 1):** `_launch_claude_for_session` has **9 callers**, only 2 on the start
  path (`:1123`/`:1152`). The rest -- resume/reconnect (`:1986`/`:2066`/`:2136`/`:2363`,
  `session_resume_modes.py:135`/`:227`) and fork (`session_fork.py:1239`) -- migrate in Slices 3/4, not now. 2b extracts
  the body into a core helper that raises `ForgeOpError` and stays render-free; the start op consumes it directly.
- [x] **The resume/fork adapter is NOT thin:** the launcher body currently owns a large render/post-exit surface that
  resume/fork depend on -- hook/version warns (`:435-436`), the sidecar status block (`:583-600`),
  `record_launch_confirmed` (`:572`/`:657`), `_infer_launch_confirmation` (`:706`), and `_post_exit_render`
  (`:621`/`:708`). A `try/except -> print_error -> return 1` wrapper would force the render-free core to either print
  (breaking layering) or **silently drop** all of it. So the adapter must consume the **same event/result contract as
  the start op** (`ClaudeStartLaunch` events + `ClaudeSessionStartResult`) and reproduce the warns, sidecar status, and
  post-exit render for resume/fork until Slices 3/4 convert them. The contract is shared launcher infra, not start-only
  -- which raises 2b's scope; if it grows too large, split the adapter bridge into its own sub-slice.
- [x] Preserve the **incognito** contract: op-owned. The delete-on-exit `finally` wraps **only** the launch; the
  launch-error hook fires before the finally so "error -> Cleaning up..." order holds. (See "Open items resolved".)
- [x] Rewire `launch_new_session`: resolve routing + build `SupervisorWiring` (CLI) -> `start_claude_session(...)` with
  the `ClaudeStartPresenter` rendering created/extensions/no-launch at their current points -> render post-exit from the
  result -> `sys.exit` at the command boundary.
- [ ] Migrate the bulk patch sites: `invoke_claude` (146) + `SessionManager` (54) repoint from `forge.cli.session.*` to
  the op/core locations. **Deferred to Slice 5:** the op injects `invoke=`/`manager=` through the `_sess()` shim, so the
  patch sites intentionally still resolve; the parent-count drop lands when the shim is retired.
- **Assertions (met):** op imports no `forge.cli`, no Click/Rich/`sys.exit`; characterization test green (manifest
  byte-identical for start **and** incognito); error precedence + mutation order unchanged; incognito `finally`
  preserved; both sidecar and host launch paths exercised. **Deferred:** parent patch-count drop (Slice 5, see above).

### 2b -- ordered mutation contract (verified line anchors in `session_lifecycle.py`)

This is the behavior-preservation contract for the op. Preserve order and branch exactly.

| #   | Line            | Call                                                       | Branch                | Purpose                                                                                                          |
| --- | --------------- | ---------------------------------------------------------- | --------------------- | ---------------------------------------------------------------------------------------------------------------- |
| 1   | 958 (uuid @970) | `manager.start_session(claude_session_id=pre_seeded_uuid)` | both                  | create session (+ optional worktree) + pre-seed UUID                                                             |
| 2   | 1012            | `_MemStore.update(_set_memory)`                            | if `memory_flag`      | enable `intent.memory.auto_update`; reassigns `manifest`                                                         |
| 3   | 1020            | `_SPStore.update(...)`                                     | if `subprocess_proxy` | set `intent.subprocess_proxy`; re-read `manifest` @1024                                                          |
| 4   | 1070            | `store.update(apply_supervisor_and_lane)`                  | if `supervise_target` | supervisor config + lane; re-read @1071                                                                          |
| 5   | 457             | `store.update(claude_project_root)`                        | first launch only     | persist launch root (in `_launch_claude_for_session`)                                                            |
| 6   | 490             | `store.update(is_sandboxed=True)`                          | sidecar               |                                                                                                                  |
| 7   | 572             | `record_launch_confirmed(...)`                             | sidecar               | routing_mode=proxy, proxy_id, base_url, sidecar key decision, cost baseline                                      |
| 8   | 625 / 632       | `store.update(is_sandboxed=False)`                         | sidecar rollback      | on `ContainerExistsError` / any exception, then re-raise                                                         |
| 9   | 638             | `store.update(is_sandboxed=False)`                         | host                  |                                                                                                                  |
| 10  | 657             | `record_launch_confirmed(...)`                             | host                  | `_routing_mode_for`, proxy_id, base_url, `compute_interactive_api_key_decision(interactive=True)`, cost baseline |
| 11  | 706             | `_infer_launch_confirmation(...)`                          | host, post-exit       | only if `exit_code == 0 and not fork_session`                                                                    |

Rows 1-4 run in `launch_new_session` before the launcher; 5-11 in `_launch_claude_for_session`. **Host path** = 5, 9,
10, 11; **sidecar path** = 5, 6, 7, 8. Rollback boundary: rows 6-8 unwind `is_sandboxed` on failure and re-raise; there
is **no** post-launch rollback (parity with `codex_interactive` -- "after launch the session is the user's"), except the
incognito delete-on-exit `finally`.

### Acceptance tests (2a + 2b)

- [x] Layering: `grep -rn "from forge.cli\|import forge.cli" src/forge/core/ops/ src/forge/session/` -> empty for new
  modules.
- [x] Characterization: `uv run pytest tests/src/session/test_claude_session_manifest_characterization.py -q` green
  before and after each sub-slice; extended with `test_incognito_start_manifest_shape_and_cleanup`, which captures the
  incognito manifest mid-launch (the only window it exists) and asserts the op-owned `finally` deletes it on exit -- 3
  passed.
- [x] Focused: `uv run pytest tests/src/cli/test_session_commands.py tests/src/cli/test_session_model_pins.py -q`.
- [x] Integration: `./scripts/test-integration.sh tests/integration/docker/test_session_lifecycle.py -v`.
- [x] `make pre-commit` clean.
- [x] 2b bridge focused:
  `uv run pytest tests/src/session/test_claude_session_manifest_characterization.py tests/src/cli/test_session_commands.py tests/src/cli/test_session_model_pins.py tests/src/cli/test_session_rewind_cli.py tests/src/cli/test_session_resume_review.py tests/regression/test_bug_nested_project_launch.py tests/regression/test_bug_passthrough_model_pin.py -q`
  -- 264 passed.
- [x] 2b bridge integration: `./scripts/test-integration.sh tests/integration/docker/test_session_lifecycle.py -v` -- 21
  passed.
- [x] 2b bridge pre-commit: `make pre-commit` -- passed after hooks sorted imports/formatted Markdown.

### Open items resolved by the start-op step

- **Staged pre-launch event contract (Nit 1)** -- resolved as a `ClaudeStartPresenter` Protocol (9 hooks). The op owns
  *timing*; the CLI presenter owns *content*. The 3 UI-tangled render seams hang off `before_launch(forge_root)`
  (`_ClaudeStartCliPresenter.before_launch` -> `_warn_before_claude_launch`, which does the hooks/version warnings);
  `on_extensions` carries the auto-install decision.
- **Incognito `finally` ownership** -- resolved **op-owned**. `start_claude_session` wraps the launch in
  `try/except ForgeOpError -> on_launch_error` then `finally -> _run_incognito_cleanup(...)`; the error hook fires
  before the finally so the "error -> Cleaning up..." output order is preserved. Cleanup render goes through the
  `on_incognito_cleanup_{start,ok,warning}` hooks. Pinned by `test_incognito_start_manifest_shape_and_cleanup`.
- Whether the 3 render seams stay inline in the CLI event handlers (preserves current timing) or move to
  `result.warnings` (moves output to after the child exits -- a timing change). Behavior-preservation favors inline
  unless deliberately changed.

## Slice 3 -- `resume_claude_session` (interactive-resume op)

**Status:** implemented 2026-07-02; review pending. Anchors verified against the post-start-op tree
(`session_lifecycle.py` = 2,121 lines before Slice 3; **2,121 after Slice 3**).

### Design decision (resolved by precedent -- mirrors the landed start op)

Slice 2 set the pattern: the op calls the **core** render-free `launch_claude_session(...)` directly (not the CLI
adapter `_launch_claude_for_session`), with a presenter for `before_launch`/`on_sidecar_launch`/`on_launch_error`; the
CLI renders the post-exit summary from the returned result. Slice 3 applies the same shape to resume. Mirror
`core/ops/codex_interactive.py` (interactive/blocking child), not `codex_session.py::continue_codex_session` (headless).

- After Slice 3, `_launch_claude_for_session` has a **single** remaining caller (`session_fork.py:1244`); the adapter
  retires with the fork work.
- `ClaudeResumeResult` mirrors the landed `ClaudeSessionStartResult` (`exit_code`, `session`, `manifest`,
  `store_exists`, `operation_started_at`, `worktree_path`, `warnings`). `_post_exit_render` (`:430`) consumes only
  `manifest`/`store_exists`/`exit_code`/`since` -- **no routing facts** in the result; those go in the pre-launch
  `ResumePrepared` event.

### Verified resume surface (`resume` dispatch, `session_lifecycle.py:1157`)

Six terminal targets. Two load-bearing invariants gate them:

1. **Codex runtime dispatch before any Claude predicate** (`:1316-1318` -> `run_codex_resume`, `session_codex.py:243`).
   **Out of scope** -- codex has its own op path; the Claude resume op never touches it. `--task` is codex-only
   (`:1320`).
2. **Concurrent-reconnect guard** (`:1461-1478`): an active session blocks reconnect without `--force`; `--force`
   diverts to `_launch_as_child`. Stays CLI-owned (renders the active-entry detail).

| Target                     | Anchor                        | Session call                        | Fresh child?        | In scope       |
| -------------------------- | ----------------------------- | ----------------------------------- | ------------------- | -------------- |
| `_launch_in_place`         | `:1512`                       | `switch_session`                    | no (pre-seeds UUID) | yes            |
| `_reconnect_in_place`      | `:1630`                       | `switch_session`                    | no                  | yes            |
| `_launch_as_child`         | `:1709`                       | `relaunch_session`                  | yes                 | yes            |
| `_resume_fresh` (transfer) | `:1849`                       | `resume_session`                    | yes                 | yes            |
| `_resume_fresh_native`     | `session_resume_modes.py:156` | `resume_session`                    | yes                 | yes            |
| `_resume_fresh_rewind`     | `session_resume_modes.py:28`  | `resume_session` + rewind artifacts | yes                 | yes            |
| `run_codex_resume`         | `session_codex.py:243`        | --                                  | --                  | **no (codex)** |

### The repeated tail to collapse (identical across all 4 lifecycle helpers + 2 resume-mode helpers)

After each mode's own session creation, every helper runs:

1. `_apply_routing_override_to_state` + `_persist_routing_override` (routing override; mutates state + disk).
2. `_get_effective_proxy_for_session` -> (template, url, proxy_id); `if routing.proxy_id: proxy_id = routing.proxy_id`.
3. `_resolve_context_limit(proxy_id or template)`.
4. `_get_launch_preferences` -> (use_sidecar, mounts, image).
5. `_apply_and_persist_direct_model_override(..., surface="resume")` -- **7 sites total**; Slice 3 collapses the **6
   in-scope** (`:1537/1674/1742/1963`, `session_resume_modes.py:125/217`). The 7th (`session_fork.py:839`) stays for
   Slice 4.
6. `_get_runtime_base_url(use_sidecar, url)`.
7. render routing summary + action + worktree/context (**CLI-owned; text differs per mode**).
8. `_launch_claude_for_session(...)` -> exit_code -- the launch (7 sites post-start-op: 4 lifecycle + 2 resume-mode + 1
   fork).
9. `sys.exit(exit_code)`.

Collapse into the op: steps 1-2 (routing override + effective proxy), 5 (model override), 6 (runtime url), 8 (launch).
Steps 3 (`context_limit`) and 4 (`_get_launch_preferences`) are **CLI-computed and plan-carried** -- the op receives
`plan.context_limit` and `plan.launch_preferences`, never recomputing from the created child (context_limit for the
parent-vs-child divergence below; launch preferences so the rewind sidecar guard runs CLI-side). Step 7 (render) and the
pre-step session creation / prompt assembly vary per mode and stay CLI-side.

### Op boundary (resolved)

- **CLI owns:** the full `resume` validation block (`:1195-1350`), routing resolution (`_resolve_routing_from_cli`),
  codex dispatch, name picker, cross-project resolution, the concurrent-reconnect guard, mode-specific session creation
  (`switch`/`resume`/`relaunch` + rewind artifacts), prompt/context assembly, **the `context_limit` and
  `_get_launch_preferences` computations**, the **rewind sidecar guard** (`session_resume_modes.py:117` -- rejects
  sidecar with a tip; needs `use_sidecar`, now CLI-computed), and all rendering.
- **Op owns:** the shared mutation + launch tail -- apply+persist routing override, apply+persist model override, the
  **UUID pre-seed write** when `plan.session_id` is set (dedup of `:1581-1592`/`:1972-1984`; keeps "write UUID before
  launch" next to the launch), effective proxy for `proxy_id`/`template`, runtime url, and `launch_claude_session(...)`.
  Fires `on_resume_prepared` before launch; delegates `before_launch`/`on_sidecar_launch`/`on_launch_error` like the
  start op. Returns `ClaudeResumeResult`.
- **`ResumeLaunchPlan` (CLI -> op) carries:** launch-target manifest, `routing`/`direct`, `resume_id`, `session_id`,
  `fork_session`, `prompt_file`, `action` code, `context_limit`, and `launch_preferences` (use_sidecar/mounts/image).
- **Deliberately NOT in the resume op:**
  - **Incognito cleanup** -- resume has no delete-on-exit contract (an incognito session cannot be resumed), unlike
    start. None of the six helpers wrap the launch in a `finally`; keep it that way.
  - **Recomputing `context_limit` or launch preferences** -- both are CLI-computed and plan-carried. `context_limit`
    especially: the fresh paths derive it from the *parent* ref before the child exists and reuse it for context
    assembly (`_resume_fresh:1879/1892`) while launch `proxy_id`/`template` come from the child (`:1958`), so
    recomputing from the created child could diverge. Launch preferences stay CLI-side so the rewind sidecar guard can
    run before the op.

### Design decisions (resolved with reviewer 2026-07-02)

1. **Op shape: (A)** -- one `resume_claude_session` op taking a `ResumeLaunchPlan` (contents in the boundary above). The
   CLI computes the mode-specific creation/prompt facts, `context_limit`, and `launch_preferences`; the plan carries
   them. The op owns the shared mutation + launch tail (routing/model overrides, UUID pre-seed, effective proxy, runtime
   url, launch). Matches the one-verb-one-op precedent (`start_claude_session`, `continue_codex_session`), and keeps
   mode-specific core entrypoints from scattering.
2. **Fork deferred to Slice 4.** `_launch_as_child` (a `resume` branch on the shared launcher) is in scope;
   `forge session fork` is not -- its host `_invoke_fork` closures and worktree behavior (`session_fork.py:1281`) differ
   enough that pulling it in now would make Slice 3 sprawl. Consequence: the fork model-override (`session_fork.py:839`)
   and launch (`:1244`) sites stay, so `_launch_claude_for_session` retires **with fork**, not here.
3. **Single `on_resume_prepared(ResumePrepared{...})` event.** `action` is an **enum/literal code** (`LAUNCH_IN_PLACE` /
   `RECONNECT` / `RELAUNCH_AS_CHILD` / `FRESH_DERIVED`), **not** display text -- the op reports structured intent; the
   CLI presenter maps the code to the exact string ("Launching" / "Reconnecting" / "Relaunching X as Y" / "Created
   derived session"). Keeps the render-free op from carrying user-facing copy.

### Invariants that MUST survive (pin with existing tests first)

- Codex runtime dispatch before Claude predicates (`:1316`); concurrent-reconnect guard (`:1461`).
- Rewind rejects sidecar with a tip (parent guard `:1383`, child guard `session_resume_modes.py:117`).
- Fresh-resume writes the pre-seeded UUID **before** launch (`_resume_fresh:1972-1984`, `_launch_in_place:1581-1592`).
- Deferred same-dir fork resumes the parent conversation (`_get_deferred_same_dir_fork_resume_id`,
  `_launch_in_place:1555`).
- `--review` edits the notes overlay, never the AI snapshot (`_resume_fresh:1916-1931`).
- `--no-proxy` resume preserves the pre-extraction override ordering: direct clears the effective proxy before
  context-limit lookup and launch preferences, so a sidecar-preferring session launches on host with direct env.
- Fresh-derived resume keeps the pre-extraction render text: no Worktree/Branch lines in the derived-session pre-launch
  block.
- `core/ops/` + `forge/session/` import nothing from `forge.cli`.

### Characterization extensions (write FIRST, green before + after)

Current coverage: start `--no-launch`, incognito start, fresh-resume (transfer). Add the untested resume modes
(read-back or mid-launch capture as needed):

- reconnect-in-place (`switch_session`; same session, routing override applied, no child).
- launch-as-child (`relaunch_session`; new child, `fork_session=True`, parent UUID as `resume_id`).
- native fresh-resume (`_resume_fresh_native`; distinct manifest from transfer).

### Acceptance tests (Slice 3)

- [x] Layering: `grep -rn "from forge.cli\|import forge.cli" src/forge/core/ops/claude_session.py` -> empty.
- [x] Op render-free: no Click/Rich/`console`/`sys.exit`/`print_error`/`print_tip` in `core/ops/claude_session.py`.
- [x] Characterization green before + after (start/incognito/transfer + new reconnect/child/native snapshots).
- [x] The 6 in-scope `_apply_and_persist_direct_model_override` + 6 resume-path `_launch_claude_for_session` sites
  collapse to one op path; `_launch_claude_for_session` left with only the fork caller (`session_fork.py:1244`), and the
  fork model-override (`session_fork.py:839`) stays for Slice 4.
- [x] Focused (resume CLI + model-pin + passthrough regression):
  `tests/src/cli/test_session_commands.py tests/src/cli/test_session_resume_review.py tests/src/cli/test_session_rewind_cli.py tests/regression/test_bug_nested_project_launch.py tests/regression/test_bug_passthrough_model_pin.py`.
- [x] Integration: `./scripts/test-integration.sh tests/integration/docker/test_session_lifecycle.py -v`.
- [x] `make pre-commit` clean.
- [x] Review follow-up: direct launch-in-place resume on a sidecar-preferring session asserts
  `_resolve_context_limit(None)`, host launch, scrubbed proxy env, and no `CLAUDE_CODE_AUTO_COMPACT_WINDOW`.

**Recorded verification (Slice 3):**

- `uv run pytest tests/src/session/test_claude_session_manifest_characterization.py -q` -> 6 passed before and after.
- `uv run pytest tests/src/cli/test_session_commands.py tests/src/cli/test_session_resume_review.py tests/src/cli/test_session_rewind_cli.py tests/src/cli/test_session_model_pins.py tests/regression/test_bug_nested_project_launch.py tests/regression/test_bug_passthrough_model_pin.py -q`
  -> 263 passed.
- `uv run pytest tests/src/cli/test_session_commands.py -q -k "resume or model or passthrough"` -> 42 passed, 166
  deselected.
- `./scripts/test-integration.sh tests/integration/docker/test_session_lifecycle.py -v` -> 21 passed.
- `make pre-commit` -> passed.

## Slice 4a -- fork launch migration (`fork_claude_session`)

**Status:** 4a.1 committed 2026-07-02; 4a.2 implemented locally 2026-07-02 and verified. Fork surface was verified
against the pre-4a.1 tree (`session_fork.py` = 1,336 lines; `session_lifecycle.py` = 2,121 lines). After 4a.1,
`session_lifecycle.py` = **2,072 lines** and `session_fork.py` = **1,350 lines**. After 4a.2, `session_lifecycle.py` =
**2,072 lines** and `session_fork.py` = **1,229 lines**. Slice 4 splits into **4a** (fork launch migration -- itself
**4a.1** adapter deletion + **4a.2** the `fork_claude_session` op, both below) and **4b** (supervisor validation/wiring
\+ sidecar prep extraction).

### Scope correction (verified -- the migration is bigger than "one caller")

"Eliminate the last `_launch_claude_for_session` caller + the fork model-override" is the **small** half. That caller is
the **sidecar** fork path (`:1244`). The **host** fork path is the bulk: **four `_invoke_fork` closures** that call
`invoke_claude` **directly** and hand-roll `launch_claude_session`'s entire host branch -- hook/version warns (`:1278`),
`record_launch_confirmed` (`:1286`), `run_with_active_session` (`:1304`/`:1326`), post-exit render (`:1334`), and
incognito cleanup (`:1301`). Migrating fork onto the render-free path means unifying those, not just deleting one call.

### Two facts that shape 4a

1. **Fork has incognito cleanup** (`:1261` sidecar, `:1301` host) -- the delete-on-exit `finally` that Slice 3
   deliberately kept OUT of `resume_claude_session`. So fork **cannot** reuse the resume op; it mirrors
   `start_claude_session`. **Boundary to preserve:** the incognito `finally` wraps **only** the launch/run section, not
   the pre-launch model override (`:839`). Today a `--model` validation error exits **before** cleanup (no delete). The
   op must keep that -- the incognito finally wraps launch only; a pre-launch error propagates uncleaned. Expanding the
   cleanup scope is a behavior change and must be called out, not slipped in.
2. **No launcher `cwd`/env gap** (verified -- my earlier claim was wrong). `launch_claude_session` already resolves
   `launch_root = resolve_claude_project_root(manifest)` (`:349`, honoring `confirmed.claude_project_root` at `:351`),
   passes `cwd=str(launch_root)` to `invoke_claude` (`:1282`), and builds fork env (`fork_name`/`parent_session`) via
   `fork_session or register_fork` (`:353-363`). The host closures' `_fork_cwd` **equals** that `launch_root`, so
   routing them through the launcher needs **no new param**. If a characterization test later proves an override is
   required, add `launch_root_override` (coherent across store update, sidecar project dir, prompt paths, and host cwd
   -- `:1087` /`:1094`/`:1177`/`:1203`/`:1282`), never an invoke-only `cwd`.

### The 4 host closures collapse to launch params

All four share `env_vars`/`unset_env_vars` and the same `cwd` (= the launcher's `launch_root`); they differ only in the
launch discriminators:

| Mode                    | Anchor  | id                      | fork_session | system_prompt     |
| ----------------------- | ------- | ----------------------- | ------------ | ----------------- |
| native-relocate         | `:992`  | `resume_id=parent`      | True         | `_nr_prompt`      |
| rewind                  | `:1060` | `resume_id=_rewind`     | True         | `prompt_file`     |
| worktree fresh-transfer | `:1166` | `session_id=_fork_uuid` | False        | `_wt_prompt`      |
| same-dir                | `:1190` | `resume_id=parent`      | True         | `_samedir_prompt` |

Sidecar (`:1244`) already carries the same discriminators: `session_id=_fork_uuid if uses_fresh_transfer else None`,
`resume_id = None if uses_fresh_transfer else (_rewind_resume_id or parent)`, `fork_session=not uses_fresh_transfer`,
`register_fork=uses_fresh_transfer`. So one parameterized launch replaces four closures + the sidecar branch (4a.2).

**Addendum ownership (must-fix in 4a.2 -- the `system_prompt` column above is addendum-composed, not launcher-ready).**
Each host closure folds the managed addendum into its prompt itself (`resolve_addendum_content_for_proxy` +
`write_managed_addendum`): `_nr_prompt`/`_samedir_prompt` are addendum-only, `_wt_prompt` is `addendum + prompt_file`,
and rewind's `_rewind_prompt_files` prepend addendum (`:1044-1048`). But `launch_claude_session` **already injects the
same managed addendum** (`:375-385`, same two functions). Routing a composed prompt through the launcher **doubles** it.
So 4a.2 must hand the launcher only the **user/context/configured** prompt and let it own addendum:
native-relocate/same-dir -> `None`, worktree -> raw `prompt_file`, rewind -> context+configured **minus** addendum.
**Rewind needs explicit characterization first:** the current sidecar path (`:1244`) already passes the
addendum-composed `prompt_file` into the launcher, so it may double the addendum **today** -- confirm, then fix or
preserve deliberately.

### Sub-slice split (resolved with reviewer)

**4a.1 -- delete the `_launch_claude_for_session` adapter (small, concrete, no behavior change).**

- [x] Inline the adapter's body at its only caller, the sidecar fork (`:1244`): replace
  `_launch_claude_for_session(...)` with `launch_claude_session(...)` + `_render_claude_launch_result(...)`. The adapter
  already calls `launch_claude_session`, so this is a mechanical inline, not a rewrite. Keep the incognito `finally`
  where it is (CLI).
- [x] Delete `_launch_claude_for_session` (0 callers remain).
- [x] Migrate its importers: `tests/regression/test_bug_nested_project_launch.py`,
  `tests/src/cli/test_session_commands.py`, `tests/src/cli/test_session_codex.py` -- repoint patches to
  `launch_claude_session` (or the inlined seam).
- [x] Leave the fork model override (`:839`) for 4a.2; moving it in 4a.1 would entangle the host closure behavior this
  sub-slice is intentionally avoiding.
- [x] **Assertions:** adapter deleted (grep: 0 callers); those 3 importer files green; host + sidecar fork behavior
  unchanged; existing fork tests + characterization unchanged.

**Recorded verification (4a.1):**

- `rg -n "_launch_claude_for_session" src tests` -> no matches.
- `uv run pytest tests/src/cli/test_session_commands.py tests/src/cli/test_session_rewind_cli.py tests/src/cli/test_session_codex.py tests/regression/test_bug_nested_project_launch.py -q`
  -> 309 passed.
- Layering grep (`from forge.cli|import forge.cli` in `core/ops/claude_session.py` + `session/model_pin.py`) -> empty.
- Op render-free grep (`click|rich|console|sys.exit|print_error|print_tip` in `core/ops/claude_session.py`) -> empty.
- `./scripts/test-integration.sh tests/integration/docker/test_session_lifecycle.py -v` -> 21 passed.
- `make pre-commit` -> passed.

**4a.2 -- `fork_claude_session` op + host-closure unification (the lift).**

- [x] Introduce `fork_claude_session` mirroring `start_claude_session` (owns incognito). Unify the 4 host closures into
  one parameterized launch (discriminators above); render via a `ForkPresenter`. Preserve the incognito boundary from
  fact 1.
- [x] Add `launch_root_override` **only if** a characterization test proves the default resolver is insufficient. No
  override was needed; `launch_claude_session`'s existing resolver matched the old fork cwd behavior.
- [x] Managed addendum is now launcher-owned for fork: native-relocate/same-dir pass `None`, transfer/rewind pass only
  user/context/configured prompts; host + sidecar worktree fork tests assert exactly one managed addendum, and host
  rewind is pinned explicitly. Sidecar rewind is rejected before prompt composition/launch.
- [x] Confirmed-state writes inside `launch_claude_session` (`claude_project_root`, `is_sandboxed`
  confirmation/rollback) are intentionally best-effort across start/resume/fork; lock-timeout failures log and do not
  abort interactive launch.
- [x] Run integration (`./scripts/test-integration.sh tests/integration/docker/test_session_lifecycle.py -v`) and
  `make pre-commit`; record results before marking 4a.2 complete.
- **Assertions:** op render-free + layering clean; fork manifest byte-identical for same-dir, worktree-transfer,
  native-relocate, and **incognito** (mid-launch capture + delete-on-exit assertion, like the incognito start test); the
  launched **system-prompt contains the managed addendum exactly once** for every mode (assert on the combined prompt
  file, not the manifest); host rewind explicitly characterized, with sidecar rewind covered by rejection behavior.

**Recorded verification (4a.2):**

- `uv run pytest tests/src/cli/test_session_commands.py::TestSessionFork tests/src/cli/test_session_rewind_cli.py tests/regression/test_bug_21x_fork_launch_handoff.py -q`
  -> 54 passed.
- `uv run pytest tests/src/cli/test_session_commands.py tests/src/cli/test_session_rewind_cli.py tests/regression/test_bug_21x_fork_launch_handoff.py tests/regression/test_bug_codex_fork_orphan.py tests/regression/test_bug_passthrough_model_pin.py tests/src/session/test_claude_session_manifest_characterization.py -q`
  -> 245 passed.
- Layering grep (`from forge.cli|import forge.cli` in `core/ops/` + `session/model_pin.py`) -> empty.
- Op render-free grep (`click|rich|console|sys.exit|print_error|print_tip` in `core/ops/claude_session.py` +
  `session/model_pin.py`) -> empty.
- `wc -l src/forge/cli/session_fork.py src/forge/cli/session_lifecycle.py src/forge/core/ops/claude_session.py` ->
  `session_fork.py` 1,229; `session_lifecycle.py` 2,072; `core/ops/claude_session.py` 1,485.
- `./scripts/test-integration.sh tests/integration/docker/test_session_lifecycle.py -v` -> 21 passed.
- `make pre-commit` -> passed.

### Boundary (4a.2)

- **CLI owns:** fork validation, name/worktree/`--into` creation, per-mode prompt assembly, the model override (or
  delegate to a core helper), and all rendering via a `ForkPresenter`.
- **Op owns:** `record_launch_confirmed` (host), `run_with_active_session`/`launch_claude_session`, incognito cleanup
  (launch-only scope), post-exit facts returned in `ForkLaunchResult`.

### Invariants that MUST survive (pin with existing tests first)

- Incognito fork deletes on exit (`:1261` sidecar, `:1301` host); the `finally` wraps **launch only** -- a pre-launch
  `--model` error exits before cleanup (fact 1); error hook fires before the finally (output order).
- native-relocate resumes the relocated JSONL from `launch_root = resolve_claude_project_root` (`:992`).
- rewind fork rolls back (delete worktree) when the transcript is unpreparable, then errors (`:1023-1039`).
- worktree fresh-transfer uses `session_id=_fork_uuid` + `register_fork`; same-dir uses `resume_id=parent` +
  `fork_session` (`:1166`/`:1190`).
- **Managed addendum is launcher-owned** (`launch_claude_session:375`): CLI fork prompt assembly passes only
  user/context/configured prompt files, never the addendum, so it lands in the child system-prompt exactly once.
- `_build_session_env` sets `FORGE_FORK_NAME` (hook fork detection, `:854`).
- Host forks fire `record_launch_confirmed` (`:1286`); sidecar forks get it inside `launch_claude_session`.
- `core/ops/` + `forge/session/` import nothing from `forge.cli`.

### Focused tests (real files -- no `test_session_fork*.py` exists)

`tests/src/cli/test_session_commands.py` (fork cases + the `_launch_claude_for_session` importer),
`tests/src/cli/test_session_rewind_cli.py`, `tests/src/cli/test_session_codex.py`,
`tests/regression/test_bug_nested_project_launch.py`, plus the fork rewind/worktree/`--into` coverage; then
`./scripts/test-integration.sh tests/integration/docker/test_session_lifecycle.py -v` and `make pre-commit`.

## Slice 4b -- supervisor wiring unification (+ optional sidecar testability)

**Status:** re-baselined 2026-07-02 against the post-4a.2 tree. The card (`card.md:84`, `:87`, `:102`) is stale -- both
of its named CLI->core extractions no longer describe the code.

**Re-baseline (verified against current code):**

| Card claim                                                              | Post-4a.2 reality                                                                               | Evidence                                                                                                                                                                                                                                                                                |
| ----------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Extract `prepare_sidecar_session` (Docker preflight + env) from the CLI | Already core-owned; no CLI sidecar prep remains                                                 | `_run_sidecar_claude_session` owns Docker check, mount parse, `build_claude_args`, secrets, container env, `is_sandboxed` + `ContainerExistsError` rollback (`core/ops/claude_session.py:1177-1461`); CLI only reads `(use_sidecar, mounts, image)` off the manifest (`session.py:449`) |
| Extract `validate_and_setup_supervisor` from the CLI                    | Op name never created; the shipped primitive is `SupervisorWiring` + `_apply_supervisor_wiring` | `core/ops/claude_session.py:146`, `:1090`; start builds the wiring and routes through the op (`session_lifecycle.py:818-830`, `:857`)                                                                                                                                                   |
| (not in card)                                                           | Fork still hand-rolls the identical wiring persistence in the CLI                               | `session_fork.py:812-861` repeats `SupervisorConfig` -> `apply_supervisor_routing` -> cascade -> `apply_checker_options` -> effort -> lane -> `store.update(apply_supervisor_and_lane)`                                                                                                 |

**Scope answers:**

1. **What 4b is now:** collapse fork's supervisor **persistence** block onto the existing core
   `_apply_supervisor_wiring`. Sidecar prep needs no extraction.
2. **Split:** yes. **4b.1** supervisor wiring dedup (the real work). **4b.2** sidecar-internal testability --
   **conditional**, only if `_run_sidecar_claude_session` failure paths lack unit coverage; may close as a no-op.
3. **Invariants:** table below.

**Already symmetric -- do NOT "reconcile" these (verified; re-adding them to the op would be a false fix):**

- Supervisor-proxy autostart: start (`session_lifecycle.py:806`) and fork (`session_fork.py:731`) both call
  `ensure_supervisor_proxy` before session creation and feed the ensured id into wiring. Pinned by
  `tests/regression/test_bug_supervisor_proxy_autostart.py` (the fork case).
- Target validation: start validates a named `--supervise <target>` via `validate_supervisor_target`; fork's target is
  the parent it already loaded (`parent_manifest`), so skipping that call is correct, not an asymmetry.

**4b.1 -- unify fork supervisor wiring onto the core primitive.**

- [x] Replace the persistence block (`session_fork.py:812-861`) with: build
  `SupervisorWiring(target=parent, source_state=parent_manifest, supervisor_proxy=<ensured>, supervisor_direct=..., cascade=cascade_flag, checker_model/provider/effort=..., supervisor_effort=..., supervisor_runtime=...)`
  and call
  `_apply_supervisor_wiring(fork_manifest, wiring, proxy_id=_preflight_routing.proxy_id if _preflight_routing else None, template=_preflight_routing.template if _preflight_routing else None, direct=direct)`,
  reassigning `fork_manifest` from its return. Guard `_preflight_routing` exactly as the current block does
  (`session_fork.py:833`) -- it is optional (assigned only under the routing branch at `:653`). The two sequences are
  otherwise byte-identical -- verified field-by-field (SupervisorConfig args, routing, cascade, checker, effort, lane,
  store/forge_root).
- [x] No new `SupervisorWiring` field was needed; the existing dataclass matched the fork mapping.
- [x] Verify supervisor patch sites still resolve after the move -- no migration expected. Current tests patch
  `forge.policy.semantic.supervisor.apply_supervisor_routing` (e.g. `test_session_commands.py:4386`,
  `test_policy_supervisor.py:912`), which `_apply_supervisor_wiring` imports at call time (`:1099`), so they keep
  working through the op. No test patches `forge.cli.session_fork.apply_supervisor_*` / `lane_record_for_runtime`
  (verified: zero hits).
- **Assertions:** fork supervisor manifest byte-identical across `--supervise` alone and with `--cascade` /
  `--checker-*` / `--supervisor-effort` / `--supervisor-runtime`; op + `session/` layering clean; supervisor and
  flag-validation error text unchanged.

**4b.2 -- sidecar-internal testability (CONDITIONAL; decide during 4b.1).**

- [x] Audit `_run_sidecar_claude_session` (`:1177-1461`) failure-path coverage: Docker unavailable -> `ForgeOpError`;
  bad `--mount`; `ContainerExistsError` -> `is_sandboxed` rollback; secret resolution. Existing sidecar/container tests
  cover parser and container primitives, but the launcher-level bad-mount `is_sandboxed` state was unpinned.
- [x] **Decide the stale `is_sandboxed` window** (caveat above): either accept-and-document, or fix by moving the
  `is_sandboxed=True` write to just before the runner (after mount/secret prep) so a mount-parse failure never sets it,
  with a regression test (`forge session fork ... --mount <bad>` leaves `is_sandboxed` false). **Decision:** fixed in
  4b.2; this sub-slice is not a no-op.
- [x] No helper extracted. The needed coverage fits through the existing launcher path.

**Invariants (both sub-slices):**

| Invariant                                                                                                | Anchor                                                       | Must survive                                            |
| -------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------ | ------------------------------------------------------- |
| Cascade-at-launch flips the flag only; runtime hook escalates when no plan exists                        | core `:1122`                                                 | comment + behavior                                      |
| Child gets its own consumer lane; parent's confirmed lane stays true                                     | core `:1134`                                                 | `apply_supervisor_and_lane` + `lane_record_for_runtime` |
| `--supervisor-runtime` -> full lane frozen at first policy check                                         | core `:1134`                                                 | lane record shape                                       |
| Supervisor flag mutual-exclusivity errors                                                                | `session_fork.py:341-360`                                    | exact strings                                           |
| Sidecar validation/prep failures do not set `is_sandboxed`; runner failures roll back                    | `core/ops/claude_session.py:1221`, `:1305`, `:1330`, `:1337` | exact failure modes                                     |
| Wiring runs after routing-override persist, before template/proxy resolution; reads `_preflight_routing` | `session_fork.py:802-833`                                    | ordering                                                |
| `core/ops` + `session/` import no `forge.cli`; op render-free                                            | grep gates                                                   | layering                                                |

> **Sidecar rollback decision:** 4b.2 moved `is_sandboxed=True` to after mount/secret/env prep and immediately before
> the runner. Docker-unavailable still raises before the write, bad `--mount` now leaves `is_sandboxed` false, and
> `ContainerExistsError` / runner exceptions still roll the flag back. Secret gathering remains best-effort/non-raising
> today (`template_secrets.py:140`, `:75`, `:84`).

**Verification:**
`uv run pytest tests/src/cli/test_policy_supervisor.py tests/src/cli/test_session_commands.py tests/regression/test_bug_supervisor_proxy_autostart.py tests/regression/test_bug_consumer_lane_fork_resume_inherit.py tests/regression/test_bug_supervisor_fork_uuid_drift.py -q`;
layering + render-free greps; `./scripts/test-integration.sh tests/integration/docker/test_supervisor_e2e.py -v`;
`make pre-commit`.

## Slice 5 -- retire the `_sess()` shim

**Status:** re-baselined 2026-07-02 against the post-4b tree. The Slice 1 roadmap anchors are stale (they cite
`session.py:866-875` and a 270/146/54 patch split from before the ops extraction).

**Re-baseline (verified against current code):**

| Fact                                                    | Slice 1 baseline                            | Current (post-4b)                                                                                                                                                                                                                                                                                                                                                           |
| ------------------------------------------------------- | ------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Lazy parent-module seams                                | 4 `_sess()`                                 | **5** -- 4 `_sess()` (`session_lifecycle.py:87`, `session_fork.py:65`, `session_manage.py:34`, `session_codex.py:53`) + 1 `_session_cli()` (`session_resume_modes.py:23`); codex `_sess()` uses `import forge.cli.session`, the others use `sys.modules`                                                                                                                    |
| `_sess().X` / `_session_cli().X` runtime call sites     | ~270 patch-driving                          | **~33** -- ops extraction collapsed them (`SessionManager` 11, `_resolve_routing_from_cli` 5, `invoke_claude`/`run_with_active_session`/`generate_unique_name` 3 each, tail 1-2)                                                                                                                                                                                            |
| `patch("forge.cli.session.X")` sites                    | 270 single + 11 multi                       | **245 single + 11 multi = 256**, 13 test files                                                                                                                                                                                                                                                                                                                              |
| Direct `from forge.cli.session import X` (3rd category) | --                                          | current **src** imports are all session.py-owned (`console`, `handle_session_error`, the `session` group, `ResolvedRouting`) and **survive**; breakage is confined to **submodule-owned** names -- e.g. `delete` (`test_bug_qa12_orphaned_session_delete.py:40`), across **6 test files**. session.py-defined names (e.g. `_generate_parent_transfer_context`) also survive |
| Concentration                                           | invoke_claude 146 + SessionManager 54 (74%) | invoke_claude **149** + SessionManager **56** = 205/245 (**84%**)                                                                                                                                                                                                                                                                                                           |
| Test-file concentration                                 | --                                          | `test_session_commands.py` holds **183/245** (75%)                                                                                                                                                                                                                                                                                                                          |
| Re-export tail                                          | `session.py:866-875`                        | `session.py:619-626` (3 name re-exports + 3 `import *`)                                                                                                                                                                                                                                                                                                                     |

**How the shim works (so retirement stays behavior-safe):** `forge.cli.session` (session.py) is a real module -- the
`session` group at `:604`, helpers defined at `:73/:353/:407/:461`, plus a re-export tail at `:619-626`. `_sess()`
returns `sys.modules["forge.cli.session"]`, so every `_sess().X` resolves the parent module's attribute at call time:
one stable patch seam for all callers across the 4 CLI modules.

**Why this is the delicate capstone -- three coupled faces of one structure:** the `_sess()` runtime access, the
`import *` re-export tail (`:624-626`), and the 256 `forge.cli.session.X` patches all exist to work around the
**circular import** between `session.py` (`import *` from submodules, which both registers commands and populates the
patch seam) and the submodules (which import back from `session.py`). `_sess()` is the lazy-access workaround; a
submodule cannot simply `import forge.cli.session` at top level (load-time cycle). Deleting the 4 defs is trivial;
migrating 256 patches to real seams without silent breakage is the actual work.

**Scope decision (please confirm before implementing):**

- **A (full, the plan):** untangle the cycle, migrate all 256 patches, delete the shim + re-export tail,
  `patch("forge.cli.session.` -> 0. High churn (mostly one test file), modest behavior value (test-idiom hygiene).
- **B (defer):** leave the shim -- at ~33 call sites it is small and harmless now; revisit only if it blocks future
  work.

Recommendation: **A**, but only if the goal is to fully close the refactor -- it is the highest churn-to-behavior-value
slice. Sub-sliced below so each step is reviewable and reversible.

**Symbol -> new seam mapping** (confirm each tail symbol's definition site before repointing):

| Symbol (patches)                                                                                 | Real home                                                                          | New patch seam after retirement                                                                                                                                                                                                 |
| ------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `invoke_claude` (149) + `run_with_active_session` (1)                                            | `forge.session.claude` / `forge.session`; op imports both (`claude_session.py:38`) | `forge.core.ops.claude_session.{invoke_claude,run_with_active_session}` -- **drop the 3 paired `invoke=`/`run_active=_sess()` injections** (`session_lifecycle.py:689/859`, `session_fork.py:1198`) so the op defaults own them |
| `SessionManager` (56)                                                                            | `forge.session`                                                                    | per-CLI-module seam where each command constructs it (`session_lifecycle` / `session_fork` / `session_manage` / `session_codex`)                                                                                                |
| `_resolve_routing_from_cli` (14)                                                                 | defined `session.py:73`                                                            | caller-module seam (caller imports directly)                                                                                                                                                                                    |
| `_generate_parent_transfer_context` (10)                                                         | defined `session.py:461`                                                           | caller-module seam                                                                                                                                                                                                              |
| `_auto_install_extensions` (5), `_get_active_session_entry` (3), `_detect_parent_extensions` (1) | defined `session.py`                                                               | caller-module seam for runtime callers; direct tests of `session.py`-defined helpers (notably `_detect_parent_extensions`) stay on `forge.cli.session` unless the helper itself moves                                           |
| `generate_unique_name` (2)                                                                       | `forge.core.naming`                                                                | caller-module seam (or `forge.core.naming.generate_unique_name`)                                                                                                                                                                |
| `_delete_single_session` (2), `_warn_if_*` (2)                                                   | confirm (likely `session_manage` / `session.py`)                                   | caller-module seam                                                                                                                                                                                                              |
| `_session_cli()` local seam (0 parent patches)                                                   | `session_resume_modes.py:23` lazy-imports `forge.cli.session`                      | direct imports from `session_lifecycle`, `session.py`, and `forge.cli.output`; no patch-count effect, but 5d cannot delete the shim until this local-var seam is gone                                                           |

**Sub-slices (easy -> hard; each independently shippable -- the shim degrades symbol-by-symbol):**

- [x] **5a -- long tail (~40 patches).** For each low-volume symbol, replace `_sess().X` with a direct import + call in
  the caller module and repoint that symbol's patches to the caller-module seam. Done 2026-07-02: migrated routing,
  transfer-context, extension install, active-session, naming, delete, and warning seams. Remaining runtime `_sess()`
  calls are only the planned 5b/5c symbols (`SessionManager`, `invoke_claude`, `run_with_active_session`), while the
  separate `_session_cli()` local-var seam is deferred to 5a.5. Parent patch lines are down to **207**. The stale-parent
  grep for these 5a symbols is empty. `_detect_parent_extensions` remains a `forge.cli.session` patch seam because the
  helper is still defined and directly unit-tested in `session.py`.
- [ ] **5a.5 -- `_session_cli()` resume-mode local seam (0 parent patches).** Replace `session_cli = _session_cli()` in
  `session_resume_modes.py` with direct imports for the 26 local calls: `_execute_resume_launch_plan`,
  `_get_effective_proxy_for_session`, `_get_resume_launch_preferences`, `_resolve_manifest_prompt_file`,
  `_resume_launch_preferences_for_op`, `_resume_routing_for_op`, `console`, `handle_session_error`, and
  `print_error_with_tip`. This does not change the 207 patch count, but it must land before 5d's `def _session_cli`
  deletion gate. Run the rewind/native resume tests that exercise both functions.
- [ ] **5b -- `SessionManager` (56 patches, 11 call sites).** Each CLI module constructs `SessionManager` directly;
  repoint its patches to that module's seam. Fragmented by command (no single seam).
- [ ] **5c -- `invoke_claude` + `run_active` (149 + 1 patches).** Drop the 3 *paired* injections
  `invoke=_sess().invoke_claude` + `run_active=_sess().run_with_active_session` (adjacent at
  `session_lifecycle.py:689/859`, `session_fork.py:1198`); let `launch_claude_session` use its module defaults
  (`invoke or invoke_claude`, `run_active or run_with_active_session`). Repoint the 149 `invoke_claude` patches and the
  1 `run_with_active_session` patch to `forge.core.ops.claude_session.{invoke_claude,run_with_active_session}`.
  **Atomic:** injection removal and patch repoint must land together (see false-green risk).
- [ ] **5d -- delete the shim.** Remove the remaining lazy seams (4 `_sess()`, with `_session_cli()` already gone in
  5a.5); convert the `import *` re-export tail (`:624-626`) to **side-effect imports**
  (`from . import session_fork  # noqa: F401`) so command registration survives; drop the 3 name re-exports
  (`:619-621`). **Migrate the direct-import category:** repoint every
  `from forge.cli.session import <submodule-owned-name>` (currently the 6 test files, e.g. `delete`; today's src imports
  are all session.py-owned and stay) to its owning module. Final gates:
  `grep -rnE 'def _sess|def _session_cli|sys\.modules\["forge\.cli\.session"\]' src/forge/cli/` -> 0; no parent-module
  patches for names owned outside `session.py`; every surviving `patch("forge.cli.session.X")` or
  `from forge.cli.session import X` targets a `session.py`-defined name.

**Risks:**

- **False green (the #1 risk).** Repointing a patch to a seam the code no longer routes through leaves the mock silently
  uncalled -- the test still passes but verifies nothing. After each symbol, prove the new seam is live: temporarily
  make the target raise and confirm the migrated tests now **fail**, or add `assert_called` where practical. This is why
  5c couples the injection change with the patch repoint.
- **5c poison gate.** For the `invoke_claude`/`run_with_active_session` wave, grep-only verification is insufficient.
  Before declaring 5c done, temporarily poison the **old** parent seam (`forge.cli.session.invoke_claude` and
  `forge.cli.session.run_with_active_session`) to raise while the new `forge.core.ops.claude_session.*` patches are in
  place; the migrated tests must still pass. Also make at least one representative new-seam mock assert it was called.
  Poisoning only the new op seam and expecting patched tests to pass is not enough, because forgotten `_sess()`
  injection would still bypass it.
- **Command registration (5d trap).** `from .session_fork import *` doubles as the side-effect import that runs the
  `@session.command()` decorators. Convert it, do not delete it, and verify `forge session --help` still lists
  start/resume/fork/... and a leaf like `forge session fork --help` works.
- **Direct-import breakage (3rd category).** Converting `import *` also drops submodule-owned names from
  `forge.cli.session`'s namespace, so `from forge.cli.session import delete` (6 test files) breaks. Current src imports
  are session.py-owned (`console`, `handle_session_error`) and unaffected. Repoint the submodule-owned imports to the
  owning module in 5d -- the patch-site sweep alone will not catch them.
- **Circular import.** Removing the re-export tail shifts load order; a submodule that newly imports `forge.cli.session`
  at top level can break the cycle. Keep such imports function-local or side-effect only, and run
  `python -c "import forge.cli.session"` after 5d.
- **Highest-churn, one file.** 183/245 patches live in `test_session_commands.py`; migrate by symbol and run that file
  after each.

**Invariants:**

- No behavior change: every migrated call resolves to the same function it does today.
- `session.py` command logic and the `session` group stay; only the `_sess()` indirection + wildcard re-export go.
- `core/ops` + `session/` still import no `forge.cli`; ops stay render-free.
- CLI command tree unchanged (`forge session --help` identical before/after).

**5a verification (2026-07-02):** stale-parent grep for the migrated tail symbols returned empty;
`rg -n "_sess\(\)\." src/forge/cli/session_lifecycle.py src/forge/cli/session_fork.py src/forge/cli/session_codex.py src/forge/cli/session_manage.py`
shows only `SessionManager` / `invoke_claude` / `run_with_active_session`;
`python -m py_compile src/forge/cli/session_lifecycle.py src/forge/cli/session_fork.py src/forge/cli/session_codex.py src/forge/cli/session_manage.py`;
`python -c "import forge.cli.session"`; `uv run forge session --help`;
`uv run pytest tests/src/cli/test_session_commands.py tests/src/cli/test_session_model_pins.py tests/src/cli/test_session_rewind_cli.py tests/src/cli/test_session_codex.py tests/src/cli/test_session_extensions.py -q`
-> **338 passed**.

**Verification (per sub-slice + final):** affected test file(s) after each symbol;
`python -c "import forge.cli.session"` (no cycle error); `forge session --help` + a couple of `--help` leaves; full
`uv run pytest tests/src/cli tests/regression -q`;
`./scripts/test-integration.sh tests/integration/docker/test_session_lifecycle.py -v` (real `claude -p` seam -- the
`invoke_claude` migration touches the launch path); `make pre-commit`. **Final gates (5d):** the three greps above (no
lazy seam in `src/forge/cli/`, no parent-module patch/import for submodule-owned names, and command registration/import
smokes green).

## Roadmap

| Slice | Scope                                                                                                             | Crux                                                                                                             |
| ----- | ----------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| 1     | system-prompt op + model-pin cluster relocation + characterization test                                           | Low-risk pattern and harness                                                                                     |
| 2     | `start_claude_session -> ClaudeSessionStartResult`                                                                | Relocate launcher/invoker seams out of CLI-safe wrappers                                                         |
| 3     | `resume_claude_session -> ClaudeResumeResult`                                                                     | Collapse repeated launch/resume routing/model/preference logic                                                   |
| 4a    | fork launch migration (`fork_claude_session`)                                                                     | 4a.1 delete `_launch_claude_for_session`; 4a.2 unify 4 host closures into the op (launcher already resolves cwd) |
| 4b    | 4b.1 unify fork supervisor wiring onto core `_apply_supervisor_wiring`; 4b.2 (conditional) sidecar-internal tests | Sidecar prep already core-owned; only fork supervisor persistence still duplicated in CLI                        |
| 5     | Retire the `_sess()` shim (5a tail -> 5b SessionManager -> 5c invoke_claude -> 5d delete)                         | Untangle the circular-import shim; migrate 256 `forge.cli.session.X` patches to real seams; patch-count -> 0     |

## Closeout Items

- [x] Slice 1 assertions ticked with verification recorded.
- [x] `docs/board/change_log.md` entry added for Slice 1.
- [x] `make pre-commit` clean.
- [x] Integration result recorded, including any environment limitation.
- [x] Card remains in `doing/` after Slice 1; move to `done/` only when all 5 slices land.
