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
rewritten to the round-3 facts and `design.md` §5.5.5 synced.

**Phase 2 shipped 2026-06-10** (see change_log):
`forge session start [name] --runtime codex --resume-from <parent> --task "..."` +
`forge session resume <name> --task "..."` over new `core/ops/codex_session.py`; manifest `runtime` + `confirmed.codex`;
snapshot keyed by real session name (synthetic-children debt retired structurally); all five acceptance rows green
including the live real-codex E2E, which also closed the two open probe-61 seams (rollout filename == stream thread_id;
stdin-prompt + `exec resume` recall).

**Phase 3 shipped 2026-06-11** (all six slices ticked below; see change_log): the `origin` rename, the apply_patch
parser, `CodexHookAdapter`/`CodexHookResponder`, and `forge hook codex-policy-check` -- PreToolUse scope, handler-only
(manual registration + trust enrollment until Phase 6).

**Phase 4 shipped 2026-06-11** (all six slices ticked below; see change_log):
`--context-delivery {initial-message, hook}` on `start --runtime codex`, the `forge hook codex-session-start` handler
(staged file -> strict `additionalContext` wire + delivery receipt), and post-turn receipt reconciliation into
`confirmed.codex.context_delivery` (incl. thread-id recovery + hook-sourced rollout). Handler-only; stages 85/86 are now
covered by the probe-debt harness run below.

**Phase 5 shipped 2026-06-11** (all seven slices ticked below; see change_log): Forge-managed interactive `codex`
sessions -- bare start opens the TUI, the interactive bridge carries the curated transfer (positional hold-instructions
framing or `--context-delivery hook`), bare resume reattaches via `codex resume <thread_id>`, thread identity reconciled
post-exit (observation receipt beats `find_rollouts_since` discovery; exactly-one-or-refuse). Registry
`interactive="beta" -> "default"`. The argv/rollout-head externals were closed by live probes post-ship (codex 0.139.0;
see the verification paragraph at the end of the Phase 5 section -- the launcher now passes `--sandbox` inside the
`resume` subcommand). Stage 87 is now covered by the probe-debt harness run below. **Next: Phase 6 (installer)**, with
both hook handlers shipped.

**Phase 6 review fixes shipped 2026-06-12** (see change_log): tracking preserved through unavailable/conflict re-runs
(`_execute_codex` None = no-authoritative-outcome -> keep prior tracking; manual-skip still authoritative), dedupe
rekeyed to `(event, command)` registration identity (wrong/bogus-event manual entries no longer satisfy it; matchers
deliberately ignored), and `sync` now counts codex actions + prints the ceremony next-steps. Two fail-confirmed
regression files + 3 CLI cases; sweep 6341 green; Docker installer 15/15.

**Phase 6 shipped 2026-06-12** (all six slices ticked below; see change_log): the codex-hooks installer module --
`forge extension enable` registers both Codex hooks as a managed TOML block in the config the **Forge install scope maps
to** (the resolved scope Open Decision: user -> `$CODEX_HOME/config.toml`, project/local -> `.codex/config.toml`),
presence-gated, best-effort (codex conflicts never block the Claude install), with trust-ceremony Next-steps guidance.
Registry `install_scopes` flipped. The trust ceremony itself stays operator-owned (unverifiable pre-turn); an optional
live-codex enable smoke could ride a future probe round. **Next: closeout** (all card phases shipped).

**Probe-debt harness slice 2026-06-12:** stages `85-policy-check-e2e`, `86-sessionstart-delivery-e2e`, and
`87-interactive-smoke` are now implemented under `scripts/experiments/codex-hooks/stages/` and wired into
`reproduce.sh all`. They convert the owed Phase 3/4/5 product-hook and real-TUI checks into runnable operator gates with
verdict files. Same-day operator run on codex-cli 0.139.0: **85 PASS** (product policy hook deny honored), **86 PASS**
(11,519-byte product SessionStart `additionalContext` delivery + receipt reconciliation), **87 PASS** (bare start, live
reattach memory, active-gate refusal, positional hold, hook-delivered interactive bridge, and read-only sandbox denial
all operator-confirmed with matching manifest/capture facts; the sandbox sentinel stayed absent). 87 now also records
the non-gating CLI UX observation that hook-delivered `SessionStart` `additionalContext` can be visibly rendered in the
TUI transcript even though delivery was passive, not a positional synthetic prompt; that prompt was codified after the
passing run, so the current PASS capture predates `results/observations.txt`.

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
- [x] Cross-project trust (the fresh-unrelated-repo probe the worktree item deferred): does ONE ceremony trust the
  command string in an UNRELATED repo, or only the enrolled project + its worktrees? Stage `84-fresh-project`
  (`scripts/experiments/codex-hooks/stages/84-fresh-project.sh`): a fresh `git init` repo at a never-seen `mktemp` path,
  byte-identical single-entry SessionStart, run with the path-stable user-level hook as a positive control; 84a (no
  folder trust) then 84b (folder-trust deconfound).
  - Assertion: a fresh repo's project hook fires (HOLDS) or not (SCOPED), gated by the user-level control firing; the
    verdict and captures are recorded.
  - **Done 2026-06-10 (codex 0.139.0): `[CROSS-PROJECT-TRUST-SCOPED]`.** Both legs proj=0 user=1 exit=0 self_enroll=no
    -- the turn ran (positive control fired) but the fresh repo's byte-identical project hook did NOT fire even with
    folder `trust_level`. Cross-project trust does NOT hold; 82w worktree survival was worktree->checkout
    canonicalization (a fire with no `[hooks.state]` record at the worktree path must map back to the enrolled
    checkout), not portable command-string trust. Captures at `~/.cache/forge-codex-hooks-probe/84-fresh-project/`
    (`results/verdict.txt`, `meta/user-config.84{a,b}-after.toml`). Reframes the installer-scope decision (above) as an
    open Phase-6 trade-off: project-scope = per-repo ceremony; user-scope = one-ceremony-for-all (path-stable).
    `bash -n`
    - shellcheck (parity with stage 82) + `pre-commit` clean on the stage/harness/README.
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

