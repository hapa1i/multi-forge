# Change Log

Completed-work record for Forge implementation sessions.

## Maintenance

- Updated by the memory writer with `strategy=changelog`, and by humans when closing a phase.
- Add compact entries for completed work only. Pending tasks belong in card checklists.
- Follow `docs/developer/board_contract.md` "Change Log Policy": each entry needs Goal, Key changes, and Verification.
- Keep entries short. Do not list every file unless the file list is the point of the work.
- Use newest-first order so active work stays near the top.
- When this file approaches the documentation size limits, compact the oldest entries at the bottom into a dated summary
  that preserves decisions, verification, and deferred items. Archive detailed old entries only if the summary is still
  too large.
- Check size before long sessions or when the file feels slow to scan:

```bash
wc -l docs/board/change_log.md
./scripts/count-tokens.py --model <agent-model> docs/board/change_log.md
```

## Entries

> Format: `## YYYY-MM-DD`, then `### Phase X.Y: Short Title`, with `**Goal**:`, `**Key changes**:` as bullets, and
> `**Verification**:`. Use newest-first order. See `docs/developer/board_contract.md` "Change Log Policy" for the full
> spec.

## 2026-07-02

### session_op_layer_extraction Slice 5: Session shim retirement

**Goal**: Remove the `forge.cli.session` compatibility shim that kept tests patching parent-module re-exports after the
Claude session path was split into focused CLI/core modules.

**Key changes**:

- Repointed parent-module test patches to the real seams by sub-slice: low-volume helpers, resume-mode local imports,
  `SessionManager`, and the Claude launcher seam in `forge.core.ops.claude_session`.
- Deleted the `_sess()` / `_session_cli()` lazy module seams and replaced the `session.py` wildcard re-export tail with
  side-effect imports that preserve Click command registration.
- Repointed direct test imports for submodule-owned commands/helpers while leaving `session.py`-defined helper tests on
  the parent module.

**Verification**: CLI/regression suite 2681 passed; Docker lifecycle integration 21 passed; stale shim greps clean
except for helpers still defined in `session.py`; `make pre-commit` clean.

### session_op_layer_extraction Slice 4b: Fork supervisor wiring

**Goal**: Finish the post-fork cleanup by collapsing fork supervisor persistence onto the core wiring primitive and
settling the remaining sidecar testability question.

**Key changes**:

- Replaced `session_fork.py`'s hand-rolled `SupervisorConfig` / lane persistence block with `SupervisorWiring` +
  `_apply_supervisor_wiring`, preserving the existing `_preflight_routing` guards and CLI-owned validation.
- Moved sidecar `is_sandboxed=True` confirmation to after mount/secret/env prep, immediately before the runner, so
  launcher validation failures such as a bad `--mount` do not strand a stale sandbox flag.
- Added a fork-sidecar bad-mount regression that asserts clean launch failure, no sidecar runner invocation, and
  `confirmed.is_sandboxed == false`.

**Verification**: focused supervisor/session/regression suite 293 passed; Docker supervisor integration 10 passed;
layering/UI-free greps empty; `make pre-commit` clean.

### session_op_layer_extraction Slice 1: Claude session preflight split

**Goal**: Start the staged Claude session CLI/core split with the lowest-risk helpers and a manifest characterization
safety net.

**Key changes**:

- Added a JSON-string manifest characterization test for Claude `start --no-launch` and fresh resume, pinning dataclass
  field order and normalized volatile values.
- Added `forge.core.ops.claude_session.resolve_and_validate_system_prompt` and rewired launch prompt resolution through
  it while keeping the CLI's `Path -> str` launcher boundary explicit. Follow-up cleanup kept `--no-launch` prompt
  validation CLI-owned, avoiding a dead op-level `ForgeOpError` path.
- Moved the CLI-free model-pin support cluster into `forge.session.model_pin`; `cli/session_model_pin.py` now only keeps
  UI-tangled persistence/warning behavior.
- Accepted `session_op_layer_extraction` into `doing/` with Slice 1 verification recorded. Parent patch count remains
  270 across 13 files; `session_lifecycle.py` is 2,496 lines after the slice.

**Verification**: characterization test 2 passed; focused units 241 passed; Docker lifecycle integration 21 passed;
layering/UI-free greps empty; `make pre-commit` clean.

### Board closeout: rewind_resume_strategy

**Goal**: Close the shipped rewind resume strategy card so `doing/` reflects only active work.

**Key changes**:

- `rewind_resume_strategy` moved `doing/ -> done/` after confirming all implementation slices were already ticked and
  the docs named in the checklist reflect the shipped `--strategy rewind --drop-last N` behavior.
- The card/checklist stale "Slice 4 next" focus was corrected to closeout state.

**Verification**: `uv run pytest tests/src/session/test_rewind_strategy.py tests/src/cli/test_session_rewind_cli.py -q`
(26 passed); `make pre-commit` clean.

### Board closeout: Sonnet 5 done; accidental_complexity A/B merged + paused

**Goal**: Reconcile the board after PR #65 merged -- close the shipped Sonnet 5 card and pause the accidental-complexity
cleanup with Batch C still open.

**Key changes**:

- `sonnet_5_default` moved `doing/ -> done/`: Sonnet 5 catalog/template support + the sonnet/opus default-tier flip
  shipped via PR #64 (`75cd28b5`). Final closeout item ticked.
- `accidental_complexity_cleanup` moved `doing/ -> paused/`: Batches A + B merged via PR #65 (`584aa2a1`), including two
  pre-merge review follow-ups (a `FORGE_DEBUG` fail-open regression test and a `loader.py` black-format fix). Paused
  with Batch C (#17-#20) and the two surfaced defects (Defect B auth-retry provider-trace gap, Gap A policy fail-open
  prose-only check) still open.

**Verification**: Board/docs-only commit. PR #65 landed green (8-dimension adversarial review + independent
`make pre-commit` and full touched-suite run clean); no code change here.

### accidental_complexity_cleanup Batch B follow-up: proxy/template config load boundaries

**Goal**: Close the Batch B review findings around newly-invalid proxy providers and malformed proxy/template YAML
surfacing as raw tracebacks in user-facing CLI paths.

**Key changes**:

- `ProxyInstanceConfig` loading now normalizes malformed proxy-file shape to `ValueError` at the loader boundary, with
  explicit mapping checks for `tiers`, `tier_overrides`, and each tier override leaf. Empty/null override leaves remain
  "no override"; falsy non-mappings (`[]`, `false`, `""`, `0`) now fail instead of being ignored.
- Template loading now rejects non-mapping nested dataclass fields before schema `__post_init__` can raise raw
  `AttributeError`/`TypeError`; proxy orchestration wraps malformed templates as `ProxyStartError`.
- CLI boundaries for `proxy start`, `proxy create`, and session model-pin proxy config reads now report clean contextual
  errors for legacy `provider: gemini/openai` proxy files and malformed YAML sections.

**Verification**: 328 targeted tests green across proxy commands, session model pins, config loader/schema, and proxy
orchestrator; ruff clean for touched loader/tests. Manual repros now fail cleanly for legacy provider, `tiers: []`,
malformed template `tier_overrides: []`, and falsy override leaf `tier_overrides.haiku: []`.

## 2026-07-01

### accidental_complexity_cleanup Batch B: template move, legacy-search delete, secrets/provider narrowing

**Goal**: Execute Batch B (#13-#16) of the 2026-07-01 simplicity-audit card -- remove the remaining medium-effort
accidental complexity behind clean seams (same branch).

**Key changes**:

- **#13**: The 4 debate/consensus evaluation templates existed twice (constants in `cli/workflow.py` + copies under
  `src/skills/*/resources/`, kept in sync by drift-guard tests). `git mv`'d the copies into `forge.review.resources`
  (byte-identical); resolvers load them via the existing `_load_workflow_resource`. Single source now, so both drift
  guards are deleted; placeholder/vocabulary invariants + direct `_resolve_*_prompt` tests move to `test_run_resources`.
  Net -336 LOC in `workflow.py`.
- **#14 (full delete)**: Removed the legacy in-memory `search()` -- a second BM25 scorer with no production callers,
  used only as a test oracle. The 12 `TestSearch` cases now run through a `_search_docs` adapter over the real
  `search_from_index`; the score-equivalence oracle is retired. `SearchDocument.tokens` kept (rebuild-index reads it).
- **#15**: Deleted `ConfigSecretsProvider` + `ProviderConfig.auth_url` + the `GEMINI_AUTH_URL`/`OPENAI_AUTH_URL` env
  mappings -- write-only plumbing never wired into the production Env+File credential chain. Chain tests moved onto the
  real Env+File chain; the h6 no-coercion guard now covers the surviving `FORGE_HOME` mapping.
- **#16**: Narrowed `ProxyInstanceConfig` providers to `{litellm, openrouter}`. `gemini`/`openai` previously validated
  then silently routed to LiteLLM; since validation runs on every read, they now fail fast with a message naming the
  supported providers + recreate path (durable-state clean break). Shipped templates write `provider=litellm`, so create
  flows are unaffected; gemini/openai model-name detection is untouched.

**Verification**: targeted unit suites green per item (search 153; config/auth/proxy/backend 1143; run_resources +
skill_content 84); #15/#16 integration-verified (auth credential resolution 4 passed, proxy commands 27 passed);
per-file `make pre-commit` clean. A 4-way adversarial review over the committed diff returned one low finding (a stale
provider comment), fixed. Batch C + surfaced defects stay open (card in `doing/`).

### accidental_complexity_cleanup Batch A: dead-code removal + drift fixes + one CLI bug

**Goal**: Execute Batch A of the 2026-07-01 simplicity-audit card -- remove verified accidental complexity and fix the
one bug it surfaced (branch `cleanup/accidental-complexity-batch-a`).

**Key changes**:

- Deleted zero-caller dead code: `promotion.py`, `resolve_template_paths`, `load_yaml_strict`,
  `resolve_subprocess_proxy_url`, `_dedupe_specs` (verified no-op: sole caller feeds one unique-path scan), and the
  never-run generic `_coerce_env_value` branch.
- De-duplicated telemetry: `provider_trace_logger` imports `RequestMode`/`LocalUsageStatus` from owner `downstream.py`;
  hoisted the byte-identical `_worker_reason_code` + upstream-emission block from the Claude/Codex invokers into the
  shared `_lifecycle` base (`operation=None` suppression preserved). Passport drops the unread `inherit_on_fork` field
  but keeps the key in `_KNOWN_UPDATE_KEYS` (accept-and-ignore).
- **Bug fix (#1)**: `backend delete --port` drove `stop_cmd.callback()` (double "Stopped" + a `sys.exit` bypassing
  delete's error path); both commands now share a silent `_stop_instance`.
- **Behavior (#9)**: `ListSessionsItem.is_active` wired to the runtime `ActiveSessionStore` (was hardcoded `False`).
- Docs/UX: reworded the `--no-proxy` guard to name `--proxy`; removed two stale CLI-alias doc lines; fixed the
  `CredentialManager` "proactive refresh" docstring.

**Verification**: full unit suite `7222 passed`; ruff + mypy + `make pre-commit` clean. New tests: `is_active` liveness,
legacy-passport accept-and-ignore, backend delete-double-stop regression. Batches B/C + surfaced defects stay open (card
in `doing/`).

### Sonnet 5 support + default-tier flip

**Goal**: Teach Forge about Claude Sonnet 5 across catalog/templates and promote the newest models to the default tiers.

**Key changes**:

- Catalog: added `claude-sonnet-5` (native 1M, adaptive-only, `token_estimate_multiplier: 1.35`) + aliases
  (`anthropic/claude-sonnet-5`, `sonnet-5`, `claude-sonnet`). Flipped all four `defaults` — sonnet -> `claude-sonnet-5`,
  opus -> `claude-opus-4-8` (anthropic + openrouter); `sonnet`/`opus`/`claude-opus` friendly aliases follow. Cleared
  Opus 4.8's stale `opt-in` tag and the now-wrong "defaults stay on 4.6" comments.
- Templates: the four anthropic-family templates default sonnet -> Sonnet 5, opus -> Opus 4.8; Fable 5, Opus 4.6, and
  Sonnet 4.6 moved into `model_alternatives` (still pinnable via `--model`).
- Passthrough: `_proxy_supports_model_pin` now short-circuits for `wire_shape == "anthropic_passthrough"`, so any Claude
  `--model` pin is honored (passthrough forwards unchanged). Also fixes a latent inability to pin Opus 4.8/4.6 on
  passthrough. Covered by `tests/regression/test_bug_passthrough_model_pin.py`.
- Estimator: `PROXY_CONTEXT_MODEL_DEFAULTS` -> `claude-opus-4-8[1m]` / `claude-sonnet-5[1m]`.
- Intelligence-score rerank so Sonnet 5 (98) sits between Opus 4.6 and Opus 4.8: Opus 4.6 98 -> 97, Opus 4.7 99 -> 98
  (was tied with 4.8 at 99), Opus 4.8 99 and Fable 5 100 unchanged. Sonnet 5 = 98, peer of Opus 4.7.
- Review quorum's `claude-opus` worker now resolves to Opus 4.8 automatically (it tracks `get_default_model`, no
  review-code change).
- Docs: proxy / model_selection / session / skills / workflow / cli_reference / README + QA proxy checklist synced.

**Verification**: `make test-unit` (7231 passed); targeted catalog/config/session/proxy suites + new passthrough
regression (470 passed); scoped Docker integration (`session start --model`, bare `claude start` default model — 2
passed); `make pre-commit` clean.

### consumer_lanes epic: closeout (team-supervisor codex dispatch carved out)

**Goal**: Close the `consumer_lanes` epic now that its lane contract is shipped and folded into normative design docs.
The one remaining follow-on -- team-supervisor codex dispatch -- is a different abstraction, so it is re-filed as a
standalone card rather than held open under the epic.

**Key changes**:

- **Decision**: consumer_lanes is complete at the lane-contract level for team-supervisor (lane placement, `claude-max`
  billing, freeze-on-real-dispatch, observability). A codex team-supervisor lane is deferred because it needs
  runtime-neutral plan/context delivery -- a team-orchestration / context-design concern, not the lane substrate.
- **Verified basis** (`src/forge/policy/team/handlers.py`): `TEAM_SUPERVISOR_CONSUMER.allowed_lanes` has no codex lane
  (`:38-43`), and supervision context reaches the handler only via `run_claude_session(resume_id=...)` =
  `claude -p --resume` (`:267-269`). `codex exec` has no `--resume`, so a codex arm would be plan-blind -- unlike the
  blind / in-band T4/T6b/T6c arms.
- New follow-on card `docs/board/proposed/team_supervisor_plan_context/` (goal, design decisions owed, constraints).
- Epic `doing/epic_consumer_lanes/ -> done/`; card + checklist marked closed; the stale checklist closeout note (still
  describing T6c as active in `doing/`) corrected. 22 member back-links repointed to `done/epic_consumer_lanes` (line-3
  `**Epic**:` headers only; no narrative touched).

**Verification**: Docs-only closeout, no code change. Code claims re-verified against `handlers.py` before writing;
back-link repoint confirmed (0 remaining `doing/epic_consumer_lanes` refs in `done/`).

### consumer_lanes T6c: Memory-writer codex dispatch arm

**Goal**: Bind the memory writer to its resolved lane's runtime so a codex binding dispatches a real `codex exec` arm
(`review-only` on `read-only`, `augment` on `workspace-write`) instead of falling through to `claude -p` -- the epic's
first consumer whose codex lane can write the repo.

**Key changes**:

- `run_memory_writer` resolves the runtime from the bound `LaneRecord` (T6b's `LaneRecord -> Lane -> resolve_lane`
  guard) **before** the claude-availability check, then branches into `_dispatch_codex_memory_writer` ahead of the
  claude `on_dispatch` (claude path byte-identical). A codex-bound writer runs when `claude` is absent (Finding 2).
- Per-mode sandbox; **no Claude permission scan** (D4). A live Phase 0 probe found a codex `workspace-write` *denial*
  exits 0 with `is_error=False` (rides `turn.completed`), so `runtime_is_error` does not catch it -- immaterial, because
  in-project doc writes (`cwd=forge_root`) auto-approve and never hit the rejection path. Real provider/turn failures
  still fold via `runtime_is_error`.
- Degrade is **best-effort async** (detached worker, stdout -> DEVNULL): log + outcome + `return False`, never raises.
  Single upstream row -- the invoker's `_emit_codex` owns the outcome for spawned runs (failure-biased, so a success
  writes none under default volume, claude parity); the arm records manually only on a no-spawn preflight failure
  (Finding 1, no double-count).
