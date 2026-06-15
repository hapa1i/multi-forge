# Change Log

Completed-work record for Forge implementation sessions.

## Maintenance

- Updated by the memory writer with `strategy=changelog`, and by humans when closing a phase.
- Add compact entries for completed work only. Pending tasks belong in card checklists.
- Follow `docs/developer/board-contract.md` "Change Log Policy": each entry needs Goal, Key changes, and Verification.
- Keep entries short. Do not list every file unless the file list is the point of the work.
- Use newest-first order so active work stays near the top.
- When this file approaches the documentation size limits, compact the oldest entries at the bottom into a dated summary
  that preserves decisions, verification, and deferred items. Archive detailed old entries only if the summary is still
  too large.
- Check size before long sessions or when the file feels slow to scan:

```bash
wc -l docs/board/change_log.md
./scripts/count-tokens.py --model <agent-model> docs/board/change_log.md
```

## Entries

> Format: `## YYYY-MM-DD`, then `### Phase X.Y: Short Title`, with `**Goal**:`, `**Key changes**:` as bullets, and
> `**Verification**:`. Use newest-first order. See `docs/developer/board-contract.md` "Change Log Policy" for the full
> spec.

## 2026-06-15

### same_dir_transfer_forks: decouple transfer mode from worktree isolation in `forge session fork`

**Goal**: Let a same-directory fork run a curated *transfer* launch (fresh child Claude session + assembled parent
context) instead of always native `--resume --fork-session`, and stop silently dropping `--strategy`/`--inline-plan` on
same-dir forks (the bug from the supervisor investigation).

**Key changes** (`src/forge/cli/session_fork.py`, `manager.py`, `session_lifecycle.py`):

- **Auto-switch**: explicit `--strategy`/`--inline-plan` on a same-dir fork resolves `resume_mode = "transfer"` pre-fork
  (gated on `resume_mode is None`, so `--resume-mode native-relocate` never auto-switches) and prints a non-silent info
  line. The existing `--resume-mode transfer` is the explicit same-dir-legal opt-in; `native-relocate` stays
  worktree/`--into`-only. No `--fresh-transfer` flag.
- **Branch widened, not duplicated**: the worktree-transfer branch predicate becomes
  `uses_fresh_transfer = (is_worktree_fork and not native_relocate) or same_dir_transfer`, resolving `worktree_path` per
  case. Six launch refs (sidecar `session_id`/`resume_id`/`fork_session`/**`register_fork`**/`system_prompt_file`; host
  `active_claude_session_id`) now key on it. `register_fork` is load-bearing: with `fork_session=False` it is the only
  thing setting `FORGE_FORK_NAME`. Budget preflight widened to `is_cross_dir or resume_mode == "transfer"`.
- **Derivation correct under partial failure**: `manager.fork_session` writes the `"transfer"` baseline (+ pre-recorded
  `context_file`) for same-dir transfer, so a best-effort CLI `_persist_fork_transfer_derivation` refinement failure
  can't leave a requested transfer fork recorded as `"native"`.
- **Deferred-resume guard**: `_get_deferred_same_dir_fork_resume_id` returns `None` when
  `derivation.resume_mode == "transfer"`, before the confirmed-state guard — a failed UUID pre-seed can no longer
  silently native-resume a `--no-launch` transfer fork.
- **Docs**: `design.md`, `end-user/session.md`, `cli_reference.md` updated; help strings dropped "worktree-only"
  framing.

**Verification**: 41 unit tests green (7 new same-dir CLI tests, 3 regression incl. a direct guard test, new manager
derivation test); 4 integration tests green (new same-dir transfer argv has `--session-id` +
`--append-system-prompt-file` and lacks `--resume`/`--fork-session`; 3 adjacent fork-launch regressions unchanged);
`make pre-commit` clean.

## 2026-06-14

### supervisor_shadow_sampling: measure the cascade's false-aligned rate (3 slices, one PR)

**Goal**: Audit how often the cascade's tier-1 `allow` short-circuits a frontier check the frontier would have blocked,
without slowing the PreToolUse hook.

**Key changes**:

- **Slice 1 (capture, inert)**: `SupervisorConfig` gains `shadow_sample_rate`/`shadow_max_per_session`/`shadow_seed`
  (range-validated in `__post_init__`, so a bad `session set` override surfaces as `InvalidOverrideValueError`). New
  `policy/semantic/shadow.py`: deterministic stable-hash sampler (no RNG; rate 0/1 short-circuit), `capture_candidate`
  freezes a *fresh* tier-1 allow's raw inputs + copied plan (`<hash>.plan.md`) + routing snapshot to
  `.forge/artifacts/<session>/shadow/`. Cap/dedup count distinct stems across `.json`/`.processing`/`.done`. Seam in
  `plan_check.py` (fresh-allow branch, gated on rate > 0, best-effort). Fully inert at rate 0 (dir never created).
- **Slice 2 (Stop-batch drain)**: `run_supervisor_check` extracted as the single emitter (`usage_command` param +
  `SupervisorRun{decision,verdict,run_ok,parsed}`); `parse_supervisor_verdict_with_status` distinguishes a parse failure
  from a real low-confidence verdict. `enqueue_shadow_marker` + Stop-hook gate (`has_pending_candidates`) +
  `_shadow_handler` (detached `Popen`, run-tree re-root via `_memory_writer_env`). New `shadow_runner.py`: atomic claim
  (`rename` → `.processing`, at-most-once), reconstruct full context/config (plan → frozen sidecar), classify
  agree/disagree/inconclusive/error with the supervisor's own block bar; never enforces.
- **Slice 3 (read surface)**: `ShadowActivity` in `build_session_activity_summary` (counts from `.done` status, spend
  from the `supervisor-shadow` ledger row); `forge activity` Shadow line + `render_summary_line` audited/queued segment;
  `forge policy shadow` group (hidden `run` worker + `show` lists disagreement artifacts with citations).
- Docs: design_workflows.md §1.2 shadow paragraph, design_appendix.md §A.13 `supervisor-shadow` emitter row.
- Post-review hardening: relative `plan_override_path` now resolves against `forge_root` at capture (mirrors
  `load_plan_override`); deterministic post-claim failures finalize as `.done` `status="error"` (no orphaned
  `.processing` phantom-pending); detached shadow worker resets `FORGE_DEPTH=0` so the frontier replay spawns; renderer
  shows only cited (blocking) violations for a disagreement.

**Verification**: 42 drain tests (`test_shadow_runner.py`) + 73 capture tests (Slice 1) + 9 `test_usage_summary.py` + 2
`test_activity.py` + 6 `test_policy_shadow.py`; 2500 policy/workqueue/cli/core-ops tests green; mypy + pyright clean on
all 10 changed source files. Schema note: additive `SupervisorConfig` fields — old Forge cannot read new manifests
(research-preview clean break).

### codex_frontend closeout: Codex shipped as a first-class alternate runtime (card -> done)

**Goal**: Close out the `codex_frontend` card after PR #26 merged to `main`. Phases 0-6 and the residual-risk
mitigations each have their own dated entries below; this records the epic closeout and the v0.6.0 release.

**Key changes**:

- Card moved `doing/codex_frontend/ -> done/` (board-contract closeout). All phase and Open-Decision boxes ticked; only
  the deliberate Deferred items remain (app-server transport, filing the upstream fail-open issue, PermissionRequest
  source-dive).
- Durable lessons promoted to `impl_notes.md`: the capability/lifecycle runtime seam (limits-as-capability-values),
  Codex hook enrollment-gating + non-computable `trusted_hash` + fail-open PreToolUse, and the
  native-direct-to-Responses topology (governed at the session/hook seams, not the wire; `isolate_codex_home` test
  isolation).
- Post-merge doc-sync landed on the branch in #26: `design.md` split into design/appendix/workflows/cli_reference for
  the 30K doc-size limit; architecture diagrams (1/5/8) and the README updated to show Codex as an alternate runtime.

**Verification**: Full checklist ticked with per-phase verification recorded; `make pre-commit` + `make test-unit` green
before tagging; PR #26 CI (Docker integration) green at merge. Released as **v0.6.0** (covers #24 supervisor timeout,
#25 supervisor cascade, #26 Codex runtime) via the `v0.6.0` tag -> `publish.yml` -> PyPI.

## 2026-06-13

### codex_frontend Phase 6 code-review fixes: 12-finding sweep (fork / enrollment / policy / handoff / invoker)

**Goal**: Resolve a branch code review of `codex-frontend` (12 findings, P1->P3). Every confirmed behavioral finding is
fixed with a regression test; doc/process findings are fixed in place. One finding was a verification artifact
(uncommitted drift) closed by landing this slice.

**Key changes**:

- **Fork rejects a Codex parent (P1)** — two layers. `cli/session_fork.py` preflights with an actionable message (Codex
  resume / branch commands), and `SessionManager.fork_session` now raises `CannotForkCodexParentError` at the internal
  boundary before any child manifest/worktree is created. Codex sessions have no `claude_session_id`, so the old path
  built child state then failed the UUID check, orphaning it; the manager guard makes the invariant hold for every
  caller, not just the CLI preflight.
- **No TYPE_CHECKING workaround (P1)** — `cli/runtime.py` imports `CodexEnrollmentVerification` directly;
  `core/ops/codex_enrollment.py` moved its heavy probe-turn imports (invoker graph, session store) into
  `_run_probe_turn` so the CLI-facing module import stays cheap. Re-greens the
  `test_production_source_has_no_type_checking_workarounds` conformance check.
- **Event-aware enrollment identity (P2)** — new `codex_registration_pairs()` (`(event, command)`) in
  `install/codex_hooks.py`; `_read_user_scope_registration` checks `("SessionStart", cmd)`, so a wrong-event Forge
  registration no longer reads as enrolled and burns a real `codex exec` turn.
- **Shared path matcher for TDD (P2)** — extracted `is_under_directory()` into `policy/deterministic/base.py`; the Codex
  tests-first sort (`cli/hooks/codex_policy.py`) and the TDD guard now share one nested-aware matcher (their drift was
  the bug; a `pkg/tests/...` path was misordered).
- **Staged-context one-shot backstop (P2)** — `consume_pending_context` empties the staging file when `unlink` fails,
  and the delivered-reconciliation paths (`core/ops/codex_session.py`, `core/ops/codex_interactive.py`) clear pending
  unconditionally, so a re-fired SessionStart can't re-deliver stale context.
- **Runtime error is not success (P2)** — `cli/session_codex.py` adds `_codex_ok()` (returncode-success AND not
  `runtime_is_error`); launch/resume exit codes, outcome render, and the resume tip all honor it.
- **Argv exposure documented (P2)** — `session/codex_invoke.py` + `docs/end-user/session.md` note that an interactive
  `--resume-from` prompt is visible in shared-host process listings, recommending `--context-delivery hook`; confirmed
  the existing debug log emits only cwd/resume, never the prompt.
- **Manifest corruption distinct from missing (P3)** — `resolve_codex_session` narrows not-found to
  `SessionNotFoundError`; other `ForgeSessionError` now surfaces "could not be read (manifest may be corrupt)" rather
  than a misleading "not found".
- **No blank provider error (P3)** — `core/invoker/codex_stream.py` returns `None` for empty/whitespace error text and
  `core/invoker/codex.py` backfills a fallback stderr when the stream is an error.
- **Enrollment diagnostic never tracebacks (P3)** — `verify_codex_enrollment` wraps the gate sequence and degrades any
  unexpected error to an UNVERIFIED result.
- **Change-log heading restored (P3)** — the Phase 6 review-fixes entry regained its missing `###`.
- **Change-log compaction** — summarized the 2026-05-22 → 2026-06-06 tail in place (board-contract size policy) so the
  file clears the 30K-token doc limit (38.5K → 28.7K count-tokens); dates, breaking changes, decisions, and design
  pointers preserved, per-test counts and play-by-play dropped (full detail in git history).

**Verification**: 553 unit+regression tests green across the touched Codex suites — 7 new
`tests/regression/test_bug_codex_*.py` (fork orphan at the CLI **and** `fork_session` layers, enrollment wrong-event,
TDD nested layout, staged-context re-read, runtime-error exit-0, manifest corrupt-vs-missing, empty provider error) plus
a `TestNeverRaises` case in `test_codex_enrollment.py`; the no-`TYPE_CHECKING` conformance test green; mypy clean (259
files); pyright clean on the 15 changed source files (`manager.py` + `exceptions.py` added for the fork-guard
invariant); `make pre-commit` clean (with every new file staged — an earlier pass silently skipped untracked files). 24
Docker integration tests green against an image rebuilt with these changes — `test_policy_hooks.py` 21/21 (Claude +
Codex `policy-check` wires and codex session-start/staged-context delivery, covering the shared `is_under_directory` and
the one-shot staging backstop) and `test_installer.py` codex-hooks 3/3. The three real-`codex` API E2Es
(`test_codex_session_start` / `codex_exec_smoke` / `claude_to_codex_resume`) stay `CODEX_API_KEY`-gated (only
`OPENAI_API_KEY` is present, which codex rejects) and were not run; they exercise codex subprocess mechanics these fixes
do not alter.

