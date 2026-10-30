# Show the effective reasoning effort

**Lane:** `doing/` -- started on 2026-10-30 on `codex/effective-effort-visibility`, based on `d32e7b1d`.

**Execution:** [Checklist](checklist.md).

**Origin:** Owner request on 2026-10-29. The effort a session actually runs at is hard to see, and on proxied routes it
can differ from Claude Code's own setting without any visible signal. Research used Claude Code 2.1.312 and the current
`main` (`e469fccf`).

**Related:** [`session_launch_effort`](../../done/session_launch_effort/card.md) shipped launch `--effort` and the
`X-Forge-Effort-Source: client` opt-in. [`statusline_enhancement`](../../done/statusline_enhancement/card.md) owns the
segment registry and golden default bar.

## Problem

Claude Code shows effort in the session header and briefly in the footer at startup or on change. The level that reaches
a model can change at four hops, and Forge records the result at none of them:

| Hop                       | Owner                                     | What can change                                                                                                         |
| ------------------------- | ----------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| Claude Code               | `/effort`, `--effort`, settings, env      | Per-model saved levels; clamps unsupported levels; `ultrathink` raises a turn                                           |
| Forge proxy (translated)  | `forge.proxy.reasoning`                   | Ignores Claude's effort without the launch opt-in; thinking-derived; tier floor; clamps to the mapped model             |
| Forge proxy (passthrough) | `forge.proxy.intercept.pin_native_effort` | Override mode may raise `output_config.effort` to the tier floor                                                        |
| Forge client stage        | `forge.core.llm.clients`                  | OpenRouter `reasoning.effort`; Argon native `thinkingLevel`; GPT-5 Chat Completions drops effort when tools are present |

The provider or gateway then maps the value again (LiteLLM per-provider translation, OpenRouter normalization). Effort
names are calibrated per model, so `high` on GPT-6 Astra and `high` on Opus 5.5 are not equivalent work.

Concrete confusions this card addresses:

- **Translated routes ignore `/effort`.** Without launch `--effort`, `resolve_reasoning_effort` uses
  `max(thinking-derived, tier floor)`. Adaptive thinking derives `medium`, so a mid-session `/effort xhigh` changes
  nothing upstream, and nothing says so.
- **Silent drops.** `LiteLLMClient._build_request_kwargs` strips `reasoning_effort` for GPT-5 Chat Completions requests
  with tools, logging only a server-side warning.
- **Nothing to inspect afterwards.** The resolved value is not in downstream telemetry, proxy metrics, the routing
  journal, or `GET /`. `runtime.llm_defaults_by_tier` exposes configured floors, not applied values.

The direct-mode model label also repeats context size: `format_model_label` renders `[Sonnet 4.6 (1M)]` beside a context
bar that already ends in `47%/1M`, and `tier_color` encodes extended context a third time.

## Evidence

