# Repository-Owned Commit Message Hook Checklist

Activation base: `effff0b4` (`main`, 2026-08-23). Source material: closed PR #238 (`c30ee67f`).

Current focus: integrated verification.

## Port and Correction

- [x] Port the repository mapping, normalizer, hook configuration, tests, and contributor guidance without the old
  terminal closeout state.
- [x] Replace global start/end substitutions with anchored cleanup and add both adjacent-inline regressions.
- [x] Preserve mapping completeness, phrase deletion, whitespace, empty-message fallback, filter mode, and fail-open
  behavior.

## Verification

- [x] Prove default installation creates both Git hooks in an isolated repository.
- [ ] Run focused normalizer/configuration tests and the integrated pre-commit suite.
- [ ] Record the new PR rather than presenting closed PR #238 as shipped.
