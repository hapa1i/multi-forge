# Epic: Global Forge Runtime -- one binary, layered state, user-only hooks

**This is an epic.** It coordinates the shared contract, sequencing, and drift control across the member cards below.
Each member is an independently shippable implementation unit; the epic ships no code itself.

**Lane**: `doing/` -- active coordinator, ready for closeout. Shipped members: **T1
[`global_forge_install`](../../done/global_forge_install/card.md)**, **T3
[`forge_project_registry`](../../done/forge_project_registry/card.md)**, **T4
[`forge_hook_dispatcher`](../../done/forge_hook_dispatcher/card.md)**, **T5
[`user_scope_hook_ownership`](../../done/user_scope_hook_ownership/card.md)**, **T7
[`forge_project_compat`](../../done/forge_project_compat/card.md)**, and **T10
[`forge_hook_sidecar_resolution`](../../done/forge_hook_sidecar_resolution/card.md)**, and **T6
[`forge_hook_migration_cleanup`](../../done/forge_hook_migration_cleanup/card.md)**, and **T8
[`forge_dev_runtime_override`](../../done/forge_dev_runtime_override/card.md)**. The epic's coordination
[`checklist.md`](checklist.md) (sequencing and seam drift-watch) stays live. There is no active implementation member:
T2 stays `proposed/` as superseded-not-abandoned, and the split T7 sweep is a standalone non-member follow-up
([`doing/forge_project_compat_mutator_sweep`](../../doing/forge_project_compat_mutator_sweep/card.md), active since
2026-07-12). Every live member is now `done/`; the epic remains here until its seam boxes, durable-doc verification,
inbound links, and lane move are closed as one coordinator pass.

**Origin**: `PreToolUse hook failed: exit 127` investigation, decomposed after four design-review rounds (2026-07-02).
Supersedes the single `proposed/global_forge_runtime/` card, which conflated a hook-reachability bug fix with a large
install/hook-ownership migration. The original card's content is redistributed across the members below.

**Decision direction**: Make Forge a single user/global CLI (PyPI, installed as a tool), keep project authority in
`<repo>/.forge/`, and register runtime hooks only at user scope through a no-op dispatcher that normally resolves a
durable user/global `forge` from any hook environment, with explicit process-scoped checkout selection for contributors.

**References**: `src/forge/install/preset.py` (Claude preset hook + `statusLine` commands),
`src/forge/install/codex_hooks.py` (`get_codex_config_path`, managed block markers `:56`, trust-byte pinning),
`src/forge/install/hooks.py` (shared hook command detection), `src/forge/install/settings_merge.py` (Claude
append+dedupe merge/`unmerge` `:505,:705,:731`), `src/forge/install/installer.py` (scope detection, source-hooks load
`:817`, tracked hook registration), `src/forge/sidecar/container.py` (sidecar mounts + env), `docs/design_appendix.md`
§C.6, `board_contract.md`.

---

## Members (each is a ticket)

Two linear tracks plus two cross-cutting members. The **incident track** (T1 -> T2) closes exit-127 without the
migration; the **user-scope-model track** (T1 -> T3 -> T4 -> T5 -> T6) is the larger redesign that later supersedes T2's
command bytes. **T9 and T10 are cross-cutting** -- each touches multiple byte-changing members and needs a single owner,
so neither sits on one linear track.

