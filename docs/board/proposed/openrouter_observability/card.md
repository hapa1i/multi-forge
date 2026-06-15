# OpenRouter Provider Trace -- session IDs and local lifecycle evidence

**Status**: Proposed. Spun out of the `supervisor_shadow_sampling` investigation on 2026-06-14, after a supervised fork
sent requests through the OpenRouter proxy but the user could not find them in OpenRouter's UI or Forge activity/cost
surfaces.

**Split from**: the original broad OpenRouter observability sketch. Log-volume work now lives in
`docs/board/proposed/proxy_log_hygiene/card.md`; remote OpenRouter reconciliation now lives in
`docs/board/proposed/openrouter_remote_reconciliation/card.md`.

**References**: OpenRouter `session_id` request field; Forge proxy cost logs (`~/.forge/costs/requests/`), request logs
(`~/.forge/logs/requests/`), run-tree headers (`X-Forge-Run-ID`, `X-Forge-Root-Run-ID`), the `core.llm`
`CompletionResponse` / `StreamEvent` abstraction, and the usage ledger cross-plane refs in `docs/design_appendix.md`
§A.13.

## Problem

Forge can prove that a request passed through a local proxy, but it cannot reliably answer the operator's first question
after a timeout: "what happened to this provider request?"

The incident that motivated this card had local evidence:

- `neat-bloodhound-executor` policy checks routed through the `openrouter-openai` proxy.
- The proxy logged multiple local `req_...` ids and streamed chunks from `openai/gpt-5.5`.
- Supervisor subprocesses timed out before the proxy saw a final streaming usage chunk, so local proxy cost/tokens were
  unavailable. This is separate from Claude's headless JSON self-report envelope, which also does not arrive when the
  subprocess is killed by the supervisor timeout.
- The user could not find corresponding requests in OpenRouter's UI or spend views.

Today the durable local records stop at Forge ids, run-tree ids, and best-effort cost rows. They do not preserve a
compact provider lifecycle record: OpenRouter `session_id`, provider generation/request id when available, whether a
stream started, whether final usage arrived, whether the client disconnected, or whether the missing cost is "not seen"
instead of "zero."

The tricky part is not merely reading a streamed chunk id in the proxy. The OpenAI-compatible response ids emitted by
the proxy adapter are currently synthetic `chatcmpl-<timestamp>` values, and the shared `core.llm` abstraction does not
surface provider ids or response headers. Provider trace therefore belongs at the shared LLM/proxy boundary, not as an
incidental request-log field.

## Phase 0 probes

Before implementation, pin the OpenRouter externals with tiny, reproducible probes:

1. **Generation id source**: determine whether `gen-...` appears in the streamed response body id, a response header,
   the non-streaming body id, or only through a later generation lookup.
2. **Cancelled stream behavior**: start a streaming request, cancel before final usage, then check whether
   `/api/v1/generation`, `/api/v1/activity`, or the dashboard records it. This decides what local trace must answer on
   its own.
3. **`session_id` transport**: confirm the field actually reaches OpenRouter through Forge's path, including `core.llm`
   -> LiteLLM/OpenAI-compatible clients -> OpenRouter. If LiteLLM drops unknown params, the implementation needs the
   right `extra_body` / allowed-params path before routing measurements mean anything.
4. **`session_id` routing impact**: compare repeated large supervisor-style prompts with and without sticky
   `session_id`, measuring first-token latency, total latency, cache indicators when exposed, provider selection, and
   failure rate.

The probes should record request timestamps, local request ids, model, key/account provenance, cancellation timing, and
whether remote evidence exists. If cancelled streams are absent remotely, that is an expected result, not a failure of
this card.

## Proposal

Ship a local provider-trace plane for OpenRouter-bound traffic, plus deliberate Forge-owned `session_id` injection. This
should answer the incident locally even when remote reconciliation cannot find an aborted request.

### 1. Forge-owned OpenRouter session IDs

Generate opaque ids instead of sending raw local paths or long session names upstream. Candidate shapes are illustrative
until Phase 0 and implementation settle the granularity:

```text
forge_sess_<short_hash>
forge_sess_<short_hash>_<role>
forge_run_<short_hash>
```

