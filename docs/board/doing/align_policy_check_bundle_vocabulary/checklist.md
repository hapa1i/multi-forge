# Align policy-check bundle vocabulary checklist

Current focus: queued last in Wave 8 Batch 3 on `agent/wave8-batch-3` from pushed closeout `34cbb601`; O080 and O077
execute first on the shared terminal policy CLI.

## Phase 1 -- Pin the corrected residue

- [x] Recheck current `main`: one terminal Click choice and two direct-command membership checks still hard-code the
  bundle names; the accepted card's earlier one-line/direct-parser evidence was stale.
- [ ] Add fail-first coverage that the terminal check option owns the shared Click choice and direct flag/positional
  parsing follows a temporarily extended shared vocabulary.
- [ ] Preserve current syntax, defaults, output, fail modes, and evaluation behavior for shipped bundles.

## Phase 2 -- Implement

- [ ] Replace only the three literal vocabulary sites with `_POLICY_BUNDLE_CHOICES` or `policy_ops.POLICY_BUNDLE_NAMES`;
  do not add a shared evaluation operation.
- [ ] Keep terminal and direct parsing behavior otherwise unchanged.

## Phase 3 -- Verify and publish

- [ ] Run focused terminal/direct policy-check tests and regression coverage.
- [ ] Commit this card after O080 and O077 without mixing shared documentation or board reconciliation.
- [ ] Run the combined unit, regression, targeted policy integration, pre-commit, documentation, board/link, and diff
  gates on the integrated Batch 3 head.
- [ ] Publish all three cards in one Batch 3 PR; close them together only after merge.

## Acceptance tests

| Boundary          | Fixture                                       | Assertion                                            | Tier            |
| ----------------- | --------------------------------------------- | ---------------------------------------------------- | --------------- |
| Terminal choice   | registered terminal `check` command           | bundle option uses `_POLICY_BUNDLE_CHOICES`          | regression      |
| Direct flag       | temporary shared bundle and empty Git diff    | `--bundle <name>` is recognized before evaluation    | hook regression |
| Direct positional | same temporary bundle, positional spelling    | name is recognized before evaluation                 | hook regression |
| Shipped bundles   | tdd/coding-standards terminal and direct uses | existing help, parsing, and evaluation remain intact | existing unit   |
