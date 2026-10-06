# Partition the Runtime Design

**Lane**: `todo/`. Scheduled 2026-10-07 as a prerequisite for
[B1's normative documentation work](../../doing/plan_file_supervision/checklist.md#documentation-prerequisites).

## Goal

Partition `docs/design_runtime.md` into stable runtime-domain documents with room for B1's routing and auth contracts.
Keep `docs/design_runtime.md` as the entry point and preserve the user's domain terminology.

## Evidence and scope

The current SHA-256-matched `.file-token-counts.json` entry reports 24,978 Claude Opus 5 tokens, only 22 below the
25,000-token living-document target. A passing hard-limit check is not sufficient room for the planned changes.

- Identify cohesive owners for subprocess/consumer routing, proxy/backend contracts, and isolation; choose boundaries
  from the actual content rather than splitting at an arbitrary line count.
- Move material losslessly, preserving every normative invariant, example, and cross-domain reference.
- Repoint inbound links, including B1's explicit §G references, and refresh token-count evidence for all changed docs.
- Execute on a separate documentation branch/PR before B1's first normative runtime update. Coordinate with
  [Partition the Session Design](../partition_session_design/card.md); no implementation batch is implied.

## Acceptance

1. Every resulting document is at or below the 23,000 Claude Opus 5 partition target, with exact-content count evidence.
2. A lossless-content audit accounts for moved sections and examples; shipped behavior and ownership are unchanged.
3. Repository Markdown links, file-size checks, `make pre-commit-md`, and diff checks pass.
4. B1 and the gather-context routing references identify the resulting canonical owners before implementation docs land.
