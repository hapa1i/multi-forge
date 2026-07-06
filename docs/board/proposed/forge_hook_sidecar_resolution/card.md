# In-container (sidecar) hook resolution

**Epic**: [`docs/board/doing/epic_global_forge_runtime/card.md`](../../doing/epic_global_forge_runtime/card.md)

**Lane**: `proposed/`. Cross-cutting -- pairs with `forge_hook_absolute_command` (host-absolute path is dead
in-container) and `user_scope_hook_ownership` (user scope is unmounted in-container). Owns the epic's seam 5.

## Goal

Keep runtime hooks working inside the `--rm` sidecar container under **both** byte-change tracks, by owning a single
in-container resolution rule keyed on `FORGE_SIDECAR`.

## Why

The sidecar is a second execution environment the original design did not account for, and both epic tracks regress it:

- The container mounts the **project** at `/workspace` and sets `HOME=/root`, `FORGE_SIDECAR=1`,
  `FORGE_LAUNCH_MODE=sidecar` (`container.py:125-169`). It does **not** mount host `~/.claude`,
  `~/.forge/projects.toml`, or `~/.local/bin`.
- In-container Claude reads `/workspace/.claude/settings*` (the project config, which rides in via the mount) and today
  resolves bare `forge` from the **image PATH** -- `forge` is installed globally in the container image.

So each byte-change track breaks the container:

- **T2 (`forge_hook_absolute_command`)** writes a **host**-absolute path (e.g. `/Users/alice/.local/bin/forge ...`) into
  the project `.claude/settings*`. That path does not exist at `/root` in the container -> exit-127 one level in.
- **T5 (`user_scope_hook_ownership`)** stops writing project hooks and registers only at host user scope. Host
  `~/.claude` is not mounted -> in-container Claude has **no hooks at all**.

## Design

The project is **bind-mounted read-write** -- `-v {project_dir}:/workspace` (`container.py:125`), and launch pre-creates
the host `<launch_root>/.claude` (`session_lifecycle.py:497`). So `/workspace/.claude/settings*.json` **is the host
file**: editing it in-container mutates host config and persists after the `--rm` container exits. That kills the naive
"entrypoint rewrites the command on the way in" idea. Two consequences shape the design:

- **Never rewrite the mounted host config in place.** In-container resolution must not `sed` `/workspace/.claude/...` --
  that is a host mutation. T10 owns an explicit **staging / injection** mechanism instead: generate a container-only
  settings file and overlay it at the path(s) Claude reads in-container, keyed on `FORGE_SIDECAR`, leaving the host
  bytes untouched.
- **Cover BOTH `settings.json` AND `settings.local.json`.** The default install scope inside a repo is **LOCAL**
  (`cli/extensions.py:585-591`), so in the **T2 world** the host-absolute dead path lands in
  `/workspace/.claude/settings.local.json` -- overlaying `settings.json` alone leaves the `.local` dead path readable
  and exit-127 survives one level in. The `.local` file is the common case, not an edge case.
- **Neutralize statusLine too (epic D3).** statusLine stays project-scoped, so it rides the same mount with the same
  host-absolute dead path (T2). The injected settings must carry a **container-resolvable** `statusLine` (bare /
  image-PATH form), not the host path -- otherwise the status line breaks in-container the same way a hook would.
- **`--settings` alternative -- verify Claude precedence first.** `claude --settings <file>` is unused today
  (`forge_hook_dispatcher` grounding), so a container-only `--settings` path could sidestep the mounted files -- **but
  only if `--settings` *suppresses* the project `settings*.json` rather than layering on top of them.** If it merges,
  the mounted `.local` dead entry still fires and `--settings` solves nothing. Confirm the precedence semantics before
  adopting it; the two-file overlay above is safe regardless.
- **After T5 there is nothing to inherit.** User-scope-only means the host project `.claude` has **no** hook block, and
  host `~/.claude` is not mounted -- so the container must be *given* hooks by injection, not by rewriting an existing
  block. The injected command uses the **bare / image-PATH** form (`forge` is installed globally in the image).
