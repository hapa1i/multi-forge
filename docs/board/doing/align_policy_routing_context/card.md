# Align policy routing context

**Epic**: [`epic_wave6_correctness_maintenance`](../epic_wave6_correctness_maintenance/card.md).

**Lane**: `doing/` -- implemented and verified on `agent/align-policy-routing-context` from merged `main` at `f6df4a40`;
awaiting independent review and merge.

**Findings**: O013 and O034.

## Goal

Resolve the current proxy identity and implicit session once from authoritative state so policy routing diffs and shadow
read commands describe the session that actually ran.

## Evidence and Authority

Rechecked on merged `main` at `f6df4a40`: policy setup still probes nonexistent `intent.proxy.proxy_id`, making the
current id permanently null, while shadow `status` and `show` still use different implicit-session resolvers. Session
intent/confirmation ownership is defined in
[`docs/design.md` §3.3](../../../design.md#33-session-file-schema-forgesessionjson).

The retained final regression artifact collected `6 failed, 10 passed` on that unchanged production cursor. The six
failures covered the matching current-proxy route, sole-local `show` selection, and missing/ambiguous JSON or human
resolver seams; the ten controls already passed.

## Acceptance Criteria

- Current proxy id comes from confirmed launch routing while template/base intent remains unchanged.
- `shadow show` and `shadow status` share one resolver and select the same explicit/current/sole-local session.
- Ambiguous or missing session errors retain clean human and JSON failure behavior.
- Retain policy command-core and CLI regressions.

## Compatibility and Exclusions

Do not move proxy ids into `ProxyIntent`, change policy intent/override ownership, or merge terminal and `%policy`
implementations (O044).

## Implementation Outcome

- Supervisor setup now reads the current proxy id from CLI-confirmed launch routing. Template and direct intent retain
  their existing ownership, and an absent launch confirmation remains conservative by seeding the source route.
- Shadow `show` and `status` now share the policy-session resolver and therefore use the same explicit, current, and
  sole-local precedence. JSON failures emit one error object on stderr with clean stdout; human diagnostics remain on
  stderr.
- Compatibility narrowing: `shadow show <uuid>` was an undocumented accepted input of the former resolver; the shared
  selector now treats explicit shadow arguments as Forge session names and fails that form cleanly, while
  `resolve_session_identifier` retains UUID support for activity and session-management callers.
- Existing design and end-user documentation already describe confirmed launch facts, proxy intent ownership, and
  supervisor auto-seeding. This correction does not change those contracts, so no design/end-user text changed.

## Verification

- Focused command-core, CLI, semantic, and retained regression slice: `248 passed`.
- Marked regression gate: `815 passed`.
- Unit gate: `9001 passed, 1 skipped, 122 deselected`.
- Targeted non-slow supervisor integration slice: `9 passed, 1 deselected`.
- Full pre-commit gate: all hooks passed after the expected Markdown normalization pass.
- Board integrity: 292 Markdown files, 718 relative links with none missing, and the Wave 6 lane graph at 7 done / 1
  doing / 5 todo; the active checklist is 670 tokens and `git diff --check` is clean.
