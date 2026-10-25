# October model evidence

Metadata checked on 2026-10-24 using OpenRouter's public [model inventory](https://openrouter.ai/api/v1/models) and
[ZDR endpoint inventory](https://openrouter.ai/api/v1/endpoints/zdr). All three have active ZDR endpoints; requests must
still send `provider.zdr: true`. Endpoint availability and prices can change.

| Model                    |   Context | Gateway output cap | Efforts                       |
| ------------------------ | --------: | -----------------: | ----------------------------- |
| Kimi K3.1 Pro            | 1,048,576 |            943,718 | low, high, max                |
| MiniMax M3.1 Flash       | 1,048,576 |            524,288 | low, medium, high, xhigh, max |
| DeepSeek V4.1 Flash 1017 | 1,048,576 |            393,216 | low, high, max                |

The Kimi route omits temperature, top-p, and top-k. Its
[native model documentation](https://www.kimi.com/code/docs/en/kimi-code/models) requires thinking; Forge does not
advertise the gateway's conflicting `none` effort. Highspeed is a provider endpoint for the same model, not another
catalog identity. The [release announcement](https://www.kimi.com/en/blog/kimi-k3-1-pro) schedules weights for November
4\.

[MiniMax's model card](https://huggingface.co/MiniMaxAI/MiniMax-M3.1-Flash) and
[published weights](https://huggingface.co/MiniMaxAI/MiniMax-M3.1-Flash/tree/main) use the MiniMax community license.
OpenRouter advertises mandatory reasoning and effort controls for M3.1 Flash; the previous M3 entry has no effort knob.

[DeepSeek's model card](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash-1017) identifies a distinct October 17
snapshot under MIT. Keep the undated V4.1 Flash entry separately selectable.

## Verification

A bounded direct Kimi probe returned a tool call and accepted the following tool-result turn both with and without
`reasoning_details` (HTTP 200). Reported total cost for the three requests was $0.002608. This confirms acceptance of
the current translated history, not equivalence to native reasoning continuity. Forge's translated Messages path omits
provider reasoning blocks. Default promotion and a general reasoning-history transport change are outside this PR.

Request-capture tests found that OpenRouter's parameter translator mutated a caller-owned `extra_body`, allowing
reasoning and verbosity from one request to leak into another. The translator now copies that mapping; a regression
checks the next request as well as the original settings.

All test runs use `PYTHON_DOTENV_DISABLED=1`. Live tests resolve the existing OpenRouter credential and pass it only
through the child environment; test proxies and configuration snapshots use temporary Forge homes.

| Check                                               | Result                                                |
| --------------------------------------------------- | ----------------------------------------------------- |
| `make test-unit`                                    | 11,170 passed; 120 integration tests deselected       |
| `make test-regression`                              | 2,154 passed                                          |
| Live proxy and existing Docker workflow integration | 18 passed                                             |
| Snapshot and new three-worker Docker integration    | 4 passed                                              |
| `forge workflow list-models --available --json`     | All three ready                                       |
| `make build`                                        | Wheel and sdist built                                 |
| `./scripts/test-wheel-runtime.sh`                   | Clean install and LiteLLM lifecycle passed            |
| Clean wheel model checks outside checkout           | All three catalogs, routes, templates, workers passed |
| `make pre-commit`                                   | Passed; refreshed proxy-guide token cache             |

The live integration file exercises each model with streaming and unary tool calls, then replays the returned tool block
with a tool result. All six cases passed with ZDR required and nonzero usage. The shared OpenRouter SDK tests cover
reported cost and cache read/write accounting; no minimum cache-hit rate is claimed for these short prompts.

Reproduce the integration selections with:

```bash
./scripts/test-integration.sh tests/integration/proxy/test_october_open_models_e2e.py \
  tests/integration/cli/test_workflow_integration.py -q
./scripts/test-integration.sh tests/src/proxy/test_october_models_integration.py \
  tests/integration/cli/test_workflow_integration.py::TestRunMultiReviewE2E::test_october_workers_keep_exact_models_on_a_shared_proxy -q
```

The initial unit run exposed a stale expected-alternatives list. After updating it, all 89 configuration-loader tests
and the complete unit rerun passed. Initial formatting and token-cache failures were also corrected.

Review follow-up verification on 2026-10-25: the catalog, session-route, and QA contract selection passed all 94 tests;
the six live proxy cases passed after moving their fixture into `conftest.py`. The rebuilt wheel/sdist includes the
updated QA resources, verified from an isolated wheel installation with 687 parsed assertions and all three October
alternatives. The catalog assertions now protect Kimi's forced-tool rejection flag. Workflow guidance and proxy examples
are corrected; guide-size cleanup is tracked in the
[partition proposal](../../proposed/proxy_model_guidance_partition/card.md). Full pre-commit passed; the refreshed
proxy-guide count is 28,304 Opus tokens.