## 2026-06-12

### codex_frontend residual-risk mitigations: version-churn guard + empirical enrollment check

**Goal**: Harden the external-binary residual risks from the card's "Risks / open questions" before closeout — Forge
owns the *detection and confirmation* surface even where the underlying behavior is codex-cli's. Three actionable items
(the `trusted_hash` source-dive and PermissionRequest pinning stay deliberately documented-not-built).

**Key changes**:

- **Validated-version ceiling (version churn).** `CODEX_VERSION_VALIDATED` (`core/runtime/codex_preflight.py`, `0.139.0`
  — the last green probe round) + additive `CodexPreflight.version_validated`/`version_beyond_validated` (defaulted, so
  every existing keyword construction stays valid). `forge runtime preflight codex` prints a **non-blocking** re-probe
  notice when the installed binary sorts strictly above the ceiling (a bump never fails readiness — the pinned
  trust/`apply_patch`/argv facts are just unverified for that version), and the real-codex E2E names the ceiling on
  failure. Mirrors the 4g `CLAUDE_VERSION_VALIDATED` guard.
- **Empirical enrollment check (the unverifiable ceremony).** `forge runtime preflight codex --verify-enrollment` over
  new `core/ops/codex_enrollment.py`: the trust ceremony is unverifiable from a config read (`trusted_hash` not
  computable), so this confirms it by *effect* — one trivial managed `codex exec` turn in a throwaway git repo, enrolled
  iff `codex-session-start` fired (the Phase 5 observation receipt appeared). Reuses `_temporary_run_env` so the codex
  child inherits `FORGE_SESSION`/`FORGE_FORGE_ROOT` and the hook resolves the disposable session exactly as in
  production. Short-circuits with **no turn** when the answer is already knowable (not ready / not registered); a turn
  that fails to complete reports `UNVERIFIED` (not "not enrolled"); the not-enrolled message is sharpened by `hook_seam`
  (managed-suppressed / disabled / re-probe hint). Tests **user** scope only (path-stable, one-ceremony-covers-all).
- **Upstream fail-open issue drafted.**
  `scripts/experiments/codex-hooks/upstream-issues/pretooluse-malformed-fails-open.md` (probe-30h reproduction: `allow`
  \+ unknown field + `continue:false` ran the command, refuting the documented fail-closed). **Owed**: the exact codex
  docs citation + an operator-confirmed `gh issue create --repo openai/codex`.
- **Docs**: design.md §5 (the verify-enrollment path beside "cannot perform or verify"); design_appendix §N.3 (both
  guards); card Risks bullets annotated with the shipped mitigations; checklist residual-risk slice + Deferred update.

**Verification**: 226 Codex-touching unit tests green (`tests/src/core/runtime/`, `test_runtime.py`,
`test_codex_enrollment.py`, the four `core/ops`/`invoker`/`session` codex suites — defaulted preflight fields keep every
construction valid); new `TestValidatedVersionGuard` (5), `test_codex_enrollment.py` (verdict-logic + `_run_probe_turn`
mechanism via a FORGE_FORGE_ROOT→receipt simulation + git-init degrade + JSON-safe/secret-free), `TestVerifyEnrollment`
CLI (4) and the two version-notice CLI cases; mypy + pyright clean on the three changed source files. No real `codex`
runs in the suite (the turn is mocked). The `--verify-enrollment` real-codex behavior is operator-gated (one quota
turn).

### codex_frontend Phase 6 review fixes: tracking preservation + (event, command) dedupe + sync ceremony

**Goal**: Fix three Phase 6 review findings — two P1s (a previously tracked Codex block orphaned when codex is
temporarily off PATH; manual-registration dedupe matching bare command strings regardless of event, so a wrong-event
registration silently skipped enforcement untracked) and one P2 (`extension sync` never printed the trust-ceremony
next-steps and `_count_actions` ignored codex, rendering a false "Already up to date." on codex-only changes).

**Key changes**:

- `Installer._execute_codex` now returns `None` for "no authoritative outcome" (module not selected, codex binary
  unavailable, conflict, apply failure) vs `(path, commands)` for a resolved read-back from disk; `init()` preserves
  prior tracking on `None` — unifying the module-dropped branch — so disable always keeps knowing about a previously
  written block. The skip-due-to-manual-registration outcome stays authoritative (`(None, [])`): ownership transferred
  to the user, tracking correctly clears.
- New `_collect_registrations()` in `codex_hooks.py`: dedupe compares `(event, command)` pairs with `type = "command"`,
  matching Codex's own registration identity; matchers deliberately ignored (a matcher'd entry still fires on
  overlapping events — installing alongside would double-fire). Wrong-event and bogus-event registrations now plan
  `install`; conflict/post-merge-validation messages name `event: command`. The event-agnostic `_collect_commands()`
  flatten is kept for the reporting surfaces (status, uninstall leftover warning) by design.
- `_count_actions` returns a third codex component (install/update = 1 action) at both call sites, and `sync_cmd` calls
  `_print_codex_completion` — a synced block can carry new entries whose per-entry `trusted_hash` is not yet granted, so
  sync is exactly where the ceremony guidance matters.

**Verification**: Two regression files, fail-confirmed against the unfixed code (6 failing + 3 behavior-guard cases):
`tests/regression/test_bug_codex_tracking_lost_on_unavailable.py` (unavailable + conflict re-runs preserve tracking and
disable still cleans up; manual-skip still drops tracking) and `tests/regression/test_bug_codex_dedupe_wrong_event.py`
(swapped/bogus events install, partial wrong-event conflicts, correct-event + matcher'd dedupe kept, non-command type
excluded). Three new CLI cases (sync restores block + counts it + prints ceremony; unchanged sync stays quiet;
codex-less re-enable keeps tracking via `status --json`). Full sweep 6341 unit+regression green; Docker
`test_installer.py` 15/15; mypy/pyright clean; `make pre-commit` clean.

### codex_frontend Phase 6: codex-hooks installer module (scope-mirroring registration)

**Goal**: `forge extension enable` registers Forge's two Codex hooks (`codex-session-start`, `codex-policy-check`) in
the Codex config the **Forge install scope maps to** — resolving the stage-84 installer-scope trade-off by user
decision: mirror the install scope (`user` -> `$CODEX_HOME/config.toml`; `project`/`local` ->
`<project>/.codex/config.toml`, Codex has no settings.local analog). Accepted trade-off: project/local installs cost one
trust ceremony per repo; enable names the ceremony explicitly so a registered-but-unenrolled install is never mistaken
for active enforcement.

**Key changes**:

- **`install/codex_hooks.py`** (new): builtin entries (trust-durable command strings, PreToolUse with NO matcher — the
  adapter filters), marker-delimited managed block (`# >>> forge hooks >>>`), `tomllib`-validated merge/remove that
  never rewrites the codex-owned `config.toml` (no TOML-writer dependency; post-merge parse validation before an atomic
  write; `.config.toml.forge.backup.<ts>`), event-name validation against the probe-pinned 10-event set (Codex loads
  bogus names silently), and dedupe vs manual registrations (full -> skip untracked; partial -> conflict — installing
  would double-register and Codex fires duplicates twice per event).
- **Installer wiring**: settings-only `InstallModule.CODEX_HOOKS` in `standard`+`full`, presence-gated on the codex
  binary (visible skip, never silent); `InstallPlan.codex` (`CodexPlan`); additive `Installation.codex_config_path`/
  `codex_commands` tracking; **codex conflicts never set `has_conflicts`** (best-effort: another tool's config must not
  fail the Claude install); uninstall removes only the managed block, refuses a tracked path that no longer matches the
  scope mapping, and deletes a whitespace-only (Forge-created) file.
- **CLI**: plan render gains a "Codex hooks (config.toml)" section; enable prints trust-ceremony Next-steps on
  install/update; `extension status` shows the registration (human + `--json`); disable previews the block removal.
- **Registry**: codex `install_scopes` `()` -> `("user", "project", "local")`; note rewritten to the shipped mapping.
- **Test isolation fix**: the new installer tests exposed that nothing isolated `CODEX_HOME` — the suite wrote the
  managed block into the real `~/.codex/config.toml` (restored from the Forge backup). New autouse `isolate_codex_home`
  fixture in `tests/conftest.py` closes the leak class for all tests.
- **Docs**: design.md §5 (seven modules + codex-hooks paragraph) + §4.1.4 (handler-only -> installer-registered +
  ceremony); design_appendix §E.2 + new §E.6 (mechanics); end-user hook.md codex sections reframed (manual TOML kept as
  a reference path); QA checklist §2.10/§2.11 (test-count 535 -> 541).

**Verification**: 59 new unit cases — `test_codex_hooks.py` (40: trust-byte golden, inline-table post-validation-only
failure with no write, full-vs-partial manual dedupe, whitespace-only deletion), `TestInstallerCodexHooks` (11: update
byte-stability, conflict-never-blocks, tampered-path refusal, module-dropped tracking preservation),
`TestEnableCodexHooks` (5 CliRunner end-to-end), registry pins; full unit+regression sweep 6329 green; Docker
`test_installer.py` 15/15 (3 new `TestCodexHooksModule` cases through the real wheel CLI: enable->status->disable cycle
with a codex shim, presence-gated skip, user-content preservation); live `forge runtime list --json` renders the flipped
scopes; `make pre-commit` clean.

### codex_frontend probe debt: operator-gated stages 85-87 harness

**Goal**: Convert the owed Phase 3/4/5 operator-gated Codex checks from README sketches into runnable probe stages:
product `codex-policy-check`, product `codex-session-start` with multi-KB `additionalContext`, and the real interactive
TUI behavior smoke.

**Key changes**:

- Added product-probe helpers to `scripts/experiments/codex-hooks/lib.sh`: stage-isolated `FORGE_HOME`, repo-root
  discovery, product-project setup, `forge` PATH guard for trust-durable product hook commands, and a guided trust
  ceremony prompt.
- Added stage `85-policy-check-e2e`: registers the real `forge hook codex-policy-check`, enables TDD on an isolated
  Forge session, asks Codex to create an impl-only file, and passes only if the manifest records a deny and the file is
  absent.
- Added stage `86-sessionstart-delivery-e2e`: registers the real `forge hook codex-session-start`, seeds a large parent
  transcript, runs the shipped `--context-delivery hook` bridge, and checks echo + `confirmed.codex` receipt facts.
- Added stage `87-interactive-smoke`: foreground TUI flow for bare start, live reattach, active-gate refusal, positional
  hold instructions, hook-delivered context, and read-only sandbox behavior, combining operator answers with manifest
  facts.
- Wired stages 85-87 into `reproduce.sh all`; post-run hardening keeps foreground TUI stdout/stderr attached to the
  terminal, aborts early when 87A did not create a thread, uses the absolute `forge` path for the second-terminal active
  gate command, and gives sandbox failures their own verdict.

**Verification**: `bash -n` on the changed harness scripts; `shellcheck -e SC1091` on the same set (dynamic stage
`source` parity); focused unit slice passed:
`uv run pytest tests/src/cli/hooks/test_codex_policy_check.py tests/src/cli/hooks/test_codex_session_start.py tests/src/session/test_codex_handoff.py tests/src/core/ops/test_codex_session.py tests/src/core/ops/test_codex_interactive.py`
(126 passed); `make pre-commit` clean. A minimal stage-style product project can run
`forge session start smoke --no-launch --no-proxy` with isolated `FORGE_HOME`, and `uv run --project ... forge --help`
validates the fallback helper command shape. Live operator run on codex-cli 0.139.0: stage 85 PASS (product
`codex-policy-check` denied the impl-only `apply_patch`; blocked file absent); stage 86 PASS (11,519-byte transfer
delivered through product `codex-session-start`, token echoed, `confirmed.codex.context_delivery` and `rollout_source`
both `session_start_hook`); stage 87 PASS after harness hardening (bare start, reattach memory, second-terminal
active-gate refusal, positional hold instructions, hook-delivered interactive bridge, and read-only sandbox denial all
operator-confirmed with matching capture facts; `sandbox_should_not_exist.txt` stayed absent). The operator also
observed that Codex CLI visibly rendered hook-delivered `SessionStart` `additionalContext` in the TUI transcript even
though it was delivered passively rather than as a positional synthetic prompt; the non-gating observation prompt was
codified after that PASS run, so the current capture predates `results/observations.txt`.

## 2026-06-11

### codex_frontend Phase 5: Interactive Codex frontend

**Goal**: Forge-manage interactive `codex` TUI sessions -- bare `forge session start --runtime codex` opens the TUI,
`--resume-from` without `--task` is an interactive bridge carrying the curated transfer, and bare `forge session resume`
reattaches via `codex resume <thread_id>`. `--task` keeps meaning headless, byte-unchanged. **Scope (user decisions)**:
bare = interactive; bridge composes both deliveries; thread capture = post-exit filesystem discovery + enrolled-home
observation receipt (separate `observation-receipt.json`; the Phase 4 delivery-receipt contract stays byte-stable);
`install_scopes` stays `()` (Phase 6) -- only `interactive="beta" -> "default"` flips.

