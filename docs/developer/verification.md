# Feature Verification

## Installation and extensions

For Day 1 install or extension lifecycle changes, verify the global-tool path with `forge extension doctor` (use
`--json` when checking install kind, PATH reachability, hook dispatcher, project registry, and compatibility fields),
then verify `forge extension enable --scope user` for runtime hooks and `forge extension enable` for project setup. For
runtime-skill/compiler changes, verify `forge runtime list --json`, `forge extension enable --runtime claude|codex|all`,
and `forge extension status --json`; also exercise `forge extension sync` and
`forge extension disable --runtime claude|codex|all` when package ownership changes. `--runtime` filters every module by
its runtime ownership, while sync preserves the installation's tracked runtime set and runtime-package health belongs to
`extension status`, not `extension doctor`. Runtime-scoped disable removes only selected ownership; omitted runtime
surfaces and unrelated user content must remain, while omitting `--runtime` retains whole-installation behavior. Codex
skills support user and project scopes only (`$HOME/.agents/skills` and `<root>/.agents/skills`); never map Forge local
scope onto the shared project target. For installer/GC changes involving untracked runtime packages, verify the
schema-v3 `forge extension status --json` object (`installations` plus `unmanaged_skill_packages`), then preview cleanup
with `forge clean --scope <project|workspace|all> --verbose` before applying the same scope with `--yes`. Cleanup must
remain fail-closed: unmarked, modified, malformed/newer, or unsafe packages are report-only and must not be removed
automatically. For Codex-hook disable changes, also verify behavior after `$CODEX_HOME` changes: disable must name both
config paths and preserve the managed block and tracking row without mutating either.

## Proxy authentication and model upgrades

For auth, proxy, and workflow changes, test the no-`.env` path explicitly: credentials should resolve from environment
variables first and `~/.forge/credentials.yaml` second, CLI failures should be actionable rather than raw tracebacks,
and workflow preflight should fail fast when required auth or proxies are missing. Remember that proxy health only
confirms the local proxy process is reachable; use `forge proxy start <proxy_id> --smoke-test` to verify upstream LLM
connectivity after first setup, credential changes, or proxy auth changes. For create-path changes, also verify
`forge proxy create <template> --json --smoke-test`: it emits one result object, and a failed probe exits non-zero while
retaining the created, reused, or adopted proxy for inspection and retry. For packaged model/template updates, verify a
fresh realization and a pre-existing user-owned snapshot: upgrades must not rewrite `proxy.yaml` or materialized LiteLLM
config. Adopting new tier defaults requires `forge proxy edit <proxy_id>` or recreation of the affected proxy/backend
before restart. For model upgrades, follow `docs/end-user/model_selection.md` for model-specific reasoning/sampling
changes. When updating LiteLLM adapters, copy complete bundled deployment entries, including any `model_info` capability
and pricing metadata; restarting alone reloads the saved config. Stop affected proxies with
`forge proxy stop <proxy_id>` before restarting with `forge proxy start <proxy_id> --smoke-test`. Existing OpenRouter
proxies can forward explicit Astra workflow workers without changing their tier defaults; LiteLLM backends must serve
the Astra route. Before recreating the local LiteLLM adapter, back up its config outside `~/.forge/backends/litellm/`;
see the saved-configuration upgrade procedure in `docs/end-user/proxy.md`.

For GPT-6.2 pricing changes, run the offline deployment tests in `tests/src/backend/test_litellm_model_metadata.py`.
Compare Astra and Sol at 272,000 and 272,001 prompt tokens with the same output length. Include cache reads and
30-minute and 12-hour writes, check the gateway's response cost, and compare Ultrafast with Standard at each length. The
expected launch multiplier is three through February 28, 2027 (Pacific time). Run
`tests/integration/proxy/test_gpt_62_ultrafast_cost_e2e.py` against its local fixture to check that the
gateway-calculated amount reaches the request's telemetry record and both proxy caps.

