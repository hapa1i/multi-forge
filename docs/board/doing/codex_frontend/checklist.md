# Codex Frontend Checklist

Manual multi-session plan for executing [`card.md`](./card.md).

This card is in active execution under `doing/`. Move the whole `codex_frontend/` directory to `docs/board/done/` after
closeout.

## Maintenance

- Update this file during implementation sessions and once before ending a session.
- Tick a task only when the assertion is satisfied and verification is recorded.
- Move completed-session details to `docs/board/change_log.md`; keep only active plan state here.
- Update design docs per phase as code ships (design docs are normative, not aspirational).
- Check size periodically while the card is active (`./scripts/count-tokens.py --model <agent-model> <this file>`).

## Current Focus

**Card accepted 2026-06-10, moved `proposed/ -> doing/` directly** (the gating probe returned GO the same day; `todo/`
parking skipped because execution starts immediately -- the lane's "accepted but no execution branch" state never
existed). Probe round 2 findings are recorded in `card.md` ("Probe-established facts"); do not re-derive them.

Next: **Phase 0 (registry correction)** -- small, owed from the probe -- then **Phase 1 (enrollment-mechanics probe
round)**, which pins the facts that gate Phases 3/4/6. **Phase 2 (bridge CLI)** is the first product deliverable and has
no dependency on Phase 1; it can interleave.

## Phase 0 - Registry correction (owed from probe round 2)

- [ ] Correct the Codex `RuntimeSpec` hooks encoding: `native_hooks="headless_inert"` is refuted by the binary -- hooks
  fire under headless `codex exec` once trust-enrolled (card facts, 40c2/40d). Encode enrollment gating as a value (new
  `HookSupport` literal; name decided at implementation -- see Open Decisions). `pretool_policy` stays `"none"` until
  Phase 1 pins PreToolUse post-enrollment.
  - Assertion: registry value + `HookSupport` comment + Codex `note` state the round-2 finding (enrolled-headless fires;
    enrollment requires the interactive ceremony until Phase 1 settles pre-enrollment);
    `tests/src/core/runtime/test_registry.py` + `tests/src/cli/test_runtime.py` updated and green; mypy clean;
    `design.md` §5.5.5 matches; change_log entry.

## Phase 1 - Enrollment-mechanics probe (headless from one enrolled home)

Build the persistent enrolled fixture first; every other item runs headless from it. Harness:
`scripts/experiments/codex-hooks/` (extend, do not fork).

- [ ] Persistent enrolled fixture: stable project path + persistent `CODEX_HOME` (the 40-trust persistent-home pattern
  minus the teardown), one operator trust ceremony. Record the operator-observed TUI prompt wording (project/folder
  trust vs hook-specific review vs both; `/hooks` availability) -- the one fact captures cannot hold.
  - Assertion: a headless `codex exec` turn in the fixture fires SessionStart reproducibly across separate runs.
- [ ] 40e -- registration-string trust dimension: change the registered `command` string in the enrolled fixture;
  observe whether trust invalidates (40d proved script-*content* changes survive).
  - Assertion: fired/not-fired recorded for a changed `command`; conclusion states what the `trusted_hash` covers.
- [ ] `trusted_hash` preimage: determine what Codex hashes (candidate preimages vs the known `sha256:0d63...` from round
  2, or source-dive the codex-cli release). Then decide the **pre-enrollment posture** (installer writes `[hooks.state]`
  records vs ships a guided one-time `codex` trust ceremony) -- an explicit decision recorded here and in `card.md`, not
  an implementation detail.
- [ ] Event coverage post-enrollment: re-run stage 20 (10-event tee) and stage 30 response contracts (30a-30h, including
  the 30e `additionalContext` magic-token oracle and PreToolUse deny/`updatedInput`) inside the enrolled home.
  - Assertion: per-event fired/not-fired matrix recorded; 30e oracle PASS/FAIL recorded (gates Phase 4); PreToolUse deny
    \+ mutation verdicts recorded (gates Phase 3 and the `pretool_policy` value).
- [ ] User-level vs project-level trust: where a user-level hook's trust record lands (50c fired one interactively but
  its home died with the run).
