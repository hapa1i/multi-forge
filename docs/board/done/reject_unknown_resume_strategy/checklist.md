# Reject unknown resume strategies checklist

Current focus: closed after PR #141 (`d2ed2349`).

## Activation and reproduction

- [x] Merge D021 before activating D022 (PR #140, `ecc79aa2`).
- [x] Start `fix/reject-unknown-resume-strategy` from merged `main` at `ecc79aa2`.
- [x] Move D021 to `done/`, move D022 to `doing/`, create this checklist, and repoint inbound board links.
- [x] Add the marked D022 regression and retain the silent structured-fallback failure on `ecc79aa2` (`DID NOT RAISE`).

## Implementation

- [x] Validate transfer-mode strategies with `parse_transfer_context_strategy` before context assembly or durable
  writes.
- [x] Persist the canonical strategy value that actually drove transfer assembly.
- [x] Reject unknown values and transfer-ineligible `rewind` with the canonical actionable error and supported set.
- [x] Preserve all four supported transfer strategies, automatic child naming, snapshot ownership, and native-mode null
  provenance.

## Acceptance coverage

| Test                          | Fixture                                          | Assertion                                                             | Test File                                                   |
| ----------------------------- | ------------------------------------------------ | --------------------------------------------------------------------- | ----------------------------------------------------------- |
| Unknown transfer strategy     | Real parent, explicit child name                 | Raises before child manifest/index or transfer artifacts exist        | `tests/regression/test_bug_d022_unknown_resume_strategy.py` |
| Rewind at transfer layer      | Real parent, `strategy="rewind"`                 | Raises with the four supported transfer values and writes nothing     | `tests/src/session/test_resume_paths.py`                    |
| Supported transfer strategies | Minimal, structured, full, and AI-curated inputs | Derivation records the canonical strategy that assembled context      | `tests/src/session/test_resume_paths.py`                    |
| Native resume provenance      | Real parent in native mode                       | Derivation strategy remains null and no transfer context is generated | `tests/src/session/test_resume_paths.py`                    |

## Verification and closeout

- [x] Run focused manager, transfer, resume-path, and D022 regression tests (107 passed).
- [x] Run the focused Docker `TestSessionManagerResumeSession` class (3 passed, 27 deselected).
- [x] Run `./scripts/test-integration.sh tests/src/session/test_resume_integration.py` (9 passed).
- [x] Run the complete regression suite (668 passed).
- [x] Synchronize design, member/epic cards, review ledger, and change log.
- [x] Run final `make pre-commit` after Markdown normalization.
- [x] Complete independent review and merge D022 before activating D010 (PR #141, `d2ed2349`).
