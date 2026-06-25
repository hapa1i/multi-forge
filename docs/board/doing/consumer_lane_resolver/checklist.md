# Checklist: T1a -- Pure lane/consumer resolver

**Card**: `card.md` (this dir). **Epic**: `docs/board/doing/epic_consumer_lanes/`. **Branch**: `consumer_lane_resolver`.

## Current focus

Phases 0-3 implemented in `src/forge/core/lanes.py` with `tests/src/core/test_lanes.py` (15 tests green; mypy + pyright
\+ pre-commit clean). **Closeout in progress**: change_log entry added; PR open against `main`. After merge: flip the
epic roster T1a -> done and move `doing/consumer_lane_resolver/` -> `done/`. No consumer is rewired (T3); no persistence
(T1b).

## Decisions (resolved)

- **Runtime-execution representation = option 2** (overrides the card's earlier option-1 lean). `RUNTIMES.values()` is
  iterated by `list_runtimes()` / `installed_runtimes()` (`core/runtime/registry.py:251,256`), which assume *agent*
  runtimes; adding a `core.llm` entry pollutes them + every caller and needs an always-true `is_installed()` hack.
  Instead, classify execution in the lane layer and leave `RUNTIMES` unmodified -- `core.llm` is not an agent runtime.
  Lane runtime axis = `{"core_llm"}` plus `RUNTIMES.keys()`.
- **Transport deferred** to dispatch (T3): `resolve_subprocess_routing` reads the proxy registry + health-probes (I/O),
  so a pure `Lane`/resolver cannot carry it. `Lane = (runtime, backend, model)`.
- **Override = allow-list** (flagged for review): an override must be one of the consumer's declared `allowed_lanes`,
  not merely any floor+reachable lane. Keeps `valid_lanes` a concrete, model-bearing set and gives each consumer
  control.

## Phase 0 -- Runtime execution capability (no registry change)

- [x] `runtime_execution(runtime_id) -> Literal["single_shot", "tool_agent"]` in the lane module: `"core_llm"` ->
  `single_shot`; an agent runtime in `RUNTIMES` -> `tool_agent`; unknown -> `LaneError`.
- [x] Floor ordering: `single_shot < tool_agent` (`_FLOOR_RANK`); a runtime satisfies a floor when its execution `>=`
  the floor (`_satisfies_floor`).

Verified: `claude_code` / `codex` / `gemini` classify `tool_agent`; `"core_llm"` classifies `single_shot`; `RUNTIMES` is
unmodified and `list_runtimes()` excludes `core_llm` (`test_runtimes_table_not_polluted_by_core_llm`).

## Phase 1 -- Types (`src/forge/core/lanes.py`)

- [x] `Lane` (frozen, hashable): `runtime_id`, `backend_id` (a `ModelSource` id), `model`. **No transport field** -- the
  live direct/proxy choice (`base_url`) is I/O-bound and resolved at *dispatch* (T3), not by the pure resolver.
- [x] `Consumer` (frozen): `id`, `capability_floor` (`single_shot | tool_agent`), `default_lane`, and
  `allowed_lanes: tuple[Lane, ...] = ()` -- a small **declared candidate set**, never a runtime x backend x model
  cross-product.
- [x] `Lane` construction validates runtime (`RUNTIMES` / `core_llm`) + backend (`ModelSource` catalog) -- both code
  constants -- normalizes `backend_id` to the canonical id (template aliases accepted, so alias/canonical lanes compare
  equal), and requires a non-empty `model`; unknown runtime/backend raises `LaneError`. Full model-catalog validation is
  deferred to T3, keeping the whole T1a module I/O-free.
- [x] **`default_lane` must itself pass the gates.** Validated at construction (`default_lane in valid_lanes(self)`) ->
  `LaneError` on an out-of-floor or unreachable default, so it cannot bypass the checks an override must pass.

## Phase 2 -- Reachability + resolver

- [x] `_reachable(runtime_id, backend_id) -> bool`, pure (code constants only). T1a has **no hard pins**; the floor does
  the filtering. Subscription pins (`chatgpt` only via `codex`) arrive with T2.
- [x] `valid_lanes(consumer) -> tuple[Lane, ...]` = the consumer's declared candidates (`{default_lane}` plus
  `allowed_lanes`) filtered by floor + reachability. A filtered *declared set*, never an enumerated cross-product.
- [x] `resolve_lane(consumer, *, override=None) -> Lane`: `override` if it is in `valid_lanes`, else the default
  (guaranteed valid by `Consumer` construction); `LaneError` on an illegal override. Pure -- no I/O.

## Phase 3 -- Tests (`tests/src/core/test_lanes.py`)

All 15 tests pass. The card's acceptance table plus the Phase 0 regression guard:

| Test                            | Assertion                                                                                            |
| ------------------------------- | ---------------------------------------------------------------------------------------------------- |
| default, no override            | `resolve_lane` returns the default lane unchanged                                                    |
| invalid default rejected        | a consumer whose `default_lane` violates its floor / reachability raises `LaneError` at construction |
| floor excludes single-shot      | tool-agent-floor consumer: no `core_llm` lane in `valid_lanes`; selecting it raises `LaneError`      |
| floor admits single-shot        | single-shot-floor consumer: both `core_llm` and agent lanes in `valid_lanes`                         |
| declared set, not cross-product | `valid_lanes` returns only declared candidates; an undeclared (but compatible) override is rejected  |
| purity                          | `resolve_lane` does no file I/O (patched `open` guard)                                               |
| RUNTIMES untouched (regression) | `list_runtimes()` excludes `core_llm`                                                                |

## Phase 4 -- Closeout

- [x] `make pre-commit` clean; `mypy` + `pyright` pass on `src/forge/core/lanes.py` + the test.
- [x] Design-doc sync: nothing to sync for T1a (internal + additive). The `design_appendix.md` §G / `design.md` §3.6.12
  update lands with T3 when a consumer is wired (tracked in the epic checklist).
- [x] `change_log.md` entry added (2026-06-25). Epic roster T1a -> done flips at merge.
- [ ] After the PR merges to `main`, move `doing/consumer_lane_resolver/` -> `done/` (board_contract closeout).

## Deferred / not in this ticket

- Subscription backend shapes + `(runtime, backend)` pins -> T2.
- Rewiring the supervisor (or any consumer) -> T3.
- Manifest persistence of overrides / `confirmed` -> T1b.
