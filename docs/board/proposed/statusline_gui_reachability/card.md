# GUI-safe `statusLine` reachability

**Lane**: `proposed/` -- design and probe work, not yet accepted for execution. Standalone follow-up to
[`epic_global_forge_runtime`](../../doing/epic_global_forge_runtime/card.md); it does not keep that epic open.

**Accept when**: a maintainer or user confirms that they actually launch Claude from a GUI, Dock, or IDE and want
Forge's status line supported there. The last confirmed workflow is terminal-only, so this card remains shelf work; a
synthetic minimal-`PATH` reproduction by itself does not justify moving it to `todo/`.

**Origin**: Follow-up to the skipped [`forge_hook_absolute_command`](../forge_hook_absolute_command/card.md) (T2). The
final dispatcher made T2's hook rewrite obsolete, but T2 was also the only card that would have made the project-scoped
`forge status-line` command independent of the launching process's `PATH`.

**Related**:

- [`forge_hook_dispatcher`](../../done/forge_hook_dispatcher/card.md) -- user-owned, absolute hook entrypoint and global
  Forge resolver.
- [`user_scope_hook_ownership`](../../done/user_scope_hook_ownership/card.md) -- runtime hooks are user-scoped;
  `statusLine` remains the deliberate project/local scalar exception.
- [`forge_hook_sidecar_resolution`](../../done/forge_hook_sidecar_resolution/card.md) -- sidecars resolve the current
  bare status-line command through the image `PATH`.
- [`forge_dev_runtime_override`](../../done/forge_dev_runtime_override/card.md) -- ships the precedence contract for
  selecting an editable checkout instead of the recorded global Forge runtime.

## Goal

Make Forge's project/local `statusLine` work when Claude is launched from a GUI, Dock, IDE, or other environment whose
minimal `PATH` cannot resolve the globally installed `forge`, without:

- reviving T2's direct-hook rewrite;
- embedding a machine-specific absolute path in portable project settings;
- breaking status-line execution in sidecars;
- overwriting a user-authored `statusLine`; or
- contradicting T8's shipped global-versus-editable runtime-selection contract.

## Problem

The shipped hook model no longer has the original exit-127 problem: user-scoped Claude and Codex hooks invoke a literal
absolute `<forge-home>/bin/forge-hook` dispatcher path, which resolves the recorded global Forge binary. `statusLine` is
different. The built-in preset still writes:

```json
{
  "statusLine": {
    "type": "command",
    "command": "forge status-line",
    "padding": 0
  }
}
```

That command is intentionally project/local-scoped. It works for terminal-launched Claude because the process inherits
the shell `PATH`; it can fail when launchd supplies only `/usr/bin:/bin:/usr/sbin:/sbin`. `forge extension doctor`
already reports this mechanical condition as `on_path_minimal=false`, but reporting it does not make the status line
reachable.

The old T2 card is not the implementation vehicle. Applying it now would replace dispatcher-backed hooks with direct
`forge hook ...` commands, bypass the project-registry gate, recreate hook-byte migration risk, and require another
Codex trust ceremony. This card addresses only the remaining status-line reachability gap.

## Verified Current Contract

- `src/forge/install/preset.py::_build_builtin_preset` pins `statusLine.command` to bare `forge status-line`; the
  registered-command golden asserts those exact bytes.
- `src/forge/install/installer.py` filters `status-line` into project/local installs and out of user scope. A manual
  conflicting scalar blocks installation unless the user explicitly forces it.
- `~/.forge/claude.preset.json` is user-editable and create-once: `ensure_preset()` never overwrites an existing file.
  Installer loading forcibly refreshes hooks and backfills builtin permissions, but it does not refresh `statusLine`.
  Changing only the builtin preset would therefore leave existing users on the old bare command.
- Host hooks use `render_dispatcher_command(...)`; `statusLine` does not use the dispatcher.
- Sidecars stage only the canonical hook block into their Forge-owned user settings. The project/local `statusLine`
  continues to come from mounted project settings, and the sidecar image makes bare `forge` resolvable on its own
  `PATH`.