- Shared codex-smoke fixtures extracted to `tests/integration/session/conftest.py`. Design docs synced (design_appendix
  §G, cli_reference, design.md, end-user memory.md).

**Verification**: 189 unit green (`test_memory_writer.py` + lane siblings), CLI bridge covered
(`test_run_cmd_forwards_codex_lane_record`, `test_set_memory_writer_via_codex_runtime`); live real-codex E2E 2 passed
(64s) -- augment actually edited a doc under `workspace-write`, one `runtime=codex`/`subscription_quota` event, no
upstream row on success; `make pre-commit` clean. Merged in PR #62 (`1064b8c8`).

## 2026-06-30

### consumer_lanes T7: Subscription-exhaustion fail-open (sticky degrade)

**Goal**: When the semantic supervisor's bound codex subscription lane exhausts mid-session, degrade once to the default
`claude -p` lane -- sticky for the session, fail-open, one hop -- so real plan-enforcement resumes instead of a silent
per-check fail-open for the rest of the session.

**Key changes**:

- **Detection (Phase 1)**: `is_subscription_exhausted` classifier in `codex_stream.py` (conservative source-literal
  allowlist on the codex JSONL `message` -- no structured status survives the `codex exec` boundary) + a
  `failure_type="subscription_exhausted"` rung in `run_supervisor_check`, gated on the codex runtime +
  `runtime_is_error` and read off `result.error or result.stderr` (a realistic quota failure exits non-zero, so the
  reason rides stderr).
- **Sticky degrade (Phase 2)**: a degrade overlay in `confirmed.policy.policy_states["forge.supervisor_lane_degrade"]`
  (new `supervisor_lane_degrade.py`), separate from the immutable `consumer_lanes` binding. The policy hook writes it
  under the existing freeze lock behind the same stale-write guard; the read side injects `lane_record=None` so later
  checks run on claude while the frozen codex binding stays observable. Reset follows the binding, not the command name:
  `supervisor remove`/re-pin clear it, `lane clear` does not; cross-resume clears on SessionStart `startup`/`resume`
  (refilled-quota retry) but preserves on `compact`/`clear` (mid-sitting, would just re-exhaust).
- **Observability + surface (Phase 3)**: exactly one `policy.lane_degraded` upstream outcome per degrade
  (`command=supervisor`, `reason_code=subscription_exhausted`; captured under the lock, emitted after it), read by
  `forge telemetry activity` (not a `UsageEvent`). `supervisor status` and `lane show` gain a `degraded` field/marker.
  Docs: design_workflows §1.2 (the one sanctioned fallback), design_appendix §G, cli_reference, end-user policy.md.

**Verification**: Focused suites green (`test_supervisor_lane_degrade`, `test_policy` hooks, `test_session_start`,
`test_session_lane`, `test_policy_supervisor`, `test_supervisor`, `test_codex_stream`); `tests/src/cli tests/src/policy`
-> 2660 passed; scoped `pre-commit` clean (mypy + pyright). Integration: `test_real_claude_hooks.py` +
`test_supervisor_e2e.py` -> 12 passed (real Claude in Docker), validating the SessionStart + policy-check hook wiring.
The degrade *trigger* stays synthesized (no live subscription to spend on demand).

### consumer_lanes T6b: Aux-consumer codex dispatch (shadow-curation codex arm)

**Goal**: Give an aux consumer a real `codex exec` dispatch arm -- the one thing T6a skipped (it shipped claude-max
billing only, no dispatch change). `forge session lane set --consumer shadow_curation --runtime codex` now routes to
Codex, not just a billing relabel. Narrowed at promotion to shadow-curation only.

**Key changes**:

- **Scope correction (D1)**: a code sweep found the three aux consumers are NOT a uniform "mirror T4" -- only
  shadow-curation is clean (blind, read-only, stdout-is-output). memory-writer (workspace-write file-editing) deferred
  to T6c; team-supervisor (plan-blind without snapshot machinery) deferred (D2).
- **Codex arm** (`session/shadow_curation.py`): `SHADOW_CURATION_CONSUMER` gains `Lane(codex, chatgpt, gpt-5-codex)`;
  the CLI threads the bound `LaneRecord`, `run_shadow_curation` validates it (`LaneRecord -> Lane -> resolve_lane`, the
  supervisor's guard) and branches on runtime into `_dispatch_codex_shadow_curation` (read-only `codex exec`, direct to
  OpenAI). The `claude_code` path is byte-identical.
- **Three contract divergences from the supervisor arm** (the headline): degrade is **fail-loud not fail-open**
  (user-invoked -> `CurationResult(success=False)` + a CLI-visible hint via new `CurationResult.error` (D5), never a
  silent claude fallback); the upstream row pins `operation="memory.shadow_curation"` not `None` (curation has no engine
  `policy.evaluate` row, so the invoker's auto row IS its only one); freeze fires **past** the preflight skip-gate, with
  `runtime_is_error` folded so an exit-0-but-failed turn fails loud.
- Docs synced in-PR: `design_appendix.md` §G (T6b paragraph), `cli_reference.md` lane-set bullet, `design.md` freeze
  wording broadened to "the actual runtime dispatch".

**Verification**: focused suites green (`test_shadow_curation.py` 35; + memory/session_lane/consumer_lane_freeze/
lanes/billing = 157); wider sweep (policy/semantic, core/invoker, core/usage, session, codex_preflight_cache) 1318; full
`tests/src/cli` 2145; `make pre-commit` clean. Real `codex exec` E2E (`test_shadow_curation_codex_smoke.py`) green
against the host ChatGPT login -- asserts success, report persisted from codex stdout, freeze fired, and exactly one
`runtime=codex`/`billing_mode=subscription_quota`/`route=codex_exec` usage event. Shipped via PR #60 (`ca20efcd`).

**Closeout (2026-06-30)**: card moved `doing/ -> done/aux_consumer_codex_dispatch/`; epic roster marked T6b done.
Durable lesson promoted to `impl_notes.md` ("Adding a codex dispatch arm to an aux consumer"). T6c (memory-writer codex
dispatch) and the team-supervisor plan-context arm remain deferred follow-ons; T7 stays in `proposed/`.

### consumer_lanes T6a: Aux-consumer lane placement (claude-max billing for the three non-supervisor consumers)

**Goal**: Pin the memory writer, shadow curation, and team supervisor to `claude-max` so their keyless+direct runs bill
`subscription_quota` like the supervisor -- closing T0's deferred operator half. No dispatch change (claude-max shares
the `claude_code` runtime; codex-exec stays T6b).

**Key changes**:

- **Phase 1 (CLI)**: `forge session lane set/show/clear --consumer <id>` -- the canonical surface for all four consumers
  (session-owned `intent.consumer_lanes`); `forge policy supervisor set` stays the supervisor convenience (same slot).
- **Phase 2 (freeze)**: best-effort `persist_lane_freeze` (`cli/consumer_lane_freeze.py`) fired from an `on_dispatch`
  hook at each consumer's real `run_claude_session` call, threading the dispatched lane with the supervisor's under-lock
  `read_bound_lane(m) == dispatched_lane` guard (memory-writer, shadow-curation, both team hooks).
- **Corrections**: billing honesty lands at Phase 1, not the freeze (`read_bound_backend_id` is
  confirmed-first-else-intent); the freeze is immutability/observability parity. A review then hardened the first cut:
  freeze only on a real dispatch (skips no longer freeze), thread the lane + equality guard so `confirmed` can't diverge
  from the billed backend (retracts "freezing before dispatch closes the window"), and use `HOOK_LOCK_TIMEOUT_S` in
  hooks.
- Docs: design §3.5/§3.6.2, appendix §G, cli_reference, end-user policy.md.
- **Closeout (2026-06-30)**: card moved `doing/ -> done/aux_consumer_lane_placement/`, epic roster marked T6a done. An
  investigation confirmed the supervisor's eager freeze-at-first-check (vs aux freeze-on-dispatch) is correct for its
  *registered* lifecycle, not a bug; the intentional asymmetry is now documented (`policy.py` /
  `consumer_lane_freeze.py` comments, design §3.5, appendix §G) and promoted to `impl_notes.md`.

**Verification**: New unit tests (`test_consumer_lane_freeze.py`, memory-writer + team-hook wiring incl.
no-freeze-on-skip and the equality guard); billing covered transitively by `test_billing.py` +
`test_read_bound_backend_id_for_all_consumers`. 7135 unit + handoff integration (10, Docker) green; pre-commit clean.

## 2026-06-29

### consumer_lanes T0: Claude Max subscription billing mode (Phase 1+2)

**Goal**: Emit `billing_mode="subscription_quota"` for a keyless, direct `claude -p` run whose bound consumer-lane
backend is `claude-max`, instead of the conservative `unknown` -- honestly, with no local cost inference.

**Key changes**:

- New `claude-max` `ModelSource` (`backend/sources.py`): `runtime_native`, `provider="anthropic"`, no credential,
  `billing_posture="subscription_quota"`, `reachable_via=("claude_code",)` -- the claude_code analog of `chatgpt`.
- `resolve_billing_mode(*, direct, has_api_key, backend_id)` (`core/usage/billing.py`) delegates to `infer_billing_mode`
  and upgrades only a keyless direct run on a `subscription_quota`-posture backend; a resolvable key still wins (`api`),
  proxied stays `unknown`, a drifted backend fails open to `unknown`. First consumer of `billing_posture`.
- `emit_usage_for_session_result` gained `backend_id`; all four consumers thread their bound backend via new
  `read_bound_backend_id(state, consumer)` (None for an absent OR drifted binding). New `Consumer` defs for
  memory-writer/shadow-curation/team-supervisor + 6 manifest slots on `ConsumerLane{Intent,Confirmed}`.
- Declaration UX (supervisor-only this card): `lane_record_for(consumer, *, runtime, backend)` +
  `forge policy supervisor set --backend claude-max` (backend selection -- `--runtime` can't pick `claude-max`, which
  shares the `claude_code` runtime). The other three consumers' operator CLI is a follow-on.
- `forge model backend` runtime-native probe hint now derives from `reachable_via` (one helper, both call sites), so
  `claude-max` points at the Claude login, not codex preflight.
- Docs: design §3.14, appendix §A.13 + source catalog, `cli_reference`, end-user `policy.md`.

**Decisions**: billing wired for all four consumers; label gated on the bound backend's `billing_posture` (no magic
string); declaration UX supervisor-only; card Q2 resolved (source ships in T0). `subscription_headless_credit` stays an
unused reserved `BillingMode` literal (removal candidate, deferred).

**Verification**: `make pre-commit` clean (ruff/black/isort/mypy/pyright/mdformat); ~700 unit tests across
usage/billing/emit, consumer_lanes, backend sources, supervisor, team handlers, memory-writer, shadow-curation;
memory-writer handoff integration green in Docker (10 passed). Real-claude supervisor e2e deferred to release
validation.

## 2026-06-28

### consumer_lanes T1b: persist + freeze the supervisor lane (consumer-lane binding)

**Goal**: Promote the narrow `SupervisorConfig.supervisor_runtime` field (T4) into a uniform, persisted consumer-lane
binding -- `intent.consumer_lanes` (requested) + `confirmed.consumer_lanes` (frozen) -- so the supervisor's lane is a
durable, frozen-at-first-dispatch fact, not a transient runtime string.

**Key changes**:

- **Schema (D1)**: `LaneRecord` (inert manifest DTO, no catalog validation) + `ConsumerLane{Intent,Confirmed,Binding}`
  named-field dataclasses on `SessionIntent`/`SessionConfirmed`. `session.models` stays catalog-free; a field-parity
  test guards `LaneRecord` against `core.lanes.Lane`.
- **Bridge + freeze (D2)**: new `session/consumer_lanes.py` -- `read_bound_lane` (confirmed-first, else intent),
  `ensure_consumer_lane_binding` (write-once freeze of the *dispatched* lane). The policy-check hook resolves the lane
  and **injects** it into `run_supervisor_check` (the engine, not the hook, calls it); the freeze records the lane that
  actually ran, not a re-read of the under-lock manifest (review P2a).
- **Clean break (D3)**: deleted `SupervisorConfig.supervisor_runtime`, `_SUPERVISOR_RUNTIMES`,
  `_supervisor_lane_override`. Read-time strip-and-warn for legacy manifests; shadow records bump
  `SHADOW_SCHEMA_VERSION` 2->3 and freeze a `LaneRecord`.
