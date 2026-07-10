# In-container (sidecar) hook resolution

**Epic**: [`docs/board/doing/epic_global_forge_runtime/card.md`](../../doing/epic_global_forge_runtime/card.md)

**Lane**: `done/` (shipped via PR #94 on 2026-07-10 after implementation verification on branch
`forge-hook-sidecar-resolution`). Cross-cutting -- closes the epic's seam 5 member work.

## Goal

Keep Forge runtime hooks working inside Claude sidecar sessions after T5 moved host hook ownership to user scope,
without mounting host `~/.claude` or mutating project `.claude` settings.

## Why

T5 correctly removed runtime hooks from project settings and registered them at host user scope. A sidecar mounts the
project at `/workspace`, but not host `~/.claude`, so that ownership change left in-container Claude hookless. The
sidecar is also a distinct path environment: the development image installs Forge under `/forge/.venv`, which was not on
its default PATH.

The card originally also covered host-absolute project hook bytes from T2. T2 was skipped, so that hypothetical track
never shipped. T10 addresses the live T5 regression and the sidecar-specific PATH and persistence effects discovered
during Phase 0.

## Shipped design

- **One hook inventory, two command renderers.** `install/preset.py` remains the canonical event/matcher/timeout source.
  Host settings render the dispatcher form; sidecar settings render bare `forge hook <handler>` commands.
- **Fresh user-scope staging on every launch.** The host launcher atomically writes the current hook settings, mode
  `0600`, to `<launch-root>/.forge/sidecar-home/settings.json`. The existing mount exposes that file at
  `/root/.claude/settings.json`. Nothing writes to `<launch-root>/.claude`.
- **Entrypoint merge, not clobber.** `docker/entrypoint.sh` atomically merges `apiKeyHelper` into the staged settings
  and preserves hooks. Repeated entrypoint runs are idempotent.
- **Image-resolvable commands.** `docker/Dockerfile.sidecar` adds `/forge/.venv/bin` to PATH, so both bare hook commands
  and a project-scoped `forge status-line` resolve in the development/test image.
- **Host-drainable deferred work.** The host pending-work directory is mounted at `/root/.forge/pending-work`. Sidecar
  hooks retain `/workspace` for in-container artifact access but serialize the host launch root into deferred-work
  payloads. The sidecar never drains these host-addressed markers; the next host CLI startup does.
- **Container root is explicit.** `FORGE_FORGE_ROOT` is `/workspace` in-container. The host root is carried separately
  as internal launcher state for deferred-work path normalization.

Enrollment is intentionally irrelevant in-container: every sidecar launch is a managed Forge session and sets
`FORGE_SESSION`. Mounting the host dispatcher would add host-only runtime metadata and path assumptions without a gate
benefit, so the bare image-PATH form is the narrower contract.

## Scope

**In:** Claude sidecar hook staging, entrypoint merge semantics, image PATH, persisted artifacts, host-drainable pending
work, direct hook commands, and project-scoped status-line resolution.

**Out:** host dispatcher resolution, Codex-in-sidecar (there is no Codex sidecar launch path), proxy/audit plumbing, and
injecting a status line for user-scope-only projects.

## Verification

| Contract                                                                             | Evidence                                                                      |
| ------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------- |
| Sidecar hook tuples match the host preset except for command form                    | `tests/src/install/test_registered_commands_contract.py`                      |
| Settings restage every launch and project `.claude` bytes stay unchanged             | `tests/src/cli/test_session_start_delete.py`                                  |
| Deferred-work markers contain host-resolvable roots and are not drained in-container | `tests/src/cli/test_artifact_hooks.py`, `tests/src/cli/test_startup_queue.py` |
| Forge is on PATH and entrypoint merging is idempotent                                | `tests/integration/sidecar/test_sidecar_hook_inject.py`                       |
| Real Claude hooks persist confirmation/transcript artifacts and host-drainable work  | `tests/integration/sidecar/test_sidecar_hook_inject.py`                       |
| Direct `%` command dispatch and project status line work in-container                | `tests/integration/sidecar/test_sidecar_hook_inject.py`                       |

## Follow-ups and accepted caveats

A project enabled only at user scope still has no project-scoped `statusLine` by D3. T10 preserves that ownership
decision; it guarantees only that an existing project-scoped `forge status-line` resolves inside the sidecar.

- **Launcher/image version skew:** a new host launcher can mount the host queue for an old sidecar image whose hooks
  still serialize `/workspace`. The host no-op `stop` handler deletes its marker, `index` retries before poison
  containment, and detached handoff/shadow workers can launch with an invalid path and fail outside the queue. A
  follow-up should validate path-bearing markers before handler dispatch and emit one clean version-skew diagnostic. The
  inverse skew remains pre-T10 behavior: an old launcher does not mount the queue, so new-image markers stay in the
  disposable container.
- **PATH breadth:** prepending `/forge/.venv/bin` exposes the development image's full virtual environment, including
  its Python and pip, not only the `forge` script. `$FORGE_PYTHON` remains explicit in the entrypoint. If
  container-shell tool resolution later regresses, replace the PATH rule with a dedicated Forge launcher rather than
  debugging it as a hook-staging failure.
