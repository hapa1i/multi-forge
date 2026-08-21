# Preserve Codex plus-prefixed Write identity

**Epic**: [`epic_repo_maintenance_round`](../epic_repo_maintenance_round/card.md).

**Finding**: corrective follow-up to D005 (HIGH) in
[`review_combined.md`](../../review_combined.md#design-conformance-findings).

**Related shipped member**: [`preserve_supervisor_edit_identity`](../preserve_supervisor_edit_identity/card.md).

**Lane**: `done/` -- implemented and verified on `fix/codex-plus-prefixed-write-identity`; review and merge remain the
parent epic's gate before Wave 2 begins.

## Goal

Preserve valid Codex `Add File` and `Update File` content whose source line begins with `++`, so complete Write content
reaches deterministic policy evaluation and materially different actions receive distinct semantic cache identities.

## Design Authority

- [`docs/design_workflows.md` §1.2](../../../design_workflows.md#12-semantic-policy-the-supervisor): only identical
  diffs may reuse an aligned supervisor result, and a Write fingerprint covers the full content.
- The Codex apply-patch grammar in `src/forge/cli/hooks/codex_patch.py` defines each body line's first `+` as transport
  syntax. The shared `extract_added_lines` contract remains unified-diff-specific and must continue to ignore `+++` file
  headers.

## Evidence

Rechecked on merged `main` at `f1ff5ee7`:

- `_Section.finalize` passes a Codex section body to the shared unified-diff extractor, which discards every line that
  begins with `+++` as though it were a `+++ b/path` header.
- Two same-path `Add File` actions carrying `+++first` and `+++second` transport lines both normalize to empty
  `added_content`, `new_content=None`, and the same action fingerprint.
- Both the semantic supervisor and tier-1 plan checker consequently invoke their evaluator once and reuse that clean
  allow for the second, materially different Write.
- The existing unified-diff helper is correct for its own callers and has coverage requiring it to omit real `+++`
  headers; changing that shared behavior would conflate two grammars.

## Expected Behavior

The Codex parser strips exactly the first transport `+` from every added body line, including lines whose file content
begins with one or more plus signs. The adapter then exposes the complete content and fingerprints it before
presentation truncation. Genuine unified-diff parsing remains unchanged.

## Scope

- Add a Codex-specific added-line extractor at the apply-patch parsing boundary.
- Use it for both `Add File` and `Update File` sections while retaining verbatim update `raw_section` data.
- Add parser and adapter unit coverage plus a marked D005 regression across both semantic cache layers.
- Update the D005 ledger and shipped-member record to identify this corrective follow-up.

## Acceptance Criteria

- Codex Add and Update transport lines such as `+++first` normalize to file content `++first`.
- Same-path plus-prefixed Adds with different content have different action fingerprints and invoke both the semantic
  supervisor and plan checker independently.
- The regression lives in `tests/regression/test_bug_d005_supervisor_edit_identity.py`, retains
  `pytestmark = pytest.mark.regression`, and names this parser root cause in its module docstring.
- Existing true unified-diff header handling remains covered and unchanged.
- Focused parser/adapter/policy tests, `make test-regression`, `make test-unit`, the targeted Docker policy-hook
  integration, and `make pre-commit` pass.

## Compatibility and Exclusions

Do not change the Codex hook wire format, patch grammar validation, cache policy, fingerprint schema, multi-file
ordering, or the shared unified-diff extractor. This member does not broaden D005 into whole-file deletion behavior or
D026 shadow configuration reconstruction.

## Outcome

Codex apply-patch parsing now uses a grammar-specific extractor that removes exactly one transport `+` from every added
body line. Valid Add and Update content beginning with plus signs survives normalization; Add content reaches
deterministic policies, and its complete pre-truncation value contributes to the existing action fingerprint. Update
`raw_section` remains verbatim.

The unified-diff helper and fingerprint schema are unchanged. Same-path `+++first` and `+++second` Add transport lines
now normalize to `++first` and `++second`, receive different fingerprints, and independently invoke both semantic cache
layers.

## Verification

- Pre-fix focused regression: `5 failed`, reproducing empty parser/adapter content and cache-identity loss in both
  semantic layers.
- Focused Codex parser, adapter, policy-hook, D005 regression, and unified-diff utility suite: `76 passed`.
- `make test-regression`: `643 passed`.
- `make test-unit`: `8,712 passed, 1 skipped, 118 deselected`.
- `./scripts/test-integration.sh tests/integration/docker/test_policy_hooks.py`: `21 passed`.
- `make pre-commit`: passed after mdformat's first-pass mechanical edits.
