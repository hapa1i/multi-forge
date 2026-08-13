# Share policy activation rules without merging state owners

**Epic**: [`epic_wave7_refactor_and_deletion`](../epic_wave7_refactor_and_deletion/card.md).

**Lane**: `todo/` -- accepted Wave 7 refactor work.

**Finding**: O044.

## Goal

Share the pure policy-name, activation-value, and validation rules used by terminal and `%policy` commands while
preserving their intentionally different writes.

## Evidence and Authority

On `5777192a`, terminal enable/disable writes policy intent and the direct command writes a session override. The old
ledger's “one command-core op” prescription would erase that post-D001 ownership distinction; only their pure
validation/value construction is safe to consolidate. Authority:
[`docs/design.md` "3.12 Command-core ops"](../../../design.md#312-command-core-ops-shared-implementation) and
[`docs/design.md` "5.2 Policy, skills, workflows, and memory"](../../../design.md#52-policy-skills-workflows-and-memory).

## Acceptance Criteria

- Both surfaces call one UI-free helper for policy lookup and activation/deactivation value validation.
- Terminal commands still persist intent; `%policy` still persists overrides; each retains its output and error shape.
- Add an exact behavior matrix and run policy CLI/direct-command unit plus targeted hook integration tests.

## Exclusions

Do not introduce one shared mutation function, change effective-intent precedence, or fold D056/O097 stream work into
this refactor.
