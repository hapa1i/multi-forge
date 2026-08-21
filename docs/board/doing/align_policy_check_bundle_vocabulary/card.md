# Align policy-check bundle vocabulary

**Origin**: Post-implementation review of Wave 7 O044 on `refactor/share-policy-activation-rules` (`d9f0e2c2`).

**Lane**: `doing/` -- implemented and locally verified in draft PR #227; await the shared Batch 3 merge before closeout.
It remains separate from Wave 8 finding credit.

## Goal

Make terminal and direct-command `policy check` parsing consume the shared policy-bundle vocabulary introduced by O044,
without expanding O044 beyond activation/deactivation rules.

## Evidence

- A 2026-08-14 search of all 32 parked Wave 7 member cards found no owner for policy-check bundle vocabulary.
- PR #179 moved terminal/direct activation to the shared vocabulary. Reverification on `34cbb601` found three residual
  literals: terminal `forge policy check --bundle` has its own Click choice, while direct `%policy check` separately
  hard-codes both flag-value and positional recognition.
- O044's stated boundary is activation/deactivation value construction. On-demand evaluation parsing is adjacent but
  independently shippable, so it remains outside that branch.

## Acceptance Criteria

- Terminal `forge policy check --bundle` uses `_POLICY_BUNDLE_CHOICES`.
- Direct `%policy check` uses `policy_ops.POLICY_BUNDLE_NAMES` for both flag-value and positional recognition.
- Existing terminal/direct policy-check syntax, defaults, output, and error behavior remain unchanged.
- Focused policy-check unit tests and `make pre-commit` pass.

## Exclusions

Do not add a shared policy-check mutation/evaluation operation, change fail-mode behavior, revise help text, or fold
this follow-up into O044.
