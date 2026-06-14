# Upstream issue draft — PreToolUse hook with malformed/unknown output fails OPEN

**Status**: DRAFT for `openai/codex`. Review + confirm the doc citation and the exact codex-cli version, then file with
`gh issue create --repo openai/codex`.

**Observed on**: codex-cli 0.138.0 (probe round 3, 2026-06-10); re-confirm against the latest release before filing.

**Forge probe**: `scripts/experiments/codex-hooks/` stage `81-enrolled-coverage.sh` subprobe `30h`, response fixture
`responses/pretooluse-malformed.json`.

---

## Title

PreToolUse hook output with an unknown field + `continue:false` is honored as `allow` (fails open, not closed)

## Summary

A trust-enrolled `PreToolUse` hook that returns an `allow` decision **alongside an unknown field and `continue: false`**
lets the tool call proceed. The unknown field and `continue:false` are silently ignored rather than causing the
malformed response to be rejected. If the hook documentation's intent is that malformed/unrecognized hook output fails
*closed* (deny), this is the opposite behavior, and it is security-relevant: a hook that emits a slightly-wrong payload
(a bug, a partial write, or a tampered hook) is treated as a permissive allow instead of a safe block.

## Environment

- codex-cli version: `0.138.0` (please confirm against current)
- OS: macOS (Darwin)
- Hook: a trust-enrolled `PreToolUse` hook (registered in `config.toml`, trust granted via the interactive ceremony)

## Reproduction

1. Register a `PreToolUse` hook that emits this exact stdout and exits 0:

   ```json
   {
     "hookSpecificOutput": {
       "hookEventName": "PreToolUse",
       "permissionDecision": "allow",
       "continue": false,
       "bogusFieldZzz": true
     }
   }
   ```

2. Run a headless turn that triggers a tool call:

   ```
   codex exec --json --sandbox read-only "Run exactly this shell command: echo PROBE-30H. Then reply DONE."
   ```

## Expected

If unknown fields and/or `continue: false` are meant to make hook output invalid, the response should be rejected and
the tool call **denied** (fail closed) — matching the documented contract.

## Actual

The command **runs** (`PROBE-30H` appears in the stream): codex honored `permissionDecision: "allow"` and ignored both
the unknown `bogusFieldZzz` and `continue: false`. Malformed/over-specified hook output therefore **fails open**.

## Why it matters

Hook authors (and frameworks that generate hook output programmatically) cannot rely on codex rejecting a malformed
response. A buggy or compromised PreToolUse hook that emits a not-quite-valid payload is treated as a permissive allow,
defeating the hook's purpose as a guardrail. Either direction is defensible, but it should be **documented and
consistent**: if the contract is fail-closed-on-malformed, this is a bug; if it is intentionally lenient, the docs that
imply fail-closed should be corrected.

## Doc reference

> TODO before filing: quote the exact sentence + link from the codex hooks docs that states malformed/unsupported hook
> output is rejected / fails closed. (Forge recorded this as "refutes the doc-claim" in the codex_frontend card; pull
> the precise source.)

## Notes

- This is reported for transparency; Forge's own Codex hook responder already emits strictly-valid output and does
  **not** rely on codex fail-closing (`src/forge/cli/hooks/codex_policy.py`). The standing probe stage `81` will flag if
  a future codex release changes this behavior.
