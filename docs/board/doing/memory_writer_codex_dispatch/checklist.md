# T6c execution checklist: memory-writer codex dispatch

**Lane**: `doing/` (member of `doing/epic_consumer_lanes/`). Branch `memory_writer_codex_dispatch`. Card: `card.md`.

## Current focus

**Phase 1 done (2026-06-30): the seam + the review-only codex arm shipped and unit-tested (10 new tests green; mypy +
pre-commit clean). augment (workspace-write) + the real-codex E2E are gated on Phase 0 (live login). D1 = Option A, both
modes.** A code-grounded sweep verified the T6b deferral: `augment` (the default mode, `models.py:106`) has the agent
write files via Write/Edit tools plus a Claude-specific permission scan (`memory_writer.py:115,281,593`), so augment
needs `sandbox="workspace-write"` (the epic's first write-granting lane) + a codex-native verification. `review-only` is
a clean `_dispatch_codex_shadow_curation` mirror. **Scope (D1=A): both modes** -- augment (`workspace-write`) +
review-only (`read-only`); the Phase 0 probe and Phase 2 augment arm are in scope.

## Decisions owed (resolve in review -- see card "Open decisions")

- [x] **D1 -- Workspace-write trust. RESOLVED: Option A** (user, 2026-06-30) -- both modes; augment accepts Codex
  `workspace-write`. Phase 0 probe + Phase 2 augment arm in scope. (D2-D5 remain recommended defaults, confirm in
  implementation.)
- [ ] **D2 -- Codex lane tuple.** `Lane(codex, chatgpt, gpt-5-codex)`, model nominal (recommended, T6b parity).
- [ ] **D3 -- Degrade.** best-effort async -> `return False` + telemetry (recommended, matches the existing path).
- [ ] **D4 -- augment verification.** Drop the Claude permission-scan for the codex arm; fold `runtime_is_error` (verify
  in Phase 0 that a codex workspace-write denial surfaces as a runtime error).
- [ ] **D5 -- transcript read.** Confirm codex reads `.forge/artifacts/.../transcript.jsonl` under `cwd=forge_root` in
  the chosen sandbox.

## Phase 0 -- Codex workspace-write behavior probe (GATE, blocks augment)

Only needed if D1 = A. Resolve with evidence, not a guess.

- [ ] Confirm `codex exec --sandbox workspace-write` actually edits files under `cwd` and reports a write denial as a
  runtime error (not exit-0-silent). Probe against the host ChatGPT login (mirror
  `test_shadow_curation_codex_smoke.py`).
- [ ] Confirm codex reads the absolute transcript path under the sandbox (D5).
- [ ] Record the fixture / observed behavior; decide GO (both modes) or fall back to review-only (Option B).

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

## Phase 2 -- `_dispatch_codex_memory_writer` (sandbox per mode; augment gated on D1)

**Status (2026-06-30): review-only arm shipped + unit-tested** (read-only sandbox, persist stdout, freeze-past-skip,
single-emitter via the invoker, manual outcome only on no-spawn per Finding 1). **augment (workspace-write) degrades
pending the Phase 0 probe**; the T6b "failure-biased" E2E check is also Phase-0-gated (live login).

- [ ] Implement mirroring `_dispatch_codex_shadow_curation`: `read_fresh_codex_preflight` ->
  `prepare_codex_request(sandbox=<per D1/mode>, model=None, cwd=forge_root, attribution=Attribution(command="memory-writer", session=..., operation="memory_writer.run"))`
  -> `CodexHeadlessInvoker().run` -> fold `runtime_is_error`.
- [ ] Sandbox per mode: `review-only` -> `read-only`; `augment` -> `workspace-write` (D1=A). If D1=B, augment stays
  claude-only (the branch guards on mode).
- [ ] Verification: do NOT run the Claude `_stdout_indicates_permission_denied` scan on the codex arm (D4); a
  workspace-write failure surfaces via `runtime_is_error` -> degrade `return False`.
- [ ] Persist the report from `result.stdout` via `_persist_review_report` as today (both modes).
- [ ] Single emitter: the codex arm returns before the claude `emit_usage_for_session_result` block -> invoker
  auto-emits only. Assert `Attribution.operation="memory_writer.run"`, `command="memory-writer"`.
- [ ] Freeze parity: `on_dispatch` fires only past the preflight skip-return (mirror T6b). Cold preflight -> no spawn,
  no freeze; failed turn -> freeze.
- [ ] Degrade + outcome recording (Finding 1 -- avoid a double upstream row): the invoker's `_emit_codex` **already**
  writes the upstream outcome row for success AND error when `Attribution.operation` is set (`codex.py:248-259`;
  `record_upstream_operation` writes any status; `_status` maps a clean run to `"success"`). So call
  `_record_memory_writer_outcome(error)` **only** on **no-spawn** setup/preflight failures (cold cache,
  request-shaping), where the invoker never runs; **spawned** runs (success or codex failure) rely on the invoker row --
  do NOT record manually. All paths `return False` / never raise (best-effort async).
- [ ] **Verify the T6b "failure-biased" claim (contradicted by code):** the T6b card says a codex success "emits no
  outcome row", but `_emit_codex` records a `"success"` row when `operation` is set. Assert the success upstream row in
  the E2E; only if it is genuinely absent does the codex success path need a manual success record for claude parity.

## Phase 3 -- Observability + docs

- [ ] Confirm the `runtime=codex`/`billing_mode=subscription_quota` usage event rides `emit_codex_usage` (shared with
  T4/T6b); `forge session lane show` surfaces the bound codex lane (T5/T6a machinery). No new observability code
  expected.
- [ ] Design-doc sync: `design_appendix.md` §G -- add a **Memory-writer codex arm (T6c)** paragraph (best-effort-async
  degrade; per-mode sandbox; the first workspace-write lane if D1=A; Claude permission-scan not ported).
  `cli_reference.md` -- `--runtime codex` now dispatches a real arm for `supervisor`/`shadow_curation`/`memory_writer`.
  `design.md` -- note the first write-granting lane if D1=A (scope-guard relaxation). end-user `memory.md` -- if D1=A,
  note the memory writer can run on a codex subscription.
- [ ] Epic roster: `epic_consumer_lanes/checklist.md` + `card.md` -> T6c done (closeout step).

## Acceptance tests

Card's Acceptance table, threaded through `run_memory_writer` + `_dispatch_codex_memory_writer`. Fill in the
`test_memory_writer.py` names as they land (mirror the T6b `test_shadow_curation.py` set).

## Verification gate

- [ ] Focused suites green: `test_memory_writer.py`, `test_session_lane.py`, `test_consumer_lane_freeze.py`,
  `test_lanes.py`.
- [ ] `make pre-commit` clean on changed files (ruff/black/isort/mypy/pyright/mdformat).
- [ ] Integration: a real `codex exec` E2E (mirror `test_shadow_curation_codex_smoke.py`) -- assert one
  `runtime=codex`/`subscription_quota` event; if D1=A, assert codex actually wrote a file.

## Closeout

- [ ] Tick acceptance rows with verification recorded.
- [ ] `change_log.md` entry (Goal / Key changes / Verification).
- [ ] Move `doing/memory_writer_codex_dispatch/` -> `done/`; update epic roster; promote durable lessons to
  `impl_notes.md` after human review.
- [ ] **Epic closeout check**: with T6c done, only team-supervisor (plan-context) remains deferred -- decide whether the
  epic closes to `done/` or stays coordinating that one follow-on.