Store the local mapping in owner-only Forge telemetry, for example:

```json
{
  "provider": "openrouter",
  "provider_session_id": "forge_sess_abc123_supervisor",
  "forge_session": "neat-bloodhound-executor",
  "role": "supervisor",
  "proxy_id": "crimson-apricot",
  "forge_root_run_id": "run_...",
  "created_at": "2026-06-14T22:40:02Z"
}
```

The proxy already receives run-tree headers, but not always the human Forge session name or command role. Add
Forge-owned headers that the proxy consumes for telemetry and strips before non-Forge upstream forwarding:

- `X-Forge-Session`
- `X-Forge-Command` or `X-Forge-Provider-Role`

Validate and sanitize these like the existing run headers. If absent, fall back to a root-run scoped provider session id
so traffic is still grouped without leaking workspace paths.

### 2. Inject `session_id` into OpenRouter requests

For OpenRouter-bound OpenAI-compatible requests:

- Preserve an explicit caller-provided `session_id`.
- Otherwise inject Forge's derived `session_id`.
- Keep human-readable labels out of upstream metadata unless a user opts in.
- Make the same capability available to direct `core.llm` OpenRouter calls through provider-specific extras so curation,
  taggers, and plan checks can share the grouping behavior.

The upside is not only observability. The motivating supervisor loop re-sent a very large repeated context on every
check. If OpenRouter's sticky `session_id` improves provider affinity or prompt-cache hits, it may reduce the latency
that caused the 45-second timeout in the first place. The Phase 0 probe must also watch for the opposite outcome:
stickiness can pin a session to a slower or less reliable provider.

### 3. Surface provider metadata through `core.llm`

Extend the canonical LLM result/event model with sanitized provider metadata instead of relying on proxy-local raw
dicts. The exact type can be settled during implementation, but it should support:

- provider name (`openrouter`, `litellm`, `openai`, etc.)
- provider response id / generation id when known
- provider request id when exposed by headers or response bodies
- selected upstream/provider name when known
- sanitized response headers needed for correlation
- the provider session id Forge sent

This metadata should be optional and additive on `CompletionResponse` and `StreamEvent`. Existing callers should keep
working when providers cannot supply it.

The proxy adapter may still need synthetic OpenAI-compatible ids for downstream clients, but those ids must be clearly
separate from provider ids in trace records and user-facing output.

### 4. Add a dedicated local provider trace plane

Do not overload cost records with provider diagnostics. Add a small provider-trace plane, likely under:

```text
~/.forge/providers/openrouter/traces/<YYYY-MM>_<pid>.jsonl
```

Each record is metadata-only and owner-only, with retention semantics comparable to the existing local telemetry
surfaces. The `provider_generation_id` value below is a placeholder shape until Phase 0 pins OpenRouter's actual id
format:

```json
{
  "schema_version": 1,
  "ts": "2026-06-14T22:40:02Z",
  "request_id": "req_...",
  "proxy_id": "crimson-apricot",
  "provider": "openrouter",
  "provider_session_id": "forge_sess_abc123_supervisor",
  "provider_generation_id": "<provider-id-if-known>",
  "mapped_model": "openai/gpt-5.5",
  "forge_run_id": "run_...",
  "forge_root_run_id": "run_...",
  "stream_started": true,
  "first_chunk_seen": true,
  "final_usage_seen": false,
  "client_disconnected": true,
  "timeout_seen": true,
  "local_usage_status": "unavailable"
}
```

Trace joins should respect the existing three-plane design:

- cost remains the spend/cap source of truth
- audit remains the redacted body/control surface
- usage remains run/session attribution
- provider trace remains provider lifecycle/correlation evidence

Join by shared `request_id` and run-tree ids where available. For direct Forge HTTP clients that mint an `X-Request-ID`,
`source_refs.cost_request_id` can provide the exact cross-plane join. For proxied `claude -p` runs, preserve the
existing invariant that usage `source_refs` can stay null and exact cost is joined by run tree because one runtime run
may produce many proxy requests.

The local trace should answer these five questions without opening megabyte proxy logs:

