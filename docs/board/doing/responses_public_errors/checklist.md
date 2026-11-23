# Verify Responses refusals

Branch `codex/responses-safe-errors`, based on `main` at `37eb0bd6`.

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
- [ ] After merge, verify the alert on `main`, record the outcome in the change log and close the card.
