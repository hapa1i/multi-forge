# Warnings Codex can see

Epic: [Codex supervisor](../epic_codex_supervisor/card.md). Member **B3**. Depends on
[B2: Codex runtime test round](../../done/codex_0160_validation/card.md) and
[B1: approved-plan snapshot contract](../../done/plan_file_supervision/card.md); both have shipped.

Selected 2026-10-10 on `feat/codex-policy-warnings`, from local `main` at `d54dba63`. The
[execution checklist](checklist.md) includes the user-selected source-only mode. This activation changes planning only.

## Problem and outcome

Forge currently leaves stdout empty for allowed Codex policy actions and writes warnings to stderr. Those diagnostics do
not provide the model with the rule feedback it needs to correct later work. Deliver bounded, attributed warnings to
Codex on an allowed action using the response shape B2 proves reaches model context. Also establish operator-visible
warnings through tested PreToolUse `systemMessage` behavior; UI/event-stream delivery and model context are separate
channels.

This enables [Jev rule-pack warnings](../../proposed/jev_rule_pack/card.md) in Codex, but is independently useful for
existing policy warnings and degraded supervisor outcomes. Ordinary warning delivery needs no supervisor or Jev call.
The optional source-only mode uses B1's shipped immutable plan snapshot to validate supervisor quotations.

## Scope

- Update the [Codex responder](../../../../src/forge/cli/hooks/codex_policy.py) and
  [policy hook command](../../../../src/forge/cli/hooks/commands.py) to emit one valid response for an allowed patch.
  Keep logs off stdout. Preserve existing deny and unresolved-review behavior.
- Aggregate warnings across every evaluated file, with stable path/rule attribution and bounded deduplication. Include
  the violated rule's intent and supplied evidence where available; do not lose a later file's warning because the first
  file allowed cleanly. Make omission/truncation visible.
- Reuse the existing policy failure semantics. A warning remains non-blocking; its delivery must not turn an allow into
  deny or clear a deterministic denial.
- Add an explicit source-only opt-in for Codex model feedback: verified passages from the exact reviewed plan snapshot
  plus fixed Forge diagnostics. Keep reviewer-generated explanations, evidence prose, and suggested fixes out of model
  context in that mode. Apply it consistently to warning and block text without changing verdicts; preserve full durable
  review evidence. Missing or fabricated quotations produce fixed diagnostics, never a claim of verified source text.
  This is a content-selection option, not a watermark guarantee.
- Respect `policy_summary_feedback` for model-visible `additionalContext`, including Jev findings: enabled sends bounded
  substantive rule/evidence feedback; disabled sends none. Keep operator diagnostics and durable records when disabled.
  B2 observed `systemMessage` as a TUI Hook notice; verify it with the product response independently of the
  model-feedback setting. Report only the tested UI/event surfaces as supported.
- Gate behavior using B2's tested runtime contract. Provide an accurate diagnostic on unsupported versions without
  claiming the model saw a warning that was only printed for the operator.
- Update the runtime, workflow and end-user policy documentation with the validated delivery behavior.

## Acceptance and validation

- Unit/regression coverage checks one JSON response, clean allow, warning, deny, unresolved review, multi-file patches,
  Unicode/escaping, duplicate findings and bounded output. Preserve atomic patch-state persistence.
- A trusted real Codex integration test permits an action and then proves the model consumed a synthetic warning marker.
  A log entry or terminal warning alone is insufficient evidence. With `policy_summary_feedback` off, assert no
  `additionalContext`; independently verify operator `systemMessage` visibility and retained activity records.
- Verify both existing policy warnings and an injected rule-pack-shaped finding without requiring a Jev API call. Check
  diagnostics/JSON stream separation and the installed hook path.
- Source-only tests reject invented or stale quotes, retain exact snapshot attribution, and exclude reviewer prose from
  every Codex model-visible warning/block field. A real Codex control distinguishes source text from a private reviewer
  nonce; full durable review evidence remains inspectable.

## B2 handoff (2026-10-09)

On Codex 0.161.0, bare PreToolUse `additionalContext` reached the model after an allowed patch; the existing explicit
`permissionDecision: allow` helper did not. `systemMessage` appeared as a TUI Hook notice without entering the model
answer. Exit-zero stderr was not visible in the tested model or UI surfaces. Use the exact measured shape and preserve
the catch-all authority guard; B2 does not implement feedback. Native rollout inspection found a developer message
tagged `hooks.additional_context` only for bare context, with no nonce in the other four arms. Historical custom-hook
stdout and exit status were not captured; the passing offline replay cannot prove the original exit status. See
[results](../../done/codex_0160_validation/evidence/README.md),
[response evidence](../../done/codex_0160_validation/evidence/feedback.json), and
[TUI evidence](../../done/codex_0160_validation/evidence/interactive-background.json).
