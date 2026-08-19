# Remove a redundant dependency declaration

**Epic**: [`epic_wave7_refactor_and_deletion`](../epic_wave7_refactor_and_deletion/card.md).

**Lane**: `done/` -- the verified O071 subset shipped in PR #186 (`19dcf9cb`) on 2026-08-15.

**Finding**: O071.

## Goal

Remove the duplicate development `python-dotenv` declaration while retaining its stronger runtime requirement and the
live `httpx2` test-client dependency.

## Evidence and Authority

Rechecked on `5bd69ef5`: Forge does not import `httpx2` directly, but Starlette 1.3's `testclient` imports it
preferentially and warns on the `httpx` fallback. Forge uses that client throughout unit and regression coverage, and
`d50d8635` deliberately added the dev dependency to resolve the Starlette alert. O071's `httpx2` premise is therefore
rejected. The separate dev `python-dotenv>=1.2.1` edge is redundant because the project runtime already requires
`python-dotenv>=1.2.2`; only that verified subset remains executable.

## Acceptance Criteria

- The dev group and lock metadata contain no duplicate `python-dotenv` edge; the runtime requirement remains.
- The dev group and lock retain `httpx2`, and strict Starlette test-client imports select it without a deprecation
  warning.
- Regenerate `uv.lock` without package-version churn, build wheel/sdist, and verify a clean install plus `forge --help`.
- Run unit and pre-commit gates because dependency resolution changes the supported environment.

## Exclusions

Do not remove `httpx` or `httpx2`, change unrelated dependency floors, or treat an editable-install success as package
proof.

## Implementation Outcome

O071 was only partly valid. Removing `httpx2` made Starlette fall back to deprecated `httpx` compatibility and emitted a
warning during the unit suite; source inspection and `d50d8635` confirmed that the dev dependency is intentional. It
remains at its existing constraint and lock version. The redundant dev `python-dotenv>=1.2.1` declaration is removed,
while runtime `python-dotenv>=1.2.2` and its resolved package remain unchanged.

The final lock diff removes only the two root dev-edge records and changes no package versions. The rebuilt wheel keeps
the runtime `httpx` and `python-dotenv` requirements and exposes no dev-group metadata. Verification passed with a
warnings-as-errors Starlette import, 17 focused proxy tests, 9,115 unit tests (one expected skip), 906 regression tests,
an isolated packaged `forge --help`, and the clean-wheel LiteLLM health smoke.
