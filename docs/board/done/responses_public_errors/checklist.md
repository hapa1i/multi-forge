# Verify Responses refusals

Merged as `98b66c1c`. Its tree matches the tested PR head `adcef226`. Both Python versions and the pre-commit suite
passed the [PR checks](https://github.com/hapa1i/multi-forge/pull/308/checks).

| Fixture                                              | Expected HTTP 400 response                          |
| ---------------------------------------------------- | --------------------------------------------------- |
| Source resolution raises an unexpected value error   | Configuration error and request ID                  |
| Request preparation raises an unexpected value error | Invalid request and request ID                      |
| Required ZDR rejects an unsupported tool             | Guidance about allowed tools and the policy setting |

- [x] Verify both generic failures withheld the internal detail. The regression failed in both cases before the fix.
- [x] Preserve the refusal code, request ID, and tool-policy guidance. Document the operator diagnostics in the
  [Codex proxy guide](../../../end-user/codex_proxy.md#spend-and-diagnostics).
- [x] All 204 focused tests and 47 loopback integration tests passed, including OpenRouter Responses, LiteLLM streaming
  cost, and the failed-smoke CLI case.
- [x] The [CodeQL scan of the merge](https://github.com/hapa1i/multi-forge/actions/runs/45160349728) passed. GitHub
  marked [alert #35](https://github.com/hapa1i/multi-forge/security/code-scanning/35) fixed on `main` at 10:57:01 UTC on
  2026-11-23. Recorded the fix in the [change log](../../change_log.md#keep-internal-errors-out-of-responses-replies).
