# T1b execution checklist: consumer_lane_binding

**Card**: [`card.md`](card.md). **Epic**: [`docs/board/doing/epic_consumer_lanes/`](../epic_consumer_lanes/card.md).
**Branch**: `consumer_lane_binding`.

## Current focus

Slice 1 (schema) **complete**; Slice 2 (binding resolution + injected resolver) is next. Design is fully settled (D1-D3
in `card.md`; persist timing decided -- fold into the existing post-eval lock). Tick a box only when its assertion is
verified and recorded -- not when work merely starts.

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

**Verification:** `tests/src/session` + `tests/src/core/test_lanes.py` -> 1022 passed (9 new cases green); mypy + pyright
clean on `models.py`.

### Slice 2 -- Binding resolution + freeze seam (injected resolver)

- [ ] The policy-check hook (holds `SessionStore`) resolves the lane from `intent.consumer_lanes.supervisor` and
  **injects** it into `run_supervisor_check` (replaces `_supervisor_lane_override(config)`, `supervisor.py:681,777`).
  `run_supervisor_check` keeps taking `SupervisorConfig + ActionContext` only -- it never reads the store.
- [ ] `ensure_consumer_lane_binding(state, consumer)` (resolve via `resolve_lane`, validate `LaneRecord -> Lane`, write
  `confirmed.consumer_lanes.<consumer>` **only if absent**) is called **inside the existing locked post-eval `_mutate`**
  that already writes `confirmed.policy` (`cli/hooks/policy.py:248-259`) -- no second lock (persist timing decided).
- [ ] Default (no override) path stays **byte-identical** to T3/T4 (parity assertion).
- [ ] Drift fails open as a **no-call**: a lane (`LaneRecord -> Lane`) that no longer validates makes the supervisor
  **skip the check** (aligned/warn, like T4's `codex_unavailable`; design_workflows §1.2), surfaced in status as "not
  executable". It **never** silently runs the default lane, and never raises into the hook.

### Slice 3 -- Clean-break migration of `supervisor_runtime` (D3)

- [ ] `SupervisorConfig.supervisor_runtime` deleted; `_supervisor_lane_override` removed (the hook injects the lane).
- [ ] **Read-time strip-and-warn**: extend `strip_preview_memory_doc_lists` (or a sibling) in `store.py` to drop
  `intent.policy.supervisor.supervisor_runtime` **and** `overrides...supervisor_runtime` before dacite, warning once if
  non-default. Without this, every T4/T5 manifest carrying the field fails the strict read.
- [ ] `ShadowCandidate` carries the resolved lane (not a runtime string); `SHADOW_SCHEMA_VERSION` bumped; shadow replay
  uses it.
- [ ] `cli/policy.py` (`:369,371,967,971`) repointed to the binding/intent lane; `rg supervisor_runtime src/` clean
  except the strip helper.

### Slice 4 -- Setters, mutation guard, status (D2)

- [ ] `validate_key` **statically rejects** `consumer_lanes.*` (a partial leaf override can't build a `LaneRecord`;
  mirrors `launch.runtime`, `overrides.py:201`), with a message pointing to `--supervisor-runtime`.
- [ ] Lane setters **expand runtime -> full `LaneRecord`** against `SUPERVISOR_CONSUMER.allowed_lanes`:
  `--supervisor-runtime {claude_code,codex}` on `forge session start` + `forge session fork` (requires `--supervise`),
  and `forge policy supervisor set --runtime`. All write `intent.consumer_lanes.supervisor`.
- [ ] Stateful **already-bound reject** lives in `policy supervisor set --runtime` (holds `SessionState`): if
  `confirmed.consumer_lanes.supervisor` exists, fail with the actionable message; `confirmed` unchanged. Before first
  dispatch it is allowed.
- [ ] `forge policy supervisor status` reads the confirmed binding when present, revalidates `LaneRecord -> Lane`, and
  reports "binding no longer executable" on drift **without** rewriting the manifest.

### Slice 5 -- Docs sync (board_contract "Design Doc Sync")

- [ ] design.md §3.5 (ownership): `confirmed.consumer_lanes` is hook-written (policy-check `_mutate`), write-once.
- [ ] design.md §3.6 (manifest gains consumer-lane `intent`/`confirmed`); design_appendix §G (the binding is now
  persisted + frozen, supervisor wired via injected resolver).
- [ ] cli_reference.md: `--supervisor-runtime` on start/fork + `policy supervisor set --runtime`; the `consumer_lanes.*`
  set rejection; the already-bound rejection; status drift line.
- [ ] Tick the epic checklist "Design-doc sync" T1b row.

## Acceptance tests (fixture-grounded)

| Test                                       | Fixture                                                                 | Assertion                                                              | Test File                                  |
| ------------------------------------------ | ----------------------------------------------------------------------- | --------------------------------------------------------------------- | ------------------------------------------ |
| `LaneRecord` stores without catalog check  | `LaneRecord("ghost_runtime", "ghost_backend", "m")`                      | constructs; raises **no** `LaneError` (unlike `Lane(...)`)            | `tests/src/session/test_models.py`         |
| `LaneRecord`/`Lane` field parity           | the two dataclasses                                                      | field names equal (drift guard)                                       | `tests/src/core/test_lanes.py`             |
| Stale binding still deserializes           | manifest `consumer_lanes.supervisor` on a since-renamed backend          | `load` succeeds; status reports "not executable"; no manifest rewrite | `tests/src/session/test_store.py`          |
| Binding frozen at first dispatch           | supervisor configured, two PreToolUse dispatches                         | `confirmed.consumer_lanes.supervisor` written once; 2nd reuses it      | `tests/src/policy/semantic/test_supervisor.py` |
| Default lane byte-identical                | no override                                                              | dispatch argv/route identical to T3/T4 baseline                       | `tests/src/policy/semantic/test_supervisor.py` |
| Drift fails open as no-call                | bound codex lane, backend removed from catalog                           | supervisor skips (aligned); **not** run on `claude_code` default      | `tests/src/policy/semantic/test_supervisor.py` |
| Generic lane override rejected             | `set consumer_lanes.supervisor.runtime_id codex`                        | rejected by `validate_key` (points to `--supervisor-runtime`)        | `tests/src/session/test_overrides.py`      |
| Set lane before bind (resolving cmd)       | unbound session, `policy supervisor set --runtime codex`                 | writes full `consumer_lanes.supervisor` `LaneRecord`; resolves at dispatch | `tests/src/cli/test_policy_supervisor.py`  |
| Set lane after bind hard-rejects           | bound session, `policy supervisor set --runtime claude_code`             | exits non-zero, actionable message; `confirmed` unchanged             | `tests/src/cli/test_policy_supervisor.py`  |
| `--supervisor-runtime` round-trips         | `fork P --supervise --supervisor-runtime codex`                          | `intent.consumer_lanes.supervisor` == codex `LaneRecord`              | `tests/src/cli/test_session_commands.py`   |
| Legacy `supervisor_runtime` strip-on-read  | manifest with `intent.policy.supervisor.supervisor_runtime=codex`        | loads (stripped), warns once; field gone from `SupervisorConfig`     | `tests/src/session/test_store.py`          |

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
