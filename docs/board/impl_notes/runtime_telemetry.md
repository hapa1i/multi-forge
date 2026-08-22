# Implementation Notes: Runtime and Telemetry

Durable routing, backend, consumer, proxy, policy, and telemetry decisions.

[Implementation-notes index](../impl_notes.md)

---

## Notes

### Mixed headless runtime workflows separate execution from routing (runtime_neutral_workflow_workers, shipped 2026-07-23)

- **Execution runtime and model routing are separate axes.** Give runtime-owned transports an explicit routing source
  and keep route-null success a consumer-scoped invariant. Do not fabricate credentials, backend ids, proxy ids, or
  model ids merely to fit a route-shaped abstraction.
- **Runtime readiness is one logical-invocation snapshot.** Freeze expensive or stateful readiness once and carry that
  object through every worker and derived round so one command cannot observe multiple machine states.
- **Mixed fan-out has one lifecycle owner.** Use one concurrency pool, one child registry, and one cancellation owner
  across runtimes. Nested runtime pools multiply the child cap and prevent prompt main-thread cleanup.
- **Worker specialization preserves runtime.** Stance and role transforms must carry the runtime field; field-by-field
  reconstruction can silently fall back to the default runtime while selection and reporting still name the original
  worker.
- **Reliable runtime-error envelopes are domain failures even at exit zero.** Preserve both output streams for
  diagnosis, but keep usage status, synthesis eligibility, and the user-visible result aligned on failure.
- **Portable workflow frontends distinguish host runtime from worker runtimes.** Compile one neutral source into native
  host packages, state default-worker behavior explicitly, and verify runtime-specific install, status, sync, and
  disable from a built wheel rather than only the source tree.

### Every real provider call must emit a provider-trace; retry paths included (Defect B, shipped 2026-07-04)

`proxy/server.py::create_message` has three provider-call success paths -- streaming, non-streaming, and the auth-retry
`client_factory.invalidate_and_retry` branch. Each records cost + metrics AND must emit `record_provider_trace`, or the
downstream plane has a "what happened to this request?" hole. Defect B was exactly that: the retry branch (401 ->
credential refresh -> 200) logged cost/metrics but skipped the trace, so a refreshed request left no record.

- **Guard**: all three sites now spread one `_trace_ctx` dict (the 8 run-tree context kwargs, built once). A new
  provider path that forgets `**_trace_ctx` fails loudly -- `record_provider_trace`'s
  `request_id`/`proxy_id`/`mapped_model` are required (no defaults), so omission is a TypeError, not a silent gap.
  Adding a fourth provider path? spread the dict.
- **Capability gating lives inside the helper** (call sites stay unconditional; a non-capable backend writes nothing).
  Verified end-to-end by `tests/regression/test_bug_auth_retry_provider_trace.py`, which drives the retry branch with
  the real helper and reads back via `read_provider_traces(request_id=...)` for capable (one record) + non-capable
  (none).

### Shared cost/usage vocabulary Literals live in a telemetry leaf, never in `core/usage` (shipped 2026-07-04)

Any `Literal` shared by BOTH the usage ledger and downstream telemetry (`Reporter`, `Confidence`, and future kin) must
be defined in `core/telemetry/vocabulary.py` -- a leaf that imports only `typing`, below `downstream` -- NOT in
`core/usage/vocabulary.py`.

- **Why**: `core/usage/__init__.py` eagerly imports `emit`, which imports `core/telemetry/downstream`. So `downstream`
  importing from `core.usage.*` cycles (`downstream -> usage/__init__ -> emit -> downstream`). The dependency arrow is
  `usage -> telemetry`; shared vocab must sit on the telemetry side so both planes import *down*.
- **Pattern**: `downstream.py` and `usage/vocabulary.py` both import + re-export the leaf's names, so existing
  `from ...downstream import Reporter` / `from ...usage.vocabulary import Reporter` sites are unchanged;
  `usage/vocabulary.py` lists them in `__all__` to mark the re-exports used.
- **Sibling vs foreign leaf**: `downstream -> .vocabulary` (same telemetry package) is cycle-safe because the package
  `__init__` is already mid-run when `downstream` loads. A *foreign*-package leaf whose `__init__` eagerly pulls
  machinery is the trap that killed the "vocabulary owns" direction (the card's original assumption).

### consumer_lanes epic closed: context-delivery model, not lane plumbing, gates a consumer's runtime swap (shipped 2026-07-01)

The `consumer_lanes` epic shipped and closed (`done/epic_consumer_lanes/`). The lane contract --
`(runtime x backend x model)` per consumer, resolved once and frozen, default = current behavior -- is normative in
design.md §3.5/§3.6.2 + design_runtime.md §G. Durable takeaways for future runtime/lane work:

- **A consumer's context-delivery model, not its lane plumbing, decides whether a non-claude runtime is addable.** The
  four wired consumers split cleanly. Supervisor / shadow-curation / memory-writer got codex arms because their context
  is **blind or in-band** -- `codex exec` has no `--resume`, so the approved plan rides a preamble (or, for the semantic
  supervisor, a curated transfer body). Team-supervisor is the exception: its context is delivered by
  `claude -p --resume <resume_id>` (`policy/team/handlers.py:267-269`; `TEAM_SUPERVISOR_CONSUMER.allowed_lanes` carries
  no codex lane, `:38-43`), so a codex lane there is **not** "one more aux arm" -- it needs runtime-neutral plan/context
  delivery first (`proposed/team_supervisor_plan_context/`). When adding a runtime to any consumer, classify its context
  source before assuming the lane substrate suffices.
- **"Lane-bound" != "can dispatch a different runtime."** claude-max binding across all four consumers (T6a) changed the
  billing label only -- claude-max shares the `claude_code` runtime. A real runtime swap (the T4/T6b/T6c codex arms) is
  a further step, gated on the context model above. Keep the two levels distinct.

### Adding a codex dispatch arm to an aux consumer: validate the lane, map into the consumer's own contract (consumer_lanes T6b, shipped 2026-06-30)

Durable rules from wiring shadow-curation's `codex exec` arm (`session/shadow_curation.py`,
`_dispatch_codex_shadow_curation`). `_dispatch_codex_supervisor` is the *template*, but a near-verbatim copy is wrong --
three axes are per-consumer.

