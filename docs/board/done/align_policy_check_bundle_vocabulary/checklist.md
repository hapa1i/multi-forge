# Align policy-check bundle vocabulary checklist

Current focus: complete -- implementation commit `5ee6a6dc` shipped in Batch 3 PR #227 (`f3353042`).

## Phase 1 -- Pin the corrected residue

- [x] Recheck current `main`: one terminal Click choice and two direct-command membership checks still hard-code the
  bundle names; the accepted card's earlier one-line/direct-parser evidence was stale.
- [x] Add fail-first coverage that the terminal check option owns the shared Click choice and direct flag/positional
  parsing follows a temporarily extended shared vocabulary.
- [x] Preserve current syntax, defaults, output, fail modes, and evaluation behavior for shipped bundles.

## Phase 2 -- Implement

- [x] Replace only the three literal vocabulary sites with `_POLICY_BUNDLE_CHOICES` or `policy_ops.POLICY_BUNDLE_NAMES`;
  do not add a shared evaluation operation.
- [x] Keep terminal and direct parsing behavior otherwise unchanged.

## Phase 3 -- Verify and publish

- [x] Run focused terminal/direct policy-check tests and regression coverage.
- [x] Commit this card after O080 and O077 without mixing shared documentation or board reconciliation.
- [x] Run the combined unit, regression, targeted policy integration, pre-commit, documentation, board/link, and diff
  gates on the integrated Batch 3 head.
- [x] Publish all three cards in draft PR #227; close them together only after merge.
- [x] Confirm all five GitHub checks, merge Batch 3 as `f3353042`, and close all three cards together.

## Acceptance tests

| Boundary          | Fixture                                       | Assertion                                            | Tier            |
| ----------------- | --------------------------------------------- | ---------------------------------------------------- | --------------- |
| Terminal choice   | registered terminal `check` command           | bundle option uses `_POLICY_BUNDLE_CHOICES`          | regression      |
| Direct flag       | temporary shared bundle and empty Git diff    | `--bundle <name>` is recognized before evaluation    | hook regression |
| Direct positional | same temporary bundle, positional spelling    | name is recognized before evaluation                 | hook regression |
| Shipped bundles   | tdd/coding-standards terminal and direct uses | existing help, parsing, and evaluation remain intact | existing unit   |

## Focused evidence (2026-08-21)

- Fail first: the new vocabulary regression reported all three residual literals (`3 failed`): the terminal option owned
  a distinct Click choice and neither direct spelling recognized the temporary shared bundle.
- Final: terminal/direct policy-check, vocabulary regression, and output-stream files passed (`170 passed`).
- Focused Ruff passed for both changed sources and the regression; repository-pinned format and type hooks run before
  the card commit.
- Integrated: the containerized `%policy check --bundle tdd` command reached the clean Git-diff result; full unit,
  regression, and pre-commit gates passed on the combined head.