| Label | Card                                                                                | Ships                                                                               | Depends on  |
| ----- | ----------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- | ----------- |
| T1    | [`global_forge_install`](../../done/global_forge_install/card.md)                   | Global tool install (`uv tool`/`pipx`) + Day-1 docs + `forge extension doctor`      | --          |
| T2    | [`forge_hook_absolute_command`](../../proposed/forge_hook_absolute_command/card.md) | **Reachability fix**: absolute-path hook + statusLine command at current scope      | T1          |
| T3    | [`forge_project_registry`](../../done/forge_project_registry/card.md)               | `~/.forge/projects.json` trusted-root registry (schema + read + enroll + lifecycle) | --          |
| T4    | [`forge_hook_dispatcher`](../../done/forge_hook_dispatcher/card.md)                 | Dispatcher mechanism + resolver + **benchmark gate** + no-op gate                   | T1, T3      |
| T5    | [`user_scope_hook_ownership`](../../done/user_scope_hook_ownership/card.md)         | User-scope-only registration + detection update + double-fire detection             | T4, T3      |
| T6    | [`forge_hook_migration_cleanup`](../../done/forge_hook_migration_cleanup/card.md)   | No-double-fire migration + candidate discovery + selected-root cleanup/enrollment   | T5          |
| T7    | [`forge_project_compat`](../../done/forge_project_compat/card.md)                   | `required_forge` first guardrail slice + missing-file semantics                     | --          |
| T8    | [`forge_dev_runtime_override`](../../done/forge_dev_runtime_override/card.md)       | Checkout-local forge for Forge contributors                                         | T4          |
| T9    | [`forge_hook_legacy_writer`](../../done/forge_hook_legacy_writer/card.md)           | Delete the second hook writer + add a tracked hooks-only replacement                | pairs T2/T6 |
| T10   | [`forge_hook_sidecar_resolution`](../../done/forge_hook_sidecar_resolution/card.md) | In-container hook staging, PATH, and host-drainable deferred work                   | T5          |

## Accepted decisions

- **D1 -- Version coupling accepted.** One global binary means one Forge version for all enrolled projects. We accept
  that this **caps per-project version flexibility**. `required_forge` (T7) is a *fail-clear guardrail*, not a version
  manager; multi-version isolation is out of scope. Rationale: it matches the git/gh/claude/codex model, and Forge is a
  research preview that already clean-breaks durable state (`coding_standards` §5), so per-project version pinning was
  never a stable guarantee. Consequence: the original card's "multi-project version conflict" moves from open question
  to accepted trade-off; T7 exists to make the failure *legible* (name the upgrade path), not to isolate versions.
- **D2 -- Split the bug fix from the migration (corrected 2026-07-02).** The exit-127 incident is closed by **T2**
  (`forge_hook_absolute_command`), which rewrites the *registered* hook command to a resolvable absolute path at the
  current scope -- one Codex re-trust, no dispatcher/registry/scope change. T1 (global install) is the independent early
  win but does not by itself fix a minimal-`PATH` hook subprocess. **Correction from the first decomposition:** the
  dispatcher ticket (T4) builds the *mechanism* but does not change what is registered, so it cannot close the incident
  alone -- T2 owns the byte change. The user-scope model (T3-T6) is the larger migration that later supersedes T2's
  bytes.
- **D3 -- statusLine stays project-scoped (2026-07-02 review; maintainer-ratified 2026-07-02).** Unlike hooks,
  `statusLine` is a **scalar** (`set_scalar`, one value) -- it cannot double-fire, so the user-scope-only rationale (T5
  "Why": remove double-fire *by construction*) does not apply to it. It also self-gates on `FORGE_SESSION`
  (design_appendix §A.8: no `FORGE_SESSION` -> no session info, **no CWD fallback**) and Claude tolerates a failing
  statusLine gracefully. Moving it to user scope would run `forge status-line` at **full Forge import in every repo on
  every render** -- the exact per-render cost the hook no-op gate exists to avoid, but with **no gate in its path** --
  and would raise a product question (render in non-enrolled repos at all?). Keeping it project-scoped dissolves both
  the cost and the question. **Consequence:** statusLine is a *documented exception* to "user scope owns all runtime
  config" -- it stays bare and project-scoped; T10 makes the bare command resolvable on the sidecar image PATH, while
  the user-scope migration (T5) covers **hooks only**. **Reversal cost if user-scope is chosen instead:** statusLine
  needs its own gated entrypoint (fast-exit before heavy import, or a status-line shim mirroring the dispatcher) + the
  non-enrolled-repo product call + a T4 contract extension for a non-hook command + T5 acceptance rows in both
  directions.

