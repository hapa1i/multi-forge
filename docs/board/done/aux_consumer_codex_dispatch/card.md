# T6b -- Aux-consumer codex dispatch (first non-Claude runtime for aux work)

**Epic**: `docs/board/doing/epic_consumer_lanes/` (member T6b). Promoted from the
inline T6b sketch on 2026-06-30; branch `aux_consumer_codex_dispatch`.

**Depends on**: T6a (`done/aux_consumer_lane_placement/`) -- the lane binding, freeze, and billing machinery for the
three aux consumers already ships. **T6b adds the one thing T6a deliberately skipped: a real runtime-keyed `codex exec`
dispatch arm.** T6a was billing-only ("claude-max shares the `claude_code` runtime, so placement changes the billing
label, not dispatch"); T6b makes `--runtime codex` actually route an aux consumer to Codex.

**Proves** (epic row): a non-claude runtime for aux work -- generalizing T4's supervisor codex arm to a second consumer
shape.

---

## What T6b adds (vs what already exists)

| Layer                                                                        | State after T6a                                       | T6b                                                                                          |
| ---------------------------------------------------------------------------- | ----------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| Consumer `allowed_lanes`                                                     | claude-max only (no codex lane)                       | **add** `Lane(codex, chatgpt, gpt-5-codex)` to the chosen consumer(s)                        |
| Lane binding / freeze (`persist_lane_freeze`, `on_dispatch`, equality guard) | done                                                  | reused unchanged                                                                             |
| Billing label (`read_bound_backend_id` -> `subscription_quota`)              | done                                                  | reused unchanged                                                                             |
| `forge session lane set --consumer X --runtime codex`                        | raises `LaneError` (codex not allowed)                | resolves once the allowed_lane exists (no CLI code change)                                   |
| **Runtime-keyed dispatch** at the dispatch call site                         | absent (unconditional `claude -p`)                    | **add** -- thread the bound `LaneRecord`, validate via `resolve_lane`, branch on its runtime |
| **`_dispatch_codex_<consumer>` arm**                                         | absent                                                | **add** -- mirror `_dispatch_codex_supervisor`                                               |
| Single usage emitter per path                                                | claude path emits via `emit_usage_for_session_result` | codex path emits via the invoker's `emit_codex_usage`; must not double-emit                  |

The lane *contract* already spans four consumers (T6a). T6b proves the *dispatch* generalizes past the supervisor.

## Research finding (corrects the epic sketch): the three aux consumers are NOT uniform

The epic T6b row lists memory-writer / shadow-curation / team-supervisor as one homogeneous "mirror T4." A 2026-06-30
code sweep contradicts that -- only shadow-curation is a clean mirror; the other two need real adaptation:

| Consumer                                               | Output shape                                                                          | Sandbox need                                             | Context source                                                                          | Current degrade                                                 | Codex fit                                                                                                       |
| ------------------------------------------------------ | ------------------------------------------------------------------------------------- | -------------------------------------------------------- | --------------------------------------------------------------------------------------- | --------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| **shadow-curation** (`session/shadow_curation.py:315`) | stdout markdown report (no parse; `result.stdout` IS the deliverable)                 | **read-only**                                            | **blind** -- official + shadow content inlined in the prompt                            | empty `CurationResult` -> CLI exits 1 (fail-loud, user-invoked) | **clean mirror-T4**                                                                                             |
| **team-supervisor** (`policy/team/handlers.py:267`)    | JSON verdict (`extract_json_from_response`)                                           | read-only                                                | **`resume_id` only** -- no `plan_override_path`/snapshot field (`team/config.py:11-30`) | `(0, "")` allow (fail-open, policy-hook)                        | **partial** -- codex has no claude-resume, so a codex arm is plan-blind unless plan-snapshot machinery is added |
| **memory-writer** (`session/memory_writer.py:534`)     | `augment`: in-place doc edits via Write tool (no parse); `review-only`: stdout report | **`augment` = workspace-write**; review-only = read-only | transcript-fed (absolute `.forge/artifacts/.../transcript.jsonl` path in prompt)        | log + telemetry + return `False` (best-effort async)            | **different shape** -- file-editing, workspace-write, Claude-specific permission-deny stdout scan               |

Verified template (the arm to mirror): `_dispatch_codex_supervisor` (`policy/semantic/supervisor.py:609-681`) and the
runtime-keyed seam `_dispatch_supervisor` (`:484-528`); fail-open via `_SupervisorRoutingError` (`:470-481`); cached
preflight `read_fresh_codex_preflight` (`core/runtime/codex_preflight_cache.py:125-172`); usage via the invoker's
`emit_codex_usage` with `Attribution.operation=None` to suppress a duplicate upstream row
(`core/invoker/codex.py:215-249`).

## Scope recommendation (resolved: shadow-curation only -- see checklist)

A staged scope keeps the routing-seam change clean and separates it from a context-model rewrite and a trust-posture
change:

- **T6b core (recommended): shadow-curation only.** The true mirror-T4 consumer: blind, read-only, stdout-is-output. The
  codex arm is a near-verbatim copy of `_dispatch_codex_supervisor` with `sandbox="read-only"` (no writes; reads are
  permitted but not required -- content is inlined). This is a complete vertical slice -- allowed_lane + dispatch branch
  \+ codex arm + per-consumer degrade + single-emitter usage + observability + CLI accepts `--runtime codex` -- proving
  the epic's "non-claude runtime for aux work" at the lowest risk.
- **team-supervisor: include only if we accept the plan-snapshot work.** Going blind for codex means sourcing the
  approved plan into the prompt (it currently rides `resume_id`). That is really a team-supervisor *context-model*
  change (port the semantic supervisor's `plan_override_path` + `--reload` machinery), somewhat orthogonal to the lane
  seam. Default recommendation: **defer** to a focused follow-on unless the reviewer wants it folded in.
- **memory-writer: defer to T6c.** `workspace-write` Codex editing the user's repo, transcript-feeding, and
  Claude-specific result detection make it a different shape *and* a safety-posture change. Folding it in would mix a
  trust decision with a routing-seam decision. This mirrors the epic's own "fan-out workers + taggers are different
  shapes, later" treatment.

## Per-consumer degrade contract (the codex arm must map into THIS, not the supervisor's)

"Fail-open (mirrors T4)" is per-consumer, not uniform. The supervisor degrades to a `PolicyDecision(allow)` via
`_SupervisorRoutingError`; the aux consumers each have their own path:

- **shadow-curation** (user-invoked): a cold/stale preflight or codex failure should **fail loud to the user** ("Codex
  not ready; run `forge runtime preflight codex`" / curation failed, exit 1) -- NOT silently fall back to claude (the
  user explicitly bound codex; "no fallback" is the epic rule, T7 is the only exception).
- **team-supervisor** (policy-hook): degrade to `(0, "")` allow, matching its existing fail-open.
- **memory-writer** (best-effort async, T6c): degrade to `return False` + telemetry, matching its existing path.

A codex-arm failure (cold cache, setup error) must therefore be caught at the consumer boundary and mapped into that
consumer's existing degrade, not raised as a supervisor routing error.

## Risks / open questions

- **Preflight is a user precondition.** The codex arm needs a fresh cached `CodexPreflight` (ChatGPT login +
  `forge runtime preflight codex`). For a user-invoked consumer (shadow-curation) a cold cache should error with the
  setup hint, not silently no-op. Acceptance must cover cold/stale cache.
- **Single usage emitter.** The claude path emits `emit_usage_for_session_result`; the codex invoker auto-emits
  `emit_codex_usage`. The dispatch branch must pick exactly one per path (no double-count) -- mirror the supervisor's
  `track_verb_cost`/single-emit discipline and the `operation` handling for upstream rows.
- **Threading the runtime.** T6a threads `backend_id` + `dispatched_lane` (for the freeze closure) into the CLI call
  sites, but the dispatch functions (`run_shadow_curation`, etc.) receive only `backend_id` + `on_dispatch`, not the
  runtime. T6b must thread the resolved `Lane`/`runtime_id` down to the branch point.
- **Billing honesty unchanged.** codex + `chatgpt` backend -> `subscription_quota` via `emit_codex_usage`'s preflight
  read; no new inference. Confirm the codex run lands `billing_mode=subscription_quota` in `forge telemetry activity`.
- **Model is nominal.** As in T4, only `runtime_id` selects the arm; `backend_id`/`model` on the lane are nominal (codex
  picks its own model). Keep `gpt-5-codex` for parity with the supervisor lane.

## Out of scope

Memory-writer codex dispatch (-> T6c); team-supervisor plan-snapshot machinery (decision owed; likely its own slice);
fan-out workers + taggers (epic "different shapes, later"); any Codex hooks / policy enforcement (T6b is headless,
blind/inlined, read-only -- the same scope guard as T4); mid-session failover (T7).
