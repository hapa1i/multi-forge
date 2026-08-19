# Offload proxy accounting persistence

**Epic**: [`epic_wave8_residual_maintenance`](../../doing/epic_wave8_residual_maintenance/card.md).

**Lane**: `todo/` -- accepted Wave 8 order 2; parked.

**Finding**: O046 (MEDIUM).

## Goal

Keep proxy request completion responsive when downstream telemetry and spend-cap checkpoints perform filesystem I/O.

## Verified Evidence

`_calc_and_log_cost` is called from async request and stream callbacks but synchronously appends downstream JSONL. Every
append can create/chmod directories and open/write a file; periodic cap persistence additionally performs an atomic
write with file and directory `fsync`. The request-audit path already uses `asyncio.to_thread`, demonstrating the
intended event-loop boundary.

## Acceptance Criteria

- Keep in-memory cost/cap totals available immediately for the completing request.
- Serialize durable downstream records and cap snapshots off the event-loop thread without reordering one proxy's
  completion evidence or racing mutable cap state.
- Flush pending accounting at controlled shutdown and retain best-effort warning behavior on write failure.
- Preserve downstream schema/event IDs, reported/unavailable cost semantics, response headers, cap decisions, and
  restart reconstruction.
- An injected slow append/atomic write must not stall an event-loop heartbeat or concurrent request completion.

## Verification

Add deterministic slow-I/O concurrency tests and shutdown-flush/failure tests. Run focused cost/cap/server tests, full
unit and regression suites, targeted Docker proxy/telemetry/cap integration, and `make pre-commit`. Update the
accounting ownership text in `docs/design_appendix.md` if the persistence mechanism changes.
