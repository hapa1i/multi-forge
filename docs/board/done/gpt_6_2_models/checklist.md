# GPT-6.2 model support

- [x] Verify the two native IDs, the four OpenRouter IDs, reasoning and sampling support, and Azure ZDR listings.
- [x] Update catalog profiles, session routes, template defaults and workflow workers. Verify the fresh and saved cases.
- [x] Verify bundled LiteLLM capabilities and token/cache prices. Record the pinned gateway's Ultrafast limitation.
- [x] Update the operator guide and packaged QA expectations. Build an sdist and wheel and exercise a clean
  installation.
- [x] Record the merge in the [change log](../../change_log.md#make-gpt-62-astra-the-default-openai-model) and move the
  card to `done/`.

| Check              | Fixture                                                    | Verified result                                                                                                                          |
| ------------------ | ---------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| Tier selection     | Fresh general and Codex templates                          | General Sonnet/Opus and Codex Opus select 6.2 Astra.                                                                                     |
| Explicit selection | Aliases, versioned IDs and shared OpenRouter proxy         | The planner selects the available provider. All four 6.2 workers forward their exact model IDs.                                          |
| Upgrade            | Materialized proxy and backend                             | The saved tier still serves its prior model. Backend recreation preserves file contents, permissions and modification time.              |
| Tool calls         | Live native OpenAI and OpenRouter, unary and streaming     | Standard Astra and Sol return the requested tool on each route. Both OpenRouter Pro variants return completions.                         |
| Pricing            | LiteLLM 1.102.2 with offline model metadata                | Standard, Flex and Priority pass across the 272K boundary. Above it Ultrafast reports the Standard price despite the configured premium. |
| Installed CLI      | Clean wheel, isolated Forge home and live OpenRouter proxy | All four workers appear ready. A blind `gpt-6.2-astra` panel completes. The wheel's local LiteLLM starts, reports healthy and stops.     |

With an OpenRouter proxy saved from `24568e35`, all four short aliases identified the proxy and showed its edit command,
both with automatic reuse and with `--proxy saved-oai`. All four corresponding previous model IDs started sessions with
`--no-launch` in both modes. The saved `proxy.yaml` stayed byte-identical. Both original upgrade links resolve.
[Proxy upgrade](../../../end-user/proxy.md#picking-up-gpt-6-astra-defaults-after-an-upgrade) ·
[Model selection upgrade](../../../end-user/model_selection.md#picking-up-gpt-6-astra-defaults-after-an-upgrade)

A fresh plan-file review explicitly pinned to `gpt-6.2-astra` received HTTP 400 `model_not_found` on the QA binary
(0.149.1). The same ChatGPT subscription completed a low-effort review on 0.170.0. Forge parsed an `allow` verdict and
recorded 17,503 input and 33 output tokens. Both standard IDs appeared in the newer CLI's model list. With the version
check in place, supervisor setup refused both IDs on 0.149.1 and accepted them on 0.170.0. Regression tests exercise the
0.166.0 boundary and the exact `-m` argument for each model at dispatch.
[Codex model requirements](https://help.openai.com/en/articles/20001275-chatgpt-work-and-codex)

The March 1, 2027 rate change and gateway verification are tracked on the
[March Ultrafast pricing card](../../todo/gpt_62_ultrafast_pricing/card.md) and
[long-context accounting fix](../../doing/gpt_62_ultrafast_long_context_cost/card.md).

The initial 32 integration cases covered local and remote LiteLLM templates against a disposable gateway, retained
backend configurations, shared-proxy routing, and direct Codex and mixed Claude/Codex panels. The follow-up passed 15
integration cases covering saved routes, both plan-file hook adapters and native Codex reviewer isolation.

`make test-unit TEST_WORKERS=2` passed 11,761 tests, `make test-regression` passed 2,555 and `make pre-commit` passed.
The watchdog deadline test needed a rerun on macOS.

## Merge verification

On November 19, 2026, PR #300 merged as `1d710f90`. Its Git tree matches the verified PR head `1a14598e`.
[Merged PR](https://github.com/hapa1i/multi-forge/pull/300)

Both Python 3.11 and 3.13 passed the unit and regression suites and the clean-wheel LiteLLM smoke test. The
test-selection comparison, pre-commit and CodeQL also passed.
[Tests](https://github.com/hapa1i/multi-forge/actions/runs/44504103480) ·
[Pre-commit](https://github.com/hapa1i/multi-forge/actions/runs/44504103463) ·
[CodeQL](https://github.com/hapa1i/multi-forge/actions/runs/44504092611)

`make pre-commit-md` passed after the card moved to `done/`. The link audit checked 797 Markdown sources.
