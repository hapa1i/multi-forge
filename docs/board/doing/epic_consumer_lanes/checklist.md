# Epic coordination checklist: consumer_lanes

**Lane**: `doing/` (active coordinator). This tracks *coordination* only -- member cards own their implementation
checklists (board_contract "Epics"). Epic framing: `card.md`.

## Current focus

First wave (T1a, T2, T3) authored as member cards in `docs/board/todo/`. No execution branch open yet. The next gate is
a coordination *decision*, not code: resolve how `core.llm` sits relative to `RuntimeSpec` before T1a implementation
starts (see Decisions owed).

## Member roster and sequencing

| Member       | Card                                 | Lane | Depends on | State                      |
| ------------ | ------------------------------------ | ---- | ---------- | -------------------------- |
| T1a          | `todo/consumer_lane_resolver/`       | todo | --         | authored                   |
| T2           | `todo/backend_subscription_sources/` | todo | T1a        | authored                   |
| T3           | `todo/supervisor_lane_driven/`       | todo | T1a        | authored                   |
| T4           | inline in `card.md`                  | --   | T1a,T2,T3  | sketch                     |
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
- **T2 must expand `ProviderType`** (`core/provider_types.py:7` -- add `openai`) and the downstream provider branches
  (`core/llm/detection.py`, `cli/backend.py:318,426,448,452`); a `chatgpt` source fails validation otherwise.

## Decisions owed (coordination, not code)

- [ ] **core.llm vs RuntimeSpec shape** (blocks T1a). `RuntimeSpec` is subprocess-shaped (`headless_cmd`,
  `is_installed()` via `shutil.which`, `core/runtime/registry.py:109`) and documents itself as "one *agent* runtime";
  `core.llm` is in-process and single-shot. Decide: add a `core.llm` entry to `RUNTIMES` with an `execution` capability
  attr and no real `headless_cmd`, or model the lane runtime axis as `{core.llm}` plus `RUNTIMES`. T1a card carries both
  options + a recommendation.
- [ ] **Shared `BillingPosture` vocabulary** (T2 + T5). Fix one enum -- `per_token` / `subscription_quota` / `free` --
  used by T2's `ModelSource` field and surfaced by T5. One spelling, no parallel variants.
- [ ] **Runtime-native credential shape** (T2). `ModelSource` requires >=1 `credential_id` and credentials are env-var
  secrets; a subscription source's auth is the runtime's native login (claude OAuth / codex `chatgpt_tokens`), not an
  env secret. Decide how a `runtime_native` source expresses auth without faking an env var.

## Link and drift control

- [ ] Each member card links this epic at its top via the current board path (`docs/board/doing/epic_consumer_lanes/`).
  Update both sides if the epic lane moves.
- [ ] When T1a opens: branch, `git mv docs/board/todo/consumer_lane_resolver docs/board/doing/`, add its `checklist.md`,
  update this roster.
- [ ] Promote T4/T5/T1b/T6 from inline sketch to member cards only after T1a+T3 land (shape proven).
- [ ] Verify the M3 no-emission gaps (WorkflowPolicy Checker/Reviewer stages, team event tagger) are actually silent
  before they become T5 acceptance -- the epic `card.md` flags them "agent-reported, verify".

## Design-doc sync (board_contract "Design Doc Sync")

- [ ] T2 ships -> update `design_appendix.md` §A.2.1 (`ModelSource` gains `billing_posture` + `runtime_native` access).
- [ ] T1a/T3 ship -> update `design_appendix.md` §G + `design.md` §3.6.12 (lane resolver layered over subprocess
  routing).
- [ ] T1b ships -> update `design.md` §3.6 (manifest gains consumer-lane `intent`/`confirmed`).

## Closeout (epic)

- [ ] Epic -> `done/` only when every live member is `done/`, or the shared contract is folded into normative design
  docs (board_contract "Epics"). Add a `change_log.md` entry; promote durable lessons to `impl_notes.md` after human
  review.
