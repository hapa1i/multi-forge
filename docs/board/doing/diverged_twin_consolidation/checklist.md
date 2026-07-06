# diverged_twin_consolidation checklist

## Current focus

Collapse must-stay-identical twin copies in the session family + `cli/hooks/`, fixing the two shipped defects (Slice 1
transcript type-guard gap; Slice 2 `%policy check` nested-layout misorder) along the way. **Awaiting review on this
checklist before any implementation.** Each phase is independently landable as its own commit.

Structure: one phased `doing/` card (not member cards), per the `state_primitive_hoist` precedent. Behavior-preserving
on Slices 3, 4a, and 5; Slice 4b is characterize-then-no-op or a scoped defect-fix; deliberate defect-fixes (with
regression tests) on Slices 1-2.

---

## Verification pass (2026-07-05, pre-implementation) — deltas from `card.md`

Re-verified every finding against the current tree (post PR #80). Line numbers below are **current**, not the card's.
Corrections the card asked for ("re-verify the counts before the relevant slice"):

- **Slice 3a accessor is named `session_runtime(state)`**, not `resolve_session_runtime` — it already exists at
  `core/ops/codex_session.py:111` with the exact `... else "claude_code"` body. The card's proposed name is wrong; the
  work is "repoint 4 inline copies to the existing accessor," plus a **placement decision** (below).
- **Slice 3b is 4 sites (card correct).** A single-line grep missed `memory_writer.py:420`, which is a **multiline**
  `Lane(runtime_id=lane_record.runtime_id, ...)` conversion (the separate `.runtime_id` read at `:429` is not one). Real
  inlined conversions: `supervisor.py:734`, `supervisor.py:810`, `shadow_curation.py:333`, `memory_writer.py:420`. The
  existing helper `_record_to_lane` is at `consumer_lanes.py:233`. Use a multiline-safe grep (`rg -U`) for the exit
  assertion.
- **Slice 3c accessor is already shared.** All three arms already call `read_fresh_codex_preflight()`
  (`codex_preflight_cache.py:125`). The duplication is the **readiness-gate logic wrapping the call**, and those arms
  are documented-divergent (impl_notes T6b/T6c). Reframed as surgical extraction of only the identical gate portion —
  highest risk in the batch.
- **Slice 4b (context-limit ref) is already partly consolidated** — `_resume_context_ref(...)` +
  `_resolve_context_limit(...)` exist and are used at `session_lifecycle.py:1603/1693/1734`. The remaining
  `_resolve_context_limit(effective_proxy_ref)` sites (`session_lifecycle.py:1857`, `session_resume_modes.py:49/155`)
  may be a *legitimately different* ref construction, not drift. Weakest-evidence item — verify-or-defer (below).
- **Test-coupling note in the card is stale:** `test_session_commands.py` (4933 lines) was split by PR #77. Repoint
  targets are now the split files (`test_session_fork.py`, `test_session_resume.py`, `test_session_start_delete.py`,
  `test_session_list_show.py`, `test_session_overrides.py`) plus `tests/src/cli/session_command_support.py`.

Confirmed exactly as the card states (High): Slice 1 (allowlist 3x at `manager.py:896/1309/1548` +
`_inherited_launch_intent:70`; guard gap `:758` vs guarded `:804` + helper `_latest_transcript_artifact_path:238`),
Slice 2 (identical 3-bucket logic; differ only in path-extraction + `startswith` vs `is_under_directory`; codex
regression exists, CLI copy never got it), Slice 4a (**8**-flag block, excluding `--supervise`, + validation strings
duplicated `session_fork.py:216-269` vs `session_lifecycle.py:932-985`; `--supervise` itself diverges — start
`type=str`, fork `is_flag`).

---

## Scope decisions (resolved 2026-07-05, verified against code)

1. **`session_runtime` home → `src/forge/session/models.py`** (Decision 1). It is a plain `SessionState` accessor
   (`class SessionState` is at `models.py:621`), so it belongs beside the type. **Not** `core/ops/session_context.py`:
   that is command-core introspection, and launch/core code (`claude_session.py`) importing it would be a sideways
   dependency. Move the existing `session_runtime(state)` there (keep it a free function; minimal churn) and repoint all
   5 sites.
2. **Shared TDD-sort key → `policy/deterministic/base.py`** (Decision 2), next to `is_under_directory`. The sort exists
   only to mirror TDD path relevance, so that module owns it; `cli/hooks/` imports down into policy.
3. **Slice 3c: DEFERRED** (Decision 3, verified). The accessor `read_fresh_codex_preflight()` is already shared; the
   only other identical code is the 2-line `reason = (preflight.blocking_reason if preflight else None) or "..."`
   expression, after which failure behavior **immediately diverges** — supervisor `raise _SupervisorRoutingError`,
   shadow-curation `return CurationResult(success=False)`, memory-writer
   `logger.warning + _record_..._outcome + return False` (the documented T6b/T6c divergence). Extracting a 1-line reason
   across three intentionally-divergent arms is negative-value. **Dropped from active scope.**
4. **Slice 4b: CHARACTERIZE-then-decide, do not consolidate** (Decision 4, verified). Real divergence found: the
   `routing`-truthy branch of `_resume_context_ref` returns `routing.proxy_id or routing.template`, while the three
   inline `effective_proxy_ref` sites use `routing.proxy_id` only (the `direct`/`else` branches are identical).
   `_resolve_context_limit(proxy_ref)` accepts either, and `ResolvedRouting` has `proxy_id`/`template` **independently
   nullable** (`session_routing.py:12,14`) — so a template-only routing computes a *different* context limit on the two
   paths. Open question (Phase 4b task): is a template-only routing **reachable** on the inline-site paths? If yes →
   drift → align the inline sites to `proxy_id or template` (small behavior-fix + regression test, **not** a pure
   consolidation); if unreachable → document as intentional/moot and drop 4b.
5. **Single phased card confirmed** (Decision 5). Card "When accepted" note marked superseded; `**Lane**:` text updated
   `proposed/ → doing/`.

---

## Phase 1 (defect-fix): intent inheritance + transcript-artifact guard

- [ ] Diff the **full** blocks at `manager.py:896`, `:1309`, `:1548` (not just the allowlist tuple) to confirm the
  surrounding logic is identical. Note the Codex caveat at `:1124` (`_inherited_launch_intent` must not copy
  `runtime=codex`) — confirm it lives outside the extracted block so consolidation preserves it.
  - Assertion: the three sites reduce to one `_inherit_intent_fields(child, parent)` with no per-site conditional lost.
- [ ] Extract `_inherit_intent_fields(child, parent)` (single allowlist + `_inherited_launch_intent` call); repoint the
  3 sites (resume-child, fork, into-fork).
  - Assertion: `rg '"consumer_lanes"' src/forge/session/manager.py` shows **one** allowlist definition.
- [ ] Fix the guard gap: replace the inline `:753-758` block with
  `transcript_artifact_path = _latest_transcript_artifact_path(parent_state)` (`parent_state` is in scope at `:753`; the
  block is the helper's logic minus the `isinstance` guard).
  - Assertion: a non-`str` `copied_path` in a malformed manifest yields `None`, never a non-str in the `str | None`
    field.
- [ ] Regression test (defect-fix gate): malformed manifest with non-str `copied_path` on the native-resume path.
  - Assertion: no crash / no non-str leak; test fails on the pre-fix code.

## Phase 2 (defect-fix): TDD tests-first sort

- [ ] Extract `tests_first_sort_key(path: str) -> int` (0=tests, 2=src, 1=other) keyed on `is_under_directory`, in the
  home decided in review (Scope #2).
- [ ] Repoint `direct_commands.py:_sort_tests_first` (currently `startswith`) and
  `codex_policy.py:sort_contexts_tests_first` to call it; each keeps its own element→path extraction (`item[0]` vs
  `ctx.target_path or ""`).
  - Assertion: `rg 'startswith\("tests' src/forge/cli/hooks/` returns nothing; both callers use the shared key.
- [ ] Confirm the `is_under_directory` migration doesn't silently drop the `tests\\`/`src\\` backslash handling the CLI
  copy has today (POSIX-focused repo, likely moot — assert the intended behavior explicitly).
- [ ] Regression test (defect-fix gate): `%policy check` orders a nested `pkg/tests` + `pkg/src` diff tests-first
  (mirror `test_bug_codex_tdd_nested_layout.py` for the CLI diagnostic path).
  - Assertion: nested layout no longer false-denies an impl-first atomic patch; fails on pre-fix `startswith` code.

## Phase 3: runtime default + lane conversion + preflight gate (behavior-preserving)

- [ ] **3a** Move the existing `session_runtime(state)` accessor from `core/ops/codex_session.py` to `session/models.py`
  (beside `SessionState`); repoint the 4 inline `... else "claude_code"` copies (`session_manage.py:881/1209`,
  `session_lifecycle.py:1391`, `claude_session.py:384`) plus the original `codex_session.py` call to it.
  - Assertion: `rg 'else "claude_code"' src/forge` returns only the accessor definition; `codex_session.py` imports it
    from `session.models`.
- [ ] **3b** Rename `consumer_lanes._record_to_lane` to the public `record_to_lane`; update its existing internal
  callers (`consumer_lanes.py:75/220`) and repoint the **4** inlined conversions (`supervisor.py:734/810`,
  `shadow_curation.py:333`, `memory_writer.py:420` — the last is multiline). No private shim unless compatibility
  evidence appears during implementation.
  - Assertion: `rg '_record_to_lane' src/forge` returns nothing, and `rg -U 'Lane\(\s*runtime_id=lane_record' src/forge`
    returns nothing (multiline-safe; catches all 4 forms).
- [ ] **3c — DEFERRED** (Decision 3). Accessor already shared; the only identical remainder is a 1-line reason
  expression, after which the three arms' failure behavior diverges by design (T6b/T6c). Not extracting. No task.

## Phase 4: supervisor flag family + context-limit ref

- [ ] **4a** Extract a shared Click option-group decorator for the **8**-flag supervisor family (mirror the codex
  `*_options` composite exemplar); share the option **definition + validation strings**, not the Rich presenters.
  `--supervise` stays **per-command** (start `type=str` `:925-931`, fork `is_flag` `:209-215`) — it is not in the shared
  group. Repoint `start` (`session_lifecycle.py:932-985` + validation `:1072-1080`) and `fork`
  (`session_fork.py:216-269` + validation `:340-352`).
  - Assertion: the shared 8-option fragment (`--supervisor-proxy`, `--no-supervisor-proxy`, `--cascade`,
    `--checker-model/-provider/-effort`, `--supervisor-effort`, `--supervisor-runtime`) and the mutually-exclusive /
    require-`--supervise` messages live once and render byte-identically across both commands; whole-help output is
    **not** identical (the `--supervise` line differs by design).
- [ ] **4b — CHARACTERIZE, do not consolidate** (Decision 4). Divergence already confirmed: `_resume_context_ref`
  returns `routing.proxy_id or routing.template`; the 3 inline sites (`session_resume_modes.py:42/148`,
  `session_lifecycle.py:1850`) use `routing.proxy_id` only. Task: determine whether a template-only `ResolvedRouting`
  (`proxy_id=None, template=set`) is **reachable** on the inline-site paths.
  - Assertion (drift): if reachable, align the 3 inline sites to `proxy_id or template` — a **behavior-fix with a
    regression test** (different context limit for template-only routing), not a pure move.
  - Assertion (intentional): if unreachable, record why (proxy_id always set when routing is truthy on these paths) and
    drop 4b — no code change.

## Phase 5: teammate/task hook bodies + Stop/StopFailure capture (behavior-preserving)

- [ ] Characterization test first, **by channel** (the hook families signal differently): Stop / StopFailure normally
  emit **hook JSON**, but Stop's verification-deny path exits 2 with stderr feedback; TeammateIdle / TaskCompleted
  signal via **exit code + stderr feedback** (no JSON) plus the lane-freeze side effect. Capture the right observable
  for each before touching either.
- [ ] Share the TeammateIdle (`commands.py:1722`) / TaskCompleted (`:1773`) body — it is **structurally** identical but
  **not** byte-identical (the log label and the `handle_*` function differ). Extract a shared body parameterized by
  `(log_label, handler_fn)`; the freeze wiring and exit/stderr contract stay identical.
  - Assertion: both commands delegate to one shared body; exit code + stderr + freeze behavior unchanged
    (characterization).
- [ ] Share the Stop / StopFailure transcript capture+reconcile core (`~:400` Stop vs `:601-729` StopFailure) — extract
  only the identical capture core, preserving StopFailure's last-chance semantics.
  - Assertion: one capture helper; Stop/StopFailure **hook JSON** byte-identical pre/post (characterization).

---

## Acceptance test table

| Test                                        | Fixture                                                          | Assertion                                                                                       | Test File                                                     |
| ------------------------------------------- | ---------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- | ------------------------------------------------------------- |
| Transcript guard (Slice 1)                  | manifest with non-str `copied_path`, native-resume path          | resolves to `None`, no non-str leak; fails pre-fix                                              | `tests/regression/test_bug_transcript_artifact_type_guard.py` |
| Nested TDD sort (Slice 2)                   | `%policy check` diff with `pkg/tests/*` + `pkg/src/*`            | tests bucket before src; impl-first atomic patch not false-denied; fails pre-fix                | `tests/regression/test_bug_policy_check_nested_tdd_sort.py`   |
| Inheritance single-source (Slice 1)         | fork/into/resume-child of a parent with all 6 inheritable fields | child inherits identically via one allowlist                                                    | existing `test_session_fork.py` / `test_session_resume.py`    |
| Supervisor flags parity (Slice 4a)          | `start`/`fork` help, shared 8-option fragment only               | the 8-option fragment + validation strings byte-identical; `--supervise` line differs by design | `test_session_start_delete.py` / `test_session_fork.py`       |
| Stop/StopFailure JSON + Stop deny (Slice 5) | Stop / StopFailure payloads, plus Stop verification-deny         | hook JSON byte-identical pre/post for JSON paths; Stop deny exit 2 + stderr unchanged           | characterization test in `tests/src/cli/hooks/`               |
| Team-hook parity (Slice 5)                  | TeammateIdle / TaskCompleted (exit 0 and exit-2 paths)           | exit code + stderr feedback + lane-freeze side effect unchanged pre/post                        | characterization test in `tests/src/cli/hooks/`               |

---

## Verification (per slice)

- [ ] Focused unit modules for the touched area pass (`tests/src/session/`, `tests/src/cli/test_session_*.py`,
  `tests/src/cli/hooks/`, `tests/src/policy/`).
- [ ] Slices 2 & 5 touch hooks → run the hook **integration** path (real `claude -p`/Docker), not just unit
  (testing_guidelines.md).
- [ ] `rg` of each collapsed pattern shows one definition (per-slice exit signals above).
- [ ] `make pre-commit` clean.
- [ ] Full unit suite before closeout.

## Closeout

- [ ] Change-log entry in `docs/board/change_log.md` (single board log — not a per-card file).
- [ ] Promote durable lessons to `impl_notes.md` after human review.
- [ ] Move `doing/diverged_twin_consolidation/` → `done/` after final merge to `main`.
