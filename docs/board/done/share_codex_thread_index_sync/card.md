# Share Codex thread-to-index synchronization

**Epic**: [`epic_wave7_refactor_and_deletion`](../epic_wave7_refactor_and_deletion/card.md).

**Lane**: `done/` -- shipped in PR #202 (`d1abccc7`) after all five GitHub checks passed.

**Finding**: O053.

## Goal

Use one UI-free writer for the byte-identical Codex interactive/session thread-binding update.

## Evidence and Authority

Reverified on `a3dadb18`: `_sync_codex_thread_to_index` remains duplicated byte-for-byte in the two Codex ops modules,
with four callers immediately after successful manifest reconciliation. Both copies write the same adoption-sensitive
durable index column. `IndexStore.update_codex_thread` already owns scoped resolution, missing-row no-op, collision
warning, durable update, and best-effort failure handling. The focused pre-change Codex op/adoption/index baseline is
201 passing tests. Authority:
[`docs/design.md` "3.12 Command-core ops"](../../../design.md#312-command-core-ops-shared-implementation) and
[`docs/design_appendix.md` "I. Codex Runtime Reference"](../../../design_appendix.md#i-codex-runtime-reference).

## Acceptance Criteria

- Both launch paths call one shared op with identical no-thread, already-bound, missing-row, and collision outcomes.
- Preserve adoption guards, lock/transaction ownership, and runtime-session ID persistence.
- Run both Codex op suites, adoption/index tests, and targeted Codex session integration coverage.

## Exclusions

Do not unify the surrounding launch flows, change thread discovery, or loosen ambiguous/native adoption checks.

## Closeout

PR #202 merged as `d1abccc7` with all five GitHub checks passing. Interactive and headless start/resume now share one
post-manifest index writer, while `IndexStore.update_codex_thread` retains scoped resolution, durable update, collision,
and best-effort ownership. Order 24 remains parked for separate activation from this closeout.
