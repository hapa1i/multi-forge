# Preserve Claude permissions in policy feedback

Status: **done** on 2026-10-15. [PR #269](https://github.com/hapa1i/multi-forge/pull/269) merged as `e9c144eb` after the
user authorized merge with the paid native trial still skipped. The implementation is fixture-verified; native context
receipt and permission handling remain unverified. See the [merged closeout](checklist.md#merged-closeout).

Activated 2026-10-14 on `codex/claude-policy-feedback-permissions`, based on `main` at `f7ce7a9a`. Identified during the
[A2 rule-pack](../../paused/jev_rule_pack/card.md) review. This independent fix is outside the Jev epic's membership; A2
must establish its own native warning-delivery evidence before claiming that acceptance.

## Problem and outcome

Previously, [`ClaudeHookResponder.allow_feedback`](../../../../src/forge/cli/hooks/policy.py) included
`permissionDecision: "allow"` with `additionalContext`. The shared
[policy hook](../../../../src/forge/cli/hooks/commands.py) calls it for allowed Write/Edit actions whenever
`policy_summary_feedback=on`, including TDD, coding-standards and supervisor sessions without Jev.

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
  `tests/src/cli/hooks/test_policy_feedback.py` for Write/Edit with injected clean, warning, unavailable, deny and
  unresolved-review results. Assert context remains present when enabled, no permission decision is emitted,
  feedback-off suppresses model context and denials retain their existing output/exit behavior. The matrix exercises the
  shared response/audit path with a mocked engine; it does not establish individual policy evaluation or supervisor
  registration coverage.
- Run fixture-backed hook integrations through `./scripts/test-integration.sh`. Prepare a separate quota-bounded native
  Claude trial with synthetic Write/Edit actions, recorded CLI version and permission configuration. Verify both model
  receipt and the native permission flow in default mode, with a configured allow rule/mode as a control. Do not use a
  bypass-permissions trial to claim default-mode behavior. The user chose to skip the prepared paid trial; this native
  evidence remains absent and was explicitly deferred from this fix's merge acceptance.
- Record the observed behavior under this card's `evidence/`. A response-shape unit test or stderr capture does not
  establish native delivery. If context-only feedback fails on an admitted runtime, record that limitation and keep the
  A2 delivery gate open rather than silently restoring blanket permission approval.
- Sync workflow/hook design and `docs/end-user/policy.md`. Add a change-log entry at closeout explaining the permission
  behavior change for existing users, alongside the regression/native evidence. Run aggregate unit, regression,
  pre-commit and board/link checks before merging this independent fix.

## Boundary

No Jev client, rule-pack evaluation, new policy verdict, Codex wire change or supervisor scheduling change belongs here.
A2 can consume the merged responder but must establish native receipt before claiming its Claude feedback acceptance.

The [Read-hygiene hook](../../../../src/forge/cli/hooks/read_hygiene.py) remains a deliberate exception to native
permission separation: when correcting a matching Read with `offset`, `limit` or `pages`, it returns
`permissionDecision: "allow"` alongside `updatedInput` containing only `file_path`. Its match is based on the path, not
installation ownership: it requires `/skills/<name>/resources/` in the path, an immediate parent named `resources`, and
a `code.md`/`docs.md` basename or supported hyphenated variant. Such paths can match anywhere on disk. This card leaves
that input-correction behavior and its matcher unchanged; it removes approval only from Write/Edit policy feedback.
