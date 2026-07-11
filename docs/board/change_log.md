# Change Log

Completed-work record for Forge implementation sessions.

## Maintenance

- Updated by the memory writer with `strategy=changelog`, and by humans when closing a phase.
- Add compact entries for completed work only. Pending tasks belong in card checklists.
- Follow `docs/developer/board_contract.md` "Change Log Policy": each entry needs Goal, Key changes, and Verification.
- Keep entries short. Do not list every file unless the file list is the point of the work.
- Use newest-first order so active work stays near the top.
- When this file approaches the documentation size limits, compact the oldest entries at the bottom into a dated summary
  that preserves decisions, verification, and deferred items. Archive detailed old entries only if the summary is still
  too large.
- Check size before long sessions or when the file feels slow to scan:

```bash
wc -l docs/board/change_log.md
./scripts/count-tokens.py docs/board/change_log.md
```

## Entries

> Format: `## YYYY-MM-DD`, then `### Phase X.Y: Short Title`, with `**Goal**:`, `**Key changes**:` as bullets, and
> `**Verification**:`. Use newest-first order. See `docs/developer/board_contract.md` "Change Log Policy" for the full
> spec.

## 2026-07-10

### forge_hook_migration_cleanup implementation

**Goal**: Give pre-user-scope installations an explicit, reviewable migration to one dispatcher-backed runtime source
without silently mutating or activating other tracked checkouts.

**Key changes**:

- Added tracked-root candidate reporting plus `forge extension cleanup-project` preview/`--yes`; user enable/sync never
  reads the registry or another root, while explicit cleanup validates one selected root, removes legacy state first,
  installs user runtime hooks, scans for duplicates, and enrolls that root last with `backfill` provenance.
- Restricted automatic Claude cleanup to canonical tracked entries or a frozen additive released-shape inventory,
  reconciled `.forge-added`/installation ownership, migrated balanced project Codex blocks with backups and re-trust
  guidance, and retained ambiguous/manual state as an operation-scoped blocker.
- Added independent doctor/status-line cleanup state (`HOOK!`) without broadening genuine `HOOKx2`, and synchronized
  architecture, CLI, Day-1/recovery, QA, and isolated walkthrough guidance.

**Verification**: focused migration suite (`320 passed`); CLI command/output/vocabulary guards (`68 passed`);
`make test-unit` (`7556 passed, 1 skipped, 116 deselected`); installer Docker suite (`16 passed`) plus final targeted
migration-and-disable rerun; real-Claude migration (`1 passed, 2 deselected`) with user-dispatcher SessionStart/Stop
effects; isolated walkthrough migration exercise; `make pre-commit`.

### forge_hook_sidecar_resolution closeout

**Goal**: Close T10 after PR #94 restored Forge runtime hooks inside Claude sidecars.

**Key changes**:

- Shipped fresh canonical hook staging in the persisted sidecar user scope, idempotent entrypoint auth merging, and an
  image PATH that resolves bare hook and project status-line commands without mutating project `.claude` settings.
- Persisted deferred work through a host-drainable queue with host-path normalization and container-side drain
  suppression; retained the stale-image skew guard and PATH breadth as explicit follow-ups.
- Moved `forge_hook_sidecar_resolution` from `doing/` to `done/`, repointed its epic links, and advanced the epic cursor
  to T6 with T8 parked.

**Verification**: `make test-unit` (`7517 passed, 1 skipped, 116 deselected`);
`./scripts/test-integration.sh tests/integration/sidecar/test_sidecar_hook_inject.py -v` (`3 passed`);
`make pre-commit`; PR #94 GitHub checks (test, pre-commit, CodeQL analyses); `make pre-commit-md`; post-merge board
link/stale-reference scan.

## 2026-07-08

### user_scope_hook_ownership closeout

**Goal**: Close T5 after PR #93 merged and hand the epic cursor to the remaining runtime-hook migration work.

**Key changes**:

- Moved `user_scope_hook_ownership` from `doing/` to `done/` with its checklist preserved as the execution record.
- Repointed the member back-link, epic forward-links, and the matcher-consolidation inbound link to the done card.
- Updated the epic focus to show T5 shipped and hand the next cursor to **T10** sidecar resolution and **T6** migration
  cleanup, with **T8** still parked.

**Verification**: `./scripts/test-integration.sh tests/integration/docker/test_installer.py` (`15 passed`);
`make pre-commit-md`; `git diff --check`.

### user_scope_hook_ownership implementation

**Goal**: Flip runtime hook ownership to user scope while preserving cleanup paths for legacy project/local installs.

**Key changes**:

- Scoped the extension module policy so user installs own `hooks`/`codex-hooks` and omit `status-line`, while
  project/local installs keep project settings such as `statusLine` and reject explicit runtime-hook module requests.
- Registered Claude and Codex runtime hooks through the T4 dispatcher command bytes, extended detection to accept both
  `forge-hook <handler>` and legacy `forge hook <handler>`, and added double-fire diagnostics.
- Tightened diagnostics so `~/.claude` is not misreported as a project install even when doctor runs from `$HOME`,
  same-file old+new hook siblings still report double-fire risk, distinct `PreToolUse` matchers do not, and Codex legacy
  hook registrations dedupe by logical `(event, handler)` identity.
- Preserved filtered-update cleanup tracking for pre-T5 project/local hook entries, while user-scope sync removes the
  old command bytes before adding dispatcher entries. Dispatcher rendering now happens before hook settings are written.
- Updated Day-1 CLI guidance, end-user docs, QA/walkthrough checks, and the interim sidecar warning path.

**Verification**: `make test-unit` (`7511 passed, 1 skipped, 116 deselected`); targeted hook/Codex/installer regression
suites including `tests/regression/test_bug_codex_dedupe_wrong_event.py`; `make pre-commit`;
`./scripts/test-integration.sh tests/integration/docker/test_installer.py::TestCodexHooksModule::test_enable_registers_block_and_disable_removes_it`
(`1 passed`).

### forge_hook_dispatcher closeout

**Goal**: Close T4 after its PR merged and hand the epic cursor back to the remaining user-scope hook migration work.

**Key changes**:

- Moved `forge_hook_dispatcher` from `doing/` to `done/` with its checklist preserved as the execution record.
- Repointed the member back-link and epic forward-links to the done card, and updated the epic focus to show no active
  member in `doing/`.
- Reframed the remaining detection risk as T5-owned now that T4 chose the hyphenated `forge-hook` shim.

**Verification**: stale-reference scan for `doing/forge_hook_dispatcher` and pre-merge T4 status language;
`git diff --check -- docs/board`; `make pre-commit-md`.

### forge_hook_dispatcher implementation and review hardening

**Goal**: Ship the T4 user-scope hook dispatcher mechanism without flipping hook registration to user scope.

**Key changes**:

- Added the generated stdlib `~/.forge/bin/forge-hook` artifact, `~/.forge/runtime.json` launcher metadata,
  known-location resolver fallback, runtime-agnostic `exec` forwarding, sync re-rendering, and doctor drift reporting.
- Chose the shim shape from the populated-registry benchmark: p95 22.13 ms for the shim versus p95 611.78 ms for the
  full Forge gate representative.
- Hardened review findings: gate exceptions fail open, registry unknown top-level fields now match package fail-open
  behavior, resolver bin-dir precedence is single-sourced, the in-suite perf assertion no longer has a tight wall-clock
  bound, and dispatcher render failures are wrapped as install errors.
- Synced the epic/member docs and promoted durable dispatcher invariants to `impl_notes.md`; T5 still owns user-scope
  registration bytes and hook-detection updates.

**Verification**: `uv run pytest tests/src/install/test_hook_dispatcher.py -q` (`25 passed`);
`uv run pytest tests/src/install/test_hook_dispatcher.py tests/src/install/test_doctor.py -q` (`39 passed`);
`uv run pytest tests/src/install/test_hook_dispatcher.py tests/src/install/test_doctor.py tests/src/cli/test_extension_enable.py tests/src/cli/test_env_vocabulary.py -q`
(`100 passed`); `uv run pytest tests/src/install -q` (`364 passed, 1 skipped`); `make pre-commit`;
`./scripts/test-integration.sh tests/integration/docker/test_installer.py` (`15 passed`).

## 2026-07-07

### env_var_interface_boundary closeout

**Goal**: Close the shipped env-var vocabulary boundary after PR #91 landed on `main`.

**Key changes**:

- Closed PR #91 (`c593eb66`) on `main`: card/checklist are in `done/`, durable notes are promoted, and the epic
  coordinator points at the done card.
- Added the `FORGE_*` vocabulary table in `design_appendix.md` with a `design.md` pointer: public (`FORGE_HOME`,
  `FORGE_PROFILE`), public-diagnostic (`FORGE_DEBUG`, `FORGE_STATUS_TRUNCATE`), internal wiring, and Test/QA harness
  classes.
- Rewrote normal-flow CLI errors/help/docstrings and user docs to say "current session", "Forge-managed session", and
  `--session <name>` instead of teaching users to set internal session env vars.
- Added paired diagnostic markers for troubleshooting sections that legitimately name hook/session env wiring; no
  whole-file docs exemption.
- Added `tests/src/cli/test_env_vocabulary.py`, a two-layer guard over CLI/op user-visible sinks and user-facing docs,
  with live product-env inventory coverage, boundary-matched names, and parity against the appendix table.

