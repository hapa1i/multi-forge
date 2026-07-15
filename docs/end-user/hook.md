# Forge Hooks — Lifecycle + Artifacts Guide

**Status:** Implemented (host runtime registrations invoke an absolute `forge-hook <name>` dispatcher, which executes
the hidden `forge hook <name>` handler surface).

Hooks are Forge’s integration layer: they observe Claude Code lifecycle events and write **confirmed facts** and
**artifacts** so sessions are inspectable and auditable.

- Canonical architecture: [`docs/design.md`](../design.md)
- Sessions (unit of work): [`session.md`](session.md)
- Proxies (proxy endpoints): [`proxy.md`](proxy.md)
- Configuration: [`config.md`](config.md)
- Policies (policy commands): [`policy.md`](policy.md)
- Workflows (forge workflow): [`workflow.md`](workflow.md)

---

## What are Forge hooks?

Claude Code and Codex invoke registered hook commands at lifecycle boundaries (SessionStart, PreToolUse, PostToolUse,
Stop, etc.); those commands reach Forge's hook handlers through the host dispatcher or the sidecar image's CLI.

Forge’s deployment model is:

- runtime hooks are configured once at user scope with the hooks-only recipe below
- host hook entries execute the literal absolute Forge dispatcher: `<forge-home>/bin/forge-hook <name>`
- with `FORGE_DEV` present, the dispatcher selects only that checkout's `.venv/bin/forge`; otherwise it resolves the
  launcher from `~/.forge/runtime.json` and then known user-tool directories, without consulting inherited `PATH`
- the dispatcher executes the hidden Forge CLI handler surface: `forge hook <name>`
- sidecar hook entries use the bare image-PATH form `forge hook <name>` instead of the host dispatcher
- Forge does **not** install ad-hoc scripts into `.claude/`

### Why this model

- one upgrade surface (upgrade Forge once)
- no per-project dependency ambiguity (Python/venv drift)
- hooks remain testable Python entrypoints

---

## Hook session resolution

Hooks need to identify the current session to read/write confirmed facts. The resolution order is:

<!-- forge-env-vocab: diagnostic:start -->

1. **`FORGE_FORK_NAME` env var** — set during fork registration (including relaunches)
2. **`FORGE_SESSION` env var** — set by `forge session start` / `forge session resume`
3. **IndexStore UUID lookup** — matches the Claude session UUID against the global index
   (`~/.forge/sessions/index.json`), searching `claude_session_id` only (no previous-ID history)

No CWD-based directory scanning — `FORGE_SESSION` is the authoritative source. Under the 1:1 model, each session has at
most one `claude_session_id`. On `/compact` or `/clear`, the UUID is **overwritten** (not accumulated). The env var
chain typically resolves in step 1 or 2; step 3 is a fallback for edge cases where env vars are not propagated.

<!-- forge-env-vocab: diagnostic:end -->

---

## Ownership rules (normative)

Hooks are intentionally restricted.

### Hooks CAN do

- write **confirmed facts** into the session file (under `confirmed.*`)

<!-- forge-env-vocab: diagnostic:start -->

- Session located via hook resolution: `FORGE_FORK_NAME` -> `FORGE_SESSION` -> UUID lookup

<!-- forge-env-vocab: diagnostic:end -->

- capture **artifacts** (approved plans, transcripts) into `<forge_root>/.forge/artifacts/...`
- apply **session overrides** through direct `%` commands handled by `UserPromptSubmit` (for example `%policy ...`,
  `%cancel-verification`)
- emit machine-readable output for debugging

### Hooks CANNOT do

- mutate session `intent` from lifecycle hooks
- change proxy routing, model selection, or LLM defaults (proxy-owned)
- invent “runtime truth” (runtime truth comes from live proxy introspection in proxy mode)

If you remember one thing: lifecycle hooks are **observers + recorders**. Direct `%` commands are the narrow exception
that may update session overrides.

---

## Installing Runtime Hooks

Install tracked runtime hooks once at user scope, without duplicating project-owned commands, agents, skills,
permissions, or environment settings:

```bash
forge extension enable --scope user --profile minimal --with hooks,codex-hooks --without commands
```

Project/local extension installs still install project-owned settings such as `statusLine`, plus commands, agents,
skills, and permissions, but they no longer write runtime hook blocks:

```bash
forge extension enable                           # Auto-detect scope
forge extension enable --scope local             # Local install → .claude/settings.local.json
```

To remove the user-scope runtime hooks later:

```bash
forge extension disable --scope user
```

