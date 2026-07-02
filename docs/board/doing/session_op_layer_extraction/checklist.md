# Checklist -- Session Op Layer Extraction

Execution plan for `card.md` (this dir). Branch: `session-op-layer`. This card is a staged, behavior-preserving
extraction of Claude session launch/resume logic out of the CLI layer, mirroring the Codex core-ops split.

## Current Focus

**Slice 1 complete (2026-07-02):** characterization safety net added, launch system-prompt resolution extracted into
`forge.core.ops.claude_session`, and the CLI-free model-pin support cluster moved into `forge.session.model_pin`. This
slice intentionally did not touch the dangerous `invoke_claude`/launcher seam; the card remains in `doing/` for Slice 2.

**Slice 2 planned (2026-07-02):** detailed plan below, grounded by read-only exploration (anchors verified against the
current tree). Key outcome: Claude start is **interactive** (blocking child), so `start_claude_session` mirrors the
existing `core/ops/codex_interactive.py` op — NOT the headless `codex_session.py`, and NOT `core/invoker/`. Slice 2 is
split into **2a (pure relocations)** and **2b (the op)** because the combined scope is too large for one reviewable PR.
Next up: **2a**.

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

- Signature: `start_claude_session(*, ctx, name, <routing/launch params injected by CLI>, announce=None, invoke=None) -> ClaudeSessionStartResult`
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
- **Signature (P5):** use `invoke: Callable[..., int] | None = None` and resolve `invoke or invoke_claude` **in the body**
  (a call-time module global), NOT `invoke=invoke_claude` as a default. A default binds `invoke_claude` at import, so
  `patch("forge.core.ops.claude_session.invoke_claude")` would not take effect and the 146-site repoint would silently
  no-op. Late-binding keeps the repoint working. Same rule for `SessionManager` (call-time global, never a default).

### Relocation map (start-path seams -- verified)

| Primitive | Current location | Status | Action |
| --- | --- | --- | --- |
| `invoke_claude` | `session/claude/invoke.py:13` | already core | inject via `invoke=None` seam, resolve `invoke or invoke_claude` in body (P5) |
| `run_with_active_session` | `session/active.py:331` | already core | call directly |
| `SessionManager` / `generate_unique_name` | `session/…` / `core/naming.py:53` | already core | call directly |
| `_build_session_env` (+ `_resolve_subprocess_proxy_launch_metadata`, `_container_reachable_url`) | `cli/session.py:374` | UI-free | -> `forge.session.launch` |
| whole `launch_confirmation.py` (`_infer_launch_confirmation`, `record_launch_confirmed`, `read_proxy_cost_baseline*`, `_routing_mode_for`) | `cli/launch_confirmation.py` | UI-free | -> `forge.session.launch_confirmation` |
| `_cwd_forge_root` | `cli/session.py:223` | UI-free | -> `forge.core` (beside `find_forge_root`) |
| `_resolve_context_limit` | `cli/session.py:254` | UI-free | -> `forge.session`, **after** moving its dep `_get_context_limit_for_proxy` (+`_context_window_for_proxy_model`) out of `cli/claude.py:61` |
| `_resolve_routing_from_cli` | `cli/session.py:81` | **CLI-bound** | stays; inject `ResolvedRouting` into the op |
| `_prepare_sidecar_prompt_file` | `cli/session.py:536` | UI-free (pure path map) | -> `forge.session.launch` |
| `_warn_if_hooks_missing` (`session_lifecycle.py:256`), `_warn_if_version_outdated` (`:276`), `_auto_install_extensions` (`session.py:557`) | CLI | **UI-tangled** (`console.print`/`print_tip`) | stay CLI; split logic from render or trigger via `announce`/`warnings` -- the op never prints |

**Start-path arithmetic (corrected):** ~3 already core (`invoke_claude`, `run_with_active_session`, `SessionManager`),
5 UI-free relocate (`_build_session_env`, `_prepare_sidecar_prompt_file`, `launch_confirmation.py`, `_cwd_forge_root`,
`_resolve_context_limit`), **~4 stay CLI-bound** (`_resolve_routing_from_cli` + the 3 render-warns/install above).

### Sub-slice 2a -- Clean-break relocations (repoint all callers, delete re-exports) [land first, independently]

- [ ] Move the UI-free primitives above into `forge.session.*` / `forge.core` **verbatim**, carrying their private
  helpers.
