# T6c execution checklist: memory-writer codex dispatch

**Lane**: `doing/` (member of `done/epic_consumer_lanes/`). Branch `memory_writer_codex_dispatch`. Card: `card.md`.

## Current focus

**Phases 0-3 + the real-codex E2E all done (2026-06-30).** Seam + review-only arm (Phase 1), the augment arm on
`workspace-write` (Phase 2), and the design-doc sync (Phase 3) shipped and unit-tested; the Phase 0 live probe returned
**GO**; a real-codex augment E2E proves codex edits the doc in place. Branch `memory_writer_codex_dispatch`: 6 commits
(seam, augment, shared conftest, E2E, docs sync, review follow-ups: CLI-bridge tests + doc/board fixes). **Remaining:
push + PR, then post-merge closeout** (change_log, epic roster T6c->done, lane move to `done/`).

**Phase 0 GO -- key finding (refines D4).** The probe (host ChatGPT login, `codex exec --json --sandbox workspace-write`
reduced through Forge's own `parse_codex_jsonl_stream`) showed: (1) codex writes files under `cwd` and reads the
transcript under the sandbox (D5 confirmed); (2) an out-of-project write is auto-rejected
(`patch rejected: writing outside of the project`) but the run **exits 0 with `is_error=False`** -- a denial rides
`turn.completed`, it does NOT set `runtime_is_error`. So D4's premise ("a workspace-write denial surfaces as a runtime
error") is **false but immaterial**: the docs live under `cwd=forge_root`, so in-project updates auto-approve; real
provider/turn failures still fold via `runtime_is_error`; no Claude-style permission scan is ported. D1 = Option A
stands (both modes).

## Decisions owed (resolve in review -- see card "Open decisions")

- [x] **D1 -- Workspace-write trust. RESOLVED: Option A** (user, 2026-06-30) -- both modes; augment accepts Codex
  `workspace-write`. Phase 0 probe + Phase 2 augment arm in scope. (D2-D5 remain recommended defaults, confirm in
  implementation.)
- [x] **D2 -- Codex lane tuple.** RESOLVED: `Lane(codex, chatgpt, gpt-5-codex)` shipped in `MEMORY_WRITER_CONSUMER`
  (`memory_writer.py:60`); model nominal (codex picks its own). T6b parity.
- [x] **D3 -- Degrade.** RESOLVED: best-effort async -> `return False` + telemetry throughout the arm (no raise, no
  fail-open); matches the existing claude path.
- [x] **D4 -- augment verification.** RESOLVED (refined by Phase 0): drop the Claude permission-scan; fold
  `runtime_is_error` for real provider/turn failures. Phase 0 falsified the "a denial surfaces as a runtime error"
  premise, but it is immaterial -- in-project doc writes auto-approve, so the rejection path is never hit.
- [x] **D5 -- transcript read.** RESOLVED: Phase 0 confirmed codex reads the transcript under `cwd=forge_root` in the
  sandbox (`jq` over `transcript.jsonl` under `workspace-write`); the augment E2E reads the artifact transcript live.

## Phase 0 -- Codex workspace-write behavior probe (GATE) -- DONE: GO

Resolved with evidence (host ChatGPT login), not a guess. Ran raw `codex exec --json --sandbox <mode>` reduced through
Forge's own `parse_codex_jsonl_stream` -- the exact `runtime_is_error` the arm sees.

- [x] `codex exec --sandbox workspace-write` **edits files under `cwd`** (wrote `summary.txt`, exit 0,
  `is_error=False`). A write denial is **NOT** a runtime error: an out-of-project write is auto-rejected
  (`patch rejected: writing outside of the project`) yet exits 0 with `is_error=False` (rides `turn.completed`).
  Immaterial -- in-project writes auto-approve (see D4).
- [x] codex **reads the transcript under the sandbox** (`jq` over `transcript.jsonl` under `workspace-write`; D5).
- [x] Decision: **GO (both modes)**. augment ships on `workspace-write`; fold-`runtime_is_error` (no permission scan) is
  the correct verification because in-project doc writes never hit the rejection path.

## Phase 1 -- Shared seam: allowed_lane + lane validation + runtime branch

- [x] Add codex `allowed_lane` to `MEMORY_WRITER_CONSUMER` (`memory_writer.py:58`):
  `Lane(runtime_id="codex", backend_id="chatgpt", model="gpt-5-codex")`. Assert `valid_lanes` includes codex, claude-max
  preserved; `lane set --consumer memory_writer --runtime codex` resolves (was `LaneError`).
- [x] Thread the bound `LaneRecord` into `run_memory_writer`; validate via
  `LaneRecord -> Lane -> resolve_lane(MEMORY_WRITER_CONSUMER)` guard (mirror `shadow_curation.py:327-347`, keyword
  args). Invalid/drifted binding -> memory-writer degrade (`return False` + outcome), not silent claude.
- [x] **Resolve the runtime early + gate the Claude-availability check on it (Finding 2 -- the codex branch must not
  require Claude).** `is_claude_available()` returns `claude_unavailable` at `memory_writer.py:429`, **before** the
  dispatch at `:530`, so a codex-bound writer is wrongly blocked when Claude is absent (shadow-curation has no such
  gate). Resolve the lane/runtime right after transcript+mode validation; run the `is_claude_available()` guard only
  when `runtime_id == "claude_code"`. **Test:** a codex-bound writer runs when `is_claude_available()` is False; a
  claude/default binding still fails cleanly with `claude_unavailable`.
- [x] Insert the runtime-keyed branch before the claude `on_dispatch` (`:530`): `codex` -> early return into
  `_dispatch_codex_memory_writer`; claude path byte-identical.

## Phase 2 -- `_dispatch_codex_memory_writer` (sandbox per mode) -- DONE

**Status (2026-06-30): both arms shipped + unit-tested + E2E-verified.** review-only (`read-only`) and augment
(`workspace-write`) share the preflight gate, freeze-past-skip, single-emitter, and best-effort degrade.

- [x] Implemented mirroring `_dispatch_codex_shadow_curation`: `read_fresh_codex_preflight` ->
  `prepare_codex_request(sandbox=<per mode>, model=None, cwd=forge_root, attribution=Attribution(command="memory-writer", session=..., operation="memory_writer.run"))`
  -> `CodexHeadlessInvoker().run` -> fold `runtime_is_error`.
- [x] Sandbox per mode: `review-only` -> `read-only`; `augment` -> `workspace-write` (D1=A). `sandbox: CodexSandbox`
  ternary on `mode`.
- [x] Verification: no Claude `_stdout_indicates_permission_denied` scan on the codex arm (D4). Real provider/turn
  failures fold via `runtime_is_error`; in-project write denials do not occur (Phase 0).
- [x] Persist the report from `result.stdout` via `_persist_review_report` (both modes). E2E asserts a `review-*.md`
  file lands even in augment mode.
- [x] Single emitter: the codex arm returns before the claude `emit_usage_for_session_result` block -> invoker
  auto-emits only. Unit test asserts `Attribution.operation="memory_writer.run"` / `command="memory-writer"`; E2E
  asserts exactly one `runtime=codex`/`subscription_quota`/`codex_exec` event.
- [x] Freeze parity: `on_dispatch` fires only past the preflight skip-return. Cold preflight -> no spawn/freeze; failed
  turn -> freeze (unit tests + E2E `freeze_calls == [1]`).
- [x] Degrade + outcome recording (Finding 1): manual `_record_memory_writer_outcome(error)` ONLY on no-spawn
  setup/preflight failures; spawned runs (success or codex failure) rely on the invoker row -- no double-count. Unit
  tests assert an empty ledger on spawned success AND spawned failure.
- [x] **T6b "failure-biased" claim -- RESOLVED (claim holds; NOT contradicted).** `record_upstream_operation` gates on
  `should_record_upstream_outcome()`, which is failure-biased: a success persists a row only under
  `upstream_event_volume="all"`. So BOTH arms (claude's manual `success` record and codex's invoker row) write nothing
  on success under default volume -- parity, no manual success record needed. The augment E2E confirms
  `read_upstream_outcomes(...) == []` on a real codex success.

## Phase 3 -- Observability + docs -- DONE

- [x] Confirmed the `runtime=codex`/`billing_mode=subscription_quota`/`route=codex_exec` usage event rides
  `emit_codex_usage` (shared with T4/T6b) -- asserted in the augment E2E. No new observability code.
  `forge session lane show` surfaces the bound codex lane via existing T5/T6a machinery.
- [x] Design-doc sync: `design_appendix.md` §G -- **Memory-writer codex arm (T6c)** paragraph added (best-effort-async
  degrade; per-mode sandbox; first workspace-write lane; permission-scan not ported; deferral note updated).
  `cli_reference.md` -- `--runtime codex` note now lists `memory_writer` (T6c); only `team_supervisor` lacks a codex
  lane. `design.md` -- freeze-trigger line notes the memory-writer codex lane (read-only or workspace-write). end-user
  `memory.md` -- "Runtime: claude or codex" section added.
- [x] Epic roster: `epic_consumer_lanes/checklist.md` + `card.md` -> T6c done (2026-07-01 closeout commit).

## Acceptance tests

Threaded through `run_memory_writer` + `_dispatch_codex_memory_writer` (unit) and the real-codex E2E. All green. Unit
tests in `test_memory_writer.py`; E2E in `test_memory_writer_codex_smoke.py`.

| Assertion                                                               | Test                                                        |
| ----------------------------------------------------------------------- | ----------------------------------------------------------- |
| codex lane is valid (added, not replacing claude-max)                   | `test_memory_writer_consumer_allows_codex_lane`             |
| review-only -> `read-only`, persist, claude emitter untouched           | `test_review_only_dispatches_read_only_and_persists`        |
| augment -> `workspace-write`, freeze, no manual row                     | `test_augment_dispatches_workspace_write`                   |
| Attribution pins operation/command; claude emitter skipped              | `test_pins_operation_and_skips_claude_emitter`              |
| cold preflight -> no spawn, no freeze, manual outcome                   | `test_cold_preflight_degrades_no_spawn_no_freeze`           |
| spawned failure -> freeze + no double row (Finding 1)                   | `test_failed_turn_degrades_but_still_freezes_no_manual_row` |
| exit-0 + `runtime_is_error` -> degrade                                  | `test_exit_zero_runtime_error_degrades`                     |
| invalid explicit lane -> no-call degrade                                | `test_invalid_explicit_lane_degrades_no_dispatch`           |
| codex arm works with `is_claude_available()` False (Finding 2)          | every codex test, via `_run_codex`                          |
| real codex writes the doc (`workspace-write`); 1 event; no upstream row | `test_memory_writer_codex_augment_real_write`               |

## Verification gate

- [x] Focused suites green: `test_memory_writer.py` (111) + `test_shadow_curation.py` / `test_session_lane.py` /
  `test_consumer_lane_freeze.py` / `test_lanes.py` (189 total, no regression).
- [x] pre-commit clean on changed files (ruff/black/isort/mypy/pyright).
- [x] Integration: real `codex exec` E2E green -- `test_memory_writer_codex_augment_real_write` asserts one
  `runtime=codex`/`subscription_quota` event AND that codex actually edited the doc (D1=A); the refactored
  shadow-curation smoke still passes (2 passed, 64s).

## Closeout

- [x] Acceptance rows recorded (table above) + verification gate green.
- [x] `change_log.md` entry added (2026-07-01: goal / key changes / verification).
- [x] Move `doing/memory_writer_codex_dispatch/` -> `done/`; epic roster updated (card + checklist); durable lesson
  promoted to `impl_notes.md` (codex `runtime_is_error` does not catch a sandbox write-denial). The failure-biased
  upstream-ledger lesson was already recorded under the T6b note, so not re-added (no duplicate).
- [x] **Epic closeout check**: T6c done leaves only team-supervisor (plan-context, pending a context-model change).
  Decision: the epic **stays in `doing/`** coordinating that one follow-on (matches its stated posture; team-supervisor
  is not yet an actionable member card).
