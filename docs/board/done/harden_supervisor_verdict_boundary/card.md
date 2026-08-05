# Harden the semantic supervisor verdict boundary

**Epic**: [`epic_policy_supervision_correctness`](../epic_policy_supervision_correctness/card.md).

**Findings**: D002–D004 (HIGH) in [`review_combined.md`](../../review_combined.md#design-conformance-findings) and the
related O028 subset in the [`code and maintenance inventory`](../../review_combined.md#code-and-maintenance-findings).

**Lane**: `done/` -- implemented on `fix/harden-supervisor-verdict-boundary`; review and merge are tracked by the active
epic before D005 starts.

## Goal

Make malformed LLM verdict data visible and fail open without allowing invalid schema values to deny, crash into
fail-closed policy handling, or masquerade as a clean aligned result.

## Evidence

- `src/forge/policy/semantic/verdict.py:96-116` defaults missing/non-numeric confidence to `1.0`; Python booleans and
  `NaN` also reach `1.0` after the current type/clamp path.
- The parser validates only the `violations` container. A string element reaches `v.get()` at lines 149-151 and raises;
  `PolicyEngine(fail_mode="closed")` turns evaluation exceptions into deny.
- The block predicate uses raw truthiness for citations at line 166 while the emitted `Violation` normalizes non-lists
  to `[]` at line 162.
- Unknown verdict literals are rewritten to `aligned` while `parsed=True`, producing a cacheable allow and shadow
  `agree` instead of parse-failure telemetry.
- The workflow and team parser siblings already demonstrate low-confidence degradation and mapping guards.

## Expected Behavior

`docs/design_workflows.md` §1.2 permits semantic blocking only for an exact `divergent` verdict with valid finite
confidence at or above the threshold and at least one normalized citation. Missing, boolean, non-numeric, or non-finite
confidence degrades to low confidence. Finite numeric values retain the existing `[0.0, 1.0]` clamp. Unknown verdict
literals and other schema-invalid responses produce a visible parse-failure/fail-open result, never a clean allow or a
deny.

## Scope

- Validate verdict and confidence without relying on Python's `bool`-as-`int` behavior or permissive `NaN` parsing.
- Filter or safely normalize non-mapping violation entries before conversion.
- Base the citation block predicate on the same normalized citation value stored in `Violation`.
- Ensure invalid verdict literals remain distinguishable in direct enforcement, telemetry, caching, and shadow
  classification.
- Consolidate normalization within the semantic verdict boundary; do not redesign workflow/team policy schemas.

## Acceptance Criteria

- Missing, `null`, boolean, string, `NaN`, and infinite confidence cannot deny; finite numeric confidence keeps the
  documented threshold and existing clamp behavior.
- Non-list containers and non-mapping elements cannot escape the parser/converter under either engine fail mode.
- A string or otherwise invalid citation cannot satisfy the citation requirement or produce a deny with empty displayed
  citations.
- Unknown/case-mismatched verdict literals are visible fail-open parse failures, are not cached as aligned, and classify
  as shadow `error` rather than `agree`.
- Valid aligned, cited divergent, uncited divergent, and mixed cited/uncited responses retain their current decisions.

## Compatibility and Exclusions

The serialized policy schema and confidence threshold do not change. Do not broaden accepted verdict spellings through
case folding: the structured-output contract is exact, and malformed external data should remain observable. Do not
change deterministic policy fail-mode semantics globally.

## Outcome

The semantic parser now rejects unknown verdict literals as parse failures, degrades malformed confidence to `0.0`,
filters malformed violation elements, and uses one normalized citation value for both display and the block predicate.
The existing parsed-status propagation makes these failures visible to enforcement, telemetry, caching, and shadow
classification without changing deterministic fail-mode behavior or the workflow/team schemas.

Restored throttle entries are cache hits only when they match the supervisor's clean-allow write shape: exact `aligned`
verdict plus numeric `1.0` confidence. Missing, malformed, unknown, or divergent entries are treated as misses and
re-evaluated instead of being coerced into cached allows.

One marked regression module per admitted finding records the root cause and verifies malformed and valid controls. The
shipped contract in `docs/design_workflows.md` already specifies the corrected behavior, so no normative design or
end-user documentation change was required.

## Verification

- Pre-fix execution of the four new regression modules: `24 failed, 10 passed`, reproducing D002–D004 and O028.
- Pre-fix restored-cache follow-up: `8 failed`, covering the O028 regression and seven invalid cache shapes.
- Verdict unit tests plus the four regression modules: `65 passed`.
- Focused semantic supervisor, policy engine, shadow, workflow-stage, and team-handler tests: `321 passed`.
- Claude and Codex policy-hook adapter tests: `47 passed`.
- Existing D001 marked regression, run directly: `1 passed`.
- `make test-regression`: `632 passed`.
- `make test-unit`: `8,702 passed, 1 skipped, 118 deselected`.
- `./scripts/test-integration.sh tests/integration/docker/test_policy_hooks.py`: `21 passed`.
- `make pre-commit`: passed after the review follow-up.