- **Status-line stdin:** documented `effort.level` (`low`..`max`; live, including mid-session `/effort`; absent when the
  model does not support effort), `thinking.enabled` and `fast_mode`. The
  [current documentation](https://code.claude.com/docs/en/statusline#available-data), rechecked on 2026-10-30, specifies
  the substituted supported level, except that `CLAUDE_CODE_EFFORT_LEVEL` is shown directly. This clarifies the original
  research, which could not establish configured-versus-clamped semantics.
- **Transcripts:** assistant entries carry undocumented `effort` and `perTurnEffort` fields in every local 2.1.281 to
  2.1.312 sample. Observed pairs include `(None, "max")` and `("xhigh", None)`, consistent with per-turn changes.
- **Session correlation:** interactive launches send no session or run identity to the proxy. `invoke.py` builds their
  environment with `derive_run_identity=False`, which skips `_apply_correlation_headers`; they send only
  `X-Forge-Model-Tier` and `X-Forge-Effort-Source`. Reusing the headless headers is unsafe. `X-Forge-Session` hashes the
  session name alone and is forwarded upstream as the provider `user` field
  ([A.14](../../../design_telemetry.md#a14-provider-lifecycle-fields-in-downstream-telemetry-314)), while run IDs drive
  run-tree telemetry. Each managed launch, host or sidecar, mints its own root run ID and records it in its routing
  commitment (`confirmed.route_commit`) before the child starts; the authority journal's `run_started` event exists only
  for marked sessions. Sidecars build their container environment separately and refuse model routes, so they never
  project a tier.
- **Dispatch paths:** `GET /` reports `tier_mappings` and `model_alternatives` for every wire shape. Translated routes
  dispatch through them unless the request names an explicit `provider/model` backend, which is preserved. Anthropic
  passthrough forwards the client body unchanged, so its tier mappings describe cost and cap attribution, not the
  upstream model.
- **Cost:** the status line already fetches `GET /` once per render for proxy-sourced segments; `ProxyRuntimeTruth` is
  shared with `forge session model show`.

## Proposal

### Phase A -- direct-mode effort, bar cleanup and launch hint (no proxy change)

- Render the stdin `effort.level` inside the model label: `[Opus 5.5 @xhigh] ###----- 47%/1M`. Omit the annotation when
  the field is absent.
- Remove the `(1M)` suffix from `format_model_label` and the deeper extended-context variants from `tier_color`. The
  context bar remains the only context-size display.
- Remove `think` from `DEFAULT_ORDER`. The segment stays available as an opt-in name with unchanged behavior.
- Leave proxied rendering unchanged in this phase. Echoing Claude's level there would be wrong on translated routes.

**Launch hint.** A managed Claude launch (`session start|resume|fork|incognito`) on a Forge proxy whose wire shape is
not `anthropic_passthrough`, without `--effort`, prints one stderr line before Claude starts. Every other wire shape,
including the `codex-responses-local` Messages ingress, resolves effort through `resolve_reasoning_effort` and ignores
Claude's level without the opt-in. The line says the route derives effort from thinking and the tier minimum, names the
selected tier's configured minimum when `GET /` reports one, and offers `--effort <level>` on the same lifecycle
command. It goes through the `forge.cli.output` recovery helpers and never into JSON output. Direct, passthrough,
`--no-launch` and bare `forge claude start` launches print nothing. Bare launch has no `--effort`, and the CLI style
contract forbids recovery commands that do not apply. Launches whose wire shape Forge cannot confirm also print nothing.

### Phase B -- proxy effort observation

**Launch key.** A new Forge-owned `X-Forge-Launch` header carries the launch's root run ID. Interactive launches stamp
it, on the host and in the sidecar container environment, only when the target is a proven Forge proxy.
`_apply_correlation_headers` scrubs it for headless children, as it does the tier and effort-source headers, so children
never write into the parent launch's observations. Keying by launch rather than session name separates same-named
sessions in different projects and starts every resume or fork with no observation. It leaves `X-Forge-Session` and the
run-tree headers unchanged.

**Resolution record.** Effort resolution returns a structured record alongside its current string result: the opt-in
flag, Claude's requested level and whether it applied, the thinking-derived value, the tier minimum, the value before
clamping, the model's supported levels, and the resolved value with its source. An opted-in request whose thinking type
is `between_tools` or `disabled` stays distinguishable from a launch without the opt-in. Final request construction
carries the record through the client stage, which adds the applied value and the outbound parameter for both streaming
and non-streaming paths.

The proxy records the completed record, in memory, bounded, and lost on restart, per `(launch, tier)`:

```json
{
  "tier": "opus",
  "tier_source": "request",
  "client_model": "claude-opus-5-5",
  "mapped_model": "openai/gpt-6-astra",
  "requested": "xhigh",
  "thinking": "adaptive",
  "opt_in": false,
  "client_applicable": true,
  "derived": "medium",
  "floor": "high",
  "pre_clamp": "high",
  "supported": ["low", "medium", "high", "xhigh", "max"],
  "resolved": "high",
  "source": "floor",
  "applied": "high",
  "wire": "reasoning.effort",
  "note": null,
  "observed_at": "2026-10-29T17:02:11Z"
}
```

- `source` is `explicit | client | thinking | floor | passthrough | override`; `wire` names the outbound parameter
  (`reasoning_effort`, `reasoning.effort`, `thinkingConfig.thinkingLevel`, `output_config.effort`) or `dropped`.
  `tier_source` uses the proxy's own dispatch labels, and `supported` is null for models without catalog levels.
- `GET /?forge_launch=<id>` adds `runtime.effort` for that validated launch only. Plain `GET /` stays unchanged and
  never enumerates launches. The status line reads the id from its inherited `ANTHROPIC_CUSTOM_HEADERS`, so no request
  is added.
- Passthrough builds the same record from the client value, or the pinned value when override mode mutates it.

### Phase B rendering

The proxied label annotates only the active tier, chosen with the proxy's dispatch precedence: an explicit tier in stdin
`model.id`, then the launch's projected `X-Forge-Model-Tier` from the inherited `ANTHROPIC_CUSTOM_HEADERS`, then
`runtime.active_tier`. This also shows which tier is active, which the mapping display currently omits. The annotated
slot names the observed `mapped_model`, not the configured tier default, so a model alternative serving the tier shows
its own name.

The same helper predicts the route model by dispatch path, checking the wire shape first:

| Dispatch path                            | Predicted route model                                        |
| ---------------------------------------- | ------------------------------------------------------------ |
| `anthropic_passthrough`                  | Claude's request model after `strip_transport_model_suffix`  |
| Translated, explicit `provider/model`    | Unproven: Forge cannot reproduce the proxy's backend mapping |
| Translated, tier route                   | Matching `model_alternatives` entry, else the tier mapping   |
| Registry fallback or invalid route truth | Unproven                                                     |

An unproven route keeps `marking` at `unknown`, as it is today for explicit backends, and is never compared with an
observation. The label still names the observed model, because that observation records what Forge sent.

**Folded bug.** `_produce_drift` and `_produce_marking` skip the projected tier today, although their comment says they
mirror the proxy, and `drift` compares against the tier default without consulting model alternatives. For a non-Claude
model pinned to Opus on a Sonnet-default proxy, both evaluate the Sonnet route. Neither checks the wire shape either: on
a passthrough proxy advertising Opus 5.5, an Opus 4.6 request gets Opus 5.5's marking declaration and a false `drift`.
Phase B moves the model label, `drift` and `marking` to the shared route helper and adds a regression test under
`tests/regression/` covering both cases.

States are spelled out rather than marked with symbols. A changed value shows the applied level, then `<-`, then
Claude's request. The arrow reads "from" and avoids a less-than reading when a tier minimum raises the level.

| State                                                       | Rendering                                          |
| ----------------------------------------------------------- | -------------------------------------------------- |
| Applied equals Claude's request, or Claude sent none        | `openrouter-openai [O:astra@xhigh S:astra H:mini]` |
| Forge, the model's levels, or the route changed it          | `[O:astra@high<-xhigh ...]`                        |
| A model alternative served the tier                         | `[O:sol@high<-xhigh S:astra H:mini]`               |
| Level, model or route changed since the last request        | `[O:astra@high (stale) ...]` until the next one    |
| Client stage dropped it                                     | `[O:gpt-5.4@dropped<-xhigh ...]` in warning color  |
| No observation for this launch, unsupported proxy, fallback | `[O:astra@unknown ...]`                            |

An observation is stale when stdin `effort.level` differs from `requested`, stdin `model.id` differs from `client_model`
after `strip_transport_model_suffix`, or a proven route model differs from `mapped_model`. Launch keying already
discards earlier launches, so staleness covers only changes within one launch.

### Phase B explain surface

`forge session model show [--json]` and `%session model show` add an effort block that reads the same observation. The
CLI takes the launch ID from the run ID in the session's routing commitment, so it works outside the Claude process for
marked and unmarked sessions. It uses that ID only when `forge session model show` already classifies the commitment as
`route_commit` evidence. An `unproven_projection` or legacy launch record reports `unknown` with that reason, without
querying the proxy. The block states the requested level, whether the launch opted in and whether that applied, the
thinking-derived value, the tier minimum, the value before clamping with the supported levels, the tier source, the wire
parameter and the backend. A launch without an observation reports `unknown`, for example before its first request,
after a proxy restart, or when the launch predates the header.

## Non-goals

- Verifying the provider-side value. Forge observes its own outbound request; gateway and provider mappings stay outside
  the claim.
- Claiming cross-model equivalence of effort names.
- Changing resolution precedence, the client-effort opt-in, or persisting launch-only effort in session intent.
- Changing the scope of `X-Forge-Session` or the run-tree headers. Interactive traffic keeps its current provider `user`
  grouping and run-tree telemetry attribution.
- Codex TUI, `subagentStatusLine` rows, and Forge workers or supervisors. Each is a possible follow-up.
- Per-turn raises such as `ultrathink` in direct mode. Revisit when Claude Code documents a per-turn stdin field; the
  transcript `perTurnEffort` field is undocumented.
- A durable downstream telemetry field in v1. Strict older readers skip records with unknown fields; add it separately
  if `forge telemetry trace explain` needs history.

## Risks

- **Shared tier traffic.** Subagents inside the same Claude process share the launch header and may use another effort
  on the same tier, so "latest" can flip. Claude Code background calls on another tier do not affect the active-tier
  display.
- **Header scope.** `X-Forge-Launch` must reach only a proven Forge proxy and never a provider. Passthrough forwards
  only its request-header allowlist and responses drop `x-forge-` headers, but tests pin both, plus the headless-child
  scrub.
- **Golden change.** Both phases deliberately change the default bar: Phase A removes `(1M)`, the deeper colors and
  `THINK`, and Phase B adds proxied annotations. Update the registry goldens and record the change; narrow terminals
  rely on the existing truncation.
- **Version skew.** Pinned QA Claude 2.1.245 may not emit `effort` on stdin, and older running proxies ignore the query
  parameter. Sessions launched before the upgrade send no launch header until relaunched. They render as no annotation
  and `unknown` respectively, never as a guessed value.
- **Hint repetition.** The launch hint repeats on every qualifying launch, including for users who rely on tier minimums
  deliberately. Add suppression only if that proves noisy.
- **Recording point.** Observing before the client stage would report `high` for the GPT-5 tools case that sends
  nothing. The observation must come from final request construction for both streaming and non-streaming paths.

## Decisions

The owner settled the design questions on 2026-10-29:

1. **Placement:** inside the `model` segment's label; no separate `effort` segment name.
2. **States:** spelled out (`<-`, `(stale)`, `dropped`, `unknown`) instead of symbol markers.
3. **`think`:** removed from `DEFAULT_ORDER`; the opt-in segment remains.
4. **Extended-context color:** removed; the context bar shows the size.
5. **Per-turn raises:** deferred until Claude Code documents a stdin field.
6. **Launch hint:** included in Phase A.
7. **`drift` and `marking` route bugs:** the projected tier, model alternatives and passthrough dispatch are fixed in
   Phase B through the shared route helper, with a regression test.

## Acceptance sketch

- Phase A: direct sessions show the stdin level and no `(1M)` suffix or deeper color; models without effort render
  unchanged; the default bar omits `THINK`. The launch hint prints once for a qualifying launch and stays silent for
  direct, passthrough, `--no-launch`, bare, unconfirmed and `--effort` launches.
- Phase B resolution: a translated launch without `--effort` shows the thinking or minimum value as
  `applied<-requested`. With `--effort`, a supported level shows alone and an unsupported one shows clamped:
  `gemini-4-argon` (low to high) with opted-in `max` and adaptive thinking shows `high<-max`. Opted-in `between_tools`
  and `disabled` requests derive `none`, then take the tier floor and clamp: the bar shows the applied value, `low<-max`
  without a floor and `high<-max` with a `high` floor. The explain surface lists the derived value, floor, pre-clamp
  value and supported levels separately and reports the opt-in as present but not applicable. A GPT-5 Chat Completions
  request with tools shows `dropped`; Argon reports `thinkingLevel`; passthrough override shows the pinned value with
  its source.
- Phase B routing: a non-Claude model pinned to Opus on a Sonnet-default proxy annotates Opus, and `drift` and `marking`
  evaluate the Opus route (regression). On a passthrough proxy advertising Opus 5.5, an Opus 4.6 request annotates and
  marks Opus 4.6, never turns `(stale)` from route prediction, and shows no `drift` (regression). An explicit
  `provider/model` request keeps `marking` at `unknown` and skips the route comparison. A model alternative renders its
  observed name. A same-tier model switch at the same effort renders `(stale)`.
- Phase B keying: same-named sessions in two projects on one proxy keep separate observations; resume and fork start at
  `unknown`. Sidecar launches carry the launch header; headless children and passthrough upstream requests do not. The
  explain surface finds an unmarked session's launch through its routing commitment and reports an unproven projection
  as `unknown`.
- Layouts without `model` perform no new work, and zero-source layouts stay probe-free.
- Probe stdin `effort.level` and `model.id` on pinned and latest Claude versions before relying on them, including
  whether `model.id` matches the request model after suffix normalization.
- Tests: resolution-record and client-stage observation units, launch-header stamping and scrubbing for host, sidecar
  and headless children, `GET /` query scoping, the route-helper regression, status-line goldens, launch-hint emission
  per wire shape and lifecycle command, and a targeted proxy integration with a stub upstream. No paid inference is
  required.
- Docs: [status-line guidance](../../../design_telemetry.md#a8-status-line-guidance-3611),
  [proxy runtime truth](../../../design_runtime.md#37-proxy-runtime-truth),
  [end-user status line](../../../end-user/config.md#status-line-statusline), and
  [launch effort](../../../end-user/proxy.md#launch-effort-on-translated-routes).