- **Setters + reject (D2)**: `--supervisor-runtime` on `session start`/`fork`, `policy supervisor set --runtime`;
  runtime expands to a full `LaneRecord` from the consumer's declared lanes (no separate allow-list). `set --runtime`
  hard-rejects once the lane is frozen (stateful, reads confirmed); `consumer_lanes.*` is rejected as a raw `set`
  override (review P2b). Status reads the frozen binding, revalidates, shows "not executable" on drift without
  rewriting. start/fork share `apply_supervisor_and_lane` (keeps `session_lifecycle.py` under the 2,500-line guard).
- **Docs**: design.md §3.5/§3.6.2, design_appendix §G, cli_reference.md synced to the shipped binding.
- **Hardening (review)**: `set --runtime` re-checks the frozen binding **under the lock** (the pre-lock check is now a
  fast path) -- a hook freezing `confirmed.consumer_lanes` mid-command can no longer persist a recorded-but-ignored
  intent lane (`store.update` skips the write when the mutate raises). `supervisor remove` (CLI **and** `%policy` direct
  path) now orphan-clears the lane binding (intent + confirmed) via `clear_consumer_lane`, so
  `set --runtime codex; remove; set planner` no longer resurrects codex through `read_bound_lane`.

**Verification**: full unit suite 7079 passed (incl. TOCTOU-abort + set/remove/set repro); supervisor E2E
(`test_supervise_cli_cascade_wiring`, `test_session_set_wires_supervisor_config`) pass; mypy + `make pre-commit` clean;
`rg supervisor_runtime src/` clean except the strip helper. Codex-lane real-API E2E deferred (needs ChatGPT login);
covered at unit level. Branch `consumer_lane_binding`, 5 slices + review hardening.

## 2026-06-27

### consumer_lanes T5: lane observability (see/verify the chosen lane + billing)

**Goal**: Make each consumer's chosen lane and how it was billed visible and measurable, and remove the codex
supervisor's double upstream-outcome row T4 carried forward. Observability only -- no durable consumer-lane binding
(T1b), no billing-inference fix (T0).

**Key changes**:

- **Configurable upstream operation (WS1)**: additive `Attribution.operation` (default `"workflow.worker"`); the shared
  invoker emit seam wraps **only** `record_upstream_operation` in `if attribution.operation is None: return`, leaving
  the early-return guard and `emit_codex_usage`/`emit_worker_usage` untouched. The codex supervisor passes
  `operation=None`, so its sole upstream row is the engine's `policy.evaluate` -- parity with the claude arm, resolving
  T4's double-count. Every other consumer defaults to `workflow.worker`.
- **Close the M3 no-emission gaps (WS2)**: WorkflowPolicy `CheckerStage`/`ReviewerStage` and the team event tagger
  switched `.ask()` -> `.complete()` to capture `CompletionResponse.usage` (system prompt preserved via an explicit
  `Message(role="system", ...)`), then emit session-tagged `emit_direct_llm_usage`
  (`policy-checker`/`policy-reviewer`/`team-tagger`) on success, parse-failure (`status="error"`), and exception.
  Checker/reviewer tag `session=context.session_name`; the team tagger resolves `FORGE_SESSION` best-effort, else
  ambient.
- **Two honest read surfaces (WS3)**: `forge telemetry activity` gains per-call `runtime`/`billing_mode` on
  `ModelCallActivity` (per-command rollup: uniform value, `mixed` on disagreement, `-`/`unknown` for downstream-only),
  rendered as a column and in `--json`. `forge policy supervisor status` gains `resolve_supervisor_lane()` and shows the
  full declared `(runtime, backend, model)` lane (+ `--json`), failing open to `null`/`(unresolved)` on lane drift. The
  usage ledger carries no backend id, so per-call telemetry shows `runtime`+`billing_mode`; the full lane shows on
  supervisor status (per-call backend attribution deferred to T1b).
- **Hardening (adversarial diff review)**: fixed a reviewer double-emit -- verdict mapping moved outside the emit `try`
  (its own fail-open-to-warn guard), and a malformed `confidence` coerces to `0.0` (system-boundary degrade) -- so one
  reviewer call can no longer surface as `calls=2/errors=1` in the metric WS2 just added.

**Verification**: full unit suite 7019 passed; hardening round green across 873 policy/invoker/ops tests; mypy +
`make pre-commit` clean. `test_supervisor_e2e.py` (Docker/real-Claude, release-tier) deferred -- the changes are
additive telemetry with no dispatch/verdict change. Shipped via PR #56 (`4fc705b4`); design docs (`design_appendix.md`
§G, `cli_reference.md`) synced in the same PR.

**Epic**: first wave (T1a/T2/T3/T4/T5) complete; epic stays in `doing/` coordinating T1b (durable binding, next cursor),
T6, and T7. Durable lessons deferred to epic closeout.

### consumer_lanes T4: codex-exec supervisor lane (first non-Claude consumer lane)

