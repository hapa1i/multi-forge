# Supervisor Status-Line Health -- Execution Checklist

Execution plan for [`card.md`](card.md). Branch: `supervisor_statusline_health`.

**Scope (re-cut 2026-06-16).** Surface frontier-supervisor **fail-open** on the always-visible status bar using the
outcome data the **usage ledger already records** -- no new durable-state field. The supervisor emits
`status="timeout"`/`failure_type` per `claude -p` run (`emit_usage_for_session_result`, `supervisor.py:496`), and the
status line already reads the ledger throttled (the `forge_cost` segment). v1 = a throttled read + a posture-preserving
render. The structured-`failure_kind`-on-`PolicyDecision` design and the parse/auth coverage it enabled are deferred to
[`upstream_downstream_ledgers`](../../proposed/upstream_downstream_ledgers/card.md) -- adding a field to the policy
decision log is the off-model path (patches the accidental outcome record, not the real one).

## Current focus

Phase 1: `read_supervisor_health(session, since) -> SupervisorHealth` -- a pure, fail-open reader over the usage ledger
(`command="supervisor"`, newest-first consecutive `status in {error, timeout}`, reset on the first `status="success"`),
beside `sum_forge_added_cost`, then surfaced throttled, mirroring `read_or_compute_session_cost`.

## Verified ground truth (read before implementing)

- **The fail-open is already in the ledger.** `_session_status` maps `SessionResult.timed_out -> ("timeout","timeout")`,
  subprocess error `-> ("error","subprocess_error")` (`src/forge/core/usage/emit.py`); the supervisor's sole emit is
  `emit_usage_for_session_result(...)` at `supervisor.py:496`. `forge activity` already shows `supervisor 24/24 errors`
  from these events. **No new emit, no new field.**
- **The status line already reads the ledger, throttled.** `forge_cost` uses `read_or_compute_session_cost`
  (`src/forge/cli/statusline/throttle.py:133`) + `sum_forge_added_cost` (`src/forge/core/ops/usage_summary.py:264`),
  wired at `registry.py:276-298`. v1 mirrors this (time-throttled, fail-open).
- **Kind from `failure_type`.** Values: `timeout | subprocess_error | runtime_reported_error | exit_<N>`. Display map:
  `timeout -> "timeout"`; everything else `-> "error"`.
- **Render is golden-immune.** `supervisor` is opt-in, excluded from `names.DEFAULT_ORDER`; the suffix appears only when
  failures exist, so healthy `SUP` stays byte-identical. ASCII `!` is already the in-line alert char (`status_line.py`).
- **v1 fails safe.** A working supervisor (aligned, or a parsed warn/deny) logs `status="success"`, never error -- so v1
  can under-warn (misses parse/auth, deferred) but never over-warns.

## Resolved design decisions

| Question        | Decision                                                                               | Why                                                                                                                  |
| --------------- | -------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| Source          | **Usage ledger** `command="supervisor"` `status` -- not `PolicyDecision.failure_kind`  | Outcome data already exists; the decision-log field is the off-model path deferred to the refactor card.             |
| Recency window  | **Consecutive** error/timeout run, newest-first, reset on the first `status="success"` | Matches the observed consecutive-timeout incident; the ledger is ts-ordered.                                         |
| Reset precision | **Next successful call** (not next cached allow)                                       | A cache hit emits no ledger event; exact reset needs the upstream-at-entry refactor. Slightly stale, never alarming. |
| Kinds in v1     | **timeout + subprocess error only**                                                    | parse logs as `status="success"`; auth emits no event. Both deferred (need the entry-wrap).                          |
| Glyph           | **ASCII `!`**                                                                          | No unicode warning glyph; survives normalize-text; golden-irrelevant.                                                |
| Threshold       | **RED `>=3`, YELLOW 1-2** (confirm Phase 2)                                            | Mirrors tiered `format_spend_cap`.                                                                                   |

## Invariants (must / must-not)

- **No durable-schema change.** v1 reads existing `UsageEvent.status`/`failure_type`. MUST NOT add `failure_kind` to
  `PolicyDecision` or any field to `UsageEvent` (that is the deferred refactor).
