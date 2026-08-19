# Decouple lane runtime vocabulary

**Epic**: [`epic_wave7_refactor_and_deletion`](../epic_wave7_refactor_and_deletion/card.md).

**Lane**: `done/` -- shipped independently in PR #178 (`30f930b0`) from preparation commit `095d8eeb`.

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

## Implementation Outcome

`runtime_execution` now classifies agent runtimes through `AGENT_RUNTIME_IDS`; the existing registry parity assertion
remains the authority for vocabulary drift. A subprocess regression pins the import boundary in a fresh interpreter. The
fresh import initialized no `forge.core.runtime`, `forge.core.llm`, or `forge.core.auth` modules and measured
approximately 55 ms cumulatively, down from the approximately 317 ms activation baseline.

Verification on the branch covers 49 focused lane assertions, 568 broader lane-consumer assertions, 9,005 unit tests
(one skip, 122 deselected), and 898 regressions. This import-only refactor changes neither a consumer binding nor a
runtime dispatch path, so the real-Codex consumer integration smokes are not applicable.

Full pre-commit passes after Markdown normalization. The board audit resolves all 852 local paths and all 55 fragments
from the 44 changed board documents; the Wave 7 graph is exactly one `doing/` member and 33 `todo/` members with valid
epic backlinks. Four unrelated fragment references in untouched historical cards remain pre-existing.

PR #178 merged at `30f930b0` with all five GitHub checks passing. The change restores the documented pure lane/runtime
vocabulary boundary without changing architecture ownership, CLI behavior, or end-user configuration, so no normative
design or end-user documentation update is required.

The post-merge closeout resolves all 853 local paths across 328 board Markdown files and all three fragments from
changed documents. The Wave 7 graph is one `done/`, zero `doing/`, and 33 `todo/` members with valid epic backlinks.

## Exclusions

Do not change runtime IDs, lane defaults, registry contents, or non-agent runtime behavior.
