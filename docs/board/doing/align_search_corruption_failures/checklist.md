# Align search corruption failures checklist

Current focus: resolve independent review and rerun the amended verification gates before PR publication.

## Activation and reproduction

- [x] Start `fix/align-search-corruption-failures` from merged PR #150 at `61580fdb`.
- [x] Close D016, move D017 from `todo/` to `doing/`, and advance the Wave 5 cursors without activating O001.
- [x] Add a marked D017 regression covering query/status in human/JSON modes against one malformed BM25 fixture.
- [x] Confirm the retained regression fails on `61580fdb`: query human/JSON and status human exit 0, while status JSON
  is the sole passing case.

## Corruption failure contract

- [x] Route project-scoped query and status corruption through one stderr-only failure renderer.
- [x] Emit one JSON error object on stderr with empty stdout and exit 1 in both JSON leaves.
- [x] Use the shared human error/tip path on stderr with empty stdout and exit 1 in both human leaves.
- [x] Read all status stores before rendering successful statistics so late BM25 corruption cannot leak partial stdout.

## Compatibility coverage

- [x] Preserve not-built indexes, empty results, and valid reads as exit-0 outcomes.
- [x] Leave `--scope all` partial-result skip behavior unchanged.
- [x] Keep unreadable-state exception classes and recovery guidance distinct from known corruption.
- [x] Keep recovery explicit through `search rebuild-index`; do not rewrite, delete, or rebuild during query/status.

## Acceptance tests

| Test                         | Fixture                                      | Assertion                                                    |
| ---------------------------- | -------------------------------------------- | ------------------------------------------------------------ |
| Four-way retained regression | malformed BM25; query/status; human/JSON     | every mode uses stderr, empty stdout, and exit 1             |
| Store classification         | malformed documents, BM25, and index state   | each corruption type names rebuild recovery                  |
| JSON stream guard            | corrupt query and status read leaves         | exactly one parseable stderr object; no stdout               |
| Human stream guard           | corrupt query and status read leaves         | shared error/tip on stderr; no partial result                |
| Successful controls          | missing index, empty result, valid stores    | existing exit-0 result shapes remain unchanged               |
| Scope-all control            | one corrupt/unreadable project among results | existing skip-and-continue partial-result policy is retained |

## Verification and closeout

- [x] Run the amended search, output-stream, unreadable-state, and D017 regression slice: 92 passed.
- [x] Run focused Ruff after the review amendments: passed.
- [x] Synchronize CLI/operator/QA docs only with shipped behavior; QA now contains 622 assertions and the change log
  measures 20,817 tokens / 1,398 physical lines.
- [x] Run the full unit and marked regression suites: 8,905 passed / 1 skipped and 690 passed, respectively.
- [x] Build the wheel and sdist, then verify both changed bundled QA resources in the wheel.
- [x] Run final `make pre-commit`, resolve all 153 changed-document links/fragments, and pass stale-lane and diff
  checks.
- [x] Receive independent review and resolve its mechanical, coverage, and documentation findings below.
- [x] Add the missing corrupt `--scope all` control and correct the stale error-helper default in the CLI style guide.
- [x] Admit the separate unreadable-query and clean-recovery inconsistencies as D051 and D052 without expanding D017.
- [x] Rerun amended focused/full tests, Markdown links, formatting, and repository-quality gates.
- [ ] Merge before activating O001.
