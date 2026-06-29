# Epic coordination checklist: consumer_lanes

**Lane**: `doing/` (active coordinator). This tracks *coordination* only -- member cards own their implementation
checklists (board_contract "Epics"). Epic framing: `card.md`.

## Current focus

T1a (PR #51, `b84e2462`), T3 (PR #52, `e66490af`), **T2** (PR #54, squash `ff3b96cc`), and **T4** (PR #55, `40b7a1b6`)
are all **done** -- the spine (pure resolver + byte-identical Claude-default supervisor), the backend axis
(runtime-native subscription sources), and the headline capability demo (codex-exec supervisor lane) are on `main`, all
four cards in `done/`. T2's three decisions are resolved (A = Option (c), user 2026-06-26: `runtime_native` owns its
auth, validator symmetry, runtime-owned display; B/C in the T2 checklist) and `design_appendix.md` §A.2.1 is synced. T4
proved a swappable non-Claude lane behind the narrow `SupervisorConfig.supervisor_runtime` field (blind/transfer-fed,
read-only, direct-to-OpenAI, fail-open); it also synced `design.md` §3.6.12 + `design_appendix.md` §G to describe both
supervisor arms, closing the §G/§3.6.12 sync T3 deferred. **T5** (lane observability) is **done** (PR #56, `4fc705b4`)
and closed to `done/lane_observability/`: two honest read surfaces (`forge telemetry activity` per-call
`runtime`/`billing_mode`; `forge policy supervisor status` the full `(runtime, backend, model)` lane), the three M3
no-emission gaps closed (checker/reviewer/team-tagger now emit session-tagged usage), and the invoker's
`workflow.worker` upstream mislabel T4 carried forward fixed (additive `Attribution.operation`; codex supervisor sets
`operation=None` for parity). With T5 done the **first wave (T1a/T2/T3/T4/T5) is complete**; the epic stays in `doing/`
coordinating T6, T7, and the T0 sibling (T1b done). **T7** (subscription-exhaustion fail-open) -- the one new ticket
from the 2026-06-26 workweave/Avengers-Pro discussion -- is authored in `proposed/subscription_exhaustion_failopen/`
(depends on T4). **T1b is done** (PR #57, `6ff555f6`, 2026-06-28; closed to `done/consumer_lane_binding/`): the
supervisor lane is now a persisted, frozen-at-first-dispatch `consumer_lanes` binding (`intent` requested + immutable
`confirmed`). **T0 is the active cursor**: promoted to a member card (`doing/claude_subscription_billing/`, branch
`claude_subscription_billing`, 2026-06-29), card authored and **awaiting plan review** before implementation -- it is
probe-first (does `claude -p` ride Max headlessly?), so the first deliverable is an operator-gated probe, not a code
change. T6 stays an inline sketch; T7 is authored in `proposed/`. The `core.llm` representation is decided (option 2 --
see Decisions).

## Member roster and sequencing

| Member       | Card                                         | Lane     | Depends on | State                                     |
| ------------ | -------------------------------------------- | -------- | ---------- | ----------------------------------------- |
| T1a          | `done/consumer_lane_resolver/`               | done     | --         | done (PR #51)                             |
| T2           | `done/backend_subscription_sources/`         | done     | T1a        | done (PR #54)                             |
| T3           | `done/supervisor_lane_driven/`               | done     | T1a        | done (PR #52)                             |
| T4           | `done/codex_exec_supervisor_lane/`           | done     | T1a,T2,T3  | done (PR #55)                             |
| T5           | `done/lane_observability/`                   | done     | T3,T4      | done (PR #56)                             |
| T1b          | `done/consumer_lane_binding/`                | done     | T4         | done (PR #57)                             |
| T6           | inline in `card.md`                          | --       | T1b        | sketch                                    |
| T7           | `proposed/subscription_exhaustion_failopen/` | proposed | T4         | authored 2026-06-26                       |
| T0 (sibling) | `doing/claude_subscription_billing/`         | doing    | none       | card authored 2026-06-29; awaiting review |

Sequencing (epic-canonical): T1a -> T3 -> T2 -> T4 -> T5 -> T1b -> T6. T2 and T3 both depend only on T1a and are
mutually independent; T3 is sequenced first to prove the seam byte-identical before T2 adds backend vocabulary --
parallelizing T2/T3 is allowed but is not the default cursor. T0 is independent, anytime.

## Scope guards (2026-06-25 review)

- **T2 ships `chatgpt` first; `claude-max` is deferred.** The `chatgpt` path is billing-proven (codex
  `chatgpt_tokens -> subscription_quota`); `claude-max` asserts `claude -p` rides a Max subscription, which is unproven.
  Gate it on T0. So **T0 is non-blocking for T2/T4 but load-bearing for `claude-max`**.
- **T2 expanded `ProviderType`** (`core/provider_types.py` -- added catalog-only `openai`). **Resolved**: the originally
  guessed downstream branches did **not** all need changes. `core/llm/detection.py` was verified unchanged (`openai` is
  never a `core.llm` routing target; `detect_provider` already maps `openai/<model>` to `litellm_remote`, and
  `is_implemented("openai")` is `False`); `cli/backend.py` got `runtime_native` display/probe handling rather than the
  per-line provider branches first guessed.

## Decisions owed (coordination, not code)

- [x] **core.llm vs RuntimeSpec shape** (was blocking T1a). **Decided: option 2** -- classify execution in the lane
  layer; leave `RUNTIMES` untouched (adding a `core.llm` entry pollutes `list_runtimes()` / `installed_runtimes()` at
  `core/runtime/registry.py:251,256` and their callers, and needs an always-true `is_installed()` hack). Lane runtime
  axis = `{"core_llm"}` plus `RUNTIMES.keys()`. See `consumer_lane_resolver/checklist.md` Phase 0.
- [x] **Shared `BillingPosture` vocabulary** (T2 + T5). **Decided** (T2 checklist Decision C): one enum
  `Literal["per_token", "subscription_quota", "free"]` in `backend/sources.py`, a `ModelSource.billing_posture` field
  defaulting `per_token`, reusing the exact `subscription_quota` spelling shared with `BillingMode`. Separate enum from
  `BillingMode` by design (posture = source-level; mode = invocation-level).
- [x] **Runtime-native credential shape** (T2). **Decided: Option (c)** (user 2026-06-26). `runtime_native` is a
  first-class endpoint family that owns its own auth: a `runtime_native` source declares `credential_ids=()` (validator
  symmetry -- `runtime_native` => empty, else => `>=1`); read surfaces render `auth_status="runtime_native"` /
  `runtime-owned` health (verify via `forge runtime preflight codex`); codex-login guidance lives in Codex preflight,
  not Forge credential storage. `Credential` stays key-only. See T2 checklist Decision A.
- [x] **Unsupported-lane failure mode** (T4). **Decided: catch + fail-open** (consistent with `proxy_not_found`;
  workweave/Avengers-Pro discussion 2026-06-26). **Shipped in T4 (PR #55):** a non-claude lane previously failed *loud*
  (`resolve_lane` outside the fail-open guard; `_dispatch_supervisor` raised `NotImplementedError`/`LaneError` the
  caller did not catch); T4 moved `resolve_lane` inside the guard and degrades an unimplemented/misconfigured lane to
  "aligned" (design_workflows §1.2 -- bad override -> `configuration_error`, preflight failure -> `codex_unavailable`,
  plan-absent -> `plan_missing`). Wiring in `done/codex_exec_supervisor_lane/`; full seam list: epic `card.md` "T3 -> T4
  carry-forward seams".

## Link and drift control

- [ ] Each member card links this epic at its top via the current board path (`docs/board/doing/epic_consumer_lanes/`).
  Update both sides if the epic lane moves.
- [x] When T1a opens: branch, `git mv docs/board/todo/consumer_lane_resolver docs/board/doing/`, add its `checklist.md`,
  update this roster. (done -- branch `consumer_lane_resolver`)
- [x] When T4 opens: branch, `git mv docs/board/todo/codex_exec_supervisor_lane docs/board/doing/`, add its
  `checklist.md`, update this roster. (done -- branch `codex_exec_supervisor_lane`)
- [x] When T5 opens: branch `lane_observability`, author `doing/lane_observability/card.md` + `checklist.md` from the
  2026-06-27 surface map, update this roster. (done -- promoted from inline sketch; shipped PR #56 and closed to
  `done/lane_observability/` 2026-06-27)
- [ ] Promote T1b/T6 from inline sketch to member cards when they become the cursor. **T4 done** ->
  `done/codex_exec_supervisor_lane/` (PR #55); **T5 done** -> `done/lane_observability/` (PR #56); **T7** (new, from the
  workweave discussion) -> `proposed/subscription_exhaustion_failopen/`. **T1b done** -> `done/consumer_lane_binding/`
  (PR #57, 2026-06-28). **T0 promoted** -> `doing/claude_subscription_billing/` (branch `claude_subscription_billing`,
  2026-06-29, awaiting plan review); T6 still inline.
- [x] Verify the M3 no-emission gaps (WorkflowPolicy Checker/Reviewer stages, team event tagger) are actually silent
  before they become T5 acceptance -- the epic `card.md` flagged them "agent-reported, verify". **Confirmed silent**
  (2026-06-27 T5 surface map): `CheckerStage.check()` (`policy/workflow/stages.py:100`), `ReviewerStage.review()`
  (`:143`), team `_classify_event()` (`policy/team/handlers.py:157`) all call `adapter.ask(...)` with no `emit_*`. Now
  T5 WS2 acceptance.

## Design-doc sync (board_contract "Design Doc Sync")

- [x] T2 ships -> update `design_appendix.md` §A.2.1 (`ModelSource` gains `billing_posture` + `runtime_native` access +
  `reachable_via`; `chatgpt` added to the shipped-catalog table; operator-view paragraph documents the runtime-owned
  read surface). Done on branch `backend_subscription_sources`.
- [x] T1a/T3 ship -> update `design_appendix.md` §G + `design.md` §3.6.12 (lane resolver layered over subprocess
  routing). **Done in T4 (PR #55):** §G's consumer-lane paragraph describes both supervisor arms (claude_code default +
  codex override); §3.6.12 notes the codex arm bypasses the proxy chain. (T3 deferred this "to >1 wired consumer"; T4 is
  that consumer.)
- [x] T5 ships -> update `design_appendix.md` §G (Observability paragraph: the two read surfaces + `operation=None`
  upstream-parity fix; per-emitter coverage table gains checker/reviewer/team-tagger rows) and `cli_reference.md`
  (`forge telemetry activity` lane columns + `forge policy supervisor status` row). Done in PR #56.
- [x] T1b ships -> updated `design.md` §3.5 (`intent.consumer_lanes` CLI-written, `confirmed.consumer_lanes`
  hook-written write-once) + §3.6.2 (consumer-lane binding invariant: intent=requested, confirmed=frozen/immutable);
  `design_appendix.md` §G (supervisor lane now the persisted/frozen `consumer_lanes` binding, hook-injected; T5
  observability reads the frozen binding, `not executable` on drift); `cli_reference.md` (`--supervisor-runtime` launch
  control + `set --runtime` row + status drift). Done on branch `consumer_lane_binding` (Slice 5).

## Closeout (epic)

- [ ] Epic -> `done/` only when every live member is `done/`, or the shared contract is folded into normative design
  docs (board_contract "Epics"). Add a `change_log.md` entry; promote durable lessons to `impl_notes.md` after human
  review.
