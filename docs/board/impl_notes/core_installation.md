# Implementation Notes: Core and Installation

Durable core, state, extension, hook, and installation decisions.

[Implementation-notes index](../impl_notes.md)

---

## Notes

### Release QA evidence is an artifact-bound contract (refresh_release_qa_for_1_0, approved 2026-09-01)

- Release-capable QA starts from an explicit prebuilt wheel. The Claude-hosted driver must match the QA package inside
  that wheel byte-for-byte before Docker mutation, and Forge/package resources must resolve from the isolated wheel
  prefix rather than a checkout or editable environment. Development-built runs remain useful but cannot emit a release
  pass.
- The repository runtime matrix owns the blocking Claude/Codex pair. Record both clients at container start and at final
  artifact save; missing or changed identity fails the pinned verdict. Resolve `latest` afresh in a separately labelled
  compatibility lane whose result never rewrites pinned evidence.
- Evidence ownership has four lanes: `automated-suite`, `clean-wheel-smoke`, `human-acceptance`, and
  `extended-exploratory`. The default release selection runs only the middle two; automated owners are references, not
  commands silently credited to the manual report. Keep the blocking selection at no more than 12 human checkpoints and
  eight subject-under-test model completions, counting every worker, round, prompted session turn, enrollment probe, and
  curation call separately from driver orchestration.
- QA remains one Claude-hosted interactive frontend. Claude and Codex are independent subjects under test; adding Codex
  runtime coverage does not justify duplicating the checklist as a Codex-hosted package.

### Worktree config cleanup must reject symlinked directory components (shipped 2026-08-20)

- Lexical containment and Git tracking checks do not make a path safe when a parent component is a symlink: filesystem
  writes and unlinks can still resolve outside the worktree or reach a tracked file under a different repository path.
- Config discovery, destination writes, cleanup, and empty-parent pruning therefore reject symlinked directory
  components. Cleanup repeats the parent check after Git I/O, immediately before unlinking, so a concurrent swap cannot
  turn an earlier ownership decision into deletion authority.
- `os.walk(..., followlinks=False)` does not protect a symlink supplied as the walk root; callers must reject that root
  before walking it.

### Repository maintenance gates are ownership decisions, not cleanup permission (approved 2026-08-04)

- **Stop verification has two supported modes.** `completion_promise` stays on the ordinary under-100-ms path;
  explicitly selected fixed `uv run pytest` is the sole blocking latency exception. Arbitrary commands are not a
  verification type, and invalid stored values must become visible fail-open configuration rather than silent success.
- **A session has separate durable, discovery, and launchability facts.** A valid manifest reserves the name and
  conversation bindings, the global index publishes it, and the recorded worktree decides whether checkout-dependent
  operations may run. A surviving manifest is degraded when its worktree vanishes, not dead.
- **Retention follows physical storage ownership.** Audit, cost, and provider lifecycle fields share downstream shards,
  so `~/.forge/telemetry/downstream/` gets one global policy and pruner. Conflicting legacy policies disable pruning
  rather than choosing a destructive minimum.
- **Deletion requires compatibility evidence per surface.** Tests alone do not make an API public, but zero production
  callers do not authorize removal. Classify imports/exports, user config, durable schemas, packaged consumers, wire
  contracts, and test disposition before deleting; split compound claims and wire intended invariants when appropriate.
- Decision records live under `docs/board/done/*_contract/`; implementation members update normative design docs only as
  behavior ships, so approval itself does not manufacture design/code drift.

### Unmanaged runtime outputs are observable state with deletion-grade provenance (unmanaged_skill_packages, shipped 2026-07-22)

- **Discovery surfaces are independently observable state.** Classify runtime discovery directories directly instead of
  deriving their health from tracking rows alone, and keep tracked-package health and unowned-entry classification as
  separate projections so adding recovery cannot weaken existing ownership semantics.
