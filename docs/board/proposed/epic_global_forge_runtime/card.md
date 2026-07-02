# Epic: Global Forge Runtime -- one binary, layered state, user-only hooks

**This is an epic.** It coordinates the shared contract, sequencing, and drift control across the member cards below.
Each member is an independently shippable implementation unit; the epic ships no code itself.

**Lane**: `proposed/` -- not yet scheduled. Members spin out to their own `doing/<slug>/` when picked up; move this epic
to `doing/` when its coordination (or a member gated on sequencing) becomes the active cursor, and add a coordination
`checklist.md` then (`board_contract.md`).

**Origin**: `PreToolUse hook failed: exit 127` investigation, decomposed after four design-review rounds (2026-07-02).
Supersedes the single `proposed/global_forge_runtime/` card, which conflated a hook-reachability bug fix with a large
install/hook-ownership migration. The original card's content is redistributed across the members below.

**Decision direction**: Make Forge a single user/global CLI (PyPI, installed as a tool), keep project authority in
`<repo>/.forge/`, and register runtime hooks only at user scope through a no-op dispatcher that resolves exactly one
global `forge` from any hook environment.

**References**: `src/forge/install/preset.py` (Claude preset hook + `statusLine` commands),
`src/forge/install/codex_hooks.py` (`get_codex_config_path`, managed block markers `:56`, trust-byte pinning),
`src/forge/install/hooks.py` (`has_forge_hook` substring detection `:69`), `src/forge/install/settings_merge.py` (Claude
append+dedupe merge/`unmerge` `:505,:705,:731`), `src/forge/cli/hooks/install.py` (the second, untracked
`forge hook enable`/`disable` writer + prefix matcher), `src/forge/install/installer.py` (scope detection, source-hooks
load `:817`), `src/forge/sidecar/container.py` (sidecar mounts + env), `docs/design_appendix.md` §C.6,
`board_contract.md`.

---

## Members (each is a ticket)

Two linear tracks plus two cross-cutting members. The **incident track** (T1 -> T2) closes exit-127 without the
migration; the **user-scope-model track** (T1 -> T3 -> T4 -> T5 -> T6) is the larger redesign that later supersedes T2's
command bytes. **T9 and T10 are cross-cutting** -- each touches multiple byte-changing members and needs a single owner,
so neither sits on one linear track.

| Label | Card                                                                        | Ships                                                                               | Depends on  |
| ----- | --------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- | ----------- |
| T1    | [`global_forge_install`](../global_forge_install/card.md)                   | Global tool install (`uv tool`/`pipx`) + Day-1 docs + `forge extension doctor`      | --          |
| T2    | [`forge_hook_absolute_command`](../forge_hook_absolute_command/card.md)     | **Reachability fix**: absolute-path hook + statusLine command at current scope      | T1          |
| T3    | [`forge_project_registry`](../forge_project_registry/card.md)               | `~/.forge/projects.toml` trusted-root registry (schema + read + enroll + lifecycle) | --          |
| T4    | [`forge_hook_dispatcher`](../forge_hook_dispatcher/card.md)                 | Dispatcher mechanism + resolver + **benchmark gate** + no-op gate                   | T1, T3      |
| T5    | [`user_scope_hook_ownership`](../user_scope_hook_ownership/card.md)         | User-scope-only registration + detection update + double-fire detection             | T4, T3      |
| T6    | [`forge_hook_migration_cleanup`](../forge_hook_migration_cleanup/card.md)   | No-double-fire migration + backfill + legacy cleanup                                | T5          |
| T7    | [`forge_project_compat`](../forge_project_compat/card.md)                   | `required_forge` fail-clear guardrail + missing-file semantics                      | --          |
| T8    | [`forge_dev_runtime_override`](../forge_dev_runtime_override/card.md)       | Checkout-local forge for Forge contributors                                         | T4          |
| T9    | [`forge_hook_legacy_writer`](../forge_hook_legacy_writer/card.md)           | Reconcile/remove the second `forge hook enable`/`disable` writer + its matcher      | pairs T2/T6 |
| T10   | [`forge_hook_sidecar_resolution`](../forge_hook_sidecar_resolution/card.md) | In-container (sidecar) hook resolution under both byte-change tracks                | pairs T2/T5 |

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

## Shared contract (the epic owns this -- drift control)

The members touch five seams that MUST stay consistent. Drift here is the reason this is an epic:

### 1. All Forge-registered command strings + all three matchers

Not just the Claude/Codex *hook* commands -- **every** string Forge writes into a runtime config is a byte-identity
contract, and byte-identity is the API:

