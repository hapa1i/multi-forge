# User-scope-only hook ownership

**Epic**: [`docs/board/proposed/epic_global_forge_runtime/card.md`](../epic_global_forge_runtime/card.md)

**Lane**: `proposed/`. Depends on `forge_hook_dispatcher` (the dispatcher mechanism) and `forge_project_registry` (the
gating registry). On the user-scope-model critical path.

## Goal

Register runtime hooks **only at user scope** (the dispatcher). Project/local scope creates/updates project Forge state
but writes **no** Forge runtime hooks. Update presence detection to the new command form, and detect cross-scope
double-fire.

## Why

One hook source removes double-firing by construction: project `.claude`/`.codex` config no longer owns executable hook
registration. Today the hazard is real and unguarded (see grounding).

## Scope

**In:**

- `forge extension enable --scope user` registers **only** the dispatcher **hook** commands (absolute path).
  **statusLine is excluded (epic D3):** it is a scalar that cannot double-fire, so the user-scope rationale does not
  apply -- it stays project-scoped and does **not** move to user scope.
- `--scope local` / `--scope project` create/update project Forge state and write **no** runtime **hook** block into
  `.claude/settings*.json` or `.codex/config.toml` -- **but still register the project-scoped `statusLine` scalar**
  (`preset.py:218-222`), the one runtime string project scope keeps (D3).
- **Update presence detection to the dispatcher command form (2026-07-02 finding).** `has_forge_hook` matches the
  substring `"forge hook"` (space) (`hooks.py:57,64,69`). If `forge_hook_dispatcher`'s benchmark picks a `forge-hook`
  shim (hyphen), that needle no longer matches, so `session_lifecycle.py:264` and `policy.py:309` (needle
  `"forge hook policy-check"`) warn incorrectly. Update `has_forge_hook`/`has_forge_hooks` + those callers to recognize
  the dispatcher form. **Conditional**: if the absolute-symlink shape wins, the `forge hook` token is preserved and no
  detection change is needed -- gate this task on the benchmark outcome.
- Cross-scope double-fire detection in `doctor`/`status` (report + name the cleanup command; cleanup itself is
  `forge_hook_migration_cleanup`).

**Out:** the migration of existing installs (`forge_hook_migration_cleanup`); reconciling the second
`forge hook enable`/`disable` writer (`forge_hook_legacy_writer`); in-container hook resolution
(`forge_hook_sidecar_resolution`); team checked-in policy (deferred, see open questions).

## Grounding (verified 2026-07-02)

- Default scope inside a repo is **local/project**, not user: `find_claude_root` returns `LOCAL` for any `.claude` above
  home (`installer.py:258-267`), and `enable_cmd` forces `LOCAL` when a git root is detected
  (`cli/extensions.py:585-591`). So "hooks land in project config" is the *current default*, which this ticket inverts.
- Hooks are written **one scope per run**; the "both scopes" double-fire arises across separate invocations. **No
  cross-scope dedup exists** -- only within-file (`installer.py:735`, `codex_hooks.py:210-237`). This ticket adds the
  detection.
- This is **not** the first command-byte change: `forge_hook_absolute_command` already rewrote the bytes once (absolute
  path). This ticket changes the *scope* (project -> user) and the *form* (to the dispatcher) -- a second command
  change, hence a second Codex re-trust (see the epic's "two re-trusts" risk).

## Risks

- **Sidecar goes hookless.** User-scope-only writes no project hook block, and the sidecar does not mount host
  `~/.claude` -- in-container Claude would have no hooks unless `forge_hook_sidecar_resolution` handles it. Cross-ref,
  not solved here.
- **Second writer resurrects project hooks.** `forge hook enable` still writes bare project hooks; the user-scope
  cutover is undermined until `forge_hook_legacy_writer` reconciles it.
- Existing project-scope installs need migrating (`forge_hook_migration_cleanup`) -- this ticket changes *new* installs.
- **Team checked-in policy tension**: teams may want project-committed hook policy. Treat that as a separate
  managed/team feature, not the default install path (out of scope for v1).

## Open questions

- Keep `forge extension enable --scope user` with new dispatcher-only semantics, or introduce a distinct
  `forge extension`-family verb (e.g. `forge extension install-hooks --user`)? **Not** a new top-level `hooks` group --
  the epic's CLI-surface decision forbids new top-level groups and the existing `hook` group is singular + hidden.
  (Epic-level naming decision, owned here.)
- How much project-local Codex hook policy to keep for teams (deferred).

## Acceptance tests

| Test                             | Fixture                                   | Assertion                                                                                                               | Test File                                |
| -------------------------------- | ----------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | ---------------------------------------- |
| Project install skips hooks      | `forge extension enable --scope local`    | project `.codex/config.toml` / `.claude/settings*.json` get **no** Forge hook block                                     | `tests/src/install/test_installer.py`    |
| Project install keeps statusLine | `forge extension enable --scope local`    | project `.claude/settings*.json` **still** registers the `statusLine` scalar (D3 exception -- not moved to user scope)  | `tests/src/install/test_installer.py`    |
| User install is dispatcher-only  | `forge extension enable --scope user`     | user config carries only the dispatcher **hook** command (absolute path); **no** `statusLine` scalar at user scope (D3) | `tests/src/cli/test_extension_enable.py` |
| Detection recognizes dispatcher  | dispatcher command installed (shim shape) | `has_forge_hook`/`has_forge_hooks` return True; no false "not installed" warning at session launch / policy enable      | `tests/src/install/test_hooks.py`        |
| Cross-scope double-fire warned   | legacy user + project Forge hooks present | doctor/status reports double-fire risk and names the cleanup command                                                    | `tests/src/cli/test_extension_enable.py` |
