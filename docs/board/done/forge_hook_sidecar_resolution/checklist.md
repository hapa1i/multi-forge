# Execution checklist: In-container (sidecar) hook resolution (T10)

Member of [`epic_global_forge_runtime`](../../doing/epic_global_forge_runtime/card.md). Owns seam 5 (host vs sidecar
execution). Card: [`card.md`](card.md). Branch: `forge-hook-sidecar-resolution`.

## Current focus

**Complete.** PR #94 merged 2026-07-10 after unit, real-Claude Docker integration, pre-commit, and GitHub CI
verification. T2 was skipped, so T10 fixes the one live regression from T5: host user-scope hooks are not mounted into
the sidecar. The shipped path stages canonical hooks into the persisted in-container user scope, makes bare `forge`
commands image-resolvable, and routes deferred work back to a host-drainable queue.

## Premise correction (verified against current code 2026-07-09)

| Card claim (2026-07-02)                                                | Current reality                                                                                                                                                                                       | Consequence for T10                                                                                                                   |
| ---------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| T2 writes a host-absolute dead path into project `.claude/settings*`   | **T2 skipped**; hook commands never rewritten to absolute paths                                                                                                                                       | The "dead path in `settings.local.json`" regression does not exist. Drop it.                                                          |
| T5 leaves the container hookless (host `~/.claude` unmounted)          | **Confirmed.** Project `.claude` no longer carries hooks (T5), host `~/.claude` is not mounted                                                                                                        | This is the sole live regression T10 must fix.                                                                                        |
| statusLine rides a host-absolute dead path (needs neutralizing)        | statusLine stays bare `forge status-line` (T2 skipped). Whether `forge` is on the sidecar PATH must be probed from the image, not inferred                                                            | statusLine may still be broken in-sidecar independent of T2 — a PATH problem, not a dead-path problem.                                |
| "forge is installed globally in the container image" → bare form works | The dev image creates an editable install under `/forge/.venv`; final PATH depends on the composed sidecar image                                                                                      | Bare `forge` may not resolve in-container today. Phase 0 confirms with an entrypoint override; command-form decision depends on it.   |
| Injection = "generate a container-only settings file and overlay it"   | A forge-owned, gitignored mount `launch_root/.forge/sidecar-home` is already mounted at `/root/.claude` (`claude_session.py:1251`); the entrypoint already writes `/root/.claude/settings.json` there | Inject into that in-container **user scope**; project `/workspace/.claude` is never touched → "host untouched" holds by construction. |
| `/root/.claude` is ephemeral because the container is `--rm`           | False for sidecar launches: `/root/.claude` is the host-persisted `launch_root/.forge/sidecar-home` mount                                                                                             | Staging must be fresh on every launch; entrypoint merge must be idempotent against prior-run settings.                                |

**Grounding:** the host launcher assembles project, project-state, persisted sidecar-home, and pending-work mounts in
`core/ops/claude_session.py`; `sidecar/container.py` supplies the sidecar/managed-session environment; the entrypoint
merges authentication into staged settings and then execs Claude. The interim hookless-sidecar warning was removed once
the real-Claude integration proved hook effects.

## Decision: in-container command form (resolves the card's one open question)

**Bare / image-PATH form (`forge hook <name>`), and make `forge` resolvable on the sidecar image PATH.** Rejected: mount
the host dispatcher. Rationale:

- The host dispatcher `~/.forge/bin/forge-hook` is a **host artifact absent from the image**; its resolver reads
  host-only `~/.forge/runtime.json` and `~/.local/bin` (`install/hook_dispatcher.py:_resolve_forge`), none mounted →
  mounting it just adds a layer that cannot resolve.
- The dispatcher's no-op gate is **moot in-container**: the sidecar always sets `FORGE_SESSION` and always runs a
  managed session, so "in-sidecar ⇒ always active." A bare `forge hook` has no gate and needs none.
- Bare form is portable to a real global sidecar image (where `forge` is already on PATH) and fixes statusLine for free.

**Phase 0 result:** bare `forge` was absent from the composed image PATH; `/forge/.venv/bin/forge` existed. The sidecar
image now adds `/forge/.venv/bin` to PATH, which is harmless for a distribution image that already exposes `forge`.

## Phase 0 — Empirical grounding (no product code)