- **Registered strings:** Claude preset hooks (`preset.py`, 13 event keys incl. `PreToolUse:Read`), the Claude
  `statusLine` command `forge status-line` (`preset.py:218-222`), and the Codex managed block (`codex_hooks.py:84`). The
  command string is part of Codex's `trusted_hash` surface (golden-pinned; `codex_hooks.py:16-19,66-67`,
  `test_codex_hooks.py:71`). T2 rewrites all of these to absolute paths; the T4/T5 cutover rewrites them again.
- **Three matchers move in lockstep or they lie:** substring `has_forge_hook` (`"forge hook"`, `hooks.py:69`), the
  specific needle `"forge hook policy-check"` (`policy.py:309`), and the **prefix** matcher `_is_forge_hook_entry`
  (`cmd.strip().startswith("forge hook ")`, `install.py:152`, used by the T9 legacy writer). An absolute path preserves
  the *substring* but breaks the *prefix* -- "detection-safe" is only two-thirds true.
- **Claude merge is append + dedupe by full entry, not replace.** Hooks are written via `merge_hooks`
  (`settings_merge.py:505`, called `:705`); `_load_forge_settings` only sets the *source* block (`installer.py:817`).
  Dedup is on the whole canonical entry, so a changed command string is a **new sibling entry that coexists** with the
  old one (double-fire) -- it does not update in place. Every byte change must **unmerge the old tracked entries before
  merging** the new ones (T2, T5, T6).

### 2. `~/.forge/projects.toml` schema + canonical path form

T3 defines it (versioned, strictly read on the CLI path, fail-open on the hook path -- see Risks), T4 consumes it (no-op
gate), T5/T6 write to it. One canonicalization rule (resolve symlinks + normalize) shared by all.

### 3. Forge-binary resolution contract

T4 defines how a hook subprocess finds the real global `forge`; T8 extends it with the dev override; a `FORGE_SESSION` /
managed-session short-circuit is part of the contract (T4). One resolver, one recorded metadata home.

### 4. Scope-ownership rule: runtime hooks live only at user scope

T5 enforces it, T6 migrates to it, `doctor` (T5/T6) detects violations, and **presence detection must be updated to
match the new command form** (see Risks). The rule covers `statusLine` too, not just hooks.

### 5. Execution environment (host vs sidecar container)

Hook commands are written into project config that rides into the sidecar (`.claude/settings*` under the project,
mounted at `/workspace`), but the container does **not** mount host `~/.claude`, `~/.forge/projects.toml`, or
`~/.local/bin` (`container.py:125-169`); `HOME=/root`, and `FORGE_SIDECAR=1` / `FORGE_LAUNCH_MODE=sidecar` are set
(`:134-136`). Consequences both byte-change tracks hit:

- A host-absolute path (T2) is a **dead path in-container** -- reintroducing exit-127 one level in.
- User-scope-only (T5) leaves in-container Claude with **no hooks** (host `~/.claude` unmounted).

**T10 is the single owner** of in-container resolution, keyed on `FORGE_SIDECAR`; T2 and T5 must *exempt* the sidecar
(emit the bare/image-PATH form there, where `forge` is globally installed in the image).

## CLI surface (command placement -- decided intentionally)

New commands attach to **existing** groups rather than inventing an `install` group that was deliberately removed
(install lifecycle already moved to `forge extension`; only `forge info` stays top-level -- `install/cli.py:1-5`,
`cli/main.py:415-418`):

- **`forge extension doctor`** (not `forge install doctor`) reports install kind + PATH reachability (T1/T2);
  `forge info` stays the quick top-level dashboard.
- **Migration / cleanup** lands under `forge extension` (the lifecycle group) -- e.g. `forge extension cleanup-project`
  (T6) -- **not** the `hook` group, which is **singular and hidden** (`cli/hooks/_group.py:8`) and exposes only the
  user-facing `enable`/`disable` that T9 reconciles.
- Any genuinely new top-level group needs explicit justification here (`cli_style_guidelines`).

## Sequencing / critical path

- **Incident track:** T1 -> **T2**. Closes exit-127 on the current scope, independent of the model. T2 is not a
  prerequisite for the model (the model replaces its bytes).
