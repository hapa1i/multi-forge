# Retire inert configuration fields

**Epic**: [`epic_repo_maintenance_round`](../../doing/epic_repo_maintenance_round/card.md).

**Decision**: [`deletion_compatibility_contract`](../../done/deletion_compatibility_contract/card.md) (DG4; O049).

**Lane**: `todo/` -- accepted Wave 7 cleanup work.

## Goal

Remove config fields that Forge accepts but does not honor, without silently breaking user-owned proxy files or strict
session manifests.

## Scope

- Retire `ProviderConfig.enable_preamble`, `ProviderConfig.openai_api_mode`, and `SessionConfig.manifest_filename`; stop
  template emission and provide the approved warning/error transition.
- Migrate or tolerantly decode existing `MemoryIntent.generated_file` manifest data before deleting the field.
- Keep `MANIFEST_FILENAME` as the single durable path authority.

## Acceptance Criteria

- Raw user-owned config distinguishes omitted values from explicitly present deprecated keys.
- The first migration release warns actionably; rejection does not occur earlier than the following release.
- Strict durable-state tests cover old/newer/malformed manifest shapes and the selected migration or reset path.
- Split proxy-config and manifest work into separate implementation cards before execution if they cannot ship
  atomically.
