# GPT-6.2 model support

- [x] Verify the two native IDs, the four OpenRouter IDs, reasoning and sampling support, and Azure ZDR listings.
- [x] Update catalog profiles, session routes, template defaults and workflow workers. Verify the fresh and saved cases.
- [x] Verify bundled LiteLLM capabilities and token/cache prices. Record the pinned gateway's Ultrafast limitation.
- [x] Update the operator guide and packaged QA expectations. Build an sdist and wheel and exercise a clean
  installation.
- [ ] Record the merge in the change log and move the card to `done/`.

| Check              | Fixture                                                    | Verified result                                                                                                                          |
| ------------------ | ---------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| Tier selection     | Fresh general and Codex templates                          | General Sonnet/Opus and Codex Opus select 6.2 Astra.                                                                                     |
| Explicit selection | Aliases, versioned IDs and shared OpenRouter proxy         | The planner selects the available provider. All four 6.2 workers forward their exact model IDs.                                          |
| Upgrade            | Materialized proxy and backend                             | The saved tier still serves its prior model. Backend recreation preserves file contents, permissions and modification time.              |
| Tool calls         | Live native OpenAI and OpenRouter, unary and streaming     | Standard Astra and Sol return the requested tool on each route. Both OpenRouter Pro variants return completions.                         |
| Pricing            | LiteLLM 1.102.2 with offline model metadata                | Standard, Flex and Priority pass across the 272K boundary. Above it Ultrafast reports the Standard price despite the configured premium. |
| Installed CLI      | Clean wheel, isolated Forge home and live OpenRouter proxy | All four workers appear ready. A blind `gpt-6.2-astra` panel completes. The wheel's local LiteLLM starts, reports healthy and stops.     |

`make test-unit` passed 11,761 tests and `make test-regression` passed 2,541. The focused integration runs covered 32
cases, including the local and remote LiteLLM templates against a disposable gateway, retained backend configurations,
shared-proxy routing, and direct Codex and mixed Claude/Codex panels. `make pre-commit` passed, including the Markdown
link audit across 796 source files.
