# Migrate `MemoryIntent.generated_file` checklist

Current focus: Wave 7 order 13 is active from `9a334b18`; keep orders 14--35 parked.

## Activation and evidence

- [x] Close order 12 on pushed `main` at `9a334b18`, branch from that exact closeout, and move only order 13 to
  `doing/`.
- [x] Recheck the field across source, tests, resources, extensions, CLI, and docs: it remains one dataclass declaration
  plus one direct deserialization fixture, with no behavior consumer.
- [x] Confirm the established tolerant-read seam: `SessionStore.read` strips only named retired fields before strict
  dacite decoding and never rewrites a manifest merely by reading it.
- [x] Run unchanged model/store and legacy-memory characterization before editing (`141 passed`).

## Implementation

- [x] Strip only legacy `intent.memory.generated_file` from the in-memory read payload before strict validation and
  decoding; ignore malformed containers so their existing error classification wins.
- [x] Remove `MemoryIntent.generated_file` and its direct-only fixture entry so new manifest writes omit the field.
- [x] Document the explicit tolerant-read exception without weakening unknown-field or schema-version strictness.
- [x] Preserve manifest bytes on successful compatibility reads and on every failed read.

## Acceptance tests

| Boundary              | Fixture                                             | Assertion                                                                 |
| --------------------- | --------------------------------------------------- | ------------------------------------------------------------------------- |
| Legacy valid manifest | object-valued `intent.memory` with `generated_file` | read succeeds, field is absent in memory, disk bytes are unchanged        |
| Current write         | populated `MemoryIntent`                            | serialized memory omits `generated_file`                                  |
| Malformed container   | non-object `intent` or `intent.memory`              | existing corruption classification and disk bytes are preserved           |
| Strict sibling        | legacy field plus an unrelated unknown memory key   | unrelated key still fails strict decoding and disk bytes are preserved    |
| Nonlegacy path        | `overrides.memory.generated_file`                   | strict override validation still rejects the key and preserves disk bytes |
| Newer schema          | unsupported version plus legacy field               | version incompatibility still wins and disk bytes are preserved           |

## Verification and closeout

- [x] Run focused model/store/legacy-memory tests and the new compatibility cases (`243 passed`).
- [x] Run targeted Docker session lifecycle integration coverage (`23 passed`).
- [x] Run `make test-unit` (`9,204 passed`, `1 skipped`, `122 deselected`), `make test-regression` (`913 passed`), and
  `make pre-commit`.
- [x] Run design-size, board link/lane/size, and diff checks: living design docs remain below 30k tokens, all 885 local
  path links across 346 board documents resolve, the Wave 7 graph is 12 `done` / 1 `doing` / 22 `todo`, and order 14
  remains parked.
- [ ] Open one draft PR for order 13; after merge, close this member before selecting order 14.
