# Correct daily-review regressions checklist

Current focus: shipped in PR #229 (`da34bcb3`) with all five GitHub checks passing; the card is closed before Wave 8
Batch 5 activation.

## Phase 1 -- Provider dispatch boundary

- [x] Add streaming and non-streaming regressions for lazy credential and client-construction failures across LiteLLM
  and OpenRouter.
- [x] Move provider-attempt signaling to the actual SDK dispatch boundary without changing direct callers, retries, or
  provider-trace joins.
- [x] Retain exactly one incomplete trace for a request that reaches provider dispatch and then fails.

## Phase 2 -- Workflow integer types

- [x] Add manifest regressions for `true` and `false` across `max_content_length`, `throttle_seconds`, and
  `max_cache_entries`, including the reviewer-bypass reproduction.
- [x] Reject booleans with workflow-entry and offending-field context while preserving valid integer/default/null forms.

## Phase 3 -- Stop diagnostics

- [x] Add a forced-color mixed-stream regression that retains the failing pytest node id and removes terminal controls.
- [x] Sanitize decoded output before secret redaction and summary selection without changing fixed argv, environment,
  classification, or bounds.

## Phase 4 -- Verification and publication

- [x] Run the focused proxy, workflow-policy, and Stop-verification suites and record results.
- [x] Run required targeted proxy and policy-hook Docker integration tests.
- [x] Run full unit and regression suites plus `make pre-commit`, board/link, and diff gates.
- [x] Verify the normative design contracts remain accurate; update them only if the implementation changes a contract.
- [x] Review and commit only confirmed paths, push the branch, and open draft PR #229 without activating Wave 8 Batch 5.
- [x] Confirm merge `da34bcb3`, record the shared evidence, repoint inbound links, and move the card to `done/`.

## Acceptance tests

| Boundary                  | Fixture                                                                 | Assertion                                                    | Test file                                                          |
| ------------------------- | ----------------------------------------------------------------------- | ------------------------------------------------------------ | ------------------------------------------------------------------ |
| Lazy provider setup       | real LiteLLM/OpenRouter client; missing credential or constructor error | no provider trace in either request mode                     | `tests/regression/test_bug_o045_failed_provider_attempt_traces.py` |
| Failed dispatch           | callback-aware provider fake that fails after signaling                 | exactly one joined incomplete trace                          | `tests/regression/test_bug_o045_failed_provider_attempt_traces.py` |
| Workflow integer controls | each integer field receives YAML boolean values                         | atomic construction failure names entry and field            | `tests/regression/test_bug_o083_unknown_workflow_policy_keys.py`   |
| Reviewer bypass           | matching filtered/reviewed branch with `max_content_length: false`      | config is rejected before evaluation                         | `tests/regression/test_bug_o083_unknown_workflow_policy_keys.py`   |
| Colored pytest output     | real forced-color failure summary plus warning-only stderr              | bounded diagnostic retains node id without terminal controls | `tests/regression/test_bug_d006_stop_test_suite_contract.py`       |
| Truncated control string  | one-line OSC/DCS intro followed by failure lines and a later ST         | later failure lines remain available for selection           | `tests/regression/test_bug_d006_stop_test_suite_contract.py`       |
| Decoded C1 controls       | UTF-8 bytes for the full U+0080--U+009F control range                   | no C1 control survives diagnostic sanitization               | `tests/regression/test_bug_d006_stop_test_suite_contract.py`       |

Provider evidence: the 10-test fail-first slice failed at every new forwarding/setup assertion on `5246473e`; after the
dispatch seam moved, the adjacent adapter/core-client/provider-trace slice passed 130 tests.

Workflow evidence: all six boolean-control cases failed first because policy construction succeeded; after the dataclass
invariant was added, the adjacent workflow config/policy/stage and O083 regression slice passed 91 tests.

Stop evidence: the real `PY_COLORS=1` regression failed first by persisting warning-only stderr; terminal sanitization
before redaction restored the colored node id. Review follow-up reproductions confirmed that multiline OSC/DCS matches
could swallow later failures and decoded C1 controls survived; bounding control strings to one line and removing the
full C1 range preserved both failure lines, and the adjacent Stop-verification slice passed 28 tests.

Final verification: the combined focused slice passed 249 tests; the manifest/Stop hook and local LiteLLM
non-streaming/streaming Docker boundaries passed four tests, and the review follow-up Stop Docker boundary passed;
`make test-unit` passed 9,331 tests with 124 deselected; and the clean `make test-regression` rerun passed 1,059 tests.
`make pre-commit`, `git diff --check`, the 420-document and 1,028-local-link board check, and the design-size checks
passed (`design.md` 30,000 Opus tokens, the former consolidated design appendix 29,988, `design_workflows.md` 18,052).
The existing attempt-boundary, strict workflow-type, and bounded Stop-diagnostic wording remains accurate, so no
normative design edit is required.
