# Checklist: same_dir_transfer_forks

Branch: `same_dir_transfer_forks` · Plan: codebase-grounded + adversarially verified (10-agent workflow, 2026-06-15 —
capture → 3-lens design → judge synthesis → claim verification). Key correction folded in from verification:
`manager.fork_session` **records** derivation but does NOT **drive** the launch shape, so same-dir transfer needs three
coordinated edits (CLI guard relax + same-dir launch path + manager derivation), not a one-line decision flip.

Decouple transfer mode from worktree isolation in `forge session fork`. Same-directory forks stay native by default; an
explicit `--resume-mode transfer`, OR explicit transfer flags (`--strategy`/`--inline-plan`) that **auto-switch** the
fork (with a non-silent info line), route the existing CWD-agnostic worktree-transfer machinery into the same-directory
branch — no more silently-dropped flags.

**Current focus:** CLOSEOUT. Phases 1–3 shipped together in one pass (reviewer P1 folded the manager-derivation and
deferred-resume guard into Phase 1 for correctness under partial fork-creation failure, so there was no smaller
shippable unit). Implementation + tests + docs + integration all landed on branch `same_dir_transfer_forks`.

**Verification (2026-06-15):** `tests/src/cli/test_session_commands.py::TestSessionFork` (7 new same-dir tests) +
`tests/regression/test_bug_same_dir_transfer_fork.py` (3) +
`tests/src/session/test_fork_into.py::TestForkNativeRelocate` (incl. new derivation test) = 41 unit tests green; 4
integration tests green (new same-dir transfer argv + 3 adjacent fork-launch regressions) via
`./scripts/test-integration.sh`; `make pre-commit` clean (ruff/black/isort/mypy/pyright/mdformat/gitleaks).

## Decisions resolved by you (2026-06-15)

- **OQ1/OQ2 — AUTO-SWITCH (not hard error):** explicit `--strategy`/`--inline-plan` on a same-directory fork
  **auto-switches** the fork into transfer mode with a non-silent info line, instead of erroring. Encoded by resolving
  `resume_mode = "transfer"` early (Phase 1 task 1) so every downstream branch keys uniformly on
  `resume_mode == "transfer"`. Gating the trigger on `resume_mode is None` means an explicit
  `--resume-mode native-relocate` never auto-switches (it keeps its same-dir rejection). **Trade-off (accepted):**
  auto-switch couples the bug fix to the launch path — there is no smaller shippable unit, so old Phase 1
  (hard-error-only) and old Phase 2 (host launch path) are merged into one Phase 1 below.
- **OQ4 — REUSE `--resume-mode transfer`:** the explicit opt-in token is the existing fork `--resume-mode transfer`
  value (today a no-op tip on same-dir), not a new `--fresh-transfer` flag. `native-relocate` stays
  worktree/`--into`-only.

## Decisions resolved by planning (not user-facing)

- **Composition path (OQ3):** Same-directory transfer reuses the exact worktree path:
  `_sess()._generate_parent_transfer_context(strategy, inline_plan)` -> `_combine_prompt_files` (transfer doc + proxy
  addendum + configured manifest prompt) -> `invoke_claude(session_id=<fresh uuid>, system_prompt_file=...)` mapping to
  `--append-system-prompt-file`. No initial-message mechanism. Confirmed CWD-agnostic:
  `_generate_parent_transfer_context` (`src/forge/cli/session.py:704`) keys on `manifest.is_fork`/`parent_session`, not
  worktree; `assemble_transfer_context` returns a per-child file whenever `child_name` is set
  (`src/forge/session/transfer.py:1221`); for a same-dir fork `output_root` is None, so the child roots at `forge_root`
  (`transfer.py:1214`) — no worktree dir required. `_resume_fresh` (`src/forge/cli/session_lifecycle.py:1996`) is a
  working same-CWD precedent for this shape (host + sidecar).
- **Sidecar parity (OQ5):** `src/forge/sidecar/container.py` has zero fork/transfer logic; the gate is entirely the four
  `is_worktree_fork`-keyed args at `src/forge/cli/session_fork.py:999-1009`. Parity is achieved by replacing those with
  a `uses_fresh_transfer` predicate — no signature change to `_launch_claude_for_session`.
- **Derivation source-of-truth:** Both writers must agree. Teach `manager.fork_session` to honor
  `resume_mode=='transfer'` for same-dir (so a `--no-launch` fork persists transfer at creation), AND keep the CLI
  `_persist_fork_transfer_derivation` override (the only writer that records the real `strategy`). The manager
  pre-records `context_file` for transfer (`src/forge/session/manager.py:1368`).