- **Deletion-authorizing provenance describes an exact reproducible tree.** It must survive loss of rebuildable caches
  and be rechecked together with ownership immediately before mutation. A marker is same-user recovery evidence, not
  authentication: any extra file, changed mode or content, unsafe path type, or external link makes the whole package
  report-only.
- **A corrupt or unreadable ownership manifest is a no-scan boundary.** Recovery is deliberately two-pass when cleanup
  first removes corrupt tracking: only a later scan may classify the remaining outputs as unowned.
- **One physical target with multiple logical scopes: observe widely, mutate narrowly.** Expose every applicable scope
  in observations but assign mutation to the narrowest clean scope. Fixed user targets remain global; project
  compatibility must not block unrelated global cleanup.
- **Unsafe containers get container-level diagnostics, not invented child records.** When an unsafe root cannot yield
  the identity a fixed per-item record requires, keep the record schema honest and surface a separate root-level
  diagnostic. Never traverse the container merely to avoid an empty result.
- **Read-only surfaces depend only on the metadata they need.** Discover candidate names without parsing full install
  sources, and let unavailable optional metadata shrink report breadth instead of blocking unrelated cleanup categories;
  mutation paths retain full validation.

### Runtime skill packages are compiled artifacts with separate ownership (cross_runtime_skills, shipped 2026-07-17)

- **Runtime selection is not persisted ownership.** Automatic enable and sync retain the union of detected and already
  managed runtimes when a binary is temporarily absent. Explicit runtime narrowing preserves omitted package tracking;
  dedicated disable owns teardown.
- **Source eligibility and executable binding are compiler inputs.** Reject symlinked source or package roots, apply the
  checkout's Git eligibility set before discovery and every read, and validate neutral and emitted packages as whole
  trees. A permitted leaf symlink requires both its alias and contained target to be eligible. Packaged-script execution
  is a separate capability from prose/resource loading and binds an owner-readable, owner-executable file from the
  selected skill root.
- **Package tracking is a strict projection of the canonical file ledger.** Empty, outside-root, unbacked, duplicate, or
  multiply claimed package paths are corrupted state and must fail before mutation. Commit tracking last; a post-write
  failure restores created files and settings ownership, while an unchanged refresh preserves its original installation
  timestamp.
- **Runtime package directories are ownership boundaries.** Revalidate directory entries with `lstat` near each
  mutation, permit install-time symlinks only at tracked leaf files, and never let `--force` adopt or delete an
  untracked same-name package.
- **Compiled-cache lifetime is part of symlink-install correctness.** The content-addressed cache has no eviction while
  tracked installs can point at digest directories. Any future cleanup must prove that no tracked symlink depends on a
  digest before removing it.

### Hook runtime ownership and recovery follow the execution environment (global runtime epic, closed 2026-07-13)

- Host Claude and Codex runtime hooks have one owner: user-scope settings containing literal absolute
  `<forge-home>/bin/forge-hook <handler>` commands. Project/local installs own `statusLine` and other project assets,
  not runtime hooks; `statusLine` remains the bare `forge status-line` scalar and does not traverse the dispatcher.
- Sidecars are a separate execution environment because host user settings are not mounted. Stage canonical direct
  `forge hook <handler>` entries into Forge-owned container-user settings and resolve them through the image PATH; never
  copy a host dispatcher path into container config or mutate mounted project settings.
- Dispatcher recovery keys on the user-scope installation row, not on the existence of any tracked installation. Repair
  an existing user install with `forge extension sync --scope user`; otherwise use
  `forge extension enable --scope user --profile minimal --with hooks,codex-hooks --without commands`. An unrelated
  project tracking row cannot make generic sync actionable.

### Project compatibility follows target ownership and mutation posture (forge_project_compat_mutator_sweep, shipped 2026-07-12)

- **Guard the Forge root that owns the state being changed, not the caller's CWD.** Named cross-CWD session operations,
  nested `fork --into`, and managed worktrees must resolve the target root before any dispatch or write. A strict
  `check_project_compatibility()` read is not enforcement: a valid version mismatch returns `compatible=False`, so
  refusing code must call `enforce_project_compatibility()` or reject that result explicitly.
