# T1b: Consumer-lane binding -- generalize + freeze the supervisor lane

**Epic**: [`docs/board/doing/epic_consumer_lanes/`](../epic_consumer_lanes/card.md) (member **T1b**; depends on T4).

**Type**: Member card. Promotes the narrow `SupervisorConfig.supervisor_runtime` field (T4) into a uniform, persisted
consumer-lane binding: a session-owned `intent` override plus an immutable `confirmed` record, resolved once and frozen.
The supervisor is the single wired consumer; the schema shape is T6-ready (other consumers added later, not here).

**Status**: Active (cursor). Branch `consumer_lane_binding`. Authored 2026-06-27; revised same day after a code-grounded
review (P1-P2 below) tightened D2/D3 and the durable-state and drift contracts.

---

## Problem

T4 placed the supervisor on a codex lane behind `SupervisorConfig.supervisor_runtime: str | None`
(`session/models.py:166`) -- a bare runtime string, validated against a static tuple (`models.py:203`). T5 then surfaced
the full `(runtime, backend, model)` lane on `forge policy supervisor status`, but `backend`/`model` are **nominal**:
only `runtime_id` is load-bearing, the lane is re-resolved live every throttle-miss (`supervisor.py:777`), and nothing
is persisted as a chosen, frozen fact. Two gaps:

