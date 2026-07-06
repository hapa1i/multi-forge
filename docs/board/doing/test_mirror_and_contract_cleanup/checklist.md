# Checklist: test_mirror_and_contract_cleanup

Execution plan for the test-mirror / contract-cleanup refactor batch. See `card.md` for the full thesis, target shape,
and per-slice rationale.

**Type**: behavior-preserving refactor batch **plus one defect-fix (Slice 5)**. Six independently landable slices.

**Branch**: `refactor/test-mirror-contract-cleanup` (single branch for the batch; slices commit independently and MAY be
split into separate PRs if review prefers).

---

## Current focus

**Board setup done; implementation NOT started -- checklist under review.** Card moved `proposed/ -> doing/`, stale
`Lane:` metadata corrected, and a "superseded" note added to the card's stale tables. No code touched, nothing
committed.

### Pickup decisions (2026-07-06)

- **Single batch card, not per-slice member cards.** The card's "When accepted" note suggests promoting per-slice member
  cards or an `epic_test_contracts` coordinator. Judged overkill for six small, low-risk, thematically-unified slices
  with no shared sequencing; precedent is `accidental_complexity_cleanup` (batches A/B/C on one card). Override by
  splitting if any slice grows or needs an independent release cadence.
- **Anchors re-verified against `HEAD` (`7b62b712`) on 2026-07-06** (card predates PR #84). Corrections folded in below;
  two card claims did not survive verification (Slice 2 "identical patches"; Slice 6 "byte-identical walkers"). A second
  review round (2026-07-06) added: the missing billing test (Slice 1); precise Slice 2 rescope + credential/cost_tracker
  carve-outs; concrete Slice 5 public names; a corrected docs-sync note; and resolved D1-D3.

### Card corrections from anchor verification (READ BEFORE EXECUTING)

- **Slice 2 -- the "5 identical monkeypatches" premise is inaccurate.** The 5 sites patch
  `forge.core.auth.template_secrets.resolve_env_or_credential` with **different return values** (`"UPSTREAM-KEY"` /
  `"sk-test"` / keyless `None`) across **four test packages** (proxy / review / policy / session), and one
  (`test_models.py`) is a `@patch` decorator, not `monkeypatch.setattr`. They do NOT cluster into one shareable fixture.
  The genuinely-shared, in-scope duplication is the **proxy runtime-state baseline** --
  `server._ensure_runtime_state -> lambda: None` (paired often with `server.cost_tracker = None`) -- repeated ~15x in
  `test_passthrough.py` and several times in `test_responses_transport.py`. -> **Slice 2 rescoped (below); D1 RESOLVED
  (a).**
- **Slice 6 -- the "4 byte-identical git-root walkers" claim is false.** Only `cli/extensions.py:47` and
  `core/ops/context.py:65` are true structural twins (and even they differ by one `.resolve()` call). `cli/codex.py`'s
  `_project_root()` (checks `.git` **or** `.codex`, never returns `None`) and `session/claude/paths.py`'s
  `find_project_root()` (raises `FileNotFoundError`, worktree-aware) are **intentionally divergent contracts**. ->
  **Slice 6 narrowed to the two real twins; the divergent two are PRESERVED (Slice-5-style).**
- **Slice 1 -- the mirror is package-level, not 1:1, and there are 6 statusline test files.** Move all six focused
  subpackage test files (below); the broader `session/` manager tests that also import `session.claude`
  (`test_manager_integration.py`, `test_manager_delete.py`, `test_fork_into.py`) STAY put. Parent `conftest.py` applies
  recursively -- no conftest move needed.

---

## Slice 1 -- test subpackage mirror (refactor, safest)

Move the focused subpackage tests into mirrored dirs. **Move, never skip** (testing_guidelines).

- [ ] **1.1** Create `tests/src/cli/statusline/` and `git mv` all **6** flat `test_statusline*.py` files into it:
  `test_statusline_forge_segments.py`, `test_statusline_session_cost_throttle.py`, `test_statusline_throttle.py`,
  `test_statusline_palette.py`, `test_statusline_registry.py`, **and `test_statusline_billing.py`**. (Billing imports
  `forge.cli.status_line` -- the renderer that is the public face of the `statusline/` subpackage's segment system -- so
  the six move together as the statusline **feature-area** mirror. If you prefer a strict subpackage-only mirror, split
  billing into a flat `test_status_line.py` instead and record why.) Assertion: `git mv` (rename tracked), imports
  unchanged.
- [ ] **1.2** Create `tests/src/session/claude/` and `git mv` the 4 focused claude test files: `test_claude_cleanup.py`,
  `test_claude_invoke.py`, `test_claude_relocate.py`, `test_claude_paths.py`. **Do NOT move**
  `test_manager_integration.py`, `test_manager_delete.py`, `test_fork_into.py` (manager-scoped, not claude-subpackage).
- [ ] **1.3** Confirm no new `conftest.py` needed (parent conftests apply recursively); add one only if a
  statusline-/claude-scoped fixture emerges. Assertion: no fixture regressions.
- [ ] **1.4** `uv run pytest tests/src/cli/statusline tests/src/session/claude -q` green; collected count for those
  files unchanged (moved, not dropped).

**Exit signal:** source->test mirror clean for the two subpackages; zero skips; test count unchanged.

## Slice 2 -- opt-in proxy runtime-state fixture (refactor) -- D1 RESOLVED (a)

The repeated boilerplate is the **runtime-state baseline**: `server._ensure_runtime_state -> lambda: None`, frequently
paired with `server.cost_tracker = None` ("runtime ready, no cost tracking"). Only THIS clusters. The credential patches
and the cost-behavior tests do not.

- [ ] **2.1** Introduce an **opt-in** fixture (e.g. `proxy_runtime_ready` in `tests/src/proxy/conftest.py`, composing
  with the existing `server_stubs` at `conftest.py:135-150`) that stubs `_ensure_runtime_state -> lambda: None` and
  (variant) `cost_tracker = None`. Apply it **only** to the tests that currently repeat that baseline. Assertion: the
  named baseline tests consume the fixture; their inline `_ensure_runtime_state` (+ `cost_tracker=None`) boilerplate is
  gone.
- [ ] **2.2 Carve-outs (do NOT touch):**
  - Tests that set a **specific** `cost_tracker` -- `_Tracker()` (`test_passthrough.py:598`),
    `_cap_tracker(on_cap_hit=…)` (`test_responses_transport.py:878,910`) -- test cost/cap behavior and keep their
    explicit setup (they may still use the fixture for `_ensure_runtime_state` and override `cost_tracker`).
  - The **credential patches** (`resolve_env_or_credential`, incl. `test_responses_transport.py:549`) -- D1: left alone.
    They are behavior-divergent, and the cross-package keyless cases test billing posture.

**Exit signal:** the runtime-state baseline boilerplate is shared via one opt-in fixture at its repeated sites;
cost-behavior and credential setups stay explicit. (**NOT** "no inline `_ensure_runtime_state`/`cost_tracker` anywhere"
-- that would erase deliberate cost setup.)

## Slice 3 -- shared Codex HeadlessResult factory (refactor, test-only) -- D2 RESOLVED

The 3 `_codex_result` copies differ ONLY in `label` + `stdout` defaults (`stderr=""`, `returncode=0`,
`duration_seconds=0.1`, lazy-import mechanics identical). Share the construction, keep behavior-specific values at the
call site.

- [ ] **3.1** Add a `codex_result(**overrides)` factory as an **importable helper** at `tests/fixtures/codex_result.py`
  (D2: `tests/fixtures/` is the established test package; a root fixture would thread params through many individual
  tests -- this is a pure object factory). Use a lazy `from forge.core.invoker.types import HeadlessResult` import.
  (Confirm at slice start whether the existing `tests/fixtures/codex/` package is the better home.)
- [ ] **3.2** Repoint `test_supervisor.py:55` (`label="supervisor"`, `stdout=""`), `test_shadow_curation.py:626`
  (`label="curation"`, `stdout="## Promote\n- Item"`), `test_memory_writer.py:1791` (`label="memory-writer"`,
  `stdout="## Promote\n- From codex"`) to the factory, passing only their distinct label/stdout. **Must-not-break:** do
  NOT unify the three Codex consumer contracts (impl_notes T6b/T6c) -- share construction only. Assertion:
  consumer-specific assertions unchanged.

**Exit signal:** one factory builds Codex headless results; per-consumer stdout/label stay local.

## Slice 4 -- output-helper routing + shim delete (refactor; two independent parts)

- [ ] **4a.1** Lift the recovery `Tip:` out of `review/routing.py:336,360` (currently baked into the
  `_raise_no_route_error` exception strings) so it is rendered at the CLI boundary via `forge.cli.output`
  (`print_error_with_tip`) in `cli/workflow.py:_handle_routing_error` (`:193`, currently
  `print_error(f"Routing failed: {msg}")`). Keep `review/` free of CLI-output imports -- carry tip DATA structurally on
  the exception, format at the CLI site (the ops-seam pattern). Assertion: user-visible recovery text preserved; no
  literal `Tip:` constructed in `review/`.
- [ ] **4b.1** Delete the `sidecar/secrets.py` re-export shim; repoint the 3 importers -- `sidecar/__init__.py:17`,
  `tests/integration/sidecar/test_auth_secrets_propagation.py:23`, `tests/src/sidecar/test_secrets.py:10` -- to
  `forge.core.auth.template_secrets`, **atomically in one commit** (coding_standards §5, no tombstone).
- [ ] **4b.2** Resolve `tests/src/sidecar/test_secrets.py`: repoint, or delete if redundant with an existing
  `template_secrets` test (check for `tests/src/core/auth/test_template_secrets.py` first). Assertion: no orphan shim
  test.

**Exit signal:** `test_cli_rich_tips_go_through_output_helpers` scope satisfied; no `forge.sidecar.secrets` importers
remain; shim gone.

## Slice 5 -- transcript primitives -> `core/transcript.py` (**DEFECT-FIX**, regression test MANDATORY)

Move the 4 low-level parsing primitives to the documented seam; converge the divergent `status_line` copy (fixes the
`human`/`ai` alias gap). Summarization/curation helpers STAY in their consumer modules.

- [ ] **5.1** Move the 4 primitives from `transfer.py:257-343` into `core/transcript.py` under **concrete public
  names**: `normalize_transcript_role`, `resolve_entry_role`, `extract_entry_blocks`, `group_entries_into_turns` (drop
  the leading `_`; rewind imports them, so public is the enabling move). Assertion: `core/transcript.py` owns them; ONLY
  parsing primitives move (`_extract_turn_summary`, `_call_llm_for_curation_prompt`, `_validate_decision_citations`,
  etc. STAY in `transfer.py` per its docstring -- "extraction/summarization logic stays in each consumer module").
- [ ] **5.2** Repoint `session/transfer.py` to the new public names (keeps its curation helpers local).
- [ ] **5.3** Repoint `session/rewind.py:13-21` -- the 2 primitives it uses (`extract_entry_blocks`,
  `group_entries_into_turns`) now import from `core/transcript.py`; `_extract_turn_summary` + the curation privates
  still import from `transfer`.
- [ ] **5.4** **Replace** `cli/status_line.py:410-421`'s divergent `_resolve_entry_role` with a call to the shared
  `resolve_entry_role`. This IS the fix: `human->user` / `ai->assistant` now normalize (old copy returned raw role or
  `None`). Preserve status_line's lazy-I/O `RenderContext` discipline (impl_notes) -- import the primitive, don't pull
  heavy `transfer` machinery.
- [ ] **5.5** **Regression test (GATE -- cannot tick Slice 5 without it):** feed a transcript entry with
  `type: "human"`/`"ai"` AND one with `message.role: "human"`/`"ai"` through status_line's resolution and assert it now
  resolves to `user`/`assistant`. Place in `tests/regression/test_bug_statusline_transcript_role_alias.py` (bug ID +
  root cause + affected files in the docstring, per testing_guidelines).

**Exit signal:** one transcript parser; status_line + rewind converge onto it; alias regression test green.

## Slice 6 -- git-root twins + direct_model relocate (refactor) -- NARROWED; D3 RESOLVED

- [ ] **6.1** Extract ONE git-root walker into a neutral `core/paths` leaf shared by `cli/extensions.py:47` and
  `core/ops/context.py:65`. Resolve the one real difference deliberately (`extensions` calls `.resolve()`, `ops/context`
  does not) -- pick the correct contract and note why. Assertion: one definition; both delegate; behavior pinned by a
  test over a symlinked/nested start path.
- [ ] **6.2 PRESERVE** `cli/codex.py:_project_root` (`.git` OR `.codex`, never `None`) and
  `session/claude/paths.py:find_project_root` (raises `FileNotFoundError`, worktree-aware) -- **do NOT** fold them in;
  their contracts differ. Assertion: both bodies byte-unchanged in the diff.
- [ ] **6.3 (D3 RESOLVED -- its own sub-slice / commit)** Move `session/direct_model.py` ->
  `forge/core/models/direct_model.py`. Verified import-safe: it imports only `forge.core.models.catalog` (+ stdlib), so
  no cycle. Repoint all importers atomically (coding_standards §5): `review/engine.py:39`,
  `core/ops/claude_session.py:40`, `cli/claude.py:28`, `cli/session_lifecycle.py:74`, `cli/session_fork.py:67`,
  `session/model_pin.py:6`, and tests (`tests/src/session/test_direct_model.py:7`,
  `tests/regression/test_bug_passthrough_model_pin.py:23`, `tests/integration/docker/conftest.py:17`). **Keep
  `session/model_pin.py` in `session/`** (session/proxy-launch specific). Assertion: `forge.session.direct_model` has
  zero importers; `forge.core.models.direct_model` resolves everywhere.

**Exit signal:** the two true walkers share one leaf; the two divergent ones untouched; `direct_model` lives in
`core.models`.

---

## Acceptance test table

| Test                              | Fixture                                                       | Assertion                                                                                                                                                                      | Test File                                                                           |
| --------------------------------- | ------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------- |
| S1 mirror + no-skip               | 6 statusline + 4 claude tests moved                           | tests run under `tests/src/{cli/statusline,session/claude}/`; collected count unchanged                                                                                        | moved files                                                                         |
| S2 opt-in runtime-state fixture   | baseline-cluster proxy tests                                  | the named `_ensure_runtime_state`(+`cost_tracker=None`) baseline tests consume the fixture; **cost-behavior tests keep explicit `cost_tracker`; credential patches untouched** | `tests/src/proxy/conftest.py`, `test_passthrough.py`, `test_responses_transport.py` |
| S3 shared codex factory           | supervisor/shadow/memory codex tests                          | one importable factory; each keeps only its distinct label/stdout; consumer assertions unchanged                                                                               | 3 codex test files + `tests/fixtures/codex_result.py`                               |
| S4a tip via output helper         | routing failure (no route / no running proxy)                 | recovery Tip rendered by `print_error_with_tip`; no `Tip:` string built in `review/`                                                                                           | `tests/src/review/…`, `tests/src/cli/test_workflow*.py`                             |
| S4b shim deleted                  | import `forge.sidecar.secrets`                                | import fails; callers use `core.auth.template_secrets`; propagation integration test green                                                                                     | `tests/src/sidecar/`, `tests/integration/sidecar/test_auth_secrets_propagation.py`  |
| **S5 alias normalization (GATE)** | transcript entry with `human`/`ai` in `type` + `message.role` | status_line resolves to `user`/`assistant` (was raw/None)                                                                                                                      | **new** `tests/regression/test_bug_statusline_transcript_role_alias.py`             |
| S6 twins converge, divergent kept | git-root callers + direct_model importers                     | `extensions`+`ops/context` delegate to one leaf; `codex._project_root` + `claude/paths.find_project_root` bytes unchanged; `direct_model` importers repoint to `core.models`   | `tests/src/cli/`, `tests/src/core/ops/`, `tests/src/session/test_direct_model.py`   |

---

## Open decisions -- RESOLVED (2026-07-06)

- **D1 (Slice 2 credential stub) -- RESOLVED (a):** leave the credential patches. They are behavior-divergent (proxy
  alone has many with different values), and the cross-package keyless cases test billing posture. Slice 2 = the opt-in
  proxy runtime-state fixture only.
- **D2 (Slice 3 factory home) -- RESOLVED:** importable helper (not a root fixture -- a pure object factory used
  repeatedly inside three modules; a fixture would thread params through many tests). Home:
  `tests/fixtures/codex_result.py` (`tests/fixtures` is the established test package; `tests/support` does not exist),
  lazy `HeadlessResult` import.
- **D3 (Slice 6 direct_model) -- RESOLVED:** move to `forge.core.models.direct_model` as its own sub-slice (6.3).
  Verified import-safe (catalog-only). Keep `session/model_pin.py` in `session/`.

**Slice ordering / PR granularity:** one branch; split into per-slice PRs if review prefers. Suggested order: **1 -> 4b
-> 3 -> 2 -> 5 -> 4a -> 6** (all decisions resolved, so no slice is decision-gated; clean mechanical first, the
defect-fix deliberately, direct_model last as its own commit).

## Design-doc / memory sync

- [ ] Slice 5: **no design doc currently names `core/transcript.py`** (only the module docstring does -- verified, no
  `rg` match in design.md/appendix/workflows/impl_notes). If Slice 5 ships, ADD a mention of `core/transcript.py` as the
  shared transcript-parsing seam to `design.md` §6 (directory structure) -- do not "cross-check" a note that isn't
  there.
- [ ] Slice 6: if a `core/paths` leaf is added, note it in `design.md` §6; note the `direct_model` relocation to
  `core.models` in §6 too.
- [ ] **impl_notes candidate (human-review gate):** the four transcript primitives are single-sourced (public) in
  `core/transcript.py`; `status_line`/`rewind` converge; `human`/`ai` alias normalization is now shared (defect closed).

## Closeout (pending)

- [ ] All slice exit signals met; **S5 regression test green (gate)**.
- [ ] `make pre-commit` clean; touched-file `ruff`.
- [ ] `change_log.md` entry per shipped slice (or one batch entry at the end).
- [ ] Move card `doing/ -> done/`.
