# Align transfer preflight and CLI contract

**Epic**: [`epic_wave6_correctness_maintenance`](../epic_wave6_correctness_maintenance/card.md).

**Lane**: `todo/` -- accepted Wave 6 work; parked pending fail-first regressions.

**Findings**: D023, D028, and O022.

## Goal

Make transfer preflight resolve the same transcript source the assembler will consume, implement the documented lineage
depth vocabulary, and reject transfer-only flags when `resume` is reattaching instead of creating a fresh child.

## Evidence and Authority

On `246aaff1`, both full-strategy preflights inspect only the latest copied artifact while `assemble_transfer_context()`
falls back to `confirmed.transcript_path` and the live Claude transcript. `--depth` is a Click integer despite the
documented `N|all`, accepts zero into an empty lineage, and explicit strategy/depth values are not rejected on non-fresh
Claude resume. [`docs/design.md` §3.9](../../../design.md#39-session-resume-context-management) defines fail-fast
context assembly and depth.

## Acceptance Criteria

- Manager and fork preflights use one shared transcript-source resolver and block an over-budget live/fallback source
  before creating child state.
- `--depth all` traverses until lineage ends; zero and negative values fail cleanly; positive integers remain
  compatible.
- Explicit `--strategy` or `--depth` without `--fresh` fails before launch, while defaults preserve ordinary reattach.
- Retain regressions covering manager and CLI paths and run targeted session integration tests.

## Compatibility and Exclusions

Do not change context rendering, transcript precedence, native/native-relocate semantics, rewind's parent-only contract,
or the context-limit calculation itself.
