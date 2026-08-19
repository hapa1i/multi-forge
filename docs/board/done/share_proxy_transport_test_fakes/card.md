# Share instance-safe proxy transport test fakes

**Epic**: [`epic_wave7_refactor_and_deletion`](../epic_wave7_refactor_and_deletion/card.md).

**Lane**: `done/` -- shipped in PR #187 (`be321ad2`) on 2026-08-15.

**Finding**: O099's `_FakeResponse` family subset. The transcript-selector subset already shipped with D007/D024.

## Goal

Give both passthrough transport suites one configurable, instance-safe fake response/stream/client fixture without
shared mutable class state.

## Evidence and Authority

Rechecked on `549fb0e3`: `test_passthrough.py` and `test_responses_transport.py` still carry parallel response, stream,
and client fake families. Both clients record requests in mutable class attributes; the Responses suite also stores
response and stream factories on its client class. Pytest's monkeypatch teardown already prevents the claimed factory
leak, and that suite resets request capture before each test, so this is a behavior-preserving isolation refactor rather
than a reproduced correctness defect. Authority:
[`docs/developer/testing_guidelines.md` "Test Maintenance Policy"](../../../developer/testing_guidelines.md#test-maintenance-policy).

## Acceptance Criteria

- Shared fixtures configure response status, headers, chunks, read/stream failures, and request capture per instance.
- Test order or a failed assertion cannot leak configuration into the sibling transport suite.
- Preserve transport-specific defaults and run both full passthrough test files plus their regression slices.

## Exclusions

Do not unify production transports, their intentionally different usage `_merge` behavior, or the already-resolved
transcript selector.

## Implementation Outcome

The two module-local class families are replaced by one shared `ProxyTransportFake` scaffold exposed through the proxy
`conftest.py`. Each test receives its own response, stream, request history, injected failures, and teardown counters.
The two owning suites configure their original Anthropic and Responses payload/header defaults locally, so sharing the
mechanism does not imply a shared wire contract.

The migrated tests use instance configuration instead of client subclasses or class-factory monkeypatches. Direct
contract coverage proves that response, stream, failure, capture, and teardown state do not cross fake instances. Both
transport files pass in either execution order, and no production transport, accounting, or provider-trace code changed.

Verification passed with 128 focused tests, 14 targeted regressions, 9,117 unit tests (one expected skip), and all 906
regression tests. Full pre-commit and Markdown hooks pass. The board audit resolves all 870 local paths across 340
Markdown files, confirms the final 9-done/0-doing/26-todo Wave 7 graph, and finds no stale lane target. Docker
integration and wheel smoke were not required because only test infrastructure and board records changed. PR #187 merged
as `be321ad2` after all five GitHub checks passed.
