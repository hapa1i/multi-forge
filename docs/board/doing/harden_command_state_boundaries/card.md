# Harden command and state boundaries

**Epic**: [`epic_wave6_correctness_maintenance`](../../doing/epic_wave6_correctness_maintenance/card.md).

**Lane**: `doing/` -- implementation and verification are complete on `agent/harden-command-state-boundaries` from
merged production code at `095fcd90` after the PR #174 bookkeeping closeout at `e7ee8f15`; independent review and merge
remain.

**Findings**: D034, D037, D038, and O027.

## Goal

Keep direct-command no-ops silent and reject malformed/reserved durable state at the shared validation chokepoints
rather than allowing internal output or raw type errors downstream.

## Evidence and Authority

Rechecked on merged production code at `095fcd90`: five direct-command no-session paths still emit an internal third
JSON shape; passport updates still omit the reserved path guard; document/content stores still treat wrong field
containers as empty; content/BM25 element types still reach downstream code; and `unwrap_optional(list[str])` still
returns `str`. O027's helper defect is live, but the original downstream claim was too broad: current override consumers
only use the result for nested-dataclass/dict routing, so list-valued overrides retain their existing behavior. The
two-outcome hook and strict-read contracts are in
[`docs/design.md` §3.11](../../../design.md#311-direct-commands-userpromptsubmit-dispatcher) and the developer coding
standards.

## Acceptance Criteria

- No-session direct-command paths emit nothing and exit 0; block outcomes remain unchanged.
- Every passport create/update path applies the same reserved-basename guard before writing.
- Wrong search container/element types raise the store-specific corruption error with rebuild guidance.
- `unwrap_optional` unwraps only real `Union[T, None]` types and leaves generic containers intact.
- Retain hook/passport/search/override regressions and run targeted search integration tests.

## Compatibility and Exclusions

Do not change valid passport frontmatter, search schema versions, override merge semantics, or hook block payloads. The
informative no-session/no-input blocks from `%plan` and `%policy check` remain intentionally unchanged; D034 is limited
to the five cited handlers whose no-session outcome is a silent no-op.