- **The aux consumers are NOT a uniform "mirror T4."** Only shadow-curation is a clean mirror (blind, read-only,
  stdout-is-output). memory-writer is workspace-write file-editing (shipped as T6c); team-supervisor is plan-blind under
  codex because the approved plan rides Claude's `resume_id` and codex has no `--resume` (deferred until plan-snapshot
  machinery is ported). Sweep output shape / sandbox / context source / degrade path before assuming a consumer is
  mirror-able.
- **Validate the bound lane before selecting the arm -- never branch on the raw `LaneRecord.runtime_id`.** A
  stale/corrupt explicit binding could otherwise dispatch codex on an invalid lane (codex runtime + non-codex backend,
  bypassing `allowed_lanes`) or fall through to claude on an unknown runtime. Run it through the same
  `LaneRecord -> Lane -> resolve_lane` guard the supervisor uses; `None` resolves to the default claude lane.
- **Degrade maps into the consumer's existing contract, not the supervisor's fail-open.** shadow-curation is
  user-invoked, so a cold/stale preflight or a failed turn **fails loud** (`CurationResult(success=False)` + a
  CLI-visible hint -- the new `CurationResult.error`, in human + `--json`), never a silent claude fallback ("no
  fallback" is the epic rule; T7 is the only exception). A policy-hook consumer (team) would degrade to its `(0, "")`
  allow; a best-effort async one (memory-writer) to `return False`.
- **`Attribution.operation` is pinned to the consumer's operation, NOT `None`.** The supervisor passes `None` to
  suppress the invoker's auto upstream row because its engine already logs `policy.evaluate`; curation has no engine
  row, so the invoker's auto `record_upstream_operation` IS its only upstream outcome and must carry
  `operation="memory.shadow_curation"` to match the claude path. Pin-vs-suppress is decided by whether an engine row
  already exists.
- **`runtime_is_error` must be folded into success.** `HeadlessResult.success` is returncode-only, so an
  exit-0-but-failed codex turn would otherwise persist an empty report. Fold it so the turn fails loud.
- **`runtime_is_error` does NOT catch a sandbox write-denial (T6c, write-capable arms).** A live probe showed a codex
  `--sandbox workspace-write` *denial* (writing outside the project) exits 0 with `is_error=False` -- the rejection
  rides `turn.completed`, not an `error`/`turn.failed` event. So folding `runtime_is_error` catches provider/turn
  failures but NOT a thwarted write. Acceptable for memory-writer because its docs live under `cwd=forge_root`
  (in-project writes auto-approve, never hitting the rejection path), so no Claude-style permission scan is ported; any
  future arm that writes *outside* its cwd needs a postcondition check, not `runtime_is_error`.
- **Codex E2E trap: the autouse `isolate_codex_home` fixture masks ChatGPT (`codex_store`) auth.** A real `codex exec`
  test on the host ChatGPT login must restore the host `CODEX_HOME` captured at import time, and clear
  `CODEX_API_KEY`/`CODEX_ACCESS_TOKEN` (preflight resolves them before `codex_store`, so a host with both resolves
  `billing_mode="api"` and fails a `subscription_quota` assertion). The upstream-outcome log is failure-biased, so a
  *successful* codex run emits the usage event but no outcome row -- assert accordingly
  (`tests/integration/session/test_shadow_curation_codex_smoke.py`).

### Consumer-lane freeze: immutability, not billing; per-lifecycle trigger (consumer_lanes T1b/T6a, shipped 2026-06-30)

Durable rules for `confirmed.consumer_lanes` and the two freeze sites: the supervisor in `cli/hooks/policy.py`, and
`cli/consumer_lane_freeze.py::persist_lane_freeze` for memory-writer / shadow-curation / team-supervisor.

- **The freeze is immutability + observability, NOT billing-enablement.** `read_bound_lane` / `read_bound_backend_id`
  read **confirmed-first else intent**, so the CLI's `intent` write already bills honestly (a keyless+direct
  `claude-max` run -> `subscription_quota`). Freezing into `confirmed` only adds write-once immutability and a stable
  observable lane. Do not gate billing on the freeze or add per-consumer billing tests -- `resolve_billing_mode` is
  consumer-agnostic (covered by `test_billing.py` + `test_read_bound_backend_id_for_all_consumers`).
- **Two lifecycles, two freeze triggers -- by design (do not unify).** The supervisor is a *registered*, session-scoped
  entity (`resume_id`) and freezes **eagerly at the first policy check** -- registration is its commitment point, and
  the eager freeze is what anchors T1b's "already bound" reject. The aux consumers are *per-hook invocations* with no
  registration, so they freeze **only on a real dispatch** (an `on_dispatch` hook fired past every skip-return:
  below-min-turns / no-docs for memory-writer; cache/tagger/resume/depth for team). Making the supervisor
  freeze-on-dispatch would leave a registered-but-never-escalated supervisor's lane unfrozen and break the reject UX --
  an investigation (2026-06-30) confirmed its freeze fires on cache hits / cascade plan-check-only allows, which is
  correct for its lifecycle, not a bug.
- **Shared guard: thread the dispatched lane, re-check equality under the lock -- never fresh-read.** Both sites pass
  the lane the run dispatched on (the same read `backend_id` came from) and freeze only if
  `read_bound_lane(m) == dispatched_lane` still holds under the lock, so a concurrent `lane set/clear` drops the stale
  write. Re-reading the manifest under the lock instead (the first T6a cut) lets `confirmed` diverge from the billed
  backend -- that was the review's Finding 2.
- **Freeze is best-effort bookkeeping.** A lock/IO failure in `persist_lane_freeze` is swallowed (logged at debug); the
  run proceeds and the next dispatch retries. Hook sites pass `HOOK_LOCK_TIMEOUT_S` (0.2s), not the helper's 5.0s
  default.
