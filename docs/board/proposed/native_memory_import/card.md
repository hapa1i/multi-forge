# native_memory_import -- capture a bounded native-memory excerpt for a reviewed handoff

**Epic**: [epic_native_multiagent](../epic_native_multiagent/card.md) (M8b -- explicit native-memory import).

**Lane**: `proposed/`. Depends on [M8a](../native_memory_explicit/card.md) for parent launch/configuration context and
[M9](../reviewed_launch_artifact/card.md) for reviewed transfer selection. No dependency on M4 or M5. Codex-source
launch integration is owned by epic parity gate P4 after M3b; existing Claude-source transfers can ship first.

## Problem (verified 2026-09-06)

- Native memory can enter a runtime outside Forge's transfer and review. `docs/design_memory.md` deliberately keeps
  Forge's memory writer separate; `src/forge/session/transfer.py` has no explicit native import.
- Resolving memory from the receiving CWD/home would select the wrong source for a cross-worktree or cross-runtime
  handoff. M8a supplies recorded parent context; older sessions may require an explicit source.
- Feeding imported prose into the curator would make exact removal depend on synthesis. Current transfer output can
  accept a post-curation section without changing the curation algorithm or child strategy matrix.

## Design

Add `--import-native-memory` on supported transfer-start, fresh/fork and regeneration surfaces. Reject it for
native/rewind launch strategies before mutation. Default-off receiving sessions may still carry an explicitly imported
excerpt; import does not enable native memory.

1. Resolve from the **parent's** runtime/configuration context, including native home and any configured alternate
   memory directory. Use runtime-specific directory adapters; never substitute the receiving CWD/home. Legacy/unknown or
   unresolvable sources require `--native-memory-source <directory>`, valid only with import. An explicitly requested
   missing/unreadable source fails actionably.
2. Capture deterministic Markdown: tested runtime entry/index files first, then remaining topic files in lexical order.
   Validate containment and reject escaping symlinks. Default total retained-text cap:
   `transfer.native_memory_max_bytes=65536` (64 KiB, positive integer), with UTF-8-safe truncation.
3. Preserve imported bytes as artifacts. Record runtime, original path, capture time, modification time, source/content
   hashes, retained ranges and omissions/truncation. Directory resolution records its evidence, not a claim of use.
4. Append a labeled `Native memory (imported)` untrusted-data section **after** the selected transfer renderer or
   curator returns. It never enters curation inputs and is never ingested by Forge's memory writer. This works with
   existing strategies; M4/M5 later feed the same final assembly step.
5. Freeze imported content/provenance with the child transfer, then let M9 create/select the complete reviewed copy.
   Removing the section removes its bytes from delivery. Bare/deferred resume reads selected artifacts, not current
   native files.
6. Explicit regeneration with the import flag may refresh the parent generated cache. It never rewrites an existing
   child's frozen or reviewed artifact; ordinary regeneration does not silently reread native memory.

Minimal transfers may carry this requested section alongside their existing pointers. Report import provenance on
show/diff; when M5 Sources is available, include the import there through the same assembly contract.

## Runtime and closeout boundary

Unit acceptance covers both native directory adapters. Standalone launch acceptance uses existing Claude-source paths to
Claude and Codex destinations, with M9 review selection. New Codex-source launch integration is a named P4 epic gate
after M3b and M8b are both shipped; it is not an unfinished mandatory row on this card.

## Non-goals

No writes/synchronization to native memory, server-side memory access, proof of historical use, child strategy
selection, or new reviewed-artifact lifecycle.

## Acceptance

| Test                         | Fixture and assertion                                                                                      | Test file                                                                                                                  |
| ---------------------------- | ---------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| Parent source                | Cross-worktree/custom homes select parent context; legacy explicit source is labeled; missing source fails | `tests/src/session/test_transfer.py`                                                                                       |
| Runtime directory adapters   | Claude and Codex entry/index ordering and alternate configuration produce deterministic imports            | `tests/src/session/test_transfer.py`                                                                                       |
| Cap and containment          | Multibyte text, oversized files and escaping links preserve bounded valid text and explicit omissions      | `tests/src/session/test_transfer.py`                                                                                       |
| Post-curation boundary       | Instruction-like native text is absent from curator inputs and preserved in the appended data section      | `tests/src/session/test_transfer.py`                                                                                       |
| Review/regeneration/deferred | Removed section absent from delivery; source changes do not alter existing frozen/reviewed payloads        | `tests/src/cli/test_transfer_cli.py`, `tests/src/session/test_prev_sessions.py`                                            |
| Existing runtime paths       | Claude-source handoff to both destinations delivers the selected import with exact retained bytes          | Extend `tests/integration/cli/test_artifact_hooks_integration.py`, `tests/integration/core/test_claude_to_codex_resume.py` |

## Design-doc sync

`docs/design_memory.md` §6.4 (import boundary); `docs/design_sessions.md` §H (captured provenance, final assembly and
review); `docs/end-user/memory.md`, `docs/end-user/transfer.md`, `docs/end-user/session.md` and `docs/cli_reference.md`.
