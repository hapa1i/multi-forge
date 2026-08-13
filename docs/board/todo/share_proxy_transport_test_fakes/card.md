# Share instance-safe proxy transport test fakes

**Epic**: [`epic_wave7_refactor_and_deletion`](../../doing/epic_wave7_refactor_and_deletion/card.md).

**Lane**: `todo/` -- accepted Wave 7 test refactor work.

**Finding**: O099's `_FakeResponse` family subset. The transcript-selector subset already shipped with D007/D024.

## Goal

Give both passthrough transport suites one configurable, instance-safe fake response/stream/client fixture without
shared mutable class state.

## Evidence and Authority

On `5777192a`, `test_passthrough.py` and `test_responses_transport.py` carry parallel fake families, and one relies on a
class-level stream factory reset manually across tests. Authority:
[`docs/developer/testing_guidelines.md` "Test Maintenance Policy"](../../../developer/testing_guidelines.md#test-maintenance-policy).

## Acceptance Criteria

- Shared fixtures configure response status, headers, chunks, read/stream failures, and request capture per instance.
- Test order or a failed assertion cannot leak configuration into the sibling transport suite.
- Preserve transport-specific defaults and run both full passthrough test files plus their regression slices.

## Exclusions

Do not unify production transports, their intentionally different usage `_merge` behavior, or the already-resolved
transcript selector.