**Verification**: `rg "Set FORGE_SESSION|set \\$FORGE_SESSION" src/ docs/end-user docs/cli_reference.md` clean;
`uv run pytest tests/src/cli/test_env_vocabulary.py tests/src/cli/test_memory.py tests/src/cli/test_session_memory.py tests/src/cli/test_session_lane.py tests/src/cli/test_output.py tests/src/core/ops/test_session_context.py -q`
(`169 passed`); `make pre-commit` clean. Integration not run because the change is docs, strings, and a source-scan test
only with no runtime behavior change. Post-merge closeout re-checked `main` at `c593eb66`, the done-lane card/checklist,
the epic inbound link, and `make pre-commit-md`.

### forge_project_registry / forge_project_compat closeout

**Goal**: Close the merged project-registry work and the first project-compat guardrail slice after PR #90 landed on
`main`.

**Key changes**:

- Moved T3 `forge_project_registry` to `done/`: `~/.forge/projects.json` is now the machine-written trusted-root
  registry, with locked read-modify-write enrollment, strict CLI reads, fail-open hook reads, doctor surfacing, and
  managed-worktree auto-enrollment.
- Moved T7 `forge_project_compat` to `done/` for the shipped first slice: `.forge/project.toml` is an opt-in,
  hand-edited compatibility pin; extension/session command paths enforce it, and doctor reports malformed or
  incompatible state.
- Split T7's uncovered mutation families into accepted follow-up `todo/forge_project_compat_mutator_sweep/`:
  confirmed-state hook writes, memory-writer doc writes, and proxy/backend registry mutations.
- Promoted durable registry/compat invariants to `impl_notes.md`; epic links now point at the done cards.

**Verification**: PR #90 verification included the targeted install/doctor/extension/guard/session/hook suite
(`355 passed, 1 skipped`), focused follow-up suite (`38 passed, 1 skipped`), named Docker integration checks
(`3 passed, 33 deselected`), `make pre-commit`, and `uv run --frozen pyright`. Closeout docs verified with
`make pre-commit-md`.

## 2026-07-06

### global_forge_install closeout

**Goal**: Close the shipped T1 member after PR #89 merged to `main`.

**Key changes**:

- Moved the card `doing/ -> done/`; repointed the 5 cross-lane links (T1 \<-> epic).
- Promoted the install-kind detection invariants to `impl_notes.md` (editable-first, launcher-symlink-not-realpath,
  `on_path_minimal` as a reported fact, kind-vs-path seam).
- Updated the epic coordinator: T1 shipped, no active member, D2 timing decision now actionable (awaiting the epic
  owner); epic stays in `doing/` with 8 members remaining.

**Verification**: `make pre-commit` clean.

### global_forge_install (epic T1): Global-tool Day-1 install + `forge extension doctor`

**Goal**: Make global-tool install the documented Day-1 path and add a read-only `forge extension doctor` reporting how
Forge is installed and whether it is globally reachable -- the epic's first, dependency-free member.

**Key changes**:

