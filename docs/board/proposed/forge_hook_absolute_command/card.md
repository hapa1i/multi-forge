# Absolute-path hook command (the reachability fix)

**Epic**: [`docs/board/proposed/epic_global_forge_runtime/card.md`](../epic_global_forge_runtime/card.md)

**Lane**: `proposed/`. Depends on `global_forge_install` -- **for a PATH-stable target to point at**, not just for a
global `forge` to exist. This is the D2 reachability fix: it ships early and closes the exit-127 incident **without**
the scope migration. Split out of `forge_hook_dispatcher` after the 2026-07-02 review found the dispatcher ticket built
a mechanism nothing invoked.

## Goal

Make the installer render every registered Forge command as a **resolvable absolute path** to the global `forge` (e.g.
`/abs/.../forge hook <name>`) at the **current** install scope, so a hook subprocess with a minimal `PATH` no longer
exits 127. No dispatcher, no registry, no scope change.

## Why

The exit-127 repro is a hook subprocess that cannot find bare `forge` on a minimal `PATH`. Global install
(`global_forge_install`) fixes interactive shells but not necessarily a minimal-`PATH` hook subprocess. Rewriting the
registered command to an absolute path closes the incident directly. This is the whole of D2's "reachability before
migration": it is independent of the dispatcher/registry/user-scope model, which later supersedes these bytes.

## Scope

**In:**

- Installer renders `<abs>/forge hook <name>` for both the Claude preset and the Codex managed block, resolving `<abs>`
  from the same install metadata `forge extension doctor` uses.
- **Rewrite `statusLine` too.** The Claude preset also registers `forge status-line` (`preset.py:218-222`) -- a bare,
  PATH-dependent command with the same failure mode. The absolute-path rewrite must cover every registered string, not
  just `hook` entries (epic shared contract, seam 1).
- **Unmerge before merge -- hooks and scalars fail differently.** Claude *hooks* go through `merge_hooks` = append +
  dedupe by full entry (`settings_merge.py:505,705`): re-enabling over a bare install **adds a second entry** and
  double-fires unless the flow `unmerge`s the old tracked entries first (exactly one entry per event). The *statusLine*
  scalar is a different path: `set_scalar` (`settings_merge.py:656`) and the plan step (`installer.py:697-712`) treat an
  existing value that differs as a **conflict**, and `has_conflicts` **aborts the whole install** (`installer.py:860`)
  unless `--force`. So T2 must **unmerge the Forge-owned tracked statusLine scalar before planning** (it is tracked with
  `stable_id` `"statusLine"`), so a tracked bare `forge status-line` is replaced cleanly -- while a **manual, non-Forge
  statusLine still conflicts** (never blanket-`--force` over user config).
- **Keep the `forge hook <name>` token sequence intact** (a space, not `forge-hook`) so the *substring* presence
  detection stays valid (`has_forge_hook` needle `"forge hook"`, `hooks.py:69`).

**Out:** the dispatcher shim (`forge_hook_dispatcher`), the registry (`forge_project_registry`), user-scope-only
(`user_scope_hook_ownership`), legacy cleanup (`forge_hook_migration_cleanup`), the sidecar exemption
(`forge_hook_sidecar_resolution`), the second untracked writer (`forge_hook_legacy_writer`).

## Which absolute path (open question, owned here)

Record the **PATH-stable launcher**, not the churning tool-venv realpath:

- `uv tool install` / `pipx install` place a stable launcher at `~/.local/bin/forge` (expanded to a literal absolute
  path, never `~` -- hook runners may not tilde-expand). The launcher path stays put across `uv tool upgrade` /
  `pipx upgrade`; the installers re-point its internals.
- The tool-venv realpath (e.g. under `~/.local/share/uv/tools/...`) **churns on every upgrade** -- recording it realizes
  the staleness risk on each upgrade.

So point at the launcher. Verify the "launcher survives upgrade" property per installer (uv tool vs pipx) as an
acceptance test rather than assuming it. This is why the `global_forge_install` dependency is about a *stable target*,
not merely a global binary.

## Design notes

- **One command-byte change -> one Codex re-trust event.** The bytes are part of Codex's `trusted_hash`
  (`codex_hooks.py:66-67`), so the golden block changes once; name the re-trust in release notes.
