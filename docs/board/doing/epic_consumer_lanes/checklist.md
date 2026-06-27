# Epic coordination checklist: consumer_lanes

**Lane**: `doing/` (active coordinator). This tracks *coordination* only -- member cards own their implementation
checklists (board_contract "Epics"). Epic framing: `card.md`.

## Current focus

T1a (PR #51, `b84e2462`), T3 (PR #52, `e66490af`), and **T2** (PR #54, squash `ff3b96cc`) are all **done** -- the spine
(pure resolver + byte-identical Claude-default supervisor) plus the backend axis (runtime-native subscription sources)
are on `main`, all three cards in `done/`. T2's three decisions are resolved (A = Option (c), user 2026-06-26:
`runtime_native` owns its auth, validator symmetry, runtime-owned display; B/C in the T2 checklist) and
`design_appendix.md` §A.2.1 is synced. **T4** (Codex-exec supervisor lane) is the next cursor and is now fully unblocked
(deps T1a+T2+T3 all landed); T5/T1b/T6 stay inline sketches. The `core.llm` representation is decided (option 2 -- see
Decisions).

## Member roster and sequencing

| Member       | Card                                 | Lane | Depends on | State                      |
| ------------ | ------------------------------------ | ---- | ---------- | -------------------------- |
| T1a          | `done/consumer_lane_resolver/`       | done | --         | done (PR #51)              |
| T2           | `done/backend_subscription_sources/` | done | T1a        | done (PR #54)              |
| T3           | `done/supervisor_lane_driven/`       | done | T1a        | done (PR #52)              |
| T4           | inline in `card.md`                  | --   | T1a,T2,T3  | sketch (next cursor)       |
| T5           | inline in `card.md`                  | --   | T3,T4      | sketch                     |
| T1b          | inline in `card.md`                  | --   | T4         | sketch                     |
| T6           | inline in `card.md`                  | --   | T1b        | sketch                     |
| T0 (sibling) | inline in `card.md`                  | --   | none       | sketch; gates `claude-max` |

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
- [ ] **Unsupported-lane failure mode** (T4, from T3 review). The supervisor is fail-open (design_workflows §1.2), but a
  non-claude lane currently fails *loud*: `resolve_lane` sits outside the fail-open guard and `_dispatch_supervisor`
  raises `NotImplementedError`/`LaneError` that the caller does not catch (`supervisor.py:463-464,603`). Decide whether
  an unimplemented/misconfigured lane catches + fails open (consistent with `proxy_not_found`) or fails loud, then wire
  it in T4. Full seam list: epic `card.md` "T3 -> T4 carry-forward seams".

## Link and drift control

- [ ] Each member card links this epic at its top via the current board path (`docs/board/doing/epic_consumer_lanes/`).
  Update both sides if the epic lane moves.
- [x] When T1a opens: branch, `git mv docs/board/todo/consumer_lane_resolver docs/board/doing/`, add its `checklist.md`,
  update this roster. (done -- branch `consumer_lane_resolver`)
- [ ] Promote T4/T5/T1b/T6 from inline sketch to member cards only after T1a+T3 land (shape proven).
- [ ] Verify the M3 no-emission gaps (WorkflowPolicy Checker/Reviewer stages, team event tagger) are actually silent
  before they become T5 acceptance -- the epic `card.md` flags them "agent-reported, verify".

## Design-doc sync (board_contract "Design Doc Sync")

- [x] T2 ships -> update `design_appendix.md` §A.2.1 (`ModelSource` gains `billing_posture` + `runtime_native` access +
  `reachable_via`; `chatgpt` added to the shipped-catalog table; operator-view paragraph documents the runtime-owned
  read surface). Done on branch `backend_subscription_sources`.
- [ ] T1a/T3 ship -> update `design_appendix.md` §G + `design.md` §3.6.12 (lane resolver layered over subprocess
  routing).
- [ ] T1b ships -> update `design.md` §3.6 (manifest gains consumer-lane `intent`/`confirmed`).

## Closeout (epic)

- [ ] Epic -> `done/` only when every live member is `done/`, or the shared contract is folded into normative design
  docs (board_contract "Epics"). Add a `change_log.md` entry; promote durable lessons to `impl_notes.md` after human
  review.