- New `src/forge/install/doctor.py` (`diagnose_install`, injectable seams): classifies the install as
  `global`/`editable`/`venv`/`unknown` (global honors `~/.local/bin`, `UV_TOOL_BIN_DIR`, `XDG_BIN_HOME`,
  `PIPX_BIN_DIR`), resolves the `forge` launcher path, and reports PATH reachability. Adds a GUI/launchd minimal-PATH
  probe (`on_path_minimal`) -- the mechanical signal for epic D2 (a healthy global install still reads `false`, since
  `~/.local/bin` is off launchd's PATH; advice is keyed on `on_path`/kind, not the probe). Advice is state-aware: an
  installed-but-off-PATH global install is told to fix PATH (`uv tool update-shell` / `pipx ensurepath`), not to
  reinstall.
- New `forge extension doctor` leaf (thin CLI over `doctor.py`; `--json` for scripting, `print_tip` advice).
- Day-1 docs: README Quick Start leads with `uv tool install` / `pipx install` (dev sub-note -> `uv sync`); uninstall ->
  tool form; end-user README gains an "Install Forge (once)" prerequisite (the workflow previously assumed `forge` was
  already on PATH).
- Design sync: cli_reference Installation table, design.md §5.1 (two install layers), design_appendix §C (tool
  distribution, kinds, probe semantics, `--json` shape).

**Verification**: `tests/src/install/test_doctor.py` (14 new tests) covers all kinds + both probe outcomes +
off-PATH-global advice + CLI JSON shape; `tests/src/{install,cli} -m "not integration"` -> 2586 passed;
`make pre-commit` clean; live `forge extension doctor` on the editable dev install reported `editable` + real path +
`on_path_minimal=false`. Installer Docker integration skipped with rationale (read-only diagnostic, no write-path
change).

### forge_hook_legacy_writer: Remove the standalone hook writer

**Goal**: End the second, untracked Claude hook mutation path before `epic_global_forge_runtime` changes hook command
bytes and ownership.

**Key changes**:

- Deleted the standalone `forge hook enable` / `forge hook disable` writer and its duplicate `FORGE_HOOK_CONFIG`
  registry; hook registration now goes through the tracked extension installer.
- Module-gated settings merges so the public replacement
  `forge extension enable --scope local --profile minimal --with hooks --without commands` writes tracked hooks only,
  without commands, agents, skills, permissions, or env.
- Migrated docs, QA checklists, Docker integration setup, and removed-command assertions to the tracked replacement.
  Clean break: the old `--user` local-file target (`~/.claude/settings.local.json`) was dropped; tracked user scope uses
  `~/.claude/settings.json`.

**Verification**:
`uv run pytest tests/src/install/test_settings_merge.py::TestMerge tests/src/install/test_installer.py::TestInstallerInit tests/src/cli/test_extension_enable.py::TestEnableWithPath tests/src/cli/test_command_tree_invariants.py::test_removed_aliases_are_clean_breaks tests/src/cli/test_hooks.py tests/src/install/test_hooks.py tests/src/install/test_registered_commands_contract.py tests/src/cli/test_read_hygiene.py::TestReadHygieneRegistration tests/src/policy/team/test_handlers.py::TestHookInstallConfig tests/src/install/test_version.py tests/regression/test_bug_stale_preset_hooks.py -q`;
`make test-unit`; `./scripts/test-integration.sh tests/integration/docker/test_installer.py`;
`./scripts/test-integration.sh tests/integration/docker/test_real_claude_hooks.py::TestRealClaudeHooks::test_session_start_hook_sets_session_id`;
grep sweep for removed command/import symbols; `make pre-commit`.

### forge_hook_matcher_consolidation: Shared hook predicate and byte contract

**Goal**: De-risk `epic_global_forge_runtime` Seam 1 by single-sourcing Forge hook-command detection and pinning the
registered command bytes before the epic changes them.

**Key changes**:

- Added `install/hooks.py::is_forge_hook_command` / `entry_is_forge_hook` with invocation-token semantics: command
  basename `forge`, second token `hook`, optional handler token; contains-only strings like `echo forge hook stop` no
  longer satisfy presence checks or destructive disable removal.
- Repointed both existing matcher sites through the shared predicate; `forge hook disable` keeps its `type == "command"`
  guard while dropping the bespoke prefix body.
- Added a contract golden for the 16 rendered Claude hook entries as `(event, matcher, command, timeout)` tuples, plus
  statusLine, Codex hook registrations, and a `merge_hooks -> unmerge` sibling-preservation round-trip.
- Promoted the durable matcher/golden invariant to `docs/board/impl_notes.md`; no design or end-user doc change was
  needed because matcher internals are not documented.

**Verification**:
`uv run pytest tests/src/install/test_hooks.py tests/src/install/test_registered_commands_contract.py tests/src/cli/test_hooks.py tests/regression/test_bug_hook_registry_drift.py -q`;
`make test-unit`; `./scripts/test-integration.sh tests/integration/cli/test_hooks_integration.py`; scoped
`uv run pre-commit run --files ...` over this card's changed files.

### proxy_tier_resolvers closeout

**Goal**: Close the shipped proxy tier/model-resolution card after PR #86 merged to `main`.

**Key changes**:

- Promoted the durable resolver invariants to `docs/board/impl_notes.md`.
- Marked the final checklist closeout items and moved the card from `doing/` to `done/`.

**Verification**: `make pre-commit-md`.

### proxy_tier_resolvers B2: Shared proxy resolution and port probe

**Goal**: Collapse the duplicated proxy model-resolution and port-probing paths without changing routing, cost, or
startup contracts.

**Key changes**:

- Added characterization coverage for `/v1/messages` and `/v1/messages/count_tokens` before refactoring, including
  explicit-backend, OpenRouter slash-passthrough, tier-alternative, and ambiguous-default cases.
- Repointed message creation and token counting through one server resolver for
  tier/default/alternative/explicit-backend decisions, with cost logging still receiving the same resolved model and
  tier.
- Added `LITELLM_PROVIDER_PREFIXES` for LiteLLM detector sites while intentionally leaving `data_models._normalize` on
  its narrower canonical-prefix contract; the code comment now marks that as a deliberate non-unification.
- Added `forge.proxy.ports` as the shared loopback probe and kept caller-specific exception contracts for the server CLI
  and proxy orchestrator.
- Added real proxy `/v1/messages/count_tokens` integration smoke coverage for default-tier and explicit-tier requests;
  resolved-model parity stays unit-pinned because that endpoint emits no resolved-model/tier headers.

**Verification**:
`uv run pytest tests/src/proxy/test_server_model_resolution.py tests/src/proxy/test_model_alternatives.py tests/src/proxy/test_routing_invariants.py tests/src/proxy/test_data_models.py tests/src/proxy/test_ports.py tests/src/proxy/test_proxy_orchestrator.py tests/src/proxy/test_server_cost.py -q`;
`./scripts/test-integration.sh tests/integration/proxy/test_proxy_local_litellm_e2e.py tests/integration/proxy/test_session_routing_e2e.py`;
`./scripts/test-integration.sh tests/integration/proxy/test_multi_proxy_workflow_e2e.py`;
`./scripts/test-integration.sh tests/integration/cli/test_status_line_integration.py`; `make pre-commit`.

### proxy_tier_resolvers B1: Tier-word resolver leaf

**Goal**: Single-source proxy/statusline tier-word detection while preserving the deliberate display-name fallback
divergence.

**Key changes**:

- Added `forge.core.tiers.detect_tier_word` for raw model-name tier detection, including the `fable -> opus` rule and
  the existing naive substring behavior.
- Repointed the three 1:1 mirror sites: proxy request validation, passthrough/server tier detection, and statusline
  explicit-model tier detection.
- Preserved `get_tier_from_display_name` unchanged: display names still check opus/fable first and default to `sonnet`
  when no tier word is visible.
- Updated the active card checklist and design directory map for the new neutral leaf.

**Verification**:
`uv run pytest tests/src/core/test_tiers.py tests/src/proxy/test_data_models.py tests/src/cli/statusline/test_statusline_forge_segments.py -q`;
`./scripts/test-integration.sh tests/integration/cli/test_status_line_integration.py`; touched-file `uv run ruff check`;
`make pre-commit`.

### test_mirror_and_contract_cleanup implementation: Test mirror and shared contract cleanup

**Goal**: Restore test mirrors and collapse duplicated support seams.

**Key changes**:

- Fixed a status_line miscount (the one behavior change): `human`/`ai` transcript role aliases now normalize through the
  shared `resolve_entry_role` primitive; regression-guarded by `test_bug_statusline_transcript_role_alias.py`.
- Moved statusline, Claude session, and direct-model tests into mirrored packages.
- Deleted the sidecar secrets shim; folded remaining coverage into core auth.
- Shared Codex result/proxy setup, transcript parsing, git-root walking, workflow tips, and direct-model pins.

**Verification**: Focused slice sweep (1045 passed); affected formatter rerun (288 passed); touched-file
`uv run ruff check`; `make pre-commit`.

### ops_policy_seam implementation: Policy command-core seam

**Goal**: Move shared policy-supervisor mutations behind a UI-agnostic op layer and close the drifted proxy-id recovery
posture.

**Key changes**:

- Added `core/ops/policy.py` for supervisor set/off/on/remove/reload/cascade and repointed both terminal CLI and
  `%policy supervisor` to it while preserving CLI output and hook JSON contracts.
- Collapsed session routing override/effective-proxy helpers into `core/ops/claude_session.py` with CLI compatibility
  aliases.
- Added logged best-effort proxy base-url recovery wrappers in `proxy/proxies.py`; kept `find_by_base_url()` fail-loud.
- Aligned `%policy supervisor reload <absolute-path>` with CLI reload path semantics: absolute paths are stored as
  provided, while relative paths still resolve from cwd.
- Matched `list_sessions_older_than(ctx, scope)` to its sibling contract and added public
  `ActiveSessionStore.is_live()`.

**Verification**: Focused suites covering policy ops/supervisor, `%direct`, session/gc contracts, proxy recovery,
session-start hook, and policy-shadow coupling (392 passed, 48 passed, 90 passed); integration
`./scripts/test-integration.sh tests/integration/cli/test_hooks_integration.py -k TestSessionStartHook` (7 passed, 9
deselected); touched-file `uv run ruff check`; `make pre-commit`.

### diverged_twin_consolidation implementation: Session and hook twin consolidation

**Goal**: Collapse must-stay-identical twins in session inheritance, runtime/lane helpers, supervisor options, TDD sort,
and hook capture paths while fixing the two verified drift bugs.

**Key changes**:

- Added one session intent inheritance helper and routed native-resume transcript artifact lookup through the guarded
  helper, closing the malformed `copied_path` type leak.
- Moved `session_runtime` to `session.models`, promoted `record_to_lane`, and shared the TDD tests-first sort key from
  `policy.deterministic.base`.
- Shared the start/fork supervisor option family and dependency error text while keeping their distinct `--supervise`
  command shapes.
- Extracted the Stop/StopFailure transcript capture core and the teammate/task team-supervisor hook body without folding
  their intentionally different failure channels.
- Verified-and-dropped 3c and 4b: codex preflight arms diverge immediately after the already-shared read, and
  template-only context routing is not reachable through the production inline CLI resolver paths.

**Verification**: Focused slice suite
`uv run pytest tests/regression/test_bug_transcript_artifact_type_guard.py tests/regression/test_bug_consumer_lane_fork_resume_inherit.py tests/regression/test_bug_policy_check_nested_tdd_sort.py tests/regression/test_bug_codex_tdd_nested_layout.py tests/src/cli/test_user_prompt_dispatcher.py::TestGuardCheck tests/src/session/test_consumer_lanes.py tests/src/session/test_shadow_curation.py tests/src/session/test_memory_writer.py tests/src/core/ops/test_codex_session.py tests/src/cli/test_session_codex.py tests/src/cli/test_session_list_show.py tests/src/cli/test_session_start_delete.py tests/src/cli/test_session_fork.py tests/regression/test_characterize_context_limit_routing_ref_template_only.py tests/src/cli/test_artifact_hooks.py tests/src/cli/hooks/test_team_hook_lane_freeze.py tests/src/cli/test_stop_verification.py tests/regression/test_bug_walkthrough_stale_stop_snapshot.py tests/regression/test_bug_supervisor_fork_uuid_drift.py`
(510 passed); hook integration
`./scripts/test-integration.sh tests/integration/cli/test_artifact_hooks_integration.py tests/integration/cli/test_stop_verification_integration.py tests/integration/docker/test_policy_hooks.py`
(42 passed); `make test-unit` (7,379 passed, 116 deselected); touched-file `uv run ruff check`.

## 2026-07-05

### state_primitive_hoist implementation: Core durable-state primitive hoist

**Goal**: Hoist durable-state and JSONL primitives to core leaves without merging telemetry planes or changing store
schemas.

**Key changes**:

- Moved `prune_jsonl_shards` to `core/state/retention.py`, repointed live callers, and deleted the dead
  `prune_usage_events` export.
- Added `atomic_write_bytes`, layered `atomic_write_text` on it, and repointed four text writers plus binary transcript
  relocation through the shared durable writer.
- Added shared telemetry JSONL append mechanics in `core/telemetry/jsonl_io.py`.
- Added a versioned JSON read helper and converged search read `OSError` handling to domain-specific
  `StateUnreadableError` subclasses.
- Review follow-up removed the unused `proxy/retention.py` shim and installer `now_iso` re-export, kept `version: null`
  diagnostics aligned with pre-hoist readers, and made search `--scope all` skip unreadable project indexes while
  `search status` reports corrupt indexes with rebuild guidance.

**Verification**: Focused card suite
`uv run pytest tests/src/core/state/test_timestamps.py tests/src/core/state/test_io.py tests/src/core/state/test_retention.py tests/src/core/telemetry/test_jsonl_io.py tests/regression/test_bug_state_atomic_write_fsync.py tests/regression/test_bug_search_store_oserror_unreadable.py tests/src/backend/test_registry.py tests/src/proxy/test_proxies.py tests/src/session/test_index.py tests/src/install/test_tracking.py tests/src/search/test_store.py tests/src/search/test_content_store.py tests/src/search/test_bm25_store.py tests/src/search/test_index_state.py tests/src/cli/test_search.py`;
review follow-up suite
`uv run pytest tests/src/core/state/test_versioned_store.py tests/src/cli/test_search.py tests/src/install/test_models.py tests/src/install/test_tracking.py tests/src/backend/test_registry.py tests/src/proxy/test_proxies.py tests/src/session/test_index.py tests/src/search/test_store.py tests/src/search/test_content_store.py tests/src/search/test_bm25_store.py tests/src/search/test_index_state.py tests/regression/test_bug_search_store_oserror_unreadable.py`;
`make test-unit`; targeted integration
`./scripts/test-integration.sh tests/integration/cli/test_search_workflow_integration.py tests/integration/cli/test_proxy_commands_integration.py::TestProxySet tests/integration/backend/test_backend_cli.py::TestBackendRegistry`;
`make pre-commit`.

### test-session-command-fixture-and-split closeout: Session CLI test split

**Goal**: Close the session CLI test refactor after PR #77 split the 4,933-line catch-all file without changing command
behavior.

**Key changes**:

- Moved `test-session-command-fixture-and-split` from `doing/` to `done/` and marked the card/checklist closeout items
  complete.
- Confirmed PR #77 (`08e4a787`) deleted `tests/src/cli/test_session_commands.py`, added command-family files for
  list/show, start/delete, fork, resume, and overrides, and introduced the narrow `successful_claude_launch` helper in
  `tests/src/cli/session_command_support.py`.
- No durable `impl_notes.md` promotion was needed; the shipped behavior is test organization only.

**Verification**: PR #77 recorded `uv run pytest tests/src/cli/test_session_*.py -q`, `make pre-commit-md`,
`git diff --check`, and `make pre-commit`; closeout re-verified the merged file layout on `main` and ran
`make pre-commit-md` plus `git diff --check`.

### rewind_resume_strategy follow-up: Real-Claude clean-prefix gate

**Goal**: Close the disclosed rewind gap by proving a fresh-UUID truncated prefix is resumable by real Claude Code, not
only unit-covered.

**Key changes**:

- Added `tests/integration/docker/test_rewind_native_contract.py`, a slow Docker real-Claude gate that creates a parent
  conversation, writes a rewind-owned fresh `<R>.jsonl` prefix with `write_rewind_transcript_prefix`, resumes it with
  `claude --resume <R> --fork-session` from another CWD, and asserts the prefix is not mutated.
- Extended the shared real-Claude Docker helper with `rewind_prefix_and_resume`.
- Updated design and board memory to replace the old disclosed clean-prefix caveat with the new integration-test anchor.

**Verification**: `uv run pytest tests/src/session/test_rewind_strategy.py tests/src/cli/test_session_rewind_cli.py -q`;
`uv run ruff check tests/integration/docker/conftest.py tests/integration/docker/test_rewind_native_contract.py`;
`./scripts/test-integration.sh tests/integration/docker/test_rewind_native_contract.py -v`; `git diff --check`.

## 2026-07-04

### accidental_complexity_cleanup Phase C: finishing phase (Defect B, #17, Gap A, WorkflowPolicy demote, dedups)

**Goal**: Close the accidental-complexity cleanup -- fix the one real bug, drop the last dead code, and resolve the owed
decisions (WorkflowPolicy scope + two dedups).

**Key changes**:

- **Defect B (proxy provider-trace hole)**: the auth-retry success path (401 -> refresh -> 200) recorded cost/metrics
  but never wrote a provider-trace record. Routed all three proxy trace sites through one shared `_trace_ctx` dict
  spread (no-behavior refactor) and added the retry call, so a new provider path can't silently omit the run-tree
  context.
- **Gap A (supervisor exit code)**: `supervisor evaluate` keyed "passed" on warning-prose matching, so fail-open paths
  without an `_INFRA_FAILURE_PREFIXES` prefix reported exit 0 instead of 2. Now honors the structural
  `PolicyDecision.fail_open` flag (prose match kept as fallback).
- **#17**: deleted unused `CredentialManager.get_cache_status`/`clear_cache`.
- **WorkflowPolicy DEMOTE**: deleted the test-only `get_all_bundles()` (the only place `workflow` was advertised as a
  discoverable bundle); relabeled `policy.md` experimental/manifest-only. Pipeline + `build_divergence_config` kept;
  `proposed/graduate_workflow_policy_cli` filed for the real CLI UX.
- **Micro-cleanups**: (a) `design_appendix §B.1` marker schema `v2 -> v1` to match `MARKER_SCHEMA_VERSION = 1`; (b)
  single-sourced `Reporter`/`Confidence` in a new neutral leaf `core/telemetry/vocabulary.py`. The card's assumed
  "vocabulary owns" direction cycles via `usage/__init__ -> emit -> downstream`; the leaf sits below `downstream` and
  both planes re-export.

**Verification**: Regression `test_bug_auth_retry_provider_trace.py` (real helper + `read_provider_traces` round-trip,
capable + non-capable, fail-first proven). Focused suites green (proxy/telemetry/usage/policy/credentials); user ran the
full integration suite green. mypy/pyright/ruff clean. `server.py` held under the personal 2,500-line guardrail via the
trace DRY; a durable `server.py` module extraction is deferred (logged in the checklist).

### backend_instance_identity_model S1-S6: Backend Instance Identity Clean Break

**Goal**: Separate backend instances, managed processes, and telemetry origin fields.

**Key changes**:

- `proxy.backend` is canonical; old `proxy.source` clean-breaks. Recreate affected proxies with
  `forge proxy create ...`.
- Backend CLI JSON now uses `backend_instance_id` / `managed_process`. Backend registry `~/.forge/backends/index.json`
  is schema v2; for old records, stop local backends first (or free ports), delete the file, then restart.
- Downstream telemetry is schema v2: `backend_id` means backend instance id, `source_id`/`source_kind` stay origin
  fields, and missing/older schemas are skipped with activity/cost `skipped_legacy_schema` counts.

**Verification**: S1-S5 focused tests and `make test-unit` passed; S6 docs verified with `make pre-commit-md`.

## 2026-07-03

### cli_style_ux_compliance S5/C2: Backend Public Terminology

**Goal**: Make `forge model backend` use first-class CLI nouns without changing backend storage or JSON contracts.

**Key changes**:

- Reworded backend help, metavars, human tables, errors/tips, and public docs to backend/backend-instance/adapter
  language while keeping `source_id`, `runtime_instance`, `BackendInstance.backend_id`, and telemetry `backend_id`
  stable. Deeper domain migration is split to `backend_instance_identity_model`.

**Verification**: backend + command-tree tests passed (51); help/list smoke checked; `make pre-commit` clean.

### cli_style_ux_compliance S3/A3: policy enable Fail-Loud

**Goal**: Replace bare `forge policy enable`'s silent no-op (warning on stdout, exit 0) with a loud, actionable failure.

**Key changes**:

- Bare `policy enable` (no `--bundle`) now prints `Error:` + `Tip:` (naming `tdd`/`coding_standards`) on stderr and
  exits 1; stdout stays empty for scripts.
- OQ-1 resolved as a clean break: the CLI requires an explicit `--bundle`. Restore-from-intent stays the interactive
  `%policy enable` shortcut's job (a separate parser writing `overrides`, still planned); `design_workflows.md` updated
  to state the CLI/dispatcher split.

**Verification**: new `tests/src/cli/test_policy_enable.py` (fail-loud names both bundles) passes; happy-path
`enable --bundle tdd` and the `%` dispatcher/M7 regression suites unaffected; CLI tip/error guards pass;
`make pre-commit` clean.

### cli_style_ux_compliance S5/C1: Activity Period Clean Break

**Goal**: Align `forge telemetry activity` with sibling telemetry period selectors.

**Key changes**:

- Replaced `--days`/`--all` with `--period today|week|month|all` (default `today`), and updated tests, docs, QA, and
  integration references.

**Verification**: 23 focused tests, 9 invariants, 1 targeted integration test, and `make pre-commit` clean.

### cli_style_ux_compliance S4: Help And Lane Errors

**Goal**: Finish the Batch B CLI help/error-message pass and the planned `telemetry activity --json` tip shape.

**Key changes**:

- Normalized touched help wording/examples, added the activity JSON error tip, and made lane help/errors enumerate live
  valid lanes including defaults.

**Verification**: Focused help/error suite passed (171 tests); `make pre-commit` clean.

### cli_style_ux_compliance S2: Logs Group Redesign

**Goal**: Split `forge logs` into a scriptable read surface and a preview-default cleanup surface that follows the CLI
destructive-verb shape.

**Key changes**:

- Promoted `forge logs` to `show`/`clean`: `show --json`, preview-default `clean --yes`, shared dry-count filtering, and
  Click clean breaks for the old bare flags.
- Updated CLI docs and bundled QA/walkthrough guidance for the new spellings.

**Verification**: Focused logs/command-tree/stream tests passed (99 tests); `make pre-commit` clean.

### backend_runtime_cleanup Step 2: Runtime-Id Backend Stop

**Goal**: Make backend runtime cleanup operate on the live runtime objects users see in `forge model backend list`,
while keeping backend config management separate.

**Key changes**:

- Changed `forge model backend stop` to accept runtime instance ids, multiple targets, and `--all`/`--yes`; local source
  ids and bare adapters now fail with runtime-id guidance, while remote sources keep the no-local-lifecycle boundary.
- Removed the `stop/delete --port` runtime spelling. `delete <adapter>` is config-only, rejects registered runtime ids
  with a `stop <runtime-id>` tip, and still stops matching local runtime instances before removing the adapter config.
- Deleted the obsolete `delete --port` double-stop regression after replacing that behavior with a clean-break exit-2
  assertion.
- Folded in the backend slice of cli_style B1: group help defines source id/runtime instance id/adapter, examples use
  valid id spaces, reconcile help names `backend list` discovery, and source-row JSON dual keys are documented.

**Verification**: `uv run pytest tests/src/cli/test_backend_commands.py -q` (42 passed); `make test-regression` (482
passed); `make test-unit` (7302 passed, 117 deselected);
`uv run ruff check src/forge/cli/backend.py tests/src/cli/test_backend_commands.py`; help smoke for
`forge model backend --help`, `stop --help`, and `delete --help`; `make pre-commit` clean.

### cli_style A1: CLI Error Streams To Stderr

**Goal**: Keep CLI result streams parse-safe by routing top-level CLI errors and diagnostics to stderr.

**Key changes**:

- Flipped error-helper defaults and bare `handle_session_error` to `err_console`; `print_tip` stays stdout by default.
- Removed explicit stdout overrides, added `err=True` to JSON/red error echoes, and kept multi-statement error
  continuations on stderr.
- Saved AST guards for stdout overrides, adjacent stdout continuations, JSON errors, and red diagnostics; added
  in-branch `--json` error coverage with stdout-empty assertions.

**Verification**: `uv run pytest tests/src/cli -q` (2207 passed); `make pre-commit` clean.

## 2026-07-02

### session_op_layer_extraction Slice 5: Session shim retirement

**Goal**: Remove the `forge.cli.session` compatibility shim that kept tests patching parent-module re-exports after the
Claude session path was split into focused CLI/core modules.

**Key changes**:

- Repointed parent-module test patches to the real seams by sub-slice: low-volume helpers, resume-mode local imports,
  `SessionManager`, and the Claude launcher seam in `forge.core.ops.claude_session`.
- Deleted the `_sess()` / `_session_cli()` lazy module seams and replaced the `session.py` wildcard re-export tail with
  side-effect imports that preserve Click command registration.
- Repointed direct test imports for submodule-owned commands/helpers while leaving `session.py`-defined helper tests on
  the parent module.

**Verification**: CLI/regression suite 2681 passed; Docker lifecycle integration 21 passed; stale shim greps clean
except for helpers still defined in `session.py`; `make pre-commit` clean.

### session_op_layer_extraction Slice 4b: Fork supervisor wiring

**Goal**: Finish the post-fork cleanup by collapsing fork supervisor persistence onto the core wiring primitive and
settling the remaining sidecar testability question.

**Key changes**:

- Replaced `session_fork.py`'s hand-rolled `SupervisorConfig` / lane persistence block with `SupervisorWiring` +
  `_apply_supervisor_wiring`, preserving the existing `_preflight_routing` guards and CLI-owned validation.
- Moved sidecar `is_sandboxed=True` confirmation to after mount/secret/env prep, immediately before the runner, so
  launcher validation failures such as a bad `--mount` do not strand a stale sandbox flag.
- Added a fork-sidecar bad-mount regression that asserts clean launch failure, no sidecar runner invocation, and
  `confirmed.is_sandboxed == false`.

**Verification**: focused supervisor/session/regression suite 293 passed; Docker supervisor integration 10 passed;
layering/UI-free greps empty; `make pre-commit` clean.

### session_op_layer_extraction Slice 1: Claude session preflight split

**Goal**: Start the staged Claude session CLI/core split with the lowest-risk helpers and a manifest characterization
safety net.

**Key changes**:

- Added a JSON-string manifest characterization test for Claude `start --no-launch` and fresh resume, pinning dataclass
  field order and normalized volatile values.
- Added `forge.core.ops.claude_session.resolve_and_validate_system_prompt` and rewired launch prompt resolution through
  it while keeping the CLI's `Path -> str` launcher boundary explicit. Follow-up cleanup kept `--no-launch` prompt
  validation CLI-owned, avoiding a dead op-level `ForgeOpError` path.
- Moved the CLI-free model-pin support cluster into `forge.session.model_pin`; `cli/session_model_pin.py` now only keeps
  UI-tangled persistence/warning behavior.
- Accepted `session_op_layer_extraction` into `doing/` with Slice 1 verification recorded. Parent patch count remains
  270 across 13 files; `session_lifecycle.py` is 2,496 lines after the slice.

**Verification**: characterization test 2 passed; focused units 241 passed; Docker lifecycle integration 21 passed;
layering/UI-free greps empty; `make pre-commit` clean.

### reject_rewind_transfer_strategy: rewind is not a transfer-context strategy (PR #68)

**Goal**: Fix the follow-up bug from #66 -- adding `ResumeStrategy.REWIND` made the codex/transfer ops accept
`strategy="rewind"` at the front door even though transfer assembly rejects it (rewind is a Claude-only `--drop-last`
launch path, not a context-assembly strategy).

**Key changes**:

- Single source of truth in `session/transfer.py`: `TRANSFER_CONTEXT_STRATEGIES` / `TRANSFER_CONTEXT_STRATEGY_VALUES` +
  `parse_transfer_context_strategy()` (the four assembly strategies; excludes rewind). The four codex/transfer ops and
  both transfer-facing CLI `Choice` lists source from it; `assemble_transfer_context` now rejects any non-transfer
  strategy (not just `REWIND`) with one uniform message, fired before the ~20s `codex doctor` preflight + session
  create/rollback.
- Deliberately untouched: the `manager.py`/`cli/session.py` transfer-mode branches (rewind dispatches to its own launch
  path before they see it; their `assemble` backstop still fires) and the fork/resume `Choice` lists (rewind-inclusive
  superset).

**Verification**: 253 unit tests green (codex ops + transfer + session_codex, incl. parametrized `[bogus, rewind]`
rejection); `make pre-commit` clean. Merged via PR #68 (`016e9d0a`).

### rewind_resume_strategy closeout: drop-last-N resume with an AI code-delta

**Goal**: Ship `--strategy rewind --drop-last N` -- resume/fork a session that carries turns `1..(T-N)` as *real*
relocated Claude history plus an AI-generated code-delta of the dropped window -- and close the card after PR #66 merged
to `main`.

**Key changes** (shipped via PR #66, `107b9251`):

- New `session/rewind.py` primitive: writes a truncated raw-JSONL prefix under a **fresh** rewind-owned UUID `<R>`
  (snapped to a complete `tool_use`/`tool_result` turn boundary), and builds a grounded net-change code-delta over only
  the dropped window `(T-N)..T`. Launches `--resume <R> --fork-session` co-delivered with an
  `--append-system-prompt-file` code-delta context.
- Deliberate break of the `native-relocate => no context file` convention: `Derivation` gains additive `dropped_turns` +
  `rewind_relocated_session_id` (no `SCHEMA_VERSION` bump); design.md §3.9 documents the new matrix row and flags it
  convention-not-guard.
- Fail-closed contiguity guard (`_assert_kept_turns_form_raw_prefix`) rejects requestId-interleaved transcripts;
  code-delta LLM failure falls back to plain native-relocate + a "code-delta unavailable" note; a privacy warning fires
  when the dropped window is sent to the curation model. Fork rewind is worktree/`--into`-only (same-dir/sidecar
  rejected); `resume --fresh --strategy rewind` is legitimately same-dir because it resumes `<R>`, not the parent UUID.
- Docs synced in-PR: design.md §3.9, design_appendix.md §H (frontmatter enum + `rewind-code-delta` schema marker),
  cli_reference.md, end-user/transfer.md.

**Verification**: unit green on merged `main` -- 26 rewind tests (`test_rewind_strategy.py` +
`test_session_rewind_cli.py`) and 30 fork/derivation tests (`test_fork_into.py` + `test_models_derivation.py`); PR #66
landed after an 8-dimension adversarial review (verdict: mergeable, no blocking defects). **Disclosed gap**: the
real-`claude` resume against a truncated `<R>` prefix is unit-covered only -- the `@pytest.mark.slow` integration test
is not yet written (design.md:765 records the same caveat). The Slice-1 stem probe proved stem-tolerance live on Claude
Code 2.1.197.

### Board closeout: Sonnet 5 done; accidental_complexity A/B merged + paused

**Goal**: Reconcile the board after PR #65 merged -- close the shipped Sonnet 5 card and pause the accidental-complexity
cleanup with Batch C still open.

**Key changes**:

- `sonnet_5_default` moved `doing/ -> done/`: Sonnet 5 catalog/template support + the sonnet/opus default-tier flip
  shipped via PR #64 (`75cd28b5`). Final closeout item ticked.
- `accidental_complexity_cleanup` moved `doing/ -> paused/`: Batches A + B merged via PR #65 (`584aa2a1`), including two
  pre-merge review follow-ups (a `FORGE_DEBUG` fail-open regression test and a `loader.py` black-format fix). Paused
  with Batch C (#17-#20) and the two surfaced defects (Defect B auth-retry provider-trace gap, Gap A policy fail-open
  prose-only check) still open.

**Verification**: Board/docs-only commit. PR #65 landed green (8-dimension adversarial review + independent
`make pre-commit` and full touched-suite run clean); no code change here.

### accidental_complexity_cleanup Batch B follow-up: proxy/template config load boundaries

**Goal**: Close the Batch B review findings around newly-invalid proxy providers and malformed proxy/template YAML
surfacing as raw tracebacks in user-facing CLI paths.

**Key changes**:

- `ProxyInstanceConfig` loading now normalizes malformed proxy-file shape to `ValueError` at the loader boundary, with
  explicit mapping checks for `tiers`, `tier_overrides`, and each tier override leaf. Empty/null override leaves remain
  "no override"; falsy non-mappings (`[]`, `false`, `""`, `0`) now fail instead of being ignored.
- Template loading now rejects non-mapping nested dataclass fields before schema `__post_init__` can raise raw
  `AttributeError`/`TypeError`; proxy orchestration wraps malformed templates as `ProxyStartError`.
- CLI boundaries for `proxy start`, `proxy create`, and session model-pin proxy config reads now report clean contextual
  errors for legacy `provider: gemini/openai` proxy files and malformed YAML sections.

**Verification**: 328 targeted tests green across proxy commands, session model pins, config loader/schema, and proxy
orchestrator; ruff clean for touched loader/tests. Manual repros now fail cleanly for legacy provider, `tiers: []`,
malformed template `tier_overrides: []`, and falsy override leaf `tier_overrides.haiku: []`.

## 2026-07-01

### accidental_complexity_cleanup Batch B: template move, legacy-search delete, secrets/provider narrowing

**Goal**: Execute Batch B (#13-#16) of the 2026-07-01 simplicity-audit card -- remove the remaining medium-effort
accidental complexity behind clean seams (same branch).

**Key changes**:

- **#13**: The 4 debate/consensus evaluation templates existed twice (constants in `cli/workflow.py` + copies under
  `src/skills/*/resources/`, kept in sync by drift-guard tests). `git mv`'d the copies into `forge.review.resources`
  (byte-identical); resolvers load them via the existing `_load_workflow_resource`. Single source now, so both drift
  guards are deleted; placeholder/vocabulary invariants + direct `_resolve_*_prompt` tests move to `test_run_resources`.
  Net -336 LOC in `workflow.py`.
- **#14 (full delete)**: Removed the legacy in-memory `search()` -- a second BM25 scorer with no production callers,
  used only as a test oracle. The 12 `TestSearch` cases now run through a `_search_docs` adapter over the real
  `search_from_index`; the score-equivalence oracle is retired. `SearchDocument.tokens` kept (rebuild-index reads it).
- **#15**: Deleted `ConfigSecretsProvider` + `ProviderConfig.auth_url` + the `GEMINI_AUTH_URL`/`OPENAI_AUTH_URL` env
  mappings -- write-only plumbing never wired into the production Env+File credential chain. Chain tests moved onto the
  real Env+File chain; the h6 no-coercion guard now covers the surviving `FORGE_HOME` mapping.
- **#16**: Narrowed `ProxyInstanceConfig` providers to `{litellm, openrouter}`. `gemini`/`openai` previously validated
  then silently routed to LiteLLM; since validation runs on every read, they now fail fast with a message naming the
  supported providers + recreate path (durable-state clean break). Shipped templates write `provider=litellm`, so create
  flows are unaffected; gemini/openai model-name detection is untouched.

**Verification**: targeted unit suites green per item (search 153; config/auth/proxy/backend 1143; run_resources +
skill_content 84); #15/#16 integration-verified (auth credential resolution 4 passed, proxy commands 27 passed);
per-file `make pre-commit` clean. A 4-way adversarial review over the committed diff returned one low finding (a stale
provider comment), fixed. Batch C + surfaced defects stay open (card in `doing/`).

### accidental_complexity_cleanup Batch A: dead-code removal + drift fixes + one CLI bug

**Goal**: Execute Batch A of the 2026-07-01 simplicity-audit card -- remove verified accidental complexity and fix the
one bug it surfaced (branch `cleanup/accidental-complexity-batch-a`).

**Key changes**:

- Deleted zero-caller dead code: `promotion.py`, `resolve_template_paths`, `load_yaml_strict`,
  `resolve_subprocess_proxy_url`, `_dedupe_specs` (verified no-op: sole caller feeds one unique-path scan), and the
  never-run generic `_coerce_env_value` branch.
- De-duplicated telemetry: `provider_trace_logger` imports `RequestMode`/`LocalUsageStatus` from owner `downstream.py`;
  hoisted the byte-identical `_worker_reason_code` + upstream-emission block from the Claude/Codex invokers into the
  shared `_lifecycle` base (`operation=None` suppression preserved). Passport drops the unread `inherit_on_fork` field
  but keeps the key in `_KNOWN_UPDATE_KEYS` (accept-and-ignore).
- **Bug fix (#1)**: `backend delete --port` drove `stop_cmd.callback()` (double "Stopped" + a `sys.exit` bypassing
  delete's error path); both commands now share a silent `_stop_instance`.
- **Behavior (#9)**: `ListSessionsItem.is_active` wired to the runtime `ActiveSessionStore` (was hardcoded `False`).
- Docs/UX: reworded the `--no-proxy` guard to name `--proxy`; removed two stale CLI-alias doc lines; fixed the
  `CredentialManager` "proactive refresh" docstring.

**Verification**: full unit suite `7222 passed`; ruff + mypy + `make pre-commit` clean. New tests: `is_active` liveness,
legacy-passport accept-and-ignore, backend delete-double-stop regression. Batches B/C + surfaced defects stay open (card
in `doing/`).

### Sonnet 5 support + default-tier flip

**Goal**: Teach Forge about Claude Sonnet 5 across catalog/templates and promote the newest models to the default tiers.

**Key changes**:

- Catalog: added `claude-sonnet-5` (native 1M, adaptive-only, `token_estimate_multiplier: 1.35`) + aliases
  (`anthropic/claude-sonnet-5`, `sonnet-5`, `claude-sonnet`). Flipped all four `defaults` — sonnet -> `claude-sonnet-5`,
  opus -> `claude-opus-4-8` (anthropic + openrouter); `sonnet`/`opus`/`claude-opus` friendly aliases follow. Cleared
  Opus 4.8's stale `opt-in` tag and the now-wrong "defaults stay on 4.6" comments.
- Templates: the four anthropic-family templates default sonnet -> Sonnet 5, opus -> Opus 4.8; Fable 5, Opus 4.6, and
  Sonnet 4.6 moved into `model_alternatives` (still pinnable via `--model`).
- Passthrough: `_proxy_supports_model_pin` now short-circuits for `wire_shape == "anthropic_passthrough"`, so any Claude
  `--model` pin is honored (passthrough forwards unchanged). Also fixes a latent inability to pin Opus 4.8/4.6 on
  passthrough. Covered by `tests/regression/test_bug_passthrough_model_pin.py`.
- Estimator: `PROXY_CONTEXT_MODEL_DEFAULTS` -> `claude-opus-4-8[1m]` / `claude-sonnet-5[1m]`.
- Intelligence-score rerank so Sonnet 5 (98) sits between Opus 4.6 and Opus 4.8: Opus 4.6 98 -> 97, Opus 4.7 99 -> 98
  (was tied with 4.8 at 99), Opus 4.8 99 and Fable 5 100 unchanged. Sonnet 5 = 98, peer of Opus 4.7.
- Review quorum's `claude-opus` worker now resolves to Opus 4.8 automatically (it tracks `get_default_model`, no
  review-code change).
- Docs: proxy / model_selection / session / skills / workflow / cli_reference / README + QA proxy checklist synced.

**Verification**: `make test-unit` (7231 passed); targeted catalog/config/session/proxy suites + new passthrough
regression (470 passed); scoped Docker integration (`session start --model`, bare `claude start` default model — 2
passed); `make pre-commit` clean.

### consumer_lanes epic: closeout (team-supervisor codex dispatch carved out)

**Goal**: Close the `consumer_lanes` epic now that its lane contract is shipped and folded into normative design docs.
The one remaining follow-on -- team-supervisor codex dispatch -- is a different abstraction, so it is re-filed as a
standalone card rather than held open under the epic.

**Key changes**:

- **Decision**: consumer_lanes is complete at the lane-contract level for team-supervisor (lane placement, `claude-max`
  billing, freeze-on-real-dispatch, observability). A codex team-supervisor lane is deferred because it needs
  runtime-neutral plan/context delivery -- a team-orchestration / context-design concern, not the lane substrate.
- **Verified basis** (`src/forge/policy/team/handlers.py`): `TEAM_SUPERVISOR_CONSUMER.allowed_lanes` has no codex lane
  (`:38-43`), and supervision context reaches the handler only via `run_claude_session(resume_id=...)` =
  `claude -p --resume` (`:267-269`). `codex exec` has no `--resume`, so a codex arm would be plan-blind -- unlike the
  blind / in-band T4/T6b/T6c arms.
- New follow-on card `docs/board/proposed/team_supervisor_plan_context/` (goal, design decisions owed, constraints).
- Epic `doing/epic_consumer_lanes/ -> done/`; card + checklist marked closed; the stale checklist closeout note (still
  describing T6c as active in `doing/`) corrected. 22 member back-links repointed to `done/epic_consumer_lanes` (line-3
  `**Epic**:` headers only; no narrative touched).

**Verification**: Docs-only closeout, no code change. Code claims re-verified against `handlers.py` before writing;
back-link repoint confirmed (0 remaining `doing/epic_consumer_lanes` refs in `done/`).

### consumer_lanes T6c: Memory-writer codex dispatch arm

**Goal**: Bind the memory writer to its resolved lane's runtime so a codex binding dispatches a real `codex exec` arm
(`review-only` on `read-only`, `augment` on `workspace-write`) instead of falling through to `claude -p` -- the epic's
first consumer whose codex lane can write the repo.

**Key changes**:

- `run_memory_writer` resolves the runtime from the bound `LaneRecord` (T6b's `LaneRecord -> Lane -> resolve_lane`
  guard) **before** the claude-availability check, then branches into `_dispatch_codex_memory_writer` ahead of the
  claude `on_dispatch` (claude path byte-identical). A codex-bound writer runs when `claude` is absent (Finding 2).
- Per-mode sandbox; **no Claude permission scan** (D4). A live Phase 0 probe found a codex `workspace-write` *denial*
  exits 0 with `is_error=False` (rides `turn.completed`), so `runtime_is_error` does not catch it -- immaterial, because
  in-project doc writes (`cwd=forge_root`) auto-approve and never hit the rejection path. Real provider/turn failures
  still fold via `runtime_is_error`.
- Degrade is **best-effort async** (detached worker, stdout -> DEVNULL): log + outcome + `return False`, never raises.
  Single upstream row -- the invoker's `_emit_codex` owns the outcome for spawned runs (failure-biased, so a success
  writes none under default volume, claude parity); the arm records manually only on a no-spawn preflight failure
  (Finding 1, no double-count).
- Shared codex-smoke fixtures extracted to `tests/integration/session/conftest.py`. Design docs synced (design_appendix
  §G, cli_reference, design.md, end-user memory.md).

**Verification**: 189 unit green (`test_memory_writer.py` + lane siblings), CLI bridge covered
(`test_run_cmd_forwards_codex_lane_record`, `test_set_memory_writer_via_codex_runtime`); live real-codex E2E 2 passed
(64s) -- augment actually edited a doc under `workspace-write`, one `runtime=codex`/`subscription_quota` event, no
upstream row on success; `make pre-commit` clean. Merged in PR #62 (`1064b8c8`).

## 2026-06-22 -- 2026-06-30 (compacted)

Consumer-lanes, corrupt-state, CLI-taxonomy, and Codex proxy-launch arc. Detailed card history remains in the matching
`docs/board/done/` cards and PRs; this summary preserves the decisions, behavior changes, verification anchors, and
deferred items.

- **consumer_lanes T0-T7**: introduced runtime-native subscription sources (`chatgpt`, then `claude-max`) and the pure
  `core.lanes` model, moved the semantic supervisor onto lane resolution, then made codex the first real non-Claude
  supervisor lane. Later slices added lane observability, persisted/frozen supervisor lane bindings,
  `forge session lane set/show/clear --consumer`, aux-consumer `claude-max` billing, shadow-curation codex dispatch, and
  sticky fail-open degrade from exhausted codex subscription lanes back to the default `claude -p` lane. Decisions:
  runtime-native auth is endpoint semantics, not a relaxed credential; T3 kept Claude byte-identical; T4 bypasses the
  proxy chain; aux freeze happens on real dispatch while supervisor freeze stays tied to its registered lifecycle;
  shadow-curation codex failures are fail-loud, not fail-open. Deferred: memory-writer codex dispatch, team-supervisor
  plan-context/codex arm, live codex subscription-exhaustion trigger, and some release-tier real-API validation.
  Verification included focused lane/source/supervisor/session/usage suites, full unit sweeps around 7k tests, Docker
  real-Claude supervisor/handoff coverage, and a host ChatGPT `codex exec` shadow-curation smoke.
- **State corruption/unreadable handling**: unified durable corruption under `StateCorruptedError` with one reset tip,
  added `forge clean` corrupt-state recovery, removed legacy baggage, then completed fail-closed GC/reset-tip coverage
  and strict cost-config validation. Follow-up split transient `OSError` reads into `StateUnreadableError`, so
  unreadable files surface check/retry guidance and are never deleted as corruption. Decisions: best-effort scan/list
  sites may still degrade, but specific-target paths propagate corruption/unreadable to the top-level handlers; hook
  commands emit `{decision:block}` JSON envelopes. Verification: 6.9k-7.3k unit/regression passes, corrupt/unreadable
  regression files, adversarial review findings fixed, `make pre-commit` clean.
- **forge_cli_cleanup slices 02-12 + closeout**: moved transfer/memory under `forge session`, moved telemetry under
  `forge telemetry`, moved backend under `forge model`, removed `forge session context`, removed alias shims
  (`authentication`, `extensions`), normalized non-leaf behavior, routed Rich errors/tips through output helpers, split
  `policy supervisor` into explicit leaves, standardized destructive `clean`/`delete`/`reset` prompts, enumerated
  editable-config verb parity, and drained read-output JSON/stream ledgers. Breaking clean-breaks intentionally return
  Click native errors; kept aliases are `ext`/`sess`/`mem`/`cfg`, with no new aliases for `telemetry`/`model`. Durable
  lessons promoted: alias policy and the Python-symbol-vs-CLI-alias trap. Verification included CLI unit sweeps, command
  tree invariants, JSON shape/stream tests, Docker installer/search/backend integrations, `uv build`, and
  `make pre-commit`.
- **forge_codex_command_group Phase 1/3/4 + closeout**: shipped `forge codex status`, the `openai_responses_passthrough`
  wire shape and Responses ingress, then `forge codex start --proxy`. The transport forwards Codex `/v1/responses*`
  byte-for-byte to preserve signed reasoning; route/preflight/proxy capability gates all require
  `wire_shape == openai_responses_passthrough` plus `responses_ingress`; generation-only accounting prevents retrieve
  double-counting; launcher strips native OpenAI/Codex auth and relies on proxy-owned upstream credentials. Review
  hardening added proxy identity verification so stale registry entries on reused ports cannot misroute Codex.
  Verification: status/transport/launcher unit suites, full CLI suite, real codex 0.141.0 routing through Forge to
  `POST /v1/responses`, proxy identity live-check, and `make pre-commit`; deferred live 200 reasoning round-trip
  remained blocked by a dead OpenAI key.
- **2026-06-25 real-checker fix**: the cascade short-circuit E2E was not flaky; its plan said "Create" a file that the
  harness pre-created, so the conservative checker correctly escalated. The plan now authorizes overwriting the existing
  file. Verification: Docker real-supervisor E2E 10/10; fixed test passed repeated real-checker runs.

## 2026-06-18 -- 2026-06-20 (compacted)

Telemetry backend-attribution + remote-reconciliation arc (cards: `upstream_downstream_ledgers`, `unified_backend`,
`backend_remote_reconciliation`, `openrouter_user_direct_callers`).

- **upstream_downstream_ledgers** (06-18): re-cut telemetry into `~/.forge/telemetry/{downstream,upstream}/` JSONL
  planes (downstream = model-attempt evidence; upstream = operation outcomes, default volume `non_success`). Cap-safe
  migration: caps persist `telemetry/caps/<proxy_id>.json` and bootstrap from `max(cap_state, downstream, legacy)` so
  the path move never zeroes monthly caps; `proxy costs reset` wipes all new planes + caches; provider-trace reads
  project downstream fields. Closeout: two-pane `forge activity` (Operation outcomes / Model calls), shared measurement
  resolution, engine writes via `record_upstream_operation`. Verified: 264 + 32 + 434/237/517 + 36 integration;
  `make pre-commit`.
- **unified_backend** (06-18, closeout 06-19): built-in `ModelSource` catalog (local/remote LiteLLM, OpenRouter,
  Anthropic passthrough, direct); templates moved to `proxy.source` deriving endpoint/auth/lifecycle from the catalog;
  downstream `backend_id` attribution while `source_id`/`source_kind` stay writer-origin; OpenRouter-specific gates
  replaced by source capabilities. `backend list/show` mark a shared local LiteLLM instance (display-only, never feeds
  `backend_id`). Follow-up: custom templates preflight credentials from declared `proxy.source`. Verified: 526 + 11
  integration; 175; 156 focused; `make pre-commit`. Shipped via PR #39 (`ab690ac9`).
- **backend_remote_reconciliation** (PR 1 06-19, PR 2 06-20): generalized provider-trace/user-grouping off OpenRouter
  (`openrouter_user_grouping` -> `provider_user_grouping`; capability-gated by `backend_id`; a source-less proxy writes
  no trace). PR 2 shipped `forge backend reconcile <source-id>` (single-id MVP): `backend/remote/` adapter protocol +
  registry, `OpenRouterRemoteAdapter` (metadata-only `GET /generation`, never content), buckets
  joined/remote/missing-remote/not-queryable; remote/network failures are renderable data, never raised (hardened by a
  32-agent review, 21 findings: NaN/overflow bodies -> `unavailable`). Verified: 185 + 52 + 2322; live
  `test_provider_trace_e2e.py`; `make pre-commit`.
- **openrouter_user_direct_callers** (06-20): extended OpenRouter `user`-field grouping to direct `core.llm` callers
  under ONE global toggle `provider_trace.inject_provider_user` (`~/.forge/config.yaml`, default off) instead of
  per-proxy; `forge config set/edit` gained nested-section support. Breaking (research preview): per-proxy `proxy.yaml`
  `inject_provider_user`/`inject_openrouter_user` removed (stale key ignored with a one-time relocation warning).
  Verified: 432 tests; mypy/pyright; sidecar Docker integration; `make pre-commit`.

## 2026-06-16 (compacted)

### proxy_log_hygiene (slices 0-5 + reviewer follow-ups)

**Goal**: Cut low-value proxy log volume (poll spam, per-chunk dumps), add bounded redacted request diagnostics aligned
with the audit no-plaintext policy, and close reviewer-found leaks.

**Key changes**: Folded loader bug fixed -- both proxy-config hops now carry `provider_trace` + `logging` (was silently
dropped; `test_bug_provider_trace_loader_dropped.py`). Successful completions log at DEBUG, INFO reserved for `>=400` /
slow polls; per-chunk stream dumps require opt-in AND DEBUG; shared `format_stream_lifecycle_summary` replaces
per-stream INFO bookends. Per-proxy `logging.requests` (`RequestLogConfig`, strict coercers, `body_capture=full`
rejected) reuses the audit body redactor -- no second sanitizer. New shared `proxy/retention.py::prune_jsonl_shards`
(age-then-size) backs audit/provider-trace/request planes. Reviewer round: 8 converter log sites reduced to
metadata-only, `stop_sequences` plaintext leak redacted in `_redact_body_for_log`, CLI int coercion for
`max_file_mb`/`stream_chunk_max_bytes`, third `create_proxy_file` template-block drop fixed.

**Verification**: 6401 unit + 438 regression green; live-proxy integration (`test_proxy_local_litellm_e2e`,
`test_provider_trace_e2e` incl. cancelled-stream) pass; two adversarial review rounds (0 production defects; nits fixed
incl. 0600-owner assertion). Docs: design §7.x/§3.14, appendix §A.11, `proxy.md`, `cli_reference.md`.

### openrouter_observability Phases 3-5

**Goal**: Persist metadata-only, owner-only provider-trace records at the shared stream seam and give them a read
surface (answer "what happened to this OpenRouter request?" after a timeout), then close the loop upstream via opt-in
`user`-field injection.

**Key changes**: **P3** -- new `proxy/provider_trace_logger.py` plane (versioned, `0600` shards, strict-dacite read,
retention prune; modeled on the audit log); shared `record_provider_trace` at the one SSE seam gates
direct-OpenRouter-only and tracks four lifecycle flags (records `client_disconnected` on cancel); `ProviderTraceConfig`
nested into `ProxyConfig`/`ProxyInstanceConfig`. **P4** -- `core/ops/provider_trace.py` UI-agnostic `list/show/explain`
(explain is route-only/trace-derived, no credential read) behind `forge provider trace` + `%provider trace`, shared
plain-text renderer. **P5** -- opt-in `inject_openrouter_user` writes the Forge session grouping id into the OpenAI
`user` field on proxied direct-OpenRouter requests (top-level kwarg, verified channel); direct callers deferred to
`todo/openrouter_user_direct_callers/`.

**Verification**: full unit (6161->6191) + integration (393) green across phases; live-OpenRouter E2E proves a real
`gen-` id surfaces and a cancelled stream records `client_disconnected=True` / `local_usage_status="unavailable"`;
metadata-only regression (no body/prompt/completion). Docs: design §3.14, appendix §A.14.

### supervisor_statusline_health: surface frontier-supervisor fail-open

**Goal**: Make a silently-failing supervisor visible (incident: supervisor timed out 24/24, failed open to `allow` while
the status line still showed a healthy `SUP`) -- surface the fail-open the usage ledger already records, no new durable
state.

**Key changes**: `read_supervisor_health` over the ledger (newest-first contiguous error/timeout streak) via the
`forge_cost` throttle; status-line `SUP!N <kind>` suffix (YELLOW 1-2, RED `>=3`, byte-identical when 0);
`forge activity` gains generic `CommandUsage.error_kinds` + `format_failing_open` ("failing open: N timeout, N error")
and `--json` carries it. Scope: "failing open" is the supervisor formatter's read only; parse/auth fail-opens deferred
to `upstream_downstream_ledgers`.

**Verification**: 191 + 112 + Phase 3 cases green (`test_usage_summary.py`, `test_activity.py`); status-line suites
unchanged; `make pre-commit` clean. Read-only render -- no integration tier.

## 2026-06-15 (compacted)

- **openrouter_observability Phases 0-2 + review fixes** (detail in `done/openrouter_observability/`): live-probed the
  OpenRouter externals first (Phase 0 -- the `gen-` id is in `body.id`, the `x-generation-id` header, and every stream
  `chunk.id`; a stream cancelled after its first chunk is remote-absent, justifying a local-only trace; the direct path
  records the OpenAI-standard `user` but ignores a custom `session_id`, steering Phase 5 to inject under `user`). Phase
  1 minted Forge-owned provider session ids + two leak-gated `X-Forge-Session`/`X-Forge-Command` headers; Phase 2
  carried provider/generation id + allowlisted headers to the proxy boundary on an additive `ProviderTraceMeta`, kept
  separate from Forge's synthetic `chatcmpl-` id. Review fixes (R1-R3) closed the incident path: a cancelled stream
  emits `provider_meta` on the first content event (not only terminal usage), the LiteLLM Responses fallback keeps meta,
  and the direct non-streaming path populates headers via `with_raw_response`. Verification: +25 then +6 unit tests;
  full `make test-unit` green at each step; mypy/pyright/pre-commit clean.
- **supervisor_launch_controls** (detail in `done/supervisor_launch_controls/`): gave `fork/start --supervise` the
  tier-1 cascade knobs `policy supervise` had, and added per-caller `--effort` to every Forge-spawned `claude -p` (no
  global default). Two effort vocabularies kept distinct (`claude --effort` low/medium/high/xhigh/max via
  `core/effort.py`; core.llm `ReasoningEffort` none/low/medium/high/xhigh); `run_claude_session` appends `--effort` and
  fails loud on an older `claude`. Additive optional fields, no SCHEMA_VERSION bump. Verification: 906 unit + 2
  integration green; pre-commit clean.
- **same_dir_transfer_forks** (detail in `done/same_dir_transfer_forks/`): a same-dir fork with explicit
  `--strategy`/`--inline-plan` auto-switches to a curated `transfer` launch (gated on `resume_mode is None`) instead of
  silently dropping them; the worktree-transfer branch widened to
  `(is_worktree_fork and not native_relocate) or same_dir_transfer` rather than duplicating. Derivation writes the
  transfer baseline pre-refinement so a best-effort failure can't record a transfer fork as native. Verification: 41
  unit
  - 4 integration green; pre-commit clean.

## 2026-06-10 -- 2026-06-14 (compacted)

- **Codex frontend shipped as a first-class alternate runtime** (detail in `done/codex_frontend/`,
  `done/runtime_abstraction/`). Phases 2-6: one-command launch (`forge session start/resume --runtime codex`), hook
  adapter/responder surfaces, SessionStart transfer delivery, interactive TUI, codex-hooks enrollment,
  capability/version guards, review fixes (fork/rollback isolation, enrollment state, policy persistence, handoff
  artifacts, invoker). Deferred: app-server transport (`codex app-server`/`--stdio`), upstream fail-open issue (draft),
  PermissionRequest/ `trusted_hash` source-dive. Enrollment evidence (stages 84-87): trust scoped, `pretool_policy`
  enrollment-gated, SessionStart context viable when enrolled.
- **Supervisor/session in parallel**: supervisor cascade tier-1 plan checks; launch-control cascade/effort parity across
  subprocesses; shadow sampling of false-aligned outcomes; same-dir transfer forks decoupled from worktree isolation.
- **Verification**: Codex runtime/hook/session suites, real-Codex E2E, supervisor cascade/shadow suites, same-dir
  transfer regressions, mypy/pyright, `make pre-commit` clean.

## 2026-06-04 -- 2026-06-09 (compacted)

- **Codex/runtime_abstraction closeout.** `codex exec` hooks confirmed no-go headless (codex-cli 0.138.0); bridge stays
  initial-message based (`bridge_session_to_codex`, one run tree) + transfer-curation attribution; docs synced.
- **Metric/activity closeout.** Cost accounting -> reported-or-unavailable (deleted price catalog, reporter/confidence
  vocab). Breaks: `forge usage` -> `forge activity`; `--scope repo` -> `--scope workspace`; stale shims removed.
- **Reader/proxy + status-line safety.** `project_root` git-common-dir-derived for linked worktrees; JSONL non-object
  guards; headless-retry / parallel-cleanup / negative-delta / status-line regressions added.
- **Verification**: Codex probe/preflight, bridge/transfer + real-codex E2E, metric/activity/status-line suites clean.

## 2026-06-01 -- 2026-06-03 (compacted)

**runtime_abstraction Phase 4 (Slices 4a-4f) + statusline** — runtime-abstraction core:

- **Run-tree + usage ledger (4a-4c)**: `RunIdentity` env (re-roots under origin); durable versioned
  `~/.forge/usage/events/` (schema v1 strict reads, never-raising writer); `track_verb_cost` emitters.
- **Invoker + runtime registry (4d-4f)**: `core/invoker/` (review fan-out behind `run_parallel`); frozen `RuntimeSpec`
  in `RUNTIMES` + `forge runtime list` (Phase 5 capability source); runtime-tagged `ActionContext`.
- **Hardening**: `run_parallel` TOCTOU fix; both-or-neither `origin_run_id`; `forge usage [session]` + session-end
  summary; sidecar usage-ledger mount. Review fixes: workflow double-count, QA proxy bugs.
- **Phase 3 native-relocate** (PASS): opt-in `session fork --resume-mode native-relocate` (host only; transfer stays
  default). Deferred: `--rewrite-paths`, sidecar native-relocate, gated default flip.
- **Phase 2 optional audit proxy**: opt-in wire chokepoint (inert by default); redact-before-persist audit JSONL
  (`forge proxy audit show|diff`). Deferred: real-upstream `@slow` passthrough replay e2e.
- **Statusline (Phases 1-5)**: config-driven segments + lazy `RenderContext`; billing-aware cost; opt-in
  `supervisor`/`policy`/`audit`/`drift`. Break: `show_rate_limits` -> opt-in `rate_limits`.
- **Verification**: policy-hook/supervisor E2E + native-relocate regression suites pass.

## 2026-05-22 — 2026-05-31 (compacted)

- **runtime_abstraction Phase 1**: schema-backed curated transfer + `forge transfer` CLI (schema v1, three-file
  artifacts, `show|regenerate|edit|diff`; `--review`/`ai-curated` opt-in, `structured` default).
- **memory_substrate (PR #8)**: split "handoff" into **memory writer** (Stop-time curation) + **transfer**
  (resume/fork); renamed CLI, old paths tombstoned.
- **Add Claude Opus 4.8** (opt-in); **memory strategies 7->4** (`--as`->`--strategy`; shadow via `--propose`).
- **Memory Enhancement (PR #1)**: passport-authoritative doc ownership; `forge memory enable/track/untrack/list/status`
  - `shadows review`; removed `.forge/memory.yaml` + three-tier resolver. Card in `done/memory_enhancement/`.
- **CLI hardening**: command-shape invariant, shared recovery-tip helpers (`cli/output.py`), template auto-start
  proxies, live-session deletion protection.