1. **The durable contract is a runtime string.** `supervisor_runtime` cannot express backend or model, and the code
   comment at `models.py:163-165` already names this ticket as its successor ("Narrow field; T1b generalizes to a
   uniform consumer-lane binding").
2. **No placement is frozen.** The epic's model is "resolved once and frozen" -- `intent` carries the override,
   `confirmed` carries the committed lane. T1b is where that durable shape lands. The epic deferred it until T4 proved a
   real override exists; it now does.

## Model

| Layer         | Field                                 | Type                          | Writer                            | Semantics                                                              |
| ------------- | ------------------------------------- | ----------------------------- | --------------------------------- | ---------------------------------------------------------------------- |
| **Intent**    | `intent.consumer_lanes.supervisor`    | `LaneRecord \| None`          | resolving commands (see D2)       | Requested lane; immutable once `confirmed` exists                      |
| **Confirmed** | `confirmed.consumer_lanes.supervisor` | `ConsumerLaneBinding \| None` | policy-check hook, first dispatch | Frozen resolved lane; durable record + the anchor the D2 reject checks |

Both sections gain a `consumer_lanes` field of a **dataclass with named per-consumer fields** (`supervisor` only in
T1b), never a `dict[str, ...]` (see D1). Fields are optional + defaulted, so existing manifests load unchanged.

## Decisions (settled 2026-06-27)

### D1 -- Storage DTO (`LaneRecord`), not the validating domain type (`Lane`)

`confirmed` is **inert historical fact**, so the persisted lane must not re-validate against the live catalogs on read.

- Add `LaneRecord` to `session/models.py`: plain `runtime_id` / `backend_id` / `model` strings, non-empty validation
  only, **no catalog/runtime import**. `core.lanes.Lane` stays the validated resolver type.
- The binding write path converts `LaneRecord -> Lane(...)` **once** (validating against today's catalogs), then
  persists the inert `LaneRecord`. Dispatch and status revalidate on demand and can report "binding no longer
  executable" **without rewriting the manifest**.
- **Why, verified:** `Lane.__post_init__` (`core/lanes.py:58-71`) validates `runtime_id` against `RUNTIMES` and
  `backend_id` against the `ModelSource` catalog, and dacite constructs typed fields on **every** manifest read
  (`store.py:190`, `effective.py:90`, both `strict=True`). Typing the field `Lane` would make a renamed backend or
  removed runtime turn an old, valid session into "corrupt state" -- it is just a stale historical binding.
- **Import boundary:** `session.models` is deliberately catalog-free today (imports only `core.effort` / `core.state` /
  `policy.*`, `models.py:13-16`). Importing `core.lanes` would drag the whole `ModelSource` catalog into foundational
  manifest loading. No hard cycle (`backend.sources` does not import `session.*`), but it violates the file's pattern:
  it already keeps `_SUPERVISOR_RUNTIMES` (`models.py:30`) and `_CHECKER_EFFORT_LEVELS` (`models.py:27`) as **inline
  mirrors with a drift-guard test** (`test_effort.py`). `LaneRecord` follows suit: a
  `dataclasses.fields(LaneRecord) == fields(Lane)` parity test guards the duplication.

### D2 -- Freeze at first dispatch; set only through resolving commands; reject a change after bind

- **Single immutability seam:** `ensure_consumer_lane_binding(state, consumer)` resolves via `resolve_lane`, validates
  `LaneRecord -> Lane`, writes `confirmed.consumer_lanes.<consumer>` **only if absent**, and returns the existing
  binding otherwise. Mirrors the `claude_session_id` pre-seed / `LaunchConfirmed` write-once discipline.

- **Timing is "first dispatch," not "session start."** The supervisor can be wired mid-session
  (`forge policy supervisor set`), so the binding freezes the first time the policy-check hook resolves the lane.

- **Resolution is an injected binding resolver (resolves P2).** After D3, `run_supervisor_check` resolves no lane itself
  -- it receives `SupervisorConfig + ActionContext`, not the store. The policy-check hook, which holds `SessionStore`,
  resolves the lane from `intent.consumer_lanes.supervisor` and **injects** it into `run_supervisor_check` (replacing
  `_supervisor_lane_override(config)`, `supervisor.py:681,777`). The binding is persisted **write-if-absent**; the lean
  is to fold that into the existing locked post-eval `_mutate` that already writes `confirmed.policy`
  (`cli/hooks/policy.py:248-259`) -- one lock, and because intent is frozen once bound, intent-resolved == the frozen
  binding on every dispatch. A pre-eval locked persist (literal "dispatch reads confirmed before use") is the
  alternative; it costs a second lock for no functional change under this freeze. **Decided: fold into the existing
  post-eval lock.**

- **The lane is set only through resolving commands, never a raw override.** A runtime-only leaf override
  (`session set consumer_lanes.supervisor.runtime_id codex`) cannot rehydrate -- `LaneRecord` requires all three fields
  and the override path strict-rehydrates a sparse dict (`effective.py:90`). So `consumer_lanes.*` is **statically
  rejected by `validate_key`** (like `launch.runtime`, `overrides.py:201`), pointing to the flag. Setters **expand
  runtime -> full `LaneRecord`** against `SUPERVISOR_CONSUMER.allowed_lanes`: the start/fork `--supervisor-runtime` flag
  and `forge policy supervisor set --runtime`.

- **Hard-reject a lane change after bind, inside the resolving command (stateful).**
  `forge policy supervisor set --runtime <other>` on a session whose `confirmed.consumer_lanes.supervisor` exists fails
  -- the guard holds `SessionState`; the cached, stateless `validate_key`/`set_override` (`overrides.py:43,277`) cannot
  see `confirmed`. Setting the runtime **before** first dispatch is allowed. Warn-and-ignore is the failure mode the
  `launch.runtime` reject exists to prevent ("recorded but ignored -- worse than rejection"). Message:

  ```text
  Error: Cannot change the supervisor lane for an already-bound session.
  This session is frozen on codex/chatgpt/gpt-5-codex.
  Start or fork a fresh session to use a different lane.
  ```

- **Required companion change (the review's finding):** there is **no** start/fork lane flag today (`session_fork.py` /
  `session_lifecycle.py` expose `--supervise`/`--supervisor-proxy`/`--cascade`/`--checker-*`/`--supervisor-effort`,
  never a runtime/lane flag). The supervisor fires on the first Write/Edit, so the binding freezes almost immediately; a
  hard-reject on the post-bind change would leave **no setter at all** and make the reject message ("fork a fresh
  session") un-actionable. T1b **must** add `--supervisor-runtime {claude_code,codex}` (requires `--supervise`) to
  `forge session start` and `forge session fork`. The parent's `confirmed` stays true; the child gets a fresh binding.

### D3 -- Clean-break migration of `supervisor_runtime` (no dual source of truth)

Delete `SupervisorConfig.supervisor_runtime` and route lane selection through `intent.consumer_lanes.supervisor` / the
confirmed binding. Internal-surface clean break (coding_standards §5): update callers atomically, no shim. Touchpoints:

- `_supervisor_lane_override(config)` (`supervisor.py:681`) -- deleted; the hook injects the resolved lane instead (D2).
- `ShadowCandidate.supervisor_runtime` (`shadow.py:92`) -- the shadow replay must carry the resolved lane; bump
  `SHADOW_SCHEMA_VERSION` (currently 2).
- `cli/policy.py:369,371,967,971` -- status reads `supervisor_runtime` + `resolve_supervisor_lane`; repoint to the
  binding/intent lane and add the drift report (D1).
- **Read-time strip-and-warn for the removed field** (the durable-state half, see below).

## Durable-state compliance (coding_standards §5)

- **Adding `consumer_lanes` is additive:** the new `intent`/`confirmed.consumer_lanes` fields are optional + defaulted,
  so `SessionState.schema_version` stays `1` (house precedent: usage-ledger `route`/`reporter`/`confidence` added at
  v1). Reads stay `dacite.Config(strict=True)`.
- **Removing `supervisor_runtime` is a clean break, NOT additive (D3).** An existing manifest or override carrying
  `intent.policy.supervisor.supervisor_runtime` would fail the strict read once the field is gone. Handled exactly like
  the already-removed `designated_docs`: a read-time **strip-and-warn** (`store.py:54,183`,
  `strip_preview_memory_doc_lists`) removes the key from `intent` **and** `overrides` before dacite and warns once if it
  was non-default. This is the §5 "known legacy state intentionally ignored, surfaced with a one-time notice" path --
  not a value shim (forbidden) and not a version bump (house precedent strips at the same version).
- **Reset / drift path:** a *bad/unwanted* binding resets by forking/starting fresh (the D2 message names this). A
  *drifted* binding (renamed catalog) stays loadable (D1); the supervisor **fails open as a no-call** -- it skips the
  check (aligned, like T4's `codex_unavailable`), and status reports "not executable". It **never silently runs the
  default lane** (that would bill the engine the user moved off).

## Scope

**In:** `LaneRecord` + `ConsumerLane{Intent,Binding,Confirmed}` dataclasses; `intent`/`confirmed` `consumer_lanes`
fields; `ensure_consumer_lane_binding` freeze seam; injected-resolver wiring in the policy-check hook; D3 clean-break
removal + strip-and-warn; `validate_key` reject of `consumer_lanes.*`; runtime-expanding setters (`--supervisor-runtime`
on start/fork, `policy supervisor set --runtime`); stateful already-bound reject; status drift report; design + CLI doc
sync.

**Out:** lane-driving any consumer other than the supervisor (T6); subscription-exhaustion fail-open (T7); `claude-max`
billing (T0); a generic `dict`-keyed consumer registry; transport selection (still derived at dispatch).

## Risks / open questions

- **Persist timing (decided):** the binding write folds into the existing post-eval `_mutate` (one lock). A pre-eval
  locked persist was the alternative; equal under the D2 freeze, so the cheaper path wins.
- **Flag spelling / intent shape (resolved):** the user-facing flag is **runtime-only**
  (`--supervisor-runtime {claude_code,codex}`); the command resolves it against `SUPERVISOR_CONSUMER.allowed_lanes` and
  stores a **full `LaneRecord`** in intent, so `intent` and `confirmed` share one shape. A generic
  `--lane <consumer>=<runtime>/<backend>/<model>` form is deferred to T6.
- **`ConsumerLaneBinding` is minimal:** `lane: LaneRecord`, `source: str` (`"default" | "intent"`, plain `str` per the
  fail-open `*Confirmed` style), `resolved_at: str`. Dropped vs the first sketch: `consumer_id` (implied by the named
  field), `default_lane` (derivable from the code consumer), `binding_version` (the manifest's `schema_version` is the
  one versioning knob).
- **Shadow replay schema bump** must land with D3 or the shadow auditor replays on the wrong lane.
- **Ownership doc:** `confirmed.consumer_lanes` is **hook-written** (the policy-check hook's locked `_mutate`), joining
  `confirmed.policy` -- not a CLI-owned exception. design.md §3.5 must say so.

## Verified touchpoints (file:line, 2026-06-27)

| Concern                         | Location                                                                         |
| ------------------------------- | -------------------------------------------------------------------------------- |
| Narrow field to promote         | `session/models.py:166` (+ comment `:163-165`, validation `:203`)                |
| Catalog-free import precedent   | `session/models.py:13-16,27,30`                                                  |
| Validating domain type          | `core/lanes.py:46` (fields), `:58-71` (`__post_init__`), `:131` (`resolve_lane`) |
| Strict read paths               | `session/store.py:190`, `session/effective.py:90`                                |
| Removed-field strip precedent   | `session/store.py:54,183` (`strip_preview_memory_doc_lists`)                     |
| Stateless/cached key validation | `session/overrides.py:43,90,201,277`                                             |
| Live lane re-resolve (dispatch) | `policy/semantic/supervisor.py:681,716,777`                                      |
| Confirmed persisted (locked)    | `cli/hooks/policy.py:197-259` (`store.update(mutate=_mutate)`)                   |
| Shadow candidate field          | `policy/semantic/shadow.py:92`                                                   |
| Status lane surface (T5)        | `cli/policy.py:40,369,371,967,971`                                               |
| Supervise flag family (no lane) | `cli/session_fork.py:170-221`, `cli/session_lifecycle.py:1199+`                  |
| Write-once confirmed precedent  | `session/models.py:419-445` (`LaunchConfirmed`)                                  |
