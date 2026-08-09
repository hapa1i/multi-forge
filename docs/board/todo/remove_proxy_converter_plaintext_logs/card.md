# Remove plaintext from proxy converter logs

**Epic**: [`epic_proxy_diagnostic_data_hygiene`](../epic_proxy_diagnostic_data_hygiene/card.md).

**Lane**: `todo/` -- accepted and parked; activate only after the admission record is reviewed and merged.

**Findings**: O037, O038, and O042 (Wave 5 MEDIUM).

## Goal

Make translated request/response converter logs metadata-only and avoid formatting caller payloads for suppressed DEBUG
records without changing conversion results.

## Evidence

Rechecked on merged `main` at `c9c4bc2e`. At DEBUG, `convert_anthropic_to_openai` logged system, message, and
tool-schema canaries through the full-request and original-schema dumps. `convert_openai_to_anthropic` logged malformed
string and dict arguments plus a non-function tool-call payload verbatim. With the logger held at INFO, a formatting spy
still ran twice for the suppressed request/schema messages.

## Expected Behavior

[`docs/design_appendix.md` §A.11](../../../design_appendix.md#a11-intercept-audit-and-request-logging-configuration-7x)
and the durable
[proxy-log hygiene note](../../impl_notes.md#no-caller-content-in-proxy-logs-redactor-excludes-caller-free-text-proxy_log_hygiene-review-2026-06-16)
permit counts, flags, enums, bounded identifiers, and structural metadata in ordinary module logs. Caller prompts,
message content, tool descriptions/schemas, raw arguments, and whole tool-call objects require an explicitly opted-in
raw-content plane.

## Scope

- Replace the full intermediate-request dump with a lazy metadata summary.
- Remove original tool-schema content from ordinary logs; retain only bounded structural counts needed for diagnosis.
- Report malformed argument type/length and fallback action without the raw value or exception rendering that embeds it.
- Report non-function tool-call type/key metadata without serializing the whole object.
- Preserve the explicit `stream_chunks` raw-debug path and its existing guard/cap.
- Retain conversion return values and the raw-argument fallback delivered to the client.

## Acceptance Criteria

| Test                           | Fixture                                                 | Assertion                                                             | Test File                                                                 |
| ------------------------------ | ------------------------------------------------------- | --------------------------------------------------------------------- | ------------------------------------------------------------------------- |
| Request/schema confidentiality | system, message, description, schema, and stop canaries | no canary reaches converter records; metadata summary still appears   | `tests/regression/test_bug_o037_o038_o042_proxy_converter_log_hygiene.py` |
| Malformed argument fallback    | invalid JSON string and wrong-typed arguments           | fallback output is unchanged; WARNING/ERROR contains type/length only | same regression + `tests/src/proxy/test_converters_log_hygiene.py`        |
| Non-function tool call         | caller-controlled custom tool-call mapping              | skip behavior remains; log contains no mapping value                  | `tests/src/proxy/test_converters_log_hygiene.py`                          |
| Suppressed DEBUG cost          | logger above DEBUG and formatting spy                   | request/schema payload formatters are not invoked                     | marked regression                                                         |
| Explicit raw stream opt-in     | `stream_chunks=true`, DEBUG, bounded chunk              | existing opt-in dump remains available and capped                     | existing converter log-hygiene coverage                                   |

## Compatibility and Exclusions

This changes internal log text only. It does not change API wire formats, malformed-tool fallback data, config, durable
state, tool-event JSONL, request IDs, or the opt-in tool-failure plane. O035's `tool_choice:any` mapping and O041's task
lifetime issue remain separate findings.

## Verification

Retain a marked fail-first regression, run focused converter/logging tests, the full regression suite, a targeted local
LiteLLM translated-proxy integration, and `make pre-commit`.