- **Test the trigger, not the LLM.** Fake the consumer to invoke (or skip) its `on_dispatch` hook to assert
  freeze-on-dispatch vs skip-never-freezes without a real `claude -p` call (`test_consumer_lane_freeze.py`,
  `test_memory_writer_cli.py`, `test_team_hook_lane_freeze.py`).

### Backend identity axes: backend instance vs managed process vs telemetry origin (shipped)

Shipped 2026-07-04 (`backend_instance_identity_model`). Keep these boundaries intact when changing backend/catalog,
template, auth, telemetry, or local lifecycle ownership:

- **Credential registry is a dependency leaf.** Credential data lives in `src/forge/core/credential_registry.py`, while
  template/catalog-aware logic lives above it (`forge.backend.sources`, `forge.core.auth.template_secrets`,
  `forge.core.auth.capabilities`). Do not move `CREDENTIALS` back into a module that imports template/catalog logic;
  that recreates the `sources -> auth -> sources` cycle that Phase 2 removed.
- **Backend instance ids and managed process ids are different value-spaces.** `ModelSource.id` values such as
  `litellm-gemini-local`, `openrouter`, and `anthropic-direct` currently implement logical backend instance ids.
  `ManagedBackendProcess.process_id` values such as `litellm-4000` are local process ids. Downstream telemetry
  `backend_id` writes the logical backend instance id, never the managed process id; local backend instance ids must not
  become port-derived.
- **The local backend instances share one adapter+port, so managed-process attribution is many-to-one.** The local
  LiteLLM backend instances `litellm-gemini-local`, `litellm-openai-local`, `litellm-anthropic-local`, and
  `codex-responses-local` all declare `adapter=litellm, default_port=4000`. The shipped default `litellm.yaml`
  references both `GEMINI_API_KEY` and `OPENAI_API_KEY`, so a single `litellm-4000` process legitimately backs multiple
  matching backend instances. `forge model backend list`/`show` surface this as `(shared)` /
  `managed_process.shared_with`. The `_local_source_matches_backend_config` heuristic that disambiguates this is
  **display-only** (`cli/backend.py`); it must never feed downstream telemetry `backend_id`, which stays derived from
  `proxy.backend`. A test fixture narrower than the shipped default (e.g. gemini-only) hides the multi-match case — lock
  shared-display behavior with a multi-key fixture, not a single-provider one.
- **`proxy.backend` has two validation postures.** Template load is strict: old `proxy.source`, unknown backends,
  ambiguous shorthand, missing values, and runtime-native backends fail loudly before proxy creation. Runtime
  `proxy.yaml` is user-owned ("edit freely"), so an unrecognized `backend` is a misconfiguration to warn-and-degrade on,
  not corruption to reject: `_backend_instance_id` (`proxy/server.py`) warns **once** (module-level set guard) and
  returns the raw value; capability gates (provider-trace, OpenRouter user, responses ingress) fail safe on an unknown
  id.
- **Telemetry `source_id`/`source_kind` are origin/correlation, not backend identity.** The backend identity field is
  downstream `backend_id`; the source fields remain the origin axis (`proxy`, `provider`, reporter). The schema-v2
  backend-identity break skips missing/older downstream schemas with a one-time warning and activity/cost
  `skipped_legacy_schema` counts rather than reattributing old records.

### Backend remote reconciliation: registry capability + total external-data coercers (shipped)

