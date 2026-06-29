# T1b execution checklist: consumer_lane_binding

**Card**: [`card.md`](card.md). **Epic**: [`docs/board/doing/epic_consumer_lanes/`](../epic_consumer_lanes/card.md).
**Branch**: `consumer_lane_binding`.

## Current focus

Slices 1 (schema) + 2 (binding resolution + injected resolver + freeze + pulled-forward override reject) + 3
(clean-break removal of `supervisor_runtime`) + 4 (setters + stateful already-bound reject; status drift landed in Slice
3\) **complete**. Dispatch, freeze, status, and the setters all read/write the same `consumer_lanes` binding. **Only
Slice 5 (docs sync) remains** before closeout. Design is fully settled (D1-D3 in `card.md`). Tick a box only when its
assertion is verified and recorded -- not when work merely starts.

## Slices

### Slice 1 -- Manifest schema (`LaneRecord` + `consumer_lanes` sections) -- DONE

- [x] `LaneRecord` added to `session/models.py`: plain `runtime_id`/`backend_id`/`model` strings; `__post_init__`
  rejects empty **or non-string** values (enforces the `str` annotation, not just truthiness -- Slice 2 setters build it
  directly); **no** `core.lanes` / `backend.sources` / `runtime.registry` import (docstring mention only). Verified:
  `test_lanerecord_stores_unknown_ids_without_catalog_validation`, `test_lanerecord_rejects_empty_fields`,
  `test_lanerecord_rejects_non_string_fields`.
- [x] `ConsumerLaneBinding` (`lane: LaneRecord`, `source: str`, `resolved_at: str`) + `ConsumerLaneIntent`
  (`supervisor: LaneRecord | None`) + `ConsumerLaneConfirmed` (`supervisor: ConsumerLaneBinding | None`) added as
  **named-field dataclasses**, never `dict`-typed.
- [x] `SessionIntent.consumer_lanes` + `SessionConfirmed.consumer_lanes` wired; `SCHEMA_VERSION` unchanged (additive).
  Verified: `test_consumer_lanes_default_none`, `test_schema_version`, the strict round-trip tests.
- [x] Drift guard: `test_lanerecord_field_parity_with_lane` asserts `fields(LaneRecord)` names == `fields(Lane)` names.
- [x] Read path open: a manifest carrying a full `consumer_lanes.supervisor` round-trips under `dacite(strict=True)`
  (`test_consumer_lanes_intent_round_trips_strict`, `..._confirmed_...`). The override-**set** reject is Slice 4.

**Verification:** `tests/src/session` + `tests/src/core/test_lanes.py` -> 1022 passed (9 new cases green); mypy +
pyright clean on `models.py`.

### Slice 2 -- Binding resolution + freeze seam (injected resolver) -- DONE

New bridge module `session/consumer_lanes.py` (manifest DTOs \<-> `core.lanes`; lives in neither -- `session.models`
stays catalog-free, `core.lanes` stays pure): `read_bound_lane` (dispatch source) + `ensure_consumer_lane_binding`
(freeze), both keyed by `consumer.id` so T6 extends by adding a named field, not editing the bridge.