- The dispatcher records `forge_binary_path` in `~/.forge/runtime.json`, but the current status-line path does not read
  that metadata before importing Forge.
- `FORGE_SESSION` controls Forge-session discovery only. Without it, the renderer deliberately keeps the ambient bar
  from Claude's stdin and immediate environment (for example path, branch, model, and context); a launcher must not
  treat missing session identity as a reason to suppress all output.
- `status-line` is invoked repeatedly during an interactive session. Any added indirection must be measured as a hot
  render path, not justified by one-time installer latency.

## Decisions Already Made

1. **Do not revive T2.** Runtime-hook command bytes, ownership, gating, and Codex trust are out of scope.
2. **Keep this independent of the global-runtime epic.** The epic's hook/runtime contract is complete; this is a
   narrower launch-environment follow-up.
3. **Do not write a literal home-directory path into project scope.** A value such as
   `/Users/alice/.local/bin/forge status-line` is not a valid team-shared `.claude/settings.json` contract.
4. **Do not silently move `statusLine` to user scope.** That reverses D3 and would run a command in every Claude
   project. It remains a candidate only if a lightweight gate, precedence, and non-enrolled cost are proven.
5. **Do not silently change runtime or compatibility semantics.** Bare `forge status-line` currently follows the
   launching process's `PATH`, which may intentionally select an editable checkout. A recorded-global resolver would
   change that behavior and therefore needs an explicit precedence decision reconciled with T8's shipped contract.
   `statusLine` is read-only and currently has no strict `.forge/project.toml` gate; this card must not add one
   incidentally.

## Design Constraints

### Portable settings bytes

Project-scope settings may be checked in and used by different users, home directories, installation tools, and
platforms. The stored command must therefore be path-portable. Local-scope settings may be machine-specific, but a
scope-dependent byte contract needs an explicit reason and tests; it must not make project and local behavior drift
accidentally.

### Sidecar parity

The same project settings are mounted into `/workspace`. A host-only absolute launcher is dead in the container. The
chosen command must either resolve in both environments or have a proven sidecar override that does not mutate host
project settings. Existing T10 guarantees -- fresh hook staging, image-PATH resolution, and host project bytes unchanged
-- remain binding.

### Scalar ownership and migration

`statusLine` is a scalar, not an append/dedupe hook list. Migration must distinguish:

- a tracked Forge-owned bare value, which `forge extension sync` may replace deliberately;
- a tracked value that the user modified after installation, which sync/disable must preserve;
- the already-current new value, which must be idempotent; and
- a manual/untracked value, which must continue to conflict rather than being overwritten.

Tracking and disable must remove only the value Forge actually installed.

### Preset ownership and migration

The install target and the preset are two separate ownership surfaces. A shipped builtin change does not update an
existing `~/.forge/claude.preset.json`, and an old preset value may be either the untouched released default or an
intentional user choice. Phase 0 must decide how to recognize and migrate the frozen known-released default without
rewriting a customized preset. Cover both the persisted preset and the target settings file; migrating only one leaves
enable/sync behavior inconsistent.

### Process contract

A launcher or shim sits between Claude and `forge status-line`, whose stdin JSON and rendered stdout are the wire
contract. Prefer `exec`-style replacement where possible. Preserve stdin bytes, stdout, stderr, environment, CWD,
signals, and exit status; prove quoting for paths containing spaces. A wrapper that merely produces output on the happy
path is insufficient.

### User-scope no-op behavior

This constraint applies only if candidate 2 moves the scalar to user scope. In that shape, a non-enrolled, non-Forge
project should exit before importing the Forge package. An enrolled Forge project must still dispatch without
`FORGE_SESSION`, preserving the ambient status bar for an unmanaged Claude launch. Candidate 1 is already selected by
project/local settings and must perform binary resolution without a session-identity gate. Benchmark the no-op, ambient,
and managed-session paths separately.

### Diagnostic truth

`forge extension doctor --json` should report status-line reachability separately from hook-dispatcher health. A healthy
dispatcher does not prove the project scalar can launch, and `on_path_minimal=false` alone does not say whether a future
shim makes that irrelevant.

## Phase 0: Probes Before Choosing the Shape

