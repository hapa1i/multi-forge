# Checklist: T1a -- Pure lane/consumer resolver

**Card**: `card.md` (this dir). **Epic**: `docs/board/doing/epic_consumer_lanes/`. **Branch**: `consumer_lane_resolver`.

## Current focus

Phase 0 locks the runtime-execution model (decided: option 2 -- classify in the lane layer, leave `RUNTIMES` untouched),
then build the pure resolver in a new `src/forge/core/lanes/` module. No consumer is rewired (T3); no persistence (T1b).

## Decisions (resolved)

- **Runtime-execution representation = option 2** (overrides the card's earlier option-1 lean). `RUNTIMES.values()` is
  iterated by `list_runtimes()` / `installed_runtimes()` (`core/runtime/registry.py:251,256`), which assume *agent*
  runtimes; adding a `core.llm` entry pollutes them + every caller and needs an always-true `is_installed()` hack.
  Instead, classify execution in the lane layer and leave `RUNTIMES` unmodified -- `core.llm` is not an agent runtime.
  Lane runtime axis = `{"core_llm"}` plus `RUNTIMES.keys()`.

## Phase 0 -- Runtime execution capability (no registry change)

- [ ] `runtime_execution(runtime_id) -> Literal["single_shot", "tool_agent"]` in the lane module: `"core_llm"` ->
  `single_shot`; otherwise `get_runtime(runtime_id)` must resolve -> `tool_agent`.
- [ ] Floor ordering helper: `single_shot < tool_agent`; a runtime satisfies a floor when its execution `>=` the floor.

Assertions: `claude_code` / `codex` / `gemini` classify `tool_agent`; `"core_llm"` classifies `single_shot`; `RUNTIMES`
is unmodified and `list_runtimes()` still returns exactly the three agent runtimes.

## Phase 1 -- Types (`src/forge/core/lanes/`)

- [ ] `Lane` (frozen, hashable): `runtime_id`, `backend_id` (a `ModelSource` id), `model`, and a *derived* `transport`
  (`"direct" | "proxy"`) computed from backend reachability -- never a constructor argument.
- [ ] `Consumer` (frozen): `id`, `capability_floor` (`single_shot | tool_agent`), `default_lane`.
- [ ] Construction validates against the catalog + runtime axis: an unknown runtime / backend / model raises
  `ValueError` (internal boundary, coding_standards §5). No silent defaults.
- [ ] **`default_lane` must itself pass the gates.** Validate at construction that `default_lane` is in
  `valid_lanes(consumer)` (floor + reachability) -> `ValueError` on an out-of-floor or unreachable default. This stops
  an invalid default from bypassing the checks an override must pass. (Shares the Phase 2 gating helper, so Consumer
  validation is wired after it.)

## Phase 2 -- Reachability + resolver

- [ ] `_reachable(runtime_id, backend_id) -> bool` from the catalog + `RUNTIMES` (sparse, not a cross-product). T1a
  covers today's catalog only; subscription pins (`chatgpt` only via `codex`) arrive with T2.
- [ ] `valid_lanes(consumer) -> tuple[Lane, ...]` = lanes whose runtime satisfies the floor AND whose
  `(runtime, backend)` is reachable. For validation + option-listing only (no failover).
- [ ] `resolve_lane(consumer, *, override=None) -> Lane`: return `override` if it is in `valid_lanes`, else the default
  (already guaranteed valid by `Consumer` construction); raise `ValueError` on an illegal override. Pure -- no file /
  proxy / subprocess I/O.

## Phase 3 -- Tests (`tests/src/core/test_lanes.py`)

The card's acceptance table, plus the Phase 0 regression guard:

| Test                            | Assertion                                                                                             |
| ------------------------------- | ----------------------------------------------------------------------------------------------------- |
| default, no override            | `resolve_lane` returns the default lane unchanged                                                     |
| invalid default rejected        | a consumer whose `default_lane` violates its floor / reachability raises `ValueError` at construction |
| floor excludes single-shot      | tool-agent-floor consumer: no `core_llm` lane in `valid_lanes`; selecting it raises `ValueError`      |
| floor admits single-shot        | single-shot-floor consumer: both `core_llm` and agent lanes in `valid_lanes`                          |
| sparse reachability             | `valid_lanes` = floor intersect reachable; no full cross-product                                      |
| purity                          | `resolve_lane` does no I/O (no-fs / monkeypatch guard)                                                |
| RUNTIMES untouched (regression) | `list_runtimes()` returns exactly `claude_code`, `codex`, `gemini`                                    |

## Phase 4 -- Closeout

- [ ] `make pre-commit` clean; `mypy` + `pyright` pass on `src/forge/core/lanes/`.
- [ ] Design-doc sync deferred to T3: the resolver is unused until a consumer is wired, so the `design_appendix.md` §G /
  `design.md` §3.6.12 update lands with T3 (already tracked in the epic checklist). T1a is internal + additive.
- [ ] `change_log.md` entry (feature completion, ~15-25 lines); epic roster: T1a -> done.
- [ ] After merge to `main`, move `doing/consumer_lane_resolver/` -> `done/` (board_contract closeout).

## Deferred / not in this ticket

- Subscription backend shapes + `(runtime, backend)` pins -> T2.
- Rewiring the supervisor (or any consumer) -> T3.
- Manifest persistence of overrides / `confirmed` -> T1b.
