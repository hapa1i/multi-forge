# reviewed_launch_artifact -- select editable handoff bytes without changing the frozen snapshot

**Epic**: [epic_native_multiagent](../epic_native_multiagent/card.md) (M9 -- implements D9 independently of child
strategies).

**Lane**: `proposed/`. No functional dependencies. Works with existing transfer output; it need not wait for M4. M5's
pruning claim and M8b's import review depend on this card. Coordinate shared launch-file edits with M8a/M3b.

## Problem (verified 2026-09-06)

- `src/forge/session/prev_sessions.py` composes a frozen snapshot plus appended notes. `src/forge/core/ops/transfer.py`
  exposes the notes overlay as the editable surface.
- `src/forge/cli/session_lifecycle.py` opens notes for `--review`, then concatenates snapshot and notes for launch.
  Deleting text from notes cannot remove content in the frozen snapshot.
- Deferred resume re-reads the stored context path and notes. `src/forge/core/ops/gc.py` protects exact derivation paths
  and paired notes; a new sibling artifact needs its own liveness relationship.
- Codex delivery uses separate bridge, exec and interactive paths, and `src/forge/cli/session_codex.py` currently
  rejects the review gate.
- The current composed view is explicitly not byte-exact: launch may add source wrappers and configured prompts. A
  review contract must distinguish the selected transfer payload from the runtime's other prompt material.

## Design

Preserve `generated.md`, frozen `prev_sessions/<parent>/children/<child>.md`, and legacy appended notes behavior when
review is not selected. Add a user-owned sibling `<child>.review.md` as the selected **transfer payload**.

1. Create the review file from the assembled frozen transfer plus notes. Later renderers may supply child sections or
   imported native memory before this step; the selection layer treats their text opaquely. Reopen an existing review
   file without overwriting user edits.
2. Feed those selected bytes through the runtime's transfer-delivery mechanism. Do not append the baseline or notes
   afterward. Configured prompts, source wrappers and native instructions are separate delivery components; record the
   selected transfer hash and final delivery hash separately, with deterministic composition.
3. Record baseline snapshot hash, selected review path/hash and delivery metadata. Deferred launch/resume continues to
   select the review artifact. Missing, unsafe or empty selected content refuses before dispatch with an actionable edit
   path; it never falls back to the unreviewed baseline.
4. Editor cancellation preserves the child and recoverable artifacts without dispatch. Regeneration refreshes the parent
   cache only; frozen snapshots, notes and review files remain unchanged.
5. `transfer edit` edits a selected review file, otherwise the existing notes overlay. `transfer edit --review`
   explicitly creates/selects the review file. Show/diff identify the selected transfer and its immutable baseline;
   distinguish this view from unrelated configured/runtime prompt components.
6. Extend artifact enumeration and GC so the review file is paired with the child derivation, not mistaken for a new
   child snapshot or deleted as an unreferenced sibling. Preserve both baseline and selected review while referenced,
   including cross-root derivations and cancelled/deferred launch recovery.

### Runtime boundary

Claude transfer-based fresh/fork/deferred launch gets the selection contract first. Add the corresponding pre-dispatch
review gate to the existing Claude-source-to-Codex bridge and its exec, interactive and deferred delivery paths. Codex
**as destination** is acceptance here and does not require M3b's Codex **as source** adapter.

Native/rewind combinations outside transfer delivery retain their restrictions. M3b later routes new Codex-source
launches through this same selection interface; it does not build another review mechanism. The epic's P4 gate owns
verification after both features are available.

## Non-goals

No child strategy matrix, curation algorithm, source adapter, native-memory import, or semantic inference about which
children a human pruned. Review selects literal transfer bytes, not every instruction the runtime might load.

## Acceptance

| Test                      | Fixture and assertion                                                                                                 | Test file                                                                                                                  |
| ------------------------- | --------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| Review creation and reuse | Existing transfer plus notes creates a review copy; reopening preserves edits and baseline bytes                      | `tests/src/session/test_prev_sessions.py`, `tests/src/cli/test_transfer_cli.py`                                            |
| Selected payload          | Remove literal transfer text; it is absent from dispatch even when baseline/notes contain it                          | `tests/src/cli/test_session_derivation.py`                                                                                 |
| Delivery composition      | Configured prompts/wrappers remain separate; selected-transfer and final-delivery hashes match their respective bytes | `tests/src/cli/test_session_derivation.py`, `tests/src/session/test_codex_handoff.py`                                      |
| Deferred/error path       | Cancellation dispatches nothing; later launch uses review; missing/empty/unsafe selected file never restores baseline | `tests/src/cli/test_session_derivation.py`, `tests/src/cli/test_transfer_cli.py`                                           |
| Regeneration and GC       | User edits survive regeneration and cleanup while referenced; baseline/review/notes share correct cross-root liveness | `tests/regression/test_bug_transfer_notes_not_gc_orphaned.py`, `tests/src/session/test_prev_sessions.py`                   |
| Codex destination parity  | Claude-source bridge, initial-message/hook delivery and interactive launch consume the selected transfer              | `tests/src/core/ops/test_codex_bridge.py`, `tests/src/session/test_codex_handoff.py`                                       |
| Runtime delivery          | Targeted installed-runtime flow checks actual reviewed payload and cancelled/deferred recovery                        | Extend `tests/integration/core/test_claude_to_codex_resume.py`, `tests/integration/cli/test_artifact_hooks_integration.py` |

## Design-doc sync

`docs/design_sessions.md` §3.9, §H and Codex delivery sections (selection, immutability, hashes, recovery and GC);
`docs/end-user/transfer.md`, `docs/end-user/session.md` and `docs/cli_reference.md`.
