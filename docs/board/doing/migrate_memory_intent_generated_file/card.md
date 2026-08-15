# Migrate `MemoryIntent.generated_file`

**Epic**: [`epic_wave7_refactor_and_deletion`](../../doing/epic_wave7_refactor_and_deletion/card.md).

**Decision**: [`deletion_compatibility_contract`](../../done/deletion_compatibility_contract/card.md) (DG4).

**Lane**: `doing/` -- active on `refactor/migrate-memory-intent-generated-file` from `9a334b18`.

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
[`docs/design.md` "3.3 Session file schema"](../../../design.md#33-session-file-schema-forgesessionjson) and DG4's
durable-state rule.

## Acceptance Criteria

- Read strips only the legacy `intent.memory.generated_file` key before strict decoding; new writes omit it.
- Old, current, malformed, non-object, and newer-schema manifests retain their existing classifications and bytes on
  failed reads.
- Remove the field and direct-only tests after adding migration coverage in `tests/src/session/test_store.py`.
- Run focused session/store/regression tests and targeted session integration coverage.

## Exclusions

Do not loosen strict decoding generally, mutate manifests merely by reading them, or change memory-writer output paths.
