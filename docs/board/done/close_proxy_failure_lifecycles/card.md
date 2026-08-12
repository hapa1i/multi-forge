# Close proxy failure lifecycles

**Epic**: [`epic_wave6_correctness_maintenance`](../../doing/epic_wave6_correctness_maintenance/card.md).

**Lane**: `done/` -- shipped in PR #167 (`33e3db7f`) after independent review.

**Findings**: O014 and O026.

## Goal

Keep proxy ownership discoverable after failed restarts and close upstream stream/client contexts when a non-200 body
read itself fails.

## Evidence and Authority

Rechecked on merged `main` at `4774f69e`: failed `start_proxy(..., skip_proxy_file=True)` removes the registry entry
while preserving `proxy.yaml`. Both passthrough transports read non-200 bodies before entering a cleanup guard. The
lifecycle and passthrough contracts are in
[`docs/design_appendix.md` §A.1](../../../design_appendix.md#a1-proxy-overlay-schema-364--user-edit-surface) and
[§A.11](../../../design_appendix.md#a11-intercept-audit-and-request-logging-configuration-7x).

## Acceptance Criteria

- A failed restart restores the prior registry entry, or leaves a stopped owned entry when only the config existed.
- A non-200 HTTP transport read error closes stream and client contexts, records failure once, and returns the stable
  upstream failure response without leaking provider content; cancellation still propagates after cleanup.
- Successful startup and ordinary non-200 relay behavior remain unchanged in both transports.
- Retain regressions and run the targeted proxy Docker integration.

## Implementation Outcome

Proxy startup now snapshots an existing entry before the temporary `starting` row replaces it. Spawn or health failure
restores that snapshot; a config-only restart retains the attempted identity as pid-less `stopped` ownership. Recovery
updates only the unchanged `starting` row, so a concurrent replacement is not overwritten.

Both raw streaming transports now read non-200 bodies inside the stream/client cleanup guard. A transport read failure
closes both contexts, records one failed completion, and returns the transport's stable HTTP 502 body without relaying
partial provider content. Readable non-200 responses retain their original status, body, and safe headers.

## Verification

The retained regression failed in the four expected cases on unchanged production code from merged `main` at `4774f69e`,
while both ordinary non-200 relay controls passed (`4 failed, 2 passed`). All six cases now pass. The focused
orchestrator and Anthropic/Responses transport modules pass (`193 passed`), as does the full proxy unit package
(`814 passed`).

Full unit tests pass (`8,981 passed`, one existing platform skip, 122 deselected), as do all 753 marked regressions.
Five targeted Docker integrations pass, covering real create/start/list/stop and streaming/non-streaming Anthropic error
relay. Design and end-user proxy contracts now record failed-start ownership and non-200 read-failure behavior.

Full pre-commit and an explicit new-file pass both succeed. All 720 local links across 287 board Markdown files have
existing targets, changed-document fragments resolve, and the post-merge 12-member Wave 6 lane graph is 4 `done` / 0
`doing` / 8 `todo`; size and diff checks pass. Both GitHub workflows passed before merge.

## Compatibility and Exclusions

Do not delete user-owned proxy files, change adoption rules, or alter successful response/header relay semantics.
