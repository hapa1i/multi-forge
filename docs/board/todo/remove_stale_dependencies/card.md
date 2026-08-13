# Remove stale dependency declarations

**Epic**: [`epic_wave7_refactor_and_deletion`](../epic_wave7_refactor_and_deletion/card.md).

**Lane**: `todo/` -- accepted Wave 7 package cleanup work.

**Finding**: O071.

## Goal

Remove the unused `httpx2` development dependency and the duplicate development `python-dotenv` declaration while
retaining the runtime requirement.

## Evidence and Authority

On `5777192a`, no source, test, script, or build configuration imports `httpx2`; `python-dotenv` is declared in both
runtime and development groups with different floors. Package metadata is authoritative in `pyproject.toml` and
`uv.lock`.

## Acceptance Criteria

- Repository and built metadata contain no `httpx2`; one runtime `python-dotenv` constraint remains.
- Regenerate `uv.lock`, build wheel/sdist, and verify a clean install plus `forge --help`.
- Run unit and pre-commit gates because dependency resolution changes the supported environment.

## Exclusions

Do not remove `httpx`, change unrelated dependency floors, or treat an editable-install success as package proof.
