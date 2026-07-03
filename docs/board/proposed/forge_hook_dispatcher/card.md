# User hook dispatcher (user-scope-model mechanism)

**Epic**: [`docs/board/proposed/epic_global_forge_runtime/card.md`](../epic_global_forge_runtime/card.md)

**Lane**: `proposed/`. Depends on `global_forge_install` (a global `forge` to resolve) and `forge_project_registry` (the
no-op gate reads the registry). Part of the user-scope-only model -- **not** the incident fix (that is
`forge_hook_absolute_command`). On the model's critical path.

## Goal

A user-scope hook entrypoint that (a) resolves the real global `forge` from any hook subprocess environment and (b)
no-ops fast in non-Forge repos, so runtime hooks can live only at user scope (`user_scope_hook_ownership`) and fire in
every repository without cost.

## Why

The user-scope-only model registers ONE hook that fires in every repository; it needs a fast no-op gate (skip
non-enrolled repos) and a robust `forge` resolver. This ticket is the mechanism; `user_scope_hook_ownership` flips
registration to user-scope-only, and `forge_hook_migration_cleanup` removes legacy project-scope hooks.

## Design

Two candidate shapes -- **the benchmark below decides:**

1. **Shim** `~/.forge/bin/forge-hook`: a tiny shell/stdlib script that no-op-checks, resolves the real `forge`, and
   `exec`s `forge hook <name>`.
2. **Absolute symlink** to the real `forge`, with the no-op/enrollment gating moved *inside* `forge hook`. Simpler
   conceptually, but pays Python/Forge startup for every hook in every repo.

**Forge-resolution contract** (both shapes honor it):

0. **Managed-session short-circuit**: if `FORGE_SESSION` (or an equivalent managed-session marker) is set, treat the
   session as active and dispatch **even if `cwd` is not enrolled** -- a managed session in a not-yet-enrolled root must
   not lose hooks (contract with `forge_project_registry`). `FORGE_SESSION` is known to reach the hook env
   (`commands.py:1302`).
1. **No-op fast path**: otherwise, if `cwd` is not inside an enrolled project (`forge_project_registry`), exit 0
   **without importing Forge** / pydantic / heavy modules.
2. **Resolve** the real global `forge` from recorded install metadata, then known user tool locations.
3. **Verify** the target is executable before `exec`.
4. **Fail loud** with a diagnostic naming the checked locations when the global `forge` cannot be found.

**Rendered command bytes (epic shared contract):** a literal absolute path, never `~` (hook runners may not
tilde-expand). The string is part of Codex's `trusted_hash` surface, so it is golden-pinned; registration is owned by
`user_scope_hook_ownership`.

**Host-oriented contract.** This resolver assumes the host filesystem/PATH. In-container (sidecar) resolution is a
different environment and is owned by `forge_hook_sidecar_resolution`; this ticket does not handle `FORGE_SIDECAR`.

**statusLine is out of scope (epic D3).** This dispatcher forwards `forge hook <name>` **only**. `forge status-line` is
not a hook and does **not** route through the dispatcher or its no-op gate; statusLine stays project-scoped and keeps
its T2 absolute-path form. If the epic later flips statusLine to user scope, a *separate* gated status-line entrypoint
is required -- it is not this ticket's `forge hook` resolver.

**Metadata home:** record the resolved `forge` binary path durably -- add a field to `~/.forge/installed.json` or a
dedicated `~/.forge/runtime.json` (decided here). Today `installed.json` tracks extensions, not the binary.

## Benchmark (decides the shape)

The choice is a real trade, not a threshold to rubber-stamp:

- **Shim**: wins on no-op latency (no Python/Forge import on the hot path) but adds a second executable to maintain, and
  a `forge-hook` (hyphen) name **breaks substring detection** (see below).
- **Absolute symlink**: simplest and detection-safe (keeps the `forge hook` token), but pays **full Python + Forge
  import on every hook**, including every no-op.

**Measure against worst-case frequency, not per-session.** The user-scope dispatcher fires on every `PreToolUse:Read`
and every `UserPromptSubmit`, in **every** repo (`preset.py:47-217`) -- potentially many times per second during active
editing. Set an **absolute no-op ceiling** (propose ~15-30 ms cold, but justify it against that per-Read cadence, not a
once-per-session cost). At that frequency, paying full Forge startup on every no-op is likely non-viable, so the shim is
the probable answer.

