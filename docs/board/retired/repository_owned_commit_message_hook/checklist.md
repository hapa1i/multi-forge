# Retired Repository-Owned Commit Message Hook Checklist

Activation base: `effff0b4` (`main`, 2026-08-23). Source material: closed PR #238 (`c30ee67f`).

Current focus: complete the explicit cancellation without presenting the rejected implementation as shipped.

## Port and Correction

- [x] Port the repository mapping, normalizer, hook configuration, tests, and contributor guidance without the old
  terminal closeout state.
- [x] Replace global start/end substitutions with anchored cleanup and add both adjacent-inline regressions.
- [x] Preserve mapping completeness, phrase deletion, whitespace, empty-message fallback, filter mode, and fail-open
  behavior.

## Verification

- [x] Prove default installation creates both Git hooks in an isolated repository.
- [x] Run focused normalizer/configuration tests and the integrated pre-commit suite.
- [x] Record that neither closed PR #238 nor the removed PR #243 implementation shipped.

## Retirement

- [x] Remove the mapping, executable hook, tests, pre-commit registration, and contributor guidance.
- [x] Preserve this stopped-work record in `retired/` with no replacement and no shipped credit.
- [x] Confirm the reduced PR contains no functional normalizer files or configuration.
