# Align transfer preflight and CLI contract

**Epic**: [`epic_wave6_correctness_maintenance`](../epic_wave6_correctness_maintenance/card.md).

**Lane**: `doing/` -- active on `agent/align-transfer-preflight-cli-contract`; the merged-main fail-first gate is
satisfied and the implementation awaits independent review and merge.

**Findings**: D023, D028, and O022.

## Goal

Make transfer preflight resolve the same transcript source the assembler will consume, implement the documented lineage
depth vocabulary, and reject transfer-only flags when `resume` is reattaching instead of creating a fresh child.

## Evidence and Authority

Rechecked by source on merged `main` at `26ab5f29`: both full-strategy preflights still inspect only the latest copied
artifact while `assemble_transfer_context()` falls back to `confirmed.transcript_path` and the live Claude transcript.
`--depth` remains a Click integer despite the documented `N|all`; `resolve_lineage()` still accepts zero or negative
values into an empty lineage; and ordinary Claude reattach still rejects other fresh-only flags without checking
explicit strategy/depth parameter sources.
[`docs/design.md` §3.9](../../../design.md#39-session-resume-context-management) defines fail-fast context assembly and
depth.

The retained regression module then failed on `26ab5f29` in seven expected cases while two compatibility controls
passed: manager did not raise, fork called `fork_session()`, Click rejected `all`, zero/negative depth launched with
empty lineage, and explicit strategy/depth reattached without `--fresh`. Positive integer depth and default reattach
remained green.

## Acceptance Criteria

- Manager and fork preflights use one shared transcript-source resolver and block an over-budget live/fallback source
  before creating child state.
- `--depth all` traverses until lineage ends; zero and negative values fail cleanly; positive integers remain
  compatible.
- Explicit `--strategy` or `--depth` without `--fresh` fails before launch, while defaults preserve ordinary reattach.
- Retain regressions covering manager and CLI paths and run targeted session integration tests.

## Implementation Outcome

Transfer assembly, manager preflight, and fork preflight now call one resolver with the existing copied-artifact,
confirmed-path, and live-Claude precedence. A recorded copied artifact remains authoritative even when its file is
missing, so this alignment does not invent a new fallback rule.

Claude resume parses a positive integer or `all` only on the fresh transfer path. Internally, `all` is an unbounded
lineage request; transfer frontmatter and the child derivation persist the resolved lineage length as an integer.
Unbounded traversal also rejects a cyclic lineage instead of looping. Explicit strategy/depth flags are rejected on
ordinary Claude reattach after runtime dispatch, preserving Codex's existing unsupported-flag errors and native/rewind
ignore semantics.

## Verification

The retained nine-case regression passes. Focused transfer/resume-path and resume/fork/Codex/rewind CLI slices pass
(`130 + 192` tests), as do all 9 targeted Docker session integration cases and all 736 marked regressions. Final
pre-commit and explicit new-file hooks pass after their formatting normalization. All 719 relative links across 285
board Markdown files resolve, the changed-document fragments resolve, the 12-member Wave 6 lane graph remains 1 `done` /
1 `doing` / 10 `todo`, and the board size and diff checks pass.

## Compatibility and Exclusions

Do not change context rendering, transcript precedence, native/native-relocate semantics, rewind's parent-only contract,
or the context-limit calculation itself.