## Shared contract (the epic owns this -- drift control)

The members touch five seams that MUST stay consistent. Drift here is the reason this is an epic:

### 1. All Forge-registered command strings + shared matcher

Not just the Claude/Codex *hook* commands -- **every** string Forge writes into a runtime config is a byte-identity
contract, and byte-identity is the API:

- **Registered strings:** Claude preset hooks (`preset.py`, 13 event keys incl. `PreToolUse:Read`), the Claude
  `statusLine` command `forge status-line` (`preset.py:218-222`), and the Codex managed block (`codex_hooks.py:84`). The
  command string is part of Codex's `trusted_hash` surface (golden-pinned; `codex_hooks.py:16-19,66-67`,
  `test_codex_hooks.py:71`). T2 rewrites all of these to absolute paths; the T4/T5 cutover rewrites the **hook**
  commands again (to the dispatcher form). **statusLine is the exception (D3):** it stays project-scoped, so it is
  rewritten **once** (T2 absolute path) and never moves to the dispatcher form or user scope.
- **Detection moves in lockstep or it lies:** `forge_hook_matcher_consolidation` single-sourced command detection in
  `install/hooks.py`, and T9 deleted the old prefix matcher with the legacy writer. T5 may still need to extend the
  shared predicate for the dispatcher form, but there is now one predicate to update.
- **Claude merge is append + dedupe by full entry, not replace.** Hooks are written via `merge_hooks`
  (`settings_merge.py:505`, called `:705`); `_load_forge_settings` only sets the *source* block (`installer.py:817`).
  Dedup is on the whole canonical entry, so a changed command string is a **new sibling entry that coexists** with the
  old one (double-fire) -- it does not update in place. Every byte change must **unmerge the old tracked entries before
  merging** the new ones (T2, T5, T6).

### 2. `~/.forge/projects.json` schema + canonical path form

T3 defines it (versioned, strictly read on the CLI path, fail-open on the hook path -- see Risks), T4 consumes it (no-op
gate), T5/T6 write to it. One canonicalization rule shared by all: store the resolved canonical string, match exact
strings first, then use `samefile()` only when both paths exist. No unconditional casefold/Unicode fold, because that
would grant trust across distinct case-variant roots on case-sensitive filesystems.

**Format decided (D-T3-c, 2026-07-07): JSON (`projects.json`), not TOML.** The registry is machine-written Forge-owned
durable state, so it follows the house pattern of every sibling registry (`sessions/index.json`, `proxies/index.json`,
`backends/index.json`, `installed.json`) and reuses the shared versioned-JSON read helper, `atomic_write_text`, and the
corrupted-vs-unreadable taxonomy for free. Forge ships **no** TOML writer (`tomllib` is read-only; `codex_hooks.py`
hand-renders only because it merges a codex-owned file). JSON also dissolves T4's "TOML-parse-in-shim tension" (the
no-op gate parses stdlib `json`) and signals "not a hand-edit surface." T7's `.forge/project.toml` stays TOML precisely
because it is the opposite: user-authored opt-in config. The two files now differ by extension *and* number, de-twinning
the lookalike names.

**T4 gate-parity strategy decided (2026-07-08):** the dispatcher uses package-owned, embed-safe stdlib source for the
same three registry rules -- walk-up with `.git` stop, canonicalize, and exact-then-`samefile()` path match -- rendered
into the shim. Behavioral parity tests compare the rendered shim verdict with
`ProjectRegistryStore.lookup_enrolled_root` across symlinks, subdirectories, nested un-enrolled git repos, worktree
`.git` files, missing registries, and corrupt/newer registries. No derived enrollment cache is needed because the JSON
shim benchmark is under budget.

### 3. Forge-binary resolution contract

T4 defines how a hook subprocess finds the real global `forge`; T8 extends it with the dev override; a `FORGE_SESSION` /
managed-session short-circuit is part of the contract (T4). One resolver, one recorded metadata home.

