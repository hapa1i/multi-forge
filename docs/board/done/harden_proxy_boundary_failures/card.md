# Harden proxy boundary failures

**Epic**: [`epic_wave6_correctness_maintenance`](../epic_wave6_correctness_maintenance/card.md).

**Lane**: `done/` -- shipped in PR #171 (`5cd268c1`) after implementation and verification on
`agent/harden-proxy-boundary-failures` from merged `main` at `22071fcd`.

**Findings**: D054 and D055.

## Goal

Reject malformed proxy fields at their template/instance load boundaries and make process-spawn failure atomic and
typed.

## Evidence and Authority

Rechecked on merged `main` at `22071fcd`. Strict template and instance loading preserve malformed values for the four
directly transported fields added to the closed wiring registry: `tool_prefixes_to_ignore=42` later raises while the
converter iterates it, and `auto_cache_min_tokens="4096"` later raises during the prompt-cache threshold comparison. The
adjacent `model_alternatives` and `prompt_caching` fields have the same unvalidated transport boundary.

`_spawn_proxy_process` creates its stderr capture before `subprocess.Popen`, but closes the descriptor only after a
successful spawn. An injected `OSError` leaves both the descriptor and path behind and escapes `start_proxy` callers
despite their documented `ProxyStartError` contract. The tempfile code predates PR #167; that PR made the adjacent
failed-start lifecycle safer but did not introduce this edge.

The retained regression artifact collects `24 failed, 2 passed` on `22071fcd`: twenty-two schema-boundary cases, one
capture-cleanup case, one typed-error case, and two valid-value controls.

[`docs/developer/coding_standards.md`](../../../developer/coding_standards.md) requires explicit boundary validation,
typed operational failures, and deterministic resource cleanup.
[`docs/design_appendix.md` §A.1](../../../design_appendix.md#a1-proxy-overlay-schema-364--user-edit-surface) defines the
transported proxy fields and failed-start cleanup posture.

## Acceptance Criteria

- Template and instance loaders reject malformed `tool_prefixes_to_ignore`, `model_alternatives`, `prompt_caching`, and
  `auto_cache_min_tokens` with field-specific `ValueError` messages before request handling.
- Valid values and absent-field compatibility defaults remain unchanged.
- A `Popen` failure closes and removes the stderr capture without masking the original spawn cause.
- `_spawn_proxy_process` converts spawn `OSError` into `ProxyStartError` for its existing callers.
- Retain fail-first regressions and run focused config/proxy, marked regression, unit, and targeted Docker integration
  coverage.

## Implementation Outcome

- Shared schema validators now reject wrong container/element types for tool-ignore and model-alternative fields,
  unknown prompt-cache modes, and non-integer cache thresholds on both template and instance paths.
- A failed `Popen` closes the parent descriptor, removes its capture path, and raises `ProxyStartError` with the
  original `OSError` chained. Successful spawn ownership is unchanged.
- The end-user proxy guide now states the accepted direct-field shapes and load-time rejection boundary.

## Verification

- Fail-first: `24 failed, 2 passed` on merged `main` at `22071fcd`; the retained artifact now passes all 26 cases.
- Focused config/converter/orchestrator and prior wiring slice: `253 passed`.
- Marked regression gate: `799 passed`.
- Unit gate: `9001 passed, 1 skipped, 122 deselected`.
- Docker proxy start plus custom-template create/reload: `2 passed`.
- Full pre-commit and the explicit new-file hook pass. The explicit pass caught the regression parameter's missing type
  annotation; its corrected rerun is green.
- Board audit: 291 files, 718 relative links, no missing targets, and a Wave 6 split of 6 `done` / 1 `doing` / 6 `todo`.
  The change log is 22,263 tokens and the design appendix remains below its cap at 29,971 tokens.

## Compatibility and Exclusions

Do not add a generic runtime type checker, rewrite existing proxy files, change provider/model selection, or absorb the
six parked Wave 6 members. Validation is limited to the four direct transport fields. Existing valid proxy files and
their absent-key defaults remain compatible.
