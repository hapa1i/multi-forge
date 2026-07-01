# session_op_layer_extraction -- mirror the Codex core-ops split for the Claude launch path

**Lane**: `proposed/` -- accepted-candidate **refactor**, not yet scheduled. Behavior-preserving structural extraction;
not blocking other work.

**Origin**: focused audit, 2026-07-01 (session lifecycle CLI/core boundary), grounded by a parallel read-only mapper
sweep (Codex template, Claude-path entanglement, `_sess()`/patch-site metrics, design-doc anchors) and re-verified with
exact `grep` patterns on the current checkout.

**Type**: single **refactor card**, staged into slices -- deliberately **not an epic**. It unwinds one code seam (the
Claude launch path) in sequence; there is no set of independently-shippable member cards sharing a contract
(`board_contract.md` epic test). The slices below are sequential reductions of the same seam, tracked in one
`checklist.md` when this moves to `doing/`.

**Relation to `accidental_complexity_cleanup`**: that card explicitly lists the `cli-session` module split + its
`_sess()` re-export layer under *do-not-simplify-first* ("documented consequence of the 2.5K-line limit + 255 test patch
targets"). This card is the deliberate, staged unwind of exactly that shim -- so it must land **after** or independently
of the cleanup batch, never as part of a Batch-A single-file PR.

**References**: `docs/design.md` §3.12 (command-core ops -- the normative pattern this mirrors);
`docs/developer/cli_style_guidelines.md` §Command Shape (lines 72-76: ops are UI-agnostic, no Click/printing/hook-JSON,
return structured data; CLI + direct-command layers own rendering); `docs/design_workflows.md` §3.5 (runtime
capability-vs-lifecycle seam); `src/forge/core/ops/codex_session.py` (the in-repo template to copy).

---

## Why (the thesis)

The Codex path already has most of the clean split the whole session surface is supposed to have. The business core
(session creation, Codex invocation, state mutation, rollback) is pure in `core/ops/codex_session.py`, and
`session_codex.py` is *mostly* a thin dispatch+render layer (Click option decorators, flag-matrix validation, Rich
rendering). It is not perfectly clean -- it still reaches through `_sess()` for name generation and
active-session/session lookups (`:199-201`, `:273`, `:452`) -- but the load-bearing logic lives in the op module, not
the CLI. `design.md` §3.12 makes this the *normative* shape: ops live in `src/forge/core/ops/`, contain no
Click/printing/hook-JSON, and return structured results; the CLI and `%direct` command layers own rendering.

The Claude launch path never got this treatment. `session_lifecycle.py` interleaves session creation, proxy-routing
resolution, model-pin validation, supervisor wiring, UUID pre-seeding, memory/subprocess-proxy mutations, and sidecar
Docker prep **directly with** Rich rendering and `sys.exit`, across three 250-300+ line entrypoints plus five private
launch/resume helpers. Three consequences:

1. **Test coupling to the parent re-export.** **255** `patch("forge.cli.session.<name>")` sites across **13** test files
   patch functions through the parent module (the `session.py:17` shim). The module split into `session_lifecycle` /
   `session_fork` / `session_manage` / `session_codex` kept a `_sess()` runtime-lookup shim in **4** modules purely so
   those patches keep resolving. Business logic cannot be exercised without importing the CLI module.
2. **Duplication across the resume/launch helpers.** `_apply_and_persist_direct_model_override` is applied **5x**;
   routing-override application, context-limit resolution, and launch-preference unpacking are repeated across the five
   `_launch_*` / `_resume_*` helpers.
3. **The exemplar itself still leaks the shim.** `session_codex.py` -- the "thin renderer" -- both defines `_sess()` at
   `:53` and calls it 5x (`:199-201`, `:273`, `:452`) for name generation and active-session/session lookups. Even the
   clean side reaches back through the parent re-export, so the shim outlives a purely-CLI refactor.

This is a **behavior-preserving structural extraction** that mirrors an existing, proven in-repo pattern. It is not a
deletion (there is no dead code here) and not an over-abstraction removal.

---

## Non-goals / must-not-break

- **No behavior change.** Same flags, same manifest writes in the same order, same dispatch semantics.
- **Rendering stays in the CLI.** `console.print`, `_print_routing_summary`, the interactive `_pick_session` picker,
  `open_in_editor` (`--review`), and all `sys.exit` / `print_error` / `print_tip` calls remain in
  `cli/session_lifecycle.py`.
- **Dispatch invariants preserved** (pin with existing tests *before* moving code):
  - Codex-runtime dispatch happens **before** Claude predicates (`:1340`, `:1651`).
  - Fresh-resume writes the pre-seeded UUID **before** launch so the SessionStart hook can detect it.
  - The active-session reconnect guard (`:1741-1758`) still blocks concurrent reconnect without `--force`.
- **Durable-state seams stay untouched** -- the three-layer override validation and atomic `temp+os.replace+fsync`
  writes the cleanup card marks Essential are out of scope.

---

## Target shape (mirror `core/ops/codex_session.py`)

New `src/forge/core/ops/claude_session.py`: UI-agnostic, `ForgeOpError` on failure, `ExecutionContext` parameter, frozen
result dataclasses replacing tuple-unpacking and inline `store.update()` calls.

| Core op (new)                                                 | Codex mirror                                                | Replaces (cli anchor)                               |
| ------------------------------------------------------------- | ----------------------------------------------------------- | --------------------------------------------------- |
| `start_claude_session(...) -> ClaudeSessionStartResult`       | `start_codex_session:170 -> CodexSessionStartResult:83`     | `launch_new_session` body (`:818`)                  |
| `resume_claude_session(...) -> ClaudeResumeResult`            | codex resume + `CodexSessionResumeResult:100`               | `resume` dispatch (`:1515`) + 5 helpers             |
| `resolve_claude_session` / `require_*`                        | `resolve_codex_session:117` / `require_codex_thread_id:159` | `manager.get_session` + active guard (`:1617-1651`) |
| `validate_and_resolve_direct_model(...)`                      | --                                                          | `resolve_direct_model_pin` + the 5x override        |
| `validate_and_setup_supervisor(...) -> SupervisorSetupResult` | --                                                          | supervisor wiring (`:1016-1061`)                    |
| `resolve_and_validate_system_prompt(...)`                     | --                                                          | prompt-file resolution (`:910-920`)                 |
| `apply_launch_routing(...)`                                   | --                                                          | `_apply/_persist` routing override (repeated)       |
| `prepare_sidecar_session(...) -> SidecarPrepResult`           | --                                                          | Docker preflight + env (`:453-588`)                 |

Result dataclasses (frozen), mirroring `CodexSessionStartResult` / `CodexSessionResumeResult`:
`ClaudeSessionStartResult`, `ClaudeResumeResult`, `SupervisorSetupResult`, `SidecarPrepResult`. Structured returns
replace the current tuple-unpacking and the 50+ inline `store.update()` mutations scattered through the launch path.

---

## Phased plan (each slice independently landable; patch sites migrate incrementally)

| Phase | Scope                                                                                                                                                                                                              | Exit signal                                                            |
| ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------- |
| 1     | Scaffold `core/ops/claude_session.py`; extract the two lowest-risk pure helpers first: `resolve_and_validate_system_prompt`, `validate_and_resolve_direct_model`. Migrate their patch sites off the parent module. | Parent patch-count strictly drops; new ops import no Click/console     |
| 2     | Extract `start_claude_session -> ClaudeSessionStartResult`; `launch_new_session` becomes dispatch+render. Migrate start-path patches.                                                                              | `launch_new_session` holds only validation-dispatch + rendering        |
| 3     | Extract `resume_claude_session -> ClaudeResumeResult`, collapsing the five `_launch_*`/`_resume_*` helpers' repeated routing/model/preference logic. Migrate resume-path patches.                                  | 5x `_apply_and_persist_direct_model_override` collapses to one op call |
| 4     | Extract `validate_and_setup_supervisor` + `prepare_sidecar_session`. Migrate their patches.                                                                                                                        | Supervisor/sidecar logic testable without the CLI module               |
| 5     | **Retire the shim.** Delete `_sess()` in all 4 modules (incl. `session_codex.py:53`) and the `session.py:17` re-export comment.                                                                                    | `def _sess` count = 0; parent patch-count = 0                          |

Phase 5 is **gated on the entire session-family test surface**, so the payoff is back-loaded: `_sess()` cannot be
removed until every parent-module patch site (across all 4 modules) has migrated. Do not expect the shim to vanish after
slice 1.

---

## Metric (how to measure progress)

```bash
# Migration burden -- the shim exists for exactly these patch-call sites:
grep -rEno 'patch\(["'"'"']forge\.cli\.session\.[A-Za-z_]+' tests/ | wc -l   # 255 today, across 13 files
# Shim definitions to delete at the end:
grep -rn 'def _sess' src/forge/cli/                                          # 4: session_lifecycle:80, session_fork:54, session_codex:53, session_manage:33
```

- **255** parent-module patch-call sites across **13** test files = the burden. The refactor is **done** when this
  reaches 0 and all four `def _sess` are deleted.
- **47** split-module patch-calls (`patch("forge.cli.session_<mod>...")`) already target the correct module and are
  unaffected.
- `_sess()` is defined in exactly **4** modules (the session-command cluster). It is **not** in `policy.py` or
  `statusline/` -- earlier notes claiming "7 modules" were loose-grep false matches (`_session_option`,
  `_session_scope_key`, `_session_cost_cache_path`).

---

## Risks

- **Large surface, high patch churn.** 255 sites; migrate per-slice, never big-bang. Each slice's PR should move one op
  and repoint only that op's patches.
- **Behavior drift is the failure mode**, not test breakage. Every slice must be a pure move: identical `store.update()`
  calls in identical order. Add a manifest-diff characterization test (start + one resume branch) *before* extracting
  the `start`/`resume` bodies, so any reordering is caught.
- **Dispatch-order invariants** (codex-before-claude, UUID-pre-seed-before-launch, reconnect guard) must survive
  extraction. Pin them with the existing lifecycle tests first.
- **Coupling to `accidental_complexity_cleanup`**: land this independently of that card's `#9`/`#10` session-manifest
  touches to avoid rebase churn in `session_manage.py` / `core/ops/session.py`.

---

## Acceptance (per-slice assertion pattern)

A slice's checklist item is ticked only when:

1. The extracted op imports no `click`, `rich.console`, or `sys.exit` (grep the new module).
2. Its former patch sites now target `forge.core.ops.claude_session` -- the parent-module patch-count (`255 -> ...`)
   **strictly decreased**, and the new count is recorded in the checklist.
3. The focused test module **and** the session integration tests pass (`./scripts/test-integration.sh`
   `tests/integration/.../test_*session*.py`) -- this path exercises real `claude -p`/Docker seams unit tests never hit.
4. No behavior change: a manifest-diff test confirms the same confirmed/intent fields are written in the same order for
   `start` and at least one resume branch.

Phase 5 ticks only when `grep -rn 'def _sess' src/forge/cli/` returns nothing and the `session.py:17` shim comment is
gone.
