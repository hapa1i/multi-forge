# Derived-session override inheritance checklist

**Status:** Complete. PR #284 merged on 2026-10-28 as `3ad15937`; the decision, bounded fixes and documentation are
shipped and verified. Uniform derivation validation remains in the separate, unstarted proposal.

## Evidence

- [x] Recheck the original D040 claim against fork, fresh resume and relaunch on current main.
- [x] Trace ordinary reattach separately from relaunch-as-child and locate existing inheritance regressions.
- [x] Check memory activation, consumer-lane intent/freeze, authority, launch identity and supervisor constraints.
- [x] Identify inaccurate user documentation: the fork guide currently claims the entire manifest is copied.
- [x] Characterize policy/memory/reset behavior and malformed legacy overrides: 21 isolated parent/child cases, with
  parent bytes preserved throughout. See [evidence](evidence.md).
- [x] Run the existing focused inheritance, override and supervisor regressions: 157 passed in 1.82 seconds.

## Decision

- [x] Specify baseline and live-override behavior for fork, fresh resume and relaunch separately in
  [the decision](decision.md).
- [x] Specify memory's effective-value exception and explicit child-flag precedence.
- [x] Preserve consumer-lane intent inheritance without copying frozen parent bindings.
- [x] Specify immutable/lifecycle-owned keys, invalid legacy state and recovery without silent repair.
- [x] Specify child reset semantics and distinguish reattach from a new session.
- [x] Resolve the product choice with the maintainer: keep the fork/fresh versus relaunch distinction.
- [x] Create [the validation implementation proposal](../../proposed/validate_derived_session_overrides/card.md) with
  fixture-grounded acceptance after the decision; leave it unstarted.

## Closeout

- [x] Correct suspension, verification, reset limitations, side effects, live plan inheritance and admission timing.

- [x] Fix fresh-resume proxy pairing, wildcard lane writes and malformed-supervisor reset diagnostics with regressions.

- [x] Remove the unreachable relaunch fallback and retain coverage of active force, reattach and never-launched
  sessions.

- [x] Run focused regressions, aggregate unit/regression, targeted Docker and full pre-commit checks; prepare the
  reviewed PR #284 update. See [revision verification](evidence.md#revision-verification).

- [x] Document shipped inheritance/reset behavior in session and memory design plus the session/policy guides; retain
  the explicit unshipped validation limitation and its follow-up owner.

- [x] Run Markdown formatting, link, file-size and diff checks: `make pre-commit-md` passed with the refreshed,
  content-matched session-guide count. See [initial verification](evidence.md#initial-documentation-verification).

- [x] Review the initial decision package and prepare PR #284.

- [x] After merge, record the decision outcome, repoint links and move this card to done.

## Merged closeout

- [PR #284](https://github.com/hapa1i/multi-forge/pull/284) merged as `3ad15937` on 2026-10-28. Its tree is identical to
  reviewed head `864cb926`.
- All five GitHub checks passed on that head: [tests](https://github.com/hapa1i/multi-forge/actions/runs/40612468551),
  [pre-commit](https://github.com/hapa1i/multi-forge/actions/runs/40612468529), both
  [CodeQL analyses](https://github.com/hapa1i/multi-forge/actions/runs/40612464745) and the CodeQL result check.
- Local verification passed 223 focused tests, 11,226 unit tests (120 integration tests deselected), 2,212 regressions,
  42 targeted Docker lifecycle tests and full pre-commit. See
  [revision verification](evidence.md#revision-verification).
- Session/memory design and session/policy guides describe the selected layers, baseline supervisor suspension,
  override-only verification setup, reset/admission limits and live inherited plans. The reviewed contract is recorded
  in the
  [session implementation notes](../../impl_notes/sessions.md#derived-configuration-keeps-layer-provenance-reviewed-2026-10-28).
- [Uniform pre-derivation validation](../../proposed/validate_derived_session_overrides/card.md) stays proposed. It owns
  refusal before proxy startup, transfer work and forced fork replacement; this closeout does not activate it.
