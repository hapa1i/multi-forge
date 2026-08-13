# Harden command and state boundaries checklist

Current focus: complete -- shipped in PR #175 (`967d9cae`); the remaining two Wave 6 members stayed parked through
merge.

## Phase 1: Activation and evidence

- [x] Close PR #174 bookkeeping on local `main` at `e7ee8f15`.
- [x] Create `agent/harden-command-state-boundaries`, move this member to `doing/`, and repoint inbound board links.
- [x] Recheck each finding against current source and existing tests; retain D034/D037/D038 and narrow O027's
  downstream-impact claim while retaining the live helper defect.
- [x] Run the retained regression slice before production changes (`21 failed, 5 passed` on production code at
  `095fcd90`).

## Phase 2: Shared boundary corrections

- [x] Make the five no-session direct-command handlers exit 0 without emitting hook output; preserve block payloads.
- [x] Apply the reserved-basename guard to every passport create and update path before any write.
- [x] Reject wrong search container and element types with store-specific corruption and rebuild guidance.
- [x] Unwrap only actual `Union[T, None]` annotations while preserving generic container types and override semantics.

## Acceptance tests

| Finding | Fixture                                            | Assertion                                                                  | Test file                                                            |
| ------- | -------------------------------------------------- | -------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| D034    | bare project, each of the five cited `%` commands  | hook exits 0 and emits no output                                           | `tests/regression/test_bug_d034_direct_command_no_session_output.py` |
| D037    | hand-authored passport at reserved `docs/index.md` | re-track is rejected before write and bytes stay unchanged                 | `tests/regression/test_bug_d037_passport_reserved_update.py`         |
| D038    | search files with wrong container or element types | readers raise store-specific corruption and the CLI gives rebuild guidance | `tests/regression/test_bug_d038_search_store_shape_validation.py`    |
| O027    | generic containers and real Optional annotations   | containers remain intact; only `Union[T, None]` unwraps                    | `tests/regression/test_bug_o027_optional_unwrap_union.py`            |

## Verification and closeout

- [x] Run focused hook, passport, search, override, and regression tests (`681 passed`; the final retained finding slice
  passed `28` tests, and the post-review passport slice passed `370`).
- [x] Run the targeted search and prompt-dispatcher Docker integration tests (`24 passed`).
- [x] Run the full regression (`872 passed`) and unit (`9004 passed, 1 skipped, 122 deselected`) suites.
- [x] Run `make pre-commit` after the final code and documentation diff (all hooks passed after the expected formatter
  normalization pass).
- [x] Synchronize the CLI reference, normative workflow design, and end-user memory guide for reserved passport
  mutations; no other architecture or file ownership changed.
- [x] Run final board integrity and diff checks (10 changed Markdown files, 2 added local links, no missing targets,
  Wave 6 member graph at 10 done / 1 doing / 2 todo, no stale todo link, and a clean diff check).
- [x] Resolve review feedback by adding rebuild guidance to the BM25 scalar-conversion fallback; retain and document the
  intentional `%plan` / `%policy check` informative-block asymmetry outside D034's five silent no-op handlers.
- [x] Record verification in `docs/board/change_log.md`, update epic counts and links, and move this card to `done/`.
- [x] Review and merge this member independently in PR #175 (`967d9cae`) before activating the next ordered Wave 6
  member.

No later member was activated before this member merged.
