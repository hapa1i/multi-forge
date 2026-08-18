# Centralize tolerant telemetry JSONL reads checklist

Current focus: order 26 is active on `refactor/centralize-telemetry-jsonl-reads` from the order-25 closeout
(`83394417`); keep orders 27--35 parked.

## Activation and evidence

- [x] Close order 25 on pushed `main` at `83394417`, create the execution branch from that exact commit, and move only
  this member to `doing/`.
- [x] Re-run source, caller, import, and test searches for the usage, downstream, upstream, and shared JSONL surfaces.
- [x] Confirm all three typed readers repeat shard/object/timestamp/error mechanics while retaining different schema and
  filter ordering.
- [x] Record the focused JSONL/usage/downstream/upstream baseline before implementation (65 passed).

## Implementation

- [x] Add one shared iterator for sorted shard reads, object-line decoding, source-path context, and read failures.
- [x] Put naive-as-UTC period matching on the yielded record context so each plane retains its current policy order.
- [x] Route usage, downstream, and upstream through the shared scaffold without changing typed decoders, schema
  versions, warnings, counters, merging, sorting, or retention.
- [x] Record the shared read ownership in the normative telemetry design while staying below its size limit.

## Acceptance tests

| Test                     | Fixture                                                              | Assertion                                                                  | Test file                                     |
| ------------------------ | -------------------------------------------------------------------- | -------------------------------------------------------------------------- | --------------------------------------------- |
| Shared shard reader      | sorted shards plus blank, malformed, and non-object lines            | yields only object records with source paths in shard/line order           | `tests/src/core/telemetry/test_jsonl_io.py`   |
| Shared period matcher    | zoned, naive, malformed, before, in-window, and end-bound timestamps | retains naive-as-UTC and half-open bounds without eager policy reordering  | `tests/src/core/telemetry/test_jsonl_io.py`   |
| Usage schema policy      | newer record excluded by value/period filters                        | skips and warns before those filters, with strict typed decoding unchanged | `tests/src/core/usage/test_ledger.py`         |
| Downstream schema policy | old/new records across kind and period filters                       | counters and one-time warnings remain scoped by kind/period                | `tests/src/core/telemetry/test_downstream.py` |
| Upstream schema policy   | current, newer, malformed, and filtered outcomes                     | retains one-time newer warning, strict decoding, and typed filters         | `tests/src/core/telemetry/test_upstream.py`   |

## Verification and closeout

- [x] Run focused JSONL, usage, downstream, upstream, and telemetry regression tests (73 focused and 168 expanded tests
  pass).
- [x] Run the full unit (9,230 passed, one skipped), regression (921 passed), and targeted Docker telemetry append/read
  (five passed) suites.
- [x] Run full pre-commit, `git diff --check`, design-size checks (29,978 and 29,990 tokens), and the board audit (360
  documents, 882 local links, zero missing; 25 done / one doing / nine todo) without a Forge workflow.
- [x] Commit and push order 26 for review without activating order 27.
