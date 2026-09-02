# Epic: 1.0 Release Hardening

**Lane**: `doing/`

## Goal

Close the verified release-blocking and release-adjacent defects from the September 2026 audit in one integrated v1.0.0
candidate without another merge-audit-follow-up cycle.

## Authorized Batch

This epic authorizes one three-card batch on `fix/1-0-release-hardening`, based on `15cbe45e` (`origin/main`):

1. [`close_cli_enforcement_and_recovery_gaps`](../close_cli_enforcement_and_recovery_gaps/card.md)
2. [`preserve_session_delete_preview_truth`](../preserve_session_delete_preview_truth/card.md)
3. [`stabilize_1_0_walkthrough_contract`](../stabilize_1_0_walkthrough_contract/card.md)

The membership and order are fixed. The three cards may be implemented in parallel because their production write sets
are disjoint. The batch integrator owns shared documentation, board state, aggregate verification, final review, and PR
reconciliation. Each member remains a distinct contiguous commit series.

## Shared Contract

- Treat the audited finding list as closed scope; do not add opportunistic refactors.
- Add a focused regression for every corrected mechanism.
- Require complete verified-prefix evidence for walkthrough `--from` resume.
- Build and test one final wheel from the integrated head.
- Any code change after final evidence invalidates and reruns the affected gate.
- Merge only when all three member cards are complete and the same final SHA passes aggregate release verification.

## Risks

- The batch crosses policy enforcement, session deletion, recovery guidance, and packaged walkthrough assets.
- Large diffs have not prevented prior regressions; reviewable commits and final-SHA evidence are mandatory.
- Cleanup changes can delete state, so ownership failures must remain fail-closed.
