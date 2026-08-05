# Epic: Policy and supervision correctness

**Parent epic**: [`epic_repo_maintenance_round`](../../doing/epic_repo_maintenance_round/card.md).

**Lane**: `done/` -- Wave 1 shipped through PRs #125–#127 and closed on 2026-08-05.

## Goal

Restore policy-state preservation and make semantic supervision fail open on malformed external verdicts while ensuring
that prompts and throttle caches identify the complete edit being judged.

## Design Authority

- [`docs/design_workflows.md` §1.2](../../../design_workflows.md#12-semantic-policy-the-supervisor): cited,
  high-confidence divergence is the only semantic block condition; external evaluation failures are visible and fail
  open; only identical diffs may share a cached result.
- [`docs/design_workflows.md` §1.6](../../../design_workflows.md#16-policy-state-and-ownership): supervisor and team
  supervisor configuration are session-owned policy intent.
- [`review_combined.md`](../../review_combined.md#design-conformance-findings): D001–D005, with the related O028 parser
  subset from the code and maintenance inventory.

## Reproduction Record

All admitted findings were rechecked against merged `main` at `a59dc12e`. An isolated temporary pytest harness exercised
the real terminal CLI, verdict parser/converter, Claude and Codex hook adapters, and shared cache-key helper. It was not
retained because its assertions characterize broken behavior; each member below requires replacement regression tests
that assert the target contract.

| Findings      | Fixture                                                                      | Observed result                                                                                                                    |
| ------------- | ---------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| D001          | Session with both supervisor configs; run `forge policy enable --bundle tdd` | Command succeeds and replaces both configs with `None`.                                                                            |
| D002          | Cited divergent verdict with missing, string, `NaN`, or boolean confidence   | Each normalizes to confidence `1.0` and denies.                                                                                    |
| D003          | Divergent verdict with `violations: ["bad"]`                                 | `verdict_to_decision` raises `AttributeError`; `PolicyEngine(fail_mode="closed")` converts evaluation errors to deny.              |
| D004          | High-confidence divergence with `citations: "plan section"`                  | Decision denies, but the emitted `Violation` contains `citations=[]`.                                                              |
| O028          | Parseable `{"verdict": "DIVERGENT", ...}`                                    | Parser reports success, rewrites it to aligned, and returns a clean allow eligible for caching and shadow `agree`.                 |
| D005 (Claude) | Same path/replacement with different `old_string` values                     | Adapter retains different raw args, but both frontier cache keys are identical and the frontier prompt reads only the replacement. |
| D005 (Codex)  | Same-path `Update File` hunks that delete different text and add nothing     | Raw diffs differ, `new_content` is `None` for both, and both supervisor/tier-1 base keys are identical.                            |

Verification performed during triage:

- temporary reproduction harness: `10 passed`;
- focused existing policy/supervision baseline: `250 passed` across policy enable, verdict, supervisor, plan-check, and
  Claude/Codex hook-adapter tests.

## Members and Sequence

| Order | Findings        | Member                                                                                        | Review boundary                                                 |
| ----- | --------------- | --------------------------------------------------------------------------------------------- | --------------------------------------------------------------- |
| 1     | D001            | [`preserve_policy_intent_on_enable`](../../done/preserve_policy_intent_on_enable/card.md)     | Session-intent mutation and CLI regression only                 |
| 2     | D002–D004, O028 | [`harden_supervisor_verdict_boundary`](../../done/harden_supervisor_verdict_boundary/card.md) | One external-data parser, converter, telemetry, and shadow seam |
| 3     | D005            | [`preserve_supervisor_edit_identity`](../../done/preserve_supervisor_edit_identity/card.md)   | Action normalization, prompts, and cache identity               |

D001 goes first because it is the repository review's sole CRITICAL finding. The remaining members are independent after
the shared contracts above are recorded in this epic.

## Related Work Excluded from Wave 1

O044 does not enter this wave. The terminal CLI deliberately mutates durable intent while `%policy enable|disable`
deliberately writes session overrides. D001 can be fixed without erasing that ownership distinction. A shared
command-core abstraction is a later bounded-maintenance candidate and requires its own admission evidence; it must not
ride along with the critical behavior fix.

## Drift Constraints

- Preserve the terminal-versus-direct intent/override ownership distinction.
- Preserve clean-allow-only caching, throttle expiry, plan fingerprints, checker route/budget/effort identity, and
  shadow sampling behavior.
- Preserve the explicit cited-and-high-confidence block bar.
- Treat LLM output as external data: malformed structure must never become a clean allow or a policy-error deny.
- Keep runtime adapters as normalization boundaries and the policy engine runtime-neutral.

## Outcome

All three live members shipped independently and remain linked above:

- D001 shipped in PR #125 (`1765afa5`) with a marked regression for the original policy-intent loss.
- D002–D004 and O028 shipped in PR #126 (`d40748ac`) with strict external-verdict and restored-cache handling.
- D005 shipped in PR #127 (`86fa53da`) with complete pre-truncation action identity across Claude, Codex, frontier,
  tier-1, and shadow replay.

The member cards record their focused, regression, unit, integration, and pre-commit verification. Normative policy and
supervision documentation is synchronized with the shipped behavior, and the review ledger records each finding's
resolution.
