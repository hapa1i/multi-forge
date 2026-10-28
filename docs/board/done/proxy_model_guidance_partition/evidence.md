# Proxy/model guidance partition evidence

Base: `6c8d0999`. Verification date: 2026-10-28. This partition changes documentation only.

## Ownership and preservation

| Topic                                                                       | Authority                                                                                      |
| --------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| Role selection, API capabilities, model versions and migration requirements | [Model selection](../../../end-user/model_selection.md)                                        |
| Proxy setup, saved snapshots, backend restart order and template reset      | [Proxy operations](../../../end-user/proxy.md#updating-saved-proxy-and-backend-configurations) |
| ZDR endpoint evidence, substitutions and opt-out                            | [Proxy ZDR policy](../../../end-user/proxy.md#openrouter-zero-data-retention-zdr)              |
| Translated output limits and reasoning history                              | [Proxy transport](../../../end-user/proxy.md#translated-response-limits-and-history)           |
| Worker inventory, default quorum and readiness                              | [Workflows](../../../end-user/workflow.md#quick-start)                                         |

Compared both guides against the base: no model identifiers or external source URLs were removed, and all existing
heading anchors remain. The two old proxy upgrade headings and API-capabilities heading forward to the moved sections.
Living links in the skills and workflow guides target model selection directly. The user guide index describes the new
split.

The review retained the model-specific effort/sampling and tool-choice restrictions, Google AI/Vertex distinctions,
Argon pricing dates, LiteLLM metadata requirements, Fable native-history caveat, dated model identities, and working
selection examples. Fable/Qwen endpoint audit dates now live with the ZDR policy. Repeated backup/recreate/restart steps
are consolidated in the proxy guide.

## CLI and snapshot verification

Used the checkout's `.venv/bin/forge` with `PYTHON_DOTENV_DISABLED=1`, a temporary `FORGE_HOME`, synthetic keys, and a
temporary working directory outside the project. No proxy/backend process or model inference was started.

- Checked 18 CLI help surfaces: proxy create/show/edit/validate/start/stop; template show/edit/reset; backend
  list/create/delete/start/stop; session start/resume; workflow panel/list-models. Documented options are admitted.
- Read all 20 user-facing templates with `forge proxy template show <name> --raw`; each matched its bundled YAML.
  Checked the Astra, Claude and Gemini tier tables and listed OpenRouter alternatives against that output.
- Ran `forge proxy create openrouter-openai --name docs-fresh --opus-reasoning high --no-start`, then
  `forge proxy validate docs-fresh` and `forge proxy show docs-fresh --raw`. The snapshot has Astra tiers and the high
  Opus effort override.
- Created a custom OpenAI template selecting GPT-6 Sol for Opus, then created `docs-saved` from it with `--no-start`.
  Materialized the isolated backend with `forge model backend create litellm`.
- Ran `forge proxy template reset openrouter-openai --yes`. The custom template disappeared, raw template output
  returned to the built-in defaults, and both saved proxy and backend bytes remained unchanged. A new proxy created
  after reset selected Astra. Explicitly editing the saved proxy to Astra then passed `forge proxy validate`.
- Checked the materialized backend's Astra route, explicit Responses flags for GPT-6.1 Sol/Sol/Luna, complete metadata
  for the models that need overrides, and Argon's local cache threshold of 4096. Astra uses LiteLLM's packaged metadata.

The old model guide's instruction to reset existing proxies with `forge proxy template reset` was incorrect. The
replacement distinguishes template defaults for future proxies from explicitly updating saved proxy/backend snapshots.
Live startup and upstream smoke tests were not run for this documentation-only change; their command syntax was checked.

## Token and repository checks

The final formatted guides were counted with
`./scripts/count-tokens.py --methods claude-opus-5 --per-file --json docs/end-user/proxy.md docs/end-user/model_selection.md`.
Both results came from Anthropic's count endpoint without fallback or inference and are cached against their exact
SHA-256 hashes in `.file-token-counts.json`.

| Guide                | Opus tokens | Card limit |
| -------------------- | ----------: | ---------: |
| `proxy.md`           |      22,232 |     23,000 |
| `model_selection.md` |      13,893 |     23,000 |

The proxy guide decreased by 6,072 tokens from the base's verified 28,304. The model guide clears the local screen, but
its explicit provider count is retained to prove this card's acceptance limit. The cache was written with the repository
checker's cache writer using these provider results.

`make pre-commit-md`, `uv run --locked pre-commit run --files .file-token-counts.json`, and `git diff --cached --check`
pass on the final partition. The earlier stale-cache failure is resolved by the recount. Existing size-target warnings
concern the unrelated session/workflow guides and two historical board files; no new size warnings remain.
