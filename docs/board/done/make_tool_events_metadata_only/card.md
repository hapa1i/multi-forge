# Make tool-event diagnostics metadata-only

**Epic**: [`epic_proxy_diagnostic_data_hygiene`](../epic_proxy_diagnostic_data_hygiene/card.md).

**Lane**: `done/` -- shipped in PR #158 (`ce7eb1ec`).

**Finding**: D035 (Wave 5 MEDIUM, narrowed after merged-main recheck).

## Goal

Replace free-form debug tool-event payloads and ordinary client-failure plaintext with bounded structural metadata while
preserving the separately opted-in tool-failure diagnostic plane.

## Corrected Evidence

A disposable test on merged `main` at `c9c4bc2e` wrote a 17,000-character caller value unchanged through
`log_tool_event(details=...)`; `_check_client_tool_failures` also emitted the client error prefix at WARNING before
scheduling the JSONL event. Source inspection found another raw schema payload in the converter caller.

The retained production-path regression then ran on this member's merged base, `a2fb0638`: four broken-behavior
assertions failed for schema plaintext, client-failure plaintext, unbounded identifiers/parameter names, and permissive
directories, while the separate pre-existing-shard `0600` control passed.

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
| Schema confidentiality      | tool schema description/property canaries                | event records contain counts/names only                                     | `tests/regression/test_bug_d035_tool_event_plaintext.py` |
| Bounded schema              | oversized IDs, names, and parameter-name collections     | every retained field is capped deterministically                            | `tests/regression/test_bug_d035_tool_event_plaintext.py` |
| Filesystem hardening        | pre-existing permissive log directories and shard        | directories become `0700`; shard remains `0600`                             | `tests/regression/test_bug_d035_tool_event_plaintext.py` |
| Opt-in failure control      | `log_tool_failures=true` with a large Write payload      | existing bounded plaintext failure record still writes                      | existing tool-failure tests                              |
| Global cleanup control      | old tool-event shard and configured `log_retention_days` | existing CLI cleanup still discovers/removes it; no second retention policy | existing `tests/src/cli/test_logs_command.py` coverage   |

## Compatibility and Exclusions

The pre-existing debug-only `tool_events` detail shape was internal and undocumented; a clean break is appropriate. The
top-level timestamp/request/tool/status/stage fields remain for diagnostics. The explicit `tool_failures` schema,
request diagnostics, audit/downstream telemetry, O041 task ownership, and D036 request-ID validation are outside this
member.

## Implementation Outcome

- Replaced the arbitrary mapping sink with frozen `ToolEventMetadata`; its exact field allowlist is regression-locked,
  event/status/stage/content enums are closed, identifiers and each stripped parameter name cap at 128 characters,
  stripped-name collections cap at 32 entries, and numeric counts cap at 1,000,000.
- Updated all schema, non-streaming, streaming, sanitizer, and client-failure callers. Schema events retain counts only;
  failure events and the adjacent WARNING retain content type/length and bounded identifiers, never tool input, schema,
  description, result, exception rendering, or arbitrary nested values.
- Corrected existing `$FORGE_HOME/logs` and `logs/tool_events` directories to `0700` on write while retaining the shared
  `open_secure_append` `0600` shard behavior. The opt-in `tool_failures` record and global cleanup owners are unchanged.

## Verification

The retained D035 module now passes five tests; the focused proxy/converter slice passes 49 tests, CLI log-clean
controls pass 55 tests, and the hermetic translated-proxy Docker slice passes three cases that prove payloads remain on
the wire but not in ordinary or structured diagnostics. Mypy and Pyright pass on the six touched Python units, the full
unit suite passes 8,934 tests with one skip and 122 deselections, and the full regression suite passes all 706 tests.
The first full-regression run exposed only cached-runtime-config test isolation (701 passed, five D035 writers gated
off); the retained module now resets that singleton around each case. Final pre-commit, board links, size, and diff
checks passed, independent review completed, and the member shipped in PR #158 (`ce7eb1ec`).