- **User-scope-model track:** T1 -> **T3 -> T4 -> T5 -> T6**. Corrected ordering: **T3 (registry schema + read) precedes
  T4** because the dispatcher's shipped no-op gate reads the registry. T4's shim-vs-symlink benchmark therefore measures
  the real gate, not a stub. T5's registration change is where the command *form* changes to the dispatcher shape and
  where detection is updated (gated on T4's benchmark outcome).
- **Cross-cutting:** **T9** (legacy writer) pairs with T2 (byte form) and T6 (cleanup) -- decide update-or-delete before
  T6 finalizes cleanup, or the untracked writer resurrects the state T6 removes. **T10** (sidecar resolution) pairs with
  T2 and T5 -- it must land with whichever byte-changing member ships first, or the sidecar regresses.
- **Off-path:** T7 (`required_forge`) is fully independent (a check on project state). T8 (dev override) pairs with T4.

## Grounding (verified against code, 2026-07-02)

| Claim                                                                 | Verdict   | Evidence                                                                              |
| --------------------------------------------------------------------- | --------- | ------------------------------------------------------------------------------------- |
| Hooks are bare `forge hook <name>` (PATH-dependent)                   | Confirmed | `preset.py:53`; `codex_hooks.py:84`; `get_codex_config_path` `codex_hooks.py:106`     |
| statusLine is a bare `forge status-line` command                      | Confirmed | `preset.py:218-222`                                                                   |
| Hooks cover 13 events incl. `PreToolUse:Read` + `UserPromptSubmit`    | Confirmed | `preset.py:47-217` (fire on every Read / every prompt, in every repo at user scope)   |
| Presence detection is a `"forge hook"` substring match                | Confirmed | `hooks.py:57,64,69`; callers `session_lifecycle.py:264`, `policy.py:309`              |
| A third matcher exists: prefix `startswith("forge hook ")`            | Confirmed | `_is_forge_hook_entry` `install.py:139-164` (used by the legacy writer, T9)           |
| A second, untracked writer exists: `forge hook enable`/`disable`      | Confirmed | `cli/hooks/install.py:87,130-134,182` (writes bare hooks to `settings.local.json`)    |
| Claude hooks merge append+dedupe by full entry (byte change coexists) | Confirmed | `merge_hooks` `settings_merge.py:505,705`; source-only load `installer.py:817`        |
| Default scope inside a repo is local/project, not user                | Confirmed | `installer.py:258-267`, `cli/extensions.py:585-591`                                   |
| Codex cleanup is marker-based; Claude is tracked/per-entry            | Confirmed | markers `codex_hooks.py:56`; Claude `unmerge` via `stable_id` `settings_merge.py:731` |
| Codex trust pinned to command bytes; golden test exists               | Confirmed | `codex_hooks.py:16-19,66-67`, `test_codex_hooks.py:71`                                |
| Sidecar mounts project only; no host `~/.claude`/`projects.toml`      | Confirmed | `container.py:125-169`; `FORGE_SIDECAR=1` `:134-136`; `HOME=/root` `:144`             |
| `FORGE_SESSION` reaches the hook subprocess env                       | Confirmed | `cli/hooks/commands.py:90,1302`                                                       |
| No `projects.toml` / `forge project` group today                      | Confirmed | absent from `src/`; `cli/main.py:402-432` has no `project`                            |
| Project identity is `.claude/` + `.forge/` only (no `project.toml`)   | Confirmed | `design.md:82,92`                                                                     |
| End-user install is `pip install multi-forge` today                   | Confirmed | `README.md:99`; dev uses `uv sync`/`.venv` (`CLAUDE.md:14`)                           |

## Cross-cutting risks (epic-owned)

- **Presence detection can lie after the cutover.** If T4's benchmark picks a `forge-hook` shim (hyphen), the
  `has_forge_hook` needle `"forge hook"` (space) stops matching, so `session_lifecycle.py:264` and `policy.py:309` warn
  incorrectly. Separately, the **prefix** matcher `_is_forge_hook_entry` breaks on an absolute path even in T2. T5 owns
  the detection update (gated on T4's shape); T9 owns the prefix matcher.
- **Same-file coexistence, not replacement.** Because Claude hooks merge append+dedupe-by-entry
  (`settings_merge.py:505`), a changed command *adds* a sibling; without unmerge-before-merge, every byte change
  double-fires in the same file. (T2/T5/T6.)
- **Sidecar regression.** Both byte-changing tracks break in-container hooks unless T10 exempts the sidecar: a
  host-absolute path is dead at `/workspace`, and user-scope-only is unmounted. (T10.)
- **A second, untracked hook writer.** `forge hook enable`/`disable` (`install.py`) writes bare hooks with no
  `installed.json` tracking and a *prefix* matcher incompatible with the absolute/dispatcher forms; it can resurrect
  exactly the legacy state T6 cleans. Update-or-delete owed. (T9.)
- **No-op frequency.** The user-scope dispatcher fires on every `PreToolUse:Read` and `UserPromptSubmit` in every repo
  (`preset.py`); the no-op ceiling (T4) is measured against per-Read / per-prompt frequency, not per-session.
- **Registry read: strict in CLI, fail-open in hook.** A corrupt/newer `projects.toml` must fail loudly in the CLI
  (durable state) but must **not** error on every hook subprocess (that bricks the session); the dispatcher's read
  degrades to "not enrolled." (T3/T4.)
- **Two Codex re-trusts across the epic.** T2 changes the command bytes (re-trust #1); the T4/T5 cutover changes them
  again (re-trust #2). Accept as the cost of the D2 split, or skip T2 if the user-scope model ships imminently.
- **Path canonicalization** for symlinked/moved worktrees (T3).
- **Version coupling** -- ACCEPTED (D1); the guardrail (T7) fails clearly rather than isolating versions.

## Open questions still owed (each assigned to a member)

| Question                                                                                   | Owner                                         |
| ------------------------------------------------------------------------------------------ | --------------------------------------------- |
| Ship the interim absolute-command fix, or jump straight to the dispatcher cutover          | T2                                            |
| Which absolute path to record: PATH-stable `~/.local/bin/forge` vs churning tool-venv path | T2                                            |
| Trust model: explicit enroll only vs auto-enroll on enable / worktree create               | T3                                            |
| Dispatcher shim vs absolute-symlink (benchmark decides; also decides the detection update) | T4                                            |
| Whether `FORGE_SESSION` / managed session short-circuits the no-op gate                    | T4                                            |
| Deprecate `extension enable --scope user` vs re-semantic it as dispatcher-only             | T5                                            |
| Legacy `forge hook enable`/`disable`: update to the new form or delete                     | T9                                            |
| In-container command form: bare/image-PATH vs mounting the host dispatcher                 | T10                                           |
| Missing `.forge/project.toml` semantics for existing projects                              | T7                                            |
| Version-check fail-open vs fail-closed matrix per hook type                                | T7                                            |
| `FORGE_DEV` override vs `uv run forge`-only for contributors                               | T8                                            |
| How much project-local Codex hook policy to keep for teams                                 | deferred -- out of scope for v1 (noted in T5) |

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

| Finding                                                                                            | Resolution                                                                      |
| -------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| Sidecar execution unaddressed; host-absolute path dead in-container; user-scope leaves it hookless | New seam 5 + new member T10 (single owner, `FORGE_SIDECAR`-keyed)               |
| Byte contract narrower than reality: statusLine + legacy writer + all three matchers omitted       | Seam 1 broadened to all registered strings + all three matchers                 |
| Claude merge is append+dedupe -> a byte change coexists (double-fire), not replace                 | Seam 1 unmerge-before-merge rule; risk added; T2/T5/T6 acceptance rows          |
| Second untracked writer `forge hook enable`/`disable` with an incompatible prefix matcher          | New member T9 (update-or-delete)                                                |
| Benchmark rule was a stub target; needs the real trade + no-op frequency + TOML-in-shim tension    | T4 benchmark rewrite                                                            |
| Registry lifecycle (enroll / backfill / `FORGE_SESSION` / corruption split) underspecified         | T3 lifecycle section                                                            |
| T3/T7 `project init` dangling reference                                                            | T7 points at T3's committed enrollment surface; T3 commits to owning enrollment |

**Round 4 (2026-07-02, maintainer findings, verified against code):**

| Finding                                                                                                                                                        | Resolution                                                                                                                 |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| statusLine is a *scalar*: an existing bare value conflicts and **aborts the install** (`installer.py:702,860`; `settings_merge.py:656`), not append+dedupe     | T2 splits the scalar path (unmerge tracked before planning; a manual value still conflicts) from the hook merge; two tests |
| Sidecar mounts host project `.claude` **read-write** at `/workspace` (`container.py:125`, `session_lifecycle.py:497`); an in-place rewrite mutates host config | T10 redesigned around staging/injection; host-bytes-unchanged assertion added                                              |
| T6 "no double-fire window" is unachievable across two files                                                                                                    | Weakened to "no *persistent* double-fire"; least-harmful ordering + report the transient window                            |
| Cards invented `forge install doctor` / `forge hooks cleanup-project`; no `install` group exists and `hook` is singular+hidden                                 | New epic "CLI surface" decision; renamed to `forge extension doctor` / `forge extension cleanup-project`                   |
