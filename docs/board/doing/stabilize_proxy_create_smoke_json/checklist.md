# Stabilize proxy create smoke-test JSON checklist

Current focus: finish final repository gates and prepare the verified D016 change for independent review.

## Activation and reproduction

- [x] Start `fix/stabilize-proxy-create-smoke-json` from merged PR #149 at `c20b8d10`.
- [x] Close O002, move D016 from `todo/` to `doing/`, and advance the Wave 5 cursors without activating D017.
- [x] Add a marked D016 regression for failed `proxy create --json --smoke-test`.
- [x] Confirm the retained regression fails on `c20b8d10` because stdout contains two top-level JSON documents and the
  command exits zero despite failed verification.

## Result and exit contract

- [x] Emit exactly one JSON object containing creation facts and the smoke-test result when `--smoke-test` is present.
- [x] Exit zero for a passing smoke probe and non-zero for a failing probe without deleting or stopping the created
  proxy.
- [x] Preserve the existing JSON object and exit behavior when `--smoke-test` is omitted.
- [x] Preserve the human-mode smoke diagnostics and failure status.

## Compatibility coverage

- [x] Cover `spawn`, `reuse`, and `adopt` creation sources with the same one-result schema.
- [x] Keep human-only smoke progress/diagnostics out of JSON stdout while nesting structured probe detail; pin both
  output modes and streams.
- [x] Leave `proxy start --smoke-test`, template selection, port allocation, and registry semantics unchanged.
- [x] Preserve `--no-start` as config-only creation without attempting smoke verification.

## Acceptance tests

| Test                       | Fixture                                     | Assertion                                                         |
| -------------------------- | ------------------------------------------- | ----------------------------------------------------------------- |
| Failed JSON smoke          | successful create; failed probe             | one parseable object; `smoke_test.passed=false`; non-zero exit    |
| Successful JSON smoke      | successful create; passed probe             | one parseable object; `smoke_test.passed=true`; exit zero         |
| JSON without smoke         | successful create; no probe                 | existing top-level creation fields remain compatible              |
| Human smoke failure        | successful create; failed probe             | human diagnostic remains visible and command exits non-zero       |
| Source variants            | spawn, reuse, and adopted orchestration     | `source` remains accurate and smoke result is nested once         |
| Creation preservation      | failed probe after successful registration  | proxy remains registered/configured for recovery                  |
| Process-backed integration | live proxy with controlled upstream failure | JSON parses once; failure status does not roll back created proxy |

## Verification and closeout

- [x] Run focused proxy create, output-stream, and D016 regression tests: 176 passed.
- [x] Run the full unit and marked regression suites: 8,899 passed / 1 skipped and 686 passed, respectively.
- [x] Run the complete Docker proxy create/start integration class: 3 passed.
- [x] Synchronize CLI design/operator/QA docs only with shipped behavior; QA now contains 618 assertions.
- [x] Build the wheel and verify both changed bundled QA resources; resolve all 194 local links/fragments across the 15
  changed Markdown files; confirm the change log measures 20,622 tokens / 1,382 physical lines.
- [x] Run final `make pre-commit`, stale-lane scans, and diff checks after recording verification evidence.
- [ ] Obtain independent review and merge before activating D017.
