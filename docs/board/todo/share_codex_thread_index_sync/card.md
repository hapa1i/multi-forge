# Share Codex thread-to-index synchronization

**Epic**: [`epic_wave7_refactor_and_deletion`](../epic_wave7_refactor_and_deletion/card.md).

**Lane**: `todo/` -- accepted Wave 7 command-core refactor work.

**Finding**: O053.

## Goal

Use one UI-free writer for the byte-identical Codex interactive/session thread-binding update.

## Evidence and Authority

On `5777192a`, `_sync_codex_thread_to_index` is duplicated byte-for-byte in the two Codex ops modules and writes the
same adoption-sensitive durable index column. Authority:
[`docs/design.md` "3.12 Command-core ops"](../../../design.md#312-command-core-ops-shared-implementation) and
[`docs/design_appendix.md` "I. Codex Runtime Reference"](../../../design_appendix.md#i-codex-runtime-reference).

## Acceptance Criteria

- Both launch paths call one shared op with identical no-thread, already-bound, missing-row, and collision outcomes.
- Preserve adoption guards, lock/transaction ownership, and runtime-session ID persistence.
- Run both Codex op suites, adoption/index tests, and targeted Codex session integration coverage.

## Exclusions

Do not unify the surrounding launch flows, change thread discovery, or loosen ambiguous/native adoption checks.
