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

**Phase 0 shipped 2026-06-10** (registry + preflight `headless_inert -> enrollment_gated` rename; see change_log). Next:
**Phase 1 (enrollment-mechanics probe round)**, which pins the facts that gate Phases 3/4/6. **Phase 2 (bridge CLI)** is
the first product deliverable and has no dependency on Phase 1; it can interleave.

**Phase 1 harness implemented 2026-06-10 (the executable half).** `scripts/experiments/codex-hooks/` extended with the
fixture mode (`lib.sh`: `fixture_init`/`fixture_build`/`fixture_require`, the stable-path/swappable-body `fixture_tee`/
`fixture_arm`, `fixture_project_specs`), stages `80-enroll-fixture` (guided ceremony) / `81-enrolled-coverage` /
`82-trust-dimensions` / `83-preimage`, the offline `hooks/hash-preimage.py` (trusted_hash reverse-engineering +
`--emit-state` forging), `reproduce.sh` wiring (`FIXTURE_STAGES`, explicit-only), and a round-3 README section. Also:
`tests/fixtures/codex/hooks/README.md` (the post-capture payload-fixture contract). `bash -n` + `shellcheck 0.11.0`
clean on every script; `hash-preimage.py` self-test passes (parse -> join -> candidate discovery -> emit-state) on a
synthetic enrolled fixture.

**Phase 1 probe COMPLETE 2026-06-10 (codex 0.138.0); all findings in.** Operator ran `./reproduce.sh 80` (ceremony) +
`81 82 83`, plus a hardened `82` re-run. **All 7 Phase-1 boxes ticked below** with recorded verification; round-3 facts
in `card.md`. **30e PASSED (Phase 4 viable)**; **PreToolUse deny + `updatedInput` work (Phase 3 + `pretool_policy` can
rise)**; the `trusted_hash` is not computable -> **posture = guided ceremony**; **enrollment survives worktrees of the
enrolled project** (82w2 valid run -> project-scope registration with a path-stable command string survives worktrees;
broad cross-project trust is untested). The three Phase-0/1 Open Decisions are resolved; the Phase 2 bridge CLI shape
remains open.

**Phase 1 closeout unit shipped 2026-06-10** (the two deferred follow-ups; see change_log): (a) the `codex_preflight.py`
`[hooks.state]` decision is recorded in code -- the read is deliberately NOT implemented (the `trusted_hash` is not
black-box computable so a record cannot be validated, and a path-keyed read would false-negative in worktrees); the seam
stays `enrollment_gated`, `untrusted` stays reserved for a future codex-cli source-dive. (b) the registry
`pretool_policy` rose `"none" -> "partial"` (deny + `updatedInput` confirmed; partial not full -- enforcement is
enrollment-gated, malformed hook output fails open, PermissionRequest unpinned), with the stale Codex `note` sentences
rewritten to the round-3 facts and `design.md` §5.5.5 synced. **Next: Phase 2 (bridge CLI)**, starting with the
CLI-shape Open Decision.

## Phase 0 - Registry correction (owed from probe round 2)

- [x] Correct the Codex `RuntimeSpec` hooks encoding: `native_hooks="headless_inert"` is refuted by the binary -- hooks
  fire under headless `codex exec` once trust-enrolled (card facts, 40c2/40d). Encode enrollment gating as a value (new
  `HookSupport` literal; name decided at implementation -- see Open Decisions). `pretool_policy` stays `"none"` until
  Phase 1 pins PreToolUse post-enrollment.
  - Assertion (round-2 snapshot; Phase 1 has since settled pre-enrollment as the guided ceremony): registry value +
    `HookSupport` comment + Codex `note` state the round-2 finding (enrolled-headless fires; enrollment requires the
    interactive ceremony); `tests/src/core/runtime/test_registry.py` + `tests/src/cli/test_runtime.py` updated and
    green; mypy clean; `design.md` §5.5.5 matches; change_log entry.
  - **Done 2026-06-10**: `enrollment_gated` landed on BOTH literals -- registry `HookSupport` and preflight `HookSeam`
    (renamed together; keeping one as `headless_inert` would split the capability model). The preflight value is
    documented as capability-not-state ("hooks can fire; `[hooks.state]` unchecked -- never treat as `active`"; the
    enrollment read is Phase 1). 63 runtime/CLI/preflight unit tests green (incl. renamed
    `test_enabled_is_enrollment_gated_never_active`); mypy clean; `rg headless_inert docs/design.md src/ tests/` empty;
    `design.md` §5.5.5 synced; card.md stale hook_seam line fixed; change_log entry added.