Shipped 2026-06-20 (`backend_remote_reconciliation`, PRs #41/#42/#43). `forge model backend reconcile` joins one local
downstream trace to one remote account-side record via an adapter under `src/forge/backend/remote/`.

- **Remote-reconcile capability = adapter-registry presence, not a flag.** A source is reconcilable iff
  `forge.backend.remote.get_remote_adapter(source_id)` resolves — there is deliberately no `ModelSourceCapabilities`
  field for it. A flag could drift from the registry, and it keeps an account-side *read* concern out of the
  proxy-*write*-path capability struct. Add a backend by registering an adapter, not by setting a flag.
- **The remote read path is external data: coercion must be total, classification never a misleading success.**
  `httpx`/`json.loads` parse bare `NaN`/`Infinity`/`1e400` by default, so `round()`/`int()` on a 200 body can raise. The
  error-vs-data invariant requires every surprising-but-parseable response to become
  `RemoteRecord(outcome="unavailable")`, never an exception (`RemoteAdapterError` is reserved for adapter bugs / config
  faults, and never embeds a key or body). Concretely in `openrouter.py`: `_as_cost_micros`/`_as_int` drop
  non-finite/overflow/bool; `_record_from_body` accepts only a generation object (a dict, optionally under a dict `data`
  wrapper) and maps any other shape (`{"data": []}`, a JSON array/string/number) to `unavailable`, not an empty `found`.
  Regression: `tests/regression/test_bug_backend_reconcile_malformed_200.py`.
- **Comparative buckets need both sides.** `missing-remote`/`missing-local` require a local anchor *and* a remote
  answer; single-sided lookups yield only `remote`/`not-queryable`. Local cost/tokens are never overwritten by remote
  figures (kept side by side with provenance).

### Review/audit fan-out must not run agents with Bash against the live working tree

Recurring hazard (hit 2026-06-20): an adversarial-review workflow run with `general-purpose` agents (tool access `*`)
edited source mid-review even though instructed to only return findings; `git checkout` then carried the uncommitted
change across branches and `git add -A` swept it into an unrelated commit.

**`Explore` is NOT a sufficient guard (hit 2026-06-23).** An audit workflow run with the read-only `Explore` agent type
(no Edit/Write) still has **Bash**. Agents instructed to "use git log/diff to inspect each slice" ran `git stash` +
`git checkout <commit>` + `git reset` to view historical state, which **reverted the entire uncommitted working tree**
to HEAD and left the repo in detached HEAD — clobbering ~33 files of unstaged Slice-02 work. Read-only file tools do not
prevent state-changing git via Bash.

Protections, in order of reliability:

- **Commit (or at least `git stash`) the work before any fan-out.** Committed/stashed state is recoverable; raw unstaged
  changes overwritten by `git reset --hard`/`git checkout -f` are not.
- Use `isolation: 'worktree'` so agents operate on their own checkout and cannot touch the primary tree.
- If agents must run in the live tree, instruct them: **read-only git only** (`log`/`diff`/`show`/`status`); never
  `checkout`/`switch`/`reset`/`restore`/`stash`/`clean`.

**Recovery:** if a tree gets reverted, check `git stash list` and `git reflog` first — an agent's `git stash` *saves*
the work (`git stash apply stash@{0}` restores it); the reflog's `reset: moving to HEAD` /
`checkout: moving from <branch> to <sha>` entries show what happened. Untracked files survive checkout/reset, so
newly-created modules are usually still present. Always `git status` before every `git add -A`.

### Status line: segment registry + Forge-unique segments (shipped)

Shipped 2026-06-03 (statusline-enhancement card). Durable rules for `src/forge/cli/status_line.py` +
`src/forge/cli/statusline/`:

- **Allowlist == producers invariant**: `names.SEGMENT_NAMES` must equal the set of `registry.SEGMENTS` producer names
  (enforced by `test_statusline_registry.py`). Add a segment's name and producer in the SAME change — a name without a
  producer would let `forge config set` accept a field that renders nothing. There are no reserved-but-unimplemented
  names. `forge config set`/`edit` is the strict gate (rejects unknown names/enums); the renderer drops unknown names
  and falls back to `DEFAULT_ORDER` when empty OR when a non-empty config resolves to nothing (never blanks the bar).
- **Proxy/session acquisition is plan-lazy**: every `registry.Segment` declares its `StatusSource` requirements. Resolve
  configured/default order into one immutable `RenderPlan` before calling `detect_proxy()` or `discover_session()`, then
  render from that same plan so acquisition and producers cannot drift. `statusline/types.py` owns neutral facts and
  `statusline/sources.py` owns proxy, transcript, session, and Git acquisition; the command module must not redeclare
  them. `statusline/formatting.py` owns presentation, visible-width, truncation, and separator-wrap helpers;
  `statusline/rendering.py` owns palette application, hardening, and final two-bucket layout. These shared formatting
  helpers use package-public names, and lower modules use the unambiguous `fmt` alias rather than the old command-shaped
  `sl`. Lower modules never import the command. A zero-source layout skips both probes; each requested source runs at
  most once. New segments must extend the exhaustive declaration test, while their own Git, transcript/cache, or
  hook-diagnostic work remains governed by lazy `RenderContext` access.
- **`DEFAULT_ORDER` is the golden contract**: empty `statusline.segments` reproduces the pre-config bar byte-for-byte
  (`test_statusline_registry.py` golden snapshots). It EXCLUDES `rate_limits` + every opt-in segment.
- **Lazy `RenderContext`**: derivations are `cached_property`, so a segment not in the active set does zero I/O (no
  transcript scan, Git subprocess, or proxy-field access). Producers call sibling `formatting` helpers; the command owns
  only stdin validation, shared-source acquisition, terminal width, and stdout.
- **Palette = output-level ANSI remap**: each role emits a unique code; `apply_palette` is a single-pass regex mapping
  default→themed. `default` palette == empty remap == byte-identical no-op (golden-safe). Glyphs thread ONLY into the
  `get_context_display` progress bar (block chars can't be safely output-remapped). Do not thread a `palette` arg
  through the `format_*` helpers.
- **Billing posture is evidence-based, never inferred from key presence.** Only an explicit `statusline.cost_mode`
  (`api` or `subscription`) declares the payer. The default `auto` stays ambiguous: direct-session rate-limit evidence
  shows subscription quota when present, otherwise the cost is hedged as `≈$`; raw `ANTHROPIC_API_KEY` presence never
  flips the display to API dollars because Forge may have hydrated that key into an OAuth session.
- **Forge-unique segments read EFFECTIVE state** (`apply_overrides(intent, overrides)` on the raw manifest, not raw
  intent) AND honor `policy.enabled` — a disabled policy makes the hook exit early (commands.py:1116), so
  `supervisor`/`policy` show `SUP(off)`/`pol:…(off)`, not active. `drift` must mirror proxy routing precedence: an
  explicit tier in stdin `model.id` (`explicit_tier_from_model`, 1:1 with the proxy's `_tier_from_model_name`) wins over
  `runtime.active_tier`, which is only the proxy `default_tier`. Using `active_tier` alone false-positives a pinned
  session on a different-default proxy.
- **Runtime-only state fails open**: the cache-hit throttle (`statusline/throttle.py`, keyed by
  `sha1(session_id|transcript_path)`) and all transcript/manifest reads degrade to recompute/None on any error — the
  status line must always exit 0. One-render command processes retain no transcript/numstat module caches;
  `RenderContext.cached_property` handles within-render reuse and persistent throttles remain file-backed. Guard value
  TYPES at point of use, not just shape at the boundary (a structurally-valid cache entry can carry a wrong-typed
  field).
- **Proxy spend caps**: `_attach_cap_summary` nests `CostTracker.cap_summary()` under `GET / metrics.costs.caps`,
  keeping `ProxyMetrics` decoupled from `CostTracker`. Cap amounts use `_fmt_cap_money` (four decimals below a cent),
  NOT `_fmt_dollars` (whose `int(usd*100)` collapses sub-cent caps to `0c`).

### Proxy tier/model resolver seams (proxy_tier_resolvers, shipped 2026-07-06)

- **Raw model-name tier words are single-sourced** in `forge.core.tiers.detect_tier_word()`. Proxy request validation,
  server passthrough tier detection, and statusline explicit-model tier detection delegate there. The helper preserves
  the existing naive substring behavior, including `fable -> opus`.
- **Statusline display names are deliberately different**: `get_tier_from_display_name()` still checks opus/fable first
  and defaults to `sonnet` when no tier word is visible. Do not fold display-name fallback behavior into the raw
  model-name tier helper.
- **LiteLLM provider-prefix vocabulary is shared only at detector sites** via `LITELLM_PROVIDER_PREFIXES`.
  `data_models._normalize()` intentionally keeps its narrower canonical-prefix stripper (`anthropic/`, `openai/`,
  `gemini/`); using the full LiteLLM prefix tuple there would over-strip and change forced-provider mapping.
- **Proxy port probing is shared, caller contracts are not**: `forge.proxy.ports.find_available_loopback_port()` owns
  the `127.0.0.1` bind probe and raises neutral `NoAvailablePortError`; `server.find_available_port()` still translates
  to `RuntimeError`, while `proxy_orchestrator._find_available_port()` still translates to `ProxyStartError`.

### Sessionless Codex proxy launcher: Responses passthrough + identity gates (shipped 2026-06-23)

Durable invariants from `forge_codex_command_group` for `forge codex start --proxy` and the Codex-facing Responses
transport.

- **Codex proxy support is a Responses passthrough, not a translation layer.** The shipped wire shape is
  `openai_responses_passthrough`: Codex's raw `/v1/responses*` HTTP/SSE traffic is forwarded byte-for-byte so signed
  reasoning items survive. Do not "simplify" this through the Anthropic/OpenAI chat converters unless `core.llm` has a
  first-class reasoning-item channel and the signature/continuity story is re-proven.
- **Capability is the full runtime conjunction.** A proxy is Codex-launchable only when live `GET /` reports both
  `wire_shape == "openai_responses_passthrough"` and `capabilities.responses_ingress is true`; file presence or a
  healthy Anthropic `/v1/messages` proxy is not enough. Keep preflight, route gating, smoke tests, and
  `assert_proxy_responses_capable` aligned to that same conjunction.
- **Identity verification is part of the capability gate.** `ensure_proxy()` resolves a proxy id by registry presence,
  not by proving the live port still belongs to that id.
  `assert_proxy_responses_capable(..., expected_proxy_id, expected_template)` must re-check `is_proxy`, `proxy_id`, and
  `template` from the same live `GET /` body before routing Codex. This prevents a stale registry entry whose port is
  now held by another capable proxy from silently misrouting the TUI.
- **The launcher configures Codex with argv `-c` provider overrides, never by writing `config.toml`.** The Phase 2 live
  probe proved list-mode `-c model_providers.forge_proxy.*` + env auth is sufficient. Preserve the no-`config.toml`
  boundary because Codex hook trust hashes the registration/config surface.
- **Sessionless means scrubbed and untracked.** `invoke_codex_bare_proxy` must not re-establish native Codex/OpenAI
  auth, `FORGE_SESSION`, `FORGE_FORGE_ROOT`, fork/session vars, `FORGE_SUBPROCESS_*`, or run-tree identity. It creates
  no manifest, no `confirmed.codex`, and no Forge resume path. Managed Codex sessions remain the
  `forge session start/resume --runtime codex` surface.

### Supervisor shadow sampling: deferred-audit + detached-worker reliability (shipped 2026-06-14)

Durable invariants for `src/forge/policy/semantic/shadow.py`, `shadow_runner.py`, `policy/semantic/plan_check.py`, and
the `_shadow_handler` in `cli/main.py`. The cascade's blind spot is the **false-aligned** case (a tier-1 `allow` the
frontier would have blocked); shadow sampling replays the frontier on a sampled subset without ever enforcing.

- **Capture/check split**: the frontier supervisor builds its OWN prompt from raw inputs (`raw_diff or new_content`) and
  reloads the plan at run time, so a deferred audit must freeze the **raw** `ActionContext` + a **copied** plan
  (`<hash>.plan.md`) + a routing snapshot — never tier-1's packed prompt text (it is local to `run_plan_check` and gone
  at the seam). Reconstruction fidelity is the locking test: rebuild → identical `SUPERVISOR_PROMPT`.
- **Work-queue reliability boundary is at spawn, not completion**: a handler "succeeds" the instant it `Popen`s and the
  marker is deleted, so the queue's poison cap never sees a detached worker's outcome. Idempotency for detached work
  must be **per-item** (atomic `os.rename` claim → `.processing`), not via the marker. A deterministic post-claim
  failure must **finalize** to a terminal state (`.done` `status="error"`), not stay `.processing` — otherwise it is
  phantom-`pending` forever and leaks a cap slot. Only a hard crash mid-write may orphan.
- **A detached worker outlives its spawner's invariants — re-establish them locally**: it must reset `FORGE_DEPTH=0` (a
  fresh top-level tree; inheriting depth ≥ 2 makes the depth guard skip its frontier call → false errors), and any path
  it replays must resolve the **same** way the consumer resolves it (a relative `plan_override_path` anchors at
  `forge_root`, not CWD — mirror `load_plan_override`, or the plan copy is silently skipped).