> **Note:** Explicit `--with hooks` or `--with codex-hooks` at `--scope local` or `--scope project` is rejected. Runtime
> hooks are user-scoped; project/local installs own statusLine and other project settings.

> **Sidecar sessions:** host user settings are not mounted into the container. Forge stages the current hook inventory
> into its container user settings automatically on every launch, using bare `forge hook <name>` commands resolved from
> the image's `PATH`. This does not modify the project's `.claude/settings*.json` files.

### Using checkout code for live hooks

Contributors can route hook subprocesses through an unreleased Forge checkout without changing global runtime metadata.
Create the checkout environment with `uv sync`, then set `FORGE_DEV` on the command that launches the managed session:

```bash
FORGE_DEV="$PWD" uv run forge session start dev-hooks
```

`FORGE_DEV` must be non-empty and expand to an absolute checkout root. The user-global dispatcher runs exactly
`$FORGE_DEV/.venv/bin/forge`, even when the hook fires from a different enrolled project. It does not infer a checkout
from the hook's working directory. If the value is empty or relative, or the target is missing, non-executable, or
cannot launch, an eligible hook fails with exit 127 instead of silently using the recorded or known-location Forge
launcher. Unset the variable to restore recorded or known-location launcher resolution.

The value is inherited when Claude or Codex starts. Relaunch the managed session after changing or unsetting it; editing
the parent shell's environment does not update an already-running process. `FORGE_DEV` selects the hook executable but
does not bypass a project's `required_forge` pin. Sidecars use the Forge executable bundled in their image, so recovery
there requires an image containing a satisfying version. To inspect the same value explicitly, pass it to doctor:

```bash
FORGE_DEV="$PWD" uv run forge extension doctor
```

Doctor reports the value, exact target, validity, and whether the installed dispatcher is current and executable enough
to honor it. This describes the doctor process's environment; a separately launched hook process may have a different
environment. If a package update leaves the dispatcher stale, run the recovery command doctor reports: user-scope sync
for a tracked user install, or the hooks-only user-scope enable recipe when none is tracked. Host `FORGE_DEV` does not
select code inside sidecar containers.

### Migrating a pre-user-scope installation

After an upgrade, user-scope enable/sync may print tracked roots that still own legacy project/local hooks. It only
reports them; it does not touch those checkouts or enroll them. For each root, review and apply separately:

```bash
forge extension cleanup-project --root /path/to/project
forge extension cleanup-project --root /path/to/project --yes
```

> **Contributor machines:** if Forge exists only in the checkout venv (`uv sync`) and no executable recorded or
> known-location launcher exists, install the persistent editable launcher first (`./scripts/setup.sh --local` from the
> checkout). Cleanup moves eligible host hooks to the user-scope dispatcher; with `FORGE_DEV` unset, they fail with exit
> 127 until one of those normal launchers exists. A valid `FORGE_DEV` explicitly selects the checkout venv instead.

Cleanup removes only canonical tracked entries or exact frozen known-released `forge hook <name>` wrappers. Modified,
mixed, or otherwise ambiguous entries are preserved and make the selected cleanup fail with a manual-cleanup path.
Changed Claude settings and project Codex config files are backed up. The command removes project registrations first,
installs/updates user runtime registrations, checks for duplicate triggers, then enrolls the selected root last. This
ordering avoids creating a new double-fire window; a failure after removal is an explicit temporary hooks-off state, and
the error includes the retry command. A migrated Codex block must be trusted again interactively.

`forge extension doctor` distinguishes the states: cleanup-required registrations are listed with their paths, while
`double_fire_risk` means the same event/matcher/handler is actually registered more than once. If you opt into the
status-line `hooks` segment, `HOOK!` is cleanup-required and `HOOKx2` is a real duplicate.

---

## Core hooks (what they do)

Forge provides these hook handlers (invoked as `forge hook <name>`):

Project-writing lifecycle, policy, team, and Codex hooks resolve every Forge root they may change and run one lenient
compatibility diagnostic per invocation before the first write. An incompatible, malformed, unreadable, or
unsupported-schema `.forge/project.toml` produces one debug-log entry and the hook proceeds; no compatibility text is
added to stdout or stderr, and exit/JSON contracts do not change. Doctor is the user-facing diagnostic surface. This
fail-open posture does not apply to explicit mutations delivered through hooks: mutating `%` commands and WorktreeCreate
fail closed.

### session-start

Purpose: establish confirmed runtime context for the session.

Typical responsibilities:

- record `confirmed.claude_session_id`
- record `confirmed.transcript_path`
- record `confirmed.started_with_proxy` for that Claude launch:
  - `{ base_url, proxy_id?, template?, port? }`

> Note: `proxy_id` is a same-machine convenience; `base_url` is the main runtime truth, and `template` is best-effort
> metadata.

> Note: this does not change routing. It records which proxy the session started under.

### plan-write (PostToolUse:Write)

Purpose: detect plan file writes and keep a pointer to the latest plan draft.

- if a file under `.claude/plans/` is written, update `confirmed.latest_plan_path`

### exit-plan-mode (PreToolUse:ExitPlanMode)

Purpose: capture an **approved** plan snapshot on the approval boundary.

- snapshot the approved plan into:
  - `<forge_root>/.forge/artifacts/{session_name}/plans/`
- append an entry to `confirmed.artifacts.plans[]`

### stop (Stop)

Purpose: persist a transcript copy at stable boundaries and enqueue deferred work.

- copy the transcript into:
  - `<forge_root>/.forge/artifacts/{session_name}/transcripts/{session_id}.jsonl`
- append an entry to `confirmed.artifacts.transcripts[]`
- enqueue search indexing work for `<forge_root>/.forge/search-index/`
- enqueue memory-writer marker (if `memory.auto_update.enabled`). See [`memory.md`](memory.md).

The later workers enforce compatibility independently. An index or policy-shadow marker refused by the pin follows the
normal bounded retry path and moves to `~/.forge/pending-work/failed/` at the retry limit; the foreground command that
drains the queue still succeeds. A detached memory writer records a `project_compatibility_refused` skip and exits 0
without dispatching or writing project files.

### pre-compact (PreCompact)

Purpose: capture the full, uncompacted transcript before compaction.

- copies the transcript to
  `<forge_root>/.forge/artifacts/{session_name}/transcripts/{session_id}_pre-compact_{timestamp}.jsonl`
- records the snapshot in `confirmed.compaction.transcript_snapshots[]`
- increments `confirmed.compaction.compact_count`
- always exits 0 (never blocks compaction; `CLAUDE_CODE_AUTO_COMPACT_WINDOW` handles compaction window sizing)

This is the canonical compaction snapshot. The SessionStart rollover (`source="compact"`) serves as fallback for
`/clear` events and defense-in-depth.

### post-compact (PostCompact)

Purpose: record compaction metadata after compaction completes.

- updates `confirmed.compaction.last_compact_at` and `last_compact_type`
- side-effect only (cannot block compaction)

### worktree-create (WorktreeCreate)

Purpose: replace Claude Code's default worktree creation with auto-install of Forge extensions.

- strict-checks the source Forge root before `git worktree add`
- creates a git worktree via `git worktree add`
- maps a nested Forge root to the same checkout-relative path in the target and strict-checks it before config copy,
  project enrollment, extension install, or session writes
- rolls back the new checkout and newly created branch if the target pin refuses the operation; if Git cannot complete
  cleanup, stderr reports the incomplete rollback
- never copies `.forge/project.toml`; runtime-config copy excludes it, so a tracked target pin may differ from the
  source
- best-effort installs project-owned Forge extensions (status line, skills, and other assets) in the new worktree; the
  existing user dispatcher supplies runtime hooks
- prints the absolute worktree path to stdout (Claude Code reads this)
- exits 1 on failure (worktree creation fails)

**Note:** Once installed, this hook replaces Claude Code's default git worktree behavior and `.worktreeinclude`
handling.

### subagent-stop (SubagentStop)

Purpose: track subagent activity in session confirmed state.

- records `agent_type`, `agent_id`, `agent_transcript_path`, and a truncated `last_assistant_message` preview
- increments `confirmed.subagents.total_count` and `by_type` counters
- observe-only (phase 1) — always exits 0

### policy-check (PreToolUse:Write/Edit)

Purpose: evaluate TDD/policy bundles before file writes.

- enforces policy bundles (TDD, coding standards) when enabled via `forge policy enable`

### codex-policy-check (Codex PreToolUse:apply_patch)

Purpose: the same policy enforcement for **Codex** sessions (`forge session start --runtime codex`).

- evaluates each file operation in a Codex `apply_patch` action against the session's policy bundles and supervisor;
  shell (`Bash`) actions pass through unevaluated
