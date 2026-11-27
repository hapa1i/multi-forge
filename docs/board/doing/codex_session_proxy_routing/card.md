# Route managed Codex sessions through a Forge proxy

**Status**: In progress on `codex/codex-session-proxy-routing` from 2026-11-27. [Execution checklist](checklist.md)
[`codex_openrouter_responses`](../../done/codex_openrouter_responses/card.md) gave sessionless Codex an OpenRouter route
and explicitly kept managed Codex sessions out of scope.
[`openrouter_responses_by_default`](../../done/openrouter_responses_by_default/card.md) then enabled Responses on every
direct OpenRouter proxy.

## Problem

The sessionless `forge codex start --proxy` supports direct OpenRouter proxies and the local Responses profile.
`forge session start <name> --runtime codex --proxy openrouter-gemini` fails with
`--proxy is not supported with --runtime codex`. Using the sessionless launcher for a non-OpenAI model costs the user
the managed-session manifest, Forge resume and reattach, transfer from a parent, artifact authority, and per-session
activity. A managed executor can also use a separately configured supervisor, for example to review an approved plan
file. Native planning-source review currently requires an OpenAI rollout.

- `run_codex_start` rejects `--proxy` and `--no-proxy` under the comment "Codex runs direct-to-OpenAI with no hooks".
  Managed Codex sessions now run trust-enrolled hooks, and Codex has had a Forge proxy route since June 2026.
  `run_codex_resume` rejects the same flags as Claude-only.
  [Managed Codex CLI](../../../../src/forge/cli/session_codex.py)
- Managed argument validation refuses `-c model_provider` and `-c model_providers.*` in the `--` tail, plus `--profile`,
  `--oss`, and remote-provider options, because a provider change would invalidate the auth Forge preflighted.
  [Launch arguments](../../../../src/forge/core/runtime/launch_args.py)

## Proposed behavior

### Launch admission and child environment

On managed Codex start, `--proxy <id-or-template>` selects a proxy and `--no-proxy` explicitly selects native auth.
Reject the two flags together. Omitting both keeps today's direct default. On headless resume and TUI reattach, the
recorded route wins. Reject either flag, including `--proxy` naming the recorded ID, before resolving a listener.

Headless start and resume, interactive start, and TUI reattach all call `assert_codex_ready()` today. Passing it a proxy
ID still requires native auth. Select preflight by route on all four paths. A proxied session needs a supported Codex
executable and a verified Responses listener. Check the measured managed CLI floor before `ensure_proxy()` can start a
proxy, then verify the resolved instance with `read_responses_launch`. The sessionless floor of 0.141.0 is the candidate
for the managed probes below. Hook capability and enrollment checks still apply to features that use them.
[Codex preflight](../../../../src/forge/core/runtime/codex_preflight.py)

Apply the sessionless credential scrub before stamping the managed session, instance, run-tree, executor, and authority
identity used by hooks and receipts. Set the synthetic `FORGE_CODEX_PROXY_TOKEN` in the child environment and pass
provider overrides in argv so the enrolled `config.toml` stays intact. Add `proxy_token` to `CodexAuthMethod` and record
`auth_method=proxy_token`, `auth_source=forge_proxy`, and `billing_mode=unknown` in `confirmed.codex`. These describe
the local connection. The proxy resolves the upstream credential and records any reported charge. Nested Forge commands
can load the active credential profile or the project's `.env`. A hook-triggered model call uses its own configured
consumer route and credentials.

