# codex_source_adapter -- capture Codex roots and children and support Codex as a transfer source

**Epic**: [epic_native_multiagent](../epic_native_multiagent/card.md) (M3b -- Codex source capability).

**Lane**: `proposed/`. Depends on M3a's source interface, coordinates and retention primitives. May proceed alongside
M4/M6. It gates Codex support, not their independently shippable Claude scopes.

## Problem (verified 2026-09-06)

- `src/forge/core/runtime/codex_rollouts.py` discovers recent rollouts by CWD/time.
  `src/forge/core/ops/codex_interactive.py` expects exactly one root candidate. A root plus newly created children can
  make unenrolled interactive discovery ambiguous.
- `src/forge/install/codex_hooks.py` recognizes subagent event names but registers no child handler. Native trust
  controls hook delivery; registration alone cannot establish capture coverage.
- `assemble_transfer_context` in `src/forge/session/transfer.py` selects Claude-shaped artifacts/paths/UUIDs, not
  `confirmed.codex.rollout_path`; `src/forge/core/transcript.py` does not parse Codex rollout semantics.
- `src/forge/core/ops/session_fork_preflight.py` and `src/forge/session/manager.py` explicitly refuse Codex parents for
  `session fork`. `src/forge/cli/session_codex.py` rejects Codex `resume --fresh`. Existing
  `--runtime codex --resume-from` establishes a destination path, not a working Codex source adapter.
- Reviewed Codex 0.153.4 evidence names `thread_source: subagent`, `parent_thread_id`, `agent_path` and
  `subagent_history_start_ordinal`; MultiAgentV2 can encrypt delegation text and reasoning. The
  [epic appendix](../epic_native_multiagent/card.md#appendix-runtime-evidence) records provenance and recheck
  obligations.

## Design

### Capture and adapter

- Implement M3a's normalized source interface for available rollout messages, function calls/outputs, compaction
  records, joins and original coordinates. Preserve plaintext historical items; represent ciphertext as unavailable.
- Resolve the root using confirmed thread/rollout evidence. Exclude positively identified descendants and Guardian
  threads from root candidates, then discover descendants recursively through parent ids. Missing metadata or multiple
  plausible roots remains an explicit ambiguity rather than a recency guess.
- Add CLI-owned `confirmed.codex.children[thread_id]`; parent id and agent path are joins, not unique child keys.
  Register subagent hooks that write receipts only. CLI code drains receipts and publishes facts idempotently.
- Capture root and descendants after exec turns and interactive exit, with receipt-driven opportunities where enrolled.
  CLI discovery remains required for unenrolled homes. Record transient-child gaps rather than asserting complete
  capture without a reliable opportunity before cleanup.
- Use M3a's source ids, sidecars, caps and immutable child versions. Root captures use
  `transcripts/root/<safe-source-id>/<sha>.jsonl` under existing root retention.
- Determine inherited history before capping. Map native history ordinals to original record coordinates; do not remove
  N physical lines from a retained tail. Missing/malformed prefix metadata reports unresolved own-history coverage.
  Token observations exclude verified inherited duplicates.

### Codex-as-source launch boundary

Support an explicit transfer-based start surface:

- `forge session start <child> --runtime codex --resume-from <codex-parent> --task "..."`, including its interactive
  variant, reads the Codex source through the adapter.
- Extend `forge session start <child> --runtime claude --resume-from <codex-parent>` with transfer
  `--strategy minimal|structured|full|ai-curated` and `--depth N|all`. This is a new Claude-destination path: create a
  new managed Claude root with parent derivation and the selected transfer, preserving the Codex parent.
- Retain native `session fork` and Codex `resume --fresh` refusals outside these explicit transfer-start paths. Do not
  remove a guard until its complete launch/rollback contract is supported.
- Keep source runtime separate from destination runtime throughout preflight, selection and rendering.
  Missing/unreadable rollout evidence fails actionably rather than producing an apparently successful empty transfer.
  Reuse M9 review selection when installed; M3b does not implement an alternative editor or artifact lifecycle.

Basic root transfer through existing strategies is this card's acceptance. M4/M5/M6 need not exist for that capability
to ship. This card does not wait for their future Codex integration rows.

## Codex parity ownership

M3b owns runtime adapter/discovery and its standalone source launch tests below. The epic owner owns P1-P4 in the
[Codex parity closeout table](../epic_native_multiagent/card.md#codex-parity-closeout), after the named features land.
M4/M5/M6 close on their explicit Claude scopes; they do not retain unpassed mandatory Codex rows. Codex parity remains
required for epic completion, with any implementation gaps assigned to an active card before that gate can pass.

## Non-goals

No child curation strategy, search-specific adapter, native orchestration, general native Codex fork/worktree support,
or new review-artifact semantics.

## Acceptance

| Test                       | Fixture and assertion                                                                                             | Test file                                                                                                            |
| -------------------------- | ----------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| Root plus descendants      | Unenrolled run with root, nested child and Guardian rollouts selects only the evidenced root                      | `tests/src/core/runtime/test_codex_rollouts.py`, `tests/src/core/ops/test_codex_interactive.py`                      |
| Adapter conformance        | Available messages/calls/outputs and compaction events satisfy M3a without consumer-specific Codex parsing        | `tests/src/session/test_transfer.py`, `tests/src/search/test_extractor.py`                                           |
| Prefix and truncation      | History ordinal differs from line index; retained records/citations and usage exclude verified inherited history  | `tests/src/session/test_transfer.py`                                                                                 |
| Receipts and ownership     | Trusted hooks write receipts, CLI publishes children by thread id, replay is idempotent                           | `tests/src/install/test_codex_hooks.py`, `tests/src/core/ops/test_codex_session.py`                                  |
| Codex-source starts        | Both destination runtimes receive non-empty available root evidence, with correct derivation and preserved parent | `tests/src/core/ops/test_codex_bridge.py`, `tests/src/cli/test_session_derivation.py`                                |
| Unsupported paths/rollback | Native fork/fresh refusals remain; transfer-start failure leaves no falsely launchable child                      | `tests/regression/test_bug_codex_fork_orphan.py`, `tests/src/cli/test_session_codex.py`                              |
| Installed runtime          | Hook sync/disable/trust and enrolled/unenrolled discovery; exec and interactive source-to-destination handoff     | Extend `tests/integration/core/test_codex_session_start.py`, `tests/integration/core/test_claude_to_codex_resume.py` |
| Discovery regression       | Root and child created in the same launch window do not cause false root ambiguity                                | New `tests/regression/test_bug_codex_child_rollout_root_ambiguity.py`                                                |

## Design-doc sync

`docs/design_sessions.md` (Codex facts, root source selection, supported transfer-start paths and derivation);
`docs/design_installation.md` (receipts and trust); `docs/design_telemetry.md` (Codex usage coverage);
`docs/end-user/session.md`, `docs/end-user/transfer.md`, `docs/end-user/hook.md` and `docs/cli_reference.md`.
