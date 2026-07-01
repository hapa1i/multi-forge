# T7 -- Subscription-exhaustion fail-open (degrade a spent subscription lane to its default)

**Epic**: `docs/board/doing/epic_consumer_lanes/` -- read the epic for the lane contract and the **"No fallback
(de-scoped)"** decision this card carves the single, deliberate exception into.

**Lane**: `done/` -- shipped via PR #61 (`96e342b1`, merged to `main` 2026-06-30); branch
`subscription_exhaustion_failopen`. Depends on T4 (done, supervisor codex lane) and T6b (done, shadow-curation codex
lane). **All phases shipped and closed out (reviewer confirmed GO 2026-06-30)** -- a 2026-06-30 code sweep changed this
card's premise (no `status`/`error.type` survives the `codex exec` boundary; see Research), reshaping detection to a
Codex JSONL `message` classifier. All decisions resolved (D1-D4); Phase 1 (detection), Phase 2 (sticky degrade), and
Phase 3 (observability + docs) all shipped and verified.

**Proves**: the epic's own **"Why now"** scenario (a Claude Max 20x user hits the weekly quota wall) is actually
*handled*, not merely *motivating* -- closing the loop the epic deliberately deferred.

---

## Problem

The epic's motivation is the quota wall: aux `claude -p` work burns subscription quota; placing a consumer on a
`codex`/`chatgpt` subscription lane rides a subscription instead. But a subscription is finite. Spent mid-session, a
frozen codex lane has nowhere to go. The epic de-scoped this ("No fallback (de-scoped)"; "Out of scope: mid-session
failover"). T7 lifts only the *narrow, one-hop* version.

**The concrete harm is specific to the supervisor and is already live.** The semantic supervisor fires on every
Write/Edit. When its bound codex lane is spent, every subsequent check fails the codex run, and the supervisor's
fail-open contract degrades each one to "aligned" (`failure_type="subprocess_error"`, design_workflows §1.2). The result
is **silent loss of enforcement for the rest of the session**: the supervisor stays configured while every check
degrades to allow. It is *observable* on secondary surfaces -- the opt-in (default-off) `supervisor` status-line health
suffix would show `SUP!N error`, and `forge telemetry activity` records the fail-opens -- but it is not *enforced*, and
easy to miss unless the user has those surfaces enabled and is watching. T7 makes the system **self-heal**: subscription
spent -> degrade to the default `claude -p` lane -> real enforcement resumes, instead of merely surfacing the failure.

## Research (2026-06-30 code sweep -- corrects the original proposal)

The original proposal floated two detection signals. Both are infeasible as written; a third path is the only option.

| Original signal idea                                      | Finding                                                                                                                                                                                                                               | Verdict                          |
| --------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------- |
| (a) `codex_preflight` exposes `chatgpt_tokens` exhaustion | `CodexPreflight` carries `billing_mode`/`auth_method` only -- it proves a subscription *exists* (`subscription_quota`), never *how much remains* (`codex_preflight.py:122-146`, `:401-403`)                                           | **Not available**                |
| (b) read provider rate-limit headers                      | The codex supervisor lane runs **direct** `codex exec` (a subprocess, stdout-JSONL only); there are **no HTTP response headers** to read. Rate-limit/`retry-after` handling exists only on the *proxy* path, which this lane bypasses | **Infeasible for direct codex**  |
| (c) classify the codex failure post-hoc                   | The only observable: a codex `error`/`turn.failed` event sets `CodexStreamResult.is_error=True` + an opaque `error_message` string (`codex_stream.py:106-109`), surfaced as `HeadlessResult.runtime_is_error`/`stderr`                | **The only path -- but brittle** |

**So T7 detection is post-hoc failure classification, not a headroom read** -- which happens to match the card's own "no
headroom pre-emptive routing" non-goal. Three load-bearing facts shape the design:

- **The exec error is a `message` string only -- and the exhausted-subscription form is human prose, not parseable JSON
  (Phase 0, verified -- corrects the original premise).** Against `openai/codex` source (`main` @ `db887d0`, 2026-06-30;
  runtime is tag `rust-v0.137.0`): the `exec --json` error event is `ThreadErrorEvent { message: String }`
  (`exec/src/exec_events.rs`) -- the internal structured discriminator
  (`ErrorEvent.codex_error_info = usage_limit_exceeded`) and the HTTP status are **dropped at the exec boundary**
  (`http_status_code_value()` is `None` for this variant). A spent ChatGPT subscription is
  `CodexErr::UsageLimitReached`, whose `#[error("{0}")]` `Display` (`protocol/src/error.rs:116,432`) is human text
  (`"You've hit your usage limit. ..."`) with **no `status`/`error.type`**. So the original "`429` + `error.type`"
  premise does **not** hold on this path. The generic `400` fixture *does* carry a stringified-JSON envelope (codex did
  not type it -- the raw-leak path), so the classifier must handle **both** shapes. Recorded:
  `tests/fixtures/codex/exec_json_quota_exhausted.jsonl` (source-derived; see that dir's README). **This resolves D1.**
- **The binding is write-once immutable.** `confirmed.consumer_lanes.<consumer>` freezes the chosen lane write-if-absent
  (`consumer_lanes.py:192-230`, T1b). A "sticky degrade" **cannot rewrite the binding.** The bound codex lane stays
  frozen and observable (`forge session lane show`); the degrade is a **separate overlay** the lane-resolution step
  consults and routes around.
- **The hook owns store I/O; the semantic module is store-free.** `cli/hooks/policy.py` reads `read_bound_lane(...)` and
  *injects* the `LaneRecord` into `run_supervisor_check` (`policy.py:189-191`, `supervisor.py:744`); the supervisor
  never touches the store. So T7's degrade **read** (force the default lane) and **write** (persist the sticky marker)
  both live in the hook, threaded through the existing lane injection. `run_supervisor_check` only needs to *surface*
  that a failure was an exhaustion (a new `failure_type`).

## Scope (sharpened by research): the supervisor, not all codex consumers

Sticky-session degrade is meaningful only for a **repeated-dispatch** consumer. The two codex consumers diverge:

| Consumer                  | Dispatch cadence                     | On exhaustion today                           | Sticky-degrade fit                                                                 |
| ------------------------- | ------------------------------------ | --------------------------------------------- | ---------------------------------------------------------------------------------- |
| **supervisor** (T4)       | every Write/Edit (repeated)          | silent per-check fail-open -> no enforcement  | **the fit** -- degrade once, sticky for the session, enforcement resumes on claude |
| **shadow-curation** (T6b) | one-shot `forge memory ... --curate` | fails loud with a hint, exit 1 (user re-runs) | **does not apply** -- no "rest of the session" across a single CLI invocation      |

**T7 core = the supervisor.** Shadow-curation's one-shot fail-loud path already does the right thing; "degrade once,
sticky" has no meaning for a single command. At most it could get a *message refinement* (its existing hint reads
"subscription spent: re-pin the lane or top up" instead of a generic codex error) -- a small, separable nicety, **not**
the sticky machinery. Recommend: out of T7 core; optional tiny follow-up.

## Goal

When the supervisor's bound **codex/chatgpt subscription** lane returns a quota-exhaustion failure, degrade **once** to
its **default `claude -p` lane**, **sticky for the rest of the session**, fail-open. Restores real enforcement instead
of silent per-check fail-open. **One hop only** (codex -> default; no chains, no arbitrary cheaper-model re-route).

## Open decisions (resolve in review)

- **D1 -- Exhaustion signal. RESOLVED -> GO (reviewer confirmed 2026-06-30).** Framing: **no HTTP `status`/`error.type`
  survives the Forge `codex exec` path; classify Codex runtime JSONL error _messages_.** This is **not** a structured
  signal at Forge's boundary -- it is a usable Codex JSONL `message` signal. (Codex maps `UsageLimitReached` /
  `QuotaExceeded` / `UsageNotIncluded` -> `UsageLimitExceeded` internally, but `exec`'s exported `ThreadErrorEvent`
  carries only `message`, so the discriminator is gone by the JSONL surface. Forge already reduces that same boundary:
  `codex_stream.py:106` (`_ERROR_EVENTS` -> `error_message`) -> `codex.py:91` (surfaces the reason on `stderr`) ->
  `supervisor.py:700` (folds it into `SessionResult.error` **only on the exit-0 runtime-error path** -- a realistic
  failed turn exits non-zero, leaving the reason on `stderr` with `error=None`, so the classifier reads
  `result.error or result.stderr`).) **Matcher (conservative allowlist)** -- exhausted iff the codex error string,
  casefolded, contains an anchor: `hit your usage limit` (invariant across every `UsageLimitReached` plan branch),
  `out of credits` (workspace credits depleted), `spend cap` (workspace usage limit), `quota exceeded. check your plan`
  (`QuotaExceeded`), or `to use codex with your chatgpt plan, upgrade to plus` (`UsageNotIncluded`); **or** the message
  parses as JSON with nested `error.type in {usage_limit_reached, insufficient_quota}` (the raw-leak path). **Negative
  set (no degrade):** `rate_limit_exceeded`/`rate_limit_reached` (transient per-minute RPM -- deliberately **excluded**
  so a momentary throttle never trips a sticky session-long degrade), `selected model is at capacity`
  (`ServerOverloaded`), `we're currently experiencing high demand` (`InternalServerError`),
  `invalid_request_error`/model-not-supported (the `400` fixture), connection/timeout/stream, bare `turn failed`,
  empty/unparseable. **Guardrails (reviewer):** gate on Codex runtime errors only -- `lane.runtime_id == "codex"`
  **and** `result.runtime_is_error` -- so a claude-lane or subprocess/setup failure is never read as exhaustion; surface
  `failure_type="subscription_exhausted"` from the supervisor failure path for Phase 2 to consume. **Why GO is safe:**
  the conservative bias degrades the *check* to allow (normal fail-open) on anything unrecognized, and only a confident
  match trips the Phase-2 *lane* degrade.
