# Retire inert configuration fields

**Epic**: [`epic_wave7_refactor_and_deletion`](../../doing/epic_wave7_refactor_and_deletion/card.md).

**Decision**: [`deletion_compatibility_contract`](../../done/deletion_compatibility_contract/card.md) (DG4; O049).

**Lane**: `done/` -- shipped in PR #191 (`e0be9a60`) on 2026-08-15; this is the first-release warning phase, not
deletion.

**Findings**: O049's `ProviderConfig.enable_preamble`, `ProviderConfig.openai_api_mode`, and
`SessionConfig.manifest_filename` subset only.

## Goal

Stop generating inert user-owned config and add an actionable accept-and-warn transition without breaking existing
proxy/session configuration files.

## Scope

- Retire `ProviderConfig.enable_preamble`, `ProviderConfig.openai_api_mode`, and `SessionConfig.manifest_filename`; stop
  template emission and add the approved warning transition.
- Keep `MANIFEST_FILENAME` as the single durable path authority.

`MemoryIntent.generated_file` is owned by
[`migrate_memory_intent_generated_file`](../../doing/migrate_memory_intent_generated_file/card.md), because
durable-state migration is independent of user-config deprecation.

## Evidence and Authority

Rechecked on `c99be7a3`: `enable_preamble` and `manifest_filename` remain declaration-only; `openai_api_mode` remains in
four shipped templates and is passed through template and proxy-instance loaders without a runtime consumer.
`MANIFEST_FILENAME` still owns every session path. The authority is
[`docs/design.md` "3.6 Configuration System"](../../../design.md#36-configuration-system),
[`docs/design.md` "3.2 Contract files"](../../../design.md#32-contract-files-authoritative-paths), and the DG4 warning
window.

## Acceptance Criteria

- Raw user-owned config distinguishes omitted values from explicitly present deprecated keys.
- Version 0.9.4-era config remains readable; explicitly present keys warn actionably, templates stop emitting them, and
  omission stays silent.
- Rejection/deletion does not occur in this card and cannot occur earlier than a later release after the warning window.
- Run config loader/schema/template tests and clean-wheel Day 1 config verification; update the relevant end-user
  configuration guide when the warning ships.

## Exclusions

Do not change proxy instance field ownership, `MANIFEST_FILENAME`, strict session-manifest parsing, or unrelated
provider compatibility fields.

## Outcome

Explicit compatibility keys remain readable and warn once per process, while new templates, config serialization, and
proxy-instance writes omit them. Runtime transport selection still uses backend plus `wire_shape`, and session paths
still use `MANIFEST_FILENAME`. A provider-registry parity test prevents the warning scan from missing a future
`ProviderConfig` block during this window.

PR #191 merged as `e0be9a60` after 438 focused tests, six O049 regressions, 9,197 unit tests (one skip, 122 deselected),
913 regressions, 34 targeted Docker tests, build and clean-wheel verification, exact-wheel resource checks, full
pre-commit, and all five GitHub checks passed. The final board audit resolves all 879 local path links across 345
documents and confirms the 12-done/0-doing/23-todo Wave 7 graph. No Forge workflow command was used.
