# Warnings Codex can see

Epic: [Codex supervisor](../epic_codex_supervisor/card.md). Member **B3**. Depends on
[B2: Codex runtime test round](../../done/codex_0160_validation/card.md) and
[B1: approved-plan snapshot contract](../../done/plan_file_supervision/card.md); both have shipped.

Selected 2026-10-10 on `feat/codex-policy-warnings`, from B2 closeout `d54dba63`, now published to `main`. The
[execution checklist](checklist.md) includes the user-selected source-only mode. Implementation and
[live evidence](evidence/README.md) are complete; the card remains active through PR review and merge.

## Problem and outcome

Forge currently leaves stdout empty for allowed Codex policy actions and writes warnings to stderr. Those diagnostics do
not provide the model with the rule feedback it needs to correct later work. Deliver bounded, attributed warnings to
Codex on an allowed action using the response shape B2 proves reaches model context. Also establish operator-visible
warnings through tested PreToolUse `systemMessage` behavior; UI/event-stream delivery and model context are separate
channels.

This enables [Jev rule-pack warnings](../../proposed/jev_rule_pack/card.md) in Codex, but is independently useful for
existing policy warnings and degraded supervisor outcomes. Ordinary warning delivery needs no supervisor or Jev call.
The optional source-only mode validates supervisor quotations against B1's immutable reviewed plan snapshot before the
warning conversion loses citation structure.

## Scope

- Update the [Codex responder](../../../../src/forge/cli/hooks/codex_policy.py) and
  [policy hook command](../../../../src/forge/cli/hooks/commands.py) to emit one valid response for an allowed patch.
  Keep logs off stdout. Preserve existing deny and unresolved-review behavior.
- Aggregate warnings across every evaluated file, with stable path/rule attribution and bounded deduplication. Include
  the violated rule's intent and supplied evidence where available; do not lose a later file's warning because the first
  file allowed cleanly. Preserve structured supervisor warnings as well as deterministic findings. Make
  omission/truncation visible. Deduplicate within one response; bounded warnings may repeat on later actions. Denied
  responses contain only blocking findings, with other warnings retained in audit evidence.
- Reuse the existing policy failure semantics. A warning remains non-blocking; its delivery must not turn an allow into
  deny or clear a deterministic denial. Separate substantive findings, fixed unavailable-review feedback, operator
  diagnostics, and audit-only depth/cascade noise. Enrich stored findings intentionally while preserving telemetry
  reason and count semantics, manual CLI contracts, and renderer purity.
- Add global `codex_policy_feedback_format=normal|source-only`, default `normal`, through `forge config show/set`.
  Source-only injects verified passages from the exact reviewed plan snapshot plus fixed Forge diagnostics. Exclude
  reviewer-generated explanations, evidence prose, and suggested fixes from Forge's Codex model-visible warning and
  block fields; retain full durable evidence. Missing/fabricated quotations keep the verdict, with actionable fixed
  diagnostics and operator-only inspection commands. The executor can still read workspace evidence; this is no
  access-isolation or watermark guarantee. Claude ignores the explicitly Codex-scoped global preference; no session
  override is added.
- Extend `policy_summary_feedback` to substantive Codex `additionalContext`, including future Jev findings: enabled
  sends bounded rule/evidence feedback; disabled sends none. Keep operator diagnostics and durable records when
  disabled. Document this expansion from the current summary-only behavior and Claude's unchanged summary injection
  until A2. B2 observed `systemMessage` as a TUI Hook notice; verify it with the product response independently of the
  model-feedback setting. Report only the tested UI/event surfaces as supported.
- Gate behavior using the tested runtime contract and secret-free executor identity supplied at every Forge launch,
  including resume/TUI. Older or unknown identity suppresses new model feedback; do not infer the current version from
  thread-creation metadata or probe per action. Record emission separately from observed delivery.
- Update runtime/workflow design, runtime configuration help, and end-user configuration/policy documentation as the
  behavior ships.

## Acceptance and validation

- Unit/regression coverage checks one JSON response, clean allow, warning, deny, unresolved review, multi-file patches,
  instruction-bearing quotations, Unicode/escaping, duplicate findings and bounded output. Preserve atomic patch-state
  persistence and audience filtering without claiming prompt-injection immunity.
- A trusted real Codex integration uses an explicitly supplied independent login and stable enrolled homes. Prove TDD
  delivery from the native injected message and landed action, then prove consumption with a stub supervisor's private
  warning nonce through the product path. With `policy_summary_feedback` off, assert no `additionalContext`;
  independently verify operator `systemMessage` visibility and retained activity records.
- Test rule-pack-shaped findings at the formatter boundary without a Jev call; label any live registry injection as
  instrumented. Check diagnostics/JSON streams and the installed wheel using the same enrolled dispatcher path, with
  checkout overrides disabled and wheel import provenance recorded.
- Source-only tests reject invented or stale quotes, retain exact snapshot attribution, and exclude reviewer prose from
  every Codex model-visible warning/block field. A real Codex control distinguishes source text from a private reviewer
  nonce and excludes extra tool reads from its delivery oracle; full durable evidence remains readable. Require verbatim
  quotations in the reviewer prompt, with one separately budgeted subscription-only Claude attempt to assess quote
  usability. Record any unusable result or missing live evidence explicitly before closeout.

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