- **D2 -- Sticky. RESOLVED (reviewer 2026-06-30).** Per-invocation re-check recreates the harm (every Write/Edit burns a
  doomed codex attempt, then fail-opens again); sticky gives one fail-open, then real enforcement on the default claude
  lane for the rest of the session.
- **D3 -- Degrade-state home/shape/reset. RESOLVED + tightened (reviewer 2026-06-30; seams verified).** Home:
  `confirmed.policy.policy_states` (`models.py:363`) -- **no new `PolicyConfirmed` field**. `build_policy_state_update`
  MERGES (`store.py:114`: `dict(existing); .update(engine_state)`) and `engine_state` is keyed by policy_id (only
  `semantic.supervisor` exists), so a non-policy-id key is never clobbered. **Key:** dedicated overlay
  `forge.supervisor_lane_degrade` (the `forge.` prefix marks it as an overlay, not a policy id). **Shape:**
  `{degraded, from_lane, to_lane, reason, at}` -- `from_lane`/`to_lane` are full lane dicts **for audit/display only**;
  route by injecting `lane_record=None` (do NOT trust the stored `to_lane` for dispatch). **Reset follows the *binding*,
  not the command name:** clear on `policy supervisor remove` / `%policy supervisor remove` (`clear_consumer_lane`,
  tears down confirmed) and on a re-pin via `policy supervisor set --runtime/--backend` /
  `session lane set --consumer supervisor` (`set_intent_lane`; a same-lane re-pin is the only one that succeeds when
  frozen -> the "topped up, retry codex" signal); **do NOT** clear on `session lane clear --consumer supervisor`
  (`clear_intent_lane` leaves the frozen confirmed binding, so codex still dispatches). Write with the
  `persist_lane_freeze` stale-write guard (under-lock `read_bound_lane == dispatched_lane`). Per-session (clear at
  resume). Full seam map: checklist Phase 2. **Not** the write-once `confirmed.consumer_lanes` binding.
