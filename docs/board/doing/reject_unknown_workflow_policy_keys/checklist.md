# Reject unknown workflow-policy keys checklist

Current focus: implementation and verification are complete; publish order 7 while orders 8--19 remain parked.

## Phase 1 -- Characterize and activate

- [x] Branch from pushed corrective closeout `071cfd92`; move only Wave 8 order 7 to `doing/` and repoint its inbound
  board links.
- [x] Recheck `_build_workflow_policies`: its unconfigured `dacite.from_dict` still discards `tagger_promt` and leaves
  `tagger_prompt=""` on the resulting policy.
- [x] Add fail-first top-level and nested unknown-key regressions plus a valid/defaulted control: the baseline produced
  four expected failures and one passing control.
- [x] Pin malformed workflow entry/type failures as actionable `ValueError`s, and verify the real hook boundary reports
  them without a raw traceback or LLM dispatch.

## Phase 2 -- Implement

- [x] Deserialize every workflow entry and nested workflow dataclass with strict unknown-key validation.
- [x] Translate deserialization failures into an actionable `ValueError` that names the workflow entry and offending
  field while preserving lazy workflow imports.
- [x] Preserve valid/defaulted configuration, workflow order, policy construction, and evaluation behavior.
- [x] Document the strict manifest boundary in the workflow design and end-user policy guide.

## Phase 3 -- Verify and publish

- [x] Run the deterministic/workflow policy slice and the O083 regression: 128 passed.
- [x] Run the new unknown-key and unchanged TDD policy-hook Docker checks: two passed.
- [x] Run 9,328 unit tests with zero skips and 124 deselected, 969 regressions, full pre-commit, the 59,979-token
  design/appendix and 17,920-token workflow design checks, the 403-document/976-link board check, and diff checks.
- [ ] Commit and push one reviewable implementation, then open one draft PR without activating Wave 8 order 8.

## Acceptance tests

| Boundary              | Fixture                                      | Assertion                                                               | Tier        |
| --------------------- | -------------------------------------------- | ----------------------------------------------------------------------- | ----------- |
| Top-level workflow    | valid entry with `tagger_promt`              | fails closed and names the entry plus unknown field                     | regression  |
| Nested workflow       | checker/reviewer entry with a misspelled key | fails closed and names the nested offending field                       | regression  |
| Malformed entry       | invalid workflow field or entry type         | actionable policy-config error reaches the existing caller boundary     | unit        |
| Valid/defaulted entry | multiple valid workflows with omitted fields | preserves order, defaults, policy IDs, and lazy workflow-module loading | unit        |
| Policy hook           | manifest-backed workflow bundle              | open-mode build failure is actionable without traceback or LLM dispatch | integration |
