# Share review worker preparation helpers checklist

Current focus: complete -- order 27 shipped in PR #206 (`242ded2d`); orders 28--35 remain parked.

## Activation and evidence

- [x] Close order 26 on pushed `main` at `8787f7e7`, create the execution branch from that exact commit, and move only
  this member to `doing/`.
- [x] Re-run source, caller, import, and test searches for review resource loading, worker preparation, CLI parsing, and
  optional JSON metadata.
- [x] Confirm consensus and adversarial retain distinct routing, fan-out, prompts, verdicts, and result types.
- [x] Record the focused consensus/adversarial/CLI baseline before implementation (214 passed).

## Implementation

- [x] Add typed pure helpers for marker validation/fill, stable worker IDs and labels, and common worker assignment
  parsing.
- [x] Route consensus and adversarial preparation through the shared boundary without changing their named domain models
  or runtime semantics.
- [x] Share only the optional JSON metadata tail while preserving key order and each command's output schema.
- [x] Record the shared ownership in normative design documentation within its size limit.

## Acceptance tests

| Test                     | Fixture                                            | Assertion                                                                     | Test file                                     |
| ------------------------ | -------------------------------------------------- | ----------------------------------------------------------------------------- | --------------------------------------------- |
| Resource validation      | role/stance templates with and without markers     | exact marker fill, guardrail, and noun-specific failure text                  | `tests/src/review/test_worker_preparation.py` |
| Worker preparation       | repeated model/label pairs and prefixed source     | stable suffixes, label map, copied routing fields, and current prompt mode    | `tests/src/review/test_worker_preparation.py` |
| Assignment parsing       | named/custom/quoted/empty/invalid worker arguments | exact model lookup, errors, prompts, and custom-label truncation              | `tests/src/review/test_worker_preparation.py` |
| Runner contracts         | consensus and adversarial mocked fan-out           | distinct routing, prompts, maps, and output models remain unchanged           | existing review tests                         |
| CLI output compatibility | all optional result metadata                       | resolved model, verdict, reason, and warning keys retain their existing order | existing and focused CLI tests                |

## Verification and closeout

- [x] Run focused review/CLI unit tests and expanded review tests (223 initial focused, 158 review-fix focused, and 444
  expanded tests pass).
- [x] Run the full unit (9,239 passed, one skipped), regression (921 passed), and targeted Docker workflow-worker (four
  passed) suites.
- [x] Run full pre-commit, `git diff --check`, design-size checks (29,988 and 29,990 tokens), and the board audit (361
  documents, 882 local links, zero missing; 26 done / one doing / eight todo) without a Forge workflow.
- [x] Open PR #206, merge it as `242ded2d` after all five checks pass, and close order 27 before activating order 28.
