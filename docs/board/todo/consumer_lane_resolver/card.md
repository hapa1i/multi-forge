# T1a -- Pure lane/consumer resolver (spine)

**Epic**: `docs/board/doing/epic_consumer_lanes/` -- read the epic for the shared lane contract (lane = runtime x
backend x model; consumer; capability floor; binding).

**Lane**: `todo/` (accepted, first wave). No execution branch open yet.

**Proves**: the lane abstraction fits the existing code with zero durable-schema commitment.

## Goal

Add the pure, side-effect-free core of the lane model: `Lane` and `Consumer` types, default-lane computation,
capability-floor + `(runtime, backend)` reachability gating, and valid-lane listing/validation. **No persistence. No
consumer rewired.** This is the contract every later ticket references.

## Scope

- New module `src/forge/core/lanes/` (first-class concept; depends on `core.reactive.routing`, `core.runtime.registry`,
  `backend.sources`).
- `Lane`: a `(runtime, backend, model)` tuple plus the *derived* transport (direct vs proxy) -- computed, never chosen.
- `Consumer`: a stable id, a **capability floor**, and a **default lane** policy. The floor is read from runtime
  capability, not invented per consumer.
- `resolve_lane(consumer, *, override=None) -> Lane`: intersect the floor with the reachable `(runtime, backend)` set,
  then pick the override if legal else the default. Pure: no I/O, no manifest, no subprocess.
- `valid_lanes(consumer) -> tuple[Lane, ...]`: floor intersect reachable, for validation + option-listing (not
  failover).

## Reuse (verified touchpoints)

- `RoutingResult` + `resolve_subprocess_routing` -- `src/forge/core/reactive/routing.py:61,279` (transport + base_url).
- `RuntimeSpec` / `RUNTIMES` -- `src/forge/core/runtime/registry.py:109,148`. Already carry harness-thickness signals
  (`native_hooks`, `pretool_policy`, `headless`) the floor can read.
- `ModelSource` / `list_model_sources()` -- `src/forge/backend/sources.py:103,372` (the backend axis).
- `WorkerRoutingPlan` -- `src/forge/review/routing.py:50` (the "resolve once, frozen" precedent; not modified here).

## Open design decision (resolve in this ticket)

**Where does `core.llm` sit?** `RuntimeSpec` is subprocess-shaped (`headless_cmd: tuple[str, ...]`, `is_installed()` via
`shutil.which`) and documents itself as "one *agent* runtime". `core.llm` is in-process and single-shot -- it has no
`headless_cmd`. Two options:

1. Add a `core.llm` entry to `RUNTIMES` with a new capability attr (e.g. `execution: "single_shot" | "tool_agent"`) and
   a sentinel/empty `headless_cmd`; make `is_installed()` always-true for it. One runtime table.
2. Keep `RUNTIMES` agent-only; model the lane runtime axis as `{core.llm}` plus `RUNTIMES.keys()`, with `core.llm`'s
   capability in a small separate record.

Recommendation: option 1 with an explicit `execution` attr -- one table, and the floor reads `execution` directly.
Record the choice in the epic `checklist.md` (it affects T3's default-lane wiring).

## Acceptance (definition of done; operationalized in the checklist when this card opens)

| Test                       | Fixture                                          | Assertion                                                                                     | Test File                      |
| -------------------------- | ------------------------------------------------ | --------------------------------------------------------------------------------------------- | ------------------------------ |
| Default, no override       | consumer with tool-agent floor, no override      | `resolve_lane` returns the consumer's default lane unchanged                                  | `tests/src/core/test_lanes.py` |
| Floor excludes single-shot | a file-reading consumer (tool-agent floor)       | a `core.llm` lane is **not** in `valid_lanes`; selecting it raises `ValueError`               | `tests/src/core/test_lanes.py` |
| Floor admits single-shot   | a judges-provided-text consumer (single-shot ok) | both `core.llm` and tool-agent lanes appear in `valid_lanes`                                  | `tests/src/core/test_lanes.py` |
| Reachability is sparse     | catalog + RUNTIMES                               | `valid_lanes` = floor intersect reachable; no full cross-product                              | `tests/src/core/test_lanes.py` |
| Purity                     | any                                              | `resolve_lane` performs no file/proxy/subprocess I/O (asserted via a no-fs/monkeypatch guard) | `tests/src/core/test_lanes.py` |

## Non-goals

- No manifest read/write (that is T1b).
- No consumer rewired to use the resolver (T3 does the supervisor first).
- No new backend shapes (`runtime_native`, billing posture) -- that is T2; T1a operates over today's catalog.
- No fallback/failover; `valid_lanes` is for validation + listing only.

## Depends on

Nothing. This is the spine.
