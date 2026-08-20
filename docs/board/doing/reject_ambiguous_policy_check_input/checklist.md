# Reject ambiguous policy-check input checklist

Current focus: queued second in Wave 8 Batch 3 on `agent/wave8-batch-3` from pushed closeout `34cbb601`; O080 executes
first on the shared terminal policy CLI.

## Phase 1 -- Pin ambiguous input

- [x] Recheck current `main`: `policy check --file PATH --diff` enters the diff branch, ignores file bytes, and still
  records the ignored file path in tool arguments.
- [x] Add fail-first long- and short-file-selector regressions proving the conflict exits 2 before stdin or file reads.
- [x] Preserve missing-selector, file-only, diff-only, JSON, fail-mode, target extraction, and evaluation controls.

## Phase 2 -- Implement and document

- [x] Reject simultaneous `--file`/`-f` and `--diff` selectors with a Click usage error at the command boundary.
- [x] Document that exactly one content source is required without changing either successful input path or output
  schema.

## Phase 3 -- Verify and publish

- [x] Run focused policy-check/output/regression tests.
- [ ] Run targeted policy integration on the integrated Batch 3 head.
- [x] Commit this card after O080 and before the vocabulary follow-up.
- [ ] Run the combined unit, regression, pre-commit, documentation, board/link, and diff gates on the integrated Batch 3
  head.
- [ ] Publish all three cards in one Batch 3 PR; close them together only after merge.

## Acceptance tests

| Boundary          | Fixture                              | Assertion                                           | Tier           |
| ----------------- | ------------------------------------ | --------------------------------------------------- | -------------- |
| Long conflict     | `--file PATH --diff`                 | usage error, exit 2, no file/stdin read             | CLI regression |
| Short conflict    | `-f PATH --diff`                     | identical no-read failure                           | CLI regression |
| Missing source    | neither selector                     | existing exit-2 diagnostic remains                  | existing unit  |
| File only         | readable file                        | Write context and file-relative target remain       | existing unit  |
| Diff only         | unified diff on stdin                | Edit context, extracted target, and raw diff remain | existing unit  |
| Output/evaluation | human/JSON and open/closed fail mode | existing result schemas and policy decisions remain | existing unit  |

## Focused evidence (2026-08-21)

- Fail first: `uv run pytest tests/regression/test_bug_o077_ambiguous_policy_check_input.py -q --tb=short` reported the
  long and short conflicts returning zero after consuming stdin (`2 failed`).
- Final: the policy-check, O077 regression, and output-stream files passed (`67 passed`).
- Focused Ruff passed for the changed source and regression; repository-pinned format and Markdown hooks run before the
  card commit.