- [x] Lane injected into dispatch. `register_supervisor_and_restore` (holds the manifest) calls
  `read_bound_lane(manifest, SUPERVISOR_CONSUMER)` and passes it to `SemanticSupervisorPolicy(lane_record=...)`, which
  forwards `_evaluate -> invoke_supervisor -> run_supervisor_check`. `run_supervisor_check` converts the injected
  `LaneRecord -> Lane` **inside its existing fail-open guard** (replacing `_supervisor_lane_override(config)`,
  `supervisor.py:777`) and never reads the store. The engine (not the hook) calls `run_supervisor_check`, so the
  injection rides the policy constructor -- same effect as the card's "inject into `run_supervisor_check`".
  `read_bound_lane` is **confirmed-first, else intent** (a frozen binding governs dispatch directly -- strengthens the
  card's "read intent == confirmed by invariant"). Verified: `test_register_injects_bound_lane_from_intent`,
  `TestReadBoundLane.*`.
- [x] `ensure_consumer_lane_binding(m, SUPERVISOR_CONSUMER, supervisor_lane)` called **inside the existing locked
  post-eval `_mutate`** (`cli/hooks/policy.py`), gated on a configured supervisor (`resume_id`, not suspended) -- no
  second lock. Freezes the default lane (`source="default"`) or the override (`source="intent"`), write-if-absent; a
  drifted record skips the freeze. **`supervisor_lane` is threaded from `register_supervisor_and_restore` (the lane the
  hook injected at dispatch), not a fresh read of the under-lock manifest** -- so a concurrent intent change during the
  (multi-second) supervisor call can't skew the binding off the lane that ran (review P2a). Verified:
  `TestSupervisorLaneBindingFreeze.*` (default freeze; suspended/no-supervisor skip; write-if-absent; threaded-lane),
  `TestEnsureConsumerLaneBinding.*` (override freeze, dispatched-not-intent, idempotent, drift skip x2).
- [x] Default (no override) path stays **byte-identical**: `lane_record=None -> override=None -> resolve_lane` returns
  the default lane, and the explicit default record (post-freeze) resolves to the same lane
  (`resolve_lane(override=None) == resolve_lane(override=default_lane)`, `lanes.py:91,141`). Existing claude-dispatch
  tests + `test_none_record_dispatches_default_claude_lane`.
- [x] Drift fails open as a **no-call**: a bound lane whose runtime/backend left the catalog raises `LaneError` at the
  `LaneRecord -> Lane` conversion inside the guard -> `configuration_error` fail-open, **neither arm spawned**, never
  the default lane. Verified: `test_drifted_record_fails_open_as_no_call`. (Status "not executable" line is Slice 4.)
- [x] **`consumer_lanes.*` override reject pulled forward from Slice 4 (review P2b).** Slice 1 added `consumer_lanes` to
  `SessionIntent`, so `validate_key` accepted it as an override path the moment dispatch began reading it -- a
  full-object `session set consumer_lanes.supervisor '{...}'` rehydrates into intent and, post-bind, becomes
  recorded-but-ignored (dispatch is confirmed-first). Now statically rejected like `launch.runtime` (`overrides.py`),
  pointing to the resolving commands. Verified: `test_consumer_lanes_rejected_as_command_only`.

**Slice 2->3 carry (RESOLVED by Slice 3).** Between Slice 2 and Slice 3 the branch was deliberately inconsistent:
dispatch + freeze read `consumer_lanes` while status still read `supervisor_runtime`, so an override-set session would
**display** codex but **dispatch + freeze** the default Claude lane (review P1). The clean-break policy
(coding_standards §5) wants the dispatch switch and the `supervisor_runtime` removal in **one atomic change**; splitting
them across commits is acceptable only because T1b is one branch -> one PR, so the divergence never reached `main`.
Slice 3 deleted the field and repointed status to the same binding, closing the divergence.

**Verification:** `tests/src/{cli,policy,session}` -> 3597 passed (P2a/P2b included); bridge + hook + overrides green;
mypy + pyright clean.

### Slice 3 -- Clean-break migration of `supervisor_runtime` (D3) -- DONE

- [x] `SupervisorConfig.supervisor_runtime` deleted (with `models.py`'s `_SUPERVISOR_RUNTIMES` tuple + `__post_init__`
  validation); `_supervisor_lane_override` removed. `resolve_supervisor_lane(lane_record)` now converts the injected
  `LaneRecord -> Lane` override (the hook injects it; the config no longer carries a runtime). Verified:
  `test_supervisor.py` codex tests inject `_CODEX_LANE_RECORD`; the two old `_SUPERVISOR_RUNTIMES<->allowed_lanes` drift
  tests deleted (the field they guarded is gone).
- [x] **Read-time strip-and-warn**: new sibling `strip_removed_supervisor_runtime(data, session_name)` in `store.py`
  (called in `read()` after `strip_preview_memory_doc_lists`) drops `intent.policy.supervisor.supervisor_runtime`
  **and** `overrides.policy.supervisor.supervisor_runtime` before dacite, warning once if the stripped value is
  non-default (not `None`/`"claude_code"`). Without it every T4/T5 manifest carrying the field would fail the strict
  read. Verified: `test_legacy_supervisor_runtime_stripped_on_read` (loads, field gone, warns once); old
  `TestSupervisorRuntimeValidation` deleted.
- [x] `ShadowCandidate.supervisor_runtime: str | None` -> `lane: LaneRecord | None`; `SHADOW_SCHEMA_VERSION` 2 -> 3;
  `capture_candidate(..., lane_record=...)` freezes the resolved lane; `shadow_runner.reconstruct_lane(candidate)` reads
  it back (malformed/absent -> `None` -> default replay) and threads it into
  `run_supervisor_check(..., lane_record=...)`. Verified: `test_shadow.py::test_freezes_resolved_lane` + schema-3
  constant; `test_shadow_runner.py::reconstruct_lane` round-trip/absent/malformed.
- [x] `cli/policy.py` both status sites (JSON helper + text render) repointed to
  `resolve_supervisor_lane(read_bound_lane(manifest, SUPERVISOR_CONSUMER))`; the `data["supervisor_runtime"]` line
  removed; drift text fallback now `Lane: not executable (binding no longer valid)`. `rg supervisor_runtime src/` is
  clean except the strip helper + a shadow-migration comment. Verified: `test_policy_supervisor.py` status tests
  migrated to `consumer_lanes` (JSON null + human "not executable" on resolve failure).

**Verification:** five affected files (`test_supervisor`, `test_shadow`, `test_shadow_runner`, `test_store`,
`test_policy_supervisor`) -> 266 passed; full unit suite -> 7059 passed, 0 failures; mypy clean on all 10 touched source
files. `rg 'supervisor_runtime|_SUPERVISOR_RUNTIMES|_supervisor_lane_override' src/` -> only the strip helper +
shadow-migration comment.

### Slice 4 -- Setters, mutation guard, status (D2) -- DONE

- [x] `validate_key` **statically rejects** `consumer_lanes.*` -- **done early in Slice 2** (review P2b): the reject
  must exist the moment dispatch reads `consumer_lanes`, not wait for the setters. Mirrors `launch.runtime`
  (`overrides.py`); `test_consumer_lanes_rejected_as_command_only`.
- [x] Lane setters **expand runtime -> full `LaneRecord`** via `lane_record_for_runtime(SUPERVISOR_CONSUMER, runtime)`
  (bridge helper, iterates `valid_lanes`): `--supervisor-runtime {claude_code,codex}` on `forge session start` +
  `forge session fork` (requires `--supervise`, extends the existing flag-family check), and
  `forge policy supervisor set --runtime`. All write `intent.consumer_lanes.supervisor` via `set_intent_lane` inside the
  same locked update that writes the `SupervisorConfig`. The Choice menu is derived from `supervisor_lane_runtimes()`
  (one source, no `_SUPERVISOR_RUNTIMES`-style mirror). Verified:
  `test_session_commands.py::test_{fork,start}_supervise_runtime_persists_lane` + `..._without_supervise_errors`;
  `test_policy_supervisor.py::test_runtime_writes_intent_lane` + `test_no_runtime_leaves_lane_unset`; bridge
  `test_consumer_lanes.py::TestLaneRecordForRuntime`/`TestSetIntentLane`.
- [x] Stateful **already-bound reject** lives in `policy supervisor set --runtime` (holds `SessionState`): if
  `confirmed.consumer_lanes.supervisor` exists, `print_error_with_tip` names the frozen `runtime/backend/model` and
  exits 1; `confirmed` and `intent` unchanged. Checked before any proxy side effect; before first dispatch it is
  allowed. Verified: `test_policy_supervisor.py::test_runtime_after_bind_rejected`.
- [x] `forge policy supervisor status` reads the confirmed binding when present, revalidates `LaneRecord -> Lane`, and
  reports drift **without** rewriting the manifest -- **landed in Slice 3** (status repointed to
  `resolve_supervisor_lane(read_bound_lane(...))`, confirmed-first; drift -> `Lane: not executable`). The D1 inert-DTO
  vs validating-domain-type split makes the read path revalidate every call, so no extra drift check was needed.

**Verification:**
`tests/src/{session/test_consumer_lanes, cli/test_policy_supervisor, cli/test_session_commands, policy/semantic/test_supervisor}`
-> 404 passed (15 new); full unit suite -> 7074 passed, 0 failures; mypy + pyright + `make pre-commit` clean. Flags
verified live in `--help` for all three commands; expansion spot-checked (`codex -> chatgpt/gpt-5-codex`).

### Slice 5 -- Docs sync (board_contract "Design Doc Sync")

- [ ] design.md §3.5 (ownership): `confirmed.consumer_lanes` is hook-written (policy-check `_mutate`), write-once.
- [ ] design.md §3.6 (manifest gains consumer-lane `intent`/`confirmed`); design_appendix §G (the binding is now
  persisted + frozen, supervisor wired via injected resolver).
- [ ] cli_reference.md: `--supervisor-runtime` on start/fork + `policy supervisor set --runtime`; the `consumer_lanes.*`
  set rejection; the already-bound rejection; status drift line.
- [ ] Tick the epic checklist "Design-doc sync" T1b row.

## Acceptance tests (fixture-grounded)

| Test                                      | Fixture                                                           | Assertion                                                                  | Test File                                      |
| ----------------------------------------- | ----------------------------------------------------------------- | -------------------------------------------------------------------------- | ---------------------------------------------- |
| `LaneRecord` stores without catalog check | `LaneRecord("ghost_runtime", "ghost_backend", "m")`               | constructs; raises **no** `LaneError` (unlike `Lane(...)`)                 | `tests/src/session/test_models.py`             |
| `LaneRecord`/`Lane` field parity          | the two dataclasses                                               | field names equal (drift guard)                                            | `tests/src/core/test_lanes.py`                 |
| Stale binding still deserializes          | manifest `consumer_lanes.supervisor` on a since-renamed backend   | `load` succeeds; status reports "not executable"; no manifest rewrite      | `tests/src/session/test_store.py`              |
| Binding frozen at first dispatch          | supervisor configured, two PreToolUse dispatches                  | `confirmed.consumer_lanes.supervisor` written once; 2nd reuses it          | `tests/src/policy/semantic/test_supervisor.py` |
| Default lane byte-identical               | no override                                                       | dispatch argv/route identical to T3/T4 baseline                            | `tests/src/policy/semantic/test_supervisor.py` |
| Drift fails open as no-call               | bound codex lane, backend removed from catalog                    | supervisor skips (aligned); **not** run on `claude_code` default           | `tests/src/policy/semantic/test_supervisor.py` |
| Generic lane override rejected            | `set consumer_lanes.supervisor.runtime_id codex`                  | rejected by `validate_key` (points to `--supervisor-runtime`)              | `tests/src/session/test_overrides.py`          |
| Set lane before bind (resolving cmd)      | unbound session, `policy supervisor set --runtime codex`          | writes full `consumer_lanes.supervisor` `LaneRecord`; resolves at dispatch | `tests/src/cli/test_policy_supervisor.py`      |
| Set lane after bind hard-rejects          | bound session, `policy supervisor set --runtime claude_code`      | exits non-zero, actionable message; `confirmed` unchanged                  | `tests/src/cli/test_policy_supervisor.py`      |
| `--supervisor-runtime` round-trips        | `fork P --supervise --supervisor-runtime codex`                   | `intent.consumer_lanes.supervisor` == codex `LaneRecord`                   | `tests/src/cli/test_session_commands.py`       |
| Legacy `supervisor_runtime` strip-on-read | manifest with `intent.policy.supervisor.supervisor_runtime=codex` | loads (stripped), warns once; field gone from `SupervisorConfig`           | `tests/src/session/test_store.py`              |

**Integration (before closeout):** the supervisor dispatch path is hook + `claude -p`/`codex exec`, which unit tests
don't exercise. Run the relevant real-Claude / real-Codex supervisor E2E
(`tests/integration/docker/test_supervisor_e2e.py`) once Slices 2-4 land -- default-lane parity + a codex-lane bind +
the already-bound reject.

## Blockers / deferred

- **Decided:** binding persist folds into the existing post-eval `_mutate` (one lock; equal to a pre-eval lock under the
  D2 freeze).
- T6 (other consumers) and T7 (exhaustion fail-open) stay out of scope; the named-field `ConsumerLaneIntent` is the seam
  T6 extends.

## Closeout

- [ ] All slice assertions ticked with verification recorded.
- [ ] `make pre-commit` clean; focused unit suites + the supervisor E2E green.
- [ ] `change_log.md` entry (Goal / Key changes / Verification).
- [ ] Promote durable lessons to `impl_notes.md` after human review.
- [ ] Update epic roster (T1b -> done) and the epic's T1b design-doc-sync box.
- [ ] `git mv docs/board/doing/consumer_lane_binding docs/board/done/` after merge to `main`.