- **native-relocate stays worktree-only:** It relocates the parent JSONL into a different encoded `~/.claude/projects`
  dir and is structurally cross-CWD (`src/forge/session/manager.py:1360`). Same-dir `--resume-mode native-relocate`
  keeps its rejection tip.

## Phase 1: Same-directory transfer launch path + auto-switch (host)

Under auto-switch, fixing the silent-flag-drop *is* adding the launch path — they ship together. The native same-dir
default (no transfer flags, no `--resume-mode transfer`) is untouched.

- [x] **Auto-switch resolution (pre-fork).** After `is_cross_dir` is known (`src/forge/cli/session_fork.py:394`), using
  the `_strategy_explicit`/`_inline_plan_explicit` ParameterSource.COMMANDLINE signals (`session_fork.py:337-338`, never
  truthiness so the `structured` default never trips it): when
  `not is_cross_dir and resume_mode is None and (_strategy_explicit or _inline_plan_explicit)`, set
  `resume_mode = "transfer"` and `print_tip` a non-silent info line ("`--strategy`/`--inline-plan` implies a transfer
  fork; using same-directory transfer"). Because the trigger requires `resume_mode is None`, an explicit
  `--resume-mode native-relocate` never auto-switches. All downstream logic then keys on `resume_mode == "transfer"`.
  - Assertion: same-dir `fork P -n C --strategy full` resolves `resume_mode=="transfer"` and prints the info line before
    `fork_session` (`session_fork.py:559`); same-dir `fork P -n C` (no transfer flags) leaves `resume_mode` None and
    launches native; `--strategy structured` typed explicitly still auto-switches (COMMANDLINE source), the unset
    default does not.
- [x] Delete the now-dead post-fork silent-drop tip at `session_fork.py:719-725` (it ran after `fork_session()` already
  created child state). `rg "ignored for same-directory forks" src/` returns nothing.
  - Assertion: a same-dir fork with explicit `--strategy` no longer prints "ignored for same-directory forks" (it
    auto-switches instead).
- [x] Relax the same-dir resume-mode tip at `session_fork.py:458-463` so it fires only for
  `resume_mode == "native-relocate"` on same-dir; `--resume-mode transfer` on same-dir must NOT print the "only applies
  to --worktree/--into" tip (it is now a valid opt-in).
  - Assertion: `fork P -n C --resume-mode native-relocate` (same-dir) still prints the "only applies to
    --worktree/--into" tip; `fork P -n C --resume-mode transfer` (same-dir) does NOT print that tip.
- [x] Compute `same_dir_transfer = (not is_worktree_fork) and resume_mode == "transfer"` and
  `uses_fresh_transfer = is_worktree_fork or same_dir_transfer` after `session_fork.py:701` (resume_mode is already
  resolved to "transfer" for the auto-switch case). Leave `native_relocate` untouched.
  - Assertion: with resume_mode resolved to "transfer" and a non-worktree fork manifest, `same_dir_transfer` is True;
    with `resume_mode is None` it is False; with `is_worktree_fork` True it stays in the worktree branch.
- [x] Split the same-dir `else` branch at `session_fork.py:930-953`: when `same_dir_transfer`, run the worktree sequence
  verbatim — `_generate_parent_transfer_context(manager, fork_manifest, parent_manifest, strategy, inline_plan)`;
  collect `[fork_context, _resolve_manifest_prompt_file(fork_manifest)]`; `_combine_prompt_files`;
  `_persist_fork_transfer_derivation(strategy, fork_context)`; pre-seed `_fork_uuid` + `claude_project_root` (the
  `877-897` block); merge proxy addendum via `_combine_prompt_files`;
  `invoke_claude(session_id=_fork_uuid, system_prompt_file=_prompt)` with NO `resume_id`/`fork_session`. When NOT
  `same_dir_transfer`, keep the existing native closure (`resume_id=parent_session_id`, `fork_session=True`,
  addendum-only) exactly as today.
  - Assertion: same-dir transfer fork calls `invoke_claude` with `session_id` set (a fresh uuid != `parent_session_id`),
    `resume_id` None, `fork_session` not True, `system_prompt_file` pointing at a file containing the generated transfer
    doc; plain same-dir fork still calls `invoke_claude` with `resume_id==parent_session_id`, `fork_session` True,
    addendum-only `system_prompt_file`.
- [x] Set `active_claude_session_id = _fork_uuid if uses_fresh_transfer else None` at `session_fork.py:1046` so the host
  post-exit/activity scoping and `run_with_active_session` use the fresh child UUID for same-dir transfer.
  - Assertion: host same-dir transfer fork: `run_with_active_session` receives `claude_session_id == _fork_uuid`; plain
    native same-dir fork still passes None.
- [x] Persisted-derivation override runs on the same-dir transfer branch (via the existing
  `_persist_fork_transfer_derivation` at `src/forge/cli/session_lifecycle.py:268`), overriding the manager baseline.
  - Assertion: after `fork P -n C --resume-mode transfer --strategy full`, reloaded manifest
    `confirmed.derivation.resume_mode == "transfer"`, `.strategy == "full"`, `.context_file` non-null.
- [x] Extend the `--strategy full` over-budget preflight gate at `session_fork.py:501` from `is_cross_dir` to
  `is_cross_dir or resume_mode == "transfer"` (resume_mode is resolved pre-fork, so an auto-switched same-dir fork is
  covered too). Grafted from UX-FIRST: a same-dir transfer with `--strategy full` over the limit must hit the same
  guard.
  - Assertion: same-dir `--strategy full` (auto-switched, or explicit `--resume-mode transfer`) with an over-limit
    parent transcript exits 1 with "exceeds context limit" (no `--force`); a plain same-dir fork never triggers the
    budget preflight.
- [x] Update `--strategy`, `--inline-plan`, `--resume-mode` help strings at `session_fork.py:125-151`: drop "worktree
  forks only"; state they apply to any transfer fork, that explicit transfer flags auto-switch a same-dir fork to
  transfer, and that `--resume-mode transfer` is same-dir-legal while `native-relocate` is cross-CWD-only.
  - Assertion: `forge session fork --help` no longer asserts these flags are worktree-only; `make pre-commit` clean.
- [x] Host tests (model on `test_resume_fresh_default_is_transfer` /
  `test_resume_fresh_native_uses_resume_fork_session`, `tests/src/cli/test_session_commands.py:~3315`; patch
  `forge.cli.session.SessionManager` + `forge.cli.session.invoke_claude`, the re-export path the existing tests use):
  auto-switch resolution + info line; same-dir transfer invoke shape; native default unchanged; derivation persistence;
  over-budget guard; inline-plan TEXT embedding (approved plan text appears in the combined same-dir child context file
  when `--inline-plan` + a `kind=='approved'` snapshot exists). Update `test_resume_mode_on_same_directory_fork_warns`
  (`test_session_commands.py:2284-2304`) to keep the native-relocate-on-same-dir tip and drop any silent-strategy-drop
  expectation.
  - Assertion: new `test_samedir_strategy_autoswitches_to_transfer`, `test_samedir_transfer_uses_fresh_session_id`,
    `test_samedir_native_default_unchanged`, `test_samedir_transfer_persists_derivation`,
    `test_samedir_transfer_over_budget_blocks`, `test_samedir_transfer_inline_plan_embeds_text` pass; the updated
    warns-test passes.

## Phase 2: Sidecar parity + manager derivation + deferred (--no-launch) resume

- [x] Generalize the sidecar dispatch args at `src/forge/cli/session_fork.py:999-1009` from `is_worktree_fork` to
  `uses_fresh_transfer`: `session_id=_fork_uuid if uses_fresh_transfer else None`;
  `resume_id=None if uses_fresh_transfer else parent_session_id`; `fork_session=not uses_fresh_transfer`;
  `register_fork=uses_fresh_transfer`; `system_prompt_file=prompt_file if uses_fresh_transfer else None`. Ensure
  `prompt_file` and `_fork_uuid` (pre-declared None at `729-730`) are assigned in the same-dir transfer branch.
  `container.py` needs NO change (it is a pure launcher; the composition lives in `_launch_claude_for_session`,
  `session_lifecycle.py:469-487`, already strategy-agnostic).
  - Assertion: sidecar same-dir `--resume-mode transfer` fork calls `_launch_claude_for_session` with
    `session_id==_fork_uuid`, `resume_id` None, `fork_session` False, `register_fork` True, non-None
    `system_prompt_file`; sidecar plain same-dir fork still gets `resume_id`+`fork_session` and `system_prompt_file`
    None.
- [x] Teach `manager.fork_session` derivation decision at `src/forge/session/manager.py:1358-1363` to honor a same-dir
  transfer request:
  `fork_resume_mode = "native-relocate" if (resume_mode=="native-relocate" and (create_worktree or is_into)) else "transfer" if (create_worktree or is_into or resume_mode=="transfer") else "native"`.
  The `context_file` pre-record at `1368` then fires for same-dir transfer too. CLI already passes
  `resume_mode=resume_mode` (`src/forge/cli/session_fork.py:570`) — already resolved to `"transfer"` for auto-switched
  same-dir forks.
  - Assertion: `fork_session(parent, create_worktree=False, resume_mode="transfer")` returns a child whose
    `confirmed.derivation.resume_mode=="transfer"` and `context_file==child_path_rel`; with `resume_mode=None` it stays
    `"native"`.
- [x] Make `_get_deferred_same_dir_fork_resume_id` (`src/forge/cli/session_lifecycle.py:197-222`) return None when
  `manifest.confirmed.derivation` is not None and `derivation.resume_mode == "transfer"`. This lets a `--no-launch`
  same-dir transfer fork fall through in `_launch_in_place` to `_resolve_derivation_context_file`
  (`src/forge/cli/session_lifecycle.py:1709`) — confirmed: the deferred resolver runs FIRST at `1702` and short-circuits
  to native at `1703-1706`, never reaching the context-file branch, so it must become derivation-aware.
  - Assertion: for a same-dir fork manifest with `derivation.resume_mode=="transfer"` and no `claude_session_id`,
    `_get_deferred_same_dir_fork_resume_id` returns None; for `"native"` it still returns the parent UUID. CLI:
    `fork P --resume-mode transfer --no-launch` then `resume C` launches with a fresh `session_id` +
    `system_prompt_file`, NOT `resume_id`+`fork_session`.
- [x] Add tests: sidecar parity (`test_sidecar_samedir_transfer_forwards_prompt`); manager derivation
  (`tests/src/session/test_fork_into.py`); deferred resume regression
  (`tests/regression/test_bug_same_dir_transfer_fork.py` asserting `_get_deferred_same_dir_fork_resume_id` returns None
  for a transfer-derivation same-dir fork).
  - Assertion: all three pass.

## Phase 3: Integration coverage + design-doc sync + docs

- [x] Add an integration assertion in `tests/integration/cli/test_session_commands_integration.py` (mirroring the
  worktree-vs-same-dir launch test at `403-603`): a same-dir `--resume-mode transfer` fork launches with `--session-id`
  \+ `--append-system-prompt-file` and WITHOUT `--resume`/`--fork-session`; a plain same-dir fork still uses
  `--resume --fork-session`. Run via
  `./scripts/test-integration.sh tests/integration/cli/test_session_commands_integration.py -v` (touches session fork
  lifecycle).
  - Assertion: captured claude argv for same-dir transfer contains `--session-id` + `--append-system-prompt-file` and
    lacks `--fork-session`; plain same-dir fork argv contains `--resume` + `--fork-session`.
- [x] DESIGN-DOC SYNC — `docs/design.md:735` currently states "Same-directory forks use `resume_mode: native`,
  `strategy: null`, `depth: 1`..." which becomes FALSE for a same-dir transfer fork. Change to: same-dir forks default
  to `resume_mode: native`; an explicit `--resume-mode transfer` (or transfer flags that auto-switch) produces a
  same-directory transfer fork (`resume_mode: transfer`, `strategy` set, `context_file` set, fresh Claude session). Keep
  the §3.9 worktree/native-relocate rationale (`669-672`) intact.
  - Assertion: `rg "Same-directory forks use .resume_mode: native" docs/design.md` returns nothing; design.md documents
    the `--resume-mode transfer` opt-in + auto-switch and that it persists `resume_mode==transfer` + `strategy`.
- [x] DESIGN-DOC SYNC — `docs/design.md:728-729` derivation comment says `resume_mode` is "native" or "transfer" and
  `strategy` is "null when resume_mode=native"; confirm this stays accurate (same-dir transfer sets `strategy` non-null,
  consistent with the existing transfer rule). No change expected; verify.
  - Assertion: design.md derivation YAML comment does not assert same-dir => strategy null.
- [x] Update `docs/end-user/session.md:508-509` — replace "Same-directory forks use native `--resume --fork-session` and
  ignore these flags" with: same-dir is native by default; explicit `--strategy`/`--inline-plan` on a same-dir fork
  **auto-switch** it to transfer (with an info line), and `--resume-mode transfer` opts in explicitly. Update the
  resume-mode/transfer-options area accordingly. Update `docs/cli_reference.md:34` one-liner to note that
  `--resume-mode transfer` (and auto-switch on transfer flags) enables same-dir transfer.
  - Assertion: `rg "ignore these flags" docs/end-user/session.md` returns nothing; session.md documents the auto-switch
    \+ the explicit opt-in; cli_reference.md mentions same-dir transfer.

## Closeout

- [x] Run scoped unit + integration:
  `uv run pytest tests/src/cli/test_session_commands.py tests/src/session/test_fork_into.py tests/regression/test_bug_same_dir_transfer_fork.py -v`
  and `./scripts/test-integration.sh tests/integration/cli/test_session_commands_integration.py -v`. `make pre-commit`
  clean.
- [x] Add a newest-first `docs/board/change_log.md` entry (Goal / Key changes / Verification) for decoupling transfer
  mode from worktree isolation in fork.
- [x] Promoted durable invariants to `docs/board/impl_notes.md` (new section "Same-directory transfer forks: decouple
  transfer mode from worktree isolation", 2026-06-15): (1) fork derivation is written twice; (2)
  `_get_deferred_same_dir_fork_resume_id` must be `derivation.resume_mode`-aware or it re-natives deferred same-dir
  transfer forks; (3) fork vs resume `--resume-mode` value sets differ; (4) auto-switch is encoded by resolving
  `resume_mode = "transfer"` pre-fork. **Verification:** all 4 invariants adversarially re-checked against the shipped
  code (4-agent workflow) before promotion. I2/I4 confirmed as written; two refinements folded into the promoted text:
  (I1) the CLI `_persist_fork_transfer_derivation` step is a best-effort, transfer-gated *refinement* writing the only
  real fork `strategy` (the manager baseline is `strategy=None`), not a blind override of a prior real value; (I3)
  resume's `--resume-mode` is `default=None` + a `_validate_resume_mode` callback accepting `{native, transfer}`, NOT a
  `click.Choice` (only fork's is a Choice).
- [x] Move `docs/board/doing/same_dir_transfer_forks/` to `docs/board/done/` (#28 merged to `main`; relocated via
  `git mv` in the closeout commit).

### Deferred / debt (from pre-PR adversarial review, 2026-06-15 — both non-blocking)

- **`docs/end-user/transfer.md` (card §5):** not updated. Verified it contains **no now-false claim** — it documents the
  `forge transfer` command family and the transfer concept CWD-agnostically and links to `session.md` (which IS updated)
  for how fork produces transfer. The card §5 aspiration ("`ai-curated` is a transfer strategy, not a native-resume
  strategy") is already covered by transfer.md §"What transfer is" + §"Strategies". Optional additive cross-reference
  only; no correctness gap.
- **Optional hardening tests:** (1) incognito + same-dir-transfer transcript-deletion cleanup keying (behavior verified
  correct — cleanup keys on the distinct child UUID filename). The headline "failed-pre-seed → silent native resume"
  guard now has BOTH a mutation-sensitive unit test and an end-to-end resume test that clears
  `confirmed.claude_session_id` (`test_cleared_uuid_transfer_fork_resumes_fresh_not_native`), so that gap is closed.

### Pre-PR UX fix (2026-06-15)

- Auto-switch notice changed from `print_tip` ("Tip:") to an unprefixed `[dim]` status line — per CLAUDE.md UX
  guidelines `Tip:` is reserved for recovery suggestions; an action Forge took is informational. Tip-location
  enforcement test (`test_output.py`) and the auto-switch assertion (substring "switched to transfer mode") both pass.

### Closeout audit outcome (2026-06-15 — 16-agent workflow)

Swept all 9 `proposed/` cards, the 6 `docs/end-user/` docs that mention fork/transfer, and the QA checklist, verifying
each claim against the diff/code:

- **Proposed cards: no change.** All 9 are unrelated subsystems; none had a subset delivered or made stale.
  `supervisor_launch_controls` verified — the split held (the diff touches no supervisor cascade/checker/effort code).
- **`docs/end-user/`: no change.** The only stale claim lived in `session.md` (already fixed in this PR); a grep
  confirmed no sibling doc repeats it. `transfer.md`/`README.md`/`model-selection.md`/`memory.md`/`config.md` clean.
- **QA checklist: one real gap closed.** Section 5 exercised `--strategy`/`--inline-plan` only on `--worktree` forks.
  Added auto case **5.22** (same-dir explicit `--resume-mode transfer`, the `--strategy` auto-switch, and the native
  default control), grounded in the shipped integration test; index metadata bumped (test-count 541→548, last-updated
  2026-06-15).

## Acceptance Test Table

| Test                                                      | Fixture                                                                                                                                                                                | Assertion                                                                                                                                                                      | Test File                                                    |
| --------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------ |
| Explicit flags auto-switch same-dir to transfer           | mocked `SessionManager`; ParameterSource for strategy == COMMANDLINE; same-dir, no `--resume-mode`                                                                                     | `resume_mode` resolves to "transfer", info line printed, `invoke_claude` gets a fresh `session_id` (not `--resume --fork-session`)                                             | `tests/src/cli/test_session_commands.py`                     |
| Same-dir transfer generates context + fresh child         | mocked `SessionManager.fork_session` returns same-dir fork (`worktree.is_worktree=False`); parent has `confirmed.claude_session_id`; `invoke_claude` patched; `--resume-mode transfer` | `invoke_claude` called with `session_id`==fresh uuid (!= parent), `resume_id` None, `fork_session` not True, `system_prompt_file` points at a file containing the transfer doc | `tests/src/cli/test_session_commands.py`                     |
| Same-dir native default preserved                         | same-dir fork manifest; `invoke_claude` patched; no flags                                                                                                                              | `invoke_claude` called with `resume_id==parent_session_id`, `fork_session` True, addendum-only `system_prompt_file`; manager derivation stays `resume_mode=="native"`          | `tests/src/cli/test_session_commands.py`                     |
| inline-plan works same-dir (embeds approved plan TEXT)    | parent with `kind=='approved'` ExitPlanMode snapshot in `confirmed.artifacts['plans']`; `--resume-mode transfer --inline-plan`                                                         | combined same-dir child context file text contains the approved plan content, not just a path ref                                                                              | `tests/src/cli/test_session_commands.py`                     |
| Manifest records resume_mode==transfer + strategy         | real `SessionStore` in temp_env; same-dir `--resume-mode transfer --strategy full`; `invoke_claude` patched                                                                            | reloaded `confirmed.derivation.resume_mode=="transfer"`, `.strategy=="full"`, `.context_file` non-null                                                                         | `tests/src/cli/test_session_commands.py`                     |
| Manager honors same-dir transfer derivation               | `fork_session(parent, create_worktree=False, resume_mode="transfer")`                                                                                                                  | child `confirmed.derivation.resume_mode=="transfer"`, `context_file==child_path_rel`; `resume_mode=None` => `"native"`                                                         | `tests/src/session/test_fork_into.py`                        |
| Sidecar parity (composed prompt forwarded)                | fork manifest with sidecar launch preference; `_launch_claude_for_session` spied; `--resume-mode transfer`                                                                             | called with `session_id==_fork_uuid`, `resume_id` None, `fork_session` False, `register_fork` True, non-None `system_prompt_file`                                              | `tests/src/cli/test_session_commands.py`                     |
| Deferred same-dir transfer fork resumes fresh, not native | same-dir fork manifest with `derivation.resume_mode=="transfer"`, no `claude_session_id`, persisted `context_file`                                                                     | `_get_deferred_same_dir_fork_resume_id` returns None; resume launches `session_id` (fresh) + `system_prompt_file`, not `resume_id`+`fork_session`                              | `tests/regression/test_bug_same_dir_transfer_fork.py`        |
| Same-dir transfer over-budget guard (full strategy)       | same-dir `--resume-mode transfer --strategy full` with over-limit parent transcript, no `--force`                                                                                      | exit 1 with "exceeds context limit"; `fork_session` not left orphaned                                                                                                          | `tests/src/cli/test_session_commands.py`                     |
| native-relocate stays worktree-only                       | same-dir `--resume-mode native-relocate`                                                                                                                                               | prints "only applies to --worktree/--into" tip; launches native; same-dir transfer path not taken                                                                              | `tests/src/cli/test_session_commands.py`                     |
| Integration: launch argv shape                            | Docker workspace with started parent session                                                                                                                                           | same-dir `--resume-mode transfer` argv has `--session-id` + `--append-system-prompt-file`, lacks `--fork-session`; plain same-dir argv has `--resume` + `--fork-session`       | `tests/integration/cli/test_session_commands_integration.py` |