- [ ] **`launch_confirmation.py` (P1):** it is a standalone module imported by `session_lifecycle.py:19` **and**
  `session_fork.py:62`, with direct tests in `tests/src/cli/test_launch_confirmed.py` **and** an indirect import
  (`from forge.cli.session_lifecycle import _infer_launch_confirmation`) in
  `tests/regression/test_bug_delete_live_session.py`. Relocating it to `forge.session.launch_confirmation` must update
  **both** importers, repoint `test_launch_confirmed.py`, and keep `session_lifecycle` re-importing the names so the
  indirect regression import still resolves.
- [ ] **Patch-migration policy (P3):** 2a is a clean break -- **no** lingering compat re-exports for these helpers -- so
  every test that patched `forge.cli.session.<helper>` must repoint to the new home in the same change. The false-green
  trap this avoids: a test still patching a CLI re-export passes while exercising the shim, not the moved code -- which is
  exactly why the re-exports are deleted rather than kept. Applies to `_build_session_env`, `_cwd_forge_root`,
  `_resolve_context_limit`, and the launch-confirmation helpers.
- [ ] **Cross-path call-site migration (Nit 4):** these helpers are used well beyond the start path, via two import styles
  (late-bound `_sess().X()` and direct `from forge.cli.session import X`) -- both break the moment the symbol leaves
  `forge.cli.session` unless a re-export stays. **Decision: repoint every caller in 2a and delete each helper's CLI
  re-export** (clean break per `coding_standards.md` §5; avoids the false-green trap above and keeps the shim shrinking,
  not growing). Only the big symbols (`invoke_claude`/`SessionManager`) keep riding the shim until 2b/Slice 5. Inventory:
  - `_build_session_env`: `session_lifecycle.py:420`, `session_fork.py:843`.
  - `_resolve_context_limit`: `session_resume_modes.py:48,175`, `session_fork.py:646,814`,
    `session_lifecycle.py:1080,1909,2046,2114,2253`.
  - `_cwd_forge_root`: `session_lifecycle.py:939,1404,1652,2466`, `session_fork.py:429`, `session_codex.py:199`,
    `session_manage.py:134,801,1019` (+ direct import `:39`), `memory_report.py:44` (+ direct import `:25`).
  - launch-confirmation helpers: imports at `session_lifecycle.py:19-20` + `session_fork.py:62`; the parent-shim **call**
    `_sess()._infer_launch_confirmation(...)` at `session_lifecycle.py:706` (mutation-table row 11); the
    `session_lifecycle:162` re-export; **5** `patch("forge.cli.session._infer_launch_confirmation")` sites in
    `tests/regression/test_bug_nested_project_launch.py`; plus the indirect import in `test_bug_delete_live_session.py`
    (P1). All repoint when the module moves and the `forge.cli.session` re-export is deleted (Nit 3).

  If 2a's diff proves too large to review, the fallback is per-helper compat re-exports with a tracked cleanup task --
  but the default is repoint-all.
- [ ] **Prereq -- `_get_context_limit_for_proxy` clean-break:** relocate it (+ its private dep
  `_context_window_for_proxy_model`) out of `cli/claude.py` **before** `_resolve_context_limit`, with its own inventory.
  It is shared beyond the relocating helper, so a naive move strands `forge claude` or leaves a hidden CLI alias:
  - `forge claude` command: `claude.py:279`.
  - `_resolve_routing_from_cli` (stays CLI -- imports from the new home): `session.py:98,142`.
  - `_resolve_context_limit` (also relocating): `session.py:271,282`.
  - regression tests importing `from forge.cli.claude import _get_context_limit_for_proxy`:
    `tests/regression/test_removal_patching_system.py:122,143,147,168`.

  `_context_window_for_proxy_model` is internal to `claude.py` (only `:82`); it moves as the private dep.
- [ ] Execute the render-seam disposition from the map (no longer "unassessed"): relocate `_prepare_sidecar_prompt_file`
  (UI-free); keep the 3 UI-tangled warn/install helpers in the CLI.
- [ ] Repoint **all** touched tests to the new locations -- start **and** the fork/resume/manage/codex/memory-report call
  sites in the inventory above, not just the start path.
- **Assertions:** pure moves (characterization test green; no error-text or mutation-order change); layering grep clean
  on every new module; `session_lifecycle.py` line count non-increasing.

### Sub-slice 2b -- The op

