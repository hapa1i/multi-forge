# Derived-session override inheritance checklist

**Current focus:** Decision selected by the maintainer on 2026-10-27; prepare the documentation PR. This card records
the contract; runtime validation belongs to the separate follow-up. Base: `32df0219`.

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

- [x] Document shipped inheritance/reset behavior in session and memory design plus the session/policy guides; retain
  the explicit unshipped validation limitation and its follow-up owner.
- [x] Run Markdown formatting, link, file-size and diff checks: `make pre-commit-md` passed with the refreshed,
  content-matched session-guide count. See [verification](evidence.md#documentation-verification).
- [x] Review the complete decision package and prepare its PR; production behavior remains unchanged.
- [ ] After merge, record the decision outcome, repoint links and move this card to done.