- [x] Build the sidecar image and probe PATH with the entrypoint bypassed:
  `docker run --rm --entrypoint /bin/sh forge-sidecar:latest -lc 'echo "$PATH"; command -v forge'` — record exit code,
  PATH, and resolved path. **Assertion:** confirms whether bare `forge` resolves (expected: **not found** in the dev
  image until PATH is fixed). **Observed:** PATH omitted `/forge/.venv/bin`; bare `forge` exited 127 while
  `/forge/.venv/bin/forge --version` succeeded.
- [x] Confirm the live regression: launch a real-Claude sidecar session with **no project hooks** and assert
  SessionStart/Stop hooks do **not** fire today (baseline for the fix). **Assertion:** `confirmed.confirmed_by` is
  absent or not `hook:*`, `confirmed.transcript_path` remains unset, and no transcript artifact is captured. Do **not**
  use `confirmed.claude_session_id` as the signal; it may be pre-seeded at session creation before any hook fires.
  **Observed:** T5 source/config grounding confirmed no project hook block and no host user settings mount; post-fix
  real Claude coverage proves the inverse through hook-authored confirmation and transcript artifacts.
- [x] Confirm Codex is not launched in-sidecar (entrypoint ultimately `exec claude "$@"`; no codex path). **Assertion:**
  grep shows the sidecar path is Claude-only -> the card's Codex-in-sidecar risk is out of scope; record it.
- [x] Enumerate first-order effects of enabling all 13 hooks in-container before wiring them:
  - Stop/StopFailure copies transcript artifacts under `/workspace/.forge/artifacts` (host-persisted via the project
    `.forge` mount) and also enqueues work markers under `get_forge_home()/pending-work`.
  - In sidecar, pending-work currently resolves under `/root/.forge/pending-work` (or the sidecar `FORGE_HOME` when
    set), while standard sidecar mounts persist only `/workspace/.forge` and, for proxied runs, selected
    `/root/.forge/{proxies,audit,costs,usage,telemetry,config.yaml}` paths -- **not** `pending-work`.
  - `policy-check` can dispatch the semantic supervisor from inside the container; `UserPromptSubmit` enables `%`
    commands; team/supervisor hooks may also dispatch subprocess work depending on session policy. **Assertion:** T10
    records either a host-drainable pending-work route with path normalization, or an explicit documented sidecar
    limitation/warning. No silent loss of memory-writer/search-index work is acceptable. **Resolved:** mount the host
    pending-work directory, serialize the host launch root into markers, and prohibit queue drain in the sidecar.
- [x] Record the results in this checklist and, if `forge` is off PATH, lock the `Dockerfile.sidecar` PATH change as the
  chosen mechanism. **Recorded:** `/forge/.venv/bin` is now part of the sidecar image PATH.

## Phase 1 — Inject hooks at the in-container user scope

- [x] Add/reuse a sidecar hook-settings renderer that draws the event inventory from the **single source**
  (`install/preset.py` hook definitions, all 13 events incl. `PreToolUse:Read` + `UserPromptSubmit`) but accepts a
  sidecar command form. For sidecar settings, render the **bare `forge hook <name>` form**, not the dispatcher form and
  not a host path. Do **not** hand-maintain the event list in bash. **Assertions:** compare the full
  `(event, matcher, command, timeout)` tuple set against the host preset golden, with only the command form transformed
  to `forge hook <name>`; preserve absent timeouts as absent and explicit timeouts as exact values; keep the two
  `PreToolUse` `policy-check` entries distinct by matcher (`Write` and `Edit`) and timeout (`60`). Host/user-scope
  preset rendering still uses the dispatcher command form.
- [x] Host launcher (`_launch_claude_sidecar` in `core/ops/claude_session.py`) stages the rendered hooks settings into
  the in-container user scope via the existing `sidecar_home` mount (`launch_root/.forge/sidecar-home`), so it lands at
  `/root/.claude/settings.json` in-container. **Assertion:** nothing is written under `launch_root/.claude` (project
  scope); the staged file is under `.forge/sidecar-home` (gitignored, forge-owned).
- [x] The host launcher **unconditionally overwrites/restages** the Forge-owned sidecar settings file at every launch;
  never skip because `.forge/sidecar-home/settings.json` already exists. **Assertion:** seed a stale prior-run hook
  block in `sidecar-home/settings.json`, launch sidecar, and observe the current tuple set replaces it before Claude
  reads it.