- **Enrollment is moot in-container (resolved).** The sidecar always sets `FORGE_SESSION` (`container.py:132`) and
  always runs a managed session, so "in-sidecar => always active" is the correct gate: host-only `projects.toml`
  enrollment is irrelevant in the container **regardless of command form** -- a dispatcher would short-circuit on
  `FORGE_SESSION` (`forge_hook_dispatcher` step 0), and a bare image-PATH hook has no gate at all. Only the **command
  form** remains an open decision.

The RW mount is exactly why this needs one owner: T2 and T5 **defer** to T10 for anything container-bound, and T10
guarantees the host config is untouched.

## Scope

**In:** decide the in-container command form; ensure the sidecar entrypoint/config produces working hooks under both
tracks; a test that in-container hooks actually fire.

**Out:** host-side resolution (`forge_hook_dispatcher` / `forge_hook_absolute_command`); the container's proxy/audit
plumbing (unrelated).

## Grounding (verified 2026-07-02)

- **Project is bind-mounted read-write**: `-v {project_dir}:/workspace` (`container.py:125`); launch pre-creates the
  host `<launch_root>/.claude` (`session_lifecycle.py:497`). So `/workspace/.claude/settings*.json` is the host file,
  writable from inside the container.
- Env: `FORGE_SESSION`, `FORGE_SIDECAR=1`, `FORGE_LAUNCH_MODE=sidecar` set (`container.py:132-136`); `HOME` is a
  sidecar-specific home, not the host `~` (`:144`).
- Host `~/.claude`, `~/.forge/projects.toml`, and `~/.local/bin` are **not** among the mounts; only a `~/.forge` subset
  is mounted, and only when `proxy_id` is set (`:164`). Sidecar mounts `.claude`/`.forge`, not all of host `~/.forge`
  (`design.md` §7).

## Risks

- **Host-config mutation.** Because `/workspace/.claude` is the live host directory, any in-place rewrite persists to
  the host after the container exits. The injection mechanism must leave host bytes untouched -- asserted explicitly
  below.
- **Two byte forms** (host-absolute/dispatcher vs in-container bare) -- acceptable because the sidecar is ephemeral
  (`--rm`), but the divergence must be intentional and tested, not accidental.
- **Codex-in-sidecar** (if used) inherits the trust-byte concern; note whether Codex runs in the container at all before
  assuming the Claude-only path is sufficient.

## Open questions

- Bare/image-PATH form vs mounting the host runtime (this card decides).

(Resolved: whether the container needs `projects.toml` enrollment -- no; `FORGE_SESSION` is always set in-sidecar, so
"in sidecar => always active" holds. See Design.)

## Acceptance tests

| Test                              | Fixture                                                                                               | Assertion                                                                                                                  | Test File                                            |
| --------------------------------- | ----------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------- |
| Sidecar hooks fire (T2 world)     | sidecar session, absolute-command track, **default LOCAL scope** (dead path in `settings.local.json`) | in-container Claude SessionStart/Stop hooks fire (not exit-127) even though the dead host path is in `settings.local.json` | `tests/integration/docker/test_real_claude_hooks.py` |
| Sidecar hooks fire (T5 world)     | sidecar session, user-scope-only track on host                                                        | in-container Claude still has working hooks (not hookless)                                                                 | same                                                 |
| Sidecar statusLine works          | sidecar session, statusLine host-absolute dead path mounted                                           | in-container status line renders (injected `statusLine` uses the image-PATH form, not the host path)                       | same                                                 |
| Host config untouched             | run a sidecar session, then diff host `.claude`                                                       | host `.claude/settings*.json` (both files) bytes unchanged after the run                                                   | `tests/src/sidecar/test_container.py`                |
| Injected form is image-resolvable | inspect the container-visible hook settings                                                           | injected hook command uses the bare/image-PATH form, not a host path                                                       | same                                                 |
