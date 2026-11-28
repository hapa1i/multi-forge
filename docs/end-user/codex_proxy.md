# Launch Codex through a Forge proxy

`forge codex start --proxy` opens a foreground Codex TUI without creating a Forge session. Supply a proxy ID to reuse
that exact instance, or a template name to resolve or start one. Codex 0.141.0 or newer is required. Forge verifies the
running proxy's identity and Responses capability before launching.

```bash
forge codex start --proxy codex-responses-openrouter
forge codex start --proxy <id>
forge codex start --proxy <id> -- -m google/gemini-4-neon
forge codex start --proxy codex-responses-local --sandbox read-only
```

Every direct OpenRouter proxy serves Claude Code on `/v1/messages` and Codex on `/v1/responses` at the same port. Claude
keeps the saved tier mappings, alternatives and overrides. Codex defaults to the model in the proxy's default tier. For
example, the Gemini template selects `google/gemini-4-neon`, and `codex-responses-openrouter` selects
`openai/gpt-6.2-astra`. After `--`, use the full OpenRouter slug with `-m` or a top-level `-c model=...` override. An
explicit `-m` takes precedence. Codex can warn about missing built-in model metadata for an unfamiliar slug. The proxy
uses `OPENROUTER_API_KEY` from the environment or active Forge credential profile.

On direct OpenRouter launches, Forge sets `service_tier="default"` for this run. Codex omits the tier from upstream
requests even if your personal config selects `priority`. To request another tier, pass it after `--`, for example
`-- -c 'service_tier="flex"'`. Forge also passes `--no-daemon` when the installed Codex CLI supports it, which
explicitly selects the embedded server for the proxy settings.

After upgrading Forge, restart an existing listener with `forge proxy stop <id>` then `forge proxy start <id>`. Its
saved configuration stays in place. An older snapshot with a missing or blank `backend` uses its saved
`provider: openrouter` and upstream URL for Responses. An explicit conflicting backend is ineligible. Older Forge
launchers require the explicit Responses profile.

The direct route supports `POST /v1/responses`. Codex sends full history for each turn, including local compaction.
Forge preserves tool calls, arguments, results and opaque reasoning by JSON value and streams upstream events as they
arrive. Live tool continuation with encrypted reasoning was observed on Gemini. Astra emitted no encrypted item in the
live test. The LiteLLM template also relays Responses subresources and uses the `openai-api` credential.

## Managed sessions

```bash
forge session start coding --runtime codex --proxy openrouter-gemini
forge session resume coding
forge session start impl --runtime codex --resume-from plan --strategy structured --task "Implement the plan" --proxy openrouter-gemini
forge session resume impl --task "Run the tests"
```

Choose the route at creation. Omit both route flags or use `--no-proxy` for native OpenAI authentication. A proxy-backed
session uses the listener's credential and keeps its ID, template and loopback address. Restore that instance if it
stops. A replacement on the same port cannot receive the session's history.

The first launch uses the proxy's default model unless you pass `-- -m <slug>`. A bare resume uses the requested model
from the last verified, completed user turn, including a model selected in the TUI. With no completed turn, Forge uses
the initial launch selection. If the listener would map that slug to a different model, restore the original fallback or
start a fresh session. An explicit switch to a different requested model uses its current mapping.

If a completed turn is waiting for the proxy's accounting record, retry the same resume command after the record
arrives. Forge checks the original thread and launch again before sending history. A timed-out resume or a clean abort
that leaves the last completed foreground turn unchanged retains the previous model. If the rollout is incomplete or the
model evidence disagrees, restore the original evidence or start a fresh session. If the first launch never established
a thread, start a fresh session.

Use `forge session model show <name>` for saved and live routing facts, `forge session model history <name> --json` for
launch commitments, and `forge telemetry activity <name>` for this session's recorded spend. A sessionless `forge_proxy`
thread lacks the binding required for adoption.

## Privacy and routing

Forge removes the top-level `client_metadata` and `prompt_cache_key` on every direct Responses create. These fields can
carry the installation, session or thread ID. The provider therefore cannot group cached prompts using Codex's supplied
cache key. The Messages setting `provider_trace.inject_provider_user` controls a different, Forge-generated ID.

