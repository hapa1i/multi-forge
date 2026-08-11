# Strip inherited Forge headers from direct children

**Epic**: [`epic_wave6_correctness_maintenance`](../epic_wave6_correctness_maintenance/card.md).

**Lane**: `todo/` -- accepted Wave 6 work; parked pending a fail-first regression.

**Finding**: D020.

## Goal

Remove inherited `X-Forge-*` lines before deciding whether a child target is a proven Forge proxy, so a direct child of
a proxied process cannot send stale internal correlation identifiers upstream.

## Evidence and Authority

On `246aaff1`, `_apply_correlation_headers()` returns on an unproven target before filtering `ANTHROPIC_CUSTOM_HEADERS`;
its own docstring says inherited Forge-owned lines are stripped first. The trust contract is
[`docs/design.md` §3.14](../../../design.md#314-cost-tracking-and-spend-caps).

## Acceptance Criteria

- A direct Anthropic target drops all inherited Forge-owned header names while preserving unrelated user headers.
- A proven Forge proxy still receives freshly derived run/root/session/command headers.
- Header matching remains case-insensitive and malformed unrelated lines retain current behavior.
- Retain a regression in `tests/regression/test_bug_d020_inherited_forge_headers.py` and run the reactive-env unit
  slice.

## Compatibility and Exclusions

This changes only inherited Forge-owned custom-header lines. It must not broaden proxy trust, strip arbitrary custom
headers, or change run/session identifier derivation.
