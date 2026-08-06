# Reject unknown resume strategies

**Epic**: [`epic_session_durable_state_safety`](../epic_session_durable_state_safety/card.md).

**Finding**: D022 (MEDIUM) in [`review_combined.md`](../../review_combined.md#design-conformance-findings).

**Lane**: `todo/` -- accepted Wave 3 implementation work after the HIGH-severity members.

## Goal

Reject an unknown transfer-context strategy before context assembly or child creation, so durable derivation metadata
always names the strategy that actually ran.

## Design Authority

- [`docs/design.md` §3.9](../../../design.md#39-session-resume-context-management): transfer supports the enumerated
  `minimal`, `structured`, `full`, and `ai-curated` strategies, while native derivations record no strategy.
- [`coding_standards.md` §5](../../../developer/coding_standards.md#internal-boundaries-module-to-module): internal
  invalid input is rejected without fallback or silent defaults.
- `src/forge/session/transfer.py::parse_transfer_context_strategy`: the existing canonical parser rejects unknown and
  non-transfer enum values with the supported set.

## Evidence

Rechecked on `dc963a7c`: `SessionManager.resume_session(..., strategy="not-a-strategy")` caught the enum conversion
failure, assembled structured context, created the child, and persisted `confirmed.derivation.strategy` as the original
unknown string. Runtime behavior and durable provenance therefore disagreed.

## Expected Behavior

- Transfer mode validates through the canonical parser before writing a context artifact, index row, or child manifest.
- Unknown values, including `rewind` at this transfer-only layer, raise an actionable typed/value error naming the
  supported set.
- Successful derivations persist the canonical strategy value that drove assembly; native mode keeps `strategy=null`.

## Acceptance Criteria

- Add `tests/regression/test_bug_d022_unknown_resume_strategy.py` with the required regression marker and a docstring
  naming D022 and the silent structured fallback.
- Unit tests cover all supported values, an unknown value, `rewind`, and native-mode null provenance.
- Failure assertions prove no child manifest/index row or context/notes artifact was created.
- Run focused manager/transfer tests, then `./scripts/test-integration.sh tests/src/session/test_resume_integration.py`,
  `make test-regression`, and `make pre-commit`.

## Compatibility and Exclusions

- This is an internal clean break for invalid input; no legacy durable value is migrated by this member.
- Do not absorb CLI reattach flags (O022), rewind launch semantics, or full-strategy artifact selection.
- Preserve automatic child-name and snapshot ownership behavior for valid strategies.
