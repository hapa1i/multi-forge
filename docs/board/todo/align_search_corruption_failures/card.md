# Align search corruption failures

**Epic**: [`epic_cli_proxy_runtime_correctness`](../epic_cli_proxy_runtime_correctness/card.md).

**Finding**: D017 (HIGH) in [`review_combined.md`](../../review_combined.md#design-conformance-findings).

**Lane**: `todo/` -- accepted Wave 5 member, parked behind the proxy create JSON member.

## Goal

Make search-index corruption produce the same actionable non-zero failure in `query` and `status`, in both human and
JSON modes.

## Design Authority

- [`cli_style_guidelines.md` failure/output rules](../../../developer/cli_style_guidelines.md#output-streams): failures
  use stderr and non-zero status without polluting the result stream.
- [`coding_standards.md` §5](../../../developer/coding_standards.md#5-interface-changes): absent, unreadable, and
  corrupt durable state are distinct outcomes.

## Evidence

Rechecked on `3f3a3c6d` with malformed BM25 and document-store files. `search query` exited 0 in JSON and human modes;
`search status` exited 1 only in JSON mode and exited 0 in human mode.

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
