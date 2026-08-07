# Reject non-object confirmed manifest state

**Epic**: [`epic_session_durable_state_safety`](../epic_session_durable_state_safety/card.md).

**Finding**: O006 (HIGH) in [`review_combined.md`](../../review_combined.md#code-and-maintenance-findings).

**Lane**: `done/` -- shipped in PR #135 (`00692356`) on 2026-08-06.

## Goal

Classify an explicit-null or otherwise non-object `confirmed` section as manifest corruption instead of leaking a raw
Python exception through session read, repair, and delete paths.

## Design Authority

- [`docs/design.md` §3.3](../../../design.md#33-session-file-schema-forgesessionjson): manifests are strict durable
  workflow records with typed `intent`, `overrides`, and `confirmed` sections.
- [`coding_standards.md` §5](../../../developer/coding_standards.md#forge-owned-durable-state): invalid durable state
  must fail with a typed, actionable classification and must not be silently defaulted or clobbered.

## Evidence

Reproduced on `6be815bf`: `SessionStore._validate_data` guards `intent` and `overrides` as objects, but calls `.get()`
on `data.get("confirmed", {})` without validating the result. The marked O006 regression writes a valid v1 fixture with
`"confirmed": null`; it failed at `store.py:502` with raw `AttributeError` before strict deserialization could classify
the manifest. The failing run left the original bytes unchanged.

## Expected Behavior

- Missing `confirmed` keeps its existing legacy/default behavior.
- An explicitly present `confirmed` value must be an object; null, list, scalar, and string values raise
  `ManifestCorruptedError` naming `confirmed` and the manifest path.
- Repair, delete, list/show, and binding consumers receive the established typed corruption outcome without mutating the
  manifest.

## Implementation Outcome

`SessionStore._validate_data` now checks the resolved `confirmed` container before any nested field access. A missing
section still resolves to the legacy empty default, and an empty object remains valid. An explicitly present null, list,
string, number, or boolean instead raises `ManifestCorruptedError` naming `confirmed` and the manifest path, with the
original bytes unchanged.

The existing repair scan now reports that state as `corrupt`, and non-force delete refuses the operation while
preserving both the manifest and session reservation. Docker CLI coverage proves the same delete path emits actionable
corruption text on stderr without a traceback or rewrite. D009 missing-worktree liveness and D011 generic read-error
classification are unchanged. The fail-first regression raised raw `AttributeError` on `6be815bf`; after the fix,
focused tests passed (95), the Docker session-command file passed (44), regressions passed (661), and unit tests passed
(8,751 with one pre-existing platform skip and 118 deselected). Final `make pre-commit` passed.

Independent review found no design violations and verified the fail-first reproduction, consumer routing, Docker path,
and exclusion fences. It also found that three status-line formatters bypass strict manifest reads and raise internally
on an explicit-null `confirmed` section before their per-segment fail-open drops the output. That contained raw-reader
policy is tracked separately as D047: defaulting invalid present state to the missing-field value here would contradict
this card's strict classification, and a status-line fix needs its own explicit degrade behavior and regression.

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
