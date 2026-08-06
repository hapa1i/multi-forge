# Enforce launch-runtime override immutability

**Epic**: [`epic_session_durable_state_safety`](../../doing/epic_session_durable_state_safety/card.md).

**Finding**: D008 (HIGH) in [`review_combined.md`](../../review_combined.md#design-conformance-findings).

**Lane**: `todo/` -- accepted Wave 3 implementation work.

## Goal

Reject every override that attempts to change `intent.launch.runtime`, including a parent `launch` object, while keeping
supported sibling launch overrides usable.

## Design Authority

- [`docs/design.md` §3.9](../../../design.md#39-session-resume-context-management): Codex/Claude launcher dispatch uses
  immutable raw `intent.launch.runtime`; `forge session set launch.runtime` is rejected.
- [`docs/design.md` §3.3](../../../design.md#33-session-file-schema-forgesessionjson): effective intent is a derived
  view and cannot replace field-owned launch identity.
- [`coding_standards.md` §5](../../../developer/coding_standards.md#internal-boundaries-module-to-module): invalid
  internal mutations are rejected without silent fallback.

## Evidence

Rechecked on `dc963a7c`: `validate_key` rejects only the exact dotted key `launch.runtime`, while its prefix rule
accepts `launch`. Setting `launch` to `{"runtime":"codex"}` over a Claude session succeeded; the effective view reported
Codex while raw intent remained `claude_code`, which is what launchers actually read. The adjacent `consumer_lanes`
guard already rejects its whole protected subtree.

## Expected Behavior

- Direct `launch.runtime` writes reject every value, including null; parent-object writes reject a `runtime` member; and
  `launch.*` set is rejected because it necessarily expands to `launch.runtime`.
- `session set launch null` is rejected because `launch` is a required object. Explicit-null clears remain supported for
  nullable sibling fields such as `launch.sidecar` and `launch.direct_model`.
- `session reset launch` and `session reset launch.runtime` may remove an already persisted illegal runtime override so
  users are not trapped in unrecoverable state.
- Parent-object updates that do not target runtime remain supported if they are valid today; sibling fields such as
  `launch.mode` keep their existing behavior.
- CLI rejection occurs before manifest mutation and explains that runtime requires a new session.

## Acceptance Criteria

- Add `tests/regression/test_bug_d008_launch_runtime_parent_override.py` with the required regression marker and a
  docstring naming D008 and the exact-key-only guard.
- Unit tests cover direct, parent-object, nested sibling, wildcard, whole-launch null rejection, nullable-sibling null
  clearing, and cleanup of existing-invalid persisted override shapes.
- CLI coverage proves `session set launch '{"runtime":"codex"}'` fails without changing manifest bytes and that a
  supported sibling launch override still succeeds; reset coverage removes an existing illegal runtime override.
- Run `tests/src/session/test_overrides.py`, `tests/src/cli/test_session_overrides.py`, then
  `./scripts/test-integration.sh tests/integration/cli/test_session_commands_integration.py`, `make test-regression`,
  and `make pre-commit`.

## Compatibility and Exclusions

- `intent.launch.runtime` is already documented immutable; this closes a bypass rather than changing the public model.
- Do not freeze all launch preferences or make launcher dispatch depend on effective state.
- Do not alter consumer-lane immutability or runtime creation flags.
