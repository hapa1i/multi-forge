# Reuse Claude usage measurement resolution checklist

Current focus: order 25 is active on `refactor/reuse-claude-usage-measurement` from `5eb39d15`; keep orders 26--35
parked.

## Activation and evidence

- [x] Close order 24 on pushed `main` at `5eb39d15`, create the execution branch from that exact commit, and move only
  this member to `doing/`.
- [x] Re-run source, caller, import, and test searches for `emit_verb_usage`, `resolve_claude_p_measurement`, and the
  four workflow aggregate callers.
- [x] Confirm the local block matches the resolver's proxied verb branch while session-result and worker emission
  already use the shared authority.
- [x] Record the focused usage/ledger regression baseline before implementation (116 passed, 891 deselected).

## Implementation

- [x] Route `emit_verb_usage` measurement fields through `resolve_claude_p_measurement`.
- [x] Remove the duplicated cost, token, reporter, confidence, and measurement-source precedence.
- [x] Strengthen golden aggregate-event coverage for measured cost, token-only, and unmeasured snapshots.
- [x] Keep an unmeasured snapshot authoritative when handed an inconsistent synthetic cost-evidence flag.
- [x] Preserve run identity, command/session/workflow/status, `route=None`, latency, null source refs, and best-effort
  emission.

## Verification and closeout

- [x] Run focused usage emitter, ledger, and usage regression tests (118 passed, 891 deselected).
- [x] Run the full unit suite (9,222 passed, one skipped, 122 deselected), regression suite (921 passed), and targeted
  Docker proxy-panel telemetry/cost integration (one passed).
- [x] Run full pre-commit and `git diff --check`; confirm `design.md` (29,974) and `design_appendix.md` (29,990) stay
  below 30,000 tokens; and audit 359 board documents, 882 local links, zero missing links, and Wave 7's 24 done / one
  doing / 10 todo lanes without a Forge workflow.
- [x] Commit and push order 25 for review without activating order 26.
