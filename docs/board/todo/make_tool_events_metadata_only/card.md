# Make tool-event diagnostics metadata-only

**Epic**: [`epic_proxy_diagnostic_data_hygiene`](../epic_proxy_diagnostic_data_hygiene/card.md).

**Lane**: `todo/` -- accepted and parked behind the converter-log member.

**Finding**: D035 (Wave 5 MEDIUM, narrowed after merged-main recheck).

## Goal

Replace free-form debug tool-event payloads and ordinary client-failure plaintext with bounded structural metadata while
preserving the separately opted-in tool-failure diagnostic plane.

## Corrected Evidence

A disposable test on merged `main` at `c9c4bc2e` wrote a 17,000-character caller value unchanged through
`log_tool_event(details=...)`; `_check_client_tool_failures` also emitted the client error prefix at WARNING before
scheduling the JSONL event. Source inspection found another raw schema payload in the converter caller.

The historical row is only partly current: `log_tool_event` now writes files through `open_secure_append` (`0600`), and
global `forge logs clean` plus optional `log_retention_days` include the `tool_events` directory. The remaining defect
is free-form, unbounded per-event data and missing explicit `0700` hardening for its directories. Default unlimited
global retention is a documented operator choice and is not replaced by a new plane-specific setting here.

## Expected Behavior

The [§A.11 no-plaintext posture](../../../design_appendix.md#a11-intercept-audit-and-request-logging-configuration-7x)
applies to debug diagnostics as well as request logs. Tool events may retain stage, status, bounded tool/request IDs,
counts, flags, parameter names, and event enums. Tool inputs, schemas/descriptions, tool-result/error content, and
arbitrary nested caller data do not belong in this plane.

## Scope

- Replace the free-form `details` sink contract with a structurally allowlisted, bounded metadata shape and update every
  caller atomically.
- Record schema structure, stripped parameter names, tool-call lifecycle, and client-failure presence without caller
  values.
- Make the ordinary client-tool-failure WARNING metadata-only.
- Harden the Forge log and `tool_events` directories to owner-only access while retaining `0600` files.
- Leave `log_tool_failures=true` behavior, truncation, and payload fields unchanged because that plane is explicit
  opt-in.
- Reuse global log cleanup semantics; do not add another retention owner or startup pruner.

## Acceptance Criteria

| Test                        | Fixture                                                  | Assertion                                                                   | Test File                                                |
| --------------------------- | -------------------------------------------------------- | --------------------------------------------------------------------------- | -------------------------------------------------------- |
| Tool-result confidentiality | failed Write/Read result with content and input canaries | JSONL and ordinary logs contain metadata but no canary                      | `tests/regression/test_bug_d035_tool_event_plaintext.py` |
| Schema confidentiality      | tool schema description/property canaries                | event records contain counts/names only                                     | `tests/src/proxy/test_proxy_logging.py`                  |
| Bounded schema              | oversized IDs, names, and parameter-name collections     | every retained field is capped deterministically                            | `tests/src/proxy/test_proxy_logging.py`                  |
| Filesystem hardening        | pre-existing permissive log directories and shard        | directories become `0700`; shard remains `0600`                             | `tests/src/proxy/test_proxy_logging.py`                  |
| Opt-in failure control      | `log_tool_failures=true` with a large Write payload      | existing bounded plaintext failure record still writes                      | existing tool-failure tests                              |
| Global cleanup control      | old tool-event shard and configured `log_retention_days` | existing CLI cleanup still discovers/removes it; no second retention policy | existing `tests/src/cli/test_logs_command.py` coverage   |

## Compatibility and Exclusions

The debug-only `tool_events` detail shape is internal and undocumented; a clean break is appropriate. The top-level
timestamp/request/tool/status/stage fields remain for diagnostics. The explicit `tool_failures` schema, request
diagnostics, audit/downstream telemetry, O041 task ownership, and D036 request-ID validation are outside this member.

## Verification

Retain a marked D035 regression, run focused proxy logging/converter/server tests, the full regression suite, a targeted
translated-proxy Docker integration, CLI log-clean controls, and `make pre-commit`.