**T4 benchmark/metadata decision (2026-07-08):** choose the stdlib `forge-hook` shim. Benchmark:
`uv run python scripts/experiments/hook-dispatcher/benchmark.py --runs 50 --project-count 40 --depth 5` measured **p50
20.21 ms / p95 22.13 ms** for the shim against a 30 ms p95 no-op ceiling, versus **p50 419.66 ms / p95 611.78 ms** for
the full Forge gate representative. Metadata home is a dedicated `~/.forge/runtime.json` with its own schema version,
not `installed.json`, so dispatcher binary resolution state does not couple to extension tracking. The chosen hyphenated
command means T5 must update presence detection away from the current `"forge hook"` space-token needle.

### 4. Scope-ownership rule: runtime hooks live only at user scope

T5 enforces it, T6 migrates to it, `doctor` (T5/T6) detects violations, and **presence detection must be updated to
match the new command form** (see Risks). **The rule covers hooks only, not `statusLine` (D3): statusLine stays
project-scoped** -- it is a scalar that cannot double-fire, so the user-scope rationale does not apply to it.

### 5. Execution environment (host vs sidecar container)

Host runtime hooks live in `~/.claude`, which the sidecar deliberately does not mount. T10 resolves that boundary by
staging the canonical hook inventory into `<launch-root>/.forge/sidecar-home/settings.json`, mounted as the in-container
user setting `/root/.claude/settings.json`. Commands use the bare `forge hook <handler>` image-PATH form; the project
`.claude` files mounted at `/workspace` remain untouched. The entrypoint merges `apiKeyHelper` into those staged
settings rather than clobbering them, and the sidecar image exposes `/forge/.venv/bin` on PATH.

Hook-generated artifacts remain under the mounted project state. Deferred-work markers use a separately mounted host
queue and serialize host-resolvable roots; the container does not drain them. `FORGE_FORGE_ROOT=/workspace` remains the
in-container root, while internal launcher state carries the host root solely for marker normalization. This is the
shipped seam-5 contract; T2's host-absolute track was skipped and is not part of the runtime design.

## CLI surface (command placement -- decided intentionally)

New commands attach to **existing** groups rather than inventing an `install` group that was deliberately removed
(install lifecycle already moved to `forge extension`; only `forge info` stays top-level -- `install/cli.py:1-5`,
`cli/main.py:415-418`):

- **`forge extension doctor`** (not `forge install doctor`) reports install kind + PATH reachability (T1/T2);
  `forge info` stays the quick top-level dashboard.
- **Migration / cleanup** lands under `forge extension` (the lifecycle group) -- e.g. `forge extension cleanup-project`
  (T6) -- **not** the `hook` group, which is **singular and hidden** (`cli/hooks/_group.py:8`) and exposes only the
  user-facing `enable`/`disable` that T9 reconciles.
- **T5 keeps `forge extension enable --scope user`** for one-time user hook registration; no distinct extension verb is
  added. In-repo auto-LOCAL/project enable stops installing runtime hooks and must point users to
  `forge extension enable --scope user` for the hook install.
- Any genuinely new top-level group needs explicit justification here (`cli_style_guidelines`).

## Sequencing / critical path

- **Incident track:** T1 -> **T2**. Closes exit-127 on the current scope, independent of the model. T2 is not a
  prerequisite for the model (the model replaces its bytes).
