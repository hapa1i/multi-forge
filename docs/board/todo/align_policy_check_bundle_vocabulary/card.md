# Align policy-check bundle vocabulary

**Origin**: Post-implementation review of Wave 7 O044 on `refactor/share-policy-activation-rules` (`d9f0e2c2`).

**Lane**: `todo/` -- accepted one-line vocabulary follow-up, parked separately from Wave 8 finding credit.

## Goal

Make terminal and direct-command `policy check` parsing consume the shared policy-bundle vocabulary introduced by O044,
without expanding O044 beyond activation/deactivation rules.

## Evidence

- A 2026-08-14 search of all 32 parked Wave 7 member cards found no owner for policy-check bundle vocabulary.
- PR #179 moved terminal/direct activation and the direct `%policy check` flag/positional parser to the shared
  vocabulary. Current `main` still leaves terminal `forge policy check --bundle` on a literal Click choice.
- O044's stated boundary is activation/deactivation value construction. On-demand evaluation parsing is adjacent but
  independently shippable, so it remains outside that branch.

## Acceptance Criteria

- Terminal `forge policy check --bundle` uses `_POLICY_BUNDLE_CHOICES`.
- Direct `%policy check` remains on `policy_ops.POLICY_BUNDLE_NAMES` for both flag-value and positional recognition.
- Existing terminal/direct policy-check syntax, defaults, output, and error behavior remain unchanged.
- Focused policy-check unit tests and `make pre-commit` pass.

## Exclusions

Do not add a shared policy-check mutation/evaluation operation, change fail-mode behavior, revise help text, or fold
this follow-up into O044.
