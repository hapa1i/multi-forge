# Close proxy failure lifecycles

**Epic**: [`epic_wave6_correctness_maintenance`](../epic_wave6_correctness_maintenance/card.md).

**Lane**: `todo/` -- accepted Wave 6 work; parked pending fail-first regressions.

**Findings**: O014 and O026.

## Goal

Keep proxy ownership discoverable after failed restarts and close upstream stream/client contexts when a non-200 body
read itself fails.

## Evidence and Authority

On `246aaff1`, failed `start_proxy(..., skip_proxy_file=True)` removes the registry entry while preserving `proxy.yaml`.
Both passthrough transports read non-200 bodies before entering a cleanup guard. The lifecycle and passthrough contracts
are in [`docs/design_appendix.md` §A.1](../../../design_appendix.md#a1-proxy-overlay-schema-364--user-edit-surface).

## Acceptance Criteria

- A failed restart restores the prior registry entry, or leaves a stopped owned entry when only the config existed.
- A non-200 body-read exception closes stream and client contexts, records failure once, and returns the stable upstream
  failure response without leaking provider content.
- Successful startup and ordinary non-200 relay behavior remain unchanged in both transports.
- Retain regressions and run the targeted proxy Docker integration.

## Compatibility and Exclusions

Do not delete user-owned proxy files, change adoption rules, or alter successful response/header relay semantics.