**Key changes**:

- **Discovery** (`core/runtime/codex_rollouts.py`): `find_rollouts_since` -- mtime-filtered rollouts since a tight
  pre-launch timestamp, head-cwd narrowing (never below one candidate), thread_id parsed from the filename. The ops
  layer requires exactly one candidate (`rollout_source="discovered_post_exit"`); ambiguity refuses to guess.
- **Observation receipt** (`session/codex_handoff.py` + `cli/hooks/codex_transfer.py`): nothing-staged turns in a
  managed session record codex's own `session_id`/`transcript_path`; the handler branches on pending-file PRESENCE so a
  failed staged delivery never masquerades as an observation. Receipts stay the hooks' only writes (design.md 3.5).
- **Launcher** (`session/codex_invoke.py`, new): foreground `subprocess.run` of `codex --sandbox X [prompt]` (start) or
  `codex resume --sandbox X <tid>` (reattach -- the subcommand declares its own flag); env = sanitized child env
  (`sanitize_codex_child_env`, extracted behavior-neutral) + FORGE_SESSION/FORGE_FORGE_ROOT + a REQUIRED caller-minted
  run-identity triple -- the TUI shares the transfer-curation event's root (one run tree; a mint-when-absent default
  would silently fork it).
- **Interactive ops** (`core/ops/codex_interactive.py`, new): `start_interactive_codex_session` (bare + bridge;
  `assemble_codex_transfer` extracted from the bridge golden-pinned byte-identical; positional delivery wraps the body
  in hold instructions via `compose_codex_interactive_context` -- the positional `[PROMPT]` starts a real model turn)
  and `reattach_codex_session` (guards shared with `continue_codex_session` by extraction). Two timestamps
  (activity-summary window vs discovery window); receipts beat discovery; rollback only before the TUI launches;
  interactive turns emit no usage event; bare starts record `context_delivery=None`.
- **CLI matrix** (`cli/session_codex.py`, `cli/session_lifecycle.py`): omitting `--task` = interactive; `--task` alone
  errors; bare resume gates on the active-session registry (Claude reconnect parity, no `--force` escape) then
  reattaches; cross-project resume restructure -- the unscoped fallback always runs on a scoped miss, codex dispatches
  (cross-CWD by design), the Claude refusal stays byte-identical. `_post_exit_render` reused via lazy import (cycle).
  `session show` gains a `Delivery:` line; registry `interactive="default"`.
- **Docs**: design.md 3.4/3.5/3.9/3.10/4.0 + runtime matrix; session.md interactive section; transfer.md "later phase"
  note replaced; hook.md observation bullet; probe README stage-87 operator checklist (real-TUI smoke incl. multi-KB
  positional + hold-instructions no-autonomous-action).

**Verification**: 70 `test_session_codex.py` (matrix incl. exact errors, cross-project both runtimes, renderers) + 22
`test_codex_interactive.py` (bare/bridge/hook matrices, two-timestamp pin, run-identity equality pin, ambiguity refusal,
reattach) + 13 `test_codex_invoke.py` (argv/env/auth postures) + observation-receipt suites; full `tests/src/cli` 1761
green; runtime package 80 green; mypy clean. Docker `test_policy_hooks.py` observation cases added. Post-ship live
probes (codex 0.139.0) closed the argv/rollout-head externals: `codex resume --help` pins
`resume [OPTIONS] [SESSION_ID]` with its own `-s/--sandbox` (the launcher was corrected to pass `--sandbox` inside the
subcommand instead of root-level), and a real rollout head matched the discovery parser exactly (`session_meta` +
`payload.cwd`; filename timestamp confirmed LOCAL time, validating filter-by-mtime). Deferred verification: operator-
gated stage 87 behavioral smoke (hold instructions, multi-KB positional, enrolled hook delivery, live reattach, sandbox
behavior).

### codex_frontend follow-up: codex-policy-check silent on unresolvable sessions

**Goal**: Align the Phase 3 hook with the codex-session-start silence rule -- under a user-scope Codex registration, "no
resolvable Forge session" means Forge is not managing the turn, and unrelated Codex sessions must see no Forge stderr
noise.

**Key changes**:

- `codex_policy_check` (cli/hooks/commands.py): the no-session stderr print -> `logger.debug` (hooks debug log via
  `FORGE_DEBUG=1`). Post-resolution diagnostics (manifest/intent/engine failures, block/check summaries, no-evaluable-
  operations) keep stderr -- they only fire inside a managed Forge session. hook.md documents the silent-allow bullet.

**Verification**: `test_no_session_passes_through` strengthened (empty stderr + caplog debug pin);
`test_codex_policy_check.py` + `test_codex_session_start.py` 28/28; mypy clean.

### codex_frontend Phase 4: SessionStart transfer delivery with initial-message fallback

**Goal**: Ship the post-enrollment upgrade the 30e probe unlocked -- deliver the curated transfer to a Codex session via
a trust-enrolled SessionStart hook (`additionalContext`) instead of the initial `codex exec` prompt, with
initial-message staying the zero-setup default. The central constraint shaped the design: enrollment is unverifiable
pre-turn (the `trusted_hash` is not computable), so hook mode = explicit opt-in + staged file + post-turn receipt
reconciliation. **Scope (user decisions)**: `--context-delivery {initial-message,hook}` flag shape; hook-undelivered
fails loud (exit 1, session kept); handler-only like Phase 3 (manual registration + ceremony until the Phase 6
installer).

**Key changes**:

- **Staging module** (`session/codex_handoff.py`, new): `pending-context.md` + `context-receipt.json` under
  `<session_dir>/codex/` (GC/delete free via the session dir; pinned anyway). `consume_pending_context` writes the
  receipt BEFORE unlinking (a delivered-but-unreceipted turn would read `hook_undelivered` dishonestly); a failed
  receipt write deliberately delivers nothing. `compose_codex_initial_message` split into
  `compose_codex_handoff_context` + task suffix -- the default path is golden-pinned byte-identical (golden added before
  the refactor).
- **Handler** (`forge hook codex-session-start`, new `cli/hooks/codex_transfer.py`): resolves the session via
  FORGE_SESSION + payload-cwd rooting (the Phase 3 rule), consumes the staged file, emits the probe-pinned strict
  one-line `{"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": ...}}` (Codex fails OPEN on
  malformed output). Never reads the manifest -- the receipt is its only write, so `confirmed.codex` stays CLI-owned
  (design.md §3.5). Every non-delivery path (no session, nothing staged = resume turns, malformed stdin) is a silent
  exit-0 no-op with NO output -- diagnostics log at debug to the hooks log (review fix: two stderr prints would have
  made every non-Forge Codex session under a user-scope registration emit Forge noise). The command name is
  trust-durable (renaming breaks `trusted_hash` enrollment).