- **Count all lifecycle states for cap/dedup**: a content-addressed candidate exists as `.json`/`.processing`/`.done`;
  counting only `*.json` undercounts mid-drain and lets identical content re-capture (over-cap + double billing).
- **Single ledger emitter via `usage_command`**: `run_supervisor_check` is the sole cost/usage emitter; the shadow path
  parameterizes the label (`supervisor-shadow`) instead of re-emitting, so a run is never double-counted.
- **Parse-status flag separates `error` from `inconclusive`**: `parse_supervisor_verdict` collapses empty/unparseable →
  divergent+0.0 (a warn that looks like a real low-confidence verdict). The audit needs
  `parse_supervisor_verdict_with_status`'s `parsed` flag to classify a failed run as `error`, distinct from a genuine
  low-confidence `inconclusive`.
- **Re-root detached spend under the origin session**: snapshot `origin_run_id`/`origin_root_run_id` into the marker at
  enqueue (the Stop hook runs in the session env) and re-root via `_memory_writer_env` at drain; otherwise spend
  attributes to whoever drained the queue. Scrub `FORGE_SESSION` (don't re-inject) to avoid a self-spawning hook loop.

### Supervisor launch controls + per-caller reasoning effort (shipped 2026-06-15)

Durable invariants for `supervisor_launch_controls` (#29): launch-time cascade parity for
`forge session fork/start --supervise`, plus a per-caller `--effort` lever on every Forge `claude -p` subprocess.
Sources: `src/forge/core/effort.py`, `core/llm/types.py`, `core/reactive/session_runner.py`,
`policy/semantic/supervisor.py`, `policy/semantic/plan_check.py`, `session/models.py`,
`cli/{session_fork,session_lifecycle,policy,memory}.py`. Each invariant was adversarially verified against the shipped
code (file:line) before promotion.

- **Two effort vocabularies, two validator homes — do not merge them.** Claude `--effort` =
  `{low,medium,high,xhigh,max}` (`validate_claude_effort`, `core/effort.py`); core.llm `ReasoningEffort` =
  `{none,low,medium,high,xhigh}` (`validate_reasoning_effort`, `core/llm/types.py`). `max` is Claude-only; `none` is
  checker-only; a drift-guard test asserts they stay unequal. The Claude validator lives in the dependency-light leaf
  `core/effort.py`, **not** `core/reactive/effort.py`, because `core/reactive/__init__.py` eagerly imports the heavy
  session runner — importing it from the foundational `session/models.py` would re-create an import cycle. So
  `session/models.py` keeps an inline `_CHECKER_EFFORT_LEVELS` mirror (drift-guarded by `test_effort.py`) instead of
  importing the core.llm vocab.
- **`run_claude_session` `--effort` is fail-loud, NOT retry-latch.** It appends `--effort` after `--model`; if an older
  `claude` rejects the flag (`_is_effort_flag_rejection`) the run fails loud with `call_count == 1` — no silent
  rerun-at-default. This is deliberately the opposite of the `--output-format json` telemetry path, which
  retries-once-and-latches (`headless_json.mark_json_output_unsupported`). Rationale: effort changes model behavior, so
  a silent default-rerun would misreport what actually ran.
- **Cascade-at-launch is flag-only — the asymmetry with `policy supervisor cascade on` is intentional.**
  `fork`/`start --supervise --cascade` set `cascade=True` only; the runtime hook escalates to the frontier when no
  approved plan exists yet. `forge policy supervisor cascade on` (and `supervisor set <target> --cascade`) instead
  resolve the approved-plan snapshot eagerly (via the `--reload` machinery) and exit 1 if none resolves. Do not "fix"
  the divergence: launch time legitimately has no plan snapshot yet.
- **One Click-free checker-helper source prevents launch/policy drift.** `CHECKER_PROVIDER_CHOICES`,
  `normalize_checker_provider_arg`, `validate_checker_model` (raises `ValueError` containing "prefixed model id"), and
  `apply_checker_options` live in `policy/semantic/supervisor.py` (no Click). `cli/policy.py` and `plan_check.py` import
  them, so launch commands, persistent `policy supervisor set`, and the tier-1 checker share one
  validation/normalization source. Add new checker controls there, not at each CLI surface.
- **Effort is per-caller by design — no global knob.** Wired per consumer: `SupervisorConfig.supervisor_effort` /
  `.checker_effort`, `MemoryWriterConfig.effort`, `TeamSupervisorConfig.effort`, `run_multi_review(reasoning_effort=)`.
  `checker_effort` feeds `ModelHyperparameters` via `merge_hyperparams` **and** is part of the plan-check throttle cache
  key (a different effort must not reuse a cached verdict). All additive optional `str | None` fields — no
  `SCHEMA_VERSION` bump.
- **Memory-enable early-return must compare effort too (recurring silent-drop shape).** `_set_memory_activation` (moved
  to `cli/session_memory.py` in Slice 02) short-circuits only when enabled AND mode AND effort are all unchanged. The
  bug was short-circuiting on enabled+mode alone, silently dropping `forge session memory enable --effort high` on an
  already-enabled, same-mode session. Regression in `test_memory.py`. When adding a new persisted activation field, add
  it to the no-op comparison or it joins this class of silent drop.

### Supervisor status-line health: surface fail-open from the usage ledger (shipped 2026-06-16)

Durable invariants for `supervisor_statusline_health` (#30): make a silently fail-open supervisor visible on the
always-on status line (`SUP!N <kind>`) and in `forge telemetry activity` (`failing open: N timeout, N error`), reading
the outcome the usage ledger already records. Sources: `src/forge/core/ops/usage_summary.py`,
`src/forge/cli/status_line.py`, `src/forge/cli/statusline/{throttle,context,registry}.py`, `src/forge/cli/activity.py`.

- **Read the ledger, not the decision log — the on-model source.** The supervisor's timeout/subprocess fail-open is
  already in the usage ledger as a non-`success` `UsageEvent.status`/`failure_type` (`emit_usage_for_session_result`).
  Surfacing it needed **no** new durable field. The rejected alternative — a structured `failure_kind` on
  `PolicyDecision` — patches the *accidental* outcome record (the decision log) instead of the real one; it is deferred
  to `upstream_downstream_ledgers` along with the kinds the ledger can't yet see (parse fail-opens logged `success`,
  auth fail-opens that emit no event, and exact cached-allow reset).
- **Two read shapes off one ledger, one kind vocabulary.** `read_supervisor_health` returns the **newest-first
  contiguous fail-open streak** (resets on the first `success`) for the status-line `SUP!N`; `_aggregate_ledger` returns
  the **window total** per kind (`CommandUsage.error_kinds`) for `forge telemetry activity`. They are deliberately
  different numbers and the docs say so. Both map `failure_type` through the single `_failure_kind` helper (`timeout`
  exact, everything incl. `None`/subprocess/exit/runtime → `error`) — keep that the only source of the kind mapping or
  the two surfaces drift.
- **Generic data, supervisor-only interpretation.** `CommandUsage.error_kinds` is a generic per-kind split of the
  existing generic `errors` count, populated uniformly for every command in `_aggregate_ledger` (no
  `command == "supervisor"` branch). "Failing open" is applied **only** by the supervisor formatter
  (`format_failing_open`); a memory-writer/panel error is an error, not a fail-open. Non-supervisor rows still carry
  `error_kinds` in `--json` as an honest generic breakdown.
- **`format_failing_open` is gated on `error_kinds`, not `errors` — with an explicit caller fallback.** Real ledger rows
  co-populate both (`_failure_kind(None) == "error"`), so `errors>0 / error_kinds={}` is exclusively a hand-built /
  internal summary. The helper returns `None` there; `render_summary_line` falls back **locally** to the legacy
  `"{errors} errors"` so the count is never silently dropped (regression: `test_errors_only_falls_back_to_count`; the
  three pre-existing hand-built `TestRenderLine` tests stay green unchanged). `forge telemetry activity` needs no
  fallback — its commands table already shows the lumped count, so the Supervisor line carries pure breakdown detail.
- **Status-line health stays fail-open + posture-preserving.** The throttled read (`read_or_compute_session_health`,
  same `forge_cost_ttl` window, distinct `fhealth-` cache) degrades a read error to **posture-only** (no suffix), never
  hiding the posture — unlike `forge_cost`, whose whole value is ledger-derived. `SUP!N` attaches to any posture
  (`SUP`/`SUP(susp)`/`SUP(off)`) so suspended/off keeps prior fail-open history visible. `recent_failures==0` is
  byte-identical to today (golden-safe; `supervisor` stays out of `DEFAULT_ORDER`). Frontier-only:
  `command="supervisor"` excludes `supervisor-shadow`/`plan-check`. `forge telemetry costs reset` clears
  `fhealth-*.json` alongside `fcost-*.json` so a wiped ledger can't replay cached health.

### OpenRouter provider trace: local lifecycle evidence for aborted streams (shipped 2026-06-16; folded 2026-06-18)

Durable invariants for `openrouter_observability`: Forge can explain a timed-out OpenRouter request from local metadata
even when OpenRouter never indexes the cancelled stream. Provider trace originally shipped as a separate fourth plane;
`upstream_downstream_ledgers` folded its fields into downstream telemetry. Do not recreate a standalone provider-trace
JSONL plane: CLI/core provider-trace readers should project from `DownstreamRecord` fields.

- **Provider trace is downstream model-call evidence.** It records provider lifecycle + correlation metadata for one
  model attempt, alongside cost, tokens, and optional redacted audit evidence under `~/.forge/telemetry/downstream/`. It
  is metadata-only, owner-only, and bounded by downstream retention. `forge telemetry costs reset` now wipes downstream
  telemetry and cap state together; provider-trace state is not a separately retained exception.
- **The shared SSE seam owns lifecycle flags.** The provider metadata carrier is consumed at the converter seam, which
  records stream-start, first user-visible chunk, final usage, and client-disconnect state exactly once through the
  existing `on_complete` path. `CancelledError`/`GeneratorExit` must be caught to mark disconnect and then re-raised;
  the writer remains best-effort so diagnostics never break a successful or already-cancelling request.
- **Synthetic response ids and provider ids are separate namespaces.** Forge may mint OpenAI-compatible `chatcmpl-...`
  ids for downstream clients, but OpenRouter's `gen-...` id lives in optional `ProviderTraceMeta`. Streaming emits
  metadata as soon as the first provider id is seen so a stream killed before final usage still keeps the provider
  generation id.
- **OpenRouter grouping uses `user`, not a custom `session_id`.** Probe evidence showed OpenRouter retains the
  OpenAI-standard `user` field and ignores custom `session_id`. Injection is default-off behind the single global
  `~/.forge/config.yaml` toggle `provider_trace.inject_provider_user`, which governs both proxied and direct `core.llm`
  paths. The proxied path also requires a backend with `provider_user_grouping`; both paths send only the shared opaque,
  hashed Forge grouping id.

### Upstream/downstream telemetry ledgers (shipped 2026-06-18)

Durable invariants for the telemetry re-cut. The change log records the implementation sweep; keep these as design
constraints for future telemetry, cost, provider-trace, and activity work.

- **Plane split is by direction, not feature.** Downstream is one model attempt: session-blind, keyed by
  request/run/root ids, with metrics, nullable cost, provenance, optional redacted wire evidence, and provider lifecycle
  fields. Upstream is one operation outcome: session-tagged, run/root-keyed, with status, reason, latency, and fail-open
  classification. `forge telemetry activity` is the join/read surface; it should not grow a third durable outcome/spend
  plane.
- **Run-tree identity is the bridge.** The proxy does not know Forge sessions, so downstream records stay session-blind.
  Session views select upstream by session, collect run/root ids, then join downstream by run tree. Adding a session
  field to downstream would be a shortcut around the architecture, not a fix.
- **Cost telemetry is best-effort; cap accounting is not.** Downstream write failures warn and must not block otherwise
  successful model traffic, but spend caps reconcile from the durable cap snapshot plus downstream and legacy logs using
  the larger total. A missing/bad telemetry row must never reset cap enforcement to zero after restart.
- **`downstream_event_id` is idempotency; `request_id` is correlation.** A caller can supply `X-Request-ID`, so it is
  not a replay key. The downstream writer owns a stable per-physical-attempt id; duplicate writes of the same attempt
  merge/count once, distinct retries get distinct ids.
- **Measurement provenance must preserve the proxied/direct asymmetry.** Direct `claude -p` self-report can be
  authoritative only when unproxied. Proxied `claude -p` cost uses proxy/downstream evidence and ignores
  Anthropic-priced runtime self-report. Per-worker proxied events stay unattributed for cost so verb/run-tree exact cost
  does not double count.
- **`None` still means unavailable, never free.** Routes with tokens but no reported dollars persist nullable cost and
  render as unavailable/hidden in spend surfaces, not `$0`. Do not reintroduce local price inference on the accounting
  path.
- **`confirmed.policy.decisions` is now a compatibility fallback.** Upstream outcomes are the operation-outcome source
  for no-call/fail-open paths; the manifest log remains capped fallback material for success/cached policy counts and
  warning text, with dedupe when both sources mention the same warning.

### Per-proxy config blocks must be wired through BOTH loader hops (proxy_log_hygiene, shipped 2026-06-16)

A `proxy.yaml` block reaches the running proxy through two independent constructors:
`load_proxy_instance_config_from_dict` (dict -> `ProxyInstanceConfig`) and `_proxy_instance_to_forge_config`
(`ProxyInstanceConfig` -> `ProxyConfig`, which `config.proxy` exposes). Both in `config/loader.py`.

- **Recurring silent-drop bug.** A new block added to the dataclasses but to neither hop loads fine in unit tests of the
  schema yet is silently dropped at runtime — the live proxy sees the default. `provider_trace` shipped with exactly
  this gap (the running proxy never saw a configured block); `logging.requests` would have repeated it. When you add a
  per-proxy config block, grep both hops and pass it through both, or it never reaches `config.proxy`.
- **Regression must cover the live-read path, not just coercion.** Assert the value survives BOTH hops AND is read where
  the server consumes it (e.g. `config.proxy.provider_trace.*`). A schema-only test passes while the runtime drops it.
- **Best-effort telemetry reads tolerate a partial `config.proxy`.** Hot-path and startup reads of telemetry blocks use
  `getattr(config.proxy, "<block>", None)` / a tolerant accessor (`_request_log_config`, `_maybe_prune_*`) and degrade
  to defaults — request logging and prune must never raise into a response path. This is deliberate best-effort
  degradation, distinct from the strict durable-state coercion that rejects malformed blocks at load time.
- **One pruner for all JSONL planes.** `core/state/retention.py::prune_jsonl_shards` (age-then-size, `0` = disable a
  bound) backs the audit, provider-trace, and request planes. New JSONL telemetry planes should delegate to it, not
  re-copy the delete-by-age/oldest-first loop.

### No caller content in proxy logs; redactor excludes caller free-text (proxy_log_hygiene review, 2026-06-16)

The "redacted = sanitized structure, never plaintext" contract binds two surfaces: the redacted JSONL diagnostics/audit
files AND the proxy module logger. Both leaked.

- **The shared `_redact_body_for_log` must never verbatim-copy a caller free-text key.** `stop_sequences` sat in
  `_SAFE_KEYS` (verbatim copy) and leaked arbitrary caller strings onto BOTH the audit and request-diagnostics planes.
  Safe keys are scalars/enums/ids/token-counts only; any field a caller fills with free text (stop_sequences, and watch
  future additions) must go through a structural branch (`{"redacted": True, "count": N}`), never `_SAFE_KEYS`.
- **The SSE converter logger leaked content at DEBUG in ~8 spots.** Per-delta text/tool-args, whole-chunk/`tc_delta`
  WARNING dumps, and the buffered-tool close-event `json.dumps(event_data)` (carried `partial_json` = `Read`'s
  `file_path`). The opt-in `stream_chunks` dump is the ONLY sanctioned raw-content path; every other stream log must be
  metadata (lengths, key-names, indices, token counts, enums, tool names/ids).
- **Hunt log leaks by data provenance, not variable name.** A name-based grep (`{chunk}`, `{args_delta}`) missed
  `json.dumps(event_data)` because the caller content was one indirection away (built event dict -> `partial_json`).
  When auditing a logging surface, trace whether each interpolated value *derives* from caller input, and grep
  `logger.*json.dumps` plus `%s`-style calls, not just known leaky names.

### A toggle that governs both proxied and direct paths belongs in global runtime config (openrouter_user_direct_callers, shipped 2026-06-20)

`provider_trace.inject_provider_user` started per-proxy (`proxy.yaml`) but had to govern both the proxy AND Forge's
direct `core.llm` callers (plan-check, curation). It moved to the global `~/.forge/config.yaml`
(`RuntimeProviderTraceConfig`, read via `get_runtime_config().provider_trace`). Keep these rules when a config value
spans both planes:

- **Ownership test: who reads it.** A value only the proxy reads stays per-proxy (the "BOTH loader hops" note still
  governs those). A value the proxy AND a non-proxy code path both read belongs in global runtime config. The proxy
  legitimately reads `get_runtime_config()` for non-routing fields — precedent: `auth_ignore_env`. Splitting one
  conceptual switch into two per-scope homes to avoid this is the wrong trade (product experience drives architecture).
  Retention keys (`retention_days`/`max_total_mb`), proxy-only, correctly stayed in `proxy.yaml`.
- **The sidecar must mount any host config the in-container proxy reads.** Moving the gate to `config.yaml` silently
  broke in-container proxied forks until `_ensure_audit_plumbing_mounts` (`sidecar/container.py`) bind-mounted
  `~/.forge/config.yaml` read-only. Mount only when the host file exists (a Docker bind source must pre-exist; absent ⇒
  toggle defaults off ⇒ the omitted mount is the correct no-op).
- **Write surfaces fail-closed even though the disk loader is fail-open.** `forge config edit` validates by constructing
  `RuntimeConfig`, which runs the loader's forward-compat coercion that *drops* unknown nested subkeys — so a typo like
  `inject_provider_usre: true` would persist with the toggle silently off. The edit path needs its own unknown-subkey
  check (reuses `_nested_sections()`), restoring parity with `set`. Same dataclass `__post_init__`, but entry paths
  differ: load degrades, set/edit reject. Regression: `test_edit_rejects_unknown_provider_trace_subkey`.
- **Cross-plane grouping ids must come from one function.** Direct (`resolve_direct_provider_user`) and proxied
  (`reactive/env.py`) injection both derive the id via `derive_provider_session_id`, so a run's direct + proxied
  OpenRouter calls group identically account-side. The direct resolver mirrors env.py's root fallback
  (`FORGE_ROOT_RUN_ID` else `FORGE_RUN_ID`). Lock this with an equality test, not two independent format assertions
  (`test_correlation.py::test_matches_proxied_derivation`). User-config relocation is warn-and-degrade (system
  boundary), not reject.