- [ ] Worktree/path sensitivity: trust keys on the registering config's **absolute path** -- verify whether enrollment
  survives a `git worktree` checkout of the same project (Forge's main isolation workflow).
- [ ] Sanitized payload fixtures to `tests/fixtures/codex/hooks/` with a provenance README (the Phase 6 descoped
  deliverable; capturable headless now).
  - Assertion: `sanitize.sh` passes; `make pre-commit` (gitleaks) clean on the fixture commit; per-file provenance table
    cloned from `tests/fixtures/codex/README.md`.

## Phase 2 - One-command bridge CLI (GO; no hook dependency)

Frontend over the shipped `bridge_session_to_codex` (`core/ops/codex_bridge.py`). Plan the slice in detail when started;
the acceptance sketch:

- [ ] CLI shape decision (e.g. `forge session start --runtime codex --resume-from <parent>`) -- recorded in Open
  Decisions before implementation.
- [ ] `runtime` field on the session manifest (`SessionIntent`/`SessionConfirmed`) + runtime-aware launcher dispatch
  (today hard-wired to `invoke_claude`).
- [ ] Codex `thread_id` (resume id) + rollout path recorded into `confirmed` (both carried in the SessionStart payload /
  `thread.started` stream event); continuation via `codex exec resume <thread_id>`.
- [ ] GC the synthetic `<parent>-codex-<suffix>` transfer children the bridge accumulates (Phase 5e recorded debt).

| Test                   | Fixture                              | Assertion                                                          | Test File |
| ---------------------- | ------------------------------------ | ------------------------------------------------------------------ | --------- |
| Bridge CLI happy path  | mocked curation + codex Popen replay | manifest `runtime=codex`; `thread_id` + rollout path in confirmed  | TBD       |
| Continuation           | recorded `thread_id`                 | relaunch invokes `codex exec resume <thread_id>` cross-CWD         | TBD       |
| Transfer-child GC      | bridge run x2                        | synthetic children GC'd; real children untouched                   | TBD       |
| Real-codex E2E (@slow) | real codex, curation mocked          | one run tree: curation + codex events; `forge activity` shows both | TBD       |

## Phase 3 - Codex hook adapter/responder (gated on Phase 1 event coverage)

Stub -- expand when Phase 1 lands. `CodexHookAdapter`/`CodexHookResponder` filling `src/forge/cli/hooks/protocols.py`;
snake_case payload -> `ActionContext`; carry the **`ActionContext.runtime` -> `origin` rename** (first real consumer;
direction resolved in `runtime_abstraction` Open Decisions 2026-06-09). `pretool_policy` rises from `"none"` only on
Phase 1's PreToolUse verdicts.

## Phase 4 - SessionStart transfer delivery with initial-message fallback (gated on Phase 1 30e)

Stub -- viable for both the interactive frontend and the enrolled headless bridge; initial-message stays the zero-setup
default.

## Phase 5 - Interactive Codex frontend (unblocked; build after 2/3)

Stub -- Forge-managed interactive `codex` sessions: `install_scopes`, `interactive="beta"` flip, FORGE_SESSION wiring
(verified in hook env + model shell), positional initial prompt (verified), session-id capture into `confirmed`.

## Phase 6 - Installer Codex support (gated on Phase 1 posture + Phases 3/5)

Stub -- Codex preset + registration target + installer-side event-name validation (the binary won't catch typos) + the
per-hook-trust story from Phase 1.

## Deferred

- App-server transport (`codex app-server` / `--stdio`): unevaluated by scope decision; spike only if multi-turn
  `exec resume` proves clumsy.

## Open Decisions

- [ ] `HookSupport` literal name for enrollment gating (Phase 0): e.g. `enrollment_gated`. Decide at implementation; the
  comment must distinguish it from `gated` (version floor) which Codex meets yet did not fire untrusted.
- [ ] Pre-enrollment posture (Phase 1): write `[hooks.state]` records programmatically vs guided one-time ceremony.
  Precedent: Forge already writes Claude's `settings.json` hooks with user consent -- but bypassing another tool's
  review gate is a posture decision, made explicitly.
- [ ] Bridge CLI shape (Phase 2): flag on `forge session start` vs a dedicated verb.

## Closeout

1. Tick final checklist items with verification; change_log entry per phase (newest-first, Goal/Key changes/
   Verification).
2. Durable lessons proposed via `.forge/memory/shadow_impl_notes.md` (human promotes).
3. Design docs + end-user docs verified against shipped behavior (registry/design.md §5.5.5 in Phase 0; session manifest
   \+ `transfer.md`/`session.md` in Phase 2; hooks docs in Phase 3+).
4. `git mv docs/board/doing/codex_frontend docs/board/done/` after the final merge to `main`.