- [x] Change the entrypoint to **merge** its `apiKeyHelper` into the existing `/root/.claude/settings.json` (via
  `$FORGE_PYTHON`), instead of `cat >`-clobbering it (`entrypoint.sh:109-114`). **Assertion:** final in-container
  `/root/.claude/settings.json` contains **both** `apiKeyHelper` and the forge `hooks` block.
- [x] Make the entrypoint merge idempotent when `/root/.claude/settings.json` already contains both a prior-run
  `apiKeyHelper` and hooks. **Assertion:** running the merge twice keeps one helper, one current hooks block, no
  duplicate hook entries, and no stale hook command bytes.
- [x] Update the entrypoint comment that currently says `/root/.claude` files are "container-local, ephemeral with
  `--rm`"; under sidecar they are host-persisted via `.forge/sidecar-home`, so freshness belongs to restaging +
  idempotent merge.
- [x] Retire the interim gate: remove/replace `SIDECAR_RUNTIME_HOOK_WARNING` once hooks fire. **Assertion:** a sidecar
  launch no longer emits the "launch without Forge runtime hooks" warning.

## Phase 2 — statusLine + image PATH

- [x] Phase 0 showed `forge` off PATH; add `/forge/.venv/bin` to `PATH` in `docker/Dockerfile.sidecar` (one `ENV` line).
  **Assertion:** `docker run --rm --entrypoint /bin/sh forge-sidecar:latest -lc 'command -v forge'` exits 0.
- [x] Confirm a **project-scoped** `forge status-line` (D3 keeps statusLine project-scoped) resolves in-container after
  the PATH fix. **Assertion:** in-container status line renders (non-empty, no exit-127) when the project `.claude`
  carries statusLine.
- [x] **Deferred decision (recorded):** a *user-scope-only* enable installs no project statusLine (D3), so such a
  sidecar session has no status line at all. Injecting a container statusLine into the user-scope settings is **out of
  scope for T10** unless review says otherwise — record as deferred, don't silently drop.

## Phase 3 — Tests

Acceptance table (fixture-grounded):

| Test                                       | Fixture                                                                                                              | Assertion                                                                                                                                                                                                                           | Test File                                                                            |
| ------------------------------------------ | -------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| Injected hooks use bare image-PATH form    | sidecar launch, staged user-scope settings                                                                           | full `(event, matcher, command, timeout)` tuple set matches host preset except command form is `forge hook <name>`; never a host abs path or `~/.forge/bin/forge-hook`; host preset still renders dispatcher                        | `tests/src/sidecar/test_container.py` (or new `test_sidecar_hook_inject.py`)         |
| Staged sidecar settings refresh each run   | stale `.forge/sidecar-home/settings.json` from an older Forge version before sidecar launch                          | launcher overwrites/restages current hook tuple set unconditionally; no stale hook command bytes survive                                                                                                                            | `tests/src/sidecar/test_container.py`                                                |
| Host project `.claude` untouched           | sidecar run; git-tracked project `.claude/settings.json` + `.local.json` present                                     | both files byte-identical before/after; hooks written only under `.forge/sidecar-home`                                                                                                                                              | `tests/src/sidecar/test_container.py`                                                |
| Entrypoint merges idempotently             | sidecar image with `/root/.claude/settings.json` already containing hooks + prior apiKeyHelper                       | final settings has **both** `apiKeyHelper` and `hooks`; two merge passes produce no duplicate hooks/helper and no stale command bytes                                                                                               | `tests/integration/sidecar/test_sidecar_hook_inject.py` (or focused entrypoint test) |
| forge resolvable in image                  | sidecar image with entrypoint override                                                                               | `command -v forge` exits 0 in-container                                                                                                                                                                                             | `tests/integration/sidecar/test_sidecar_hook_inject.py`                              |
| Sidecar hooks fire (T5 world)              | sidecar session, user-scope-only hooks on host (unmounted)                                                           | in-container SessionStart/Stop hook effects are observable via `confirmed.confirmed_by`, `confirmed.transcript_path`, and/or captured transcript artifact; do not rely on pre-seeded `claude_session_id` alone                      | `tests/integration/sidecar/test_sidecar_hook_inject.py`                              |
| Sidecar artifacts persist                  | sidecar Stop/StopFailure with transcript path                                                                        | transcript artifact is copied under host-visible `.forge/artifacts/<session>/transcripts/` and manifest `confirmed.artifacts.transcripts` records the repo-relative path                                                            | `tests/integration/sidecar/test_sidecar_hook_inject.py`                              |
| Sidecar pending work is not silently lost  | sidecar Stop/StopFailure with memory/index/shadow-capable session, then host-side pending-work drain                 | marker route is host-persisted and host-drainable with host-resolvable paths, or the implementation emits an explicit documented sidecar limitation/warning instead of enqueueing into an ephemeral queue                           | `tests/integration/sidecar/test_sidecar_hook_inject.py`                              |
| Sidecar policy/direct-command side effects | sidecar session with policy enabled; direct in-container `forge hook user-prompt-submit` invocation for `%` commands | policy-check fail-opens/dispatches under sidecar env as intended; `%` commands remain JSON-safe and do not assume host-only state; do **not** rely on `claude --print` for `UserPromptSubmit` because that hook is interactive-only | `tests/integration/sidecar/test_sidecar_hook_inject.py`                              |
| Sidecar statusLine renders                 | sidecar session, project-scoped `forge status-line` present                                                          | status line non-empty, not exit-127                                                                                                                                                                                                 | `tests/integration/sidecar/test_sidecar_hook_inject.py`                              |