1. Did the request leave Forge?
2. Which provider/account route did it use?
3. Which provider session/generation should I inspect if one exists?
4. Did the stream start, finish, or lose its final usage chunk?
5. Is missing cost a real zero, unavailable evidence, timeout, disconnect, or provider failure?

Stream lifecycle should have one shared capture point. The proxy log-hygiene card owns stopping raw chunk dumps and
rendering compact in-log lifecycle summaries; this card consumes the same lifecycle instrumentation to persist provider
trace records. The two cards should not independently instrument the streaming loop.

### 5. Local read surfaces

Add a provider-trace read surface before remote reconciliation:

```bash
forge provider trace list --session neat-bloodhound-executor --since today
forge provider trace show req_...
forge provider trace explain req_...
```

`explain` should prefer local facts and use precise provenance labels, for example:

```text
req_... left Forge via proxy crimson-apricot -> OpenRouter openai/gpt-5.5.
Stream started and emitted chunks.
The supervisor subprocess timed out before final streaming usage was observed.
Local cost is unavailable, not zero.
No remote lookup was performed.
```

Remote OpenRouter lookups belong to the reconciliation card, not this foundation card.

## Privacy and auth constraints

- Do not send raw workspace paths upstream in `session_id` or metadata.
- Avoid raw user/session labels unless the user opts into human-readable provider labels.
- Provider trace records are metadata-only. They must not contain prompt, completion, tool output, or replayable request
  bodies.
- Request/body capture remains governed by the audit/request-log redaction policy, not by provider trace.
- Never print API keys. If output reports credential provenance, say only `env`, `credentials.yaml`, or
  `management key unavailable`.

## Open questions

- Exact `session_id` granularity: Forge session, root run, role, or a composite?
- Should provider metadata live directly on `CompletionResponse` / `StreamEvent`, or in a nested `ProviderTraceMeta`
  object reused by both?
- Should trace writing happen in the proxy adapter, the proxy server streaming loop, the direct `core.llm` clients, or a
  small shared helper used by all of them and by proxy log-hygiene summaries?
- How much provider header data is useful after sanitization, and which headers should be allowlisted?
- Should provider trace pruning reuse the request-diagnostics retention machinery from the proxy log-hygiene card, and
  what defaults should it use relative to cost, audit, usage, and request logs?

## Risks

- `session_id` changes routing behavior by design. It may improve cache affinity, but it can also pin traffic to a worse
  provider longer than OpenRouter's default routing would have.
- Provider ids might not be exposed in the stream shape Forge uses. The trace must still be useful with only local
  request/session/run ids.
- Extending `core.llm` touches shared direct-call and proxy behavior; keep fields optional and test old providers.
- A provider trace plane is another local telemetry surface. Keep it metadata-only, owner-only, and bounded.
- Remote reconciliation may never be able to find client-aborted streams. The local trace must not depend on remote APIs
  to explain the incident.

## Acceptance sketch

- **Phase 0 generation-id probe recorded**: a minimal OpenRouter streaming/non-streaming probe records where provider
  ids are exposed, or that they are absent.
- **Phase 0 cancelled-stream probe recorded**: a stream cancelled before final usage records whether OpenRouter has a
  remote record and what endpoint/key found it.
- **Session id injected**: an OpenRouter proxy request without `session_id` receives a Forge-derived value; an explicit
  caller value is preserved.
- **Session id is private**: a session in a nested workspace path does not leak raw filesystem paths in provider
  `session_id` or metadata.
- **Provider metadata is additive**: an existing fake `core.llm` client with no provider metadata still produces normal
  completions/stream events.
- **Synthetic id is not provider id**: the proxy adapter can emit an OpenAI-compatible response id while the trace
  distinguishes it from provider generation/request ids.
- **Stream lifecycle traced**: a stream that starts and then disconnects records `stream_started`, `first_chunk_seen`,
  `final_usage_seen=false`, and disconnect/timeout status.
- **Usage join semantics preserved**: a proxied `claude -p` run with multiple proxy requests can keep usage
  `source_refs` null while trace and cost remain joinable by run tree/request ids.
- **Trace stays metadata-only**: prompts, completions, tool output, and replayable bodies are absent from provider
  traces.