- **Posture belongs to the operation boundary.** Explicit CLI and mutating `%` commands fail closed before side effects;
  lifecycle/context hooks diagnose once and preserve their wire; detached work refuses the project write without
  changing an unrelated foreground command's result. Operation semantics win over transport, so WorktreeCreate and
  mutating `%` forms remain strict even though they arrive through hooks.
- **Background refusal must stay bounded.** Index and shadow markers use the existing retry-to-`failed/` queue contract,
  preserving fairness and poison evidence. The already-detached memory writer instead records
  `project_compatibility_refused` and exits 0. Do not invent a permanently pending marker state.
- **Global state is exempt only when it has no Forge-root owner.** Proxy/backend registries and read-time repair of
  proven-stale derived session/active rows remain available under an incompatible CWD pin. Paired index writes still
  inherit the owning project mutation's guard; mixed cleanup gates only project-owned items and reports partial refusal.
- **Destructive worktree replacement needs prospective checks.** Before stale `fork --worktree --force` removes
  anything, validate the stale root, exact replacement commit, and branch safety; create from that pinned commit and
  retain the post-create target defense. A refusal must preserve the checkout, branch, dirty files, manifest, index, and
  transfer state; rollback failures must be surfaced.

### Dev hook selection is a resolver override; transient venvs are never implicit runtime metadata (forge_dev_runtime_override, reviewed 2026-07-11)

- `FORGE_DEV` changes binary resolution, not dispatch eligibility. The generated dispatcher applies the managed-session
  / enrolled-root gate and missing-handler check first. Only then does presence of the variable -- including an empty
  value -- enter a hard branch for `<absolute-checkout-root>/.venv/bin/forge`. An invalid target or failed `exec` exits
  127 and must not fall through to the normal skip-invalid candidate loop. The override mutates no `runtime.json` state,
  does not bypass project compatibility, and does not apply to sidecar hooks that bypass the host dispatcher.
- Implicit launcher recording is a total, ordered transition: executable non-venv discovery; otherwise valid recorded
  non-venv launcher; otherwise first executable known-global fallback; otherwise `null`. Keep custom non-venv launchers
  and deliberate A-to-B migrations working. An explicit installer `forge_binary_path` remains authoritative. Do not
  replace this table with a global-directory allowlist or record an unverified fallback path.
- Venv classification is lexical: inspect the candidate path's own `bin`/`Scripts` parent for sibling `pyvenv.cfg` and
  never resolve the candidate first. Resolving `~/.local/bin/forge` would land inside the uv tool venv and incorrectly
  reject the stable global launcher symlink. Legacy recorded `.venv/bin/forge` paths are replaced or cleared on the next
  enable/sync through the same table.
- Managed Claude and Codex launchers inherit `FORGE_DEV`, so changing or unsetting it requires a relaunch. Doctor
  reports the value from its own process environment, which may differ from the hook launcher, and separates target
  `valid` from dispatcher `effective` (valid target plus current, executable installed shim).

### Hook migration discovery must not activate roots; selected-root cleanup enrolls last (forge_hook_migration_cleanup, shipped 2026-07-11)

- Project-registry enrollment is runtime activation, not discovery metadata: the user dispatcher begins handling ambient
  hooks in an enrolled root. User-scope `extension enable`/`sync` may report tracked migration candidates, but must not
  open their checkouts or read/write `projects.json`; otherwise a read/report path can create double-fire without
  producing a repository diff.
- `forge extension cleanup-project --yes` is the explicit mutation boundary for one selected root. It strictly
  preflights shared and selected-root state, removes eligible legacy registrations first, reconciles tracking, ensures
  user runtime registration, scans for unresolved duplicates, and enrolls only that root as the final activation write.
  A post-removal failure is an honest hooks-off recovery state: retain backups and report the exact retry command rather
  than restoring legacy hooks or claiming success.