1. **Reproduce the real boundary.** Launch the status-line command with launchd's minimal `PATH` and pin the current
   failure plus the successful terminal control.
2. **Determine command evaluation semantics.** Verify whether Claude expands `$HOME`, `~`, relative paths, and shell
   syntax for `statusLine.command`; do not infer this from hook behavior. Include default and custom `FORGE_HOME`, and
   record whether a GUI launch inherits the custom value.
3. **Determine scalar precedence.** Install distinct user, project, and local `statusLine` values and record which one
   Claude executes. Confirm whether a user-scoped gated shim can coexist with project/local customization.
4. **Verify the working directory.** If a Forge-root-relative launcher is considered, prove the command's CWD for a
   normal project, a nested launch directory, a worktree, and a managed sidecar.
5. **Verify sidecar override options.** Test whether staged user settings or a launcher `--settings` overlay can replace
   only the scalar without changing mounted project files or precedence unexpectedly.
6. **Measure render cost.** Compare the current active path, current minimal-PATH failure, and each viable shim on cold
   start and repeated renders. Record p50/p95 rather than choosing a threshold after implementation.
7. **Verify upgrade stability.** If a user-global path participates, test `uv tool` and `pipx` upgrade behavior without
   resolving the stable launcher symlink to a churning tool-venv target.
8. **Map preset provenance.** Characterize an untouched persisted builtin preset, a customized `statusLine` preset, an
   unchanged tracked target scalar, and a tracked scalar modified after installation. Do not choose migration behavior
   from tracking presence alone.
9. **Record runtime precedence.** With both a global tool and an editable checkout available, prove which binary the
   current terminal path selects and what each candidate would select. Verify any intentional change against T8's
   shipped precedence contract.

## Candidate Shapes

Phase 0 chooses one; this card does not assume that the first plausible command is portable.

1. **Portable Forge-owned shim referenced from project/local settings.** Candidate only if command expansion or a stable
   relative location works on host and sidecar. Its job is cheap binary resolution, not session gating: it must invoke
   the renderer even when `FORGE_SESSION` is absent. Resolve the Forge binary according to an explicit precedence
   contract; dispatcher parity is one possible outcome, not an assumed requirement.
2. **User-scoped gated status-line entrypoint.** Machine-local absolute bytes avoid project portability problems, but
   this reopens D3. Accept only if precedence is deterministic, the no-op avoids a full Forge import in non-enrolled
   projects, and enrolled unmanaged launches still render the ambient bar without `FORGE_SESSION`.
3. **Scope-aware rendering.** Keep project scope portable while allowing a machine-local command at local scope. Accept
   only if sidecar behavior and tracking remain comprehensible; different bytes by scope are a product contract, not an
   installer shortcut.
4. **Diagnostics and launch guidance only.** This is a deliberate no-implementation decision, not fulfillment of the
   goal: keep `forge status-line` unchanged, make doctor report the unsupported launch posture precisely, and document
   terminal launch or user-managed app-environment setup. Forge does not mutate launchd's `PATH`. Prefer this outcome if
   every command-level solution creates a larger portability or sidecar problem than it solves.

## Out of Scope

- Any change to Claude or Codex runtime-hook registration, dispatch, project enrollment, or trust bytes.
- Making arbitrary bare `forge` commands work from GUI-launched processes.
- A general launchd environment manager.
- Changing T8's shipped checkout-local runtime override.
- Moving `statusLine` to global configuration without the Phase 0 precedence and cost evidence.
- Changing status-line content, segments, formatting, or telemetry semantics.

## Risks

- **Portable-config regression:** a machine path committed to project settings works for its author and fails for every
  collaborator.
- **Sidecar regression:** a host-resolvable command replaces the current image-resolvable bare command.
- **Scalar clobber:** sync mistakes a manual `statusLine` for Forge-owned state and overwrites it.
- **Hot-path tax:** a user-scope solution adds process/import latency to every render in every project.
- **Runtime drift:** the status line resolves a different Forge installation than runtime hooks, or silently pins the
  released global tool for contributors expecting editable code.
- **False doctor health:** hook dispatcher health is reported as proof of status-line reachability when the two use
  different commands.