- a block is delivered as Codex's deny JSON on stdout (not an exit code); an allow produces no output
- non-Forge Codex sessions (no resolvable Forge session) pass through as a fully silent allow
- **registered by `forge extension enable --scope user`** (codex-hooks module, standard profile): the installer writes a
  managed block into `$CODEX_HOME/config.toml` and preserves an existing file's mode during atomic merge/remove.
  Project/local installs do not write runtime Codex blocks. Skipped with a notice when `codex` is not installed.
- registration alone is inert: complete Codex's one-time trust ceremony (run `codex` interactively and grant trust when
  prompted) — Codex hooks only fire from trust-enrolled registrations

### codex-session-start (Codex SessionStart)

Purpose: deliver the transfer handoff to a Codex session as `additionalContext` — the hook half of
`forge session start --runtime codex --context-delivery hook`.

By default the curated transfer rides the first `codex exec` prompt, so no Codex hook setup is required. With
`--context-delivery hook`, Forge stages the handoff under the session directory and this hook injects it at SessionStart
instead; after the turn, Forge reconciles the hook's delivery receipt into the session manifest
(`confirmed.codex.context_delivery`). If the hook never fired (not enrolled), the command exits 1 and tells you so — the
first turn ran without the parent context.

- every other invocation is silent (no stdout/stderr). In a **managed** session with nothing staged (interactive starts,
  resume turns) the hook still records a small observation receipt under the session directory — that is how enrolled
  homes capture the thread id of interactive sessions exactly. Non-Forge Codex sessions see zero writes.
- **registered by `forge extension enable --scope user`** (codex-hooks module, with `codex-policy-check`, as a managed
  block in the user Codex config) — then complete the one-time trust ceremony (run `codex` interactively and grant
  trust). To register manually instead, add this to your Codex `config.toml`:

```toml
[[hooks.SessionStart]]
[[hooks.SessionStart.hooks]]
type = "command"
command = "/absolute/path/to/forge-home/bin/forge-hook codex-session-start"
timeout = 60
```

Use the exact absolute dispatcher path that Forge registers for your install; changing the command bytes requires a new
Codex trust ceremony.

- the installer detects a pre-existing manual registration and leaves it alone (it never double-registers; a *partial*
  manual registration is reported as a conflict to resolve by hand)

- **do not rename or alter the registered command string**: Codex trust hashes the registration definition, so any
  change to the `command` value invalidates the enrollment and the hook silently stops firing

### read-hygiene (PreToolUse:Read)

Purpose: silently fix Read calls to skill instruction files that include extra parameters.

Models sometimes add `offset`, `limit`, or `pages` when reading skill instruction files, violating the "file_path only"
contract in SKILL.md. This hook detects these calls and uses Claude Code's `updatedInput` capability to strip the extra
parameters before the Read executes — zero token cost, no retry needed.

**Scope:** Only targets instruction files matching `{mode}.md` or `{mode}-{family}.md` (e.g., `code.md`,
`docs-openai.md`). Does not affect QA checklists, report templates, or other skill resources.

### user-prompt-submit (UserPromptSubmit)

