# Decide derived-session override inheritance

**Origin**: D040 residual admission recheck on merged `main` at `bad273ef` (2026-08-19).

**Lane**: `done/` -- shipped on 2026-10-28 in [PR #284](https://github.com/hapa1i/multi-forge/pull/284), merged as
`3ad15937` with the same tree as reviewed head `864cb926`. The maintainer selected the inheritance contract on
2026-10-27. Uniform pre-derivation validation subsequently shipped in PR #294; see its
[implementation card](../../done/validate_derived_session_overrides/card.md). See
[merged closeout](checklist.md#merged-closeout).

**Parent epic**: [`epic_repo_maintenance_round`](../../done/epic_repo_maintenance_round/card.md) (completed provenance).

## Question

When fork, fresh resume, and relaunch derive a child, should live parent overrides be copied as overrides, baked into
the child's baseline intent, or omitted except for explicitly inheritable fields?

## Selected outcome

The maintainer selected the [decision](decision.md): fork/fresh inherit selected baseline intent plus effective memory
settings; relaunch retains valid live overrides as a separate layer, with reset subject to supervisor identity checks.
The 2026-10-27 recheck confirms the distinction and existing regressions that require relaunch to preserve disabled
policy. [Evidence](evidence.md) records the verified behavior and validation gaps. Pre-merge review also fixed
proxy-pair inheritance, wildcard lane writes and malformed-supervisor reset diagnostics, and removed the unreachable
relaunch fallback. The separate validation implementation shipped on 2026-10-30.

## Original evidence

- `_inherit_intent_fields` deep-copies raw baseline intent for fork, fresh resume, and relaunch.
- `apply_memory_inheritance` then deliberately reads effective parent memory and bakes only `auto_update` into the
  child; this matches the shipped memory-specific inheritance contract.
- Fresh resume and fork do not copy the generic `overrides` map, so an effective `%policy disable` can disappear while
  an effective memory toggle is retained. Relaunch copies the entire override map and therefore behaves differently.
- Design §3.3 defines overrides as live toggles but does not say whether those toggles cross a derivation boundary.
  Existing docs explicitly promise memory activation and selected lane/intent inheritance, not generic override
  propagation.

The asymmetry is real, but D040's proposed correction is not grounded enough to execute: making every child inherit
effective state could unexpectedly propagate temporary policy toggles, while dropping memory's effective value would
break an explicit contract.

## Decision considered

The original alternatives were:

1. copy raw intent plus selected explicit inheritance only;
2. copy raw intent and the parent's generic overrides; or
3. materialize effective values into a fresh child baseline and clear inherited overrides.

The selected contract uses option 1 for fork/fresh and option 2 for relaunch, preserving memory's explicit exception. It
specifies baseline supervisor suspension, override-only verification setup, consumer lanes, lifecycle-owned fields,
malformed legacy overrides and reset limits. The follow-up card carries fixture-grounded acceptance tests; execution is
tracked separately in that implementation card.