- **Bridge/op wiring**: `bridge_session_to_codex(staged_context_path=)` stages the framed body and sends the raw task as
  the prompt; `_temporary_run_env` now also scopes `FORGE_FORGE_ROOT` (the CHILD's forge_root -- worktree sessions'
  manifests aren't findable from payload cwd alone, benefits both codex hooks). `start_codex_session` gained
  `context_delivery` + a pre-turn guard (knowable-negative seams `disabled|unknown|managed_suppressed|untrusted` fail
  before any state; `enrollment_gated` proceeds). `_reconcile_hook_delivery` post-turn: receipt matching the stream
  thread -> `session_start_hook` (receipt `transcript_path` supersedes glob as `rollout_source="session_start_hook"`,
  cross-checked with a warning); receipt present when the stream missed `thread.started` -> **recovers**
  `thread_id = receipt.session_id` (otherwise-unresumable session stays resumable); absent/mismatched ->
  `hook_undelivered` + staged file cleared (one-shot: an enrolled resume can never late-deliver stale context; resume
  also defensively clears).
- **CLI**: `--context-delivery` Choice with Click default `None` (a real default would trip
  `reject_codex_flags_for_claude` on every plain Claude start -- regression-pinned), resolved to initial-message in
  `run_codex_start`; undelivered render prints `print_error_with_tip` (ceremony / delete-and-retry) and exits 1 even
  when the codex turn succeeded. `CodexConfirmed.context_delivery` (additive).
- **Docs**: design.md §3.9 (delivery contract; the stale "hook delivery deferred to Phase 6" claim removed at the code
  slice that falsified it) + §3.5 (receipt note); end-user hook.md (`codex-session-start` section with the probe-pinned
  NESTED registration TOML + trust-durable-name warning), session.md + transfer.md (flag, default, failure semantics);
  probe README "stage 86" operator-gated note (enrolled E2E incl. the unprobed multi-KB additionalContext size).
- **File-size compliance** (commit-hook limits): `cli/session_model_pin.py` split out of `session_lifecycle.py` (the
  --model pin validate/apply/persist helpers; same pattern as the original session.py split), design.md §3.9 verbosity
  trims (content-preserving), and the 2026-06-05 change_log block compacted per the board-contract size policy.

**Verification**: 60+ new unit cases -- `test_codex_handoff.py` (16: roundtrip/one-shot/receipt-failure),
`test_codex_session_start.py` (10: delivery, strict-wire key sets, payload-cwd rooting, 7 silent no-ops asserting empty
stdout AND stderr, incl. consume-failure fail-open), `test_codex_bridge.py` (+7: golden, staging-at-Popen-time, env
restore), `test_codex_session.py` (+8: hook-mode matrix incl. thread-id recovery + per-seam guard),
`test_session_codex.py` (+5 incl. the plain-Claude-start None-default regression), `test_gc.py` (+1 handoff-files
pinning); full blast radius 1270 ops/session/CLI tests green; mypy clean on all of `src/forge/`. Docker:
`test_policy_hooks.py` 21/21 (4 new `TestCodexSessionStartDocker` cases through the real wheel CLI, incl. the
no-FORGE_SESSION user-scope silence case; 17 pre-existing unchanged).

**Deferred**: the real-codex enrolled-hook E2E is operator-gated (stage 86, with stage 85); additionalContext payload
size beyond the 30e short token is unprobed until that round.

### codex_frontend Phase 3 follow-up: blocked actions no longer persist policy state

**Goal**: Fix four Phase 3 review findings, chiefly that both hook commands persisted engine-collected policy state
before checking whether the composed decision blocks the action.

**Key changes**:

- A blocked action (deny / unresolved needs_review) never lands -- Claude denies the Write/Edit, Codex rejects the whole
  all-or-nothing `apply_patch` -- so its collected state (e.g. TDD `tests_touched` from a clean test file riding in a
  denied patch) no longer persists; decision-log entries still persist as the audit trail. Gated in
  `_persist_policy_state` (Claude) and at the `codex-policy-check` persist call (cross-file aggregate).
- Codex stderr telemetry now labels the decisive file (first denying / first unresolved result), not `file_results[0]`,
  which could be an allowing file routing the label helper down the wrong branch.
- All three Codex wire emissions print with explicit `file=sys.stdout`; `_join_sections` types its formatter as
  `Callable[[CompositeDecision], str]`.

**Verification**: New `tests/regression/test_bug_blocked_action_persists_policy_state.py` (both runtimes, fail-confirmed
against the unfixed code) + telemetry-label unit test; 6,123 unit/regression tests green; Docker `test_policy_hooks.py`
17/17; mypy/pyright clean.

### codex_frontend Phase 3: Codex hook adapter/responder + `forge hook codex-policy-check`

**Goal**: Fill the runtime-neutral `HookAdapter`/`HookResponder` protocols with the Codex pair so a `codex exec` turn
can enforce Forge policy on `apply_patch` actions, carrying the resolved `ActionContext.runtime -> origin` rename. Scope
(user decision): **PreToolUse only** (Stop/UserPromptSubmit/SessionStart land with their Phase 4/5 consumers;
PermissionRequest stays descoped -- never observed firing headless); **handler-only** -- enforcement needs a manually
registered + trust-enrolled Codex hook until the Phase 6 installer.

**Key changes**:

- **`origin` rename** (`policy/types.py`): `ActionContext.runtime -> origin`, values `{forge_cli, claude_code, codex}`
  per the recorded `runtime_abstraction` decision -- the two on-demand CLI leaves (`forge policy check`/`supervisor`)
  become `forge_cli`; `%policy check` stays `claude_code` (Claude-context); the false "flows into attribution" docstring
  claim fixed. Zero behavioral surface (no read sites, never serialized); 47 test kwargs across 11 files.
- **apply_patch parser** (`cli/hooks/codex_patch.py`, new): `parse_apply_patch -> list[PatchFileOp] | None` over the
  probe-pinned grammar (Add/Update/Move to/Delete, `@@` hunks, End-of-File tolerance, CRLF); `None` = malformed ->
  caller fails open (converges with Codex's own rejection); `path` is the post-op Move-to target.
- **Adapter/responder** (`cli/hooks/codex_policy.py`, new): `CodexHookAdapter` normalizes per-file ops to the tool names
  every policy's `applies_to` gates on (Add->`Write`, Update->`Edit`; deletes skipped; `Bash` -> `[]`), tagging
  `origin="codex"` with runtime truth in `tool_args`; `CodexHookResponder` emits the probe-pinned deny wire
  (`hookSpecificOutput.permissionDecision="deny"` + reason, strict `json.dumps` only -- Codex FAILS OPEN on malformed
  output; `BLOCK_EXIT = 0`). Protocol cardinality became `build_contexts -> list[ActionContext]` (clean break; the
  Claude adapter returns `[ctx]`/`[]`, wire bytes unchanged); deny reason text shared via extracted
  `format_deny_text`/`format_needs_review_text` (Claude strings byte-identical).
- **`forge hook codex-policy-check`** (`cli/hooks/commands.py`): per-file evaluation with tests-first ordering (an
  atomic test+impl patch passes TDD, the `%policy check` precedent); cross-file precedence deny > needs_review >
  warn/allow; allow emits NO stdout (allow-feedback delivery unprobed); session resolved via FORGE_SESSION with
  payload-cwd `forge_root` rooting (Codex `session_id` is a thread UUID, never in the Claude index). Engine assembly
  extracted as `build_hook_engine` + `register_supervisor_and_restore` (moved-not-changed; cascade resolver wiring now
  serves both commands); `_persist_policy_decisions` writes one decision-log entry per file op in one lock cycle with an
  **explicitly aggregated** `engine_state` -- `evaluate()` clears collected state per call, so a one-shot end read would
  drop earlier files' TDD `tests_touched` (review finding, regression-pinned).
- **Docs**: design.md §4.1.4 (both shipped pairs, normalization, list cardinality, handler-only caveat) + §4.1.5 (shared
  reason text, per-runtime wire framing); registry codex note (`pretool_policy` stays `"partial"`); `protocols.py`
  docstrings; end-user `hook.md` codex-policy-check section; probe README owes "stage 85" (operator-gated enrolled
  end-to-end).

**Verification**: 57 new unit cases (24 parser, 16 adapter/responder, 17 command incl. the state-aggregation,
payload-cwd, and wire-strictness regressions and two cascade shared-wiring cases) -- full sweep 6118 unit+regression
green; mypy/pyright/pre-commit clean. Docker: `test_policy_hooks.py` 17/17 (7 new Codex cases; 10 pre-existing unchanged
-- extraction moved no Claude bytes) + `test_supervisor_e2e.py` 9/9 (cascade through the extracted registration).

**Deferred**: real-codex enrolled-hook E2E is operator-gated (trust ceremony) -- recorded as probe stage 85; whether
Codex surfaces exit-0 stderr to the agent is unobserved (warnings are advisory).

## 2026-06-10

### Supervisor cascade: tier-1 plan check before the frontier supervisor

**Goal**: Route semantic-supervisor checks through a cheap stateless tier-1 plan check (opt-in `--cascade`) so
clearly-aligned Write/Edit actions short-circuit and only uncertain ones pay the frontier `claude -p --resume` call.

**Key changes**:

- `PolicyEngine.register_resolver()`: a resolver policy runs only when pass-1 emitted `needs_review` and nothing denied;
  `_run_policy()` extraction keeps applies_to/fail-mode/state semantics identical for both passes; `_collected_state`
  cleared per `evaluate()`; `rules_active` uses `registered_policy_ids` (includes the resolver). Cascade off is
  bit-identical to the pre-cascade engine.
- `PlanCheckPolicy` (`semantic.plan_check`, new `policy/semantic/plan_check.py`): one cheap `core.llm` call (tagger
  mechanics, default OpenRouter `google/gemini-3.5-flash`, with per-provider defaults and an approximately 32K-token
  configurable prompt budget) judging the action against the approved-plan snapshot. Prompt packing uses head+tail
  excerpts, keeps diff file/hunk headers when truncated, includes Edit matched/replacement fragments and Write target
  existence context, and tells the checker when plan or action fields were truncated. Emits only `allow` (cached via
  ThrottleCache, plan fingerprint in key) or `needs_review`; every failure path escalates — degrades to frontier-always,
  never to unsupervised. Reasons ride in low-severity violations (clamped 500 chars), never `decision.warnings`, so
  resolved escalations stay silent on the allow path.
- CLI/config: `SupervisorConfig.cascade`/`checker_provider`/`checker_model`/`checker_budget_tokens`;
  `forge policy supervise --cascade/--no-cascade --checker-provider --checker-model` (modifiers with target, standalone
  toggle without); advanced budget tuning stays in session config via
  `forge session set policy.supervisor.checker_budget_tokens <tokens>`; enabling auto-resolves the plan snapshot via the
  `--reload` machinery and fails loud pre-mutation when none resolves; `%policy supervise cascade on|off`; status/show
  surfaces. Existing local LiteLLM backend configs created before `gemini/gemini-3.5-flash` was added must be
  recreated/updated or paired with an explicit served checker model such as `gemini/gemini-2.5-flash`.
- Measurement: decision-log-derived `plan_check_allow`/`plan_check_needs_review` counters (cached allows counted) in
  `forge activity` + summary line; session-tagged `plan-check` ledger events via `emit_direct_llm_usage`. Named
  needs-review (not "escalated") because a tier-1 `needs_review` co-occurring with a deterministic deny skips the
  resolver; actual frontier runs are the supervisor counters.
- Docs: design.md §4.1.2 cascade block + §4.1.5 resolver bullet + CLI row; design_appendix §D ownership + §A.13 emitter
  rows; end-user policy.md cascade subsection.

**Verification**: 5950+ unit/regression tests pass (`-m "not integration"`) incl. 80+ new cases (engine resolver,
plan-check policy, CLI, dispatcher, hook wiring, activity); Docker tier 19/19 (`test_supervisor_e2e.py` +
`test_policy_hooks.py` — escalation resolves aligned/divergent with exactly one frontier invocation, plan-check error
ledger event, CLI wiring persistence, cascade-off regression, plus a `slow`-marked real-LLM short-circuit e2e: the
default checker via the host's port-4001 LiteLLM approves an aligned action with zero frontier invocations);
`make pre-commit` hooks clean on all touched files.

**Deferred**: allow-verdict rationale is debug-logged only — validating false-aligned rates needs shadow-sampling
(follow-up idea on the card).

### codex_frontend Phase 1 follow-up: cross-project trust probe (stage 84) -> SCOPED

**Goal**: Settle the last untested Phase-1 assumption gating the Phase 6 installer story -- does ONE Codex trust
ceremony trust a hook command string in an UNRELATED repo, or only the enrolled project + its `git worktree` checkouts
(82w)?

**Key changes**:

- **New probe** `scripts/experiments/codex-hooks/stages/84-fresh-project.sh` (extends the round-3 fixture harness;
  headless, consumes the stage-80 enrolled fixture, no new ceremony). A fresh `git init` repo at a never-seen `mktemp`
  path registers a byte-identical single-entry SessionStart (same stable `$HOOKBIN/SessionStart.sh` command, differing
  ONLY in the registering config path); the path-stable user-level hook is the positive control. Two legs: 84a (no
  folder trust) then 84b (folder-trust deconfound -- 40b: folder trust alone does not fire hooks, so a fire there is the
  definition hash). Canonicalized `FRESH` (macOS /var->/private/var) so the run cwd matches the trust path; single
  `finish_verdict` exit (restore-from-base + exit-code policy); pre-leg `grep -F` self-guards; rejects
  `PROBE_USE_REAL_CODEX_HOME=1`. Wired into `reproduce.sh` (`FIXTURE_STAGES`, budget); README stage-map + 5-verdict
  vocabulary + de-staled "fixtures are headless-unavailable" bottom section.
- **Finding (real codex 0.139.0): `[CROSS-PROJECT-TRUST-SCOPED]`** -- both legs proj=0 user=1 (turn ran, positive
  control fired -- a real no-fire, not a dead turn), self_enroll=no. Cross-project trust does NOT hold; the 82w worktree
  survival was worktree->checkout canonicalization, not portable command-string trust. **Installer reframe:**
  project-scope = a ceremony per repo; USER-scope (`$CODEX_HOME/config.toml`) = one ceremony covers all projects
  (path-stable).
- **Docs synced**: card Risk bullet (UNTESTED -> RESOLVED/SCOPED) + 82w annotation; checklist new ticked Phase-1 item +
  Worktree/installer-scope Open Decision reframed; design.md §5.5.5 + `registry.py` codex note "per CODEX_HOME" ->
  path-keyed trust + user-scope guidance.

**Verification**: probe ran live on real codex 0.139.0 (2 turns) -> SCOPED, cross-checked against the
`meta/user-config.84{a,b}-after.toml` captures (not just oracle text). `bash -n` clean; shellcheck stage 84 = only info
SC1091 (one fewer finding than the shipped stage 82 -- at parity); `pre-commit` clean on stage/harness/README; the
registry-note edit carries no test assertion (grep clean), runtime/preflight suites rerun green.

### codex_frontend Phase 2 follow-up: suppress Claude display vestiges on Codex `session show`

**Goal**: Stop `session show` printing `Agent: claude-code` and `Model Family: anthropic` for Codex sessions.

**Key changes**: `_print_session_detail` gates the `Agent:` line (display-only `intent.agent` vestige, superseded by
`Runtime:`) and the whole Computed Context block (Claude routing/tier/policy state) on `runtime == "claude_code"`.
Claude sessions render unchanged; `--json` keeps its documented env-derived `context` shape.

**Verification**: new `test_show_human_suppresses_claude_vestiges` + 229 session CLI tests green; mypy clean.

### codex_frontend Phase 2: One-command Codex bridge CLI (`session start --runtime codex`)

**Goal**: Wrap the Phase-5e `bridge_session_to_codex` op in a real session lifecycle -- one command derives a
Codex-runtime session from a Claude parent, runs the first `codex exec` turn, and makes continuation a first-class
`session resume` path.

**Key changes**:

- **CLI**: `forge session start [name] --runtime codex --resume-from <parent> --task "..."` (per the resolved flag-shape
  decision) with `--strategy` (default `ai-curated`), `--depth`, `--sandbox`, `--worktree/--branch`; 17 Claude-only
  flags rejected with codex and 5 codex-only flags rejected without it. `forge session resume <name> --task "..."`
  dispatches on `intent.launch.runtime` before any Claude predicate and runs `codex exec resume <thread_id>` (cross-CWD,
  in the session's recorded worktree, prompt on stdin); `_launch_claude_for_session` refuses codex manifests as a
  backstop. New `cli/session_codex.py` (rendering) + `core/ops/codex_session.py`
  (`start_codex_session`/`continue_codex_session`). `session show` renders Runtime/Thread/Rollout/Auth; JSON adds
  `intent.runtime` + `confirmed.codex`.
- **Manifest**: `LaunchIntent.runtime` (registry ids `claude_code`/`codex`; CLI maps `claude` -> `claude_code`;
  `launch.runtime` blocked in `session set`), new `SessionConfirmed.codex` (`thread_id`, `rollout_path`,
  `rollout_source="discovered_by_thread_id"`, `auth_method`/`auth_source`/`billing_mode` from preflight, `last_run_at`).
  `confirmed.launch` + `claude_session_id` stay unset for codex (Claude-resume predicates refuse for free; ANTHROPIC-key
  posture would misread). Older Forge cannot read new manifests (strict dacite) -- accepted research-preview break; old
  manifests read fine (additive field with default).
- **Invoker**: `CodexStreamResult.thread_id` parsed from `thread.started`; runtime-neutral
  `HeadlessResult.runtime_session_id`; `prepare_codex_request(resume_thread_id=...)` appends the probe-60 form-A
  `resume <tid>` argv. New `core/runtime/codex_rollouts.py` (`find_rollout_path` by thread_id, newest-mtime wins).
- **Transfer/GC**: the snapshot is keyed by the **real session name** (Derivation.context_file -> GC-protected),
  structurally retiring the Phase-5e synthetic-children debt; bridge gains `child`/`preflight`/`output_root` (snapshot
  written under the child's indexed forge_root for nested-project worktrees, same output-root pattern as the fork
  precedent); stale-snapshot guard (reference-checked via new public `gc.referenced_transfer_context_paths()`;
  unreferenced -> replaced with paired `.notes.md`; referenced -> error) and two-phase rollback (guard failure deletes
  only the session; post-guard failure also deletes this run's snapshot+notes).
- **Docs**: design.md §3.4/§3.5/§3.9/§4.0 (one-command frontend shipped, runtime dispatch, `confirmed.codex` ownership);
  end-user `session.md` (Codex workflow + cheat sheet) + `transfer.md` (one-command flow promoted, manual recipe kept
  for sessionless handoffs).
- **Review fixes (pre-merge)**: post-creation lookup/rollback-delete scoped to the child's forge_root -- session names
  are project-scoped, so the unscoped strict resolution raised `AmbiguousSessionError` and stranded the just-created
  session whenever another project had the same name (child root now read from `state.forge_root`, no index round-trip);
  resume refreshes the recorded auth posture (`auth_method`/`auth_source`/`billing_mode`) from the fresh preflight so
  `session show` cannot report the first turn's auth after the user switches Codex auth. Regressions:
  `test_codex_session.py` (cross-project duplicate start + rollback isolation, changed-preflight resume).

**Verification**: ~150 new/extended unit tests green (invoker stream/argv, manifest roundtrip + override rejection,
rollout discovery, bridge extensions, op lifecycle incl. rollback/collision/worktree-ownership GC pinning, CLI flag
matrix/dispatch/rendering); full CLI package 1619 green; mypy/pyright clean. **Live**: real-codex E2E
`tests/integration/core/test_codex_session_start.py` passed (2 real turns) -- verifies the two probe-61 claims as a
standing guard: the `$CODEX_HOME` rollout filename ends with the live stream's thread_id, and stdin-prompt +
`exec resume` recalls turn-1 state with a stable thread id. (Probe stage 61 script written + wired into `reproduce.sh`;
the E2E supersedes its one-shot run.)

### codex_frontend Phase 1 closeout: `pretool_policy` rise + preflight `[hooks.state]` decision

**Goal**: Ship the one code unit Phase 1 deferred for an explicit decision -- align the capability encoding with the
round-3 probe findings before Phase 2 sessions load `design.md` §5.5.5 as context.

**Key changes**:

- **Registry (`core/runtime/registry.py`)**: Codex `pretool_policy` `"none"` -> `"partial"` -- Phase 1 confirmed
  post-enrollment PreToolUse deny (JSON + exit-2) and `updatedInput` mutation headless, refuting the old "unprobed"
  rationale. `"partial"`, not `"full"`: enforcement exists only in trust-enrolled homes, malformed hook output FAILS
  OPEN, and PermissionRequest is unpinned headless. `PolicyEnforcement` comment rewritten (Codex is now the partial
  runtime); the stale Codex `note` claims ("only SessionStart observed", "registration-string dimension unprobed",
  "until pre-enrollment is settled") replaced with the round-3 facts (full event coverage incl. 30e, command string in
  the `trusted_hash`, guided-ceremony posture, worktree survival, fails-open caveat, `Bash`/`apply_patch` tool names).
- **Preflight (`codex_preflight.py`, comments/docstrings only -- behavior unchanged)**: the four forward-pointing "the
  `[hooks.state]` read is Phase 1" notes now record the resolved decision -- the read is deliberately NOT implemented
  (the `trusted_hash` is not black-box computable so a record cannot be validated; enrollment survives worktrees with no
  record at the worktree's config path, so a path-keyed read would false-negative). The seam stays `enrollment_gated`;
  `untrusted` stays reserved, reachable only if a codex-cli source-dive recovers the hash.
- **`design.md` §5.5.5 synced**: `pretool_policy="partial"` with probe facts + caveats; the enrollment parenthetical
  states the settled guided-ceremony posture. Board: card Deliverables 2/3 + checklist Current Focus/Phase 1/Phase 3
  updated.

**Verification**: 63 runtime/preflight/CLI unit tests green (assertions updated to `partial`); mypy clean; stale-claim
grep (`unprobed|only SessionStart|settles pre-enrollment|...`) empty over the normative surfaces (`docs/design.md`,
`docs/design_appendix.md`, `src/`, `tests/src/`) -- the active card/checklist round-2 snapshot lines that quote the
superseded wording are annotated as historical (superseded by round 3) rather than deleted; live
`forge runtime list --json` renders `pretool_policy: partial` + `native_hooks: enrollment_gated`; `make pre-commit`
clean.

### codex_frontend Phase 1: Enrollment-mechanics probe (harness + round-3 findings, codex 0.138.0)

**Goal**: Build the Phase 1 probe harness that pins Codex's enrollment mechanics (what `trusted_hash` covers, whether
Forge can pre-enroll programmatically, which events fire post-enrollment, worktree/path sensitivity), then run it. The
operator ran the ceremony + headless stages the same day, so the findings landed in this phase (below). The
findings-gated `codex_preflight.py` `[hooks.state]` slice + the registry `pretool_policy` rise are the one remaining
code unit, deferred for an explicit decision (see Findings).

**Key changes** (all under `scripts/experiments/codex-hooks/`, extend-not-fork):

- **`lib.sh` fixture mode (additive)**: `fixture_init`/`fixture_build`/`fixture_require` (a PERSISTENT enrolled
  `CODEX_HOME`+proj+hookbin under `$CAPTURE_ROOT/fixture`, surviving across runs; auth copied per run, removed on exit);
  the stable-PATH / swappable-BODY `fixture_tee`/`fixture_arm`/`fixture_tee_all` (the registered command string -- hence
  the trust key -- never changes, but the body is re-stamped per stage); `fixture_project_specs`/`fixture_register_*`;
  and a `PROBE_EXEC_CWD` override on `run_exec` (stage 82's worktree turn). 40d (trust survives body change) is the
  load-bearing assumption; stage 81 re-validates it first.
- **Stages 80-83**: `80-enroll-fixture` (guided TTY ceremony: register all 10 events + a matcher'd PreToolUse + a
  user-level + a sacrificial entry before ONE grant, snapshot the trust delta, verify SessionStart fires headless on two
  fresh runs); `81-enrolled-coverage` (40d re-validation, per-event fired matrix, 30a-30h response contracts with
  arm/tee discipline -- 30e gates Phase 4, PreToolUse deny/`updatedInput` gate Phase 3 + `pretool_policy`);
  `82-trust-dimensions` (40e command-string mutation with the primary as control; user-vs-project trust location;
  worktree path-sensitivity with a project-trust deconfound -> Phase 6 installer scope); `83-preimage`. **No
  `--dangerously-bypass-hook-trust` in 80-83** -- enrollment is the variable under test.
- **`hooks/hash-preimage.py`** (offline): parses the enrolled configs, joins each `[hooks.state]` key to its
  registration, and scans candidate canonicalizations, declaring a winner only when one reproduces EVERY harvested hash;
  `--emit-state` then forges a `[hooks.state]` record so stage 83 can prove programmatic pre-enrollment end-to-end
  (fresh home, forged record, headless turn). Honest when no candidate matches (posture -> guided ceremony; source-dive
  next).
- **`reproduce.sh`**: 80 added to `GUIDED_STAGES`; new `FIXTURE_STAGES=(81 82 83)` that `resolve_stage` recognizes but
  both default run sets EXCLUDE (explicit-only -- blind runs would burn quota against a maybe-absent fixture); budget
  table extended. **README** round-3 section (fixture model, ceremony, stage map, verdict vocabulary).
- **`tests/fixtures/codex/hooks/README.md` + 5 payloads**: `session_start`/`pre_tool_use`/`post_tool_use`/
  `user_prompt_submit`/`stop` `.stdin.json`, sanitized + provenance table filled. Surfaced + fixed a real `sanitize.sh`
  over-match (its `sk-` scan tripped on `task-*` plugin filenames in codex-home tree listings -> word-boundary anchor).
- **Board**: card.md round-3 facts; checklist 7/7 Phase-1 boxes ticked with verification; the three Phase-0/1 Open
  Decisions resolved (HookSupport name, guided-ceremony posture, project-scope worktree survival).

**Findings (codex-cli 0.138.0; captures at `~/.cache/forge-codex-hooks-probe/`)**:

- **Enrollment**: one "trust all" grant (operator wording: *"trust all - no command or hash"*) enrolled 13 keys;
  SessionStart fires headless reproducibly. **40d holds** (body-swap kept trust). **40e**: the command string IS in the
  per-entry `trusted_hash` (moved entry untrusted, primary intact).
- **Gates**: **30e PASS** (additionalContext token echoed -> Phase 4 SessionStart delivery viable headless); PreToolUse
  **deny** (JSON + exit-2) blocked and **`updatedInput` mutation took effect** (-> Phase 3 + justifies a
  `pretool_policy` rise); Stop block-once + UserPromptSubmit block work. **PermissionRequest did not fire under the
  read-only sandbox probe** (its headless behavior under permission-eliciting conditions is unpinned); **malformed
  PreToolUse output FAILS OPEN** (refutes the doc fail-closed claim -- Phase 3 caveat). `tool_name` is
  `"Bash"`/`"apply_patch"` (not `"shell"`).
- **`trusted_hash` NOT black-box computable** (0/13 over 15 canonicalizations) -> **posture = guided ceremony**
  (programmatic `[hooks.state]` blocked pending a codex-cli source-dive).
- **Enrollment survives worktrees of the enrolled project** (82w2, valid run): the project hook fired in a
  `git worktree` checkout with no folder `trust_level` and no `[hooks.state]` record at the worktree path (cross-checked
  against the captured clean base). Chained with 40b (folder trust alone does not fire hooks), that can only be a
  `trusted_hash` match on the definition (byte-identical command string). Mechanism not distinguished (path-independent
  hash vs worktree->checkout canonicalization), and broad cross-project trust is UNTESTED. **-> Phase 6 (holds either
  way): project-scope registration with a path-stable command string survives worktrees** (resolves the scope Open
  Decision; a fresh-project probe is owed before any cross-project trust story). The first 82w2 run was VOID (the
  persistent fixture had retained a worktree `trust_level` block); stage 82 was hardened with a strip-first clean base,
  `82w2`-before-`82w` ordering, and an INVALID self-guard, then re-run.

**Verification**: `bash -n` + `shellcheck 0.11.0` clean on `lib.sh` + stages 80-83 + `reproduce.sh` + `sanitize.sh`;
`py_compile` + self-test green on `hash-preimage.py` (incl. the fallback TOML parser); the live probe ran end-to-end (80
ceremony + 81/82/83) on real codex 0.138.0; findings cross-checked against the raw captures (streams/payloads/state),
not just oracle text; `sanitize.sh` passes; `make pre-commit` (incl. gitleaks/mypy/mdformat) clean on every changed
file; the hardened `82` re-run was cross-checked against the captured clean base (worktree block stripped, no worktree
`[hooks.state]` record). **Remaining**: the `codex_preflight.py` `[hooks.state]` slice + registry `pretool_policy` rise
(one `src/`+tests+design.md unit, deferred for a decision -- "hash-not-computable" means a static
`active`-via-validation verdict is unachievable, so the seam stays `enrollment_gated`).

### codex_frontend Phase 0: Registry correction -- `headless_inert` -> `enrollment_gated`

**Goal**: Correct the Codex hooks capability encoding refuted by gating-probe round 2: trust-enrolled hooks DO fire
under headless `codex exec` (40c2/40d) and interactively (50c) -- the gate is a one-time trust enrollment, not the
execution mode. First code commit of the `codex_frontend` card.

**Key changes**:

- `HookSupport` (registry) and `HookSeam` (preflight) renamed `headless_inert` -> `enrollment_gated` **together**, so
  neither half of the capability model retains the refuted value. Resolves the card's literal-name Open Decision.
- The preflight verdict is pinned as capability-not-state: "hooks can fire, but this preflight has not checked the
  `[hooks.state]` record" -- never treat it as `active`. The per-hook enrollment read is Phase 1.
- Codex `RuntimeSpec` note rewritten to the round-2 facts (trust lives in user `config.toml` `[hooks.state]` keyed by
  the registering config's absolute path; survives script-*content* changes; only SessionStart observed firing).
  `pretool_policy` stays `"none"` (post-enrollment PreToolUse unprobed). `design.md` §5.5.5 synced; card.md stale
  "hook_seam is today honestly `unknown`" line fixed.

**Verification**: 63 runtime/CLI/preflight unit tests green (incl. renamed
`test_enabled_is_enrollment_gated_never_active`); mypy clean; `rg headless_inert docs/design.md src/ tests/` empty; live
`forge runtime list` renders `enrollment_gated` and `forge runtime preflight codex` renders
`Hook seam: enrollment_gated` (render asserted, exit code orthogonal); `make pre-commit` clean.

## 2026-06-09

### Phase 6: Codex frontend evaluation (probe-only; runtime_abstraction complete)

**Goal**: Evaluate Codex as a Forge frontend runtime -- a reproducible probe + a go/no-go decision record + a follow-up
build card -- without shipping product code. Closes the last open phase of `runtime_abstraction`.

**Key changes**:

- **Probe harness** `scripts/experiments/codex-hooks/` (mirrors the native-resume precedent): staged `reproduce.sh`,
  isolated `CODEX_HOME` (auth copied 0600 into a disposable tree), per-label tee/respond hooks, JSON/TOML registration
  generator, scan-and-fail `sanitize.sh`. Stages 00/05 (preflight + schema, 0 turns), 10 (headless-fire gate), 20
  (payloads), 30 (responses, moot-headless), 40/50 (trust/interactive -- headless parts + operator-gated TTY steps), 60
  (exec-resume), 70 (bypass, moot-headless). A capture-dir false-positive bug was found and fixed (probe_init clears the
  per-stage dir).
- **Gate finding (codex-cli 0.138.0):** Codex hooks do **NOT** fire under headless `codex exec` -- 0 firings across all
  4 registration surfaces, with `--dangerously-bypass-hook-trust`, on repeated same-home runs, confirmed by 5
  independent clean isolated tests. So headless policy enforcement and SessionStart transfer injection are unavailable
  on `codex exec`; interactive firing is UNVERIFIED (needs a TTY operator session).
- **Other pinned facts:** `codex exec resume <thread_id>` works and is **cross-CWD** (`--json` composes; `--last`
  unreliable); payload shape is snake_case as documented; registration validation is shallow (bogus event names load
  silently); session files at `$CODEX_HOME/sessions/.../rollout-<ts>-<session_id>.jsonl`; `FORGE_SESSION` reaches the
  model shell.
- **Go/no-go:** bridge CLI = **GO** (no hook dep; resume verified); SessionStart delivery = **NO-GO headless ->
  initial-message stays primary** (vindicates the Phase 5 deferral); hook adapter + interactive frontend = **gated on an
  interactive-firing probe**; app-server = deferred. Build work seeded in `docs/board/proposed/codex_frontend/`.
- **Registry correction** (`src/forge/core/runtime/registry.py`): the Codex `RuntimeSpec` read as "hooks work once
  version-gated" (`native_hooks="gated"`, `pretool_policy="partial"`), but hooks are enabled + version-OK yet do not
  fire headless. Corrected the **machine-readable fields**, not just the note: `native_hooks="headless_inert"` (new
  `HookSupport` value) + `pretool_policy="none"`, so a consumer reading the field -- not just the prose -- sees the
  limit. `codex_preflight.py` aligned: `hook_seam` now returns `headless_inert` (new `HookSeam` literal) for the normal
  enabled+version-OK headless case instead of `unknown`, so `forge runtime preflight codex` reports a known negative,
  not "trust unproven" (still never `active`).
- **Checklist compaction:** Phase 6 planning pushed the checklist over the 30k-token board hook; Phases 2/3-hardening/4
  (4a-4f) slice bodies compacted (state + decisions + debt preserved; verification bodies in git history + these
  entries). 31.2k -> ~25k tokens.

**Verification**: `bash -n` + shellcheck clean on the harness; stages 00/05/10/20/60 + headless 40/50 run green with
captures; the runtime/preflight/CLI suites (`test_registry.py`/`test_runtime.py`/`test_codex_preflight.py`) pass + mypy
clean after the field/seam/note edits. Probe spent ~10 short ChatGPT-quota turns. No runtime/execution behavior changed
(nothing branches on these capability values); only `forge runtime list`/`preflight codex` now render the corrected
`native_hooks`/`pretool_policy`/`hook_seam`. **`runtime_abstraction` is fully executed (Phases 0-6)**; the
`doing/ -> done/` lane move is gated on the merge to `main`.

### Phase 5f: Phase 5 doc sync + `forge transfer` end-user guide (docs-only closeout)

**Goal**: Sync the normative + end-user docs to shipped Phase 5 (Codex headless runtime) behavior and close out Phase 5.

**Key changes**:

- `design.md` §3.9 rewritten from pre-5e future tense to shipped: the `bridge_session_to_codex` cross-runtime hop
  (parent -> ai-curated Codex-targeted transfer -> body prepended to the `codex exec` prompt -> `CodexHeadlessInvoker`,
  one run tree), initial-message delivery as the Phase 5 mechanism (SessionStart-hook delivery deferred to Phase 6), and
  the honest CLI status (no `--runtime codex` frontend yet; user surface = `regenerate --target-runtime codex` + manual
  `codex exec`). §3.14 gained a "Transfer curation usage (Phase 5e)" paragraph. The bridge is documented in §3.9 (a
  cross-runtime resume-delivery op), not §5.5.5, which was already correct.
- `design_appendix.md` §A.13: `codex_exec` (route) + `codex_jsonl` (reporter) flipped reserved -> emitted; the
  per-emitter table gained the `transfer-curate` row; §M.1 `target_runtime` comment de-staled.
- New end-user guide `docs/end-user/transfer.md` (the chosen home): documents the previously-undocumented
  `forge transfer show|regenerate|edit|diff` group + the three-file model + the cross-runtime "plan in Claude, implement
  in Codex" workflow (honest that the one-command bridge is Phase 6). Registered in `README.md`; `session.md` repointed.
- `card.md` Phase 6 note corrected ("Phase 5 uses only `SessionStart`" was wrong -> initial-message delivery). The dated
  5a change_log "provisional" line is left as a historical snapshot.

**Verification**: `make pre-commit` clean (mdformat + the new guide); design docs under the tiktoken size hook; grep
gates clean (`SessionStart` outside `done/` names initial-message delivery; `codex_exec`/`codex_jsonl` shown as
emitted); `forge transfer --help`/`regenerate --help` confirm the guide matches the shipped CLI; the documented
`regenerate -> show -> codex exec` path is covered end-to-end by the 5e real-codex E2E
(`tests/integration/core/test_claude_to_codex_resume.py`). **Phase 5 is complete** (5.0/5a-5f shipped).

### Phase 5e: Claude->Codex resume bridge (the payoff)

**Goal**: Compose the Phase 5 build-group parts into the "plan in Claude -> implement in Codex via curated transfer"
hop, attributed across one run tree.

**Key changes**:

- New `core/ops/codex_bridge.py::bridge_session_to_codex` (UI-agnostic core op; no CLI -- the `--runtime codex` frontend
  is Phase 6): parent session -> ai-curated transfer (`target_runtime=codex`) -> body **prepended to the `codex exec`
  prompt** (initial-message delivery, not a `SessionStart` hook -- per-hook trust is unconfirmable, 5a) ->
  `CodexHeadlessInvoker().run`. Returns `CodexBridgeResult`; raises `ForgeOpError` for bad strategy / missing parent /
  non-ready Codex (Codex's own success/failure rides on `.codex`, not raised).
- "One run tree" is an `os.environ` contract: the bridge mints a fresh root (`new_root_run_identity()`) into env via a
  tested `_temporary_run_env` context manager, so both the curation `core.llm` call and the `codex exec` run derive
  under it -- no API change to the 5b/5c emitters. Per-run child key (`<parent>-codex-<run-suffix>`) avoids re-feeding a
  stale frozen snapshot.
- Part A: instrumented the ai-curated transfer curation (a previously-unattributed `core.llm` call) to emit a usage
  event (`.ask`->`.complete` to capture in-band tokens; `route=core_llm` / `runtime=forge_cli` /
  `command=transfer-curate`). General gap-fix: no-ops without an ambient run identity.
- `compose_codex_initial_message` is the named prompt-composition seam (pure, unit-tested).

**Verification**: hermetic bridge + transfer + codex-emit unit/CIT suites pass (99); real-codex E2E
(`tests/integration/core/test_claude_to_codex_resume.py`, `@slow`) green against real `codex 0.137.0` (~8s; curation
mocked so codex auth is the only hard dep); 5b real-codex smoke regression green; `mypy` clean; `make pre-commit` clean.

**Deferred to 5f**: `design.md` §3.9/§3.14/§5.5.5 sync (initial-message delivery; curation usage event; bridge composes
preflight + invoker) + the end-user cross-runtime workflow doc. No CLI command and no `SessionStart`-hook delivery (both
Phase 6).

## 2026-06-08

### Phase 5b-5d: Codex headless runtime (invoker + usage + transfer relabel)

**Goal**: Ship the Codex build group -- a `CodexHeadlessInvoker` reusing the hardened lifecycle, a native usage emitter,
and a `target_runtime`-aware transfer relabel -- so the Phase 5e plan-in-Claude/implement-in-Codex bridge has its parts.

**Key changes**:

- **Probe-first (B0)**: captured a real `codex exec --json` run (codex-cli 0.137.0) verbatim into
  `tests/fixtures/codex/` (success + error streams + `-o` oracle + provenance README). The fixture is authoritative over
  docs; it confirmed the doc-sourced token field names (`input_tokens`/`cached_input_tokens`/`output_tokens`).
- **Parser (B1)**: `core/invoker/codex_stream.py` reduces the JSONL event stream -> `(final_text, tokens, is_error)`; a
  failed turn (`error`+`turn.failed`) maps to `runtime_is_error`.
- **Shared lifecycle (B2)**: extracted the hardened `run`/`run_parallel` lifecycle into `_HeadlessLifecycleBase`
  (`core/invoker/_lifecycle.py`) with six template hooks; `ClaudeHeadlessInvoker` subclasses it ("moved, not changed").
  Migrated ~30 test patch-strings `claude.<sym>` -> `_lifecycle.<sym>` across the invoker test + 3 review drivers + the
  json-flag regression; both retry-race canaries stayed green.
- **Invoker + builder (B3/B4)**: `core/invoker/codex.py` -- `CodexHeadlessInvoker` (format-retry predicate always
  `False`) + `prepare_codex_request` (argv `codex exec --json --sandbox`, key injected only for env/credential_file
  auth, no proxy, run-tree triple stamped via the neutral `stamp_run_identity` factored out of `build_claude_env`).
- **Usage (5c)**: `emit_codex_usage` -- `route=codex_exec`/`reporter=codex_jsonl`/`runtime_native`,
  `confidence=unavailable` + `cost=None`/`source_refs=None` (direct to OpenAI; honest cost absence), `billing_mode` from
  `CodexPreflight` via a new optional `Attribution.billing_mode`.
- **Transfer (5d)**: `target_runtime` threads through `assemble_transfer_context` (default `claude`, byte-identical to
  pre-5d) -> frontmatter + `## Runtime Hints`; `forge transfer regenerate --target-runtime {claude|codex}` defaults from
  the cache (no silent flip). Delivery is initial-message (no SessionStart hook -> Phase 6).
- **Design sync**: `design.md` §5.5.5 (shared `_lifecycle` base + two invokers), §3.14 (native Codex emitter), §3.9
  (`target_runtime` + initial-message delivery).

**Decisions**: 5c `confidence=unavailable` (ledger confidence is cost-only; Codex reports no $); 5d minimal relabel
(body stays Claude-worded; curation tuning deferred); SessionStart-hook delivery deferred to Phase 6 (`hook_seam` can't
confirm per-hook trust).

**Verification**: 430 hermetic unit tests (invoker/usage/transfer/CLI + migrated review/regression); real-codex `@slow`
smoke green (8s, full stack: builder -> invoker -> real `codex exec` -> parser -> emitter); `mypy` clean (15 files);
`make pre-commit` clean.

### Phase 5a: Codex auth/runtime preflight (probe-first)

**Goal**: Ship a read-only native-Codex preflight -- run before any `codex exec` -- that resolves a non-interactive
credential, fails closed with setup guidance, and exposes a stable `CodexPreflight` contract for slices 5b/5c/5d, after
a live probe of the installed `codex` binary to correct doc-implied assumptions.

**Key changes**:

- **Stage-A probe (codex-cli 0.137.0, binary-authoritative)**: `codex doctor --json` is `schemaVersion: 1` with
  **string-boolean** auth details (`stored API key`/`stored ChatGPT tokens`/`stored agent identity` =
  `"true"`/`"false"`), parses a valid report **even on non-zero exit**, and reports `overallStatus="warning"` while auth
  is fine (so it must NOT gate readiness). It exposes **no per-hook trust** check -- so 5a never claims a trusted hook.
  Sanitized note in the 5a checklist.
- **`src/forge/core/runtime/codex_preflight.py`** (render-free core): frozen `CodexPreflight` + `preflight_codex` /
  `assert_codex_ready` (typed `CodexPreflightError`, mirroring `validate_proxy_startup`). Auth resolution is
  binary-authoritative: Forge `CODEX_API_KEY` (env/file) -> `CODEX_ACCESS_TOKEN` (env) -> `codex doctor` stored auth ->
  fail closed. `ready = installed AND auth resolved AND not responses-blocked` -- never `overallStatus`. `hook_seam`
  never returns `active` (trust is a 5d per-hook-hash check); managed suppression is claimed only on explicit
  `requirements.toml` evidence. The resolved key value is **never** a result field (would leak via `asdict()`/`--json`);
  5b reads it via the non-rendered `codex_api_key_for_subprocess()`.
- **Responses as a report, not a route**: `--proxy <id>` reads an existing proxy's `wire_shape` via
  `config.loader.load_proxy_instance_config` (lazy import; no `forge.proxy` dependency, no `/v1/responses` route);
  neither wire shape serves Codex Responses, so a proxied route is `proxy_unsupported` and direct `codex exec` is
  preferred.
- **`codex-api` (`CODEX_API_KEY`) credential** added to `CREDENTIALS`; note clarifies it is not OPENAI_API_KEY and not
  the ChatGPT login (Codex owns its own store).
- **CLI** `forge runtime preflight codex [--proxy] [--json]`: Rich report; `--json` dumps the secret-free dataclass;
  exit 1 when not ready.
- **Review hardening (2026-06-08)**: `_resolve_responses_posture` catches the config loader's `ValueError`/`TypeError`
  (invalid id / corrupt `proxy.yaml`) -> `proxy_unsupported`, not a traceback (preserves the never-raise contract);
  version comparison pads components (`0.131` meets the `0.131.0` floor); stored-auth resolution documented as
  PRESENCE-based (a non-"ok" `auth.credentials.status` does not fail-close -- validity is proven at 5b). Stale
  credential docs updated (`authentication.md` + `design_appendix.md`: six credentials, `codex-api` row,
  `not_needed_for` note); managed-suppression tests made fully hermetic + the nested-TOML parser branch covered.

**Verification**: 85 focused tests (`test_codex_preflight.py`, `test_runtime.py` preflight, `test_capabilities.py`
codex-api) + 244 broader (auth/runtime/CLI) green; mypy + pyright 0/0/0 on changed src. Live
`forge runtime preflight codex` on 0.137.0: `chatgpt_tokens`/`subscription_quota`, `hook_seam=unknown`,
`doctor=warning`, **Ready YES**, exit 0 (unknown `--proxy` -> exit 1; non-codex runtime -> exit 2). No
Docker/integration tier (5a spawns nothing). 5b-5f remain provisional pending a re-plan from the Stage-A findings.

### Phase 5 planning + Slice 5.0: Codex/Claude runtime-fact corrections

**Goal**: Scope Phase 5 (cross-runtime resume) and, before planning, re-verify the `runtime_abstraction` card's
external-tool assumptions against current Claude Code + Codex CLI — the card pinned Codex 0.124.0, now 0.137.0 stable
(~13 minors stale).

**Key changes**:

- **Research**: three adversarially-verified web sweeps (every claim grounded in fetched official docs or the installed
  `codex` binary) produced a per-assumption diff. Corrected stale Codex facts: hooks are **default-on**
  (`[features] hooks`; `codex_hooks` is a **deprecated alias**, not "required" and not "removed"); **10** lifecycle
  events (was 5); `SessionStart` additionalContext is the transfer-injection seam but **conditional** on hook
  enablement+trust (keep an initial-message fallback); `PreToolUse` can mutate via `updatedInput`; first-party
  non-interactive auth (`CODEX_API_KEY` / `codex login --device-auth` / enterprise tokens) + `codex doctor`; Codex emits
  `wire_api="responses"` only, so a proxy must serve Responses on its **Codex-facing** surface (a translated
  chat-completions backend does not block); `codex app-server --stdio` is a real alias for `--listen stdio://` (verified
  against the 0.137.0 binary — the rendered docs table omitted it).
- **Slice 5.0 (registry, shipped)**: `core/runtime/registry.py` Codex `RuntimeSpec` → `hook_feature_flag=None`,
  `hook_min_version="0.131.0"`, default-on note (10 events, `updatedInput`, `allow_managed_hooks_only`, Responses,
  SessionStart-trust caveat); `HookSupport` comment generalized to version-gated. `card.md` hooks paragraph + capability
  matrix + posture bullets + Phase 5/6 notes and `design.md` §5.5.5 corrected.
- **Plan**: `checklist.md` Phase 5 expanded from a 4-task stub to slices 5.0 (done) → 5a auth/runtime preflight → 5b
  `CodexHeadlessInvoker` (one-shot `codex exec`) → 5c usage attribution → 5d target-runtime curator (SessionStart +
  fallback) → 5e Claude→Codex demo → 5f doc sync, with fixture-grounded acceptance tables, a research verdict, and an
  Open Risks list. Transport decision recorded: one-shot `codex exec` (app-server a deferred follow-up).

**Verification**: `tests/src/core/runtime/test_registry.py` + `tests/src/cli/test_runtime.py` → 17 passed; mypy clean on
changed src. Otherwise docs/planning (no runtime behavior change beyond registry data). `make pre-commit` clean.

### Phase 4g: Exact cost attribution for proxied `claude -p` (run-tree correlation)

**Goal**: Replace the concurrency-fragile before/after proxy snapshot delta for proxied `claude -p` cost
(`verb_snapshot_estimated`, polluted when a session shares the proxy) with an **exact** join that correlates each cost
record to the Forge run that incurred it. ToS-clean: Forge's own headless subprocesses through Forge's own proxy, opaque
non-secret run ids; no credential extraction; the interactive OAuth session is untouched. Resolves the last Phase 4 open
decision.

**Key changes**:

- **Join key is the run tree, not `source_refs`.** One `claude -p` run makes many requests, so the single-valued
  `source_refs.cost_request_id` is the wrong shape — `source_refs` stays null on `claude -p`
  (`test_bug_usage_claude_p_null_source_refs.py` holds, no `UsageEvent` schema change). Cost records gain additive
  `forge_run_id`/`forge_root_run_id` (`schema_version` 1, no bump; reader uses `.get()`).
- **Env injection (gated, Forge-owned).** `build_claude_env` stamps `X-Forge-Run-ID`/`X-Forge-Root-Run-ID` via
  `ANTHROPIC_CUSTOM_HEADERS` only for a headless child (`derive_run_identity`) targeting a **proven Forge proxy**
  (`target_is_forge_proxy` OR marker present **and** `base_url == FORGE_SUBPROCESS_BASE_URL`) — an opaque/third-party
  base_url, including an inherited marker + explicit opaque override, never leaks the header. Strips inherited
  `X-Forge-*` lines, preserves user lines.
- **Proxy validate + stamp.** Middleware validates each inbound id (`^run_[0-9a-f]{12}$`, shared with `mint_run_id` via
  the new dependency-free `forge.core.run_id` leaf) and stores `None` on a spoof/malformed value; threads the ids
  through `_calc_and_log_cost` -> `log_request_cost`. One site covers both wire shapes.
- **Read-time root join + suppression.** `sum_reported_cost_by_root` returns `has_records`/`runs_with_records`
  (presence, incl. dollar-less records) and `has_cost`/`per_run` (dollars) separately;
  `usage_summary._join_session_cost` sums by `forge_root_run_id` and suppresses a `verb_snapshot_estimated` event
  **per-run-subtree** — only when its OWN run produced records, or it is a verb whose DIRECT children did (fan-out, via
  worker `parent_run_id`). Whole-root suppression was wrong: it dropped a correctly-unstamped sibling's snapshot
  whenever any run under the shared session root was stamped (silent undercount). A no-dollars route renders
  **unavailable**, never `$0`; root-summing still captures orphan cancelled leaves. The event stays
  `verb_snapshot_estimated`; the read surface recomputes the exact figure (`proxy_request_exact`) and renders it
  **without the `~` estimate marker** (`cost_estimated=False` on the summary/command DTOs drives `forge activity` and
  the session-end line).

**Verification**: Unit + regression suites green — `test_run_id.py`, `test_cost_logger.py::TestForgeRunCorrelation`
(+`runs_with_records` presence), `test_env.py::TestCorrelationHeaders`, `test_usage_summary.py::TestRootJoin4g`
(+exactness flags), `test_activity.py` (exact renders without `~`), and
`tests/regression/test_bug_4g_mixed_stamped_unstamped_undercount.py` (the shared-root undercount guard); mypy clean.
Docs synced (design.md §3.14, design_appendix.md §A.9/§A.13, card + checklist). **4g.0 feasibility canary PASSED**
(`tests/integration/proxy/test_forge_run_id_correlation.py`, all 6 cases, 28.6s) against a live OpenRouter-backed Forge
proxy on **Claude Code 2.1.168** — proving the load-bearing external dependency on the real wire: plain `claude -p`,
`claude -p --bare`, and a multi-request tool loop where the tool loop forced >= 2 requests and **every** record carried
the run ids. The standing version-regression guard records the validated version (`CLAUDE_VERSION_VALIDATED`).

## 2026-06-07

### Docs: correct the `claude_session_id` pre-seed lifecycle (design.md §3.3/§3.5 + session.md)

**Goal**: design.md §3.3/§3.5 and the end-user session guide said `claude_session_id` is "not pre-seeded by the CLI" /
"`None` until Claude starts" / "a non-null value means it has been used" — true only for the native `--fork-session`
path. The `forge session start` path (and transfer/fresh children) actually **pre-seed** it (the CLI generates the UUID,
writes it at creation, imposes it via `--session-id`) and the SessionStart hook **validates** it. Align the normative
and user docs to the shipped code (documentation-guidelines Rule 2: design docs describe shipped behavior).

**Key changes**:

- **design.md §3.3** (1:1 invariant): every launch that starts a **new** Claude conversation pre-seeds —
  `forge session start` and transfer/fresh children (`fork`, `resume --fresh`) generate a UUID and impose it via
  `--session-id`, which the hook validates; only **native** `--fork-session` forks do not pre-seed (Claude mints, hook
  records; `native-relocate` reuses the parent UUID). A non-null UUID alone is **not** "used" (a `--no-launch` start
  session already carries a pre-seeded UUID) — "used"/resumable requires hook confirmation or transcript-backed
  evidence, matching `_is_resumable_session` ("Pre-seeded UUIDs without other evidence are still rejected").
- **design.md §3.5**: the CLI-writes note now states the CLI pre-seeds for start + transfer/fresh children; the
  Hooks-write note says SessionStart validates (those paths) or records (native `--fork-session`).
- **end-user/session.md**: same corrections, and fixed a self-contradictory resume section — the stale "never-launched →
  launch in-place / previously-used → fork" bullets now describe reattach-by-default vs `--fresh`-derives-a-child,
  matching the adjacent intro/Gates text and `_reconnect_in_place` (`--resume`, no `--fork-session`).

**Verification**: Docs-only — no code change (the code was already self-consistent: `models.py:400` comment, the
start/fork launch paths, and `_is_resumable_session` all agree). Grep confirms no stale "not pre-seeded" / "None until
Claude starts" / "non-null means used" claims remain outside `done/`. `make pre-commit` clean.

### Fix: `project_root` consistently git-common-dir-derived (workspace_scope Slice 1)

**Goal**: Sessions started in a **manually**-created linked worktree (`git worktree add`, then `forge session start` —
not `--worktree`) did not group under `--scope workspace`, defeating the core motivation of the `workspace_scope`
proposal. Fix the latent `project_root` derivation bug rather than layer a new scope concept over it.

**Key changes**:

- `SessionManager.start_session` and the same-directory `fork` path derived `project_root` via
  `find_project_root(worktree_path)`, which returns the *worktree's own* root for a linked worktree (its `.git` is a
  file). Both now route through the existing canonical `resolve_project_root()` (`get_main_repo_root` + graceful non-git
  fallback), so `project_root` is the shared git-common-dir root for every worktree of a repo — aligning the code with
  design.md §3, which already names `get_main_repo_root()` as the `project_root` identity source. Removed the now-unused
  `find_project_root` import.
- Minor improvement: a `.forge/`-enabled non-git directory no longer raises mid-`start_session`; `project_root` degrades
  to the directory itself, consistent with how `checkout_root` already falls back.

**Verification**: New regression `tests/regression/test_bug_workspace_scope_manual_worktree.py` (confirmed failing on
the old derivation — `wt-sess` missing from `--scope workspace` — and passing after the fix). 1031 session+ops unit
tests pass; `make pre-commit` clean. No design-doc change (the fix makes code match the existing §3 contract).

### Rename `--scope repo` → `--scope workspace` (workspace_scope precursor, clean break)

**Goal**: Resolve concern #1 from the `workspace_scope` proposal review — the proposed `--scope workspace` would have
been a synonym of the existing `--scope repo` (the logical-repo / worktree-family grouping). Rename the flag value
instead of adding a second name, so the CLI keeps one scope vocabulary.

**Key changes**:

- **Flag value renamed across all four command families** that share the `repo|project|all` scope: `forge session list`,
  `forge clean`, `forge memory status|shadows *`, and the `%session list` / `%clean` direct commands. `VALID_SCOPES`
  (`core/ops/session.py`, `core/ops/gc.py`), Click `Choice`/`default`/help, error messages, and the `%`-dispatcher
  defaults all use `workspace`. `session list` + `%session list` defaults flip `repo` → `workspace` (identical
  filtering, new name); `clean`/`memory`/`%clean` keep their existing `project` defaults.
- **Clean break (research-preview)**: `--scope repo` now fails with Click's native "invalid choice" — no alias or
  tombstone (coding-standards §5). This is a pure CLI-surface + `--json` `"scope"` output rename; the durable session
  index is untouched (the `project_root` field is kept — workspace membership is still derived from it, not stored).
- **Vocabulary swept** in prose/docstrings: "repo-scoped"/"repo-wide" → "workspace-scoped"/"workspace-wide" across
  design.md §3/§3.2/§4.0, design_appendix §B, end-user `session.md`, `diagrams.md`, and internal resolution docstrings.
  **Preserved deliberately** (workspace_scope card Open Q1, deferred): the `resolve_session_repo_wide` function symbol,
  the `project_root` field name, and the git-identity term "logical repo". `done/` board cards left as historical
  snapshots (board contract).

**Breaking change / reset**: `forge session list --scope repo`, `forge clean --scope repo`,
`forge memory ... --scope repo`, and `%clean --scope repo` are removed — use `--scope workspace` (same behavior). Update
any scripts/aliases.

**Verification**: 438 unit+regression tests pass across the affected suites (session ops, gc, resolution, clean CLI,
session/memory CLI, `%`-dispatcher, shadow curation, cross-project regression). Final grep confirms no `--scope repo` /
"repo-scoped" / "repo-wide" prose remains outside `done/`. `make pre-commit` clean.

## 2026-06-06 (compacted)

metric-evidence card closeout + cleanups (shipped 0.4.0, PR #18).

- **Version 0.3.0 → 0.4.0**; metric-evidence card `doing/ → done/`. Breaking CLI: `forge proxy costs` → `costs show`
  (Click consumes the first positional as a subcommand, so bare `costs` prints group help), `forge usage` →
  `forge activity` (reports Forge *automation* activity — supervisor/memory-writer/verbs/policy — not total usage). Old
  names are flag-tolerant hidden tombstones that exit non-zero naming the replacement.
- **Removed CLI rename-migration tombstones (clean break)**: error-only tombstone commands/flags (`forge usage`,
  `forge handoff run`, `forge session handoff`/`memory`, `search -q`, `memory track --as`, `--resume-mode handoff`, the
  `--force` "deprecated alias for --yes") and stale-state migration guards (`_RENAMED_KEYS`/`_REMOVED_KEYS`,
  `_REMOVED_STRATEGIES`/`scan_stale_passports`) deleted — degrade to the generic unknown-key/strategy-rejection paths.
  `schema_version` validators KEPT (forward-compat). `coding-standards.md` §5/§6 + `design.md` §4.0 realigned:
  command/option removals are clean breaks.
- **`forge proxy costs reset`**: wipes the three telemetry planes (`requests/`, `verbs/`, usage `events/`) + the derived
  status-line cost cache; spares audit + transcript cache-hit. Restart `Tip:` (a live proxy holds cost/cap totals in a
  separate process the CLI can't reach). `--dry-run`/`--yes`.
- **Status-line weekly quota**: both windows (`5h:N% · 7d:M%`, `_extract_windows` clean break), heat-mapped on the
  shared context gradient; reset countdown binds inline to the hotter window (`7d:52%↻1d`).
- **PR #18 adversarial review fixes**: tightened headless `--output-format json` retry `_REJECTION_RE` (a transient
  error echoing argv no longer latches JSON off process-wide / double-bills a proxied retry); `run_parallel` retry spawn
  mirrors the primary's `cleanup_started` re-check; launch-resurrection `exists()` guard; negative-delta clamp;
  `forge +$Y` counts `{reported, gateway_calculated}` and excludes the typed `ROUTE_CLAUDE_INTERACTIVE` route; legacy
  verb fallback trusts `cost_measured` only.
- **Cleanups folded in**: `sum_forge_added_cost` gained a `since` bound (no whole-ledger re-parse per poll); dormant
  `stream-json` parse branch removed (seam note left); DRY extractions — `core.state.decode_json_object` (one JSONL
  guard, 5 readers), shared `proxy_costs.py` aggregation, `emit.py` `_direct_cost_provenance` (proxied path stays
  per-caller to avoid double-counting the verb aggregate).
- **QA checklist coverage** (`src/skills/qa/`): closed 6 gaps where a cost-honesty regression would pass the release
  gate (§3.4 masking misfire, §7.12-7.14 cost honesty/provenance/tombstone, §8.5 `forge +$Y` segment).

## 2026-06-05 (compacted)

metric-evidence-simplification card (Phases 1-5): Forge never invents metric figures — every dollar is
reported-or-unavailable with recorded provenance.

- **Phase 2 (cost not an oracle)**: proxy cost reported-or-unavailable (`cost_usd` carriers; OpenRouter `usage.cost`,
  LiteLLM `x-litellm-response-cost`); unreported → `cost_micros=None`/`confidence="unavailable"`. Price catalog
  (`pricing.py`/`pricing.yaml`) **deleted** so it can't re-enter accounting. Breaking (research-preview): cost-record
  `estimated`/`pricing_source` → `reporter`+`confidence` (`COST_SCHEMA_VERSION` stays 1). Spend caps fire only for
  cost-reporting routes.
- **Phase 3**: `cap_mode` + strict pre-flight estimate removed; post-event enforcement only. Stale `cap_mode:` rejected
  with a tombstone. Reset: remove the `cap_mode:` line from `proxy.yaml`.
- **Phase 1/5 (schema + reporters)**: `core/usage/vocabulary.py` `Route`/`Reporter`/`Confidence` literals;
  `USAGE_SCHEMA_VERSION` stays 1 by decision (a pre-Phase-1 strict reader dropping new records is acceptable for
  best-effort telemetry). Headless cost precedence: one reporter per run (proxied → `forge_proxy`; direct → native or
  tokens-only/`unavailable`). Shared `core/reactive/headless_json.py` unwraps the `claude -p --output-format json` array
  envelope (2.1.165 emits an array, not the documented object; retry-once-and-latch).
- **Phase 4 (status-line honesty)**: billing `auto` renders `ambiguous` (never infers `api` from `ANTHROPIC_API_KEY`);
  additive `confirmed.launch`. Deferred: `usd_to_micros` vs proxy `round()` diverge ≤1 micro at half-micro fractions.

## 2026-06-04

- **Cost/audit JSONL readers (metric-evidence Phase 0)**: added the `isinstance(record, dict)` guard to four
  `.get`-after-`json.loads` readers (`read_cost_logs`, `read_verb_logs`, `read_audit_logs`, `CostTracker._parse_record`)
  so one non-object line (`[]`/`1`/`null`) no longer aborts `forge proxy costs`/`audit show`. Regression
  `test_bug_cost_log_non_dict_line.py`.
- **Status-line PR #16 review (5 findings)**: proxy GET `/` runs idempotent `_ensure_runtime_state()` (caps were
  load-order dependent); `render_segments` fail-open per producer; tier-scanner parity test; the "byte-identical output"
  claim qualified to the API billing path. Regressions `test_bug_proxy_root_caps_uninitialized.py`,
  `test_bug_statusline_producer_failopen.py`.

## 2026-06-03 (compacted)

- **runtime_abstraction Phase 4 follow-up**: `forge usage [session]` + session-end summary
  (`read_usage_events(session=)` filter, pure `build_session_activity_summary`; design §3.12/§3.14, appendix §A.13);
  sidecar usage-ledger mount (rw, proxy-id gated). Review fixes: workflow double-count (N-worker panel read as N+1)
  split into `CommandUsage.workers`; supervisor-warning misattribution. QA proxy bugs: accepts mid-conversation
  `{"role":"system"}`; passthrough streaming errors surface real status; QA refuses a stale-revision container.
- **Statusline Enhancement (Phases 1-5)**: config-driven status line — segment registry + lazy `RenderContext`;
  billing-aware cost (`api`→$ / `subscription`→quota / `ambiguous`→`≈$`); throttled file-backed `cache_hit`;
  Forge-unique opt-in segments (`supervisor`/`policy`/`audit`/`drift`); spend-cap proximity. Break: flat
  `show_rate_limits` → opt-in `rate_limits` segment. Golden no-op guard freezes default output.

## 2026-06-02 (compacted)

- **Phase 4 hardening (4a/4c/4d)**: `run_parallel` spawn/register TOCTOU fixed with a lock-guarded `cleanup_started`
  flag (children reaped exactly once; no Ctrl+C hang/orphan); typed `HeadlessResult.cancelled` (cancelled workers emit
  no error usage); `emit_direct_llm_usage` copies `cached_tokens`; both-or-neither `origin_run_id`/`origin_root_run_id`
  contract.
- **Phase 4 integration validation**: `test_policy_hooks.py` 10/10, `test_supervisor_e2e.py` 4/4, real-claude
  memory/workers green. Pre-existing: `test_real_shadow_curation_smoke` fails on a stale `--session` arg (PR #6
  ancestor; test-only, tracked).

## 2026-06-01 (compacted)

**runtime_abstraction Phase 4 (Slices 4a-4f)** — runtime-abstraction core:

- **4a run-tree env**: `RunIdentity` + `FORGE_RUN_ID`/`PARENT`/`ROOT`, orthogonal to `FORGE_DEPTH`; memory writer
  re-roots under the session's origin identity. appendix §F.5/§C.1.
- **4b usage ledger**: durable versioned `~/.forge/usage/events/` (third plane, joined by `request_id`; schema v1 strict
  reads, never-raising writer). design §3.14, appendix §A.13.
- **4c instrument paths**: `track_verb_cost` cost holder; emitters for workflow verbs + memory-writer/supervisor/shadow
  \+ action tagger; conservative `billing_mode` (no key-presence inference).
- **4d HeadlessInvoker**: new `core/invoker/` (`HeadlessRequest`/`Result`/`Attribution` + protocol +
  `ClaudeHeadlessInvoker`); review fan-out moved **verbatim** behind `run_parallel` (the seam is the lifecycle, not
  routing). design §5.5.5.
- **4e runtime registry**: frozen `RuntimeSpec` per runtime in `RUNTIMES` (the capability source Phase 5 reads);
  tri-state capability literals with version gates; `forge runtime list`. Nothing branches on it yet.
- **4f runtime-tagged ActionContext**: `ActionContext.runtime` required attribution (policy engine stays
  runtime-agnostic); Claude halves named behind `HookAdapter`/`HookResponder` protocols. design §4.1.4/§4.1.5.
- **Phase 3 native-relocate** (PASS on Claude 2.1.158): opt-in `forge session fork --resume-mode native-relocate` (host
  only; transfer stays default) with preflights + rollback + dir-scoped cleanup. Bug: `encode_project_path` now maps
  `_`→`-` (Claude 2.1.158 hyphenates underscores). Regression `test_bug_encode_project_path_underscore.py`. design §3.9.
  Deferred: `--rewrite-paths`, sidecar native-relocate, gated default flip.
- **Phase 2 optional audit proxy**: opt-in wire chokepoint (inert by default); orthogonal `wire_shape`
  (`openai_translated`|`anthropic_passthrough`) × `intercept.mode`; thinking-preserving passthrough;
  redact-before-persist audit JSONL (`forge proxy audit show|diff`); sidecar host-persistent mounts. design
  §7.x/§3.4/§3.7. Deferred: real-upstream `@slow` passthrough replay e2e.

## 2026-05-31

**runtime_abstraction Phase 1** — schema-backed curated transfer + `forge transfer` CLI:

- `transfer.py` `_build_ai_curated_output()` emits canonical sections 1-7 + User Notes overlay; `schema_version: 1`,
  `target_runtime` reserved for Phase 5; citations outside the seen turn range dropped so `schema: full` never
  overstates evidence. Three-file artifact model (`generated.md` cache, frozen `children/<child>.md`, `.notes.md`
  overlay). New `forge transfer show|regenerate|edit|diff`. design §3.9 reframes curated transfer as the primary
  cross-boundary substrate; appendix §M.
- Closeout decisions (keep-current): `--review` stays opt-in; `structured` stays the CLI default (`ai-curated` opt-in).
  `ctx` is prior art/inspiration only, never a dependency (appendix §M.4). Schema stable for Phase 5.

## 2026-05-28 — 2026-05-29 (compacted)

- **memory_substrate (PR #8)**: split "handoff" into **memory writer** (Stop-time doc curation) and **transfer**
  (resume/fork context). `handoff_agent.py→memory_writer.py`, `handoff.py→transfer.py`; CLI
  `forge handoff run→forge memory-writer run`, `forge session handoff show→forge memory report show` (old paths
  tombstoned). Durable accept-and-tolerate: `--resume-mode handoff→transfer`, `handoff_timeout→memory_writer_timeout`.
  Intentional `handoff` KEEPs (work-queue `kind="handoff"`, artifact path, `queued_handoff`) recorded in impl_notes.
- **Add Claude Opus 4.8** (retain 4.6+4.7): `claude-opus-4-8` opt-in ($5/$25/$0.50, 1M ctx, adaptive-only); `opus`
  defaults stay on 4.6; 4.8 takes over 4.7's review/template role.
- **Memory strategies 7→4**: removed `debugging`/`patterns`/`suggested` (shadow mode now orthogonal via `--propose`;
  `suggested_*→shadow_*`); `--as`→`--strategy` (`--as` a hidden tombstone). Stale removed-strategy passports rejected.

## 2026-05-22 — 2026-05-26 (compacted)

- **Memory Enhancement project (PR #1, Phases 0-5)**: passport-authoritative doc ownership replacing manifest
  `designated_docs[]`; two primitives — passports select docs, session activation decides whether the writer runs.
  `session/passport.py` (`MemoryStrategy`, YAML frontmatter, `synthesize_passport`, `PassportError`); top-level
  `forge memory enable/track/untrack/list/status` + `forge memory shadows review`. Removed `.forge/memory.yaml`
  activation, `MemoryIntent.designated_docs`, the three-tier resolver, `ProjectMemoryConfig`, `--inherit-memory`. design
  §5.6, appendix §G; card archived to `done/memory_enhancement/`.
- **CLI hardening**: command-shape invariant (groups orient, leaves act) — `forge config show`,
  `forge search query <terms>`, `forge proxy metrics` all-proxies. Shared recovery-tip helpers (`cli/output.py`); break:
  `forge backend create <existing>` errors + exits 1. Auto-start proxies from templates (`ensure_proxy`,
  liveness-aware). Live-session deletion protection (`forge session delete` refuses a live launch without `--force`).
  Regressions: supervisor-proxy-autostart, stale-healthy-proxy, delete-live-session.
