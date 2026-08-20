# Preserve assistant block boundaries checklist

Current focus: characterize and correct O087 on active Wave 8 order 8; orders 9--19 remain parked.

## Phase 1 -- Characterize and activate

- [x] Branch from pushed order-7 closeout `d196b866`; move only Wave 8 order 8 to `doing/` and repoint its inbound board
  links.
- [x] Recheck both transcript projections on current `main`: each filters non-empty assistant text blocks and joins them
  with `""`, collapsing a later block into the prior block when neither supplies a newline.
- [x] Add fail-first regressions for the collapsed-boundary case in both supported transcript projections, plus negative
  substring and unchanged-shape controls: four expected failures and ten passing controls on the activation baseline.

## Phase 2 -- Implement

- [x] Preserve exactly one needed line boundary between adjacent assistant text blocks without changing single-block
  content or adding a separator when either side already supplies one.
- [x] Share the boundary rule across both transcript projections while keeping message selection, timestamp ordering,
  malformed-entry handling, and non-text filtering unchanged.
- [x] Update the durable Stop-verification contract to state how separate assistant blocks compose without weakening the
  standalone-line rule.

## Phase 3 -- Verify and publish

- [x] Run the focused helper/Stop and adjacent verification slice: 77 passed, including all 14 O087 regressions.
- [x] Run two targeted Docker Stop-hook checks, 9,328 unit tests with 124 deselected and zero skips, 983 regressions,
  full changed-file and repository pre-commit, the 59,979-token design/appendix and 18,052-token workflow design checks,
  the 404-document/977-link board check, and diff hygiene.
- [x] Commit and push the implementation as `e4d184fa`, then open draft PR #224 without activating Wave 8 order 9.
- [ ] Merge PR #224 and retain this card in `doing/` until its closeout lands on `main`.

## Acceptance tests

| Boundary                     | Fixture                                                   | Assertion                                                            | Tier        |
| ---------------------------- | --------------------------------------------------------- | -------------------------------------------------------------------- | ----------- |
| Newer transcript projection  | prior block lacks newline; next block is exact promise    | extracted text keeps a line break and completion verification passes | regression  |
| Legacy transcript projection | prior block lacks newline; next block is exact promise    | extracted text keeps a line break and completion verification passes | regression  |
| Standalone guard             | promise is only a substring or split across text blocks   | completion verification remains incomplete                           | regression  |
| Compatibility                | single block or an existing boundary on either block edge | extracted content is unchanged                                       | unit        |
| Stop hook                    | manifest-backed completion promise across content blocks  | real hook allows Stop and records `passed`                           | integration |
