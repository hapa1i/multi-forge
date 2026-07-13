# User-scope-only hook ownership

**Epic**: [`docs/board/done/epic_global_forge_runtime/card.md`](../../done/epic_global_forge_runtime/card.md)

**Lane**: `done/` -- shipped via PR #93 on 2026-07-08 and closed out on `main`. Depends on `forge_hook_dispatcher`
(shipped -- the dispatcher mechanism + `render_dispatcher_command`) and `forge_project_registry` (shipped -- the gating
registry). Execution record in [`checklist.md`](checklist.md).

## Goal

Register runtime hooks **only at user scope** (the dispatcher). Project/local scope creates/updates project Forge state
but writes **no** Forge runtime hooks. Update presence detection to the new command form, and detect cross-scope
double-fire.

## Why

One hook source removes double-firing by construction: project `.claude`/`.codex` config no longer owns executable hook
registration. Today the hazard is real and unguarded (see grounding).

## Scope

**In:**

- `forge extension enable --scope user` keeps the existing extension lifecycle surface and registers dispatcher **hook**
  commands (absolute path) in user settings. **statusLine is excluded (epic D3):** it is a scalar that cannot
  double-fire, so the user-scope rationale does not apply -- it stays project-scoped and does **not** move to user
  scope. Other extension modules (commands/agents/skills/permissions) still install at user scope as today.
- `--scope local` / `--scope project` create/update project Forge state and write **no** runtime **hook** block into
  `.claude/settings*.json` or `.codex/config.toml` -- **but still register the project-scoped `statusLine` scalar**
  (`preset.py:218-222`), the one runtime string project scope keeps (D3).
- **Update presence detection to the dispatcher command form (required -- T4 chose the hyphen shim).** Detection is now
  single-sourced in the consolidated token predicate `is_forge_hook_command` (`hooks.py`, semantics: basename `forge`,
  second token `hook`), so a `forge-hook <name>` command no longer matches. Extend that **one** predicate -- plus
  `has_forge_hook`/`has_forge_hooks` and their five callers (`session_manage.py`, `session.py`, `policy.py`,
  `session_lifecycle.py`, `search.py`) -- to recognize the dispatcher form **additively** (keep matching bare
  `forge hook` for the T6 migration window). Do not revert to substring detection.
- Cross-scope double-fire detection in `doctor`/`status` (report + name the cleanup command; cleanup itself is
  `forge_hook_migration_cleanup`).

**Out:** the migration of existing installs (`forge_hook_migration_cleanup`); the already-owned legacy writer cleanup
(`forge_hook_legacy_writer`); in-container hook resolution (`forge_hook_sidecar_resolution`); team checked-in policy
(deferred, see open questions).

## Grounding (verified 2026-07-02)

- Default scope inside a repo is **local/project**, not user: `find_claude_root` returns `LOCAL` for any `.claude` above
  home (`installer.py:258-267`), and `enable_cmd` forces `LOCAL` when a git root is detected
  (`cli/extensions.py:585-591`). So "hooks land in project config" is the *current default*, which this ticket inverts.
- Hooks are written **one scope per run**; the "both scopes" double-fire arises across separate invocations. **No
  cross-scope dedup exists** -- only within-file (`installer.py:735`, `codex_hooks.py:210-237`). This ticket adds the
  detection.
- This was the **only shipped command-byte change**. T2's interim absolute-command proposal was skipped, so this ticket
  changed the scope (project -> user) and form (direct `forge hook` -> absolute dispatcher) in one transition, requiring
  one Codex re-trust.

## Risks

- **Sidecar goes hookless until T10.** User-scope-only writes no project hook block, and the sidecar does not mount host
  `~/.claude` -- in-container Claude would have no hooks unless `forge_hook_sidecar_resolution` handles it. T5 does not
  implement injection; it carries an exposure gate so T10 lands before sidecar users see the change, unless a maintainer
  records an explicit temporary waiver and T5 warns/blocks before sidecar launch.
- **Legacy untracked project hooks remain possible.** `forge_hook_legacy_writer` removes the second writer, but entries
  written before that cleanup still lack tracking and must be handled by `forge_hook_migration_cleanup`.
- Existing project-scope installs need migrating (`forge_hook_migration_cleanup`) -- this ticket changes *new* installs.
- **Team checked-in policy tension**: teams may want project-committed hook policy. Treat that as a separate
  managed/team feature, not the default install path (out of scope for v1).

## Resolved decisions

- Keep `forge extension enable --scope user` with the new hook-ownership semantics; no distinct extension verb.
- Explicit project/local `--with hooks` / `--with codex-hooks` hard-rejects because it contradicts the ownership rule.
- Sidecar injection is entirely T10-owned; T5 carries only the sidecar exposure gate / interim-gap documentation.

## Open questions

- How much project-local Codex hook policy to keep for teams (deferred).

## Acceptance tests

| Test                              | Fixture                                   | Assertion                                                                                                                               | Test File                                |
| --------------------------------- | ----------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------- |
| Project install skips hooks       | `forge extension enable --scope local`    | project `.codex/config.toml` / `.claude/settings*.json` get **no** Forge hook block                                                     | `tests/src/install/test_installer.py`    |
| Project install keeps statusLine  | `forge extension enable --scope local`    | project `.claude/settings*.json` **still** registers the `statusLine` scalar (D3 exception -- not moved to user scope)                  | `tests/src/install/test_installer.py`    |
| User settings are dispatcher-only | `forge extension enable --scope user`     | user config carries dispatcher **hook** commands (absolute path), **no** `statusLine`; commands/agents/skills/permissions still install | `tests/src/cli/test_extension_enable.py` |
| Detection recognizes dispatcher   | dispatcher command installed (shim shape) | `has_forge_hook`/`has_forge_hooks` return True; no false "not installed" warning at session launch / policy enable                      | `tests/src/install/test_hooks.py`        |
| Cross-scope double-fire warned    | legacy user + project Forge hooks present | doctor/status reports double-fire risk and names the cleanup command                                                                    | `tests/src/cli/test_extension_enable.py` |
