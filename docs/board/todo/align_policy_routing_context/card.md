# Align policy routing context

**Epic**: [`epic_wave6_correctness_maintenance`](../epic_wave6_correctness_maintenance/card.md).

**Lane**: `todo/` -- accepted Wave 6 work; parked pending fail-first regressions.

**Findings**: O013 and O034.

## Goal

Resolve the current proxy identity and implicit session once from authoritative state so policy routing diffs and shadow
read commands describe the session that actually ran.

## Evidence and Authority

On `246aaff1`, policy setup probes nonexistent `intent.proxy.proxy_id`, making the current id permanently null, while
shadow `status` and `show` use different implicit-session resolvers. Session intent/confirmation ownership is defined in
[`docs/design.md` §3.3](../../../design.md#33-session-file-schema-forgesessionjson).

## Acceptance Criteria

- Current proxy id comes from confirmed launch routing while template/base intent remains unchanged.
- `shadow show` and `shadow status` share one resolver and select the same explicit/current/sole-local session.
- Ambiguous or missing session errors retain clean human and JSON failure behavior.
- Retain policy command-core and CLI regressions.

## Compatibility and Exclusions

Do not move proxy ids into `ProxyIntent`, change policy intent/override ownership, or merge terminal and `%policy`
implementations (O044).
