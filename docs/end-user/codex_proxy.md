# Launch Codex through a Forge proxy

`forge codex start --proxy` opens a foreground Codex TUI without creating a Forge session. Supply a proxy ID to reuse
that exact instance, or a template name to resolve or start one. Codex 0.141.0 or newer is required. Forge verifies the
running proxy's identity and Responses capability before launching.

```bash
forge codex start --proxy codex-responses-openrouter
forge codex start --proxy codex-responses-openrouter -- -m google/gemini-4-carbon
forge codex start --proxy codex-responses-local --sandbox read-only
```

The direct template uses `OPENROUTER_API_KEY` from the environment or the active Forge credential profile. Its default
model is `openai/gpt-6.2-astra`. Pass Codex arguments after `--`. Unrecognized slugs such as the tested Gemini model can
trigger Codex's fallback model metadata warning. Selection by slug works with Codex's built-in metadata.

The direct route supports `POST /v1/responses`. Codex sends full history for each turn, including local compaction.
Forge preserves tool calls, arguments, results and opaque reasoning by JSON value and streams upstream events as they
arrive. Live tool continuation with encrypted reasoning was observed on Gemini. Astra emitted no encrypted item in the
live test. The LiteLLM template also relays Responses subresources and uses the `openai-api` credential. Both templates
continue to serve translated Messages requests.

## Privacy and routing

Forge removes the top-level `client_metadata` and `prompt_cache_key` on every direct Responses create. These fields can
carry the installation, session or thread ID. The provider therefore cannot group cached prompts using Codex's supplied
cache key. The Messages setting `provider_trace.inject_provider_user` controls a different, Forge-generated ID.

By default the direct route sets `provider.zdr=true`, admits only client-executed tools, and launches Codex with web
search disabled. A configured `zdr_fallbacks` entry applies even across model families. Forge prints both slugs at
launch when they differ and keeps the shape Codex built for the requested model. The destination may reject that shape.
Launch with the destination slug if you want Codex to use that model's metadata.

The saved proxy setting `allow_non_zdr=true` permits caller-supplied routing and hosted tools. OpenRouter account and
guardrail policies still apply. An account ZDR diagnostic points to OpenRouter's privacy settings. A text-only ZDR
refusal identifies the endpoint restriction. A ZDR-eligible model can resolve either.

The child receives a loopback token and temporary `-c` provider settings. Forge strips inherited Codex, OpenAI and
OpenRouter credentials and Forge session and run-tree variables. A nested Forge command can still load the active
credential profile or the project's `.env`. Set `PYTHON_DOTENV_DISABLED=1` to disable dotenv loading.

## Spend and diagnostics

Direct Responses caps use the OpenRouter account charge in `usage.cost`, rounded per request to integer microdollars. A
zero account charge on BYOK counts as zero. A separate bill from the BYOK provider falls outside this cap. A stream that
ends before its terminal usage can also leave spend uncounted. Codex can omit `max_output_tokens`, so OpenRouter can
require more available credit to admit a request than it ultimately charges.

If Codex shows HTTP 429, run `forge proxy metrics <id>` to see the active caps and their settings. For an individual
request, use `forge telemetry trace show <request-id>` and
`forge model backend reconcile openrouter --request-id <request-id>`. A fresh generation may take several seconds to
appear remotely.
