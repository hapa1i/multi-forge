# Close Daily Bug Scan Follow-ups 2026-09-04

**Lane**: `doing/`

## Goal

Close four reproduced model-routing, passthrough-effort, and resume-recovery regressions introduced by the 2026-09-03
merge sequence.

## Scope

- Preserve an explicitly selected non-Claude model across the interactive Claude launch boundary so the proxy dispatches
  the planned alternative rather than the selected tier's default.
- Normalize Claude Code's `[1m]` transport suffix before passthrough native-effort capability lookup.
- Map a configured native effort floor to the lowest supported level at or above that floor instead of weakening it.
- Preserve the complete intended `session resume` lifecycle action in persisted-route recovery commands.

## Constraints

- Keep tier identity and exact requested-model identity distinct; do not mutate materialized proxy configuration.
- Preserve existing direct-Claude pin behavior and the translated proxy path's established downward clamping semantics.
- Keep passthrough message history byte-identical and retain sanitized public reasoning errors.
- Recovery suggestions must remain copyable, include only explicitly applicable options, and perform the requested fresh
  child action rather than a bare parent resume.
- Avoid unrelated model-catalog, routing, or CLI refactors.

## Acceptance

1. An interactive historical Gemini Flash pin reaches proxy dispatch as that model, not the tier default.
2. Canonical and provider-prefixed `[1m]` Claude requests use native `output_config.effort` handling.
3. An `xhigh` floor against `[low, medium, high, max]` resolves to `max` and never lowers a stronger client value.
4. Fresh-resume route recovery retains child name, strategy, depth, review, force, memory, and authority options when
   explicitly supplied.
