# Share policy activation rules without merging state owners

**Epic**: [`epic_wave7_refactor_and_deletion`](../epic_wave7_refactor_and_deletion/card.md).

**Lane**: `doing/` -- active on `refactor/share-policy-activation-rules` from O043 closeout commit `2a08f009`.

**Finding**: O044.

## Goal

Share the pure policy-name, activation-value, and validation rules used by terminal and `%policy` commands while
preserving their intentionally different writes.

## Evidence and Authority

Rechecked on `2a08f009`: terminal enable/disable writes policy intent and the direct command writes a session override.
Both still duplicate the bundle/fail-mode vocabulary, enabled values, TDD permissive config, and no-bundle validation.
The old ledger's “one command-core op” prescription would erase the post-D001 ownership distinction; only their pure
validation/value construction is safe to consolidate. The unchanged characterization suite passes 108 tests. Authority:
[`docs/design.md` "3.12 Command-core ops"](../../../design.md#312-command-core-ops-shared-implementation) and
[`docs/design.md` "5.2 Policy, skills, workflows, and memory"](../../../design.md#52-policy-skills-workflows-and-memory).

## Acceptance Criteria

- Both surfaces call one UI-free helper for policy lookup and activation/deactivation value validation.
- Terminal commands still persist intent; `%policy` still persists overrides; each retains its output and error shape.
- Add an exact behavior matrix and run policy CLI/direct-command unit plus targeted hook integration tests.

## Implementation Status

`build_policy_activation` now derives bundle and fail-mode choices from their policy authorities, validates activation
inputs, and returns typed activation/deactivation values. Both terminal and direct-command handlers call it, but their
intent and override mutations remain separate and surface-owned. The behavior matrix is pinned by core-op and surface
regressions, including invalid inputs and TDD permissive configuration.

Verification on the branch covers 125 focused tests, 22 targeted Docker hook integrations, 9,022 unit tests (one skip,
122 deselected), and 898 regressions. Full pre-commit passes after Markdown normalization. `docs/design.md` records the
command-core boundary; `docs/end-user/policy.md` already documents the unchanged commands, options, and distinct state
owners, so it needs no edit.

## Exclusions

Do not introduce one shared mutation function, change effective-intent precedence, or fold D056/O097 stream work into
this refactor.