- **Throttled + fail-open.** The read mirrors the `forge_cost` throttle; any ledger-read error returns empty health and
  never raises. `status_line()` MUST always exit 0.
- **Frontier-only.** Count `command="supervisor"` only. MUST NOT count `command="supervisor-shadow"` or `plan-check`.
- **Posture-independent suffix.** `!N <kind>` attaches to whatever posture renders (`SUP`/`SUP(susp)`/`SUP(off)`) --
  suspended/off write no new events, so prior fail-open history stays visible.
- **Allowlist == producers.** The suffix lives inside the existing `supervisor` segment; no new segment name;
  `SEGMENT_NAMES == {seg.name for seg in SEGMENTS}` holds.
- **Golden default bar unchanged.** `supervisor` stays out of `DEFAULT_ORDER`; `format_supervisor` with no failures
  (`recent_failures==0`) is byte-identical to today.
- **Zero I/O when inactive.** The throttled read happens only when the `supervisor` segment is active.

## Phases

### Phase 1: `read_supervisor_health` over the usage ledger (throttled, fail-open)

**Goal**: A pure reader returning the recent consecutive supervisor fail-open run from the ledger, surfaced under the
`forge_cost` throttle, never raising.

**Status (2026-06-16): Phase 1 complete.** `make pre-commit` clean (mypy/pyright/ruff/black/isort/mdformat/gitleaks).
191 passed across the five files run for Phase 1: `test_usage_summary.py`, `test_statusline_session_cost_throttle.py`,
`test_statusline_forge_segments.py`, and `test_proxy_costs.py` (the four carrying the new reader/throttle/context/reset
tests), plus `test_statusline_registry.py` (no new tests there; run to confirm the golden bar and lazy-context behavior
did not regress -- the context box below mirrors its `TestLazyContext`). The lazy-access test for the new
`supervisor_health` accessor landed in `test_statusline_forge_segments.py`, not `test_statusline_registry.py` as the
context box below anticipated. Issue #1 (reset clears `fhealth-*.json`) and the semantic cache validator
(`_valid_health_fields`, Issue #2) shipped; no durable-schema change. No visible status-line change yet -- the
`SUP!N <kind>` render is Phase 2.

- [x] `SupervisorHealth(recent_failures: int, last_kind: str | None, last_seen_at: str | None)` +
  `read_supervisor_health(session, *, since) -> SupervisorHealth`: read `command="supervisor"` events newest-first,
  count the contiguous `status in {error, timeout}` run, break at the first `status="success"`; `last_kind` from the
  newest failure's mapped `failure_type`, `last_seen_at` its `ts`. *Verify*: unit -- 3 timeout events ->
  `recent_failures==3, last_kind=="timeout"`; append a newest `status="success"` -> `0`; a `subprocess_error` ->
  `last_kind=="error"`. *Files*: `src/forge/core/ops/usage_summary.py` (beside `sum_forge_added_cost`).
- [x] Surfaced throttled + fail-open: a thin wrapper mirroring `read_or_compute_session_cost`
  (`statusline/throttle.py`), keyed on `(forge_root, session)`; a malformed/empty ledger returns empty health, no raise.
  *Verify*: unit -- malformed shard -> empty health, no exception; cached within the TTL window. *Files*:
  `src/forge/cli/statusline/throttle.py`.
- [x] Exposed as `RenderContext.supervisor_health` (`@cached_property`, zero I/O unless the supervisor segment is
  active). *Verify*: mirror `test_statusline_registry.py::TestLazyContext` -- not accessed when supervisor inactive.
  *Files*: `src/forge/cli/statusline/context.py`.
- [x] `forge proxy costs reset` also clears the derived `fhealth-*.json` cache (Issue #1) so a wiped ledger cannot
  replay stale health until TTL: added to the table-driven `_RESET_TARGETS` (drives both the `--dry-run` preview and the
  delete loop); `design_appendix.md §A.9` now names both `fcost-`/`fhealth-` caches. *Verify*: unit -- reset removes
  `fhealth-deadbeef.json` but preserves the bare `deadbeef.json` cache-hit entry; `--dry-run` lists the
  supervisor-health cache. *Files*: `src/forge/cli/proxy_costs.py`, `docs/design_appendix.md`.

### Phase 2: render `SUP!N <kind>` (posture-preserving, golden-safe)

**Goal**: Append a colored ASCII health suffix to `format_supervisor` after the posture token, default-off, without
touching golden bars.

**Status (2026-06-16): Phase 2 complete.** `make pre-commit` clean (first pass, no auto-fix); 112 passed across
`test_statusline_forge_segments.py` (format + producer health cases), `test_statusline_registry.py` (golden
byte-identity + `test_allowlist_equals_producers`, both unchanged), and `test_statusline_session_cost_throttle.py`.
**Deviation from the approved plan**: `format_supervisor` takes the two primitives it renders (`recent_failures`,
`last_kind`) rather than a `SupervisorHealth` param. `status_line.py` has a deliberate zero-top-level-forge-import
convention (all 8+ forge imports are lazy/in-function), and the renderer needs only count + kind (not `last_seen_at`);
the producer unpacks `ctx.supervisor_health`, keeping the dataclass coupling on the forge-aware side. No new import;
render is byte-identical to the planned shape. The §A.8 supervisor-health paragraph was added.

- [x] `format_supervisor` gains optional `recent_failures`/`last_kind` (the two fields it renders, not a
  `SupervisorHealth` param -- preserves `status_line.py`'s zero-top-level-forge-import convention); when
  `recent_failures>0`, append `!N <kind>` regardless of posture (`SUP!3 timeout`, `SUP(susp)!2 timeout`,
  `SUP(off)!4 error`). YELLOW 1-2, RED `>=3` (mirror `format_spend_cap`). `recent_failures==0` byte-identical to today.
  *Verify*: `test_statusline_forge_segments.py` -- suffix + tiers on all three postures; zero failures equals current
  output. *Files*: `src/forge/cli/status_line.py`.
- [x] `_produce_supervisor` unpacks `ctx.supervisor_health` into the two render fields (no shim); all posture branches
  preserved. *Verify*: producer test -- `policy.enabled` + 3 ledger timeouts -> `SUP!3 timeout` (seeded end-to-end);
  disabled -> `SUP(off)` + suffix; suspended-via-override -> `SUP(susp)` + suffix. *Files*:
  `src/forge/cli/statusline/registry.py`.
- [x] Golden default bar unchanged + render fail-open: golden snapshots pass; a raising reader degrades to
  **posture-only** (no suffix), NOT a dropped segment -- the posture is manifest-derived, only the suffix is
  ledger-derived (corrects the plan's "segment omitted"; that is `forge_cost`'s behavior, whose whole value is
  ledger-derived). *Verify*: `test_statusline_registry.py::TestGoldenNoOpGuard` + `test_allowlist_equals_producers`
  unchanged; `test_raising_reader_degrades_to_posture_only` -- posture present, no `!`. *Files*:
  `tests/src/cli/test_statusline_forge_segments.py`, `tests/src/cli/test_statusline_registry.py`.

**Design-doc updates**: status-line segment reference (`design_appendix.md §A.8`) -- describe the `SUP!N <kind>` suffix,
posture preservation, ASCII `!`, yellow/red tiers, and the ledger source.

### Phase 3: `forge activity` failing-open line + end-user doc + closeout

**Status (2026-06-16): Phase 3 complete.** `make pre-commit` clean (mdformat auto-fixed doc prose, second pass clean);
79 `test_usage_summary.py`/`test_activity.py` + 112 status-line tests green. **Deviations from the approved plan, both
from the branch review:** (1) the breakdown field is the generic neutral `error_kinds` (sibling to `errors`), populated
uniformly in `_aggregate_ledger` with no `command == "supervisor"` branch -- "failing open" is the supervisor
formatter's interpretation only, so memory-writer/panel rows carry a generic breakdown in `--json` but are never
mislabeled; (2) `format_failing_open` is gated on `error_kinds`, and `render_summary_line` keeps an explicit local
fallback to the legacy `"{errors} errors"`, which means the three pre-existing hand-built `TestRenderLine` tests stay
green **unchanged** (no churn, the opposite of the draft's "update existing tests"). Docs also call out the
streak-vs-window semantic gap (review point 3).

- [x] `forge activity` Supervisor render appends `failing open: N timeout, N error` from the existing ledger
  `failure_type` (no new field); `--json` includes the per-kind counts as generic `commands[*].error_kinds`. *Verify*:
  `test_activity.py::test_human_render_shows_failing_open` + `test_json_includes_error_kinds`;
  `test_usage_summary.py::TestLedgerPlane::test_error_kinds_breakdown`, `TestFailureKind`, and `TestRenderLine`
  failing-open + fallback cases. *Files*: `src/forge/cli/activity.py`, `src/forge/core/ops/usage_summary.py`.
- [x] `docs/end-user/session.md`: note after the `forge activity` description -- `SUP!N timeout` means recent frontier
  checks are failing open, pointing to `forge activity <session>`, explicit that `SUP!N` is the consecutive streak vs
  the window aggregate; session-end example updated. Plus `policy.md` cross-reference and `design_appendix.md §A.13`.
  *Files*: `docs/end-user/session.md`, `docs/end-user/policy.md`, `docs/design_appendix.md`.
- [x] `make pre-commit` clean; `change_log.md` feature-completion entry; durable lessons promoted to `impl_notes.md`.
  The deferred kinds (parse/auth), exact reset, and the decision-log/upstream path are recorded in
  `upstream_downstream_ledgers` -- not lost. *Files*: `docs/board/change_log.md`, `docs/board/impl_notes.md`.
- [ ] **Lane move `doing/ -> done/` pending merge to `main`** (repo convention: the move is gated on the final merge,
  per the `codex_frontend` closeout). Perform
  `git mv docs/board/doing/supervisor_statusline_health docs/board/done/supervisor_statusline_health` immediately after
  this branch lands on `main`.

## Acceptance test table

| Test                       | Fixture                                                              | Assertion                                                       | Test File                                         |
| -------------------------- | -------------------------------------------------------------------- | --------------------------------------------------------------- | ------------------------------------------------- |
| Timeout visible with count | session ledger w/ 3 `command="supervisor"` `status="timeout"` events | supervisor segment renders `SUP` + `!3 timeout`                 | `tests/src/cli/test_statusline_forge_segments.py` |
| Consecutive count          | 3 contiguous supervisor error/timeout events                         | `recent_failures==3`, `last_kind=="timeout"`                    | `tests/src/cli/test_statusline_forge_segments.py` |
| Success resets streak      | 3 failures then a newest `status="success"` supervisor event         | `recent_failures==0`                                            | `tests/src/cli/test_statusline_forge_segments.py` |
| Posture preserved + suffix | `policy.enabled=False` / `suspended=True` + ledger failures          | `SUP(off)`/`SUP(susp)` renders WITH the suffix                  | `tests/src/cli/test_statusline_forge_segments.py` |
| Shadow excluded            | only `command="supervisor-shadow"` events                            | no suffix (frontier-only)                                       | `tests/src/cli/test_statusline_forge_segments.py` |
| Status-line fail-open      | malformed ledger shard                                               | empty health, `status_line()` exits 0, no suffix                | `tests/src/cli/test_statusline_registry.py`       |
| Golden default unchanged   | default segments (no failures)                                       | `supervisor` absent from `DEFAULT_ORDER`; golden byte-identical | `tests/src/cli/test_statusline_registry.py`       |
| Activity failing-open line | session ledger w/ 2 timeout + 1 subprocess_error supervisor events   | `forge activity` shows `failing open: 2 timeout, 1 error`       | `tests/src/cli/test_activity.py`                  |

## Deferred to `upstream_downstream_ledgers` (proposed)

- **parse** fail-opens (ledger logs them `status="success"`) and **auth/proxy-not-found** fail-opens (emit no ledger
  event) -- both need the upstream-at-verb-entry emit.
- **Exact cached-allow reset** (reset on next cached allow, not next call) -- needs no-call outcome records.
- **Structured `failure_kind` on `PolicyDecision`** -- the original v1 design; off-model (policy side-channel),
  superseded by a first-class upstream ledger.

## Provenance

Re-cut 2026-06-16 from a first-principles dialogue (this card's investigation): the supervisor timeout is already in the
usage ledger and the status line already reads the ledger, so the minimal marker needs no new durable state. The heavier
decision-log design and the clean two-ledger model are captured in `upstream_downstream_ledgers`.
