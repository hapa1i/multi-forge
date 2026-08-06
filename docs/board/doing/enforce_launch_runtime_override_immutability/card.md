# Enforce launch-runtime override immutability

**Epic**: [`epic_session_durable_state_safety`](../epic_session_durable_state_safety/card.md).

**Finding**: D008 (HIGH) in [`review_combined.md`](../../review_combined.md#design-conformance-findings).

**Lane**: `doing/` -- independently reviewed on `fix/enforce-launch-runtime-override-immutability` from merged `main` at
`00692356`; pending merge.

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

Reproduced on `00692356`: the marked D008 regression called `set_override` with parent key `launch` and
`{"runtime":"codex"}`. The call returned normally and persisted the effective Codex value because `validate_key`
rejected only the exact dotted path `launch.runtime`; raw intent and launcher dispatch remained `claude_code`. The
failing run also confirmed the input dictionary was mutated. The adjacent `consumer_lanes` guard already rejects its
whole protected subtree.

Execution rechecked the planned clear behavior against the schema: `SessionIntent.launch` has been optional since the
initial schema, older manifests omit it, and the general override contract allows explicit-null clears. Therefore
`session set launch null` remains valid; rejection is keyed to introducing `runtime`, not to touching the parent.

## Implementation Outcome

`set_override` now rejects the direct key, a parent `launch` object containing `runtime`, and `launch.*` before it
mutates the override dictionary. All three routes share the existing immutable-runtime diagnostic. Parent objects that
contain only supported sibling fields, whole-launch null clears, and nullable sibling clears retain their existing
behavior.

`delete_override` deliberately accepts the exact `launch.runtime` path so `session reset launch.runtime` can repair an
illegal override written by an older Forge; resetting the parent remains available too. Launcher dispatch still reads
raw intent, and consumer-lane validation and runtime creation flags are unchanged.

Execution corrected one parked-card assumption rather than encoding it: `SessionIntent.launch` is optional, old
manifests may omit it, and the general explicit-null contract therefore permits `session set launch null`. The
immutability boundary is introducing a `runtime` member, not touching the optional launch section.

Independent review found no design violations and verified all write routes, reset recovery, raw-intent dispatch, and
the mid-execution card correction. It also found that `relaunch_session` deep-copies an already-persisted illegal
`launch.runtime` override into its child. Dispatch remains safe and reset works, but whether relaunch inheritance should
preserve, scrub, or diagnose that stale key is a separate compatibility policy; the observation is recorded as D048
rather than changed here.

## Expected Behavior

- Direct `launch.runtime` writes reject every value, including null; parent-object writes reject a `runtime` member; and
  `launch.*` set is rejected because it necessarily expands to `launch.runtime`.
- `session set launch null` remains supported because `SessionIntent.launch` is an optional legacy-compatible section;
  it clears only the effective view and cannot change raw runtime dispatch. Explicit-null clears also remain supported
  for nullable sibling fields such as `launch.sidecar` and `launch.direct_model`.
- `session reset launch` and `session reset launch.runtime` may remove an already persisted illegal runtime override so
  users are not trapped in unrecoverable state.
- Parent-object updates that do not target runtime remain supported if they are valid today; sibling fields such as
  `launch.mode` keep their existing behavior.
- CLI rejection occurs before manifest mutation and explains that runtime requires a new session.

## Acceptance Criteria

- Add `tests/regression/test_bug_d008_launch_runtime_parent_override.py` with the required regression marker and a
  docstring naming D008 and the exact-key-only guard.
- Unit tests cover direct, parent-object, nested sibling, wildcard, whole-launch null clearing, nullable-sibling null
  clearing, and cleanup of existing-invalid persisted override shapes.
- CLI coverage proves `session set launch '{"runtime":"codex"}'` fails without changing manifest bytes and that a
  supported sibling launch override still succeeds; reset coverage removes an existing illegal runtime override.
- Run `tests/src/session/test_overrides.py`, `tests/src/cli/test_session_overrides.py`, then
  `./scripts/test-integration.sh tests/integration/cli/test_session_commands_integration.py`, `make test-regression`,
  `make test-unit`, and `make pre-commit`.

## Compatibility and Exclusions

- `intent.launch.runtime` is already documented immutable; this closes a bypass rather than changing the public model.
- Do not freeze all launch preferences or make launcher dispatch depend on effective state.
- Do not alter consumer-lane immutability or runtime creation flags.
