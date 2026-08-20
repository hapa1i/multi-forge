# Reject unknown workflow-policy keys checklist

Current focus: complete -- O083 shipped independently in PR #223 and Wave 8 order 7 is closed.

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
- [x] Commit and push the implementation as `47554574`, then open draft PR #223 without activating Wave 8 order 8.
- [x] Merge PR #223 as `92d71a6d`, synchronize the final board evidence, and move this member to `done/` before
  activating order 8.

## Review follow-up

- [x] Qualify `get_bundle_policies` documentation to distinguish strict workflow parsing from TDD's narrower value
  validation, and record the verified TDD unknown-key gap separately as parked O101.
- [x] Record the pre-existing atomic-build tradeoff: construction errors diagnose and allow before engine-owned
  `fail_mode`, without evaluating a partial policy set.
- [x] Align workflow dataclass-shape tests with the strict `dacite` configuration used by production.
- [x] Rerun the focused review slice (25 passed), Markdown hooks, full pre-commit, and diff checks.

## Acceptance tests

| Boundary              | Fixture                                      | Assertion                                                               | Tier        |
| --------------------- | -------------------------------------------- | ----------------------------------------------------------------------- | ----------- |
| Top-level workflow    | valid entry with `tagger_promt`              | construction rejects and names the entry plus unknown field             | regression  |
| Nested workflow       | checker/reviewer entry with a misspelled key | construction rejects and names the nested offending field               | regression  |
| Malformed entry       | invalid workflow field or entry type         | actionable policy-config error reaches the existing caller boundary     | unit        |
| Valid/defaulted entry | multiple valid workflows with omitted fields | preserves order, defaults, policy IDs, and lazy workflow-module loading | unit        |
| Policy hook           | manifest-backed workflow bundle              | open-mode build failure is actionable without traceback or LLM dispatch | integration |
