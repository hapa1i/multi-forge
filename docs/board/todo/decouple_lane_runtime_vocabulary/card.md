# Decouple lane runtime vocabulary

**Epic**: [`epic_wave7_refactor_and_deletion`](../epic_wave7_refactor_and_deletion/card.md).

**Lane**: `todo/` -- accepted Wave 7 refactor work.

**Finding**: O043.

## Goal

Make `forge.core.lanes` depend on the import-light runtime vocabulary rather than loading the runtime registry and LLM
preflight stack.

## Evidence and Authority

On `5777192a`, `lanes.py` imports `RUNTIMES` only for membership checks, while `AGENT_RUNTIME_IDS` already lives in
`core/runtime_vocab.py` and parity tests bind it to the registry. Fresh-process import timing measured about 317 ms for
`forge.core.lanes` versus 20 ms for `forge.core.runtime_vocab`. Authority:
[`docs/design.md` "2. Core components"](../../../design.md#2-core-components-the-pieces) and
[`docs/developer/coding_standards.md` "Code Organization"](../../../developer/coding_standards.md#1-code-organization).

## Acceptance Criteria

- Lane validation uses the neutral runtime-ID set and retains an exact parity guard against registered agent runtimes.
- Importing `forge.core.lanes` does not initialize `forge.core.runtime` or the LLM/preflight stack.
- Run `tests/src/core/test_lanes.py`, consumer-lane tests, and a fresh-process import assertion/measurement.

## Exclusions

Do not change runtime IDs, lane defaults, registry contents, or non-agent runtime behavior.