- **User-scope-model track:** T1 -> **T3 -> T4 -> T5 -> T6**. Corrected ordering: **T3 (registry schema + read) precedes
  T4** because the dispatcher's shipped no-op gate reads the registry. T4's shim-vs-symlink benchmark therefore measures
  the real gate, not a stub. T5's registration change is where the command *form* changes to the dispatcher shape and
  where detection is updated (gated on T4's benchmark outcome).
- **Cross-cutting:** **T9** (legacy writer) pairs with T2 (byte form) and T6 (cleanup) -- delete it before T6 finalizes
  cleanup, so no untracked writer can resurrect the state T6 removes. **T10** (sidecar resolution) shipped after T5 via
  PR #94 and restores runtime hooks in the container through staged sidecar-user settings.
- **Off-path:** T7 (`required_forge`) is fully independent (a check on project state). Its first guardrail slice
  shipped; the remaining mutator-family sweep is active in `doing/` as
  [`forge_project_compat_mutator_sweep`](../../doing/forge_project_compat_mutator_sweep/card.md) (reclassified
  2026-07-11 as a standalone follow-up, not an epic member -- it touches none of the five seams). T8 (dev override)
  pairs with T4.
- **Adjacent (non-member), sequence-sensitive:**
  [`env_var_interface_boundary`](../../done/env_var_interface_boundary/card.md) declares `FORGE_*` an internal
  launcher-to-runtime contract and strips internal env-var names (notably `FORGE_SESSION`) from normal-flow user
  surfaces. It is deliberately **not** a member (the vocabulary boundary is repo-wide, not epic-owned), but it couples
  one-directionally to this epic: **T4/T5/T6 author new user-facing strings** (dispatcher messages, `doctor`
  registry/cleanup output, migration output), and shipped **T3 already speaks its vocabulary** (`forge_project_registry`
  checklist Phase 3: normal-flow says "managed session"/`--session`, not `FORGE_SESSION`). It landed **before** T4/T5/T6
  via PR #91 (`c593eb66`), so those surfaces should be authored against the shipped boundary; its `test_output.py`-style
  guard catches re-leaks after the fact. Not a blocker for T4's *mechanism* -- only for T4's user-facing *strings*.

## Grounding (verified against code, 2026-07-02)

Line refs are the 2026-07-02 snapshot; T3 Phase 0 re-verified the T3-relevant rows on 2026-07-07, including
`projects.json`, `find_forge_root`, and `FORGE_SESSION`, so see its checklist before relying on exact line numbers.

| Claim                                                                     | Verdict   | Evidence                                                                              |
| ------------------------------------------------------------------------- | --------- | ------------------------------------------------------------------------------------- |
| Hooks are bare `forge hook <name>` (PATH-dependent)                       | Confirmed | `preset.py:53`; `codex_hooks.py:84`; `get_codex_config_path` `codex_hooks.py:106`     |
| statusLine is a bare `forge status-line` command                          | Confirmed | `preset.py:218-222`                                                                   |
| Hooks cover 13 events incl. `PreToolUse:Read` + `UserPromptSubmit`        | Confirmed | `preset.py:47-217` (fire on every Read / every prompt, in every repo at user scope)   |
| Presence detection uses the shared hook-command predicate                 | Confirmed | `install/hooks.py::is_forge_hook_command` / `entry_is_forge_hook`                     |
| A third matcher exists: prefix `startswith("forge hook ")`                | Resolved  | `forge_hook_matcher_consolidation` replaced it with the shared predicate              |
| A second, untracked writer exists: `forge hook enable`/`disable`          | Resolved  | T9 deletes `cli/hooks/install.py`; tracked replacement uses `forge extension enable`  |
| Claude hooks merge append+dedupe by full entry (byte change coexists)     | Confirmed | `merge_hooks` `settings_merge.py:505,705`; source-only load `installer.py:817`        |
| Default scope inside a repo is local/project, not user                    | Confirmed | `installer.py:258-267`, `cli/extensions.py:585-591`                                   |
| Codex cleanup is marker-based; Claude is tracked/per-entry                | Confirmed | markers `codex_hooks.py:56`; Claude `unmerge` via `stable_id` `settings_merge.py:731` |
| Codex trust pinned to command bytes; golden test exists                   | Confirmed | `codex_hooks.py:16-19,66-67`, `test_codex_hooks.py:71`                                |
| Sidecar omits host `~/.claude` and stages hooks in persisted sidecar home | Resolved  | `claude_session.py::_stage_sidecar_hook_settings`; `test_sidecar_hook_inject.py`      |
| `FORGE_SESSION` reaches the hook subprocess env                           | Confirmed | `cli/hooks/commands.py:90,1302`                                                       |
| No `projects.json` / `forge project` group today                          | Confirmed | absent from `src/`; `cli/main.py:402-432` has no `project`                            |
| Project identity is `.claude/` + `.forge/` only (no `project.toml`)       | Confirmed | `design.md:82,92`                                                                     |
| End-user install is `pip install multi-forge` today                       | Confirmed | `README.md:99`; dev uses `uv sync`/`.venv` (`CLAUDE.md:14`)                           |

## Cross-cutting risks (epic-owned)

- **Presence detection can lie after the cutover.** T4's benchmark picked a `forge-hook` shim (hyphen), so the current
  shared predicate still needs an update before T5 flips registration; otherwise `session_lifecycle.py:264` and
  `policy.py:309` could warn incorrectly. T5 owns the detection update.
- **Same-file coexistence, not replacement.** Because Claude hooks merge append+dedupe-by-entry
  (`settings_merge.py:505`), a changed command *adds* a sibling; without unmerge-before-merge, every byte change
  double-fires in the same file. (T2/T5/T6.)
- **Sidecar regression -- resolved by T10.** User-scope-only host hooks are unmounted; fresh canonical hooks stage into
  the persisted in-container user scope and execute through the image PATH.
- **Legacy untracked entries still exist in the wild.** T9 removes the writer, but any entries it already wrote have no
  `installed.json` tracking and must still be handled by T6's value-based cleanup.
- **No-op frequency.** The user-scope dispatcher fires on every `PreToolUse:Read` and `UserPromptSubmit` in every repo
  (`preset.py`); the no-op ceiling (T4) is measured against per-Read / per-prompt frequency, not per-session.
- **Registry read: strict in CLI, fail-open in hook.** A corrupt/newer `projects.json` must fail loudly in the CLI
  (durable state) but must **not** error on every hook subprocess (that bricks the session); the dispatcher's read
  degrades to "not enrolled." (T3/T4.)
- **Two Codex re-trusts across the epic.** T2 changes the command bytes (re-trust #1); the T4/T5 cutover changes them
  again (re-trust #2). Accept as the cost of the D2 split, or skip T2 if the user-scope model ships imminently.
- **Path canonicalization** for symlinked/moved worktrees (T3).
- **Version coupling** -- ACCEPTED (D1); the guardrail (T7) fails clearly rather than isolating versions.

## Resolved questions from current activation

These are no longer open; kept here so the epic card and checklist do not drift.

| Question                                                                                   | Outcome                                                                                                                                              |
| ------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| Ship the interim absolute-command fix, or jump straight to the dispatcher cutover          | **Resolved: skip T2.** Terminal-only launch makes the interim reachability fix unnecessary; reopen only if GUI/Dock/IDE launch becomes supported.    |
| Which absolute path to record: PATH-stable `~/.local/bin/forge` vs churning tool-venv path | **Moot with T2 skipped.** T5 inherits only T2's unmerge-before-merge groundwork; T10 owns sidecar exemption, with T5 carrying the exposure gate.     |
| Trust model: explicit enroll only vs auto-enroll on enable / worktree create               | **Resolved: enroll-on-enable + auto-enroll-on-managed-worktree** with `enrollment_source` provenance.                                                |
| Enrollment surface: new `forge project` group vs `forge extension` family                  | **Resolved: fold into `forge extension enable`.** Project/local enable enrolls the targeted root; user-scope enable enrolls no root by itself.       |
| Whether `FORGE_SESSION` / managed session short-circuits the no-op gate                    | **Resolved: yes.** T3 pins the semantics; T4 owns the dispatcher implementation.                                                                     |
| Dispatcher shim vs absolute-symlink                                                        | **Resolved: shim.** T4 benchmark measured shim p95 22.13 ms under the 30 ms ceiling; full Forge gate p95 611.78 ms.                                  |
| Dispatcher metadata home                                                                   | **Resolved: `~/.forge/runtime.json`.** Keeps runtime binary resolution state separate from strict extension tracking in `installed.json`.            |
| Legacy `forge hook enable`/`disable`: update to the new form or delete                     | **Resolved: delete chosen and shipped in T9.**                                                                                                       |
| Missing `.forge/project.toml` semantics for existing projects                              | **Resolved: missing file is compatible / unconstrained.**                                                                                            |
| Version-check fail-open vs fail-closed matrix per hook type                                | **Resolved:** command paths fail closed; session/context hook readers fail open with diagnostics; policy hooks keep existing fail-mode settings.     |
| `extension enable --scope user` naming                                                     | **Resolved: keep existing verb.** T5 re-semantics hook ownership without adding a new extension verb; project/local completion points to user scope. |
| Explicit project/local `--with hooks`                                                      | **Resolved: hard-reject.** Implicit `standard` modules are filtered by scope; explicit contradictory hook modules fail with an ownership-rule error. |
| In-container command form: bare/image-PATH vs mounting the host dispatcher                 | **Resolved: bare image-PATH form.** T10 stages `forge hook <handler>` and exposes Forge on the sidecar PATH; no host dispatcher mount.               |

## Open questions still owed (each assigned to a member)

| Question                                                     | Owner                                                                    |
| ------------------------------------------------------------ | ------------------------------------------------------------------------ |
| `FORGE_DEV` override vs `uv run forge`-only for contributors | T8 -- **resolved 2026-07-11: `FORGE_DEV` override** (T8 checklist Ph. 0) |
| How much project-local Codex hook policy to keep for teams   | deferred -- out of scope for v1 (noted in T5)                            |

## Out of scope

- Removing PyPI distribution -- the install *target* changes (project venv -> global tool), the *channel* stays.
- A version manager / multi-version isolation -- D1 accepts the coupling.
- Making Forge an importable dependency of managed projects.
- Forking Claude/Codex configuration models.

## Provenance (reviews -> tickets)

**Round 1 (decomposition):** split bug fix vs migration -> D2; benchmark before the registry -> T4 gate; reconcile
`required_forge` -> D1 accepted -> T7; specify resolution + schema -> T4/T3; dev-mode + test -> T8.

**Round 2 (2026-07-02, code-cited findings):**

| Finding                                                                | Resolution                                                                                   |
| ---------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| T2 built a dispatcher nothing invoked; reachability unfixed (High)     | Split out T2 `forge_hook_absolute_command` as the actual byte-change fix; D2 corrected       |
| T4/T3 sequencing contradicted the no-op-gate dependency (High)         | Reordered T3 before T4; benchmark now measures the real gate                                 |
| User-scope command form makes `has_forge_hook` lie (Medium)            | Detection update owned by T5, gated on T4's shim-vs-symlink outcome; T2 stays detection-safe |
| T7 missing-file semantics undefined for existing projects (Medium)     | T7 specifies missing `project.toml` = compatible/unconstrained + test                        |
| T6 conflated Codex marker cleanup with Claude tracked cleanup (Medium) | T6 splits the two mechanisms + legacy/manual fallback                                        |

**Round 3 (2026-07-02, Fable 5 review, verified against code):**

| Finding                                                                                            | Resolution                                                                                  |
| -------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| Sidecar execution unaddressed; host-absolute path dead in-container; user-scope leaves it hookless | New seam 5 + new member T10 (single owner, `FORGE_SIDECAR`-keyed)                           |
| Byte contract narrower than reality: statusLine + legacy writer + matcher drift omitted            | Seam 1 broadened to all registered strings; prep cards collapsed detection to one predicate |
| Claude merge is append+dedupe -> a byte change coexists (double-fire), not replace                 | Seam 1 unmerge-before-merge rule; risk added; T2/T5/T6 acceptance rows                      |
| Second untracked writer `forge hook enable`/`disable` with an incompatible prefix matcher          | T9 deletes the writer; matcher already shared by `forge_hook_matcher_consolidation`         |
| Benchmark rule was a stub target; needs the real trade + no-op frequency + TOML-in-shim tension    | T4 benchmark rewrite                                                                        |
| Registry lifecycle (enroll / backfill / `FORGE_SESSION` / corruption split) underspecified         | T3 lifecycle section                                                                        |
| T3/T7 `project init` dangling reference                                                            | T7 points at T3's committed enrollment surface; T3 commits to owning enrollment             |

**Round 4 (2026-07-02, maintainer findings, verified against code):**

| Finding                                                                                                                                                        | Resolution                                                                                                                 |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| statusLine is a *scalar*: an existing bare value conflicts and **aborts the install** (`installer.py:702,860`; `settings_merge.py:656`), not append+dedupe     | T2 splits the scalar path (unmerge tracked before planning; a manual value still conflicts) from the hook merge; two tests |
| Sidecar mounts host project `.claude` **read-write** at `/workspace` (`container.py:125`, `session_lifecycle.py:497`); an in-place rewrite mutates host config | T10 redesigned around staging/injection; host-bytes-unchanged assertion added                                              |
| T6 "no double-fire window" is unachievable across two files                                                                                                    | Weakened to "no *persistent* double-fire"; least-harmful ordering + report the transient window                            |
| Cards invented `forge install doctor` / `forge hooks cleanup-project`; no `install` group exists and `hook` is singular+hidden                                 | New epic "CLI surface" decision; renamed to `forge extension doctor` / `forge extension cleanup-project`                   |

**Round 5 (2026-07-02, maintainer residual-issues review, verified against member cards):**

| Finding                                                                                                                                                                                                          | Resolution                                                                                                                                                       |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| statusLine unspecified under user-scope: T4 dispatcher is `forge hook`-only, T5 conflated statusLine into "dispatcher hook commands", no gate applies; embedded product question (render in non-enrolled repos?) | **D3**: statusLine stays project-scoped (scalar, can't double-fire, self-gates on `FORGE_SESSION`); seams 1/4 + T4/T5 corrected to hooks-only                    |
| T10 overlay example named only `settings.json`; default scope is LOCAL, so the T2 dead path lives in `settings.local.json`                                                                                       | T10 covers **both** settings files; `--settings` alternative flagged pending Claude-precedence verification; T10 also neutralizes statusLine's mounted dead path |
| T10 open question "does the container need `projects.json` enrollment?" is answerable now                                                                                                                        | Resolved: sidecar always sets `FORGE_SESSION` (`container.py:132`) + always a managed session -> "in-sidecar => always active", enrollment moot; T10 OQ2 closed  |
| T6 risk bullet narrates install-then-remove; T6 scope chose remove-legacy-first                                                                                                                                  | T6 risk realigned to remove-first (transient **hooks-off** window) + one-line least-harmful rationale                                                            |
| T5 open-question candidate `forge hooks install --user` violates the epic CLI-surface rule (new plural group; `hook` is singular+hidden)                                                                         | T5 open question reshaped to a `forge extension`-family name / drop the rename                                                                                   |
| Acceptance-row ownership: T3 held T6's backfill row **and** a fail-open row targeting T4's not-yet-existent `test_hook_dispatcher.py` (T3 precedes T4)                                                           | Existing-install row moved T3 -> T6 (bulk behavior later superseded in Round 6); T3 fail-open row retargeted to `test_project_registry.py`                       |

**Round 6 (2026-07-10, T6 checklist review, verified against the shipped dispatcher):**

| Finding                                                                                                                                                                                                            | Resolution                                                                                                                                                                            |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| User-scope bulk backfill is behavior-changing: `_should_dispatch()` activates an installed dispatcher for an enrolled ambient root, so enrolling before legacy cleanup creates double-fire without a checkout diff | User enable/sync only reports candidates and leaves `projects.json` unchanged; explicit cleanup removes legacy state, verifies user registration, then enrolls the selected root last |