Keep user-supplied provider overrides reserved. Update the CLI comment and the reserved-flag diagnostic that says
managed Codex always uses the native provider. The existing explanation for reserving `model_provider` and
`model_providers.*` still applies because an override could change the auth Forge preflighted.
[Launch builders](../../../../src/forge/session/codex_invoke.py) ·
[Recorded Codex facts](../../../design_session_execution.md#i1-recorded-codex-facts-confirmedcodex)

### Proxy identity, adoption, and recovery

Persist the resolved **proxy ID, template, and loopback base URL** together in `intent.proxy` at creation. Today's
`ProxyIntent` contains only the template and URL. On both forms of resume, call `read_responses_launch` at that URL with
the recorded ID and template. Verify live Responses capability and policy before committing a launch or sending history.
Refuse a stopped listener, a different ID on the same port, or an incomplete binding. This pins the Forge route. An
operator can rotate the upstream credential on that route. Keep `confirmed.launch` empty for Codex as today.
[Session intent](../../../../src/forge/session/models.py)

Every instance registers with Codex as `forge_proxy`. Today `forge session adopt` checks the rollout's working directory
and records `direct=True` using the adopting host's native auth facts. It can mislabel a sessionless proxied thread on a
native-ready host. Reject an alias-only `forge_proxy` rollout during adoption planning and when rechecking the rollout
before binding. Sessionless launches have no managed record tying that alias to an instance. This defect can be fixed
independently. [Adoption](../../../../src/forge/core/ops/codex_adopt.py)

To continue the original thread, restore its recorded proxy. To use another route, start a fresh session. A Claude
parent can supply context through `--resume-from`. The transfer reader does not read `confirmed.codex.rollout_path` and
can fall back to a lineage pointer. Offering a history-preserving route change from a Codex parent depends on the
[Codex source adapter](../../proposed/codex_source_adapter/card.md#codex-as-source-launch-boundary).

### Model selection and OpenRouter policy

Share the complete sessionless launch policy on start, resume, and reattach. With direct OpenRouter, use the standard
service tier by default and `--no-daemon` when supported. Under required zero data retention (ZDR), pass
`web_search="disabled"` through `-c`, apply the live `zdr_fallbacks` policy, and show both slugs when they differ. Codex
constructs its request for the requested slug and the proxy dispatches the mapped slug. Preserve the launch notices for
relaxed ZDR, unreported cost, and Messages-only inspection. The local LiteLLM Responses profile uses its own launch
policy. [Sessionless launcher](../../../../src/forge/cli/codex.py) ·
[Codex proxy guide](../../../end-user/codex_proxy.md)

Where managed passthrough is permitted, `-m` takes precedence over a top-level `-c model=...`. At creation, use the live
Responses policy's `requested_default_model` or the advertised default tier's model when the user omits both. Advisory
starts use the chosen proxy's default because they accept no `--` tail and Codex rejects catalog `--model`. If the
launch has neither an explicit slug nor a usable default, refuse and name the proxy setting to fix. Raw passthrough
arguments apply to one launch.

For bare resume and reattach, replay the **verbatim requested slug from the last completed foreground user turn on the
bound thread**. Record the thread ID and the requested and dispatched slugs together in `confirmed.codex` under the
session-instance guard. For direct OpenRouter, dispatched means the slug Forge sent upstream after applying policy. For
the local profile, it means the slug Forge forwarded to LiteLLM. LiteLLM owns any further mapping.

- **Headless.** Match the launch's request and proxy dispatch to the bound thread's successful `turn.completed` in
  `codex exec --json`. A failed turn leaves the previous selection in place.
- **TUI.** The OpenRouter trace already exposes both slugs after an in-TUI `/model` switch. Reconcile the bound
  rollout's completed foreground turn and selected model with its attributed proxy dispatch. A process exit, title
  request, intermediate tool step, or failed turn alone cannot advance the selection. Prove the turn association for
  each admitted frontend and route. [Existing trace behavior](../../done/codex_openrouter_responses/card.md)

If the thread has had no completed user turn, replay the first non-aborted **start** commitment. If completion or the
model cannot be established, refuse resume even with an explicit `-m` and explain how to start fresh. On resume,
re-evaluate the live policy for the requested slug. If replaying the same slug would now dispatch a different model,
refuse before sending history or committing the launch. Name both targets and suggest restoring the original mapping or
starting fresh. An explicit change to a different requested slug can proceed under live policy. If the destination
rejects the history, surface the failure and retain the prior completed selection.

### Usage, spend, and session activity

On headless turns, `prepare_codex_request` currently labels the provider `openai`. `emit_codex_usage` writes both a
session usage event and a downstream attempt containing its JSONL token totals. For a proxied turn, keep one session
event with `route=codex_exec`, the exact JSONL totals, and the resolved model and provider facts. The Responses proxy
owns one downstream attempt per actual create, including its backend, tokens, and reported cost. Leave cost off the
session event and suppress the synthetic native attempt on this path. Stamp the same run and root IDs on the event and
its proxy creates. The cost join assigns their summed charges to the event-backed activity row, which takes its tokens
from JSONL. Direct Codex keeps its native attempt. [Codex emitter](../../../../src/forge/core/usage/emit.py) ·
[Telemetry contract](../../../design_telemetry.md#314-cost-tracking-and-spend-caps)

A parentless TUI start or reattach emits no Codex usage event, but each launch already commits a fresh root run ID in
its own routing journal. Attribute proxied Codex activity to validated, non-aborted launch commitments belonging to the
current project and session instance. Send `X-Forge-Run-ID` and `X-Forge-Root-Run-ID` to the loopback listener only. For
these launches, filter usage events, upstream outcomes, and downstream attempts by owned runs and verified descendants
before aggregation. Include independently attributed supervisor and worker runs under their own roots. The existing
`X-Forge-Session` hash uses only the name. The activity reader currently accepts that hash even when a record carries
another project's run IDs. A matching label alone must never admit a record or add a foreign root to the join. If Codex
drops the headers, require an equivalent measured, instance-scoped association.
[Activity reader](../../../../src/forge/core/ops/usage_summary.py)

### Routing journal and operator output

Write a Codex-specific `route.kind=proxy` payload with the session instance ID, verified proxy ID, template, backend and
Responses wire shape. Recording the session instance distinguishes successive sessions at the same project/name. Give it
separate verbatim requested and policy-mapped slug fields. The existing proxy `requested_model` requires a
catalog-canonical ID, which loses the provider prefix on `google/gemini-4-carbon` and cannot represent an uncatalogued
slug. Validate the new shape independently of Claude tier selection. A commitment records what Forge planned to launch.
Only completed-turn evidence updates the replay selection.

Use a new manifest schema version for proxy-backed Codex state. The manifest writer selects the lowest compatible
version, and older readers reject unknown fields. Omit the new keys when writing historical direct Codex and Claude
shapes. Keep the journal envelope and existing `runtime_native` and Claude payloads readable. Older Forge cannot read
the new manifest or Codex proxy event. Document downgrade recovery as keeping the session files and using a compatible
Forge version. Audit readers of `intent.proxy`, especially supervisor route inheritance and session reports. Coordinate
`confirmed.codex` writes with the [Codex source adapter](../../proposed/codex_source_adapter/card.md) so updating the
completed model or captured children preserves both. [Manifest writer](../../../../src/forge/session/store.py) ·
[Journal validation](../../../../src/forge/session/routing.py)

The launch banners and `forge session show` currently print direct OpenAI routing for Codex, and
`forge session model show` always reports native intent. Render the recorded intent, launch commitment, and available
live endpoint facts in the appropriate human and JSON surfaces.
[Session details](../../../../src/forge/cli/session_manage.py) ·
[Model report](../../../../src/forge/core/ops/session_model.py)

## Evidence required before implementation

The predecessor exercised real Codex 0.141.0, 0.149.1, 0.161.0, and 0.170.0 on loopback with the provider overrides. It
covered TUI start, `exec --json`, and `exec resume --json`. The second TUI prompt ran in the same process. Reuse those
[results](../../done/codex_openrouter_responses/probe-results.md#tool-use-and-compaction) and the
[native driver](../../../../scripts/experiments/openrouter/helpers/codex_matrix.py).

- **Managed launch matrix.** Probe the proposed managed arguments and environment for headless start, headless resume,
  TUI start, and TUI reattach after exit. Record results by binary version and launch form. Exercise the candidate floor
  and a newer pin with an isolated Codex home and a fake Responses upstream. Drive the real TUI through a PTY. If the
  candidate fails, exercise the next candidate across all four forms and record the supported floor. Repeat the admitted
  forms through Forge's entry points in integration acceptance.
- **Headers and binding.** Capture Forge's run headers at Responses ingress and verify they never reach the upstream.
  Inspect the rollout and observe which listener received history on each resume form, with and without provider
  overrides in the native control. Include two instances sharing a template and provider alias.
- **Model replay.** Pair the bound rollout's turn context and completion boundary with the requested and dispatched
  slugs. Switch models inside the TUI, complete a user turn, exit, and reattach. Repeat with a failed switch and a title
  or tool request. Exercise an explicit cross-model resume with opaque reasoning history. Record which evidence
  identifies the last completed foreground turn and what the next launch actually sends.
- **Hooks and advisory enrollment.** Verify trust-enrolled hooks and managed executor identity through the proxy.
  Exercise feedback on 0.161.0 and 0.162.1 and Stop review on 0.162.1. Run the empirical `verify_codex_enrollment` turn
  with proxy-only credentials. If native auth is still necessary for advisory enrollment, document the prerequisite and
  refuse advisory launch when it is missing. Ordinary proxy-only sessions use route preflight independently.

## Integration acceptance

Use disposable Codex homes, isolated Forge projects, and fake upstreams. The managed TUI shim can verify argv, the child
environment, and refusal ordering. Use the real-client probes above for header delivery, hook firing, model switching,
thread continuity, and reattach spend.
[Managed TUI shim](../../../../tests/integration/cli/test_transfer_fidelity_integration.py) ·
[Proxy fixtures](../../../developer/verification.md#sessionless-codex-through-openrouter-responses)

- With only the proxy's synthetic OpenRouter credential and an empty native login store, run headless start from a
  supported Claude parent (`--resume-from <parent> --strategy structured --task ...`), headless resume, parentless TUI
  start, and TUI reattach. Assert the recorded proxy auth values. With dotenv disabled, verify the child has the
  loopback token and managed identity, and lacks the parent's upstream keys. Exercise a hook-triggered model call with
  its own fixture credential and consumer route. For example, have the proxied executor use an approved plan file and
  check the reviewer endpoint. A `forge_proxy` rollout presented as a native review source must still fail admission.
  [Native source limits](../../../end-user/native_supervision.md)
- Test the explicit direct start and the conflicting start flags. On both resume forms reject either route flag,
  including the same proxy ID. A below-floor CLI must refuse a proxied start before `ensure_proxy()`. For an admitted
  advisory start, assert selection of the proxy default and refusal of user passthrough.
- Stop the recorded instance, then put a different ID on the same port with the same template. For each case, both
  resume paths must refuse before sending history or publishing a routing commit. Restarting the original instance at
  its recorded URL must permit resume. On a native-ready host, give adoption a valid alias-only rollout from the current
  directory. It must explain that the proxy cannot be identified and leave neither a manifest nor an index binding.
  Check an ordinary direct adoption as a control.
- Enable web search in the disposable home and configure a required-ZDR fallback. On start and resume, inspect the
  client request, upstream request, and operator output for disabled hosted search and the requested/mapped slugs. Check
  that a local LiteLLM launch omits the OpenRouter-specific defaults. On a bound OpenRouter thread change only the
  fallback for its recorded slug. Bare resume and reattach must name the old and new targets and send zero creates.
- Start with an explicit Gemini slug on a GPT-default proxy. Both forms of bare managed resume must request Gemini,
  including after a change to the proxy default. After a completed in-TUI `/model` switch or explicit headless switch to
  GPT, bare resume must request GPT. A failed switch from Gemini must leave Gemini as the next request. Exercise a bound
  thread with no completed turn and a later failed resume commitment. It must replay the initial start slug. Ambiguous
  completion evidence must yield a recovery message before history is sent.
- Drive a headless tool turn that makes two Responses creates with distinct token counts and known charges. Assert one
  Codex usage event and two downstream attempts attributed to the serving backend. Check the fixture's token and spend
  totals in `forge telemetry activity` and its request count in `forge telemetry costs show`. The proxy cap must advance
  by the sum of the two charges. At a configured reject cap, the next create must stop at the proxy.
- Create identically named sessions in two projects sharing one Forge home and proxy. With curation and workers idle,
  give a parentless TUI start and its reattach distinct charges. Interleave the other project's headless and TUI
  creates, then query `forge telemetry activity <name> --json` from each project. The first project must show the first
  charge, then the sum of its two charges exactly once. Give one of the second project's attempts the shared legacy name
  hash and add a label-only attempt. Neither may contribute to the first project's total. The second must show only its
  own events, tokens, and charges. Recreate a session under the same name and check that old launch IDs contribute
  nothing to the new instance.
- Inspect the start and reattach banners, `forge session show`, and `forge session model show` in human output. Check
  both show commands with `--json` and the committed event with `forge session model history <name> --json`. The proxied
  fixture must identify the actual proxy and model fallback. Round-trip both a provider-qualified slug and an
  uncatalogued slug verbatim. Read historical Claude and direct Codex journals, round-trip their manifests in the
  existing formats, and verify that an older reader rejects the proxied fixture. Direct Codex must still report native
  OpenAI routing.

## Risks

- A local forced-compaction trial sent 2,055 requests in 60 seconds when the stub kept reporting usage above the
  compaction threshold. An unattended headless turn can exhaust a shared spend cap. The proxy can enforce a reject cap
  against reported charges, and an interrupted stream can leave cost unreported.
  [Probe conditions](../../done/codex_openrouter_responses/card.md) ·
  [Spend behavior](../../../end-user/codex_proxy.md#spend-and-diagnostics)
- Codex sends full history on resume, including opaque reasoning. A changed target may reject it. The proxy binding,
  completed-turn selection, and live fallback check determine whether Forge can safely launch that replay.

## Open questions

- Should a future Codex child started with `--resume-from <claude-parent>` inherit its parent's Responses-capable proxy?
  This proposal defaults to direct when neither route flag is supplied. Explicit `--no-proxy` selects direct even if
  inheritance is later introduced.
- Should catalog `--model` select a Codex route through `session_model_routing`? That planner currently never selects
  for Codex, and Claude-only `--model` is refused for Codex sessions.

## Scope

This card covers host-managed Codex sessions. The supervisor, memory writer, and shadow curation consumer lanes keep
their own dispatch and credentials. A proxied executor can use an admitted supervision configuration. Native review
sources still require an admitted OpenAI rollout with historical account provenance. Extending source admission, sidecar
Codex support, and the sessionless launcher's public contract are outside this proposal.

When this ships, update the [launch contract](../../../design.md#34-proxy-vs-no-proxy-mode),
[session schema](../../../design_sessions.md),
[resume and transfer](../../../design_session_context.md#39-session-resume-context-management),
[Codex facts and journals](../../../design_session_execution.md), [proxy runtime](../../../design_runtime.md),
[telemetry](../../../design_telemetry.md), [CLI reference](../../../cli_reference.md),
[verification procedures](../../../developer/verification.md), and the end-user
[Codex proxy](../../../end-user/codex_proxy.md) and [session](../../../end-user/session.md) guides.