## Acceptance Tests

| Test                          | Fixture                                                                 | Assertion                                                                                                                            | Test File                                                                  |
| ----------------------------- | ----------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------- |
| Minimal-PATH host launch      | command-level fix selected; global tool installed; launchd-style `PATH` | Forge status line executes successfully without shell-profile state                                                                  | `tests/src/install/test_statusline_reachability.py` (new)                  |
| Unsupported posture           | diagnostics-only outcome selected; launchd-style `PATH`                 | probe retains the pinned failure; doctor reports actionable unsupported guidance                                                     | same + `tests/src/install/test_doctor.py`                                  |
| Terminal control              | normal shell `PATH`                                                     | existing terminal behavior and rendered output stay unchanged                                                                        | same + `tests/integration/cli/test_status_line_integration.py`             |
| Portable project bytes        | project-scope install under two different home paths                    | stored project command contains no first user's literal home path and resolves for both                                              | new test + installer integration                                           |
| Manual scalar preserved       | untracked custom `statusLine`                                           | install/sync reports the existing conflict and does not overwrite it                                                                 | `tests/src/install/test_installer.py`                                      |
| Tracked migration             | unchanged Forge-tracked bare command                                    | sync replaces it once; a second sync is byte-idempotent; disable removes only the tracked value                                      | same                                                                       |
| Modified tracked scalar       | tracked old install whose target scalar changed later                   | sync/disable preserves the changed value and reports the ownership conflict                                                          | same                                                                       |
| Persisted preset migration    | untouched old default preset and user-customized preset                 | frozen default follows the chosen migration; custom value remains user-owned                                                         | `tests/src/install/test_preset.py` + installer tests                       |
| Ambient unmanaged render      | Forge-enabled/enrolled project; no `FORGE_SESSION`                      | launcher preserves the current path/model/context status bar rather than exiting blank                                               | new launcher test + `tests/src/cli/statusline/test_statusline_registry.py` |
| User-scope no-op, if selected | non-enrolled, non-Forge project                                         | shim exits before importing Forge; benchmark records p50/p95                                                                         | new test + Phase 0 benchmark                                               |
| Sidecar parity                | project/local status line in managed sidecar                            | command resolves inside the image and host `.claude` bytes remain unchanged                                                          | `tests/integration/sidecar/test_sidecar_hook_inject.py` or new sibling     |
| Worktree/nested CWD           | managed worktree and nested launch path                                 | chosen portable indirection resolves the correct Forge project without CWD guessing                                                  | new integration coverage                                                   |
| Runtime selection contract    | global tool plus editable checkout                                      | selected binary matches T8's shipped precedence contract; no accidental global/editable flip                                         | new test + `tests/src/install/test_hook_dispatcher.py`                     |
| Process propagation           | stdin JSON, stderr/failure, signal, and spaced paths                    | shim preserves bytes, exit status/signals, environment, CWD, and argument quoting                                                    | new launcher contract tests                                                |
| Custom Forge home             | non-default `FORGE_HOME`, terminal and GUI-style envs                   | chosen command either resolves that home or reports the unsupported missing-env posture honestly                                     | new reachability + doctor tests                                            |
| Doctor truth                  | healthy hooks plus broken/healthy status-line variants                  | human and `--json` output report the two reachability facts independently                                                            | `tests/src/install/test_doctor.py`                                         |
| Clean package install         | wheel installed in an isolated tool environment                         | selected launcher/resources work when present; diagnostics-only outcome reports the limitation without editable-checkout assumptions | installer Docker suite / clean wheel smoke                                 |

## Verification Requirements

Because the likely change crosses installer state, project settings, sidecar execution, and packaged runtime files:

- run the focused installer/status-line unit and regression suites;
- run targeted installer and sidecar integration tests through `./scripts/test-integration.sh`;
- run `make pre-commit`;
- build the wheel/sdist and verify from a clean global-tool install;
- verify `forge extension doctor --json`, project/local `forge extension enable`, and user-scope runtime hooks; and
- perform one real GUI/launchd-style smoke test, not only a subprocess with a synthetic `PATH`.
