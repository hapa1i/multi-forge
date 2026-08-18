# Centralize tolerant telemetry JSONL reads

**Epic**: [`epic_wave7_refactor_and_deletion`](../../doing/epic_wave7_refactor_and_deletion/card.md).

**Lane**: `doing/` -- active on `refactor/centralize-telemetry-jsonl-reads` from the order-25 closeout (`83394417`).

**Finding**: O056.

**Depends on**: [`centralize_time_parsing_and_periods`](../../done/centralize_time_parsing_and_periods/card.md).

## Goal

Share the line/read/timestamp/newer-schema scaffold across usage, downstream, and upstream telemetry while retaining
each plane's schema and failure policy.

## Evidence and Authority

Reverified on `83394417`: all three readers still repeat sorted shard iteration, object-line decoding, timestamp
matching, and read-error handling; only append I/O is shared in `core/telemetry/jsonl_io.py`. Usage and upstream apply
schema fences before value/period filters, while downstream deliberately scopes kind/period before its schema counters.
The focused read/write/schema baseline is 65 passing tests. Authority:
[`docs/design_appendix.md` "A.13 Usage-attribution ledger schema"](../../../design_appendix.md#a13-usage-attribution-ledger-schema-314)
and
[`docs/developer/coding_standards.md` "System boundaries"](../../../developer/coding_standards.md#system-boundaries-external-data).

## Acceptance Criteria

- A generic iterator owns file/line/timestamp mechanics and yields enough context for each plane's typed decoder.
- Plane-specific schema versions, warnings, counters, retention, malformed-line tolerance, and newer-schema outcome stay
  separately asserted.
- Run JSONL I/O plus full usage/downstream/upstream unit and regression suites; run targeted telemetry integration where
  append/read interaction changes.

## Exclusions

Do not create one shared telemetry record schema, change JSONL bytes, collapse plane retention, or downgrade newer-state
failures. Keep `CostTracker.bootstrap_from_logs` separate: cap bootstrap skips irrelevant month shards before opening
them and deduplicates `downstream_event_id` records.
