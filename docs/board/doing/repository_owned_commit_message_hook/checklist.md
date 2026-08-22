# Repository-Owned Commit Message Hook Checklist

Activation base: `5d9fadc4` (`main`, 2026-08-22).

## Behavior migration

- [x] Copy the existing mapping and normalizer into repository-owned paths without changing their behavior. The imported
  mapping and normalizer initially matched the personal sources at SHA-256 `7a7cbec9...` and `248655e3...`; only the
  normalizer's inaccurate "ASCII" docstring wording changed afterward.
- [x] Record characterization evidence for all mapping entries and the message-level fallback behavior. The focused
  suite pins all 156 emoji entries, all 16 phrase entries, bracket-label stripping, and emoji-only fallback.

## Hook ownership

- [x] Register the normalizer only for the `commit-msg` stage and make the default hook installation include both
  `pre-commit` and `commit-msg`.
- [x] Verify the stage mutates the message file before commit creation and leaves ordinary file hooks in `pre-commit`. A
  temporary-repository test installs both generated hook files and invokes the installed `commit-msg` hook against
  `.git/COMMIT_EDITMSG`.
- [x] Verify installation surfaces the existing global `core.hooksPath` conflict instead of depending on it silently.
  Pre-commit 4.6 exits 1 with `Cowardly refusing to install hooks with core.hooksPath set` on the current machine.

## Documentation

- [x] Update contributor setup and repository guidance with the authoritative files, installation command, and migration
  from global hooks.
- [ ] Update the change log and close the card after verification.

## Verification

- [x] Run focused normalizer and pre-commit configuration tests: 11 passed.
- [x] Run unit and regression suites: 9,594 unit passed with 117 deselected; 1,057 regression passed.
- [x] Run full pre-commit and `git diff --check`; both pass after Black and mdformat's mechanical first-run changes.
- [ ] Commit, push, open the PR, and record its link.