- [ ] Add frozen `ClaudeStartLaunch` (announce payload) + `ClaudeSessionStartResult` (`exit_code`, `session`,
  `worktree_path`, `warnings`, `operation_started_at`, plus the confirmed facts the post-exit render needs:
  `routing_mode`, `proxy_id`, `base_url`, `is_sandboxed`, `claude_project_root`, **and `store_exists`** (Nit 3)).
  `store_exists` is captured **post-run but before the incognito cleanup `finally`** (`_launch_claude_for_session:708`
  reads `store.exists()` for `_post_exit_render`; the incognito delete runs later, at `:1138`). So it is **True** for
  incognito at capture -- it does **not** track incognito auto-delete; it flags a session **deleted during the run**
  (e.g. in-session `forge session delete`), which drives the "was deleted during this run" message (`:727`). The op must
  capture at the same point (Nit 5); the CLI cannot re-derive it without re-reading state.
- [ ] Write `start_claude_session` mirroring `start_interactive_codex_session`: preserve the ordered mutation contract in
  the table below **exactly** (host and sidecar differ), the sidecar-vs-host branch, and the **staged pre-launch event
  sequence** (created/routing -> extensions -> no-launch) fired at its current anchors (Nit 1), not a single
  pre-run `announce`.
- [ ] The 3 UI-tangled warn/install helpers are inside the launcher body the op will own (warns at `:435-436`,
  auto-install at `:1103`). Preserve their current pre-launch print timing: split each into a logic core (op) + a render
  the CLI performs (via `announce`/injected hook), rather than collecting into `warnings` (which would move the output to
  after the child exits -- a timing change).
- [ ] Convert **every** CLI-error exit inside `_launch_claude_for_session` to `raise ForgeOpError` (Nit 2): the direct
  `sys.exit(1)` sites (`:468/487/495/629`) **and** the `print_error(...) + return 1` paths -- runtime-dispatch backstop
  (`:392`), direct-model env error (`:675`), proxy model-pin error (`:683`). The op cannot `print_error`; the CLI renders
  the `ForgeOpError` message.
- [ ] **Shared-launcher compatibility (Nit 1):** `_launch_claude_for_session` has **9 callers**, only 2 on the start path
  (`:1123`/`:1152`). The rest -- resume/reconnect (`:1986`/`:2066`/`:2136`/`:2363`, `session_resume_modes.py:135`/`:227`)
  and fork (`session_fork.py:1239`) -- migrate in Slices 3/4, not now. 2b extracts the body into a core helper that raises
  `ForgeOpError` and stays render-free; the start op consumes it directly.
- [ ] **The resume/fork adapter is NOT thin:** the launcher body currently owns a large render/post-exit surface that
  resume/fork depend on -- hook/version warns (`:435-436`), the sidecar status block (`:583-600`),
  `record_launch_confirmed` (`:572`/`:657`), `_infer_launch_confirmation` (`:706`), and `_post_exit_render`
  (`:621`/`:708`). A `try/except -> print_error -> return 1` wrapper would force the render-free core to either print
  (breaking layering) or **silently drop** all of it. So the adapter must consume the **same event/result contract as the
  start op** (`ClaudeStartLaunch` events + `ClaudeSessionStartResult`) and reproduce the warns, sidecar status, and
  post-exit render for resume/fork until Slices 3/4 convert them. The contract is shared launcher infra, not start-only --
  which raises 2b's scope; if it grows too large, split the adapter bridge into its own sub-slice.
- [ ] Preserve the **incognito** contract: the delete-on-exit `finally` wraps **only** the launch (never
  creation/validation); render suppression for incognito. Decide owner: op-owned finally vs CLI wrapper around the op.
- [ ] Rewire `launch_new_session`: resolve routing (CLI) -> `start_claude_session(...)` with the staged event handlers
  (created/routing, extensions, no-launch) rendering at their current points -> render post-exit from the result ->
  `sys.exit` at the command boundary.
- [ ] Migrate the bulk patch sites: `invoke_claude` (146) + `SessionManager` (54) repoint from `forge.cli.session.*` to
  the op/core locations (or pass `invoke=`); record the new parent patch count (target: material drop from 270).
- **Assertions:** op imports no `forge.cli`, no Click/Rich/`sys.exit`; characterization test green (manifest
  byte-identical for start **and** incognito); error precedence + mutation order unchanged; incognito `finally`
  preserved; both sidecar and host launch paths exercised; parent patch count drops materially.

### 2b -- ordered mutation contract (verified line anchors in `session_lifecycle.py`)

This is the behavior-preservation contract for the op. Preserve order and branch exactly.