For Sonnet 5.5 thinking or translation changes, run
`./scripts/test-integration.sh tests/integration/proxy/test_sonnet_55_e2e.py` and exercise the direct worker with
`forge workflow panel -p "<review prompt>" -m claude-sonnet`. The integration gate requires `ANTHROPIC_API_KEY` and
`OPENROUTER_API_KEY` and covers native thinking/tool-choice refusals, translated streaming and sampling filtering, and
passthrough preservation of signed tool history. Translated `between_tools` uses the lowest supported effort; exact
native semantics require Anthropic passthrough.

For Fable 5.2 routing or translation changes, run
`./scripts/test-integration.sh tests/integration/proxy/test_fable_52_e2e.py`. Local synthetic upstreams verify
required-ZDR substitution, sampling filtering, forced-tool refusals, and signed-history passthrough. See
`docs/end-user/model_selection.md` for saved-proxy alias recovery and the direct-LiteLLM tool-choice limitation.

For Gemini 4 tool-history or default-tier changes, run
`./scripts/test-integration.sh tests/integration/proxy/test_gemini_4_defaults_e2e.py -m slow` with `OPENROUTER_API_KEY`
and a paid-tier `GEMINI_API_KEY`. This live gate covers streaming and non-streaming tool round trips on the Neon and
Hydrogen default tiers, `xhigh` acceptance under required ZDR, and continuing another model's tool call through
OpenRouter and through local LiteLLM to Google AI. The default no-argument integration run excludes it, along with the
live Google AI cases in `test_session_routing_e2e.py`. Follow the Neon and Hydrogen migration in
`docs/end-user/model_selection.md` before using the default Gemini workflow worker with a saved LiteLLM backend.

### Sessionless Codex through OpenRouter Responses

The loopback fixtures exercise translated and explicit Responses profiles, the legacy OpenRouter backend fallback, both
clients on one port, endpoint-specific audit and smoke output, unreported cost and a shared two-cent cap. They also
check the OpenRouter-only Codex launch flags and retain coverage for local LiteLLM subresources and accounting. Use
synthetic credentials for this suite.

```bash
PYTHON_DOTENV_DISABLED=1 GEMINI_API_KEY= OPENROUTER_API_KEY= ./scripts/test-integration.sh \
  tests/integration/proxy/test_codex_openrouter_responses_e2e.py \
  tests/integration/proxy/test_litellm_streaming_cost_e2e.py \
  tests/integration/cli/test_proxy_commands_integration.py::TestProxyCreateAndStart::test_create_json_failed_smoke_is_one_result_and_preserves_proxy
```