**Goal**: Place the semantic supervisor on a real non-Claude runtime -- headless `codex exec` riding the ChatGPT
subscription -- behind one narrow `SupervisorConfig` field, proving the T1a lane abstraction admits a *swappable* new
lane (more than T3's byte-identical Claude default). Blind/transfer-fed only; no Codex hooks or policy enforcement.

**Key changes**:

- **Lane plumbing**: `SUPERVISOR_CONSUMER` gains a codex candidate `allowed_lane`
  (`Lane(runtime_id="codex", backend_id="chatgpt", model="gpt-5-codex")`; backend/model nominal -- only `runtime_id`
  selects the arm). `SupervisorConfig.supervisor_runtime: str | None` (additive, **no `SCHEMA_VERSION` bump**) is
  validated in `__post_init__` against `_SUPERVISOR_RUNTIMES = ("claude_code", "codex")`; `_supervisor_lane_override`
  raises `LaneError` on validated-but-unmapped drift (M3), never silently falling back to claude.
- **Codex arm** (`_dispatch_codex_supervisor`, replaces T3's `NotImplementedError`): cached preflight ->
  `prepare_codex_request` (sandbox `read-only`, `model=None`, no resume) -> `CodexHeadlessInvoker` ->
  `parse_supervisor_verdict(stdout)`. `_headless_to_session_result` folds `runtime_is_error` (a codex turn can fail at
  exit 0) into the failure signal so a runtime failure isn't misread as unparseable output. Runs in
  `cwd=context.repo_root` (the action repo, not the planner's `source_cwd` -- Phase 9).
- **Fail-open everywhere** (supervisor contract, design_workflows §1.2): `resolve_lane(override=...)` moved inside the
  guard; bad/unknown lane -> `configuration_error`; plan-absent short-circuits *before* spawning codex ->
  `plan_missing`; all codex setup failures -> `codex_unavailable`. No path bricks the policy hook.
- **Cached preflight, never `codex doctor` in the hook** (Phase 7): new `core/runtime/codex_preflight_cache.py`;
  `forge runtime preflight codex` (and `--verify-enrollment`, Phase 10) writes a secret-free cache invalidated by codex
  binary + `auth.json` + `credentials.yaml` mtimes + TTL (M4). The original `run_doctor=False` plan was inert for
  ChatGPT-login auth.
- **Single usage emission** via the invoker's `emit_codex_usage` (the arm never calls `emit_usage_for_session_result`).
  Shadow auditor replays on the configured lane (`ShadowCandidate.supervisor_runtime`, `SHADOW_SCHEMA_VERSION` 1->2,
  M1).
- Docs: design.md §3.6.12 + design_appendix.md §G note the codex arm bypasses the proxy chain (direct to OpenAI).

**Deferred to T5**: the shared `CodexHeadlessInvoker` hardcodes
`record_upstream_operation(operation="workflow.worker")`, so a codex supervisor's upstream row is mislabeled
(tokens/`billing_mode` correct; relabeling touches every invoker consumer, so it belongs to T5's telemetry scope).

**Verification**: supervisor unit suite green (`test_supervisor.py` 103+; 8 new T4 acceptance tests + the Phase-1 lane
tests), shadow 49, preflight cache 11, runtime CLI; `tests/integration/docker/test_supervisor_e2e.py` 10 passed (default
`claude -p` flow unregressed; `forge session set` wires `supervisor_runtime`); `make pre-commit` clean. Shipped via PR
#55 (`40b7a1b6`); a 5-agent read-only verification confirmed all of Phases 1-10 + review fixes M1-M5 are present in
merged `main`.

## 2026-06-26

### consumer_lanes T2: runtime-native subscription sources (ChatGPT via codex)

**Goal**: Let the model-source catalog name a subscription backend whose connection and auth are owned by a runtime (the
ChatGPT subscription reached through codex), so a lane can target it without inventing a URL or a Forge credential.

**Key changes**:

- `backend/sources.py`: new `runtime_native` `EndpointKind` (`SourceEndpoint.runtime_native()`, no URL/credential) and a
  `BillingPosture` declaration (`per_token` default | `subscription_quota` | `free`), distinct from the per-invocation
  `BillingMode` in `core/usage` (shared spelling only). `ModelSource` gains `billing_posture` and
  `reachable_via: tuple[str, ...]`. Validator symmetry: a `runtime_native` source MUST declare zero credentials and no
  endpoint URL; every other kind still requires >=1 credential. Added the `chatgpt` built-in (`provider="openai"`,
  `runtime_native`, `subscription_quota`, `reachable_via=("codex",)`).
- `core/provider_types.py`: `ProviderType` gains catalog-only `openai` (never a `core.llm` routing target;
  `detect_provider` maps `openai/<model>` to `litellm_remote`).
- `core/lanes.py`: `_reachable` now honors `reachable_via` -- a pinned source is reachable only via its listed runtimes
  (empty = any), so `claude_code/chatgpt` is unconstructible while `codex/chatgpt` resolves.
- `cli/backend.py`: read surfaces treat `runtime_native` as runtime-owned, not "configured" -- `list` reports auth
  `runtime_native` / health `runtime-owned`; `test-auth` skips the probe and points to `forge runtime preflight codex`
  instead of reporting a credential failure.
- `config/loader.py` (review fix): a `runtime_native` source cannot back a proxy -- template loading rejects a
  `proxy.source` pointing at one, so a template can never mint a proxy for an undialable backend (enforces the "no proxy
  support for subscriptions" boundary).
- `core/runtime_vocab.py` (new, dependency-light; review fix): the lane runtime axis (`{core_llm}` + agent `RUNTIMES`).
  `sources` validates `reachable_via` pins against it at import, so a typo like `("codx",)` fails loudly instead of
  reading as silently unreachable in `lanes._reachable`. A drift test locks the vocab to `RUNTIMES`. Sources imports the
  vocab (not `core.runtime.registry`) because that package pulls `auth`/`template_secrets` back into `sources` -- a
  cycle; this mirrors the existing dependency-light `core.provider_types` pattern.

**Decision**: runtime-native auth is a first-class semantic of the endpoint kind (Option c), not a relaxed credential
exception. Forge names the backend and reasons about its billing/reachability; the runtime owns endpoint + auth, and
`Credential` stays pure.

**Verification**: focused suites pass (`test_sources.py`, `test_lanes.py`, `test_backend_commands.py`, `test_loader.py`,
plus the custom-template-source regression); 4638 ripple tests across `core`, `backend`, `config`, `proxy`, `cli` pass
(confirming the `ProviderType += openai` and import-graph changes route nowhere); mypy + pyright clean;
`make pre-commit` clean. Design appendix §A.2.1 synced (schema bullets, catalog row, operator-view + template
paragraphs, validation list).

## 2026-06-25

### Fix cascade short-circuit E2E: internally-inconsistent plan, not a flake

**Goal**: Make `test_short_circuit_real_checker_skips_frontier` (the one real-LLM cascade test) pass reliably instead of
consistently escalating to the frontier and blocking.

**Key changes** (test-only; no `src/` change):

- The test's approved plan said "Create src/demo.py ..." but the harness pre-creates that file, so the Write reaches the
  tier-1 checker with `target_exists=true` / `write_mode=overwrite_existing_file`. The deliberately-conservative checker
  ("never guess aligned") *correctly* escalated the create-vs-overwrite contradiction -- so the `mode=divergent`
  frontier fired and blocked (exit 2). The model was right; the plan was wrong. Re-phrased the plan to authorize
  overwriting the existing file to the exact action content, with a comment so it isn't "simplified" back to "Create".

**Verification**: confirmed the test LiteLLM (port 4001) serves `gemini/gemini-2.5-flash` (so this was a plan-wording
bug, not infra). `tests/integration/docker/test_supervisor_e2e.py` 10/10 in Docker; the fixed test passed 4/4 across
repeated real-checker runs (was 0/2). Surfaced during the `supervisor_lane_driven` (T3) E2E pass; fixed on its own
branch as T3-independent.

### consumer_lanes T3: supervisor becomes lane-driven (Claude default, byte-identical)

**Goal**: Drive a real consumer (the semantic supervisor) through the T1a lane resolver -- proving the lane abstraction
fits the existing code -- while keeping the run byte-identical to today (no durable schema, no Codex).

**Key changes**:

- `run_supervisor_check` (`policy/semantic/supervisor.py`) now resolves a `supervisor` `Consumer`
  (`SUPERVISOR_CONSUMER`, floor `tool_agent`, default lane runtime `claude_code`) via `resolve_lane`, then dispatches
  through a thin runtime-keyed seam `_dispatch_supervisor`. The `claude_code` arm (`_dispatch_claude_supervisor`) is the
  pre-T3 path moved **verbatim** -- routing/model/env, the `track_verb_cost` + `run_claude_session` call, and the SOLE
  `emit_usage_for_session_result`. A routing failure raises `_SupervisorRoutingError`, caught by the caller to emit the
  unchanged `proxy_not_found` fail-open. The `codex` arm is `NotImplementedError` (T4); an unknown runtime raises
  `LaneError`.
- Only `lane.runtime_id` is load-bearing in T3 (it selects the arm); `backend_id` (`anthropic-direct`) and `model`
  (`opus`) are nominal -- the arm still derives transport dynamically. T2 makes backend load-bearing.
- Seam lives in `supervisor.py` (not a new module) so existing `patch("...supervisor.run_claude_session")` /
  `resolve_subprocess_routing` targets keep binding.
- Docs: `design_appendix.md` §G gains a consumer-lane layering note. design.md §3.6.12 narrative deferred to >1 wired
  consumer (recorded as checklist debt).

**Verification**: 94 supervisor unit tests (89 existing pass **unchanged** + 5 new: lane binding, single emission on
success + failed run, codex/unknown-runtime arms); 215 `tests/src/policy/semantic` pass (incl. shadow). mypy + pyright
clean on changed source. A 4-lens adversarial workflow (control-flow / emit+cost / dispatch-args / blast-radius), each
byte-diffing against `main`, returned **BYTE_IDENTICAL_HOLDS** with 0 real divergences. `make pre-commit` clean.

### consumer_lanes T1a: pure lane/consumer resolver

**Goal**: Add the pure, I/O-free core of the consumer-lane model (epic `consumer_lanes`) so later tickets can place each
unit of Forge LLM-work on a chosen `(runtime, backend, model)` lane.

**Key changes**:

- New `src/forge/core/lanes.py`: `Lane`, `Consumer`, `runtime_execution`, `valid_lanes`, `resolve_lane`, `LaneError`.
- `core.llm` modeled in the lane layer (decision: option 2) -- `RUNTIMES` left untouched so `list_runtimes()` /
  `installed_runtimes()` stay agent-only (regression-guarded).
- Resolver is pure (no proxy/registry/network I/O): transport deferred to dispatch (T3); `backend_id` normalized to the
  canonical `ModelSource` id (template aliases accepted); override is an allow-list over a consumer's declared lanes;
  default validated at construction; model-catalog validation deferred to T3.

**Verification**: 15 unit tests in `tests/src/core/test_lanes.py` (floor gating, default/override resolution, alias
normalization, purity guard, `RUNTIMES`-untouched regression); `mypy` + `pyright` + `make pre-commit` clean.

### Read failures vs corruption: `StateUnreadableError` split (Fix A)

**Goal**: A transient read failure (OSError) is not corruption — so `forge clean` must never delete a file it merely
failed to open, and a momentarily unreadable state file must surface an actionable "check/retry" message instead of a
misleading "corrupt" or "no session found".

**Key changes** (continues the 2026-06-24 corrupt-state work):

- **New exception family**: `StateUnreadableError(StateError)`, sibling of `StateCorruptedError`, with domain variants
  (`Manifest`/`IndexUnreadableError` = `ForgeSessionError`; `TrackingUnreadableError` = `ForgeInstallError`;
  `Proxy`/`BackendRegistryUnreadableError`). All five readers (store, index, tracking, proxies, backend) now raise the
  unreadable variant on `OSError` instead of a `*CorruptedError`.
- **`forge clean` no longer deletes on transient reads** (HIGH fix): `_detect_corrupt_state` deletes only
  `StateCorruptedError`; an unreadable file is skipped. Backend registry added to `_global_registry_probes`;
  transfer-context protection now triggers on corrupt *and* unreadable.
- **CLI routing**: `handle_unreadable_state_error` (check/retry, never delete) wired into `handle_session_error` and the
  top-level `AliasGroup.main` catch; `%`-handlers emit a distinct unreadable `{decision:block}` (generalized
  `_emit_state_error_block`).
- **Ripple** (~29 sites): at specific-target resolution sites (`session_context`, resolution, session/codex ops, policy,
  memory\*, session_lifecycle, extensions) `except StateCorruptedError: raise` became
  `except (StateCorruptedError, StateUnreadableError): raise`, so an unreadable file propagates to the retry handler
  rather than being swallowed into "no session found". Best-effort sites (`show_proxy`, `codex status`) degrade on both.
- **Docs**: `end-user/proxy.md` cost-bootstrap wording corrected (downstream only; bootstrap no longer reads legacy).

**Verification**: 6927 unit + 464 regression pass; `make pre-commit` clean. 13 new tests (9 in
`tests/regression/test_bug_state_unreadable_not_deleted.py` — clean never deletes/over-corrects, every reader maps
OSError to unreadable, routing; 4 unreadable-routing in `test_corrupt_state.py`). The lone failing test
(`test_result_run_tree_ids_are_optional`) fails only when `FORGE_RUN_ID` leaks from an active Forge session — passes on
a clean tree, unrelated to this change.

## 2026-06-24

### Corrupt-state routing completion: fail-closed GC, full reset-tip coverage, strict costs

**Goal**: Finish the corrupt-state work so every durable-corruption path surfaces the one reset instruction,
`forge clean` never deletes live state on a transient read error, and user-edited spend caps reject unknown keys instead
of silently changing behavior.

**Key changes** (four commits on `main`: `2ec1c7f`, `8e2b6b2`, `f81676d`, `19b6bab`):

- **GC fail-closed** (`core/ops/gc.py`): `_build_transfer_context_reference_set` no longer swallows manifest read errors
  with `except Exception: continue`. A transient/corrupt read on a live child no longer drops its
  `derivation.context_file` from the protected set, so `forge clean` can't unlink authoritative transfer context. The
  same swallow fed the codex stale-snapshot guard. Regression test added.
- **Full reset-tip coverage**: completed the `except StateCorruptedError: raise` (or propagate-from-op) pattern across
  the remaining bypasses — proxy registry (`cli/proxy.py` x8 + claude/codex/session + `core/ops/proxy.py`),
  session/index (resolution, `session_context` nested fallbacks, policy, memory, memory_report, session_lifecycle,
  transfer), and codex ops (session/bridge/interactive). Corruption types multiply-inherit a domain base AND
  `StateCorruptedError`, so a plain `except ForgeSessionError` was intercepting them before the top-level handler.
- **Hook channel** (`cli/hooks/direct_commands.py`): `%proxy list` / `%session list` now emit the corrupt-state
  `{decision:block}` JSON envelope (shared `_emit_corrupt_state_block` helper) instead of letting corruption escape to
  the CLI Rich tip + exit 1, which broke the UserPromptSubmit contract.
- **Strict costs** (`config/schema.py`): `costs` / `costs.caps` reject unknown keys (e.g. the removed `cap_mode`) with a
  ValueError naming the offender, instead of silently ignoring them.

**Adversarial verification**: a 3-lens skeptic panel over the routing diff converged on one real defect — the
`%proxy list` hook regression above — fixed (with the identical pre-existing `%session list` gap) before commit.
Deliberate soft-degrades confirmed intact: delete `--force` recovery, child-lookup callbacks, list-row enrichment,
`show_proxy` degrade, `proxy_identity` ambient lookup, `forge clean`.

**Verification**: 6922 unit tests pass (same 1 pre-existing unrelated telemetry failure,
`test_result_run_tree_ids_are_optional`). 6 new regression tests in `test_corrupt_state.py`. `make pre-commit` clean.

### Backward-compat audit: unified corrupt-state handling + baggage removal

**Goal**: As a clean-break fork with no users, carry no compatibility baggage, and make corrupt durable state fail
gracefully with one actionable instruction instead of a traceback.

**Key changes** (two commits on `main`: `46142882`, `90d8d9d2`):

- **Corrupt-state UX**: every durable-corruption error is now a `StateCorruptedError` (re-parented onto the existing
  domain bases). The top-level `AliasGroup.main` catch routes them all to `handle_corrupt_state_error`, which names the
  offending file and prints one recovery tip (`forge clean`, or reset `.forge` / `~/.forge` + `forge extension enable`).
  The proxy-config loader now raises `StateCorruptedError` (was bare `ValueError`); a truncated `active.json` self-heals
  via discard + recreate.
- **`forge clean` recovery**: added corrupt-state detection/removal — global registries probed at every scope, corrupt
  index falls back to corrupt-state-only mode (never flags every session dir).
- **Removed baggage**: legacy verb-log cost plane (dir/glob + reactive helpers + `verbs` reset target + server arg);
  `costs.cap_mode` and install `patched_files` removed-key tombstones (stale keys now ignored, not rejected); session
  `worktree_path` alias, `designated_docs` strip + dead `_infer_actual_type` param, and the flat-layout
  `iter_legacy_flat_files` reader.
- **Docs/QA sync**: README corrupt-state note, `cli_reference.md`, `design.md`, `design_appendix.md`,
  `end-user/proxy.md`, and the QA checklist (test-count 548 -> 543).

**Adversarial review**: two findings fixed — (1) 7 high-traffic fail-report sites now defer `StateCorruptedError` ahead
of the `ForgeOpError`/`ForgeInstallError` wrap so corruption keeps the reset tip; (2) `forge clean`'s scope gate removed
so global-registry corruption is probed at every scope. Accepted limitation: ~50 best-effort/scan-degrade catch sites
keep backstop semantics by design.

**Verification**: 7361 unit tests pass (1 pre-existing unrelated failure, `test_result_run_tree_ids_are_optional`, a
telemetry `run_id` leak from #49 — fails on clean tree, not touched here). `make pre-commit` clean (ruff, black, isort,
mypy, pyright, mdformat). Net −7 lines despite adding the corrupt-state feature.

### forge_cli_cleanup closeout: CLI taxonomy cleanup card

**Goal**: Close the active `forge_cli_cleanup` card after the full Phase 2 slice set (02-12) shipped and merged to
`main`.

**Key changes**:

- Moved the card `doing/ -> done/` and corrected its stale status line (was "In progress; Slices 03, 04, 06 shipped").
- Confirmed the durable lessons were already promoted to `impl_notes.md` (the D6 alias policy + the "Python symbol !=
  CLI alias string" trap); no new promotion needed.
- Recorded closeout completion in the card checklist's current-focus note.

**Verification**: Code shipped via PR #49 (squash `8a38a372`); working tree clean on `main`. Docs-only closeout;
`make pre-commit` clean.

### forge_cli_cleanup Slice 05: alias + canonical-name pass (final code slice)

**Goal**: Apply the D6 alias decision — make `auth` the canonical command (remove the `authentication` alias) and remove
the `extensions` -> `extension` back-compat shim — closing the last code slice of the CLI cleanup card.

**Key changes**:

- **Clean break (`src/forge/cli/main.py`)**: `_ALIASES` -> `{ext, sess, mem, cfg}`; `_DISPLAY_ALIASES` ->
  `{extension, session, memory, config}`; registration flipped to `main.add_command(auth, name="auth")`. The rename and
  the alias removal are atomic — `forge auth` resolves via the alias today, so both must land together.
  `forge authentication ...` and `forge extensions ...` now fail via Click "No such command" (exit 2, no tombstone).
- **Help/comment accuracy**: `auth.py` help text -> `forge auth`; `install/{cli,hooks,preset,settings_merge}.py`
  comments, `test_version.py` docstrings, and QA `2-extension.md` -> singular `extension` (keeps the drift sweep clean).
- **Tests**: `extensions` -> `extension` CLI strings in `test_startup_queue.py` (6) + 3 integration files
  (`test_installer.py` incl. the `:158` output assertion now matching the real singular tip, `test_project_identity.py`,
  `test_startup_queue_integration.py`); new `test_removed_aliases_are_clean_breaks` (bare + leaf forms) +
  `test_canonical_command_names_resolve` guards. Python symbol/module paths (`from forge.cli.extensions import ...`,
  `runner.invoke(extensions, ...)`) intentionally untouched.
- **Docs**: `cli_reference.md` (alias sentence + `forge auth` table rows); `cli_style_guidelines.md` (crisp D6 rule:
  deliberate aliases only, new nouns get none, rename shims are temporary); `end-user/authentication.md` (removed the
  now-false "Alias" banner); `end-user/README.md`, `config.md`, root `README.md`, QA
  `checklist.md`/`3-authentication.md`.

**Breaking change (research preview)**: `forge authentication` and `forge extensions` are removed — use `forge auth` and
`forge extension`. Kept aliases: `ext`/`sess`/`mem`/`cfg`. New nouns `telemetry`/`model` have no alias.

**Reconciliation with the planned checklist**: the planned `JSON_MISSING_ALLOWLIST` rename was a no-op (the ledger was
already drained to `{}` in Slice 07); the real blast radius was wider than the original card bullets (also `auth.py` /
`install/*.py` / `test_version.py` docstrings, two integration shell-command files, and three end-user docs).

**Verification**: 2314 cli+install unit tests pass; manual smoke (exit 2/2/0/0; `forge --help` shows `auth` +
`extension (ext)`); both drift sweeps clean (the two residual `extensions.py` hits are benign English prose); a 3-lens
read-only adversarial verification workflow (completeness / alias-mechanism / diff-review) returned clean with zero
findings; `make pre-commit` clean; Docker integration 34/34 pass (`test_installer.py` / `test_project_identity.py` /
`test_startup_queue_integration.py`) on a wheel-installed forge — confirms `forge extension` works end-to-end with the
`extensions` alias removed.

**Card status**: final code slice — all Phase 2 slices (02-12) complete; the card is ready to move `doing/` -> `done/`.

### forge_cli_cleanup Slice 12: non-leaf + small-surface cleanup

**Goal**: Close the last non-alias slice — normalize the two hand-rolled non-leaf groups (F13), drain the final
`SINGLE_LEAF_GROUP_ALLOWLIST` entry, and resolve the F14 small-surface candidates.

**Key changes**:

- **F13**: `forge config` + `forge search` now use `no_args_is_help=True` (the `telemetry`/`model` pattern), dropping
  their hand-rolled `invoke_without_command` help-echo callbacks. **Behavior change**: bare
  `forge config`/`forge search` now print help to stderr and exit **2** (was exit 0 on stdout), matching every other
  group.
- **Single-leaf drain**: added `forge policy shadow status [session] [--json]` (sample rate + pending/done audit
  counts), making `shadow` a real 2-leaf group (show + status); the hidden `run` worker and its Stop-hook `Popen` are
  untouched. `SINGLE_LEAF_GROUP_ALLOWLIST` drained to `set()`. New `count_pending_candidates` helper in
  `policy/semantic/shadow.py` names "pending" precisely (vs `count_existing_candidates`, which counts all states).
- **F14 `proxy metrics --all` removed** (clean break): bare `metrics` already aggregates when >1 proxy. Old `--all` →
  Click "No such option" (exit 2).
- **F14 resume-mode asymmetry documented** (comment only): `resume` uses `{native, transfer}` (stays in place), `fork`
  uses `{transfer, native-relocate}` (can relocate to a worktree) — cross-referenced at both call sites.
- **F14 kept as-is**: `memory track` and `extension sync` — the names are defensible (the audit's rename suggestions
  rested on a misread; `enable` = first-time setup, `sync` = refresh an existing install).
- **Fold-in**: `claude.py start_cmd`'s 5 error sites now route through `output.err_console` (stderr), fixing a
  pre-existing stream-rule violation; the Slice 11 `err_console` primitive is reused.

**Verification**: 267 tests across the touched CLI files pass, incl. new `shadow status` cases, the `metrics --all`
clean-break test, and updated `test_claude_command.py` stderr assertions; tree invariants pass with both allowlists
empty; `make pre-commit` clean.

**Follow-up (post-review fixes)**:

- **Stream contract for policy resolver**: `_resolve_policy_session` wrote its "session not found" / "multiple sessions"
  diagnostics through the stdout module console, so a failing `policy shadow status <bad> --json` (the new read leaf)
  emitted the error on stdout with empty stderr. Routed all of that helper's diagnostics through `output.err_console` —
  it only ever prints on failure, so nothing there is a result. This fixes the whole policy surface (`policy status`,
  `supervisor status`, etc.), not just `shadow status`. Regression test
  `tests/regression/test_bug_slice12_policy_resolver_error_stream.py`.
- Fixed a duplicated Slice 05 checklist line (edit artifact from the Slice 12 closeout).

### forge_cli_cleanup Slice 11: recovery-output cleanup

**Goal**: Resolve card finding F9 — route every hand-rolled terminal `Tip:` and `[red]Error:[/red]` through the
`forge.cli.output` helpers, and turn the two debt ledgers into locked, never-grow guards.

**Key changes**:

- **234 `[red]Error:[/red]` sites → `print_error`** across 18 CLI modules. The transform is receiver-preserving
  (`<recv>.print(f"[red]Error:[/red] {x}")` → `print_error(f"{x}", console=<recv>)`), so rendered output is
  byte-identical (`print_error` reconstructs the same `console.print`); redundant `style="red"` kwargs dropped. Done via
  two deterministic codemods (single-line, then the 13 multi-line concat blocks).
- **10 terminal tips routed**: 8 plain `click.echo("Tip: …")` (auth ×4, claude ×2, hooks/install ×2) → `print_tip`; the
  2 `session.py` `ClickException`-embedded tips → `print_error_with_tip` + `sys.exit(1)`. The proxy resolver now
  prints-and-exits instead of raising (no caller catches it; all 13 resolver tests mock it). `claude.py` proxy-error
  branches likewise use `print_error_with_tip`.
- **2 non-recovery `Tip:` reworded**: the `forge telemetry costs show` help docstring (`proxy_costs.py`) and a
  `session_fork.py` convention comment, so no stray literal `Tip:` survives outside the helper/allowlist.
- **Guards locked**: `CLI_ERROR_MARKUP_ALLOWLIST` drained to `set()`; `test_cli_rich_tips_go_through_output_helpers`
  broadened from `[dim]Tip:` to literal `Tip:` (catches plain echoes + ClickException-embedded), allowlisting only the 3
  assistant-facing `hooks/direct_commands.py` payloads. Both fail on any new offender.
- **Scope boundary (recorded)**: plain `click.echo("Error: …")` without Rich markup (~11 files) stays out of F9 scope;
  the guards target `[red]Error:[/red]`/`Tip:` only. Migrated plain echoes only where intertwined with a moved tip
  (claude/install).
- Docs: `CLAUDE.md` + `cli_style_guidelines.md` recovery-output rules updated for the broadened tip scan and the drained
  ledgers.

**Verification**: full unit suite 6879 passed (clean run-tree env — the lone failure under a live Forge shell was an
ambient `FORGE_RUN_ID` leak into a shadow-curation subprocess, unrelated); `tests/src/cli` 2032 passed incl. the 13
`test_output.py` guards; `make pre-commit` clean (black reformatted 2 files, then green; mypy/pyright/isort/mdformat/
gitleaks pass). Every multi-line and nuanced edit reviewed against the final post-black source.

**Follow-up (post-review fixes)**:

- **Stream regression fixed**: the `session._resolve_routing_from_cli` rewrite had moved proxy-resolution errors/tips
  from Click's stderr (old `ClickException`) onto stdout, polluting the results stream (cli_style_guidelines.md "Output
  Streams"). Added a shared `output.err_console` (`Console(stderr=True)`) and routed the resolver's 5 error/tip sites
  through it; `hooks/install.py` now imports the same `err_console` instead of constructing its own. Helper defaults
  stay stdout (changing them would flip ~71 bare call sites — out of scope). New regression test
  `tests/regression/test_bug_slice11_resolver_error_stream.py` exercises the real resolver (the 5 unit tests all mock
  it) and asserts error+tip on stderr, clean stdout.
- **Tip allowlist tightened** from file-level to payload-level: pinned to the 3 exact assistant-payload sentences in
  `direct_commands.py` (plus a stale-payload check), so a new `Tip:` anywhere — including elsewhere in that file — now
  fails. Verified all four branches fire (clean / stray-in-pinned-file / stray-elsewhere / removed-payload).

### forge_cli_cleanup Slice 10: policy supervisor cleanup

**Goal**: Resolve card F7 — split the overloaded `forge policy supervise` (15 options, 7 mutually-exclusive actions)
that collided with the separate one-shot `forge policy supervisor`, by deleting `supervise` and promoting `supervisor`
into a verb group.

**Key changes**:

- **`forge policy supervisor` is now a group with 8 leaves**:
  `{status, set, off, on, remove, reload, cascade, evaluate}`. Each leaf lifts one branch of the old `supervise_cmd`;
  the per-invocation cross-flag validation (action-count, "`--timeout` requires a target") is gone because Click's tree
  enforces it structurally. The `src/forge/policy/semantic/supervisor.py` ops layer was unchanged — leaves map 1:1 to
  existing functions.
- **One-shot file eval is now `forge policy supervisor evaluate`** (renamed from the standalone `supervisor` leaf;
  `evaluate`, not `check`, since `forge policy check` owns bundle-engine eval and stays untouched).
- **`supervisor status` gained `--json`** via a shared `_supervisor_status_dict()` helper reused by `policy status` (one
  canonical supervisor JSON shape; configured + unconfigured shapes pinned in tests). Required by the `_READ_LEAVES`
  guard — any leaf named `status` must expose `--json`.
- **Direct command `%policy supervise` renamed to `%policy supervisor`** (`_handle_policy_supervisor`); sub-verbs
  (off/on/remove/reload/cascade/`<target>`) unchanged.
- **Guard**: dropped `forge policy: supervise|supervisor` from `LEAF_NAMING_ALLOWLIST` (now `{}`); the split dissolves
  the confusable-sibling collision and introduces no new ones.
- **Docs/QA**: complete clean-break sweep across 10 files (`cli_reference`, `design`, `design_workflows`, five
  `end-user/*`, QA `13-policy.md`) mapping every `supervise`/one-shot form to the new leaves.

**Breaking change (research preview)**: `forge policy supervise` is removed (every action moved to a `supervisor` leaf),
and the bare one-shot `forge policy supervisor -f … -r …` now requires the `evaluate` subcommand because `supervisor`
became a group. On the CLI both error via Click (exit 2). The in-session `%policy supervise` falls through the
direct-command dispatcher to a block-JSON usage message naming `%policy supervisor`. `--reload`/`--reload-from`
collapsed to `reload [--from PATH]`.

**Verification**: 59 tests in `test_policy_supervisor.py` (incl. two clean-break tests and configured/unconfigured
`status --json` shapes), 84 in `test_user_prompt_dispatcher.py` (incl. old-verb-falls-through), 7 tree invariants, 2032
in `tests/src/cli`; live CLI confirms both clean breaks; repo-wide greps show no stale `supervise`/bare-one-shot refs
outside board files; `make pre-commit` clean.

### forge_cli_cleanup Slice 09: destructive-command consistency

**Goal**: Standardize destructive verbs (card F3 + F14a) — a `clean` verb previews by default and mutates only with
`--yes`; every `delete`/`reset` keeps one `--yes` bypass — and convert the `_(review)_` rule into mechanical guards.

**Key changes**:

- **`forge proxy clean` removed (F14a, clean break)**: verified fully redundant — `prune_stale_proxies()` prunes the
  registry **and** deletes overlay dirs, and `forge proxy list`/`create`/`start` each call it before their work, while
  `forge clean`'s always-global `proxies` category covers it too. Deleted the command and **all** 7 stale references
  (module header, `cli_reference.md`, `design.md` §3.6.3, three `end-user/proxy.md` refs incl. the troubleshooting
  recovery row, and the QA auto step), naming `forge clean` / auto-pruning as the replacement. Old path → Click
  `No such command`.
- **`forge session clean` conformed**: dropped `--dry-run`, added `--yes`; default now previews
  (`_clean_sessions_dry_run` returns the deletable count so the caller offers a `Use --yes to delete.` tip), `--yes`
  deletes. Updated the `main.py` session-cleanup-exemption comment (`clean --dry-run` → `clean preview`).
- **`forge search clean` conformed**: added `--yes`; default previews via new **read-only** `find_missing()` detectors
  on `SearchDocumentStore` and `IndexStateStore` (siblings of `prune_missing`, same predicate, no lock/write), `--yes`
  prunes (unchanged).
- **Two mechanical guards** (`test_command_tree_invariants.py`, positive assertions):
  `test_clean_verbs_preview_by_default` (every `clean` leaf carries `--yes`, never `--dry-run`) and
  `test_destructive_prompt_verbs_use_yes` (every `delete`/`reset` leaf carries `--yes`; `forge session reset`, a
  non-deleting override-layer reset, is the one permanent exemption). Style-guide destructive rule flipped `_(review)_`
  → `_Guard:_`.

**Breaking change (research preview)**: `forge proxy clean` and `forge session clean --dry-run` are removed. Stale
proxies are pruned automatically by `proxy list/create/start` (and `forge clean`); `session clean` now previews by
default — pass `--yes` to delete. `search clean` likewise previews by default; pass `--yes` to prune.

**Verification**: 395 tests across `test_command_tree_invariants` (7), `test_session_commands`, `test_search`,
`test_proxy_commands` (removal → exit 2), and the search-store `find_missing` units; `forge proxy clean` errors via
Click; a repo-wide grep confirms no stale `proxy clean` reference outside board files; `make pre-commit` clean.

### forge_cli_cleanup Slice 08: config-object verb parity

**Goal**: Implement D7 — enumerate the tiered editable-config verb vocabulary in the style guide (un-defer the
placeholder), correct a docstring that implied false `forge proxy` parity, and lock the core set with a regression
guard. No behavior change, no net-new commands.

**Key changes**:

- `cli_style_guidelines.md`: replaced the deferred config-object rule (which punted to "the forge_cli_cleanup card")
  with the enumerated tiered vocabulary — core `{show, edit, reset}` (met by `config`/`proxy template`/`claude preset`),
  optional `{set, validate}`, a per-surface table, and a dual `_Guard:_`/`_(review)_` marker. `proxy` documented as the
  partial-lifecycle exception (no `reset`); `backend` excluded as a lifecycle resource under the sibling-verbs rule.
- `config_cmd.py`: reworded the module docstring to drop the false "matches forge proxy show/set/edit" parity claim; it
  now names the core+optional membership and points at the style guide.
- `test_command_tree_invariants.py`: new `test_editable_config_objects_share_core_verbs` — a positive core-set assertion
  on the three editable-config objects plus a boundary lock asserting `proxy`/`model backend` carry no `reset`. Positive
  assertion (not the `_assert_ledger` debt helper) because there is zero pre-existing debt — all three already comply.

**Verification**: `test_command_tree_invariants.py` (5 passed, incl. the new guard); full `tests/src/cli` (2022 passed);
`make pre-commit` clean.

### forge_cli_cleanup Slice 07: read-output consistency (+ F11 audit)

**Goal**: Make every read surface default to human output, expose a stable `--json`, and keep human + JSON on stdout --
draining the `JSON_MISSING_ALLOWLIST` / `JSON_DEST_ALLOWLIST` debt ledgers to empty.

**Key changes**:

- **`--json` added (A)**: 10 read leaves grew `--json` (dest `as_json`) -- the 8 allowlist leaves plus `auth profiles`
  and `session transfer diff`. New shapes are stable + fully populated on empty paths. `auth status` exposes only
  source/provenance labels (secret `value` is `null` -- verified no leakage); `memory shadows show` is multi-row;
  `claude preset show` parses only inside the `--json` branch (human mode still tolerates a corrupt file).
  `_READ_LEAVES` gained `profiles`/`diff`; `JSON_MISSING_ALLOWLIST` -> `{}`.
- **`--json` dest normalized (B, D8)**: 9 leaves rebound `json_output` -> `as_json` across `proxy.py`/`policy.py`/
  `workflow.py` (uniform rename -- every ref was leaf-private). `JSON_DEST_ALLOWLIST` -> `{}`.
- **`search query` inverted (C)**: now prints a Rich table by default; `--json` re-emits the prior shape byte-stable
  (including conditional `error`/`hint`/empty variants). Updated all JSON-parsing consumers: `test_search.py` (+2 new
  human-default tests), the stop-snapshot regression test, the search integration test, QA 12.3 + walkthrough 10.5
  checklists, `search.md`, `cli_reference.md`.
- **Stream ownership (D)**: `proxy_audit.py` shared console flipped `stderr=True` -> stdout so `audit show`/`diff` human
  tables join their JSON on stdout. New `tests/src/cli/test_output_streams.py` (plain `CliRunner()`; Click 8.2 removed
  `mix_stderr`) asserts `--json` is valid JSON on stdout with empty stderr for the telemetry + audit leaves.
- **F11 (record-only)**: audited ~32 session-scoped commands at 100% selector compliance; rule stays `_(review)_`, card
  Open Question 1 resolved. Annotated the style-guide rule "audited compliant 2026-06-23".
- **Shape-test backfill + hardening (review follow-up)**: the structural guard only proves `--json` *presence*, so added
  ~40 behavioral shape tests across the 10 new branches (parseability, exact key sets, dispatch/empty/error paths) --
  authored + adversarially verified via a fan-out workflow. The `auth status` no-secret-leak contract is now pinned by a
  test that sets a real secret (env + file) and asserts every `is_secret` var serializes `value: null`. Fixed a real bug
  this surfaced: `auth status --json` silently swallowed a corrupt-credentials `ValueError` (the human path warns),
  violating the "best-effort degradation is never silent" rule -- now it carries an always-present `warning` key (null
  when clean), mirroring `transfer show --json`. Also corrected `cli_style_guidelines.md`, which still called the
  stdout/stderr JSON guard "planned/not yet wired".

**Verification**: ~2021 CLI unit tests pass (4 `test_command_tree_invariants.py` guards with both ledgers empty,
`test_search.py` ×25, `test_output_streams.py` ×7, ~40 new `--json` shape tests across the touched leaf suites,
regression); secret-redaction + JSON round-trip smoke-checked; the wheel-installed `forge search query --json`
integration test passes in Docker; `make pre-commit` clean (black/isort/ruff/mypy/pyright/mdformat).

### forge_cli_cleanup Slice 02: session-scope move (transfer + memory split)

**Goal**: Move session-scoped surfaces under `forge session` so the command taxonomy mirrors ownership -- transfer
context and memory activation are session concerns; project-doc passports stay top-level.

**Key changes**:

- `forge transfer show|regenerate|edit|diff` -> `forge session transfer ...` (clean break; old paths return Click "No
  such command", exit 2). The transfer group is wired onto `session` in `cli/main.py` (assembly layer) to avoid a
  `session <-> transfer` import cycle.
- Memory split (D4): activation/report verbs move to a new `forge session memory` group
  (`enable`/`disable`/`status`/`report`); top-level `forge memory` keeps passport verbs (`track`/`list`/`passport`/
  `shadows`). `report` is flattened from the former single-leaf `forge memory report show`.
- New module `cli/session_memory.py` (errors routed through `print_error`, no hand-rolled markup); `memory_report.py`'s
  `report` group collapsed to a single `report` command.
- Resolved two debt ledgers in `test_command_tree_invariants.py`: removed `forge memory report` from
  `SINGLE_LEAF_GROUP_ALLOWLIST` (flattened), and **fixed** the `forge memory report show` JSON-missing debt rather than
  hiding it — `forge session memory report` gained a `--json` mode (dest `as_json`; latest path+content, or the report
  list under `--all`), and `report` was added to the guard's `_READ_LEAVES` so the flattened leaf stays enforced (the
  rename had moved it out of the `show`-named coverage). One fewer leaf for Slice 07 to drain.
- Synced docs to the new paths: `cli_reference.md`, end-user (`transfer.md`/`session.md`/`memory.md`/`README.md`),
  design docs, `board/README.md`, `impl_notes.md`, `AGENTS.md`, and QA/walkthrough checklist command blocks.

**Verification**: full `tests/src/cli` unit suite including the new `test_session_memory.py` and `report --json` cases
in `test_memory_report.py`; `test_command_tree_invariants.py` confirms `forge session memory report` is now a guarded
read leaf with `--json`; the cross-package `tests/src/review/test_skill_content.py` guard repointed to
`forge session memory enable`; `make pre-commit` clean (ruff/black/isort/mypy/pyright/mdformat/gitleaks); handoff
integration (`tests/integration/cli/test_handoff_integration.py`, 10 passed) exercises
`forge session memory enable`/`report` end-to-end against a wheel-installed forge in Docker.

### forge_cli_cleanup Slice 03: move telemetry surfaces

**Goal**: Co-locate operator observability under `forge telemetry` and clean-break the old scattered paths.

**Key changes**:

- Added `forge telemetry activity|trace|costs`; removed top-level `forge activity`, `forge provider`, and
  `forge proxy costs`.
- Retired `%provider trace` with no `%telemetry` replacement; `%help` no longer advertises it.
- Moved telemetry-cost human output to stdout, kept JSON on stdout, and tightened the single-leaf group guard while
  removing the fixed `forge provider` ledger entry.
- Updated CLI docs, end-user guides, QA checklists, design breadcrumbs, integration activity coverage, and agent-facing
  guidance.

**Verification**: telemetry-focused unit/hooks suite (213 passed); targeted activity integration (1 passed); `uv build`;
`make pre-commit`.

### forge_cli_cleanup Slice 04: move backend under `forge model`

**Goal**: Build the decided `forge model` namespace and clean-break the old top-level backend path.

**Key changes**:

- Added `forge model` with visible children `backend` and `catalog`; `catalog` renders the static model catalog with
  `--json`.
- Moved all backend verbs to `forge model backend`; old `forge backend ...` now falls through to Click's native "No such
  command" handling.
- Updated recovery tips, shipped QA/config templates, integration harness/fixture paths, `AGENTS.md`, docs, impl notes,
  and command-tree invariant debt (`forge model backend show`, plus `catalog` in the read-leaf JSON guard).
- Kept `forge workflow list-models` as runtime readiness and reworded it to "workflow models".

**Verification**: focused unit/regression slice (69 passed); backend integration (8 passed); proxy smoke (1 passed);
`uv build`; CLI sanity checks; `make pre-commit`.

### forge_cli_cleanup Slice 06: remove `forge session context` (clean break)

**Goal**: Drain the last hidden CLI tombstone — remove the deprecated `forge session context` alias so the surface
relies on Click's native "No such command" instead of a redirect shim.

**Key changes**:

- Deleted the hidden `forge session context` command and its now-dead `_print_session_context` helper from
  `session_manage.py` (plus the two `__all__` exports). The behavior already lives in `forge session show`
  (`--json`/`--field`).
- Kept the `forge.core.ops.session_context` module — still used by `session show`, `activity`, `policy`, and the
  `%`-direct commands. Corrected its "Used by" docstring and two mis-attributed comments in `session_manage.py`.
- Dropped the `session context` note from `cli_reference.md`; fixed the now-stale "deprecated" reference in
  `impl_notes.md`.
- Deleted `tests/src/cli/test_session_context.py` (removed code → delete test); the ops test
  `tests/src/core/ops/test_session_context.py` stays.

**Verification**: `forge session context` exits 2 with Click "No such command" (no tombstone). Tombstone sweep confirmed
`context` was the only deprecated-alias `hidden=True` command (`hook`/`memory-writer`/`status-line`/`policy shadow run`
are live internals). 267 tests pass across `test_session_commands`, `test_session_context` (ops),
`test_command_tree_invariants`, `test_activity`, `test_policy_shadow`, `test_direct_commands_provider`.

### forge_codex_command_group closeout: sessionless Codex proxy launcher card

**Goal**: Close the active `forge_codex_command_group` card after the status surface, Responses passthrough transport,
and sessionless `forge codex start --proxy` launcher shipped.

**Key changes**:

- Moved the card from `doing/` to `done/` and updated its checklist/card closeout state.
- Synced end-user docs for the sessionless Codex proxy launch path, including the `codex-responses-local` template,
  Responses-capable proxy requirement, env scrub/no-`config.toml` boundary, and `openai-api` credential ownership.
- Promoted durable implementation notes for the Codex Responses passthrough and launcher identity/capability gates.
- Recorded the remaining live 200 reasoning round-trip as an accepted operator residual: it still needs a working
  OpenAI/LiteLLM key, but the routing/launcher path has been verified up to upstream 401/429.

**Verification**: Docs-only closeout; `make pre-commit-md` clean.

### forge_codex_command_group Phase 4: `forge codex start --proxy` launcher

**Goal**: Ship the sessionless, proxy-backed Codex TUI launcher -- the consumer the card was built for -- on top of the
Phase 3 Responses transport.

**Key changes**:

- **CLI** (`src/forge/cli/codex.py`): new `forge codex start --proxy <id-or-template> [--sandbox] [-- codex-args]` leaf.
  Order: codex-installed -> hard version gate -> `ensure_proxy` -> capability gate -> exec, with the full error matrix
  on a stderr `Console` via `forge.cli.output` helpers (closes the Phase 1 stderr-Console deferral).
- **Version gate** (`core/runtime/codex_preflight.py`): `CODEX_PROXY_CONTRACT_VALIDATED = "0.141.0"` +
  `codex_proxy_contract_blocker()`. Fail-closed below the floor (parsed only); unparseable/None allowed. Distinct
  surface from the 0.139.0 probe ceiling and the 0.131.0 hook floor.
- **Capability gate** (`proxy/proxy_orchestrator.py`): `assert_proxy_responses_capable()` + `ProxyUnreachableError` /
  `ProxyNotResponsesCapableError`. Requires the full `wire_shape == openai_responses_passthrough` AND
  `capabilities.responses_ingress` conjunction off `GET /` (mirrors the runtime route gate); returns the proxy's
  default-tier model. **Review fix**: also re-verifies proxy identity (`is_proxy` + `proxy_id` + `template`) from the
  same body via `expected_proxy_id`/`expected_template`, raising `ProxyIdentityMismatchError` -- `ensure_proxy` returns
  exact ids by registry presence, not liveness, so a stale entry on a reused port can't misroute Codex to a different
  proxy.
- **Bare invocation** (`session/codex_invoke.py`): `invoke_codex_bare_proxy` + pure env/argv builders.
  `_CODEX_BARE_PROXY_STRIP_VARS` scrubs native codex/OpenAI auth, the 5 OpenAI account/routing vars, and
  session/run-tree identity; re-establishes NO native auth (the proxy owns upstream); list-mode `-c` provider argv; `-m`
  auto-default suppressed when the user passes one; never `--strict-config`.
- **Allowlist**: removed `forge codex` from `SINGLE_LEAF_GROUP_ALLOWLIST` (now 2 leaves); updated the registration test.
- **Docs**: `cli_reference.md` `start` row; `design.md` §3.4 "Bare launch (Codex)" + §3.7 consumer cross-ref.

**Verification**: 62 new unit tests (version blocker, capability + identity gate, env/argv/invoke, CLI matrix) pass;
full `tests/src/cli` suite green; `make pre-commit` clean. Live gate: real codex 0.141.0 routed via the list-mode `-c`
argv to `POST /v1/responses`, and the identity check was live-verified against a real proxy body (correct id passes,
wrong id rejects). The 200 reasoning round-trip stays credential-blocked (dead key), as in Phase 3.

## 2026-06-22

### forge_codex_command_group Phase 3: Codex Responses proxy transport (passthrough)

**Goal**: Give Forge's proxy a Codex-facing OpenAI **Responses** ingress so `forge codex start --proxy` (Phase 4) has a
Responses-capable proxy, and flip the dead `proxy_supported` preflight posture live — without dropping Codex's
reasoning-item continuity.

**Key changes** (revises card Slice 2: passthrough, not the originally-scoped translating transport — translation drops
signed reasoning):

- New `openai_responses_passthrough` wire shape forwards Codex's raw `/v1/responses*` traffic byte-for-byte. Shared
  SSE-teardown core extracted to `proxy/stream_relay.py` (Anthropic passthrough's 32 tests unchanged);
  Responses-specific forwarding in `proxy/responses_passthrough.py` (Bearer injection + strip inbound
  auth/`OpenAI-Organization`/`-Project`, tolerant usage side-tap, `x-litellm-response-cost` USD→micros, response-header
  allowlist that also drops the proxy-owned `x-request-id`).
- `proxy/responses_ingress.py` (new): the FastAPI\<->transport glue — the `/v1/responses*` handler, route registrar
  (`POST /v1/responses` create before the `{rest:path}` catch-all), and GET / advertisement helpers. Route gated on
  `wire_shape == openai_responses_passthrough` **and** the source's `responses_ingress` else 501; bodyless GET/DELETE
  never call `.json()`. Extracted from `server.py` to keep that module under the 2.5k-line cap (reads proxy runtime
  state via a lazy `import forge.proxy.server`, which also avoids a load-time cycle). `server.py` registers the routes
  and uses the helpers in `GET /`.
- `backend/sources.py`: `responses_ingress` capability, `codex-responses-local` source/template (litellm-local upstream
  so cost is reported), `source_bearer_auth_env_var()` (single secret env var; fail-closed on 0/>1).
- `core/runtime/codex_preflight.py`: `proxy_supported` now returned, gated on the **same** wire_shape ∧
  `responses_ingress` conjunction the route enforces (file-read preflight can't green-light a proxy the runtime would
  501).
- `proxy_orchestrator.py`: smoke test POSTs a Responses request for this wire shape.
- Accounting precision (pre-merge review): cost/metrics/spend-cap are wired only for the generation endpoint
  (`POST /v1/responses`), so a `GET /v1/responses/{id}` retrieve echoing the original `usage` can't double-count; the
  `OnComplete` callback now carries `error_type`, and a terminal `response.failed` (streamed or non-streamed 200) folds
  into `failed=True` instead of being recorded as success (`response.incomplete` stays a billed partial success).
- Docs: `docs/design.md` §3.4 wire-shape section.

**Verification**: 54 unit tests (`tests/src/proxy/test_responses_transport.py`, incl. the accounting-gate +
terminal-status regressions) + preflight conjunction cases; full unit suite green (6702 passed) — the new source's only
ripple was the `backend list` shared-instance test (codex-responses-local is an OpenAI-credentialed co-tenant of
litellm-4000, now in its `shared_with`); `make pre-commit` clean. **Live gate** (real `codex-cli 0.141.0` → forge
`:8105` → litellm `:4000` → OpenAI): `GET /` advert + intercept table confirmed; codex drove `POST /v1/responses`
(streaming) through the route (not 501), single `X-Request-ID` relayed back. **Deferred**: a 200 reasoning round-trip is
credential-blocked (this env's `OPENAI_API_KEY` is dead) — must be re-confirmed with a live key before the card closes.

### forge_codex_command_group Phase 1: `forge codex status` (read-only Codex inspection)

**Goal**: Ship the read-only Codex inspection surface as the first independently-shippable slice of the codex
command-group card; the proxy-backed launcher stays parked behind the Phase 2 probe.

**Key changes**:

- New `forge codex` group (`src/forge/cli/codex.py`) with one leaf, `status`: reports binary + version
  (`get_runtime("codex").detect()`), per-scope Codex config path, managed-block presence, Forge-only event-aware
  registration pairs, and a static enrollment posture (`yes/no/partial/wrong-event`). Never claims enrollment — points
  to `forge runtime preflight codex --verify-enrollment`.
- Scope resolution mirrors the installer: default = detected scope via `find_forge_installation` (else user);
  project/local roots resolve by walking up for `.git`/`.codex` (not bare cwd); `--all` lists user/project/local
  distinctly (config collapses project\<->local, but tracking is scope-keyed).
- `start` deliberately **not** shipped: a no-`--proxy` placeholder that always errors would be a tombstone and could pin
  a `--proxy` contract the Phase 2 kill criterion may invalidate. `forge codex` is allowlisted as intentional
  single-leaf phasing debt in `SINGLE_LEAF_GROUP_ALLOWLIST` (remove when `start --proxy` ships in Phase 4).
- Docs: `cli_reference.md` "Codex management" section.

**Verification**: 14 unit tests in `tests/src/cli/test_codex_status.py` (scope detection, subdir root resolution,
`--all` local, Forge-only filter, wrong-event, no-`start`-command) plus tree-invariant + output guards = 31 pass;
`make pre-commit` clean (mypy, pyright, ruff, black, isort, mdformat).

## 2026-06-20

### openrouter_user_direct_callers: unified provider-`user` toggle + direct-caller injection

**Goal**: Extend OpenRouter `user`-field session grouping (shipped for the proxied path) to Forge's direct `core.llm`
callers, governed by a single global toggle instead of a per-proxy one — chosen on the principle *product experience
drives architecture* (one switch over two per-scope homes).

**Key changes**:

- **Global toggle**: `provider_trace.inject_provider_user` (default off) now lives in `~/.forge/config.yaml`
  (`RuntimeProviderTraceConfig`); `forge config set/edit` gained nested-section support via a `_nested_sections()`
  registry. Loader is fail-open (bad subtree resets only `provider_trace`); write surfaces (`set`/`edit`) fail-closed on
  unknown subkeys.
- **Proxied gate repointed**: `_inject_provider_user_enabled()` reads `get_runtime_config().provider_trace` (same
  pattern as `auth_ignore_env`); `proxy.yaml`'s `provider_trace` is now retention-only.
- **Sidecar**: mounts `~/.forge/config.yaml` read-only so in-container proxied forks read the same toggle.
- **Direct injection**: `with_openrouter_user` + `resolve_direct_provider_user(role)` (`core/usage/correlation.py`)
  wired into plan-check (role `plan-check`, OpenRouter-gated) and transfer curation (role `transfer-curate`). Both
  derive the id with the same `derive_provider_session_id` as the proxied path, so a run's direct and proxied OpenRouter
  calls group identically account-side. Tagger excluded by design (local LiteLLM).

**Breaking change (research preview)**: the per-proxy `proxy.yaml` `provider_trace.inject_provider_user` (and its legacy
`inject_openrouter_user` alias) is removed. A stale key still loads but is **ignored** with a one-time relocation
warning. Migration: `forge config set provider_trace.inject_provider_user=true` in `~/.forge/config.yaml`. Retention
keys (`retention_days`, `max_total_mb`) stay proxy-owned.

**Verification**: 432 tests green across all touched files (runtime-config, config CLI, schema, routing invariants,
sidecar, correlation, plan-check, transfer, 2 regressions); `mypy` + `pyright` clean on every changed source and test
module. Docs synced (design §3.14, appendix §A.14, end-user config.md + proxy.md). Sidecar integration run passed in
Docker (`test_audit_plumbing.py`: config.yaml mounted read-only + in-container `get_runtime_config()` reads the toggle).
`make pre-commit` clean.

### backend_remote_reconciliation PR 2: `forge backend reconcile` (single-id MVP)

**Goal**: Ship the MVP of backend remote reconciliation -- join one local downstream trace to one remote account-side
record for any backend with a registered remote adapter. OpenRouter is the first adapter.

**Key changes**:

- New `src/forge/backend/remote/` package: a `BackendRemoteAdapter` protocol + adapter registry (presence in the
  registry, not a `ModelSourceCapabilities` flag, is what makes a source remote-reconcile capable), generic
  metadata-only DTOs (`RemoteCapability`, `RemoteRecord`), and `RemoteAdapterError`/`RemoteAdapterNotFoundError`.
- `OpenRouterRemoteAdapter` (narrow `httpx` client) hits `GET /api/v1/generation?id=...` with the normal key, whitelists
  metadata only (never `/generation/content`), normalizes `total_cost` USD -> micros, and maps every HTTP/network result
  to a `RemoteRecord(outcome=...)` (200->found, 404->not_found, 401/403->not_authorized, else->unavailable; missing key
  -> not_authorized via a no-HTTP pre-check).
- New op `core/ops/backend_reconcile.py` (`reconcile_generation` + `render_reconcile_lines`): comparative bucket
  taxonomy `joined`/`remote`/`missing-remote`/`not-queryable`; downstream reads scoped by `backend_id`; local and remote
  cost/tokens kept separate with provenance; remote/network failures are renderable data, never raised.
- New CLI leaf `forge backend reconcile <source-id>` (`--request-id`/`--remote-id`/`--json`/`--timeout`), and docs
  (cli_reference, design_appendix §A.14, end-user/proxy.md). Windowed account-wide activity/analytics (management key,
  `local`/`missing-local` buckets) stays a declared follow-on -- the protocol already carries the window seam.
- Review hardening (from a 32-agent adversarial review, 21 confirmed findings): total numeric coercers + a parse net so
  a malformed-but-parseable 200 body (NaN/Infinity/overflow/bool, default `json.loads` accepts these) maps to
  `unavailable` instead of crashing the CLI with a traceback (the error-vs-data invariant); empty-string ids normalized
  so the xor guard and mode dispatch agree; template aliases resolved to canonical; a 200 error-envelope ->
  `unavailable`; render predicate includes `local_output_tokens`; CLI catches `RemoteAdapterError`; tip wording
  `Use --flag`.

**Verification**: `tests/src/core/ops/test_backend_reconciliation.py` + `tests/src/cli/test_backend_reconcile.py` +
`tests/src/backend/remote/test_openrouter_remote.py` -> 52 passed (14 added for the review fixes, incl. a replaced
tautological content-leak assertion); broader `tests/src/{backend,core/ops,cli}` -> 2322 passed; `make pre-commit` clean
(mypy + pyright).

## 2026-06-19

### backend_remote_reconciliation PR 1: generalize provider-trace observability over any backend

**Goal**: Resume the paused `openrouter_remote_reconciliation` work as the provider-generic
`backend_remote_reconciliation` card (OpenRouter becomes the first adapter, not the feature). PR 1 removes the last
OpenRouter coupling from the provider-trace / provider-user-grouping surfaces so the upcoming `forge backend reconcile`
feature builds on a backend-neutral base.

**Key changes**:

- Renamed the source capability `openrouter_user_grouping` -> `provider_user_grouping` (`backend/sources.py`) and the
  config key `provider_trace.inject_openrouter_user` -> `inject_provider_user` (`config/schema.py`).
- Removed the two `provider_name == "openrouter"` fallbacks: provider-trace writes and the `user`-field injection are
  now purely source-capability gated by `backend_id`. Renamed `_openrouter_user_value` -> `_provider_user_value` and
  `_inject_openrouter_user_enabled` -> `_inject_provider_user_enabled`, and dropped the now-dead `provider_name` param
  from `record_provider_trace` and all call sites + the passthrough ctx dict.
- A proxy with no `proxy.source` now writes no trace / injects no user (the fallback's only beneficiary), surfaced once
  via a dedicated `_warned_absent_backend_source` INFO latch in `server.py`.
- `proxy.yaml` is user-owned config (system boundary): the old `inject_openrouter_user` key is honored as a
  warn-and-degrade alias (new key wins if both set), not a hard reject.
- Genericized provider-coupled comments/docstrings and normative docs (design §3.14, appendix §A.14, cli_reference,
  end-user/proxy.md incl. an alias note). Board: moved `paused/openrouter_remote_reconciliation` ->
  `doing/backend_remote_reconciliation`, reframed card/checklist (two-PR plan, superseded Phase 0 decisions), and
  updated the telemetry epic's member table + the `openrouter_user_direct_callers` references.

**Verification**: `uv run pytest` over the renamed proxy/config/cli/ops surfaces + the new
`test_bug_provider_trace_inject_alias.py` regression (185 passed); `make pre-commit` clean (mypy + pyright); live
`tests/integration/proxy/test_provider_trace_e2e.py` (2 passed) confirms the real OpenRouter proxy still writes traces
via the `source: openrouter` capability gate.

### unified_backend follow-up: custom templates preflight credentials from declared source

**Goal**: Fix a credential-preflight gap left by `unified_backend` — user-named proxy templates silently skipped
credential checks because lookups keyed on the shipped-only `TEMPLATE_ENV_VARS` map, so a custom template launched
without its API key and failed at runtime instead of failing fast at start.

**Key changes**:

- `required_env_vars_for_template()` (`core/auth/template_secrets.py`) reads a template's declared `proxy.source` and
  resolves required env vars from the model-source catalog, falling back to `TEMPLATE_ENV_VARS` when no source is
  readable/declared. `credentials_for_template`, `get_secrets_for_template`, and proxy-start
  `_ensure_template_credentials` route through it.
- Read hardening: an existing-but-unreadable template (permissions/IO) or invalid YAML now logs at WARNING instead of
  degrading silently; an unknown name stays silent (`FileNotFoundError`). Still best-effort — returns the safe fallback,
  never raises into callers.
- `credentials_for_template(..., required_vars=)` reuses the resolved list on the proxy-start failure path, removing a
  redundant template read.
- AGENTS.md: added backend-source / telemetry / provider-trace operator-verification guidance.

**Verification**: New regression `tests/regression/test_bug_custom_template_source_credentials.py` plus 5
`test_template_secrets.py` unit cases (declared-source resolve, no-source/unknown-name fallback, unreadable-warns,
invalid-yaml-warns); `tests/src/{proxy,core/auth,backend,sidecar}` + regression green (156 focused); mypy clean;
`make pre-commit` clean.

### unified_backend closeout: shared local-instance display + review follow-up

**Goal**: Land the PR #39 review follow-up and close the `unified_backend` card.

**Key changes**:

- `forge backend list`/`show` now mark a local LiteLLM runtime instance shared across sources (one `litellm-4000`
  process backs Gemini + OpenAI under the shipped default config); `--json` carries `runtime_instance.shared_with`. The
  matching heuristic stays display-only and never feeds downstream telemetry `backend_id` (still derived from
  `proxy.source`).
- Proxy `_backend_source_id` warns once when `proxy.yaml` carries an unrecognized `source` (warn-and-degrade; user-owned
  config is a system boundary), instead of silently passing an unknown `backend_id` into telemetry.
- Added a multi-key backend-list test mirroring the shipped default (the case the prior gemini-only fixture masked) plus
  warn-once server coverage; documented the shared local LiteLLM process model in `proxy.md` and design appendix §A.2.1.
- Card moved `doing/ -> done/`; telemetry epic member table updated (`unified_backend` done).

**Verification**: backend CLI + new server suite (22) and proxy/backend/telemetry/usage suites (175) green;
`make pre-commit` clean (mypy + pyright). Shipped via PR #39 (squash `ab690ac9`).

## 2026-06-18

### unified_backend: model-source catalog and downstream source attribution

**Goal**: Make local and remote model sources one listable backend/source axis and key downstream telemetry on a
canonical catalog id.

**Key changes**:

- Added a built-in `ModelSource` catalog for local LiteLLM, remote LiteLLM, OpenRouter, Anthropic passthrough, and
  direct-runtime sources, with endpoint, credential, lifecycle, and capability metadata.
- Moved proxy templates to `proxy.source`, deriving endpoint/auth/lifecycle facts from the catalog while keeping runtime
  backend instances separate from static source definitions.
- Expanded `forge backend list/show/test-auth` around source ids; remote sources have intentional no-lifecycle behavior
  and local lifecycle still resolves to existing LiteLLM adapters/ports.
- Added downstream `backend_id` attribution across proxy cost, audit, provider trace, and direct usage emitters while
  preserving `source_id`/`source_kind` as writer-origin metadata.
- Replaced OpenRouter-specific provider-trace and `user` injection gates with source capabilities.

**Verification**: Focused unit/regression acceptance slice passed 526 tests; backend integration slice passed 11 tests;
`make pre-commit` clean.

### upstream_downstream_ledgers closeout: two-pane activity + upstream boundary coverage

**Goal**: Finish two-pane `forge activity` and close non-engine upstream outcome gaps.

**Key changes**:

- Extracted shared measurement resolution for proxied/direct/self-reported paths.
- Routed policy-engine writes through `record_upstream_operation(...)` and added non-engine operation outcomes.
- Reworked `forge activity` into Operation outcomes and Model calls panes with clean-break JSON and bounded rollups.
- Kept `render_summary_line(...)` in lockstep and updated design, user, CLI, QA, and board docs.

**Verification**: `mypy` clean for `measurement.py`; targeted suites passed 434/237/517 tests; integration closeout
passed 36 tests; `make pre-commit` clean.

### upstream_downstream_ledgers: telemetry clean cut and cap-safe migration

**Goal**: Re-cut Forge telemetry toward downstream model-attempt evidence and upstream operation outcomes without
silently resetting spend caps during the path move.

**Key changes**:

- Added `~/.forge/telemetry/downstream/` and `~/.forge/telemetry/upstream/` JSONL planes. Proxy cost, audit/drift/
  mutation, provider lifecycle evidence, direct `core.llm`, direct `claude -p`, and Codex usage now write downstream
  attempt records; policy evaluation outcomes write upstream records.
- Default upstream volume is `non_success`; `upstream_event_volume=all` enables success/cached-allow operation logs.
- Spend caps now persist `telemetry/caps/<proxy_id>.json` and bootstrap from
  `max(cap_state, downstream logs, legacy cost logs)`, so clean-cut migration and dropped best-effort telemetry writes
  do not reset monthly caps to zero.
- `forge proxy costs reset` now wipes old cost logs, new upstream/downstream telemetry, cap state, audit sidecar state,
  usage events, and derived status-line caches; sidecar proxy launches mount `~/.forge/telemetry/` rw.
- Provider trace reads now project downstream attempt fields, and `forge proxy costs show --by-verb` derives attribution
  by joining downstream requests to usage run ids instead of writing new `costs/verbs` shards.

**Verification**: Focused telemetry/proxy/policy/activity/sidecar suite green (264 tests), provider-trace CLI/core/
regression suite green (32 tests), direct/provider metadata regression coverage added, ruff clean on touched Python and
tests.

## 2026-06-16 (compacted)

### proxy_log_hygiene (slices 0-5 + reviewer follow-ups)

**Goal**: Cut low-value proxy log volume (poll spam, per-chunk dumps), add bounded redacted request diagnostics aligned
with the audit no-plaintext policy, and close reviewer-found leaks.

**Key changes**: Folded loader bug fixed -- both proxy-config hops now carry `provider_trace` + `logging` (was silently
dropped; `test_bug_provider_trace_loader_dropped.py`). Successful completions log at DEBUG, INFO reserved for `>=400` /
slow polls; per-chunk stream dumps require opt-in AND DEBUG; shared `format_stream_lifecycle_summary` replaces
per-stream INFO bookends. Per-proxy `logging.requests` (`RequestLogConfig`, strict coercers, `body_capture=full`
rejected) reuses the audit body redactor -- no second sanitizer. New shared `proxy/retention.py::prune_jsonl_shards`
(age-then-size) backs audit/provider-trace/request planes. Reviewer round: 8 converter log sites reduced to
metadata-only, `stop_sequences` plaintext leak redacted in `_redact_body_for_log`, CLI int coercion for
`max_file_mb`/`stream_chunk_max_bytes`, third `create_proxy_file` template-block drop fixed.

**Verification**: 6401 unit + 438 regression green; live-proxy integration (`test_proxy_local_litellm_e2e`,
`test_provider_trace_e2e` incl. cancelled-stream) pass; two adversarial review rounds (0 production defects; nits fixed
incl. 0600-owner assertion). Docs: design §7.x/§3.14, appendix §A.11, `proxy.md`, `cli_reference.md`.

### openrouter_observability Phases 3-5

**Goal**: Persist metadata-only, owner-only provider-trace records at the shared stream seam and give them a read
surface (answer "what happened to this OpenRouter request?" after a timeout), then close the loop upstream via opt-in
`user`-field injection.

**Key changes**: **P3** -- new `proxy/provider_trace_logger.py` plane (versioned, `0600` shards, strict-dacite read,
retention prune; modeled on the audit log); shared `record_provider_trace` at the one SSE seam gates
direct-OpenRouter-only and tracks four lifecycle flags (records `client_disconnected` on cancel); `ProviderTraceConfig`
nested into `ProxyConfig`/`ProxyInstanceConfig`. **P4** -- `core/ops/provider_trace.py` UI-agnostic `list/show/explain`
(explain is route-only/trace-derived, no credential read) behind `forge provider trace` + `%provider trace`, shared
plain-text renderer. **P5** -- opt-in `inject_openrouter_user` writes the Forge session grouping id into the OpenAI
`user` field on proxied direct-OpenRouter requests (top-level kwarg, verified channel); direct callers deferred to
`todo/openrouter_user_direct_callers/`.

**Verification**: full unit (6161->6191) + integration (393) green across phases; live-OpenRouter E2E proves a real
`gen-` id surfaces and a cancelled stream records `client_disconnected=True` / `local_usage_status="unavailable"`;
metadata-only regression (no body/prompt/completion). Docs: design §3.14, appendix §A.14.

### supervisor_statusline_health: surface frontier-supervisor fail-open

**Goal**: Make a silently-failing supervisor visible (incident: supervisor timed out 24/24, failed open to `allow` while
the status line still showed a healthy `SUP`) -- surface the fail-open the usage ledger already records, no new durable
state.

**Key changes**: `read_supervisor_health` over the ledger (newest-first contiguous error/timeout streak) via the
`forge_cost` throttle; status-line `SUP!N <kind>` suffix (YELLOW 1-2, RED `>=3`, byte-identical when 0);
`forge activity` gains generic `CommandUsage.error_kinds` + `format_failing_open` ("failing open: N timeout, N error")
and `--json` carries it. Scope: "failing open" is the supervisor formatter's read only; parse/auth fail-opens deferred
to `upstream_downstream_ledgers`.

**Verification**: 191 + 112 + Phase 3 cases green (`test_usage_summary.py`, `test_activity.py`); status-line suites
unchanged; `make pre-commit` clean. Read-only render -- no integration tier.

## 2026-06-15 (compacted)

- **openrouter_observability Phases 0-2 + review fixes** (detail in `done/openrouter_observability/`): live-probed the
  OpenRouter externals first (Phase 0 -- the `gen-` id is in `body.id`, the `x-generation-id` header, and every stream
  `chunk.id`; a stream cancelled after its first chunk is remote-absent, justifying a local-only trace; the direct path
  records the OpenAI-standard `user` but ignores a custom `session_id`, steering Phase 5 to inject under `user`). Phase
  1 minted Forge-owned provider session ids + two leak-gated `X-Forge-Session`/`X-Forge-Command` headers; Phase 2
  carried provider/generation id + allowlisted headers to the proxy boundary on an additive `ProviderTraceMeta`, kept
  separate from Forge's synthetic `chatcmpl-` id. Review fixes (R1-R3) closed the incident path: a cancelled stream
  emits `provider_meta` on the first content event (not only terminal usage), the LiteLLM Responses fallback keeps meta,
  and the direct non-streaming path populates headers via `with_raw_response`. Verification: +25 then +6 unit tests;
  full `make test-unit` green at each step; mypy/pyright/pre-commit clean.
- **supervisor_launch_controls** (detail in `done/supervisor_launch_controls/`): gave `fork/start --supervise` the
  tier-1 cascade knobs `policy supervise` had, and added per-caller `--effort` to every Forge-spawned `claude -p` (no
  global default). Two effort vocabularies kept distinct (`claude --effort` low/medium/high/xhigh/max via
  `core/effort.py`; core.llm `ReasoningEffort` none/low/medium/high/xhigh); `run_claude_session` appends `--effort` and
  fails loud on an older `claude`. Additive optional fields, no SCHEMA_VERSION bump. Verification: 906 unit + 2
  integration green; pre-commit clean.
- **same_dir_transfer_forks** (detail in `done/same_dir_transfer_forks/`): a same-dir fork with explicit
  `--strategy`/`--inline-plan` auto-switches to a curated `transfer` launch (gated on `resume_mode is None`) instead of
  silently dropping them; the worktree-transfer branch widened to
  `(is_worktree_fork and not native_relocate) or same_dir_transfer` rather than duplicating. Derivation writes the
  transfer baseline pre-refinement so a best-effort failure can't record a transfer fork as native. Verification: 41
  unit
  - 4 integration green; pre-commit clean.

## 2026-06-10 -- 2026-06-14 (compacted)

- **Codex frontend shipped as a first-class alternate runtime.** Phases 2-6 added the one-command Codex launch path
  (`forge session start/resume --runtime codex`), hook adapter/responder surfaces, SessionStart transfer delivery,
  interactive TUI support, codex-hooks installation/enrollment plumbing, capability/version guards, and review fixes
  around fork/rollback isolation, enrollment state, policy persistence, handoff artifacts, and invoker behavior. The
  closeout moved the card to done and recorded remaining empirical enrollment residuals.
- **Deferred Codex items remain tracked** (full detail in `done/codex_frontend/` and `done/runtime_abstraction/`):
  app-server transport (`codex app-server`/`--stdio`, unevaluated by scope decision), filing the upstream fail-open
  issue (draft ready), and the PermissionRequest/`trusted_hash` source-dive (documented-not-built).
- **Codex probe and enrollment evidence was preserved at the decision level.** Stages 84-87 covered cross-project trust,
  version churn, guided enrollment, and interactive reattach smoke paths. The durable outcome was that trust is scoped,
  `pretool_policy` is partial/enrollment-gated, SessionStart additional context is viable when enrolled, and some
  guided/operator steps remain intentionally external to non-interactive automation.
- **Supervisor/session work landed in parallel.** Supervisor cascade added tier-1 plan checks before the frontier
  supervisor; launch controls gained cascade/reasoning-effort parity across subprocesses; shadow sampling measured
  false-aligned cascade outcomes; same-dir transfer forks decoupled transfer mode from worktree isolation.
- **Verification highlights**: focused Codex runtime/hook/session suites, real-Codex E2E probes, supervisor cascade and
  shadow suites, same-dir transfer fork regressions, mypy/pyright, and `make pre-commit` were run across the compacted
  work. Detailed per-phase matrices remain in git history before this compaction.

## 2026-06-04 -- 2026-06-09 (compacted)

- **Codex/runtime_abstraction closeout.** Probe-only Codex frontend evaluation confirmed `codex exec` hooks do not fire
  headless in codex-cli 0.138.0, so SessionStart transfer delivery and headless policy hooks stay no-go while the bridge
  path stays initial-message based. Runtime/preflight capability fields now report `headless_inert`/`none`. Phase 5e
  shipped `bridge_session_to_codex` (parent -> ai-curated Codex transfer -> `codex exec`, one run tree) plus transfer
  curation usage attribution; Phase 5f synced design docs and added the end-user transfer guide. Codex headless runtime,
  preflight, stream parser, unavailable-cost usage, and target-runtime transfer threading shipped in the preceding
  phases.
- **Metric evidence and activity closeout.** Forge cost accounting moved to reported-or-unavailable figures, deleted the
  price catalog, removed strict preflight cap estimates, added reporter/confidence vocabulary, and kept spend caps
  post-event. `forge usage` became `forge activity`; `forge proxy costs reset` now clears telemetry/cap/status-line cost
  state; tombstones and stale migration shims were removed as clean breaks where appropriate.
- **Workspace/status-line hardening.** `project_root` resolution became git-common-dir-derived for linked worktrees,
  `--scope repo` became `--scope workspace`, session pre-seed lifecycle docs were aligned, and status-line producer /
  cap-load / weekly-quota regressions were fixed.
- **Reader and proxy safety fixes.** Cost/audit JSONL readers gained non-object guards; headless retry, parallel
  cleanup, negative-delta, and provenance edge cases from PR review were covered by regressions.
- **Verification highlights**: Codex probe harness stages and runtime/preflight suites green; bridge/transfer/codex
  suites and real-codex E2E green; metric/activity/status-line suites and `make pre-commit` clean. Detailed per-phase
  verification remains in git history before this compaction.

## 2026-06-03 (compacted)

- **runtime_abstraction Phase 4 follow-up**: `forge usage [session]` + session-end summary
  (`read_usage_events(session=)` filter, pure `build_session_activity_summary`; design §3.12/§3.14, appendix §A.13);
  sidecar usage-ledger mount (rw, proxy-id gated). Review fixes: workflow double-count (N-worker panel read as N+1)
  split into `CommandUsage.workers`; supervisor-warning misattribution. QA proxy bugs: accepts mid-conversation
  `{"role":"system"}`; passthrough streaming errors surface real status; QA refuses a stale-revision container.
- **Statusline Enhancement (Phases 1-5)**: config-driven status line — segment registry + lazy `RenderContext`;
  billing-aware cost (`api`→$ / `subscription`→quota / `ambiguous`→`≈$`); throttled file-backed `cache_hit`;
  Forge-unique opt-in segments (`supervisor`/`policy`/`audit`/`drift`); spend-cap proximity. Break: flat
  `show_rate_limits` → opt-in `rate_limits` segment. Golden no-op guard freezes default output.

## 2026-06-02 (compacted)

- **Phase 4 hardening (4a/4c/4d)**: `run_parallel` spawn/register TOCTOU fixed with a lock-guarded `cleanup_started`
  flag (children reaped exactly once; no Ctrl+C hang/orphan); typed `HeadlessResult.cancelled` (cancelled workers emit
  no error usage); `emit_direct_llm_usage` copies `cached_tokens`; both-or-neither `origin_run_id`/`origin_root_run_id`
  contract.
- **Phase 4 integration validation**: `test_policy_hooks.py` 10/10, `test_supervisor_e2e.py` 4/4, real-claude
  memory/workers green. Pre-existing: `test_real_shadow_curation_smoke` fails on a stale `--session` arg (PR #6
  ancestor; test-only, tracked).

## 2026-06-01 (compacted)

**runtime_abstraction Phase 4 (Slices 4a-4f)** — runtime-abstraction core:

- **4a run-tree env**: `RunIdentity` + `FORGE_RUN_ID`/`PARENT`/`ROOT`, orthogonal to `FORGE_DEPTH`; memory writer
  re-roots under the session's origin identity. appendix §F.5/§C.1.
- **4b usage ledger**: durable versioned `~/.forge/usage/events/` (third plane, joined by `request_id`; schema v1 strict
  reads, never-raising writer). design §3.14, appendix §A.13.
- **4c instrument paths**: `track_verb_cost` cost holder; emitters for workflow verbs + memory-writer/supervisor/shadow
  \+ action tagger; conservative `billing_mode` (no key-presence inference).
- **4d HeadlessInvoker**: new `core/invoker/` (`HeadlessRequest`/`Result`/`Attribution` + protocol +
  `ClaudeHeadlessInvoker`); review fan-out moved **verbatim** behind `run_parallel` (the seam is the lifecycle, not
  routing). design §5.5.5.
- **4e runtime registry**: frozen `RuntimeSpec` per runtime in `RUNTIMES` (the capability source Phase 5 reads);
  tri-state capability literals with version gates; `forge runtime list`. Nothing branches on it yet.
- **4f runtime-tagged ActionContext**: `ActionContext.runtime` required attribution (policy engine stays
  runtime-agnostic); Claude halves named behind `HookAdapter`/`HookResponder` protocols. design §4.1.4/§4.1.5.
- **Phase 3 native-relocate** (PASS on Claude 2.1.158): opt-in `forge session fork --resume-mode native-relocate` (host
  only; transfer stays default) with preflights + rollback + dir-scoped cleanup. Bug: `encode_project_path` now maps
  `_`→`-` (Claude 2.1.158 hyphenates underscores). Regression `test_bug_encode_project_path_underscore.py`. design §3.9.
  Deferred: `--rewrite-paths`, sidecar native-relocate, gated default flip.
- **Phase 2 optional audit proxy**: opt-in wire chokepoint (inert by default); orthogonal `wire_shape`
  (`openai_translated`|`anthropic_passthrough`) × `intercept.mode`; thinking-preserving passthrough;
  redact-before-persist audit JSONL (`forge proxy audit show|diff`); sidecar host-persistent mounts. design
  §7.x/§3.4/§3.7. Deferred: real-upstream `@slow` passthrough replay e2e.

## 2026-05-31

**runtime_abstraction Phase 1** — schema-backed curated transfer + `forge transfer` CLI:

- `transfer.py` `_build_ai_curated_output()` emits canonical sections 1-7 + User Notes overlay; `schema_version: 1`,
  `target_runtime` reserved for Phase 5; citations outside the seen turn range dropped so `schema: full` never
  overstates evidence. Three-file artifact model (`generated.md` cache, frozen `children/<child>.md`, `.notes.md`
  overlay). New `forge transfer show|regenerate|edit|diff`. design §3.9 reframes curated transfer as the primary
  cross-boundary substrate; appendix §M.
- Closeout decisions (keep-current): `--review` stays opt-in; `structured` stays the CLI default (`ai-curated` opt-in).
  `ctx` is prior art/inspiration only, never a dependency (appendix §M.4). Schema stable for Phase 5.

## 2026-05-22 — 2026-05-29 (compacted)

- **memory_substrate (PR #8)**: split "handoff" into the **memory writer** (Stop-time doc curation) and **transfer**
  (resume/fork context); renamed modules/CLI (`forge memory-writer run`, `forge memory report show`) with old paths
  tombstoned and durable accept-and-tolerate for `--resume-mode` / timeout keys.
- **Add Claude Opus 4.8** (opt-in; defaults stayed on 4.6 at the time), and **memory strategies 7→4** (`--as`→
  `--strategy`; shadow mode orthogonal via `--propose`; stale removed-strategy passports rejected).
- **Memory Enhancement (PR #1, Phases 0-5)**: passport-authoritative doc ownership (passports select docs, session
  activation decides whether the writer runs); `forge memory enable/track/untrack/list/status` + `shadows review`;
  removed `.forge/memory.yaml`, `MemoryIntent.designated_docs`, and the three-tier resolver. design §5.6, appendix §G;
  card archived to `done/memory_enhancement/`.
- **CLI hardening**: command-shape invariant (groups orient, leaves act), shared recovery-tip helpers (`cli/output.py`),
  template auto-start proxies, live-session deletion protection. Regressions added for each.