- **Detection is only two-thirds safe.** `/abs/.../forge hook policy-check` still contains the generic substring
  `"forge hook"` and the specific `"forge hook policy-check"` (`policy.py:309`), so `has_forge_hook` and the
  session-launch / policy-enable warnings stay correct. **But** the **prefix** matcher `_is_forge_hook_entry`
  (`cmd.strip().startswith("forge hook ")`, `install.py:152`) does **not** match an absolute path. That matcher belongs
  to the second writer, reconciled in `forge_hook_legacy_writer` -- flag the interaction; do not fix it here.
- **Sidecar exemption is not ours.** A host-absolute path is a dead path at `/workspace` in the sidecar
  (`container.py`); config destined for the container must keep the bare/image-PATH form. That exemption is owned by
  `forge_hook_sidecar_resolution`; this ticket must defer to it, not write host-absolute bytes into container-bound
  config.
- **Superseded, not wasted.** When the dispatcher lands it replaces the **hook** bytes (a second re-trust). Ship this
  ticket if the user-scope model is more than a sprint out; otherwise fold reachability into the cutover and accept that
  the incident stays open until then. (See the epic's "two Codex re-trusts" risk.) **statusLine is the exception (epic
  D3):** it stays project-scoped, so its absolute-path rewrite here is **permanent** -- the dispatcher never supersedes
  it.

## Grounding (verified 2026-07-02)

- Bare command today: `preset.py:53`; statusLine `preset.py:218-222`; Codex `codex_hooks.py:84`.
- Merge is append+dedupe by full entry: `merge_hooks` `settings_merge.py:505,705`; tracked `unmerge` `:731`.
- Detection needle `"forge hook"` substring: `hooks.py:57,64,69`; specific-needle caller `policy.py:309`; presence
  caller `session_lifecycle.py:264`; incompatible prefix matcher `_is_forge_hook_entry` `install.py:139-164`.
- `trusted_hash` covers command bytes: `codex_hooks.py:66-67`; golden test `test_codex_hooks.py:71`.

## Risks

- **Absolute-path staleness** across `uv tool upgrade` / `pipx upgrade` -- mitigated by recording the stable launcher
  (above); if the launcher itself is not stable on some installer, prefer landing the dispatcher (which owns a
  resolution fallback) sooner.
- **Double-fire on re-enable** if unmerge-before-merge is missed (the append+dedupe merge coexists rather than
  replaces).
- **Prefix matcher blind to the new form** -- reconciled in `forge_hook_legacy_writer`, not here.
- **Codex re-trust** on the byte change.

## Open questions

- Ship this interim fix at all, or jump straight to the dispatcher cutover? Depends on the user-scope model's timeline
  (owned here).
- Which recorded path form per installer (launcher vs realpath) -- resolved above; confirm the stable-launcher property
  empirically.

## Acceptance tests

| Test                                | Fixture                                      | Assertion                                                                          | Test File                                  |
| ----------------------------------- | -------------------------------------------- | ---------------------------------------------------------------------------------- | ------------------------------------------ |
| Bare Codex finds Forge (abs path)   | absolute-path command, no venv on `PATH`     | Codex hook exits 0, resolves the global `forge`                                    | `tests/src/install/test_installer.py`      |
| statusLine (tracked) replaced       | prior Forge-tracked bare `forge status-line` | re-plan replaces it with the absolute path, no conflict, install proceeds          | `tests/src/install/test_installer.py`      |
| statusLine (manual) still conflicts | user's own non-Forge `statusLine` value      | install plans a conflict (not silently overwritten without `--force`)              | `tests/src/install/test_installer.py`      |
| Re-enable is idempotent             | enable over an existing bare install         | exactly one entry per event (old tracked entries unmerged before merge)            | `tests/src/install/test_installer.py`      |
| Recorded path survives upgrade      | install, then simulate tool upgrade          | the recorded launcher path still resolves the current `forge`                      | `tests/src/install/test_install_doctor.py` |
| Detection stays true (substring)    | absolute-path command installed              | `has_forge_hook` / `has_forge_hooks` return True; no false "not installed" warning | `tests/src/install/test_hooks.py`          |
| One re-trust only                   | reinstall                                    | command bytes change exactly once (Codex golden updated once)                      | `tests/src/install/test_codex_hooks.py`    |