- [x] CLI shape decision -- **resolved 2026-06-10: `forge session start [name] --runtime codex --resume-from <parent>`**
  (rationale + scoping caveats recorded in Open Decisions: `--resume-from` requires `--runtime codex` in Phase 2;
  task/prompt surface needed for the headless turn; ai-curated default for the Codex path).
- [x] `runtime` field on the session manifest + runtime-aware launcher dispatch -- **shipped 2026-06-10**:
  `LaunchIntent.runtime` (registry ids; CLI maps `claude` -> `claude_code`; immutable -- `session set launch.runtime`
  rejected in `overrides.validate_key`); `start`/`resume` dispatch on `intent.launch.runtime` before any Claude
  predicate; `_launch_claude_for_session` backstop refuses codex manifests. Verified: `tests/src/session/test_models.py`
  (roundtrip + old-manifest reads), `test_overrides.py`, `tests/src/cli/test_session_codex.py` (42 tests: flag matrix,
  dispatch, backstop, show).
- [x] Codex `thread_id` recorded into `confirmed.codex` from the hook-free `thread.started` stream event; continuation
  via `forge session resume <name> --task` -> `codex exec resume <thread_id>` (probe-60 form-A argv, prompt on stdin,
  cross-CWD in the session's recorded worktree) -- **shipped 2026-06-10**. Verified:
  `tests/src/core/invoker/test_codex_stream.py`/`test_codex_invoker.py` (parse + argv),
  `tests/src/core/ops/test_codex_session.py` (resume argv/cwd/stdin, drift warning, missing-tid guidance).
- [x] Rollout path recorded honestly -- **shipped 2026-06-10**: discovered by `thread_id` glob
  (`core/runtime/codex_rollouts.py`), recorded with `rollout_source="discovered_by_thread_id"` only on a hit (None when
  absent; a future hook-sourced value gets its own label). The `thread_id` == rollout-filename equality was
  binary-paired from one live run by the standing E2E (see the @slow row below) rather than a one-shot probe run --
  probe stage 61 (`scripts/experiments/codex-hooks/stages/61-rollout-identity.sh`) is written + wired into
  `reproduce.sh` for the experiment harness, superseded for verification by the E2E.
- [x] Synthetic transfer-children debt retired **structurally** (better than GC'ing them): the CLI path keys the
  snapshot by the **real session name**, so `Derivation.context_file` GC-protects it; leftover synthetic
  `<parent>-codex-<suffix>` files from pre-Phase-2 manual bridge runs are swept by the existing orphan detection.
  Stale-snapshot guard (reference-checked, removes paired `.notes.md`) + two-phase rollback ship with the op. Verified:
  `tests/src/core/ops/test_gc.py::TestCodexTransferPinning`, `test_codex_session.py::TestStartCodexSessionGC` (zero
  orphans, nested-worktree ownership via `output_root`, rollback/retry, referenced-collision refusal).

| Test                   | Fixture                              | Assertion                                                          | Test File                                                                         |
| ---------------------- | ------------------------------------ | ------------------------------------------------------------------ | --------------------------------------------------------------------------------- |
| Bridge CLI happy path  | mocked curation + codex Popen replay | manifest `runtime=codex`; `thread_id` parsed from `thread.started` | `tests/src/core/ops/test_codex_session.py`, `tests/src/cli/test_session_codex.py` |
| Continuation           | recorded `thread_id`                 | relaunch invokes `codex exec resume <thread_id>` cross-CWD         | `tests/src/core/ops/test_codex_session.py`                                        |
| Rollout discovery      | stream `thread_id` + session files   | matching rollout path recorded without requiring hooks             | `tests/src/core/runtime/test_codex_rollouts.py`, `test_codex_session.py`          |
| Transfer-child GC      | real-name snapshot + synthetic file  | synthetic children GC'd; real children + notes untouched           | `tests/src/core/ops/test_gc.py`, `test_codex_session.py`                          |
| Real-codex E2E (@slow) | real codex, curation mocked          | one run tree: curation + codex events; rollout id; stdin resume    | `tests/integration/core/test_codex_session_start.py` (passed live)                |

## Phase 3 - Codex hook adapter/responder (shipped 2026-06-11)

Plan approved 2026-06-10 (full plan: `~/.claude/plans/effervescent-plotting-pascal.md`). **Scope decisions (user):**
PreToolUse only (Stop/UserPromptSubmit/SessionStart/PermissionRequest land with their Phase 4/5 consumers); deny =
strict stdout JSON (`hookSpecificOutput.permissionDecision: "deny"`) + exit 0, NOT Claude's exit-2 contract (Codex fails
OPEN on malformed hook output); **handler only** -- enforcement needs a manually registered + trust-enrolled Codex
PreToolUse hook until the Phase 6 installer. Load-bearing: every policy's `applies_to` gates on
`tool_name in ("Write", "Edit")`, so the adapter normalizes apply_patch ops (Add File -> Write, Update File -> Edit,
deletions skipped); `origin="codex"` + raw `tool_args` keep runtime truth.

- [x] Slice 1 -- `ActionContext.runtime` -> `origin` rename (mechanical, first; recorded decision: the two CLI leaves
  `cli/policy.py:577/:752` -> `forge_cli`; `%policy check` stays `claude_code`; fix the "flows into attribution"
  docstring claim).
  - Assertion: zero `runtime=` kwargs on `ActionContext` constructions in src+tests; policy/hooks/reactive/regression
    suites green; mypy clean.
  - **Done 2026-06-10**: field + docstring rewritten (notes the name deliberately does not invite `get_runtime()`); 47
    test kwargs across 11 files + the `result.origin` read assertion; 702 targeted unit tests green; mypy clean; the
    surviving `runtime=` hits are all other domains (UsageEvent/Attribution/LaunchIntent/target_runtime) by design.
- [x] Slice 2 -- apply_patch parser (`cli/hooks/codex_patch.py`, new): `PatchFileOp` + `parse_apply_patch` (`None` =
  malformed -> caller fails open; reuses `extract_added_lines`).
  - Assertion: fixture-literal Add, Update+`@@`, Move to, Delete, multi-file order, empty `[]`, malformed `None` all
    pass in `tests/src/cli/hooks/test_codex_patch.py`.
  - **Done 2026-06-10**: 24 parser cases green incl. CRLF, End-of-File tolerance, Delete-with-body malformed, `path` =
    post-op Move-to target.
- [x] Slice 3 -- `CodexHookAdapter`/`CodexHookResponder` (`cli/hooks/codex_policy.py`, new) + protocol cardinality
  `build_context` -> `build_contexts(...) -> list[ActionContext]` (clean break; Claude wire bytes unchanged); deny
  reason text shared via extracted `format_deny_text`/`format_needs_review_text`.
  - Assertion: deny JSON round-trips to the probe-pinned key set exactly; protocol-conformance test covers both pairs;
    `test_policy_feedback.py` untouched and green (byte guard).
  - **Done 2026-06-10**: 16 adapter/responder cases green; conformance test extended with the Codex pair; one missed
    `build_context` caller surfaced by the full sweep (`test_bug_usage_session_attribution_contract.py`) and updated.
- [x] Slice 4 -- `forge hook codex-policy-check` + engine-assembly extraction (`build_hook_engine`,
  `register_supervisor_and_restore`, `_persist_policy_decisions` with explicit aggregated `engine_state` -- `evaluate()`
  clears `_collected_state` per call, so the per-file loop MUST accumulate); cross-file precedence deny > needs_review >
  warn/allow; tests-first ordering.
  - Assertion: `policy_check` diff confined to two helper call lines; state-aggregation regression (tests-file +
    docs-file patch persists `tests_touched`) and payload-cwd regression (process CWD outside project, payload cwd
    inside, unindexed manifest) pass; stdout-strictness regression (non-empty stdout == exactly
    `{"hookSpecificOutput"}`) passes; stdout/stderr asserted separately (Click 8.4).
  - **Done 2026-06-11**: 17 command cases green incl. both pinned regressions, deny-beats-needs_review co-occurrence,
    and the two cascade shared-wiring cases (short-circuit + escalation through the extracted helper); 6118
    unit+regression sweep green; mypy/pyright/pre-commit clean.
- [x] Slice 5 -- Docker integration: `TestCodexPolicyCheckDocker` in `tests/integration/docker/test_policy_hooks.py`
  (deny = exit 0 + stdout JSON; state across invocations; fail-open paths); suite run before AND after the slice-4
  extraction; probe-harness README gains the operator-gated "stage 85" enrolled E2E follow-up note.
  - Assertion: `./scripts/test-integration.sh tests/integration/docker/test_policy_hooks.py` green.
  - **Done 2026-06-11**: 17/17 (`test_policy_hooks.py` -- 7 new Codex cases + 10 pre-existing unchanged, proving the
    extraction moved no Claude bytes) + 9/9 `test_supervisor_e2e.py` (cascade path through the extracted registration);
    stage-85 follow-up note added to the probe README.
- [x] Slice 6 -- docs/board sync: design.md §4.1.4/§4.1.5 (+§5.5.5 mirror check), protocols.py docstrings, registry
  codex note sentence (`pretool_policy` stays `"partial"`), end-user hook.md, card Deliverable 3 annotation, change_log
  entry.
  - Assertion: no stale "Phase 6 adapter" claim on normative surfaces; `make pre-commit` clean.
  - **Done 2026-06-11**: §4.1.4 documents both shipped pairs + normalization + handler-only caveat; §4.1.5 documents the
    shared reason text + per-runtime wire framing; §5.5.5 unchanged (its capability claims stay accurate --
    `pretool_policy` stays `"partial"`); registry note gains the shipped-handler sentence; hook.md gains the
    codex-policy-check section; change_log entry added.

## Phase 4 - SessionStart transfer delivery with initial-message fallback (gated on Phase 1 30e -- PASSED)

Plan approved 2026-06-11 (full plan: `~/.claude/plans/expressive-zooming-rainbow.md`). **Scope decisions (user):**
`--context-delivery {initial-message,hook}` on `start --runtime codex` (default initial-message; Click default `None` --
the reject-list pattern); hook-undelivered = fail loud (keep session,
`confirmed.codex.context_delivery = "hook_undelivered"`, exit 1 with ceremony/delete-and-retry tips); handler name
`codex-session-start` is trust-durable (renaming breaks `trusted_hash` enrollment); handler-only like Phase 3 (manual
registration + ceremony until Phase 6). Load-bearing: enrollment is unverifiable pre-turn, so hook mode = stage
`compose_codex_handoff_context(body)` to `<session_dir>/codex/pending-context.md`, prompt carries only the task, the
hook consumes the staged file and writes `context-receipt.json`, and the CLI reconciles post-turn (receipt also recovers
`thread_id` when the stream missed `thread.started`; receipt `transcript_path` supersedes glob discovery as
`rollout_source="session_start_hook"`). One-shot invariant: staged file never survives the start turn (consumed or
cleared); resume defensively clears.

- [x] Slice 1 -- composition split (`compose_codex_handoff_context`, byte-pinned golden FIRST) +
  `session/codex_handoff.py` staging module (pending/receipt paths, atomic stage/consume/clear/read).
  - Assertion: golden test pins today's initial-message bytes pre- and post-refactor; handoff module roundtrip/one-shot/
    malformed-receipt cases green; stale "deferred to Phase 6" bridge docstrings rewritten.
  - **Done 2026-06-11**: golden ran green against pre-refactor code first, then the split; receipt-write failure
    deliberately leaves pending unconsumed (nothing delivered the receipt can't vouch for). 29 tests
    (`test_codex_handoff.py` 16 + `test_codex_bridge.py` 13) green; mypy clean.
- [x] Slice 2 -- `forge hook codex-session-start` (new `cli/hooks/codex_transfer.py`; strict one-line wire JSON pinned
  to the probe response fixture; never reads the manifest -- only `store.session_dir`; receipt-before-stdout).
  - Assertion: happy path stdout byte-equals formatter + staged consumed + receipt fields; all silent no-op paths exit 0
    with empty stdout; wire-strictness + payload-cwd rooting regressions.
  - **Done 2026-06-11**: 9 new cases in `test_codex_session_start.py` (delivery + strict-wire key sets + rooting + 6
    silent no-ops incl. the resume case); full hooks package 146 green; mypy clean. Command docstring records the
    trust-durable-name constraint.
- [x] Slice 3 -- bridge staging param + `_temporary_run_env(..., forge_root=)` sets `FORGE_FORGE_ROOT` (worktree
  rooting; call site passes the CHILD's forge_root).
  - Assertion: staged file exists at Popen time with framed body; prompt == task exactly; default mode byte-identical
    (no staging artifacts); env restore cases.
  - **Done 2026-06-11**: `FORGE_FORGE_ROOT` passed unconditionally (`transfer_root` = the child's forge_root) so BOTH
    codex hooks resolve worktree sessions; Popen side_effect snapshots staging+env at spawn time. 18 bridge tests + 215
    ops-package tests green; mypy clean.
- [x] Slice 4 -- op wiring: `CodexConfirmed.context_delivery`, pre-turn seam guard (disabled/unknown/managed_suppressed/
  untrusted fail fast; enrollment_gated proceeds), `_reconcile_hook_delivery` (match / thread-id recovery / undelivered
  \+ clear), resume defensive clear, `--context-delivery` flag (Click default `None` + reject list + exit-1 render).
  - Assertion: hook-mode happy path, not-fired, mismatched-receipt, thread-id recovery, per-seam guard, default-mode
    `initial_message`, resume leftover clear, GC/delete pinning, plain-Claude-start regression all green.
  - **Done 2026-06-11**: receipt also recovers `thread_id` when the stream misses `thread.started` (resumability
    preserved; receipt `transcript_path` supersedes glob as `rollout_source="session_start_hook"`); the
    plain-Claude-start None-default regression pins the reject-list interaction. 1270 tests (ops + session + CLI
    packages) green; mypy clean on all of `src/forge/`.
- [x] Slice 5 -- Docker integration (`TestCodexSessionStartDocker`, real wheel CLI) + probe README stage-86
  operator-gated note (enrolled E2E incl. multi-KB additionalContext; **resolved 2026-06-12 by stage 86 PASS** with an
  11,519-byte transfer).
  - Assertion: `./scripts/test-integration.sh tests/integration/docker/test_policy_hooks.py` green.
  - **Done 2026-06-11**: 20/20 (3 new SessionStart delivery cases -- staged->wire+receipt, nothing-staged silent,
    malformed-stdin fail-open; 17 pre-existing unchanged). Stage-86 note records the composed-loop + payload-size
    verification owed to the operator round.
- [x] Slice 6 -- docs/board sync: design.md §3.9 (shipped opt-in delivery) + §3.5 (receipt is the hook's only write),
  end-user hook.md (probe-pinned NESTED registration TOML) + session.md/transfer.md, card Deliverable 4 annotation,
  change_log entry; narrow grep gate (src/, design.md, end-user/, active card -- excluding done/ + historical change_log
  entries).
  - Assertion: no stale "deferred to Phase 6" delivery claim on the normative surfaces; `make pre-commit` clean.
  - **Done 2026-06-11**: grep gate clean (only this checklist's meta-references remain); `make pre-commit` clean (mypy
    caught + fixed a `HookSeam` literal annotation in the seam-guard test); full sweep 5773 unit + 399 regression green.

## Phase 5 - Interactive Codex frontend (in progress 2026-06-11)

Plan approved 2026-06-11 (full plan: `~/.claude/plans/wise-wiggling-wolf.md`). **Scope decisions (user):** bare =
interactive (omitting `--task` on `start --runtime codex` / codex `resume` launches/reattaches the TUI; `--task` keeps
meaning headless, byte-unchanged); interactive composes with `--resume-from` (curated transfer rides the positional
initial prompt, or `--context-delivery hook`); thread-id capture = post-exit filesystem discovery (zero-setup) + an
enrolled-home **observation receipt** from `codex-session-start` (separate `observation-receipt.json`; the Phase 4
delivery-receipt contract stays byte-stable); `install_scopes` stays `()` (Phase 6 installer) -- Phase 5 flips only
`interactive="beta" -> "default"`. Load-bearing: the positional `[PROMPT]` starts a model turn (not passive context), so
the interactive framing carries explicit hold instructions; hook delivery is the only truly passive path. The TUI owns
stdout (no JSONL stream), so interactive turns emit NO usage event and `confirmed.codex` is reconciled post-exit
(observation receipt beats discovery; ambiguity refuses to guess). Two timestamps: `operation_started_at` (activity
summary `since`) vs `rollout_discovery_started_at` (tight pre-launch discovery window). `run_identity` is REQUIRED on
the launcher (the TUI must share the curation event's root). Bare starts record `context_delivery=None` (the field is a
transfer-delivery fact).

- [x] Slice 1 -- discovery + receipt groundwork: `codex_rollouts.py` `DiscoveredRollout`/`parse_rollout_filename`/
  `find_rollouts_since` (mtime filter; head-cwd narrowing; ambiguity returned to caller); `codex_handoff.py`
  `ObservationReceipt` + path/write/read/clear.
  - Assertion: post-launch rollout found with thread_id from filename; older excluded; same-cwd ambiguity returns both;
    observation roundtrip/malformed/clear; `receipt_path() != observation_receipt_path()`.
  - **Done 2026-06-11**: filename parse is strict-timestamp/opaque-id (Phase 2 stance); narrowing only applies when it
    leaves >= 1 candidate (unknown head shape never eliminates the true rollout); canonical-path compare handles macOS
    /var -> /private/var. 53 tests green (`test_codex_rollouts.py` + `test_codex_handoff.py`); mypy clean.
- [x] Slice 2 -- hook observation receipt: `codex_transfer.py` branches on **pending-exists** (not the consume return --
  a staged receipt-write failure must NOT produce an observation receipt); nothing-staged + managed session writes the
  observation receipt, stays silent; unmanaged stays zero-write.
  - Assertion: mutual exclusivity incl. the staged-failure case; Phase 4 regression -- `_reconcile_hook_delivery` never
    reads the observation file (observation-without-delivery still reconciles `hook_undelivered`).
  - **Done 2026-06-11**: 6 new hook-level cases (`TestObservationReceipt`) + the resume-case docstring/assertion update
    - the ops-level Phase 4 regression (`test_observation_receipt_never_read_as_delivery`). Full hooks package 153
      green; `test_codex_session.py` 49 green; mypy clean.
- [x] Slice 3 -- bridge assembly extraction + interactive launcher: `assemble_codex_transfer` (golden-pinned
  byte-identity), `sanitize_codex_child_env` (behavior-neutral), `compose_codex_interactive_context` (hold
  instructions), new `session/codex_invoke.py` `invoke_codex_interactive` (REQUIRED `run_identity`; foreground
  `subprocess.run`; argv `codex --sandbox X [resume tid] [prompt]`).
  - Assertion: bridge golden byte-identical; four auth postures pinned; launcher argv/env exact (FORGE_SESSION/
    FORGE_FORGE_ROOT/root triple, DEPTH+1, no parent-run var).
  - **Done 2026-06-11**: bridge keeps its early strategy/parent checks (fail before the ~20s preflight; the helper
    revalidates); the four auth postures exercise the extracted helper transitively through the unmodified
    `prepare_codex_request` tests. 86 tests green (bridge incl. golden + invoker + new `test_codex_invoke.py` 13 + ops);
    mypy clean. The `codex resume --help` argv was verified live post-ship (see the verification paragraph below): the
    builder was corrected to pass `--sandbox` inside the `resume` subcommand, where it is documented.
- [x] Slice 4 -- interactive ops (`core/ops/codex_interactive.py`, new): `start_interactive_codex_session` +
  `reattach_codex_session`; `ROLLOUT_SOURCE_POST_EXIT="discovered_post_exit"`; two timestamps; receipt-beats-discovery;
  `context_delivery=None` for bare; rollback only before the TUI launches; `run_with_active_session` wrap; no
  `emit_codex_usage`.
  - Assertion: bare/bridge/hook matrices; precedence + planted-stale-receipt; ambiguity refusal; two-timestamp pin;
    run-identity equality pin; reattach guards verbatim-consistent with `continue_codex_session`.
  - **Done 2026-06-11**: guards shared by extraction (`resolve_codex_session`/`require_codex_thread_id` moved out of
    `continue_codex_session` -- messages identical by construction); hook-undelivered still records a
    discovery-recovered thread (delivery and identity are separate facts); a TUI spawn failure keeps the session (the
    rollback boundary is the launch). 22 new tests (`test_codex_interactive.py`); blast radius 1484
    (ops+session+invoker+hooks) green; mypy clean on 14 ops/session files.
- [x] Slice 5 -- CLI matrix + registry flip + session show: `session_codex.py` rework (bare=interactive; exact errors
  for `--task`-alone and orphan transfer flags); `session_lifecycle.py` cross-project resume restructure (unscoped
  fallback always runs on scoped miss; codex dispatches, Claude refusal byte-identical); `_post_exit_render` via lazy
  import (cycle: `session_lifecycle.py:101` already imports `session_codex`); registry `interactive="default"`;
  `session show` Delivery line.
  - Assertion: full matrix; headless rows byte-unchanged; plain-Claude None-default regression green; cross-project
    matrix (bare codex resolves+dispatches, bare Claude keeps today's hint+exit 1); registry flip pinned.
  - **Done 2026-06-11**: bare resume reuses the Claude reconnect refusal verbatim with NO `--force` escape (`--force`
    stays in the Codex-rejected flag list -- two TUIs on one thread would interleave a rollout); `run_codex_resume` now
    takes the resolved manifest (the active gate needs its `forge_root`); the cross-project `cross_project` flag defers
    the Claude refusal until after runtime dispatch (resolution can't know the runtime). Accepted edge change: bare
    cross-project AmbiguousSessionError now surfaces via `handle_session_error` instead of the hint (the unscoped lookup
    runs where it previously didn't). `test_session_codex.py` 70 green (was 36; obsolete `requires --task`/
    `requires --resume-from` rows replaced per matrix); full `tests/src/cli` 1761 green; runtime package 80 green
    (registry pin flipped); mypy clean.
- [x] Slice 6 -- Docker integration + stage 87: `TestCodexSessionStartDocker` observation cases (pre-existing 20
  unchanged); probe README stage-87 operator-gated checklist (bare/bridge/hook/reattach/--sandbox; multi-KB positional;
  hold-instructions no-autonomous-action).
  - Assertion: `./scripts/test-integration.sh tests/integration/docker/test_policy_hooks.py` green.
  - **Done 2026-06-11**: nothing-staged Docker case renamed to pin the observation receipt (payload identity +
    `observed_at`) with silent stdout/stderr through the real wheel CLI; staged case pins per-turn mutual exclusivity
    (no observation); unmanaged case pins zero writes. Stage-87 note added beside 85/86. Docker `test_policy_hooks.py`
    21 green (run as the script's underlying
    `uv run pytest -m integration tests/integration/docker/test_policy_hooks.py` -- the wrapper's preamble is duplicated
    by the `forge_test_image` fixture and this file needs no LiteLLM).
- [x] Slice 7 -- docs/board sync: design.md §3.9/§3.5/§3.4/§4.0; transfer.md "later phase" note removed; session.md +
  hook.md; card Deliverable 5 annotation; change_log entry; grep gate (no stale "not yet supported" interactive claim on
  normative surfaces); `make pre-commit` clean; full unit sweep.
  - **Done 2026-06-11**: design.md gained the §3.9 "Interactive Codex sessions" paragraph + post-exit capture facts in
    Recorded-Codex-facts, §3.4/§3.5/§3.10 receipts-plural updates, §4.0 command rows, runtime-matrix bullet
    (`interactive="default"`); session.md "Interactive Codex sessions" section + command block; transfer.md note now
    points at it; hook.md observation bullet. Card Deliverable 5 marked SHIPPED with the deferred list. Grep gate found
    one stale claim outside the planned set -- the `codex_bridge.py` module docstring still called the user-facing
    command "Phase 6" -- fixed. Full sweep `tests/src tests/regression -m "not integration"` 6265 green; pre-commit
    clean (second run after isort/black/mdformat fixes).

Impl-time verification CLOSED 2026-06-11 (live probes, codex 0.139.0, after the tooling outage lifted): (a)
`codex resume --help` pins `codex resume [OPTIONS] [SESSION_ID] [PROMPT]` with SESSION_ID as "UUID or session name,
UUIDs take precedence" AND its own `-s/--sandbox` -- the builder was corrected from root-level
`codex --sandbox X resume <tid>` (propagation into the subcommand flow not guaranteed) to the documented
`codex resume --sandbox X <tid>`; argv pin updated, 13 launcher tests + 20 interactive-ops tests green. (b) Root
`codex --help` pins `-s/--sandbox` and the positional `[PROMPT]` for the bare/bridge start form. (c) A real
`~/.codex/sessions` rollout head matches the parser exactly (`type=session_meta`, `payload.cwd`;
`parse_rollout_filename` + `_rollout_head_cwd` verified against the live file), and the filename timestamp is LOCAL time
vs the payload's UTC -- confirming the filter-by-mtime decision. **Closed 2026-06-12 by stage 87 PASS:** behavioral TUI
smoke covered hold instructions, multi-KB positional delivery, enrolled hook delivery, live reattach, active-gate
refusal, and read-only sandbox denial.

## Phase 6 - Installer Codex support (shipped 2026-06-12)

**Scope decision (user, 2026-06-12): Codex hook registration mirrors the Forge install scope** (see Open Decisions).
Mapping: `user` -> `$CODEX_HOME/config.toml` (default `~/.codex/config.toml`); `project` AND `local` ->
`<project_root>/.codex/config.toml` (Codex has no settings.local analog -- both Forge project scopes target the one
per-project config; the committed-vs-not distinction is the user's gitignore choice, documented).

**Design decisions (recorded at plan time):**

- **No `codex.preset.json`** (the card's question-marked sketch is rejected): the Claude preset exists for user-owned
  permissions/env; hooks always come from the builtin even there. The Codex registration is hooks-only AND the command
  string is trust-hashed -- a user-editable surface would invite silently breaking enrollment. Builtin-only entries in
  `install/codex_hooks.py`.

- **Registration mechanism = marker-delimited managed TOML block** appended to `config.toml` (`# >>> forge hooks >>>` /
  `# <<< forge hooks <<<`): codex-cli owns that file (auth, model config, comments), so Forge never rewrites or
  normalizes it -- no TOML-writer dependency added. Pre-checks parse with stdlib `tomllib` (unparseable file or
  non-array `hooks.<event>` -> conflict; our command already present anywhere -> skip); post-merge content is
  re-validated with `tomllib` before the atomic write; backup mirrors the settings pattern
  (`.config.toml.forge.backup.<ts>`). Uninstall removes the marker block only; Forge commands found OUTSIDE the markers
  are warned about and left (user-owned now).

- **Trust-byte stability**: the rendered entry bytes (probe-pinned nested `[[hooks.<event>]]` shape, command strings
  `forge hook codex-session-start` / `forge hook codex-policy-check`, timeout 60) are golden-pinned -- sync/update
  replaces the block with identical bytes so existing enrollment survives (82e: the hash covers the definition).
  `codex-policy-check` registers PreToolUse with NO matcher (probe: `matcher="shell"` never fired; the adapter filters
  apply_patch vs Bash itself).

- **Module + gating**: new settings-only `InstallModule.CODEX_HOOKS` (`codex-hooks`) in `standard` + `full` profiles,
  **presence-gated** -- skipped with a visible notice when the `codex` binary is absent (registry `is_installed()`;
  system-boundary degrade, never silent). `--with codex-hooks` on a codex-less machine still skips with the notice.

- **Enrollment is the user's ceremony**: enable prints a Next-steps block (run `codex` interactively, grant trust; hooks
  are inert until then). The installer never claims enrollment (unverifiable pre-turn, Phase 1).

- [x] Slice 1 -- `install/codex_hooks.py`: builtin entries, `CODEX_HOOK_EVENTS` (the probe-pinned 10) + event-name
  validation (the binary loads bogus names silently), block render, target-path mapping, merge/unmerge/detect.

  - Assertion: golden block bytes pinned; merge is idempotent + dedupes against user-moved entries; unparseable config
    and non-array `hooks.<event>` -> conflict without touching the file; post-validate failure restores the original;
    unknown event name raises at plan time; `CODEX_HOME` env honored.
  - **Done 2026-06-12**: 40 tests (`test_codex_hooks.py`) incl. the trust-byte golden, the inline-table
    (`hooks = { SessionStart = [] }`) post-validation-only failure with no write and no backup, full-vs-partial manual
    registration (skip vs conflict), and whitespace-only file deletion on remove; mypy clean.

- [x] Slice 2 -- installer wiring: `InstallModule.CODEX_HOOKS`, profile membership, presence gating, `InstallPlan` codex
  section, additive `Installation` tracking fields, plan/init/uninstall/update integration.

  - Assertion: plan shows codex entries only when module on + binary present; init writes block + backup + tracking;
    re-run skips (idempotent); uninstall removes block + tracking; update replaces block byte-identically; old tracking
    manifests (no codex fields) still read.
  - **Done 2026-06-12**: `TestInstallerCodexHooks` (11 cases) incl. update byte-stability, conflict-never-blocks (the
    Claude install completes), tampered-tracking-path refusal, and module-dropped tracking preservation; install package
    286 green. Found + fixed a test-isolation hole: the suite wrote the block into the REAL `~/.codex/config.toml`
    (restored from the Forge backup); new autouse `isolate_codex_home` in `tests/conftest.py` makes the leak
    structurally impossible.

- [x] Slice 3 -- CLI: enable completion prints the ceremony Next-steps when codex hooks were installed; status renders
  the codex registration; disable removes it; plan rendering shows the codex section.

  - Assertion: enable/status/disable CLI tests; no `Tip:` outside output.py (existing invariant test stays green).
  - **Done 2026-06-12**: `TestEnableCodexHooks` (5 end-to-end CliRunner cases: ceremony next-steps, unavailable notice,
    status human + `--json` codex fields, disable preview + removal); 4 existing mock plans gained `codex = None`;
    `test_extension_enable.py` 44 green; Tip-invariant untouched.

- [x] Slice 4 -- registry flip: codex `install_scopes` `()` -> `("user", "project", "local")` + note rewritten to the
  shipped mapping.

  - Assertion: registry/CLI tests updated; `forge runtime list --json` renders the scopes.
  - **Done 2026-06-12**: registry + note updated (installer paragraph replaces the open-trade-off sentence); 87
    runtime/CLI tests green; live `forge runtime list --json` renders `install_scopes: ['user', 'project', 'local']`.

- [x] Slice 5 -- Docker integration: wheel-CLI enable with a codex shim on PATH writes the block; disable removes it;
  presence-gated skip without the shim.

  - Assertion: `./scripts/test-integration.sh tests/integration/docker/test_installer.py` green.
  - **Done 2026-06-12**: `TestCodexHooksModule` (3 cases: full enable->status->disable cycle with a codex shim,
    presence-gated skip, user-content preservation through the cycle); file 15/15 green (12 pre-existing unchanged).

- [x] Slice 6 -- docs/board sync: design.md §5 install model + §4.1.4/§3.9 "manual registration until Phase 6" caveats
  rewritten to installer-registered (+ceremony); design_appendix §E module table + codex registration subsection;
  end-user hook.md "not auto-installed" bullets replaced; change_log entry.

  - Assertion: grep gate -- no stale "not auto-installed"/"installer support is planned" claim on normative surfaces;
    `make pre-commit` clean.
  - **Done 2026-06-12**: design.md §5 (seven modules + codex-hooks paragraph) + §4.1.4 (handler-only ->
    installer-registered + ceremony); appendix §E.2 row + new §E.6; hook.md both codex sections reframed (manual TOML
    kept as reference); QA checklist 2.10/2.11 added (count 535 -> 541); grep gate clean (remaining "manual
    registration" hits document the dedupe behavior); `make pre-commit` clean; full unit sweep 6329 green; change_log
    entry added.

| Test                    | Fixture                               | Assertion                                                     | Test File                                        |
| ----------------------- | ------------------------------------- | ------------------------------------------------------------- | ------------------------------------------------ |
| Block merge idempotent  | user config.toml with comments + auth | two installs -> one block, user bytes untouched               | `tests/src/install/test_codex_hooks.py`          |
| Conflict fail-closed    | config.toml with `hooks` as non-array | plan conflict, file unmodified                                | `tests/src/install/test_codex_hooks.py`          |
| Trust-byte stability    | installed block, then update()        | block bytes identical pre/post sync                           | `tests/src/install/test_codex_hooks.py` (golden) |
| Scope mapping           | user/project/local installs           | user -> $CODEX_HOME, project+local -> .codex/config.toml      | `tests/src/install/test_codex_hooks.py`          |
| Presence gating         | no codex on PATH                      | module skipped with visible notice, no file created           | `tests/src/install/test_installer.py`            |
| Uninstall block removal | enabled then disabled                 | marker block gone, user content + outside-marker entries kept | `tests/src/install/test_installer.py`            |
| Wheel-CLI e2e           | Docker, codex shim on PATH            | enable writes block, disable removes, skip without shim       | `tests/integration/docker/test_installer.py`     |

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
  canonicalization) is not distinguished, but the worktree-survival conclusion holds either way. **\[Superseded by stage
  84 -- see below: the project-vs-user scope choice is reopened as a trade-off.\]** The round-2 read was that Phase 6
  would register at project scope with a path-stable command string (`.codex/config.toml` travels with git AND keeps
  trust across worktrees -- no per-worktree re-enrollment). Caveats for the installer: the command string must not embed
  the worktree/project path, or the hash diverges and trust breaks; one interactive ceremony seeds the first record.
  **Cross-project trust is now TESTED (stage 84, codex 0.139.0, 2026-06-10): it does NOT hold** -- a fresh unrelated
  repo's byte-identical project hook stays untrusted even with folder trust (proj=0, user=1), so the worktree survival
  (82w) was worktree->checkout canonicalization, not portable command-string trust. **Installer scope is now an open,
  informed Phase-6 trade-off (not re-resolved here -- decided when Phase 6 builds the installer):** project-scope
  `.codex/config.toml` travels with git and survives worktrees but costs a ceremony *per repo*; USER-scope
  `$CODEX_HOME/config.toml` is path-stable so one ceremony covers every project (stage 84's user-level control fired
  unprompted from the fresh repo) but is not committed with the repo -- **user scope is the leading
  one-ceremony-covers-all candidate.** **RESOLVED 2026-06-12 (user decision): Codex registration mirrors the Forge
  install scope** -- `user` -> `$CODEX_HOME/config.toml`, `project`/`local` -> `<project_root>/.codex/config.toml`
  (Codex has no settings.local analog). Accepted trade-off: project/local installs cost one trust ceremony per repo; the
  enable Next-steps block names the ceremony explicitly so a registered-but-unenrolled install is never mistaken for
  active enforcement. See the Phase 6 plan for the mechanism.
- [x] Bridge CLI shape (Phase 2): **resolved 2026-06-10 -- flag shape on `forge session start`:**
  `forge session start [name] --runtime codex --resume-from <parent>`. Rationale: this is a session-creation operation
  (new manifest with a `runtime` field, runtime-specific `confirmed` facts, runtime-aware launcher dispatch), so it
  belongs on `start`; `runtime` stays a first-class session attribute rather than a Codex side path; it composes with
  Phase 5 (bare `forge session start --runtime codex` later means "start Codex directly" -- `--resume-from` is just the
  derivation source); and a dedicated verb would freeze today's Claude->Codex hop as a permanent concept when the
  architecture wants runtime-neutral session launch. Scoping caveats for the slice plan: (a) Phase 2 rejects
  `--resume-from` without `--runtime codex` -- with the default (Claude) runtime it would be a synonym of
  `resume --fresh`, and same-runtime derivation keeps its existing verbs (`resume --fresh`/`fork`); broadening later
  stays open. (b) The headless Codex turn needs an initial task: `bridge_session_to_codex` takes a required `task`
  composed with the transfer body into the `codex exec` initial message, and `start` has no prompt argument today -- the
  task/prompt surface spelling is decided in the slice plan. (c) The Codex path defaults `--strategy ai-curated` (the
  shipped bridge default; design.md §3.9 names curated transfer the cross-boundary substrate), deliberately diverging
  from `resume --fresh`'s `structured` default (whose LLM-free hot path was a recorded Phase 1 closeout decision of
  `runtime_abstraction`).
- [x] Task surface spelling (caveat (b) above): **resolved 2026-06-10 -- `--task TEXT` on both `start` and `resume`**,
  required with `--runtime codex` / Codex sessions and rejected otherwise (no positional prompt -- it would conflict
  with `start`'s optional `[name]` argument). Deferred without prejudice: `--task-file`/stdin task input (spell it when
  a real task outgrows a shell argument), and `--model` for Codex (today the flag goes through the Claude-specific
  `resolve_direct_model_pin`; rejected with codex, wiring a Codex model mapping later is cheap).

## Closeout

1. Tick final checklist items with verification; change_log entry per phase (newest-first, Goal/Key changes/
   Verification).
2. Durable lessons proposed via `.forge/memory/shadow_impl_notes.md` (human promotes).
3. Design docs + end-user docs verified against shipped behavior (registry/design.md §5.5.5 in Phase 0; session manifest
   \+ `transfer.md`/`session.md` in Phase 2; hooks docs in Phase 3+).
4. `git mv docs/board/doing/codex_frontend docs/board/done/` as the final closeout commit once shipped and verified, so
   `main` lands with the card already in `done/`.
