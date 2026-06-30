# T7 execution checklist: subscription-exhaustion fail-open

**Lane**: `doing/` (member of `doing/epic_consumer_lanes/`). Branch `subscription_exhaustion_failopen`. Card: `card.md`.

## Current focus

**Awaiting plan review -- no `src/` changes yet.** A 2026-06-30 code sweep changed T7's premise: there is **no
structured exhaustion signal** (no headroom field, no HTTP rate-limit headers on the direct `codex exec` path), so
detection must classify an opaque codex error string whose real exhausted-subscription shape is **unrecorded**. Before
implementing, the reviewer needs to resolve **D1-D4** (card) -- above all **D1 (the signal)** and **D4 (supervisor-only
scope)**. **Phase 0 (signal capture) is a hard gate**: do not build the matcher on a guessed string.

## Decisions owed (resolve in review -- see card "Open decisions")

- [ ] **D1 -- Exhaustion signal.** How do we obtain the real spent-ChatGPT `codex exec` error shape (live-probe /
  documented evidence / conservative best-effort matcher)? Recommend a conservative matcher + a recorded fixture if
  obtainable; degrade only on a confident quota match. **Gate: if no reliable signal, defer/reshape T7.**
- [ ] **D2 -- Sticky vs per-invocation.** Recommend sticky (session-long, deterministic).
- [ ] **D3 -- Degrade-state home, shape, reset.** Recommend the existing `confirmed.policy.policy_states` generic dict
  (no new `PolicyConfirmed` field), a **dedicated** `policy_states["supervisor_lane"]` entry (not mixed with the
  supervisor's hash-keyed ThrottleCache), shape `{degraded, from_lane, to_lane, reason, at}`. **Reset:** `policy
  supervisor remove` + a lane re-pin must clear it (`clear_consumer_lane` does NOT touch policy state); per-session
  (re-tested on resume). NOT the write-once `consumer_lanes` binding.
- [ ] **D4 -- Scope = supervisor-only.** Recommend yes; shadow-curation message refinement is an optional follow-up.

## Phase 0 -- Exhaustion-signal capture/confirm (GATE, blocks Phase 1)

Resolve D1 with evidence, not a guess. **Do not proceed to Phase 1 on an unverified error string.**

- [ ] Capture or document the real exhausted-ChatGPT `codex exec` error event (status + `error.type` + message), or
  cite authoritative evidence of its shape.
- [ ] Record a fixture under `tests/fixtures/codex/` (e.g. `exec_json_quota_exhausted.jsonl`) mirroring the existing
  `exec_json_error.jsonl` shape, OR record explicitly that the shape is unverifiable and the matcher is best-effort.
- [ ] Define the conservative classifier predicate (the exact status/`error.type`/message allowlist) and its negative
  set (generic 4xx, transient/network, empty -> **not** exhausted).
- [ ] **Decision recorded**: signal is reliable enough to proceed, or T7 is deferred/reshaped (escalate to reviewer).

## Phase 1 -- Detection classifier + `failure_type` (after Phase 0 passes)

- [ ] Pure `is_subscription_exhausted(...)` classifier (input: the codex `CodexStreamResult`/`SessionResult` error
  fields). Conservative: True only on the Phase-0 quota markers; False on generic errors, transient/network, empty.
- [ ] New `failure_type="subscription_exhausted"` surfaced by `run_supervisor_check` (distinct from `subprocess_error`),
  set only when the failed run was on a `codex` lane AND the classifier matches. Claude-lane failures are never
  classified as exhaustion.
- [ ] Unit tests: classifier truth table (Phase-0 fixture + the negative set); `run_supervisor_check` surfaces the new
  `failure_type` only on a codex-lane quota failure.

## Phase 2 -- Sticky degrade (hook-owned, fail-open)

- [ ] Degrade-state in `confirmed.policy.policy_states["supervisor_lane"]` (generic dict, no new strict-dataclass
  field; D3). Shape `{degraded, from_lane, to_lane, reason, at}`.
- [ ] **Reset wiring**: clear the degrade marker on `policy supervisor remove` AND on a lane re-pin (`set --runtime` /
  `lane set`) -- `clear_consumer_lane` clears only the binding, so add explicit policy-state clearing. Confirm
  cross-resume (recommend per-session: cleared/re-tested on a fresh resume).
- [ ] **Write** (in `cli/hooks/policy.py`, under the existing freeze lock): when a check returns
  `failure_type="subscription_exhausted"` on a codex lane, persist the degrade marker. Best-effort (a lock/IO failure
  never blocks the hook), mirroring `persist_lane_freeze`.
- [ ] **Read** (top of the check, `cli/hooks/policy.py`): if the supervisor is degraded this session, inject
  `lane_record=None` (the default claude lane) into `run_supervisor_check` instead of the bound codex lane. The
  write-once `confirmed.consumer_lanes` binding is left untouched (stays observable in `lane show`).
- [ ] Fail-open throughout: a degrade-path error degrades the *check* to allow, never raises (design_workflows §1.2).
- [ ] Acceptance: sticky-degrade, enforces-on-claude-after-degrade, one-hop-only, fail-open (card table).

## Phase 3 -- Observability + docs

- [ ] One **upstream** operation outcome via `record_upstream_operation` (`command=supervisor`,
  `operation=policy.lane_degraded`, `reason_code=subscription_exhausted`, from/to lane in `message`), read by `forge
  telemetry activity` (Operation outcomes pane). NOT a `UsageEvent` (model-call/cost plane -- wrong shape).
  Self-contained, no T5 dependency.
- [ ] Surface "degraded this session" on a read surface (`forge session lane show` and/or `forge policy supervisor
  status`) so the operator can see the lane was routed around without editing the (still-frozen) binding.
- [ ] Design-doc sync: `design_workflows.md` §1.2 (name T7 as the one sanctioned fallback exception);
  `design_appendix.md` §G (consumer-lane layer: the degrade overlay vs the immutable binding); `design.md` §3.5/§3.6.2
  if the `confirmed.policy` ownership note needs it; `cli_reference.md` if a read surface changes. End-user
  `policy.md`/`session.md` if the degrade is user-visible.
- [ ] Epic roster: `epic_consumer_lanes/checklist.md` + `card.md` -> T7 done.

## Verification gate

- [ ] Focused suites green: `test_supervisor.py`, `test_policy_hooks.py`, the new classifier test, `test_consumer_lanes`
  / lane-resolution tests, usage emission test.
- [ ] `make pre-commit` clean.
- [ ] Integration note: a **real** codex exhaustion E2E is impractical (cannot spend a live subscription on demand), so
  coverage relies on the Phase-0 fixture + a synthesized exhaustion error driven through the supervisor/hook path. State
  this explicitly at closeout (mirrors how T0's real-billing path was probe-gated, not E2E-gated).

## Closeout

- [ ] Tick acceptance rows with verification recorded.
- [ ] `change_log.md` entry (Goal / Key changes / Verification).
- [ ] Move `doing/subscription_exhaustion_failopen/` -> `done/`; update epic roster; promote durable lessons to
  `impl_notes.md` after human review.
- [ ] **Epic closeout check**: with T7 the last live member, the epic itself can close to `done/` (board_contract
  "Epics") unless a T6c/team-supervisor follow-on keeps it coordinating.
