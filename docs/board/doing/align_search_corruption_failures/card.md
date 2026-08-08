# Align search corruption failures

**Epic**: [`epic_cli_proxy_runtime_correctness`](../epic_cli_proxy_runtime_correctness/card.md).

**Finding**: D017 (HIGH) in [`review_combined.md`](../../review_combined.md#design-conformance-findings).

**Lane**: `doing/` -- active on `fix/align-search-corruption-failures` from merged PR #150 (`61580fdb`).

## Goal

Make search-index corruption produce the same actionable non-zero failure in `query` and `status`, in both human and
JSON modes.

## Design Authority

- [`cli_style_guidelines.md` failure/output rules](../../../developer/cli_style_guidelines.md#output-streams): failures
  use stderr and non-zero status without polluting the result stream.
- [`coding_standards.md` §5](../../../developer/coding_standards.md#5-interface-changes): absent, unreadable, and
  corrupt durable state are distinct outcomes.

## Evidence

Rechecked on merged `main` at `61580fdb` with a valid empty document store and malformed BM25 file. The retained
four-case regression failed for query human, query JSON, and status human because each exited 0; status JSON was the
only passing case because it already emitted one stderr object and exited 1.

## Expected Behavior

- Corruption exits non-zero for query/status and human/JSON output.
- JSON failure is one object on stderr with empty stdout; human failure uses the shared error/tip path on stderr.
- Not-built indexes, empty results, and successful reads remain exit-0 outcomes.

## Acceptance Criteria

- Add a marked D017 regression covering the four corrupt command/mode combinations.
- Cover document, BM25, and index-state corruption without conflating unreadable or missing state.
- Extend CLI stream assertions and run focused search/CLI tests, the regression suite, and `make pre-commit`.

## Compatibility and Exclusions

- Do not change `--scope all` partial-result policy without separate evidence.
- Do not rebuild or delete corrupt state automatically; keep the explicit `search rebuild-index` recovery action.
- Keep query's unreadable-state stream/exit mismatch separate as D051; inability to read bytes is not known corruption.
- Keep `search clean`'s generic human corruption guidance separate as D052; this member owns query/status recovery only.
