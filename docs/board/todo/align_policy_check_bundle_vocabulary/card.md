# Align policy-check bundle vocabulary

**Origin**: Post-implementation review of Wave 7 O044 on `refactor/share-policy-activation-rules` (`d9f0e2c2`).

**Lane**: `todo/` -- accepted three-line vocabulary follow-up, parked for separate execution after O044 shipped in PR
#179. This is a standalone follow-up, not a new member of Wave 7's fixed 34-member sequence.

## Goal

Make terminal and direct-command `policy check` parsing consume the shared policy-bundle vocabulary introduced by O044,
without expanding O044 beyond activation/deactivation rules.

## Evidence

- A 2026-08-14 search of all 32 parked Wave 7 member cards found no owner for policy-check bundle vocabulary.
- On the O044 branch, `forge policy enable` and `%policy enable` use the shared vocabulary, while terminal
  `forge policy check --bundle` still constructs a literal Click choice and direct `%policy check` still repeats the
  literal bundle tuple in its flag and positional parsing paths.
- O044's stated boundary is activation/deactivation value construction. On-demand evaluation parsing is adjacent but
  independently shippable, so it remains outside that branch.

## Acceptance Criteria

- Terminal `forge policy check --bundle` uses `_POLICY_BUNDLE_CHOICES`.
- Direct `%policy check` uses `policy_ops.POLICY_BUNDLE_NAMES` for both flag-value and positional bundle recognition.
- Existing terminal/direct policy-check syntax, defaults, output, and error behavior remain unchanged.
- Focused policy-check unit tests and `make pre-commit` pass.

## Exclusions

Do not add a shared policy-check mutation/evaluation operation, change fail-mode behavior, revise help text, or fold
this follow-up into O044.
