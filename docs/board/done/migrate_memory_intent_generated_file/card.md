# Migrate `MemoryIntent.generated_file`

**Epic**: [`epic_wave7_refactor_and_deletion`](../epic_wave7_refactor_and_deletion/card.md).

**Decision**: [`deletion_compatibility_contract`](../../done/deletion_compatibility_contract/card.md) (DG4).

**Lane**: `done/` -- shipped in PR #192 (`b7a8ad9e`) on 2026-08-16.

**Finding**: O049's `MemoryIntent.generated_file` subset.

**Coordinates with**: [`migrate_inert_config_fields`](../../done/migrate_inert_config_fields/card.md) for O049
sequencing; the manifest migration is independently shippable.

## Goal

Remove the inert dataclass field while old strict session manifests remain readable through an explicit tolerant
migration.

## Evidence and Authority

Rechecked on `9a334b18`: `generated_file` still appears only in the `MemoryIntent` declaration and one direct
deserialization fixture; no source, resource, extension, CLI, or documentation path consumes it. `SessionStore.read`
already strips two retired fields before strict dacite decoding, providing the established migration seam. Authority:
[`docs/design_sessions.md` "3.3 Session file schema"](../../../design_sessions.md#33-session-file-schema-forgesessionjson)
and DG4's durable-state rule.

## Acceptance Criteria

- Read strips only the legacy `intent.memory.generated_file` key before strict decoding; new writes omit it.
- Old, current, malformed, non-object, and newer-schema manifests retain their existing classifications and bytes on
  failed reads.
- Remove the field and direct-only tests after adding migration coverage in `tests/src/session/test_store.py`.
- Run focused session/store/regression tests and targeted session integration coverage.

## Exclusions

Do not loosen strict decoding generally, mutate manifests merely by reading them, or change memory-writer output paths.

## Outcome

Current manifests no longer serialize `MemoryIntent.generated_file`. The reader tolerates only the exact legacy
`intent.memory.generated_file` path in its parsed payload and never rewrites during a read; malformed containers,
unknown siblings, overrides, and newer schemas retain strict error behavior.

PR #192 merged as `b7a8ad9e` after 243 focused tests, 9,204 unit tests (one skip, 122 deselected), 913 regressions, 23
targeted Docker session-lifecycle tests, full pre-commit, design-size checks, and all five GitHub checks passed. No
Forge workflow command was used.
