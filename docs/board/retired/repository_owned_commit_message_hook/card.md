# Repository-Owned Commit Message Hook

**Lane**: `retired/`

**Outcome**: Cancelled on 2026-08-23 after the user decided not to adopt repository-owned text or commit-message
normalization. The implementation was removed from PR #243 before merge.

**Replacement**: None; retaining no repository-owned normalizer is the deliberate outcome.

**Epic**: Retired with
[`epic_daily_review_remediation_2026_08_23`](../epic_daily_review_remediation_2026_08_23/card.md).

## Original Goal

Revive the unmerged work from closed PR #238 so Multi-Forge owns its commit-message normalization instead of depending
on a personal `core.hooksPath`, while correcting the adjacent-inline whitespace loss found during review.

## Historical Decisions

- Port the complete existing mapping and established normalization behavior from `c30ee67f`; do not import its stale
  closeout commit.
- Register the normalizer only for pre-commit's real `commit-msg` stage and install both `pre-commit` and `commit-msg`
  hook types by default.
- Anchor prefix and suffix cleanup. Preserve an existing separator beside an inline removed symbol, but do not invent
  whitespace when a symbol was glued to both neighboring tokens.
- Keep missing/unreadable mapping and message-file failures fail-open with warnings.
- Document migration away from a global `core.hooksPath`; do not add a tracked `.githooks` dispatcher.

## Historical Acceptance

1. All 156 symbol and 16 phrase entries are repository-owned and characterized.
2. `fix🔥 message` and `fix 🔥message` both normalize to `fix message`; established prefix, suffix, middle, fallback,
   filter, and file-mutation behavior remains intact.
3. A temporary repository proves pre-commit installs and runs the real `commit-msg` hook before commit creation.
4. Developer and agent guidance identifies the authoritative files and installation command.

## Retirement

The work reached a verified branch implementation, but the product decision changed before merge. It receives no shipped
finding credit, no `done/` status, and no change-log entry. The mapping, executable hook, tests, pre-commit
registration, and contributor guidance were all removed from the PR.
