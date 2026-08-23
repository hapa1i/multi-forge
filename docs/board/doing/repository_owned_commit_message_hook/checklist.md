# Repository-Owned Commit Message Hook Checklist

Activation base: `effff0b4` (`main`, 2026-08-23). Source material: closed PR #238 (`c30ee67f`).

Current focus: review and merge [PR #243](https://github.com/hapa1i/multi-forge/pull/243); implementation and integrated
verification are complete.

## Port and Correction

- [x] Port the repository mapping, normalizer, hook configuration, tests, and contributor guidance without the old
  terminal closeout state.
- [x] Replace global start/end substitutions with anchored cleanup and add both adjacent-inline regressions.
- [x] Preserve mapping completeness, phrase deletion, whitespace, empty-message fallback, filter mode, and fail-open
  behavior.

## Verification

- [x] Prove default installation creates both Git hooks in an isolated repository.
- [x] Run focused normalizer/configuration tests and the integrated pre-commit suite.
- [x] Record the new PR rather than presenting closed PR #238 as shipped.

## Verification Evidence

- The 23 focused normalizer and Markdown-hook tests pass, including both adjacent-inline regressions.
- An isolated temporary repository installs and runs the real `commit-msg` hook before commit creation.
- `make pre-commit` passes with the repository-owned mapping, script, and hook registration on the integrated head.