- Ambiguity is operation-scoped. An unresolved registration in the selected root blocks that cleanup; an unresolved
  registration in another tracked root remains doctor/candidate-report state and must not suppress the user's own
  dispatcher installation.

### User-scope hook dispatcher is a generated runtime artifact, with fail-open gate semantics (forge_hook_dispatcher, 2026-07-08)

- `~/.forge/bin/forge-hook` is a standalone stdlib script rendered from `src/forge/install/hook_dispatcher.py`, not a
  normal import path. It cannot assume Forge's package is importable from hook-launched `python3`. Keep the no-op gate
  dependency-light and preserve its generated-source stamp. Recovery must follow the user-scope installation state:
  `forge extension sync --scope user` for an existing user row, otherwise the hooks-only user-scope enable recipe above.
  Do not infer that generic sync is actionable from an unrelated tracked project installation.
- The dispatcher gate is fail-open: corrupt/newer/unknown-field project registry state, deleted cwd, and transient
  filesystem gate errors degrade to exit 0 with no traceback. Resolver failures happen only after the gate chooses to
  dispatch and should remain fail-loud with checked locations.
- The embedded gate intentionally mirrors `core.ops.context.find_forge_root` and project-registry
  parse/canonicalize/match behavior. If those rules change, update `_GATE_SOURCE` and the parity fixture matrix
  together; the source hash catches installed-vs-package staleness, not semantic drift between the package
  implementation and the embedded copy.
- Treat the Phase-0 benchmark script as the performance authority. Unit tests should pin no-dispatch/no-import behavior
  on populated registries rather than assert tight cold-start wall-clock ceilings that can flake on slower hosts.

### `FORGE_*` env vars are a classified interface, not general user vocabulary (env_var_interface_boundary, shipped 2026-07-07)

- The human authority is `docs/design_installation.md` §A.7b. Public names are `FORGE_DEV`, `FORGE_HOME`, and
  `FORGE_PROFILE`; public-diagnostic names are `FORGE_DEBUG` and `FORGE_STATUS_TRUNCATE`;
  launcher/proxy/run-tree/session names such as `FORGE_SESSION`, `FORGE_FORK_NAME`, `FORGE_RUN_ID`, and
  `FORGE_SUBPROCESS_*` are internal wiring; `FORGE_QA_*` and `FORGE_TEST_REPO` are test/QA harness variables.
- Normal-flow user surfaces should say "current session", "Forge-managed session", and `--session <name>`, not tell
  users to set launcher-owned env vars. Troubleshooting docs may name internal wiring only inside paired
  `forge-env-vocab: diagnostic:start/end` markers.
- `tests/src/cli/test_env_vocabulary.py` is the drift guard: live product-env inventory coverage, AST scan over CLI/op
  user-visible sinks (including `console.print` and Click echo/exception aliases), literal scan over `docs/end-user/**`
  - `docs/cli_reference.md`, boundary-matched internal names, and parity between its mapping and the appendix table. Add
    future public `FORGE_*` vars to both the appendix and the guard before documenting them in normal-flow help/docs.

### Project registry trust keys preserve filesystem boundaries; compatibility pins are opt-in guardrails (T3/T7, shipped 2026-07-07)

- `~/.forge/projects.json` is Forge-owned machine state, not a hand-edit surface. Keep it versioned JSON, write it via
  locked read-modify-write + atomic replace, and preserve the split read contract: CLI/operator paths fail clear on
  corrupt, unreadable, or newer state; hook/dispatcher paths fail open with a `degraded` reason that `doctor` can
  surface.
- The project-registry trust key must not casefold or Unicode-fold unconditionally. Store the resolved canonical string,
  match exact strings first, then use `Path.samefile()` only when both paths exist. This keeps case-sensitive
  filesystems from granting trust across case-variant directories while still accepting same-directory spelling variants
  on case-insensitive filesystems. Deleted/stale roots intentionally match only exact stored strings.