Purpose: dispatch direct user commands (`%` commands). See [In-session commands](#in-session-commands--commands) below
for the full list.

---

## In-session commands (% commands)

Type these directly in the Claude prompt to interact with Forge without switching to a terminal. Commands starting with
`%` are intercepted by the `UserPromptSubmit` hook and handled by Forge.

| Command                                      | Effect                                                    |
| -------------------------------------------- | --------------------------------------------------------- |
| `%h` / `%help`                               | Show command help                                         |
| `%config`                                    | Show effective runtime config (read-only)                 |
| `%session list`                              | List sessions                                             |
| `%plan`                                      | Show the current session's recorded plan file path        |
| `%proxy list`                                | List proxies (read-only)                                  |
| `%proxy show <id>`                           | Show proxy details (read-only)                            |
| `%proxy audit show\|diff [id]`               | Recent audit metadata / wire changes (read-only)          |
| `%policy status`                             | Show policy config and state                              |
| `%policy enable --bundle tdd [--permissive]` | Enable policy enforcement                                 |
| `%policy disable`                            | Disable all policies                                      |
| `%policy check [--staged] [--bundle <name>]` | Evaluate git diff against policies (diagnostic, not gate) |
| `%cancel-verification`                       | Bypass active verification loop                           |

> **Note:** `%policy enable/disable` applies session overrides that persist until changed or reset. The CLI
> `forge policy enable/disable` mutates session intent. `%policy check` is read-only — it evaluates but doesn't change
> enforcement state.

> **Compatibility:** Mutating `%policy` forms, including supervisor set/on/off/remove/reload/cascade, and
> `%cancel-verification` strict-check the resolved session's Forge root. A refusal is returned through the normal
> `{"decision":"block"}` response with recovery and writes nothing. Read-only `%policy status`, `%policy check`, and
> bare `%policy supervisor` remain available.

> **Note:** `%` commands only work in interactive Claude sessions. They do NOT fire in `claude --print` mode.

---

## Artifacts: where they go

Artifacts are stored under the session's **Forge project root** (`forge_root`). For root-level
`session start --worktree`, that is usually the original repo root; for `fork --worktree` and `fork --into`, it is the
destination worktree's Forge root.

- `<forge_root>/.forge/artifacts/{session_name}/plans/`
- `<forge_root>/.forge/artifacts/{session_name}/transcripts/`

Paths stored in the session file should be forge-root-relative for portability.

---

## Debugging hooks

### “Hooks aren’t firing”

Checklist:

- run `forge extension doctor` and resolve any listed `cleanup-project` action
- follow any `hook_dispatcher` recovery advice from doctor
- confirm runtime hooks in user settings invoke the expected absolute `<forge-home>/bin/forge-hook` path
- confirm the dispatcher can resolve an executable launcher from `runtime.json`, a known user-tool directory, or a valid
  `FORGE_DEV`; inherited `PATH` is not the host runtime-hook resolver
- check Claude Code hook logs (or Forge’s emitted JSON output)

### "Hooks fired but session file didn't update"

- hooks only write `confirmed.*`

<!-- forge-env-vocab: diagnostic:start -->

- confirm `FORGE_SESSION` env var is set (should be set by `forge session start` / `resume`)
- if env var is missing, confirm the session exists in the IndexStore (`~/.forge/sessions/index.json`)

<!-- forge-env-vocab: diagnostic:end -->

- confirm the session manifest exists at `<forge_root>/.forge/sessions/<name>/forge.session.json`

### "Hooks changed my model / routing"

They shouldn't. If this appears to happen:

- verify you didn't change `ANTHROPIC_BASE_URL` / proxy base URL between runs
- verify which proxy the session started under (`confirmed.started_with_proxy`)
- in proxy mode, compare against live runtime truth (`GET /`)

---

## Advanced

### Hook resolution mechanism

<!-- forge-env-vocab: diagnostic:start -->

See [Hook session resolution](#hook-session-resolution) for the three-step resolution chain (`FORGE_FORK_NAME` ->
`FORGE_SESSION` -> UUID lookup).

<!-- forge-env-vocab: diagnostic:end -->

### Hook handler group

The dispatcher invokes the hidden `forge hook ...` handler group (group name `hook`, not `hooks`). You can run handlers
directly for focused diagnostics:

```bash
forge hook session-start       # SessionStart handler
forge hook stop                # Stop handler
forge hook policy-check        # PreToolUse:Write/Edit handler (Claude)
forge hook codex-policy-check  # PreToolUse:apply_patch handler (Codex; installed to Codex config)
forge hook codex-session-start # SessionStart transfer delivery (Codex; installed to Codex config)
```

### Files to inspect (debugging)

| File                                                     | Purpose                                                    |
| -------------------------------------------------------- | ---------------------------------------------------------- |
| `<forge_root>/.forge/sessions/<name>/forge.session.json` | Session manifest with `confirmed.*` facts                  |
| `~/.forge/sessions/index.json`                           | Global session index (UUID lookup)                         |
| `~/.claude/settings.json`                                | Current user-scoped runtime hook registrations             |
| `<forge_root>/.claude/settings*.json`                    | Project state; Forge hook entries mean cleanup is required |
| `<forge_root>/.forge/artifacts/`                         | Captured plans and transcripts                             |

### Gotchas

<!-- forge-env-vocab: diagnostic:start -->

| Trap                    | Explanation                                                                                                                |
| ----------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| "FORGE_SESSION not set" | Hooks fall back through `FORGE_FORK_NAME` and UUID lookup; check `~/.forge/sessions/index.json`                            |
| "Hooks not firing"      | Use `forge extension doctor`; host hooks use the absolute dispatcher, not inherited `PATH`                                 |
| "Wrong settings file"   | Runtime hooks live in user settings; project/local settings own project assets and may contain pre-migration cleanup state |
| `HOOK!` / `HOOKx2`      | `HOOK!` means cleanup required; `HOOKx2` means an actual duplicate trigger                                                 |

<!-- forge-env-vocab: diagnostic:end -->
