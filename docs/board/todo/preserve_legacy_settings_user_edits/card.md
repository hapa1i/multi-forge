# Preserve user edits during legacy settings removal

**Epic**: [`epic_installer_transaction_safety`](../../doing/epic_installer_transaction_safety/card.md).

**Finding**: D019 (MEDIUM) in [`review_combined.md`](../../review_combined.md#design-conformance-findings).

**Lane**: `todo/` -- final Wave 4 member after the tracked-baseline work.

## Goal

Make full disable's legacy no-sidecar fallback remove scalar and environment values only when they still equal the
tracked Forge-owned values.

## Design Authority

- [`docs/design_appendix.md` §C.3](../../../design_appendix.md#c3-settings-merge-rules): legacy removal compares values
  and preserves user edits.
- [`docs/design_appendix.md` §C.4](../../../design_appendix.md#c4-durable-installproject-files): settings and ownership
  metadata form a reversible transition whose failures retain an actionable ownership state.

## Evidence

Rechecked on `2461e3fa` with a valid legacy installation row and no `.forge.added.*` sidecar. After changing both the
tracked `statusLine` and a tracked environment value, full disable deleted both; an unrelated environment value
survived. Hooks and permissions already remove by tracked value and are not the failing branch.

## Expected Behavior

- Legacy scalar/env entries are removed only when the current value equals the tracked entry value.
- A missing value is a no-op, and a user-modified value remains unchanged while other still-owned values are removed.
- Hooks and permissions keep their existing canonical/stable-id matching behavior.
- Successful disable still removes the installation row after every owned surface is handled.

## Acceptance Criteria

- Add a marked D019 regression with a docstring naming unconditional scalar/env deletion in `unmerge`.
- Unit tests cover equal, modified, and absent scalar/env values; mixed owned/user values; and unchanged hooks and
  permissions matching.
- Exercise full disable through the real installer, not only the helper, with and without a legacy backup file.
- Run focused settings/installer tests, targeted Docker installer disable coverage, a clean-wheel lifecycle smoke, the
  regression suite, and `make pre-commit`.

## Compatibility and Exclusions

- This is a legacy no-sidecar compatibility correction; do not replace the current smart-unmerge path.
- Do not infer ownership from Forge-looking names or values absent from tracking.
- Do not change backup retention, D012 baseline selection, runtime-scoped survivor semantics, or Codex registration.
