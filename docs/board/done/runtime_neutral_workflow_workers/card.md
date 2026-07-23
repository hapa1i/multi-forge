# runtime_neutral_workflow_workers -- dispatch Forge workflow workers through the selected runtime

**Lane**: `done/` -- accepted 2026-07-22; shipped via PR #110 as `26122901` on 2026-07-23. Separate Axis 2 follow-up
discovered while executing [`cross_runtime_skills`](../cross_runtime_skills/card.md); it is not part of that card's
approved Axis 1 scope.

## Why

`panel`, `analyze`, `debate`, and `consensus` are skill frontends for `forge workflow`, but the workflow engine
currently launches every worker through `claude -p` and hard-requires the Claude binary. Installing those frontends for
Codex would therefore mislabel a Claude-worker workflow as Codex-native even though `CodexHeadlessInvoker` already
exists elsewhere in Forge.

## Proposed outcome

- Define a runtime-neutral worker request/response contract for review workflows.
- Select workers through the runtime registry instead of a hard-coded Claude subprocess; runtime-native auth and billing
  posture are resolved by runtime preflight without asserting a static backend identity.
- Reuse `CodexHeadlessInvoker` where its lifecycle, auth, and transcript contracts match; document any adapter gap.
- Preserve current Claude request construction, dispatch, and model-role semantics, except for deliberately folding
  reliable runtime-error envelopes. Exit-zero failures cannot reach synthesis as successes; on non-zero exits, runtime
  stream text takes precedence while an otherwise empty result retains `Exit code N`.
- Only after worker parity is verified, make the four workflow frontend skills eligible for non-Claude packages.

## Boundaries and risks

- This is an engine/auth/telemetry change, not a skill-frontmatter transform.
- Subscription versus API billing, proxy routing, policy hooks, timeout/cancellation, and provider traces must remain
  truthful for every worker.
- A Codex-hosted frontend does not imply Codex workers until this card ships.
- The shipped cross-runtime skill work updated neutral authoring metadata for these skills but kept their Codex package
  eligibility disabled until Axis 2 ships.

## Acceptance direction

Use the same workflow fixtures with Claude and Codex worker adapters; assert equivalent synthesis inputs, explicit
runtime attribution, cancellation/error behavior, and telemetry/provider-trace ownership. Add targeted integration for
real headless runtime execution before moving the card to `done/`.
