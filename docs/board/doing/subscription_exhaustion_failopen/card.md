# T7 -- Subscription-exhaustion fail-open (degrade a spent subscription lane to its default)

**Epic**: `docs/board/doing/epic_consumer_lanes/` -- read the epic for the lane contract and the **"No fallback
(de-scoped)"** decision this card carves the single, deliberate exception into.

**Lane**: `doing/` -- promoted from `proposed/` on 2026-06-30; branch `subscription_exhaustion_failopen`. Depends on T4
(done, supervisor codex lane) and T6b (done, shadow-curation codex lane). **Awaiting plan review before
implementation** -- a 2026-06-30 code sweep materially changed this card's premise (no structured exhaustion signal
exists; see Research), so the scope and the Phase 0 gate below need reviewer sign-off first.

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
is **silent loss of enforcement for the rest of the session**: the supervisor stays configured while every check degrades
to allow. It is *observable* on secondary surfaces -- the opt-in (default-off) `supervisor` status-line health suffix
would show `SUP!N error`, and `forge telemetry activity` records the fail-opens -- but it is not *enforced*, and easy to
miss unless the user has those surfaces enabled and is watching. T7 makes the system **self-heal**: subscription spent ->
degrade to the default `claude -p` lane -> real enforcement resumes, instead of merely surfacing the failure.

## Research (2026-06-30 code sweep -- corrects the original proposal)

The original proposal floated two detection signals. Both are infeasible as written; a third path is the only option.

| Original signal idea                              | Finding                                                                                                                                                                                                                | Verdict                          |
| ------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------- |
| (a) `codex_preflight` exposes `chatgpt_tokens` exhaustion | `CodexPreflight` carries `billing_mode`/`auth_method` only -- it proves a subscription *exists* (`subscription_quota`), never *how much remains* (`codex_preflight.py:122-146`, `:401-403`)                            | **Not available**                |
| (b) read provider rate-limit headers              | The codex supervisor lane runs **direct** `codex exec` (a subprocess, stdout-JSONL only); there are **no HTTP response headers** to read. Rate-limit/`retry-after` handling exists only on the *proxy* path, which this lane bypasses | **Infeasible for direct codex**  |
| (c) classify the codex failure post-hoc           | The only observable: a codex `error`/`turn.failed` event sets `CodexStreamResult.is_error=True` + an opaque `error_message` string (`codex_stream.py:106-109`), surfaced as `HeadlessResult.runtime_is_error`/`stderr` | **The only path -- but brittle** |

**So T7 detection is post-hoc failure classification, not a headroom read** -- which happens to match the card's own
"no headroom pre-emptive routing" non-goal. Three load-bearing facts shape the design:

- **The error arrives as structured-ish JSON, but the exhausted-subscription shape is unrecorded.** The one recorded
  error fixture (`tests/fixtures/codex/exec_json_error.jsonl`) shows codex surfaces errors as a `message` that is itself
  a stringified JSON envelope carrying `status` + nested `error.type` (there: a `400` `invalid_request_error`). A spent
  ChatGPT subscription is *likely* a `429` with an `error.type` like `rate_limit_exceeded`/`usage_limit_reached`/
  `insufficient_quota` -- more parseable than free text -- **but no fixture or probe captures the real shape.** Building a
  matcher on a guessed string is the central risk. **Phase 0 must capture or document it first.**
- **The binding is write-once immutable.** `confirmed.consumer_lanes.<consumer>` freezes the chosen lane write-if-absent
  (`consumer_lanes.py:192-230`, T1b). A "sticky degrade" **cannot rewrite the binding.** The bound codex lane stays
  frozen and observable (`forge session lane show`); the degrade is a **separate overlay** the lane-resolution step
  consults and routes around.
- **The hook owns store I/O; the semantic module is store-free.** `cli/hooks/policy.py` reads `read_bound_lane(...)` and
  *injects* the `LaneRecord` into `run_supervisor_check` (`policy.py:189-191`, `supervisor.py:744`); the supervisor never
  touches the store. So T7's degrade **read** (force the default lane) and **write** (persist the sticky marker) both
  live in the hook, threaded through the existing lane injection. `run_supervisor_check` only needs to *surface* that a
  failure was an exhaustion (a new `failure_type`).

## Scope (sharpened by research): the supervisor, not all codex consumers

Sticky-session degrade is meaningful only for a **repeated-dispatch** consumer. The two codex consumers diverge:

| Consumer                  | Dispatch cadence                  | On exhaustion today                                 | Sticky-degrade fit                                                                |
| ------------------------- | --------------------------------- | --------------------------------------------------- | --------------------------------------------------------------------------------- |
| **supervisor** (T4)       | every Write/Edit (repeated)       | silent per-check fail-open -> no enforcement        | **the fit** -- degrade once, sticky for the session, enforcement resumes on claude |
| **shadow-curation** (T6b) | one-shot `forge memory ... --curate` | fails loud with a hint, exit 1 (user re-runs)       | **does not apply** -- no "rest of the session" across a single CLI invocation       |

**T7 core = the supervisor.** Shadow-curation's one-shot fail-loud path already does the right thing; "degrade once,
sticky" has no meaning for a single command. At most it could get a *message refinement* (its existing hint reads
"subscription spent: re-pin the lane or top up" instead of a generic codex error) -- a small, separable nicety, **not**
the sticky machinery. Recommend: out of T7 core; optional tiny follow-up.