| # | Line | Call | Branch | Purpose |
| - | ---- | ---- | ------ | ------- |
| 1 | 958 (uuid @970) | `manager.start_session(claude_session_id=pre_seeded_uuid)` | both | create session (+ optional worktree) + pre-seed UUID |
| 2 | 1012 | `_MemStore.update(_set_memory)` | if `memory_flag` | enable `intent.memory.auto_update`; reassigns `manifest` |
| 3 | 1020 | `_SPStore.update(...)` | if `subprocess_proxy` | set `intent.subprocess_proxy`; re-read `manifest` @1024 |
| 4 | 1070 | `store.update(apply_supervisor_and_lane)` | if `supervise_target` | supervisor config + lane; re-read @1071 |
| 5 | 457 | `store.update(claude_project_root)` | first launch only | persist launch root (in `_launch_claude_for_session`) |
| 6 | 490 | `store.update(is_sandboxed=True)` | sidecar | |
| 7 | 572 | `record_launch_confirmed(...)` | sidecar | routing_mode=proxy, proxy_id, base_url, sidecar key decision, cost baseline |
| 8 | 625 / 632 | `store.update(is_sandboxed=False)` | sidecar rollback | on `ContainerExistsError` / any exception, then re-raise |
| 9 | 638 | `store.update(is_sandboxed=False)` | host | |
| 10 | 657 | `record_launch_confirmed(...)` | host | `_routing_mode_for`, proxy_id, base_url, `compute_interactive_api_key_decision(interactive=True)`, cost baseline |
| 11 | 706 | `_infer_launch_confirmation(...)` | host, post-exit | only if `exit_code == 0 and not fork_session` |

Rows 1-4 run in `launch_new_session` before the launcher; 5-11 in `_launch_claude_for_session`. **Host path** = 5, 9, 10,
11; **sidecar path** = 5, 6, 7, 8. Rollback boundary: rows 6-8 unwind `is_sandboxed` on failure and re-raise; there is
**no** post-launch rollback (parity with `codex_interactive` -- "after launch the session is the user's"), except the
incognito delete-on-exit `finally`.

### Acceptance tests (2a + 2b)

- [ ] Layering: `grep -rn "from forge.cli\|import forge.cli" src/forge/core/ops/ src/forge/session/`  -> empty for new modules.
- [ ] Characterization: `uv run pytest tests/src/session/test_claude_session_manifest_characterization.py -q` green
  before and after each sub-slice (extend with an incognito-start snapshot in 2b).
- [ ] Focused: `uv run pytest tests/src/cli/test_session_commands.py tests/src/cli/test_session_model_pins.py -q`.
- [ ] Integration: `./scripts/test-integration.sh tests/integration/docker/test_session_lifecycle.py -v`.
- [ ] `make pre-commit` clean.

### Open items to resolve during 2a

- Staged pre-launch event contract (Nit 1): the exact event set (`on_created`/`on_extensions`/`on_no_launch`) and how the
  3 UI-tangled render seams (`_warn_if_hooks_missing`, `_warn_if_version_outdated`, `_auto_install_extensions`) hang off
  it. (`_prepare_sidecar_prompt_file` is resolved -- UI-free, relocates.)
- Incognito `finally` ownership (op vs CLI wrapper).
- Whether the 3 render seams stay inline in the CLI event handlers (preserves current timing) or move to
  `result.warnings` (moves output to after the child exits -- a timing change). Behavior-preservation favors inline
  unless deliberately changed.

## Roadmap

| Slice | Scope                                                                   | Crux                                                              |
| ----- | ----------------------------------------------------------------------- | ----------------------------------------------------------------- |
| 1     | system-prompt op + model-pin cluster relocation + characterization test | Low-risk pattern and harness                                      |
| 2     | `start_claude_session -> ClaudeSessionStartResult`                      | Relocate launcher/invoker seams out of CLI-safe wrappers          |
| 3     | `resume_claude_session -> ClaudeResumeResult`                           | Collapse repeated launch/resume routing/model/preference logic    |
| 4     | `validate_and_setup_supervisor` + `prepare_sidecar_session`             | Test supervisor/sidecar without CLI module                        |
| 5     | Retire the shim                                                         | Delete all 4 `_sess()` defs and the parent `session.py` re-export |

## Closeout Items

- [x] Slice 1 assertions ticked with verification recorded.
- [x] `docs/board/change_log.md` entry added for Slice 1.
- [x] `make pre-commit` clean.
- [x] Integration result recorded, including any environment limitation.
- [x] Card remains in `doing/` after Slice 1; move to `done/` only when all 5 slices land.
