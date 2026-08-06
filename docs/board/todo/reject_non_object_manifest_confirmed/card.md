# Reject non-object confirmed manifest state

**Epic**: [`epic_session_durable_state_safety`](../epic_session_durable_state_safety/card.md).

**Finding**: O006 (HIGH) in [`review_combined.md`](../../review_combined.md#code-and-maintenance-findings).

**Lane**: `todo/` -- accepted Wave 3 implementation work.

## Goal

Classify an explicit-null or otherwise non-object `confirmed` section as manifest corruption instead of leaking a raw
Python exception through session read, repair, and delete paths.

## Design Authority

- [`docs/design.md` §3.3](../../../design.md#33-session-file-schema-forgesessionjson): manifests are strict durable
  workflow records with typed `intent`, `overrides`, and `confirmed` sections.
- [`coding_standards.md` §5](../../../developer/coding_standards.md#forge-owned-durable-state): invalid durable state
  must fail with a typed, actionable classification and must not be silently defaulted or clobbered.

## Evidence

Rechecked on `dc963a7c`: `SessionStore._validate_data` guards `intent` and `overrides` as objects, but calls `.get()` on
`data.get("confirmed", {})` without validating the result. A valid v1 fixture with `"confirmed": null` raised raw
`AttributeError`; the same holds for other non-mapping values before strict deserialization can classify them.

## Expected Behavior

- Missing `confirmed` keeps its existing legacy/default behavior.
- An explicitly present `confirmed` value must be an object; null, list, scalar, and string values raise
  `ManifestCorruptedError` naming `confirmed` and the manifest path.
- Repair, delete, list/show, and binding consumers receive the established typed corruption outcome without mutating the
  manifest.

## Acceptance Criteria

- Add `tests/regression/test_bug_o006_non_object_manifest_confirmed.py` with the required regression marker and a
  docstring naming O006 and the unchecked `.get()` root cause.
- Unit coverage parameterizes representative non-object values, preserves missing/empty-object reads, and verifies bytes
  remain unchanged.
- Repair and delete coverage proves the malformed manifest is classified through existing recovery handling rather than
  a raw traceback or implicit replacement.
- Run focused store/repair/delete tests, then
  `./scripts/test-integration.sh tests/integration/cli/test_session_commands_integration.py`, `make test-regression`,
  and `make pre-commit`.

## Compatibility and Exclusions

- This tightens the existing v1 shape; it does not bump the schema or migrate an invalid section.
- Preserve missing-field compatibility and all field-level `confirmed` ownership rules.
- Do not change missing-worktree liveness (D009) or generic filesystem-read classification (D011).
