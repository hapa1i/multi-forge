# Harden command and state boundaries

**Epic**: [`epic_wave6_correctness_maintenance`](../epic_wave6_correctness_maintenance/card.md).

**Lane**: `done/` -- shipped in PR #175 (`967d9cae`).

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

## Implementation Outcome

- The five D034 handlers now return a silent successful no-op without a session; existing block payloads and the
  intentionally informative `%plan` and `%policy check` outcomes remain unchanged.
- Passport creation and update share the reserved-basename guard before writes, including re-tracking hand-authored
  files through `resolve_with_overrides`.
- Document, content, and BM25 stores reject wrong container and element types through their corruption errors with
  rebuild guidance instead of treating them as empty or leaking downstream type failures.
- Optional unwrapping now recognizes only a real union containing `None`, preserving generic containers and existing
  override routing.

## Verification

- Retained regressions: `28 passed` after producing `21 failed, 5 passed` on `095fcd90`.
- Focused hook, passport, search, override, and regression slice: `681 passed`; post-review passport slice:
  `370 passed`.
- Marked regression gate: `872 passed`.
- Unit gate: `9004 passed, 1 skipped, 122 deselected`.
- Targeted search and prompt-dispatcher Docker integration slices: `24 passed`.
- Full pre-commit and board integrity gates passed; relevant CLI, workflow-design, and end-user memory documentation is
  synchronized.