- [x] Unit tests (host-side, no Docker): injected tuple contract + host-untouched + staged-location + unconditional
  restage assertions above.
- [x] Integration tests (Docker real-Claude + direct hook invocation where Claude `--print` cannot fire an event): hooks
  fire + statusLine renders + image PATH probe with entrypoint override + entrypoint idempotence + artifact/pending-work
  side effects + direct in-sidecar `forge hook user-prompt-submit` `%` command check. Per CLAUDE.md, this change touches
  hooks + sidecar, so the **integration tier is required before finishing**, not deferred to closeout. Target the
  sidecar integration file: `./scripts/test-integration.sh tests/integration/sidecar/test_sidecar_hook_inject.py -v`.

## Phase 4 — Design-doc sync + closeout (seam 5)

- [x] `design.md §7` (sidecar mounts + narrow exception): document that sidecar sessions inject Forge runtime hooks at
  the in-container user scope (`/root/.claude`, via the `.forge/sidecar-home` mount) using the bare image-PATH
  `forge hook` form; host project `.claude` is never mutated; statusLine relies on `forge` on the image PATH.
- [x] `design_appendix §C` / `§C.6` records the sidecar exception alongside user-scope ownership (T5).
- [x] Update epic `checklist.md`: record seam 5 verification, the command-form resolution + the retired
  `SIDECAR_RUNTIME_HOOK_WARNING`, and advance the cursor to T6 with T8 parked.
- [x] Add the compact `docs/board/change_log.md` entry (goal / key changes / verification).
- [x] Keep durable rules in normative design docs; do not promote them to `impl_notes.md` without the human review that
  file requires.
- [x] After merge, move card `doing/ -> done/`; repoint the epic forward-link + this card's back-link to `done/`.

## Resolved blockers / deferred item

- **Resolved:** `forge` was absent from PATH; the image now includes `/forge/.venv/bin`.
- **Resolved:** Stop/StopFailure markers use a mounted host queue with host-root path normalization and host-only drain.
- **Follow-up:** validate path-bearing queue markers before dispatch so a new launcher plus stale image produces one
  explicit version-skew diagnostic instead of index retries or detached workers with `/workspace` host paths.
- **Accepted trade-off:** `/forge/.venv/bin` is prepended to the image PATH, so the development venv's Python and pip
  are also preferred in `forge session shell`; `$FORGE_PYTHON` keeps entrypoint interpreter selection explicit.
- **Deferred:** user-scope-only-enable sidecar sessions have no statusLine (D3). Not fixed by T10 unless review requests
  it (Phase 2).
- **Out of scope (verified):** Codex-in-sidecar (no codex launch path in the container), host-side resolution
  (`forge_hook_dispatcher`/`forge_hook_absolute_command`), the container's proxy/audit plumbing.
