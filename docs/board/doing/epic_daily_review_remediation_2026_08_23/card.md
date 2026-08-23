# Epic: Daily Review Remediation 2026-08-23

**Lane**: `doing/`

## Goal

Ship one reviewed correction for the defects confirmed by the 2026-08-23 automated review, while also reviving the
repository-owned commit-message hook from closed PR #238 with its known normalization defect corrected.

## Fixed Batch

- Branch: `fix/daily-review-remediation`
- Base: `effff0b4` (`main`, 2026-08-23)
- Integration owner: the single implementer executing this batch
- Execution: sequential; no parallel writers
- Order:
  1. [`correct_daily_review_findings_2026_08_23`](../correct_daily_review_findings_2026_08_23/card.md)
  2. [`repository_owned_commit_message_hook`](../repository_owned_commit_message_hook/card.md)

The members share `.pre-commit-config.yaml`, repository guidance, board closeout, and aggregate validation. Each member
keeps a contiguous implementation commit series; one integration-only closeout commit may reconcile shared docs and
board state.

## Acceptance

1. Every current-main defect has a fail-first regression or composition test and a contract-preserving fix.
2. The repository-owned commit hook ships with adjacent-inline normalization covered.
3. Both members pass their focused and risk-required checks on the shared branch.
4. Full unit, regression, pre-commit, board/link, file-size, and diff checks pass on the integrated head.
5. The PR is merged only with fixed membership intact; removing a member requires updating this epic first.