## Phase 1 - Enrollment-mechanics probe (headless from one enrolled home)

Build the persistent enrolled fixture first; every other item runs headless from it. Harness:
`scripts/experiments/codex-hooks/` (extend, do not fork).

**Harness -> stage map (built 2026-06-10; run to fill in the findings):** persistent fixture + ceremony = `stage 80`;
40e registration-string = `stage 82` (82e); `trusted_hash` preimage + posture = `stage 83` + `hooks/hash-preimage.py`;
post-enrollment event coverage / 30e / PreToolUse = `stage 81`; user-vs-project + worktree sensitivity = `stage 82`
(82u/82w); sanitized payload fixtures = `stage 81` captures -> `sanitize.sh` -> `tests/fixtures/codex/hooks/`. Run:
`./reproduce.sh 80` (operator TTY), then `./reproduce.sh 81 82 83` (headless).

- [x] Persistent enrolled fixture: stable project path + persistent `CODEX_HOME` (the 40-trust persistent-home pattern
  minus the teardown), one operator trust ceremony. Record the operator-observed TUI prompt wording (project/folder
  trust vs hook-specific review vs both; `/hooks` availability) -- the one fact captures cannot hold.
  - Assertion: a headless `codex exec` turn in the fixture fires SessionStart reproducibly across separate runs.
  - **Done 2026-06-10** (codex 0.138.0): stage 80 enrolled 13 trust keys from ONE grant; SessionStart fired headless on
    both verification turns (80v1=1, 80v2=2) and again in 81/82. Operator wording: *"You can trust all - no command or
    hash"* -> a single per-config grant, not per-entry review (`meta/operator-notes.txt`).
- [x] 40e -- registration-string trust dimension: change the registered `command` string in the enrolled fixture;
  observe whether trust invalidates (40d proved script-*content* changes survive).
  - Assertion: fired/not-fired recorded for a changed `command`; conclusion states what the `trusted_hash` covers.
  - **Done 2026-06-10** (82e): moved entry fired=0, unchanged primary fired=1 -> the command string IS in the per-entry
    `trusted_hash`. With 40d (content survives), the hash covers the registration *definition*, not the script bytes.
- [x] `trusted_hash` preimage: determine what Codex hashes (candidate preimages vs the known `sha256:0d63...` from round
  2, or source-dive the codex-cli release). Then decide the **pre-enrollment posture** (installer writes `[hooks.state]`
  records vs ships a guided one-time `codex` trust ceremony) -- an explicit decision recorded here and in `card.md`, not
  an implementation detail.
  - **Done 2026-06-10** (83): NOT black-box computable -- 15 canonicalizations matched 0/13 harvested hashes
    (`meta/preimage-report.txt`). The command string is in the hash (82e) but the algorithm needs a codex-cli Rust
    source-dive. **Posture RESOLVED: guided one-time ceremony** (see Open Decisions); programmatic `[hooks.state]`
    writing stays blocked until/unless a source-dive makes the hash computable (`hash-preimage.py` already supports
    `--emit-state` for that future).
- [x] Event coverage post-enrollment: re-run stage 20 (10-event tee) and stage 30 response contracts (30a-30h, including
  the 30e `additionalContext` magic-token oracle and PreToolUse deny/`updatedInput`) inside the enrolled home.
  - Assertion: per-event fired/not-fired matrix recorded; 30e oracle PASS/FAIL recorded (gates Phase 4); PreToolUse deny
    \+ mutation verdicts recorded (gates Phase 3 and the `pretool_policy` value).
  - **Done 2026-06-10** (81): matrix in `results/event-matrix.txt`. **30e PASS** (token echoed -> Phase 4 viable).
    PreToolUse **deny** (JSON + exit-2) blocked; **`updatedInput` mutation took effect** (-> Phase 3 + `pretool_policy`
    can rise). Stop block-once forced one extra pass; UserPromptSubmit block suppressed the turn; PermissionRequest did
    not fire under read-only. **Malformed output FAILED OPEN** (refutes the doc-claim -- Phase 3 caveat). `tool_name` is
    `"Bash"`/`"apply_patch"`, so `matcher="shell"` never fired.
- [x] User-level vs project-level trust: where a user-level hook's trust record lands (50c fired one interactively but
  its home died with the run).
  - **Done 2026-06-10** (82u): both user- and project-level hooks fire headless when enrolled; the user record keys by
    `codex-home/config.toml`, project records by `proj/.codex/config.toml` (`meta/trust-locations.txt`).