- Enrollment consent is explicit or derived, never detection-based: project/local `forge extension enable` enrolls the
  targeted root; user-scope enable enrolls no root by itself; managed session worktrees/forks auto-enroll because the
  user created them through Forge. Install success and trust enrollment are separate facts.
- `.forge/project.toml` is repo-local, user-authored, and opt-in. Missing means compatible/unconstrained and should not
  warn or auto-create a file. Strict command paths fail closed on malformed, unsupported, or incompatible pins;
  session/context hook helpers fail open with diagnostics. PEP 440 range checks use
  `SpecifierSet.contains(..., prereleases=True)` so checkout-local dev/rc Forge builds can satisfy numeric ranges.
- T7 intentionally closed with the remaining mutation-family sweep split to the standalone
  [`forge_project_compat_mutator_sweep`](../done/forge_project_compat_mutator_sweep/card.md) card. That follow-up
  shipped via PR #98 with every classified project-state mutator guarded or narrowly exempted; the durable posture and
  ownership rules are recorded above.

### Install-kind detection: editable-first, launcher-symlink-not-realpath, minimal-PATH is a fact (global_forge_install, shipped 2026-07-06)

`src/forge/install/doctor.py` (`diagnose_install`) classifies how the `forge` binary is installed. Durable rules:

- **Editable is checked before venv.** A dev checkout's launcher lives in a venv `bin`, but `editable` (PEP 610
  `direct_url.json` `dir_info.editable`) is the more actionable label than `venv`.
- **Global keys on the launcher's on-PATH symlink location, not its realpath target** (`~/.local/bin` /
  `UV_TOOL_BIN_DIR` / `XDG_BIN_HOME` / `PIPX_BIN_DIR`). Resolving the symlink would land inside a `uv tool` tool-venv
  and mis-classify a global install.
