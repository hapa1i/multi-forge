# T7 execution checklist: subscription-exhaustion fail-open

**Lane**: `doing/` (member of `doing/epic_consumer_lanes/`). Branch `subscription_exhaustion_failopen`. Card: `card.md`.

## Current focus

**Phase 1 complete (reviewer confirmed GO 2026-06-30); Phase 2 (sticky degrade) is next.** Phase 0 settled **D1** from
`openai/codex` source: no `status`/`error.type` survives the `codex exec` boundary (the structured discriminator is
dropped), so detection classifies the Codex JSONL `message` via a conservative source-literal allowlist (anchor:
`hit your usage limit`) + a stringified-JSON fallback. Phase 1 shipped the `is_subscription_exhausted` classifier
(`codex_stream.py`) and a `failure_type="subscription_exhausted"` rung in `run_supervisor_check`, gated on
`lane.runtime_id == "codex" and result.runtime_is_error` (G1) -- behavior-neutral relabel, still fail-open, for Phase 2
to consume (G3). **All decisions resolved (D1-D4, reviewer 2026-06-30): D2 = sticky, D3 = `policy_states` overlay +
binding-follows reset map (Phase 2), D4 = supervisor-only.** Phase 2 (sticky degrade) is ready to implement.

## Decisions owed (resolve in review -- see card "Open decisions")

- [x] **D1 -- Exhaustion signal. RESOLVED -> GO (reviewer confirmed 2026-06-30).** The real shape is documented from
  `openai/codex` source: a Codex JSONL `message` string only (no status/`error.type` on the exec path). Conservative
  source-literal allowlist + JSON fallback shipped in Phase 1 (`codex_stream.is_subscription_exhausted`).
- [x] **D2 -- Sticky. CONFIRMED (reviewer 2026-06-30).** Per-invocation re-check just recreates the harm (every
  Write/Edit burns a doomed codex attempt, then fail-opens again). Sticky = one fail-open, then real enforcement on the
  default claude lane for the rest of the session.
- [x] **D3 -- Degrade-state home/shape/reset. CONFIRMED + tightened (reviewer 2026-06-30).** Home:
  `confirmed.policy.policy_states` (no new `PolicyConfirmed` field) -- `build_policy_state_update` MERGES
  (`store.py:114`: `dict(existing); .update(engine_state)`), and `engine_state` is keyed by policy_id (only
  `semantic.supervisor` exists), so a non-policy-id key is never in `engine_state` and is never clobbered. **Key:**
  dedicated overlay `forge.supervisor_lane_degrade` (the `forge.` prefix signals "overlay, not a policy id"). **Shape:**
  `{degraded, from_lane, to_lane, reason, at}` -- `from_lane`/`to_lane` stored as full lane dicts **for audit/display
  only**; routing injects `lane_record=None` (do NOT trust stored `to_lane` for dispatch). **Reset** = follow the
  *binding*, not the command name (see Phase 2 for the verified seams). NOT the write-once `consumer_lanes` binding.
- [x] **D4 -- Scope = supervisor-only. CONFIRMED** -- the shipped Phase 1 gate (`lane.runtime_id == "codex"` in
  `run_supervisor_check`) is supervisor-only; shadow-curation message refinement remains an optional follow-up.

## Phase 0 -- Exhaustion-signal capture/confirm (GATE, blocks Phase 1) -- DONE (reviewer confirmed GO 2026-06-30)

Resolved D1 with source evidence, not a guess. Gate passed; Phase 1 implemented below.

- [x] Documented the exhausted-ChatGPT `codex exec` error shape from `openai/codex` source (**`main` @ `db887d0`,
  2026-06-30; runtime tag `rust-v0.137.0`** -- SHA pinned so this stays durable as `main` moves):
  `exec/src/exec_events.rs` (`ThreadErrorEvent { message: String }` -- message-only; status + `codex_error_info` dropped
  at the exec boundary) and `protocol/src/error.rs:116,432` (`CodexErr::UsageLimitReached` `Display` = human prose
  `"You've hit your usage limit. ..."`). Confirmed `http_status_code_value()` is `None` for this variant -> **no
  `429`**. Framing: not a structured signal at Forge's boundary -- a usable Codex JSONL `message` signal.
- [x] Recorded fixture `tests/fixtures/codex/exec_json_quota_exhausted.jsonl` (source-derived, Plus-plan message; exact
  4-line envelope mirroring `exec_json_error.jsonl`). Provenance + two-shape error note added to the dir's README.
- [x] Defined the conservative predicate (card D1): degrade on casefolded anchors `hit your usage limit` /
  `out of credits` / `spend cap` / `quota exceeded. check your plan` /
  `to use codex with your chatgpt plan, upgrade to plus`, **or** JSON
  `error.type in {usage_limit_reached, insufficient_quota}`. Negative set: `rate_limit_exceeded` (transient RPM --
  excluded), `selected model is at capacity`, `we're currently experiencing high demand`, `invalid_request_error`
  /model-not-supported (`400` fixture), connection/timeout/stream, bare `turn failed`, empty/unparseable.
- [x] **Decision recorded: GO (recommended).** Anchors are stable source literals; conservative bias degrades the
  *check* (normal fail-open) but never trips the *lane* degrade on an unrecognized error. **Gate to Phase 1 = reviewer
  confirms GO** (or judges prose-matching too brittle -> defer/reshape).

## Phase 1 -- Detection classifier + `failure_type` -- DONE

- [x] Pure `is_subscription_exhausted(error_message: str) -> bool` classifier in `codex_stream.py` (next to
  `_extract_error_message`; **no `CodexStreamResult` schema change**). Card-D1 allowlist (G2: all five display families
  -- usage limit / workspace credits depleted / spend cap / quota exceeded / usage-not-included) + JSON `error.type`
  fallback. Conservative: True only on the Phase-0 anchors; False on generic/transient/RPM/empty.