- [x] Worktree/path sensitivity: trust keys on the registering config's **absolute path** -- verify whether enrollment
  survives a `git worktree` checkout of the same project (Forge's main isolation workflow).
  - **Done 2026-06-10 (82w2, valid run): enrollment survives worktrees of the enrolled project.** The project hook fired
    in the worktree checkout (`proj-codexwt`) with proj=1 user=1 and **no folder `trust_level` and no `[hooks.state]`
    record at the worktree path** -- cross-checked against the captured clean base
    (`meta/user-config.no-wt-trustlevel.toml`: worktree block stripped, 13 records all at the codex-home/proj paths).
    With **40b** (folder trust alone does NOT fire hooks), the firing can only be a `trusted_hash` match on the
    registration definition (byte-identical `$HOOKBIN/<event>.sh` command string). **Mechanism not distinguished**
    (path-independent hash vs Codex canonicalizing the worktree back to the enrolled checkout), and the broad "any
    project with the same command string is trusted" claim is UNTESTED (needs a fresh-project probe). **-> Phase 6
    (holds either way): project-scope registration with a path-stable command string survives worktrees** (no
    per-worktree re-enrollment; resolves the scope Open Decision). *(First 82w2 run was VOID -- leftover worktree
    `trust_level` in the persistent fixture; stage 82 hardened with a strip-first clean base and an INVALID self-guard,
    verified ad hoc against the captured configs, then re-run.)*
- [x] Sanitized payload fixtures to `tests/fixtures/codex/hooks/` with a provenance README (the Phase 6 descoped
  deliverable; capturable headless now).
  - Assertion: `sanitize.sh` passes; `make pre-commit` (gitleaks) clean on the fixture commit; per-file provenance table
    cloned from `tests/fixtures/codex/README.md`.
  - **Done 2026-06-10**: 5 payloads promoted
    (`session_start`/`pre_tool_use`/`post_tool_use`/`user_prompt_submit`/`stop`) with the provenance table filled.
    `sanitize.sh` passes (a real over-match -- `task-*` plugin filenames tripping the `sk-` scan -- was fixed with a
    word-boundary anchor); `make pre-commit` (gitleaks) clean on the fixtures.
- [x] Phase 1 closeout code unit (the two deferred follow-ups): registry `pretool_policy` `"none" -> "partial"` (Phase 1
  confirmed post-enrollment PreToolUse deny + `updatedInput`; partial not full -- enrollment-gated, malformed output
  fails open, PermissionRequest unpinned) + the preflight `[hooks.state]` decision recorded in code (read deliberately
  not implemented; seam stays `enrollment_gated`; `untrusted` reserved for a future source-dive) + the stale registry
  `note`/comment claims rewritten + `design.md` §5.5.5 sync.
  - Assertion: no "unprobed"/"only SessionStart"/"settles pre-enrollment" claim remains in the normative surfaces
    (`docs/design.md`, `docs/design_appendix.md`, `src/`, `tests/src/`); board card/checklist round-2 snapshot lines
    annotated as superseded by round 3; registry + preflight + CLI tests assert the new values; preflight behavior
    unchanged.
  - **Done 2026-06-10**: 63 runtime/preflight/CLI unit tests green (assertions updated to `partial`); mypy clean;
    stale-claim grep empty over the normative surfaces above; card.md/checklist.md round-2 snapshots annotated; live
    `forge runtime list --json` renders `pretool_policy: partial`; change_log entry.

## Phase 2 - One-command bridge CLI (GO; no hook dependency)

Frontend over the shipped `bridge_session_to_codex` (`core/ops/codex_bridge.py`). Plan the slice in detail when started;
the acceptance sketch:

- [ ] CLI shape decision (e.g. `forge session start --runtime codex --resume-from <parent>`) -- recorded in Open
  Decisions before implementation.
- [ ] `runtime` field on the session manifest (`SessionIntent`/`SessionConfirmed`) + runtime-aware launcher dispatch
  (today hard-wired to `invoke_claude`).
- [ ] Codex `thread_id` (resume id) recorded into `confirmed` from the hook-free `thread.started` JSONL stream event;
  continuation via `codex exec resume <thread_id>`.
- [ ] Rollout path recorded into `confirmed` without pretending it is hook-free: either discover the matching
  `$CODEX_HOME/sessions/.../rollout-*.jsonl` by `thread_id`, or populate it from the SessionStart payload only when the
  home is trust-enrolled. Discovery assumes stream `thread_id` == the rollout filename's `session_id` -- doc-asserted
  (`tests/fixtures/codex/README.md` calls `thread_id` "the resume/session id") but never binary-paired from one run;
  verify the equality as the first implementation step.
- [ ] GC the synthetic `<parent>-codex-<suffix>` transfer children the bridge accumulates (Phase 5e recorded debt).

| Test                   | Fixture                              | Assertion                                                          | Test File |
| ---------------------- | ------------------------------------ | ------------------------------------------------------------------ | --------- |
| Bridge CLI happy path  | mocked curation + codex Popen replay | manifest `runtime=codex`; `thread_id` parsed from `thread.started` | TBD       |
| Continuation           | recorded `thread_id`                 | relaunch invokes `codex exec resume <thread_id>` cross-CWD         | TBD       |
| Rollout discovery      | stream `thread_id` + session files   | matching rollout path recorded without requiring hooks             | TBD       |
| Transfer-child GC      | bridge run x2                        | synthetic children GC'd; real children untouched                   | TBD       |
| Real-codex E2E (@slow) | real codex, curation mocked          | one run tree: curation + codex events; `forge activity` shows both | TBD       |

## Phase 3 - Codex hook adapter/responder (gated on Phase 1 event coverage)

Stub -- expand when started. `CodexHookAdapter`/`CodexHookResponder` filling `src/forge/cli/hooks/protocols.py`;
snake_case payload -> `ActionContext`; carry the **`ActionContext.runtime` -> `origin` rename** (first real consumer;
direction resolved in `runtime_abstraction` Open Decisions 2026-06-09). `pretool_policy` rose to `"partial"` in the
Phase 1 closeout unit (2026-06-10); the adapter must emit strictly valid output (Codex fails OPEN on malformed hook
responses) and match Codex tool names (`Bash`, `apply_patch`).

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

- [x] `HookSupport` literal name for enrollment gating (Phase 0): **resolved 2026-06-10 -- `enrollment_gated`**, applied
  to both the registry `HookSupport` and the preflight `HookSeam` (renamed together so no half of the capability model
  retains the refuted `headless_inert`). The comment distinguishes it from `gated` (version floor -- Codex meets the
  floor yet untrusted hooks do not fire) and pins the preflight verdict as capability-not-state (never `active`).
- [x] Pre-enrollment posture (Phase 1): **resolved 2026-06-10 -- guided one-time ceremony.** Stage 83 found the
  `trusted_hash` is not black-box computable (0/13), so Forge cannot reliably forge `[hooks.state]` records; the
  installer ships a guided `codex` trust step instead. Re-openable only if a codex-cli source-dive recovers the hash
  algorithm (`hash-preimage.py --emit-state` is ready for that path). Programmatic pre-enrollment is therefore NOT the
  posture, sidestepping the "bypass another tool's review gate" concern for now.
- [x] Worktree/installer scope (Phase 6): **resolved 2026-06-10 (82w2, valid run) -- enrollment survives worktrees of
  the enrolled project, so project-scope registration is viable.** The project hook fired in a worktree with no folder
  `trust_level` and no `[hooks.state]` record at the worktree path; chained with 40b, that can only be a `trusted_hash`
  match on the definition (byte-identical command string). The mechanism (path-independent hash vs worktree->checkout
  canonicalization) is not distinguished, but the worktree-survival conclusion holds either way. **Phase 6 registers
  Codex hooks at project scope with a path-stable command string** (`.codex/config.toml` travels with git AND keeps
  trust across worktrees -- no per-worktree re-enrollment). Caveats for the installer: the command string must not embed
  the worktree/project path, or the hash diverges and trust breaks; one interactive ceremony per `CODEX_HOME` still
  seeds the first record; and **cross-project trust (a different repo reusing the command) is UNTESTED** -- a
  fresh-project probe is owed before any "one ceremony for all projects" story.
- [ ] Bridge CLI shape (Phase 2): flag on `forge session start` vs a dedicated verb.

## Closeout

1. Tick final checklist items with verification; change_log entry per phase (newest-first, Goal/Key changes/
   Verification).
2. Durable lessons proposed via `.forge/memory/shadow_impl_notes.md` (human promotes).
3. Design docs + end-user docs verified against shipped behavior (registry/design.md §5.5.5 in Phase 0; session manifest
   \+ `transfer.md`/`session.md` in Phase 2; hooks docs in Phase 3+).
4. `git mv docs/board/doing/codex_frontend docs/board/done/` as the final closeout commit once shipped and verified, so
   `main` lands with the card already in `done/`.