- **`on_path_minimal` is a reported fact, never a fault.** A healthy `~/.local/bin` global install reads `false`
  (launchd's minimal PATH excludes `~/.local/bin`); it is the mechanical signal for bare-command consumers such as the
  project `statusLine`, not host hook reachability. Host hooks invoke the absolute dispatcher. `advice` therefore keys
  on `on_path`/kind, not on `on_path_minimal`.
- **Advice distinguishes "not installed" from "installed, off PATH."** Both read `on_path=false`; the latter gets
  PATH-setup (`uv tool update-shell` / `pipx ensurepath`), not a reinstall.
- **`install_kind` and `forge_path` are different subjects.** kind reads the running interpreter's metadata;
  `forge_path`/`on_path` read PATH resolution — they can describe different installs in a mixed dev+global setup (owned
  by T8 `forge_dev_runtime_override`).
- **Two install layers**: the `forge` tool (global-tool install, on PATH) is distinct from extensions
  (`forge extension enable` -> `.claude/`). Docs: `design.md §5.1`, `design_installation.md §C`.

### Forge hook-command detection is single-sourced in `install/hooks.py` (forge_hook_matcher_consolidation, shipped 2026-07-06)

- `install/hooks.py::{forge_hook_handler,is_forge_hook_command}` are the shared parser/predicate for "does this command
  invoke a Forge hook?". Shell-token parsing maps both legacy `forge hook <handler>` commands and dispatcher
  `forge-hook <handler>` commands (bare, quoted, or absolute-path) to the same logical handler, while rejecting
  contains-only strings such as `echo forge hook stop` and `echo forge-hook stop`.
- Entry-level settings scans should use `entry_is_forge_hook`. Any cleanup path that removes hook entries from Claude
  settings must pass `require_command_type=True` so non-command entries are preserved while still sharing the same
  command predicate.
- The registered-command contract lives in `tests/src/install/test_registered_commands_contract.py` and must key Claude
  hook rows on `(event, matcher, command, timeout)`, not a set of command strings. The two `policy-check` rows share
  bytes under different matchers/timeouts; a string set is blind to that drift. Cleanup and migration code should key
  command identity through the shared parser; any future command-byte change must update that parser and the golden
  contract together.

### Claude hook registration is owned by the tracked installer (forge_hook_legacy_writer, 2026-07-06)

- The standalone `forge hook enable` / `forge hook disable` writer was removed as a clean break. Claude hook
  registration now goes through `forge extension enable`, so writes are tracked in `installed.json` and uninstalled via
  the settings unmerge path instead of a second hand-written settings mutator.
- Runtime hook registration is user-scope-only. The public hooks-only replacement is
  `forge extension enable --scope user --profile minimal --with hooks --without commands`. This writes tracked hooks to
  `~/.claude/settings.json` without commands, agents, skills, permissions, or env.
- Tracked `--scope local` writes project/local settings such as `statusLine` to `.claude/settings.local.json`; explicit
  local/project `--with hooks` is rejected instead of silently dropped.

### Keep best-effort recovery wrappers separate from fail-loud primitives (ops_policy_seam, shipped 2026-07-06)

Proxy base-url recovery now has two deliberately different contracts in `proxy/proxies.py`:

- `ProxyRegistryStore.find_by_base_url()` is the primitive: it calls `read()` and propagates registry corruption or
  unreadability. Terminal/operator commands that need registry truth should keep using the loud primitive.
- `recover_proxy_id_from_base_url()` / `recover_proxy_entry_from_base_url()` are best-effort launch/session recovery
  wrappers: they catch, debug-log with `exc_info=True`, and return `None`. Use these from hooks, launch confirmation,
  and context enrichment paths where losing registry recovery must not break the session.

Do not merge the two postures by burying `try/except` inside `find_by_base_url`; that would hide registry corruption
from operator surfaces.

### Diverged twins: consolidate at the concept owner, characterize weak matches first (shipped 2026-07-06)

The `diverged_twin_consolidation` card closed two real drifts and dropped two false positives. Durable rules for future
refactor audits:

- **Put shared helpers at the concept owner, not the first caller.** `session_runtime(state)` belongs beside
  `SessionState` in `session.models`, not in a runtime-specific ops module. The TDD tests-first sort key belongs in
  `policy.deterministic.base` next to `is_under_directory`, because it exists to mirror deterministic policy path
  relevance.
- **Do not extract across intentionally different degrade paths.** The codex consumer arms already share
  `read_fresh_codex_preflight`; after that, supervisor, shadow-curation, and memory-writer failures map into different
  contracts. A helper that erases those contracts is worse than duplicate-looking code.
- **Characterize before aligning weak drift.** Context-limit routing looked like `proxy_id` vs `proxy_id or template`,
  but production CLI proxy routing supplies `proxy_id` on the inline paths. Keep characterization tests for these
  boundary contracts instead of forcing no-op consolidation.
- **For hooks, share the core but preserve the signal channel.** Stop emits JSON and can block with exit 2 on
  verification; StopFailure is fail-open; team hooks signal through exit code and stderr. Pin those observables before
  extracting shared hook bodies.

### State primitive hoists keep byte formats and error contracts at the caller boundary (shipped 2026-07-06)

Shared state helpers now live in `core` leaves, but callers still own their domain record shape and error vocabulary.
When adding a new durable-state or JSONL path, import the primitive down instead of re-copying it, then preserve the
caller-facing contract with characterization tests.

- **Timestamp helpers are not interchangeable.** `core.state.now_iso()` keeps the existing offset form used by state
  models, while `core.state.utc_timestamp_z()` preserves the second-precision `Z` bytes used by telemetry JSONL records.
  Do not replace one with the other to chase a "single timestamp" grep result, and do not add private `_now_iso` copies.
- **Use the bytes atomic writer for byte-owned state.** `core.state.atomic_write_bytes()` owns the file fsync,
  `os.replace`, parent-dir fsync, and optional final mode; `atomic_write_text()` is just UTF-8 text on top of that.
  Signed transcripts and other byte-exact payloads should call the bytes primitive directly, not decode/re-encode
  through text.
- **Unreadable is environmental; corrupted is content/schema.** Versioned JSON readers should map read `OSError`s to the
  `StateUnreadableError` family, while invalid JSON, missing/wrong schema versions, and malformed payloads stay in the
  corrupted family. Search stores keep domain-specific unreadable subclasses so CLI surfaces can say check/retry instead
  of rebuild/delete.
- **JSONL readers accept objects only.** Use `core.state.decode_json_object()` so blank, malformed, and
  valid-but-non-object lines (`[]`, `1`, `"x"`, `null`) are skipped before a reader calls `.get()`. Cost, usage, and
  telemetry/audit readers share this guard; do not re-copy ad hoc `json.loads` checks.

### CLI command aliases and canonical names (forge_cli_cleanup Slice 05, shipped 2026-06-24)

Durable rules for `src/forge/cli/main.py` aliasing and any future CLI command rename.

- **Two maps, one mechanism.** `_ALIASES` (alias -> canonical, resolved by `AliasGroup.get_command`) and
  `_DISPLAY_ALIASES` (canonical -> alias, surfaced in `--help` by `AliasGroup.format_commands`). Shipped set is
  `ext`/`sess`/`mem`/`cfg` only.
- **D6 alias policy (recorded in `cli_style_guidelines.md`).** Durable short aliases only when deliberately chosen (a
  rationale-backed UX affordance); new top-level nouns get NO alias by default (`telemetry`/`model` have none);
  canonical names follow user vocabulary (`auth` is canonical, not `authentication`); rename/back-compat shims are
  temporary -- remove them in a cleanup slice, never keep them indefinitely.
- **Surface vocabulary does not rename durable domain state.** `forge telemetry activity` reports Forge automation
  activity, while the internal usage-ledger plane keeps `UsageEvent`, `usage/events/`, `read_usage_events`, and
  `usage_summary.py`. Rename the user-facing surface only when the underlying domain has not changed.
- **Removing an alias for a canonical command is atomic with the registration rename.** `forge <alias>` resolves only
  via `_ALIASES`, so deleting `"auth": "authentication"` is coherent only when `main.add_command(auth, ...)` is flipped
  to `name="auth"` in the SAME change. Delete-without-rename breaks the command; rename-without-delete leaves a stale
  alias. (coding_standards "change interfaces atomically".)
- **Recurring trap: Python symbol/module path != CLI alias string.** `from forge.cli.extensions import extensions` and
  `runner.invoke(extensions, ...)` are the command-object symbol (module `forge.cli.extensions`), unrelated to the CLI
  alias string. Renaming/removing a CLI alias changes ONLY invocations through `main` with the literal token
  (`["extensions", ...]`, shell `forge extensions`); direct command-object invocations and imports stay.
  `forge extensions` (with a space) never matches `forge.cli.extensions` (dots), so it is a safe `replace_all` pattern
  -- the bare word `extensions` is not.
- **Clean-break + drift verification.** `test_command_tree_invariants.py::test_removed_aliases_are_clean_breaks` pins
  removed aliases (bare AND leaf forms) to exit 2 "No such command" and canonical names to resolve. Removed paths stay
  absent; do not add hidden tombstone groups or flag-tolerant compatibility leaves. Assert on `result.output` (this
  repo's `CliRunner()` surfaces the Click usage error there even though Click writes it to stderr). For a CLI rename run
  a zero-tolerance command-form drift sweep (`rg "forge authentication|forge extensions" --glob '!docs/board/**'` must
  be empty) plus a broader prefix-less sweep that is a *classify* step (English prose like "Show extensions status" is
  fine, not a hit). Installer/extension-path renames need the Docker integration run (`test_installer.py` etc.):
  `CliRunner` cannot catch a test asserting on the real binary's tip text (a latent plural-vs-singular assertion at
  `test_installer.py:158` was only proven correct by the live run).
