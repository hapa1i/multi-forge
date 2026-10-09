# Warnings Codex can see

Epic: [Codex supervisor](../../doing/epic_codex_supervisor/card.md). Member **B3**. Depends on
[B2: Codex runtime test round](../../doing/codex_0160_validation/card.md).

## Problem and outcome

Forge currently leaves stdout empty for allowed Codex policy actions and writes warnings to stderr. Those diagnostics do
not provide the model with the rule feedback it needs to correct later work. Deliver bounded, attributed warnings to
Codex on an allowed action using the response shape B2 proves reaches model context. Also establish operator-visible
warnings through tested PreToolUse `systemMessage` behavior; UI/event-stream delivery and model context are separate
channels.

This enables [Jev rule-pack warnings](../jev_rule_pack/card.md) in Codex, but is independently useful for existing
policy warnings and degraded supervisor outcomes. It does not depend on B1 or Jev.

## Scope

- Update the [Codex responder](../../../../src/forge/cli/hooks/codex_policy.py) and
  [policy hook command](../../../../src/forge/cli/hooks/commands.py) to emit one valid response for an allowed patch.
  Keep logs off stdout. Preserve existing deny and unresolved-review behavior.
- Aggregate warnings across every evaluated file, with stable path/rule attribution and bounded deduplication. Include
  the violated rule's intent and supplied evidence where available; do not lose a later file's warning because the first
  file allowed cleanly. Make omission/truncation visible.
- Reuse the existing policy failure semantics. A warning remains non-blocking; its delivery must not turn an allow into
  deny or clear a deterministic denial. Apply any configured source-only feedback formatter consistently.
- Respect `policy_summary_feedback` for model-visible `additionalContext`, including Jev findings: enabled sends bounded
  substantive rule/evidence feedback; disabled sends none. Keep operator diagnostics and durable records when disabled.
  If B2 proves `systemMessage` reaches the UI/event stream, use it for operator warnings independently of that
  model-feedback setting. If unsupported, name the tested operator surface without claiming in-session visibility.
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

## B2 handoff (2026-10-09)

On Codex 0.161.0, bare PreToolUse `additionalContext` reached the model after an allowed patch; the existing explicit
`permissionDecision: allow` helper did not. `systemMessage` appeared as a TUI Hook notice without entering the model
answer. Exit-zero stderr was not visible in the tested model or UI surfaces. Use the exact measured shape and preserve
the catch-all authority guard; B2 does not implement feedback. See
[results](../../doing/codex_0160_validation/evidence/README.md),
[response evidence](../../doing/codex_0160_validation/evidence/feedback.json), and
[TUI evidence](../../doing/codex_0160_validation/evidence/interactive-background.json).