- **D4 -- Scope = supervisor-only. RESOLVED** (see Scope). Shadow-curation message refinement is an optional separable
  follow-up, not T7 core.

## Acceptance (definition of done -- fixture-grounded)

| Test                                 | Fixture                                              | Assertion                                                                                                                                                                                                                                          | Test File                                      |
| ------------------------------------ | ---------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------- |
| classifier: quota error -> degrade   | the Phase-0 exhaustion error (recorded/synthesized)  | `is_subscription_exhausted(...)` True on the quota shape, False on a generic 400/model error and on transient/empty errors                                                                                                                         | classifier unit test                           |
| exhausted supervisor degrades sticky | codex lane bound + a quota-exhaustion codex failure  | a degrade marker is written to `confirmed.policy.policy_states["forge.supervisor_lane_degrade"]`; the **next** check resolves to the default claude lane                                                                                           | `tests/src/cli/test_policy_hooks.py`           |
| degraded supervisor enforces         | after degrade, a divergent action                    | the next check dispatches `claude_code` and produces a **real** verdict, not a fail-open                                                                                                                                                           | `tests/src/policy/semantic/test_supervisor.py` |
| one degradation event                | exhaustion                                           | exactly one **upstream** outcome via `record_upstream_operation` (`command=supervisor`, `operation=policy.lane_degraded`, `reason_code=subscription_exhausted`, from/to lane in `message`); read by `forge telemetry activity`, NOT a `UsageEvent` | `test_supervisor.py` / upstream test           |
| fail-open preserved                  | exhaustion mid-hook                                  | the policy hook never crashes; degrades, never raises                                                                                                                                                                                              | `test_policy_hooks.py`                         |
| one hop only                         | default claude lane also failing                     | no chain; stays on the default (no second failover)                                                                                                                                                                                                | `test_supervisor.py`                           |
| healthy subscription unchanged       | non-exhausted codex run                              | no degrade; byte-identical to T4                                                                                                                                                                                                                   | `test_supervisor.py`                           |
| non-quota codex failure no degrade   | a generic codex error (e.g. model-not-supported 400) | no degrade marker; normal fail-open; the codex lane stays bound                                                                                                                                                                                    | `test_supervisor.py` / classifier unit         |

## Non-goals

- **Not general mid-session failover or capacity forecasting** (epic "Out of scope").
- **Not headroom-based pre-emptive routing** (do not route by remaining quota before exhaustion -- that is dynamic
  routing, which the epic rejects).
- **One hop only**: subscription -> default, no chains, no arbitrary cheaper-model re-route.
- **Shadow-curation sticky degrade** (one-shot consumer; out of T7 core -- optional message refinement only).
- Stays **the single exception** to the epic's "no general fallback".

## Depends on / relates to

- **T4** (done) -- the supervisor codex lane that can be exhausted.
- **T6b** (done) -- the second codex consumer; informs the scope decision (one-shot vs repeated).
- **T5** (done) -- benefits from richer read surfaces over the minimal degradation event T7 emits.
- **T0/claude-max** -- a future `claude-max` subscription would extend the same *idea*, but its exhaustion signal is
  different (Anthropic rate-limit on the `claude_code` runtime, not a codex error event), so it is a **separate
  detection seam**, not a reuse of T7's codex classifier.
