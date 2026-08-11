# Strip inherited Forge headers from direct children

**Epic**: [`epic_wave6_correctness_maintenance`](../../doing/epic_wave6_correctness_maintenance/card.md).

**Lane**: `done/` -- shipped in PR #164 (`26ab5f29`) on 2026-08-11.

**Finding**: D020.

## Goal

Remove inherited `X-Forge-*` lines before deciding whether a child target is a proven Forge proxy, so a direct child of
a proxied process cannot send stale internal correlation identifiers upstream.

## Evidence and Authority

Reproduced on merged `main` at `55fcda59`: the retained D020 regression supplies all four inherited Forge-owned header
names plus user and malformed lines to a direct child, then fails because the four Forge lines remain. On that base, the
unproven-target return in `_apply_correlation_headers()` preceded `ANTHROPIC_CUSTOM_HEADERS` filtering even though its
docstring said inherited Forge-owned lines were stripped first. The trust contract is
[`docs/design.md` §3.14](../../../design.md#314-cost-tracking-and-spend-caps).

## Acceptance Criteria

- A direct Anthropic target drops all inherited Forge-owned header names while preserving unrelated user headers.
- A proven Forge proxy still receives freshly derived run/root/session/command headers.
- Header matching remains case-insensitive and malformed unrelated lines retain current behavior.
- Retain a regression in `tests/regression/test_bug_d020_inherited_forge_headers.py` and run the reactive-env unit
  slice.

## Implementation Outcome

`_apply_correlation_headers()` now removes the four exact Forge-owned header names before the proven-proxy gate. It
preserves unrelated and malformed non-Forge lines in their existing order. Proven Forge proxies continue through the
existing derivation path and receive fresh run, root-run, session, and optional command headers; direct and otherwise
unproven targets receive none of those inherited identifiers.

No proxy-trust rule, identifier derivation, general custom-header policy, or configuration surface changed.

## Verification

- The retained regression failed on merged `main` at `55fcda59` because all four inherited Forge-owned lines remained
  (`1 failed`).
- The two D020 regressions plus reactive-env unit slice pass (`85 passed`); the review-added case pins removal of an
  all-Forge-only custom-header variable rather than accepting an empty value.
- The full regression target passes and collects both marked guards (`727 passed`).
- The targeted proxy-correlation integration canary passes, including both real Claude custom-header variants
  (`6 passed`).
- Full pre-commit passes after mdformat normalized the edited board Markdown.
- All 719 relative links across 284 board Markdown files resolve, all 12 fragments referenced by the 18 changed board
  files resolve, and the lane audit confirms only D020 is active while the other 11 Wave 6 members remain parked.
- Independent review completed and PR #164 merged as `26ab5f29`.

## Compatibility and Exclusions

This changes only inherited Forge-owned custom-header lines. It must not broaden proxy trust, strip arbitrary custom
headers, or change run/session identifier derivation.