## Goal

When the supervisor's bound **codex/chatgpt subscription** lane returns a quota-exhaustion failure, degrade **once** to
its **default `claude -p` lane**, **sticky for the rest of the session**, fail-open. Restores real enforcement instead of
silent per-check fail-open. **One hop only** (codex -> default; no chains, no arbitrary cheaper-model re-route).

## Open decisions (resolve in review)

- **D1 -- Exhaustion signal (Phase 0 gate, the crux).** No fixture/probe records the real spent-ChatGPT `codex exec`
  error. Options: (a) live-probe a spent subscription [costly/impractical to spend a real quota on demand]; (b) find
  documented/community evidence of the exact status/`error.type`; (c) ship a **conservative** matcher (degrade only on a
  *confident* quota match -- e.g. `status==429` AND `error.type in {rate_limit_exceeded, usage_limit_reached,
  insufficient_quota}`, or a tight message-substring allowlist -- and treat anything unrecognized as a normal fail-open,
  **no degrade**). *Recommend (b)+(c): a conservative matcher + a recorded fixture if obtainable; degrade only on a
  confident match so a transient network blip never trips a sticky session-long degrade.* **If no reliable signal is
  reachable, T7 should be deferred/reshaped rather than ship a guessed matcher.**
- **D2 -- Sticky vs per-invocation re-check.** *Recommend sticky* (frozen-lane philosophy: exhaust once -> claude for the
  rest of the session, deterministic). The original proposal agrees.
- **D3 -- Degrade-state home, shape, and reset (tightened per review).** Store the sticky marker in the existing
  **`confirmed.policy.policy_states`** generic per-policy dict (`PolicyConfirmed.policy_states: dict[str, dict[str,
  Any]]`, `models.py:363`) -- **no new `PolicyConfirmed` field**, so the strict dataclass schema is untouched. Use a
  **dedicated** entry (e.g. `policy_states["supervisor_lane"] = {degraded, from_lane, to_lane, reason, at}`) rather than
  nesting inside `policy_states["semantic.supervisor"]`, which the supervisor's hash-keyed `ThrottleCache` already owns
  (verify the engine's `build_policy_state_update` merge preserves a non-`policy_id` key). **Reset (the gap the review
  caught):** `clear_consumer_lane` (`consumer_lanes.py:162`) clears only the lane binding, **not** policy state, so
  `policy supervisor remove` and a lane **re-pin** (`set --runtime` / `lane set`) must *also* clear this marker, or a
  stale degrade survives a reconfigure. **Cross-resume:** recommend **per-session** (re-tested on a fresh resume, since a
  weekly quota may have refilled) -- clear at session start or expire via `at`; confirm in review. **Not** the write-once
  `confirmed.consumer_lanes` binding (a generic home for a future T6c codex consumer would be a separate `.degraded`
  overlay, out of supervisor-only T7's scope).
- **D4 -- Scope = supervisor-only?** *Recommend yes* (see Scope). Shadow-curation message refinement is an optional
  separable follow-up, not T7 core.

## Acceptance (definition of done -- fixture-grounded)

| Test                                | Fixture                                                        | Assertion                                                                                          | Test File                                       |
| ----------------------------------- | ------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- | ----------------------------------------------- |
| classifier: quota error -> degrade  | the Phase-0 exhaustion error (recorded/synthesized)           | `is_subscription_exhausted(...)` True on the quota shape, False on a generic 400/model error and on transient/empty errors | classifier unit test                            |
| exhausted supervisor degrades sticky | codex lane bound + a quota-exhaustion codex failure           | a degrade marker is written to `confirmed.policy.policy_states["supervisor_lane"]`; the **next** check resolves to the default claude lane | `tests/src/cli/test_policy_hooks.py`            |
| degraded supervisor enforces        | after degrade, a divergent action                             | the next check dispatches `claude_code` and produces a **real** verdict, not a fail-open           | `tests/src/policy/semantic/test_supervisor.py`  |
| one degradation event               | exhaustion                                                    | exactly one **upstream** outcome via `record_upstream_operation` (`command=supervisor`, `operation=policy.lane_degraded`, `reason_code=subscription_exhausted`, from/to lane in `message`); read by `forge telemetry activity`, NOT a `UsageEvent` | `test_supervisor.py` / upstream test               |
| fail-open preserved                 | exhaustion mid-hook                                           | the policy hook never crashes; degrades, never raises                                             | `test_policy_hooks.py`                          |
| one hop only                        | default claude lane also failing                              | no chain; stays on the default (no second failover)                                               | `test_supervisor.py`                            |
| healthy subscription unchanged      | non-exhausted codex run                                       | no degrade; byte-identical to T4                                                                   | `test_supervisor.py`                            |
| non-quota codex failure no degrade  | a generic codex error (e.g. model-not-supported 400)         | no degrade marker; normal fail-open; the codex lane stays bound                                    | `test_supervisor.py` / classifier unit          |

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
  different (Anthropic rate-limit on the `claude_code` runtime, not a codex error event), so it is a **separate detection
  seam**, not a reuse of T7's codex classifier.