**TOML-parse-in-shim tension.** The no-op gate must read `projects.toml` (`forge_project_registry`). Parsing TOML in a
minimal shim is itself startup cost. If a stdlib `tomllib` shim cannot hit the ceiling, the fallback is a **derived
plain-list cache** (a flat, cheap-to-read file the CLI keeps in sync with `projects.toml`) -- not "fall back to the
slower symlink." Do not resolve a missed shim budget by reintroducing full-startup-per-hook.

Because `forge_project_registry` (schema + read) precedes this ticket, the benchmark measures the **real** gate, not a
stub. Record the chosen shape (and any derived-cache decision) in the epic's shared-contract section.

## Detection interaction (2026-07-02 finding)

The shape choice determines whether substring presence detection breaks. `has_forge_hook` matches the substring
`"forge hook"` (space) (`hooks.py:57,64,69`):

- **Absolute symlink to real `forge`** -> command keeps the `forge hook <name>` token -> detection stays valid.
- **`forge-hook` shim (hyphen)** -> command does **not** contain `forge hook` (space) -> `has_forge_hook` lies, and
  `session_lifecycle.py:264` / `policy.py:309` warn incorrectly.

If the shim shape wins, the detection update (`has_forge_hook` + callers) is **required** and is owned by
`user_scope_hook_ownership`. Flagged here because the benchmark makes the call.

## Grounding (verified 2026-07-02)

- Trust-byte stability is already load-bearing: `codex_hooks.py:16-19,66-67`; golden test `test_codex_hooks.py:71`.
- Hooks fire on every Read / prompt in every repo: 13 event keys incl. `PreToolUse:Read` + `UserPromptSubmit`
  (`preset.py:47-217`) -- the frequency the no-op ceiling is measured against.
- `FORGE_SESSION` reaches the hook env: `cli/hooks/commands.py:90,1302`.
- Detection helpers to build on: `find_forge_installation` `installer.py:279`, `find_forge_root` `context.py:122`.
- Forge does **not** use Claude `--settings` today; Codex `-c` is used only for proxy-provider wiring
  (`session/codex_invoke.py:176-190`) -- launch-time injection is not an existing hook mechanism.

## Risks

- **Reachability across upgrades** (`uv tool upgrade` / `pipx upgrade`) -- resolution must survive a moved binary via
  recorded metadata + fallback, not a hard-coded path.
- **No-op latency** in many non-Forge repos at per-Read frequency (the benchmark gate).
- **Registry read on the hot path** must be fail-open (`forge_project_registry`) -- a corrupt registry cannot error
  every hook.
- **Runtime-agnostic forwarding** -- one dispatcher is invoked by both Claude and Codex with different stdin payloads;
  it forwards to `forge hook <name>` and must not depend on which runtime called it.

## Open questions

- Shim vs absolute-symlink -- **the benchmark decides** (do not pre-commit). The choice also decides whether the
  detection update is needed and whether a derived plain-list cache is introduced.
- Metadata home: extend `installed.json` vs a new `~/.forge/runtime.json`.

## Acceptance tests

| Test                             | Fixture                                 | Assertion                                                                                                                    | Test File                                         |
| -------------------------------- | --------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------- |
| Dispatcher resolves global Forge | dispatcher installed, no venv on `PATH` | hook command exits 0 and dispatches to the global `forge`                                                                    | `tests/src/install/test_hook_dispatcher.py` (new) |
| Outside project no-ops           | cwd outside enrolled roots              | exits 0 without loading project state / importing Forge                                                                      | same                                              |
| Managed session short-circuits   | `FORGE_SESSION` set, cwd not enrolled   | dispatches anyway (managed session keeps hooks)                                                                              | same                                              |
| Corrupt registry fails open      | corrupt/newer `projects.toml`, hook run | dispatcher degrades to not-enrolled, exits 0, does not error (integration; the read-helper unit is `forge_project_registry`) | same                                              |
| Literal absolute path            | user hook install                       | config contains `/abs/home/.forge/bin/...`, not `~`                                                                          | same                                              |
| Stale target resolved            | recorded `forge` path stale             | tries known tool locations or reports an actionable resolution error                                                         | same                                              |
| No-op path is cheap              | non-Forge repo, per-Read cadence        | no-op exits under the benchmark ceiling; no Forge import                                                                     | same (perf assertion)                             |