For native TUI acceptance, run `forge_acceptance.py --selftest` with the manifest's pinned Codex binary and a new
receipt path. Verify the read and follow-up edit on both model slugs, the cap and the generation lookups. A live rerun
requires a separately approved manifest and a dedicated credit-limited key.
[Harness and commands](../../scripts/experiments/openrouter/README.md#codex-responses)

For launch-default changes, set `service_tier="priority"` in a disposable Codex home and use a loopback OpenRouter
fixture. On a CLI that supports `--no-daemon`, verify that the tier and shared-server warnings are absent. The default
Responses request should omit `service_tier`, and an explicit `-- -c 'service_tier="flex"'` should send `flex`. Also
launch with the minimum supported Codex CLI to catch unsupported flags.

## Backends, telemetry and costs

For downstream-telemetry retention or config-ownership changes, inspect configured, effective, and source state with
`forge config show --json`; preview legacy proxy-key migration with `forge config migrate-retention [--json]`, apply it
with `--yes`, and restart running proxies. Without an explicit global policy, conflicting or unreadable legacy inputs
must disable pruning and block migration instead of selecting a value. Apply writes the global policy before removing
still-matching legacy keys, and normal proxy startup must not rewrite user-owned proxy files.

For backend-source, telemetry, provider-trace, and cost-accounting changes, verify the operator read paths:
`forge model backend list|show <source-or-backend-id>|test-auth <source-id>`,
`forge telemetry trace list|show <request_id>|explain <request_id>`, and
`forge telemetry costs show --by-model|--by-verb`, plus `forge proxy metrics [proxy_id] --json`. Cost breakdown flags
are mutually exclusive; JSON retains both summaries, and verb runs count unique Forge run IDs separately from requests.
Bare metrics JSON is always a proxy-ID-to-metrics/null map, while a selected proxy returns its raw metrics object. Use
`forge telemetry costs reset --dry-run` before destructive telemetry resets; `reset` wipes legacy costs,
downstream/upstream telemetry, cap state, audit sidecar state, usage events, and derived status-line caches, while
running proxies keep in-memory cost/cap counters until restarted. For backend lifecycle or remote-reconcile changes,
also verify `forge model backend start <source-or-adapter>`, `forge model backend stop <runtime-id>...|--all`,
`forge model backend delete <adapter>`, and `forge model backend reconcile <source-id> --request-id|--remote-id`; `stop`
targets runtime instance ids from `list`, not source ids or adapter names.

For LiteLLM streaming-cost changes, run
`./scripts/test-integration.sh tests/integration/proxy/test_litellm_streaming_cost_e2e.py`. Verify final `usage.cost`
counts once toward telemetry and caps, while missing cost stays unavailable and distinct from explicit zero.

## Workflow workers and review

For workflow-worker or review-engine changes, run `forge workflow list-models --available --json`, refresh Codex
readiness with `forge runtime preflight codex`, then exercise `forge workflow panel -p "<review prompt>" -m codex` and
`forge workflow panel -p "<review prompt>" -m claude-opus,codex`. Codex workers are opt-in and run read-only; panels
that include one must use blind context (`--context blind`). The default worker set remains Claude-backed. `--proxy`
does not reroute direct Claude or Codex workers, and `--effort` applies only to Claude workers.

For worker native-control changes, run
`./scripts/test-integration.sh tests/integration/docker/test_worker_native_controls.py`. Verify workers disable native
delegation, native memory, and Claude skills; resumed reviews must preserve the source transcript and managed root
settings remain unchanged.

## Policy CLI and hooks

For policy CLI or hook changes, exercise `forge policy check --bundle coding_standards --file <path>` and
`git diff | forge policy check --bundle coding_standards --diff`; exactly one content source is valid. Unknown policy
bundle names, unknown `bundle_config` owners, and invalid supported-bundle field types must fail atomic engine
construction. The diff path splits multi-file patches into per-file contexts, evaluates tests before implementation
through one engine, and reports `files_checked` plus each violation's `file_path` in JSON. It must preserve boundaries
for Git C-quoted paths, renames, copies, binary patches, and combined diffs, and fail closed when a non-deletion chunk
cannot be attributed. The removed `workflow` bundle diagnostic must name both `policy.bundles` and
`policy.bundle_config.workflow`. Claude and Codex hooks report that build error and allow the action before the
configured fail mode applies.

For Claude policy-feedback changes, run `./scripts/test-integration.sh tests/integration/docker/test_policy_hooks.py`.
Allowed-action context must use `hookSpecificOutput.additionalContext` without `permissionDecision`; disabling
`policy_summary_feedback` must retain blocks and operator warnings.
`uv run python scripts/experiments/claude-hooks/policy-feedback.py` prints a synthetic native-trial manifest; actual
native receipt and permission checks require a separately approved `--run <manifest> --output <new-absolute-directory>`
trial.

For Codex policy-feedback changes, test `forge config set codex_policy_feedback_format=source-only` against the `normal`
default, and `forge config set policy_summary_feedback=off` against `on`. Clean allows stay silent; disabling summaries
must retain blocking reasons, operator notices, audit evidence, and required Stop correction guidance. See
`docs/end-user/policy.md` for verified quotation rules and executor admission.

## Jev client

For Jev client changes, follow `scripts/experiments/jev/README.md`.
`PYTHON_DOTENV_DISABLED=1 uv run python scripts/experiments/jev/probe.py [--stage measurement]` prints a synthetic
manifest without dispatch; `--live` requires explicit approval of that manifest. A2/A3 consumer experiments are retired;
see `docs/design_history.md` for the preserved evidence and source revision.

## CLI commands

For CLI surface changes, check `docs/developer/cli_style_guidelines.md`: use explicit leaf verbs, keep read-command
results on stdout, route diagnostics/errors/prompts to stderr, expose stable `--json` on scriptable list/show/status
surfaces, and send recovery output through `forge.cli.output` helpers. Conflict-bearing dry-run previews remain on
stdout even when they exit non-zero; only the terminating failure diagnostic goes to stderr. Keep error messages
accurate and offer only recovery commands that apply to the current install and runtime. Extend
`tests/src/cli/test_output_streams.py` when a new read leaf could split result and diagnostic streams.

## Session lifecycle, transfer and memory

For resume, transfer, memory-writer, and activity changes, verify the user-facing surfaces:
`forge session resume <name> --fresh --review`, `forge session transfer show|regenerate|edit|diff`,
`forge session memory report [session] [--latest|--all|--json]`, and `forge telemetry activity [session]`; `forge usage`
is removed, and `forge telemetry costs show` is the authoritative reported spend view, including direct Jev requests
when no proxy ID is supplied. For fresh-transfer ancestry changes, verify
`forge session resume <parent> --fresh --depth <N|all>`; explicit uses of `--strategy` or `--depth` require `--fresh`,
`N` must be positive, and `all` follows lineage to the terminal ancestor. For rewind launch-strategy changes, verify
`forge session resume <parent> --fresh --strategy rewind --drop-last N` and
`forge session fork <parent> --worktree|--into <path> --strategy rewind --drop-last N`; `rewind` is not a
`forge session transfer regenerate` strategy.

For transfer-fidelity changes, run
`./scripts/test-integration.sh tests/integration/cli/test_transfer_fidelity_integration.py`. Check retained tool text
through regenerate/show and fresh resume with `--review`; oversized interactive Codex prompts must refuse before launch
and remove the new session and snapshot. See `docs/end-user/transfer.md` for delivery and strategy alternatives.

For child configuration or reset changes, follow the configuration inheritance and reset section in
`docs/end-user/session.md`. Fork/fresh children drop generic overrides but inherit effective memory-writer settings;
relaunch children keep overrides. Verify `forge session reset --all` preserves baseline supervisor suspension; use
`forge policy supervisor on --session <name>` to resume it. Verify invalid parent overrides block fork, fresh resume,
and active-session relaunch before proxy startup or child creation. Follow the diagnostic's recovery for the parent,
using `forge session reset --session <parent> <key>` when it offers a keyed reset.

For session-store, launchability, repair, or workspace-scope changes, preview orphan recovery with
`forge session repair [--json]`, apply it with `forge session repair --yes`, check degraded records with
`forge session list --scope workspace --json` and `forge session show <session> --json`, and inspect Git worktree
membership and session occupancy with `forge workspace worktrees [--json]`. Repair is scoped to the current Forge root;
it must never recreate missing worktrees or accept collision/corrupt records. Valid missing-worktree sessions remain
visible but unlaunchable until the checkout returns.

For session deletion or cleanup changes, cancel an unconfirmed `forge session delete <name>` and compare the default
`forge session clean --older-than <days>` preview with its `--yes` apply. Verify `forge session purge <name> --json` and
project-scoped `purge --all`, then apply only to isolated fixtures. Delete/clean preserve native files and remove
unreferenced Forge content; purge additionally removes verified native paths. Both refuse active sessions, workers and
dependents. Include `--delete-worktree` and missing-root retries through `--forge-root`. Pre-confirmation reads must not
repair indexes or drain work. Test stale instance writers, changed inventories and partial failures; retain external
retry evidence until all removals succeed. Native-layout probes require a separately approved concrete manifest.

For abandoned worker recovery, use an isolated launcher that exits before releasing its lease. Check that
`delete --all --force` lists the lease, cancellation preserves it, and confirmation clears it even if a native child
survived. Verify live workers still block and purge still checks native runtime activity.

For native-session adoption changes, run `forge session adopt [--json]` from the native launch directory, adopt a full
Claude conversation or Codex thread id with `forge session adopt <conversation-id> --name <name>`, then resume the
managed session. Bare preview lists Claude conversations only and `--model` is Claude-only; runtime selection must come
from on-disk evidence, ambiguous or unverifiable matches must fail closed, and deleting the Forge session must preserve
the original transcript or rollout.

## Session model routing and reasoning effort

For Claude model-route changes, exercise `forge session start|resume|fork|incognito --model <catalog-id-or-alias>` and
use `--model-tier haiku|sonnet|opus` only to disambiguate a multi-tier proxy match. Inspect intent, durable commitment,
current proxy facts, and the validated event sequence with `forge session model show|history <session> --json`. Explicit
`--proxy` is strict, `--no-proxy` accepts only direct Claude models, and bare resume or inherited-route fork reuses
stored route intent. `--model` alone cannot cross an inherited proxy boundary; refusal recovery must offer only
applicable restart or reroute commands, preserve the exact resume target and complete intended resume/fork action
(including explicit lifecycle options), and add `--model-tier` only when disambiguation is needed. If a fresh child
already exists, recovery must target that child rather than create another from the parent. Verify that historical and
non-Claude alternatives preserve the requested model and selected tier's hyperparameters through launch. A non-Claude
`--model` may start a paid proxy even with `--no-launch`. Codex rejects catalog `--model` and accepts `--proxy` or
`--no-proxy` only at creation.

For managed Codex proxy verification, use a disposable Codex home, an isolated Forge project, a loopback Responses stub
and a synthetic backend credential. Run the headless start and resume and the TUI start and reattach commands in the
[managed proxy guide](../end-user/codex_proxy.md#managed-sessions). Compare requested and dispatched slugs, thread ID
and run IDs with the rollout, routing journal and proxy attempts. Swap the listener ID at the same URL and verify both
resume forms refuse before the stub receives history. A changed fallback for the recorded slug must also refuse. Use a
separately trust-enrolled fixture for hook-dependent supervision. Run the managed CLI and reporting fixtures together:

```bash
./scripts/test-integration.sh tests/integration/core/test_managed_codex_proxy.py tests/integration/cli/test_codex_proxy_session_reports.py
```

When several registered proxies share a base URL, check `forge session show <name> --field context.proxy.proxy_id` after
SessionStart. The field prints an ID when exactly one matching entry is `healthy` or `starting`. Otherwise it prints an
empty line and bare resume validates the saved template.

For Claude reasoning-effort changes, run
`./scripts/test-integration.sh tests/integration/proxy/test_effort_observation_e2e.py`. Inspect `effort.observations` in
`forge session model show <name> --json` for the last outbound effort per tier on that launch. In Claude,
`%session model show` distinguishes an omitted effort parameter (`unset`), one the client removed (`dropped`), and
missing evidence (`unknown`). The same gate checks Gemini 4 thinking-level translation, including the `xhigh` ceiling on
Neon and Hydrogen, sampling filtering, and Vertex unary/streaming output limits against local stub upstreams.

## Codex runtime, consumer lanes and supervision

For Codex-runtime session changes, start with `forge runtime preflight codex`, then verify the relevant launch path:
`forge session start <name> --runtime codex --resume-from <parent> --task "..."`,
`forge session resume <name> --task "..."`, or the interactive TUI path that omits `--task`. `--context-delivery hook`
and Codex policy enforcement require Codex hook registration/trust for `$FORGE_HOME/bin/forge-hook codex-session-start`
and `$FORGE_HOME/bin/forge-hook codex-policy-check`; use `forge codex status` for static registration and
`forge runtime preflight codex --verify-enrollment` for empirical user-scope trust verification (it runs one cheap Codex
turn). The default transfer delivery is `initial-message`. Runtime hooks are user-scoped via the `forge-hook <name>`
dispatcher, while project/local extension installs own status line and project assets. For consumer-lane or
subscription-billing changes, verify
`forge session lane set|show|clear --consumer <supervisor|memory_writer|shadow_curation|team_supervisor>`,
`forge policy supervisor status`, and `forge telemetry activity [session]`; `--backend claude-max` should label only
keyless direct runs as `subscription_quota`, while resolvable keys remain `api` and proxied runs remain `unknown`. This
inherited rule applies to all four consumers, including existing frozen supervisors. The supervisor-only
`--auth-mode subscription-only` opt-in instead verifies and uses a stripped, direct Claude login child; test both
policies, all four lane commands, and refusal without inference when the opt-in cannot verify auth. Usage credits must
be disabled on the account. Plan-file supervision supports host Claude/Codex executors; sidecars refuse it. Keep
reviewer timeouts within 1–45 seconds and preserve the registered 60-second hooks. Verify reviewer capability admission
on the old supported CLI and after an executable update; auth-only user/sidecar helpers must still work. Check stale
sidecar-image refusal, v2-compatible ordinary writes, and separation of live review evidence from shadow audits.

For direct Codex resume accounting, set `CODEX_HOME` to a disposable home with `cli_auth_credentials_store = "file"` in
its `config.toml` and sign in there with `codex login --device-auth`. Use an isolated `FORGE_HOME` and verify the
preflight reports `codex_store` and `subscription_quota`. Export the same `CODEX_HOME` before running
`./scripts/test-integration.sh tests/integration/core/test_codex_session_start.py --basetemp=<new-test-directory>`. The
fixture writes `native-resume-usage.json` beneath that directory. Compare the terminal counts with the independent
rollout samples, request totals and session activity for the start and each resume.

For Codex Stop-review changes, run `forge extension sync` and trust the updated user hooks, then verify
`forge runtime preflight codex --verify-enrollment --json` reports `stop_review_enrolled: true`. Configure an idle
managed host Codex executor with `forge policy supervisor set --session <session> --plan <path> --trigger stop`, then
inspect `forge policy supervisor status --session <session> --json` and `forge telemetry activity <session> --json`.
Verify at most one reviewer dispatch and one correction per explicit turn, with subsequent work retained as unreviewed.
Preview `forge policy supervisor reset-review --session <session> --json` before applying with `--yes`; reset excludes
pending work, preserves the spent allowance, and requires a new explicit prompt. Follow `docs/end-user/policy.md` for
partial coverage and recovery; Stop rejects non-Codex executors, sidecars, cascade, and shadow sampling.

For native Codex supervision, follow `docs/end-user/native_supervision.md` for the admitted binary/source matrix. After
disabling account extra usage, use `forge policy supervisor auth login --runtime codex --confirm-extra-usage-off` with
the source's ChatGPT account, then `forge policy supervisor auth status --runtime codex --json`. Configure a completed
source with
`forge policy supervisor set <planner-or-full-thread-id> --source-runtime codex --runtime codex --model gpt-6.1-sol --supervisor-effort low --auth-mode subscription-only`.
Verify source identity and latest attempts through supervisor status and telemetry activity. Native Stop sources require
`--trigger stop --plan <path>`; shared or active executor sources require Stop. Unsupported histories/binaries and
unavailable auth must refuse without fallback; `--auth-mode api` is a separately authorized paid route.