By default the direct route sets `provider.zdr=true`, admits only client-executed tools, and launches Codex with web
search disabled. It also refuses hosted plugin requests and online model variants and explicitly disables OpenRouter's
web plugin on the outgoing request. Check your OpenRouter organization and account plugin settings: locked defaults can
override request settings, and enabled plugins have their own retention policies.
[OpenRouter plugin defaults](https://openrouter.ai/docs/guides/features/plugins/overview)

A configured `zdr_fallbacks` entry applies even across model families. Forge prints both slugs at launch when they
differ and keeps the shape Codex built for the requested model. The destination may reject that shape. Launch with the
destination slug if you want Codex to use that model's metadata.

Codex launch reports when Messages inspection is enabled. Responses preserves opaque reasoning and has no body audit.
The saved setting `allow_non_zdr=true` permits caller-supplied routing and hosted tools. Forge discloses this at launch.
OpenRouter account and guardrail policies still apply. An account ZDR diagnostic points to OpenRouter's privacy
settings. A text-only ZDR refusal identifies the endpoint restriction. A ZDR-eligible model can resolve either.

The child receives a loopback token and temporary `-c` provider settings. Forge strips inherited Codex, OpenAI and
OpenRouter credentials and Forge session and run-tree variables. A nested Forge command can still load the active
credential profile or the project's `.env`. Set `PYTHON_DOTENV_DISABLED=1` to disable dotenv loading.

## Spend and diagnostics

For a local HTTP 400 refusal, check the error code. `configuration_error` points to the Responses backend or its base
URL. A request-policy refusal uses `invalid_request` and explains which field or setting to change. If preparation fails
unexpectedly, use the `X-Request-ID` response header to find the event in the proxy log.

Messages and Responses share the proxy’s daily and monthly spend caps. Direct Responses uses the OpenRouter account
charge in `usage.cost`, rounded per request to integer microdollars. A zero account charge on BYOK counts as zero. A
separate bill from the BYOK provider falls outside this cap. A stream that ends before its terminal usage can also leave
spend uncounted. Codex can omit `max_output_tokens`, so OpenRouter can require more available credit to admit a request
than it ultimately charges.

A completed or incomplete generation without a reported cost blocks the next direct Responses create until restart. A
malformed unary success returns HTTP 502. Forge records any usable final cost or blocks the next create under the
default policy. The direct route cannot track a background job to completion. It refuses background creates and treats
an unexpected pending response as lacking a final charge. An explicit stream error is recorded as a failed attempt.

The default applies even with no dollar cap. A reporting gap still permits Messages requests within the shared cap. On
`forge proxy create` and `forge proxy start`, add `--smoke-test --smoke-endpoint responses` to check one unary Responses
generation and its price. Choose `messages` to check Claude's endpoint. A bare `--smoke-test` checks Messages unless the
saved profile is `openai_responses_passthrough`. An unpriced Responses generation fails its smoke. To accept uncounted
charges, use the following commands.

```bash
forge proxy set <id> costs.on_unreported_cost=allow
forge proxy stop <id>
forge proxy start <id> --smoke-test --smoke-endpoint responses
```

Forge honors a saved `allow` even if an earlier version ignored it on a translated proxy. Each Codex launch reports that
unpriced requests can exceed recorded spend. Restarting can interrupt either client. It clears the reporting gap and
in-memory effort observations, and reloads persisted dollar-cap totals. A source that declares its cost unavailable
requires the override before its first direct create. This setting is specific to direct OpenRouter Responses. To clear
it from an older LiteLLM proxy, run `forge proxy set <id> costs.on_unreported_cost=null`.

`forge runtime preflight codex --proxy <id>` reports `proxy_supported` for this route. That command also reports native
headless login readiness. To verify enrolled hooks using the running listener's credential, use
`forge runtime preflight codex --proxy <id> --verify-enrollment`. This runs a disposable read-only turn and reports
whether the SessionStart hook fired.

If Codex shows HTTP 429, run `forge proxy metrics <id>` to see the active caps and their settings. For an individual
request, use `forge telemetry trace show <request-id>` and
`forge model backend reconcile openrouter --request-id <request-id>`. A fresh generation may take several seconds to
appear remotely.