- [x] New `failure_type="subscription_exhausted"` in the `run_supervisor_check` failure ladder, **ahead of**
  `subprocess_error`/`exit_N`. **G1 gate:** set only when `lane.runtime_id == "codex"` **and** `result.runtime_is_error`
  **and** the classifier matches **`result.error or result.stderr`**. **G3:** behavior-neutral relabel (still
  fail-open/allow) for Phase 2 to consume.
- [x] **Review fix (high)**: classify against `result.error or result.stderr`, not `result.error` alone. A realistic
  codex failure exits **non-zero**, so `_headless_to_session_result` does NOT fold `stderr` into `error` (that fold is
  exit-0-only) -- the quota reason rides `stderr` with `error=None`. The original `result.error`-only check would have
  classified it as `exit_1`. Caught in review; the positive test now models `returncode=1`.
- [x] **Review fix (display)**: unified the fail-open warning + decision text to
  `reason = result.error or result.stderr or "exit N"` (one var, also feeds the classifier), so the quota message
  surfaces in the policy warning instead of a bare "exit 1" on the realistic non-zero path. Guarded by an
  `"usage limit" in decision.warnings` assertion in the `returncode=1` test.
- [x] Unit tests: classifier truth table + **G4** both-extraction-shapes
  (`test_codex_stream.py::TestSubscriptionExhaustionClassifier`); supervisor seam --
  `test_codex_quota_runtime_error_classified_subscription_exhausted` (**realistic `returncode=1`**, reason on stderr),
  `test_codex_quota_at_exit_zero_fold_path_also_classified` (exit-0 fold path), and
  `test_claude_lane_quota_like_error_stays_subprocess_error` (G1 gate); the pre-existing `model overloaded` test still
  asserts `subprocess_error` (non-quota unaffected).

**Verification**:
`pytest tests/src/core/invoker/test_codex_stream.py tests/src/policy/semantic/test_supervisor.py tests/src/core/invoker/test_codex_invoker.py`
-> 185 passed; `mypy` clean on both changed `src/` files; `pre-commit` (ruff/black/isort/mypy/pyright) clean.

## Phase 2 -- Sticky degrade (hook-owned, fail-open)

- [ ] Degrade-state in `confirmed.policy.policy_states["forge.supervisor_lane_degrade"]` (overlay key, NOT a policy id;
  no new strict-dataclass field; D3). Shape `{degraded, from_lane, to_lane, reason, at}` -- `from_lane`/`to_lane` are
  full lane dicts for **audit/display only**.
- [ ] **Write** (`cli/hooks/policy.py`, under the existing freeze lock): when a check returns
  `failure_type="subscription_exhausted"` on a codex lane, persist the marker. **Stale-write guard (mirror
  `persist_lane_freeze`, `consumer_lane_freeze.py:60`):** under the lock, write only if the supervisor is still
  configured AND `read_bound_lane(m, SUPERVISOR_CONSUMER) == dispatched_lane` -- else a concurrent remove/re-pin is
  silently undone by a late hook write. Best-effort (a lock/IO failure never blocks the hook).
- [ ] **Read** (top of the check, `cli/hooks/policy.py`): if degraded this session, inject `lane_record=None` (the
  default claude lane) into `run_supervisor_check` instead of the bound codex lane. Route by `None`, **never** by the
  stored `to_lane`. The write-once `confirmed.consumer_lanes` binding is untouched (stays observable in `lane show`).
- [ ] **Reset map -- follow the *binding*, not the command name** (all seams verified 2026-06-30). Clear via a
  policy-domain helper (NOT the lane primitives -- layering) at each site:
  - `policy supervisor remove` (`policy.py:1344`) **and** `%policy supervisor remove` (`direct_commands.py:859`) -- both
    call `clear_consumer_lane` (tears down confirmed) -> **clear** the marker.
  - `policy supervisor set --runtime/--backend` (`policy.py:1256`) **and** `session lane set --consumer supervisor`
    (`session_lane.py:163`) -- both call `set_intent_lane` (re-pin); a same-lane re-pin is the **only** re-pin that
    succeeds when frozen (`set_cmd` rejects a different lane via `_LaneFrozen`) -> **clear** (the "topped up, retry
    codex" signal).
  - **Do NOT clear** on `session lane clear --consumer supervisor` (`clear_intent_lane`, `session_lane.py:184`) -- it
    leaves the frozen confirmed binding, so codex still dispatches and the degrade still applies.
- [ ] **Cross-resume (per-session):** clear the marker at session start/resume so a fresh resume re-tests codex (the
  weekly quota may have refilled). Confirm the exact seam in Phase 2.
- [ ] Fail-open throughout: a degrade-path error degrades the *check* to allow, never raises (design_workflows §1.2).
- [ ] Acceptance: sticky-degrade, enforces-on-claude-after-degrade, one-hop-only, fail-open (card table).

## Phase 3 -- Observability + docs

- [ ] One **upstream** operation outcome via `record_upstream_operation` (`command=supervisor`,
  `operation=policy.lane_degraded`, `reason_code=subscription_exhausted`, from/to lane in `message`), read by
  `forge telemetry activity` (Operation outcomes pane). NOT a `UsageEvent` (model-call/cost plane -- wrong shape).
  Self-contained, no T5 dependency.
- [ ] Surface "degraded this session" on a read surface (`forge session lane show` and/or
  `forge policy supervisor status`) so the operator can see the lane was routed around without editing the
  (still-frozen) binding.
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
