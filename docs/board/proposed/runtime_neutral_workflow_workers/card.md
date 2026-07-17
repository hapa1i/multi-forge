# runtime_neutral_workflow_workers -- dispatch Forge workflow workers through the selected runtime

**Lane**: `proposed/` -- separate Axis 2 follow-up discovered while executing
[`cross_runtime_skills`](../../done/cross_runtime_skills/card.md). It is not part of that card's approved Axis 1 scope.

## Why

`panel`, `analyze`, `debate`, and `consensus` are skill frontends for `forge workflow`, but the workflow engine
currently launches every worker through `claude -p` and hard-requires the Claude binary. Installing those frontends for
Codex would therefore mislabel a Claude-worker workflow as Codex-native even though `CodexHeadlessInvoker` already
exists elsewhere in Forge.

## Proposed outcome

- Define a runtime-neutral worker request/response contract for review workflows.
- Select workers through the runtime/backend registry instead of a hard-coded Claude subprocess.
- Reuse `CodexHeadlessInvoker` where its lifecycle, auth, and transcript contracts match; document any adapter gap.
- Preserve current Claude behavior and model-role semantics.
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
real headless runtime execution before accepting the card into `todo/`.
