# Verify and correct token totals on direct Codex resume

**Status**: Proposed. Follow-up to [managed Codex proxy routing](../../doing/codex_session_proxy_routing/card.md).

A native-auth `forge session resume <name> --task ...` passes the terminal JSONL token counters directly to the session
usage event and downstream attempt. On the proxy route, real Codex 0.141.0 and 0.172.0 reported cumulative thread
counters on resume. Forge subtracts the pre-launch baseline for that route. The direct path bypasses that subtraction.
Its actual wire behavior still needs a direct-auth measurement. [Invoker](../../../../src/forge/core/invoker/codex.py) ·
[Native proxy measurements](../../doing/codex_session_proxy_routing/evidence/managed-cli-matrix.json)

## Acceptance

- Use an isolated native-auth test home and one bound thread. Capture the first turn, the pre-resume rollout counter,
  the resumed JSONL terminal counter, and each launch's usage ledger event. Compare their sum with the session total
  from `forge telemetry activity <name> --json`.
- If direct resume reports cumulative counters, reuse the verified per-launch delta calculation for its session event
  and native attempt. Check input, cached input and output independently. Exercise missing or decreasing counters and
  preserve unknown usage when the delta cannot be established.
- Cover a first turn, two consecutive resumes, and a failed turn followed by a successful resume. Keep cost and billing
  provenance consistent with native auth. Record the verified behavior in the
  [telemetry design](../../../design_telemetry.md).
