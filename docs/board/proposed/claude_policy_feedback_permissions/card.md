# Preserve Claude permissions in policy feedback

Status: **proposed**, identified during the 2026-10-14
[A2 checklist review](../../doing/jev_rule_pack/checklist.md#separate-prerequisite-claude-feedback-permissions). This is
an independent fix and a prerequisite for A2's Claude warning-delivery gate, outside the Jev epic's membership. It needs
its own execution branch, checklist, PR and closeout before A2 consumes the changed responder.

## Problem and outcome

[`ClaudeHookResponder.allow_feedback`](../../../../src/forge/cli/hooks/policy.py) includes `permissionDecision: "allow"`
with `additionalContext`. The shared [policy hook](../../../../src/forge/cli/hooks/commands.py) calls it for allowed
Write/Edit actions whenever `policy_summary_feedback=on`, including TDD, coding-standards and supervisor sessions
without Jev.

Claude's [official hook contract](https://code.claude.com/docs/en/hooks#pretooluse-decision-control), checked
2026-10-14, says explicit allow skips the permission prompt subject to native exceptions and deny/ask rules. Omitting
the decision leaves normal permission handling in place. Context injection is a separate field. Removing allow therefore
changes behavior beyond Jev; default-mode users may see prompts previously bypassed by the policy summary.

Keep Forge's policy decision and feedback while leaving permission approval to Claude's configured rules/mode. Verify
that Claude still receives substantive `additionalContext` without an explicit decision. B3 only established that
behavior for Codex.

## Scope and acceptance

- Remove unconditional permission approval from the shared Claude feedback response without replacing it with `ask` or
  `defer`. Keep denying/unresolved-review behavior and summary on/off semantics intact; do not introduce a new bypass
  setting or make Jev activation the condition for correct permissions.
- Add `tests/regression/test_bug_claude_policy_feedback_permissions.py` and extend
  `tests/src/cli/hooks/test_policy_feedback.py` for TDD, coding standards and supervisor clean/warning/failure outcomes.
  Assert context remains present when enabled, no permission decision is emitted, feedback-off suppresses model context
  and denials retain their existing output/exit behavior.
- Run fixture-backed hook integrations through `./scripts/test-integration.sh`. Prepare a separate quota-bounded native
  Claude trial with synthetic Write/Edit actions, recorded CLI version and permission configuration. Verify both model
  receipt and the native permission flow in default mode, with a configured allow rule/mode as a control. Do not use a
  bypass-permissions trial to claim default-mode behavior. Native spend/quota authorization remains outstanding.
- Record the observed behavior under this card's `evidence/`. A response-shape unit test or stderr capture does not
  establish native delivery. If context-only feedback fails on an admitted runtime, record that limitation and keep the
  A2 delivery gate open rather than silently restoring blanket permission approval.
- Sync workflow/hook design and `docs/end-user/policy.md`. Add a change-log entry at closeout explaining the permission
  behavior change for existing users, alongside the regression/native evidence. Run aggregate unit, regression,
  pre-commit and board/link checks before merging this independent fix.

## Boundary

No Jev client, rule-pack evaluation, new policy verdict, Codex wire change or supervisor scheduling change belongs here.
A2 can continue offline work but must consume a verified fix before claiming its Claude feedback acceptance.
