# PR #275: bounded investigation and A2 pause

## Owner decision, 2026-10-19

Pause A2's current Jev-backed compatibility-wrapper hook path and select A3 for separate feasibility work. Preserve the
experimental tools and results through [PR #275](https://github.com/hapa1i/multi-forge/pull/275). This is a pause of
partially shipped work, not completion of the warning policy or retirement of the broader idea.

The [continuation decision](feasibility-continuation-2026-10-19.md#decision-stop-the-current-implementation-path) owns
the reasoning. Jev repeated an explicit definition-presence error and hit the frozen sentinel stop. Opus missed the
frozen missing-replacement retention label and exceeded the proposed five-second stage in 21 of 36 requests. Its
disagreement also exposed a contract ambiguity; the [offline review](offline-retention-admission.md) clarifies it
without rewriting labels or declaring the failed study successful. The bounded native audit established neither
representative coverage nor useful warnings. These results do not prove that every future Jev question or rule pack is
infeasible.

## Retained scope and limits

- A1's typed client, explicit evaluation identity and telemetry remain shipped. A2's consent foundations, offline
  outcomes, human review and evaluation tools remain available; `jev_rule_pack` remains reserved.
- The [bounded diagnostic capture](bounded-diagnostic-2026-10-18/README.md) records 38 requests and $1.029230756
  reported spend. Its allowance is consumed. No additional A2 or A3 experiment capture ran during this wrap; standard
  integration verification used its normal setup and is recorded below.
- Capture journals, manifests, completed reviews and saved reports retain their original JSON bytes through the lane
  move. Harness defaults and current document links follow `paused/`; historical source receipts still identify the code
  used then. New executions have new source identities and cannot silently reuse an old capture authorization.
- Settings remain unset. Runtime evidence acquisition, trusted scope declarations, dispatch, activation, warning
  delivery and quality acceptance remain open. The card's unchecked acceptance items are preserved.

Reconsideration requires an owner decision and a bounded proposal addressing evidence admission, representative
usefulness and the tested quality/latency failures. A different complete-diff review product would need an explicit
scope decision. Another prompt variant alone does not reopen runtime implementation.

## Verification and next member

[PR #275](https://github.com/hapa1i/multi-forge/pull/275) merged as `fe2d09a1` on 2026-10-19 with the same tree as
reviewed head `06074f0c`; all five GitHub checks passed. Local `make test` passed 11,597 unit tests and 528 integration
tests, and `make test-regression` passed 2,015 tests. These standard selections had no failures, skips or retries; slow
integrations were not selected. An earlier run with an added offline-cache restriction failed to resolve `hatchling` for
wheel building. Removing that restriction allowed the complete normal run to pass, including both wheel-isolation tests.
These software checks do not change the failed semantic result or establish A3 quality.

Focused pause validation passed 490 affected script tests, 94 relocation/evaluation/replay regressions and 70
inventory/source-audit tests; these overlap the aggregate suites. All 40 retained JSON evidence files match their
pre-move hashes. The inventory now uses private platform temporary storage while retaining historical ledger support.
Applicable changed-file pre-commit checks passed, including types, formatting, secrets, size limits and the 722-source
Markdown link audit. The user's unrelated `AGENTS.md` edits were excluded and preserved. Settings remain unset, and A2
remains paused with its runtime and quality gates open.

[A3](../../../doing/jev_cascade/card.md) depends on A1 and shipped B1, not A2. It activated on
`codex/jev-cascade-feasibility` from `8dea95f5`, with its own [checklist](../../../doing/jev_cascade/checklist.md) and
finite feasibility plan. A3 must establish action/plan coverage and a useful false-allow/abstention trade-off before
skipping any real review. The [epic](../../../doing/epic_jev_support/checklist.md) remains active and owns that handoff.
