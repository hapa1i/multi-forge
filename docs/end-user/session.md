# Forge Sessions — Session Manager Guide

**Status:** Implemented for session management (naming, worktrees, artifacts). Updated here to match the **Session vs
Proxy** regime in `docs/design.md`.

- Canonical architecture: [`docs/design.md`](../design.md)
- Proxies (proxy endpoints): [`proxy.md`](proxy.md)
- Configuration system: [`config.md`](config.md)

---

## What a session is (and is not)

A **session** is a human unit of work with a **1:1 relationship** to a Claude process invocation:

- named session identity (portable name)
- worktree association (optional for parallel work — multiple sessions can also run in the same directory)
- session manifest (`<forge_root>/.forge/sessions/<name>/forge.session.json`) storing intent/overrides/confirmed facts,
  including relaunch preferences
- artifacts (approved plans, transcripts)
- exactly one `claude_session_id` (pre-seeded by `forge session start` and by transfer/fresh children, then validated by
  the SessionStart hook; only a native `--fork-session` lets Claude mint it, which the hook records)

**1:1 invariant:** Each Forge session maps to one Claude process invocation. `forge session start` **pre-seeds**
`claude_session_id` (the CLI generates it and imposes it via `--session-id`; the SessionStart hook validates it), so a
non-null value does **not** by itself mean the session ran — "used" means it has hook-confirmed or transcript-backed
evidence (a `--no-launch` session carries a pre-seeded UUID but never launched). `forge session resume` **reattaches**
to the same conversation by default; `resume --fresh` derives a **child session** (a fork with lineage). Related
sessions are grouped by lineage (`parent_session`), not by UUID accumulation.

A session is **not** a proxy routing identity.

- Proxy routing defaults are **proxy-owned**.
- Sessions cannot override proxy-owned routing/hyperparams.

---

## Session state: what files exist

- Session manifest (per Forge project): `<forge_root>/.forge/sessions/<name>/forge.session.json`
- Global session index: `~/.forge/sessions/index.json` (name, forge_root, project_root, last-used-at, UUID)
- Active-session registry: `~/.forge/sessions/active.json` (runtime-only live launches; self-heals stale entries)

> **Session identity:** Hooks use Forge launch env vars only. Resolution order is: `FORGE_FORK_NAME` -> `FORGE_SESSION`
> -> IndexStore UUID lookup. No CWD-based directory scan.

Multiple sessions can coexist in the same Forge project, each with its own directory under
`<forge_root>/.forge/sessions/`.

The session file includes hook-confirmed facts such as:

- `confirmed.claude_session_id` (launch-owned: pre-seeded by `forge session start` and by transfer/fresh children, then
  validated by the SessionStart hook; only a native `--fork-session` lets Claude mint it, which the hook records)
- `confirmed.transcript_path`
- `confirmed.started_with_proxy` (snapshot from the SessionStart hook; `{base_url, proxy_id?, template?, port?}`)

> `proxy_id` is a same-machine convenience; `base_url` is the primary runtime truth, and `template` is best-effort
> metadata.

---

## Launch through Forge (recommended)

Always launch Claude through Forge to get session tracking:

**Two launch paths exist:**

**Session-managed launch** (`forge session start`, `forge session resume`) — full lifecycle tracking:

```bash
forge session start                                            # Auto-named, direct to Anthropic
forge session start my-feature                                 # Named, direct to Anthropic
forge session start my-feature --proxy openrouter-anthropic    # Named + proxy routing
```

This gives you: named session with manifest, hook-driven plan snapshots, transcript capture, status line, session
resume, search, and the memory writer. Requires `forge extension enable` first (creates `.forge/`).

**Bare launch** (`forge claude start`) — proxy routing only, no session state:

```bash
forge claude start --proxy openrouter-anthropic
forge claude start --no-proxy
```

No `FORGE_SESSION` set, no session manifest, no artifacts. Session-specific hooks and status line are no-ops. Does not
require `.forge/`. Use `forge session start` for managed sessions.

**Bare Codex proxy launch** (`forge codex start --proxy`) — Responses proxy routing only, no session state:

```bash
forge codex status
forge codex start --proxy codex-responses-local
forge codex start --proxy my-codex-proxy --sandbox read-only -- -m gpt-5.5
```

This opens the foreground Codex TUI through a Responses-capable Forge proxy. It creates no Forge session, requires no
`.forge/`, writes no `confirmed.codex`, and is not resumable through `forge session resume`. Forge configures Codex with
argv `-c` provider overrides instead of editing Codex's `config.toml`, and the child env is scrubbed so native Codex /
OpenAI account variables and inherited Forge session or run-tree identity do not leak into the sessionless launch. Use
`forge session start --runtime codex` when you want a managed Codex session with recorded thread state.

Running `claude` directly bypasses both paths.

---

## Core commands (cheat sheet)

> **Alias:** `forge sess` is a shorthand for `forge session`.

### CLI Reference

```bash
# Bare launch (proxy routing only, no session state)
forge claude start --proxy <proxy_id>
forge claude start --no-proxy

# Bare Codex launch (Responses proxy routing only, no session state)
forge codex status
forge codex start --proxy codex-responses-local
forge codex start --proxy <proxy_id> --sandbox read-only -- -m gpt-5.5

# Create/start managed session (full lifecycle tracking)
forge session start [name] \
  [--proxy <proxy_id>] [--no-proxy] \
  [--worktree/-w] [--branch/-b <branch>] \
  [--incognito/-i] \
  [--system-prompt/-s <text>] \
  [--system-prompt-file/-S <path>] \
  [--sidecar|--host-proxy] [--mount <host:container>] [--image <name>] \
  [--no-launch]

# Resume an existing session (default: reattach; --fresh: context assembly)
forge session resume <name>
forge session resume <name> --fresh

# Derive a fresh child session (PARENT optional; interactive picker)
forge session resume [parent] --fresh \
  [--child-name/-n <child_name>] \
  [--strategy/-s minimal|structured|full|ai-curated] \
  [--depth/-d <n>] \
  [--resume-mode native|transfer] \
  [--proxy <template>]

# Codex-runtime session (interactive TUI by default; --task runs headless `codex exec` turns)
forge session start [name] --runtime codex \
  [--resume-from <parent> [--task "<first task>"]] \
  [--strategy minimal|structured|full|ai-curated] [--depth <n>] \
  [--sandbox read-only|workspace-write|danger-full-access] [--worktree/-w] [--branch/-b <branch>] \
  [--context-delivery initial-message|hook]
forge session resume <name>                        # reattach the codex TUI to the same thread
forge session resume <name> --task "<next task>"   # next headless turn on the same Codex thread

# Show / list
forge session show            # Current session (from $FORGE_SESSION)
forge session show <name>     # Named session details
forge session list            # Sessions across the workspace (default: --scope workspace)
forge session list --scope project  # Sessions in current Forge project only
forge session list --scope all      # All sessions globally

# What a session did (operation outcomes + model calls)
forge telemetry activity [name]         # Per-session Forge automation outcomes, model calls, cost, tokens
forge telemetry activity [name] --json --days N --all

# Fork (conversation branching)
forge session fork <parent> [--name <name>] [--model <claude-model>] [--incognito] [--branch <branch>] [--worktree] [--into <path>] [--supervise] [--supervisor-proxy <id>] [--no-supervisor-proxy] [--cascade] [--checker-model <id>] [--checker-provider <p>] [--checker-effort <level>] [--supervisor-effort <level>] [--no-launch]

# Delete
forge session delete <name> [--keep-worktree] [--delete-branch] [--force] [--keep-transcripts]

# Clean (age-based bulk delete; previews by default, --yes to delete)
forge session clean --older-than DAYS [--yes] [--force] [--keep-transcripts] [--delete-worktree] [--delete-branch]

# Incognito (same options as start, auto-deletes on exit)
forge session incognito [name] [--proxy <proxy_id>] [--no-proxy]
  [--worktree/-w] [--branch/-b] [--system-prompt/-s] [--system-prompt-file/-S]
  [--sidecar|--host-proxy] [--mount] [--image] [--extensions/--no-extensions]

# Mid-session toggles (session-local only)
forge session set <key> <value> [--session <name>]
forge session reset [key] [--all] [--session <name>]

# Sandboxed session shell
forge session shell [name]
```

If Forge still sees a live launch in `~/.forge/sessions/active.json`, `forge session delete <name>` refuses to delete
the session (exit 1) and `forge session delete --all` skips the live ones (deleting the rest). Liveness self-heals, so a
session whose launcher already exited deletes normally. `--force` deletes a running session anyway (Forge state is
removed while Claude keeps running until the launch exits) and also overrides dirty-worktree and corruption guards.
`--yes` only skips confirmation prompts; it does not override the active-session guard.

### Session cleanup

Clean up old sessions by age:

```bash
forge session clean --older-than 30           # Preview sessions > 30 days old
forge session clean --older-than 30 --yes     # Actually delete them
forge session list --older-than 30            # List old sessions before cleaning
```

Active sessions are always skipped. Worktrees and branches are preserved by default. Claude transcript files
(`~/.claude/projects/*.jsonl`) are deleted; Forge artifact snapshots (`<forge_root>/.forge/artifacts/`) are not.

For automatic cleanup, set `session_retention_days` in `~/.forge/config.yaml`:

```bash
forge config set session_retention_days=90    # Auto-clean sessions > 90 days on CLI startup
```

Auto-cleanup runs opportunistically on each `forge` command (same pattern as log retention). It never deletes worktrees
or branches automatically.

---

## Prerequisites

Sessions require a **Forge project** — a directory with `.forge/` (and `.claude/`), created by `forge extension enable`:

```bash
cd my-repo
forge extension enable --scope local    # Creates .claude/ and .forge/ if needed
forge session start my-feature    # Now works
```

Without `.forge/`, `forge session start` fails with a clear error. The bare launcher (`forge claude start`) does not
require `.forge/`.

---

## Session scoping (`forge_root`)

All session state (manifests, artifacts, search index, transfer files) is scoped to the **Forge project root**
(`forge_root`) — the directory containing `.forge/`. In most setups this is your repo root. In monorepos with nested
Forge projects, each project has its own session namespace.

Session files always live under `<forge_root>/.forge/...`; `worktree.path` records where the code checkout lives. The
common worktree cases are:

| Command shape                                                | Where the child/session state lives                                           |
| :----------------------------------------------------------- | :---------------------------------------------------------------------------- |
| `forge session start --worktree` from a root-level project   | Original project root's `.forge/`; the new worktree is only the code checkout |
| `forge session start --worktree` from a nested Forge project | Equivalent nested Forge project inside the new worktree                       |
| `forge session fork --worktree`                              | New worktree's Forge project root                                             |
| `forge session fork --into <path>`                           | Target worktree's Forge project root at the equivalent position               |

### Which commands resolve cross-project?

Most session commands resolve sessions **workspace-wide** — if `list` shows a session, you can interact with it
regardless of which Forge project you're currently in (within the same git repo):

| Command                   | Scope                | Notes                                             |
| :------------------------ | :------------------- | :------------------------------------------------ |
| `session list`            | Workspace (default)  | `--scope project` / `--scope all`                 |
| `session show`            | Workspace-wide       | Prefers current project; shows cross-project note |
| `session delete` (named)  | Workspace-wide       | Prefers current project; shows cross-project note |
| `session delete --all`    | Current project only | Requires being inside a Forge project             |
| `session set` / `reset`   | Workspace-wide       | Via `--session` flag                              |
| `session resume` / `fork` | Current project only | CWD-dependent (Claude Code constraint)            |
| `session clean`           | Global               | All projects regardless of CWD                    |

When the same session name exists in multiple Forge projects within the repo, the current project wins. If you're not in
any of them, you'll see an error listing the locations.

When forking `--into` another worktree, the child session lands at the **equivalent position** — if the parent was at
`monorepo/packages/app`, the child lands at `target-worktree/packages/app`. The target must have Forge enabled at that
path.

---

## Workflows

### Start a session

```bash
forge session start                   # Auto-named (e.g., "happy-fox")
forge session start auth-refactor     # Explicit name
```

Typical effects:

- creates/updates the session manifest: `<forge_root>/.forge/sessions/auth-refactor/forge.session.json`
- updates the global index: `~/.forge/sessions/index.json` (including last-used time)
- registers a runtime live-session entry: `~/.forge/sessions/active.json` (cleared when the launch exits)
- sets `FORGE_SESSION=auth-refactor` env var
- launches Claude Code

### Start a session in a worktree (optional for filesystem isolation)

```bash
forge session start auth-refactor --worktree
```

Why use a worktree:

- isolates **filesystem changes** (no cross-talk between sessions editing files)
- useful when sessions will be modifying code concurrently

> Worktrees add **filesystem** isolation so multiple sessions can modify files concurrently without conflicts. Sessions
> can also coexist in the same worktree (see [Session state](#session-state-what-files-exist)).

For root-level Forge projects, `start --worktree` keeps the session manifest and artifacts in the original
`<forge_root>/.forge/`; the manifest's `worktree.path` points at the isolated checkout. Nested Forge projects are
remapped to the equivalent nested Forge root inside the new worktree.

### Start a sidecar session (Docker isolation)

```bash
forge session start auth-refactor --sidecar
```

Why use sidecar mode:

- bundles proxy + Claude Code inside a Docker container (lifecycle coupling, port isolation)
- project directory is mounted at `/workspace`
- optional extra mounts: `--mount /data:/mnt/data:ro`
- custom image: `--image my-dev-image:latest`
- Forge records sidecar mode, extra mounts, and image in the session manifest so `forge session resume <name>` can
  replay them later

To open a shell inside a running sidecar session:

```bash
forge session shell auth-refactor
```

### Resume an existing session

```bash
forge session resume auth-refactor
```

Default behavior: **reattach** — resumes the **same** Claude conversation in the **same** Forge session. This reopens
the existing conversation in place after the previous launch has ended.

- **Reattach** (default): relaunches the **same** Claude conversation on the same Forge session
  (`--resume <claude_session_id>`, no fork) and refreshes `confirmed` runtime facts (`confirmed_at`, `transcript_path`).
- **Fresh child** (`--fresh`): derives a new **child session** (a fork with lineage) with context assembled from the
  parent — this is the path that mints a distinct child UUID (native mode uses `--resume --fork-session`). See "Derive a
  fresh session from an existing one" below.
- If the session was created in sidecar mode, Forge relaunches it in sidecar mode again using the recorded image and
  extra mounts.

**Gates** (hard-fail, not warn):

- Session must have **resumable evidence**. Hook-confirmed sessions work, and transcript-backed sessions also work if
  the SessionStart hook missed confirmation. Pre-seeded UUIDs by themselves are not enough.
- Session must **not be currently active**. Fails if another launcher is still running for this session.

### Derive a fresh session from an existing one

```bash
forge session resume auth-refactor --fresh
# or: interactive pick to choose a parent
forge session resume --fresh
```

`forge session resume --fresh` creates a new child session derived from the parent. By default it uses assembled
transfer context; `--resume-mode native` carries the full Claude conversation instead.

**Resume modes** (`--resume-mode`):

| Mode                 | Mechanism                                           | Trade-off                                              |
| -------------------- | --------------------------------------------------- | ------------------------------------------------------ |
| `transfer` (default) | Assembled context via `--append-system-prompt-file` | Editable + portable; survives `/compact`               |
| `native`             | `--resume --fork-session` (full conversation)       | Byte-faithful but opaque; same CWD; lost on `/compact` |

```bash
# Default: assembled context (transfer)
forge session resume auth-refactor --fresh

# Lossless: carry full conversation history
forge session resume auth-refactor --fresh --resume-mode native

# Curate the user-notes overlay in $EDITOR before launching
forge session resume auth-refactor --fresh --review
```

Native mode requires the parent to have a confirmed Claude session ID (i.e., the session must have been launched at
least once). `--strategy` and `--depth` are ignored in native mode. `--review` is only valid for transfer mode (native
resumes carry the conversation verbatim and have no editable artifact).

**Curating with `--review`.** When you pass `--review`, Forge opens the per-child **user-notes overlay**
(`children/<child>.notes.md`) in `$EDITOR` and waits — the AI snapshot (`children/<child>.md`) stays read-only, so your
notes survive a later `forge session transfer regenerate`. Save and exit normally to launch; abort (`:cq` in vim) to
skip the launch. Your notes are preserved on disk regardless. If you abort, the child remains unlaunched; run
`forge session resume <child>` later. Notes are merged after the snapshot at launch.

**Per-parent layout for resume artifacts.** Each parent gets a directory under `.forge/prev_sessions/`:

```text
<forge_root>/.forge/prev_sessions/
└── <parent>/
    ├── generated.md              # Regeneratable AI cache (overwritten on every resume)
    └── children/
        ├── <child>.md            # Per-child AI snapshot (frozen; never edited)
        └── <child>.notes.md      # Per-child user-notes overlay (edit this; merged at launch)
```

Re-resuming the same parent regenerates `generated.md` but never disturbs an existing `children/<child>.md` **or** its
`.notes.md` overlay. Write your edits to the notes overlay (via `--review` or `forge session transfer edit`) so they
survive regeneration. Inspect or reshape any of this with the `forge session transfer` group
(`show`/`regenerate`/`edit`/`diff`) — see [transfer.md](transfer.md), which also covers the cross-runtime (Codex)
workflow.

Resume and fork-recovery launches inject the per-child file directly with `--append-system-prompt-file`. If you
customize `CLAUDE.md`, do not also add manual references to `.forge/prev_sessions/...` there, or you may duplicate the
same transfer context.

### Derive a Codex session from a Claude parent (cross-runtime)

```bash
forge session start impl --runtime codex --resume-from planner --task "Implement the plan."
forge session resume impl --task "Now add tests."
forge session show impl      # Runtime, Codex thread id, rollout path, auth posture
forge telemetry activity impl          # transfer-curate + codex turns under one run tree
```

Requires `codex` installed and authenticated (`forge runtime preflight codex` → `Ready YES`). The start command curates
the parent's context (default `--strategy ai-curated`), prepends it to your `--task` as the initial `codex exec`
message, and records the Codex **thread id** so each `resume --task` continues the same conversation — from any
directory; the turn always runs in the session's recorded worktree. Codex sessions go direct to OpenAI: proxy,
supervision, memory, and other Claude-only flags are rejected. `--task` selects the headless form, requires
`--resume-from`, and is only valid for Codex sessions; omitting it opens the interactive TUI (next section). If the
first turn fails before Codex opens a thread, resume refuses with guidance — delete the session and start again.

**Context delivery (`--context-delivery`):** `initial-message` (default) prepends the curated transfer to the first
prompt — zero setup. `hook` delivers it via a trust-enrolled Codex `SessionStart` hook instead (`additionalContext`):
register `forge hook codex-session-start` in your Codex config and complete the one-time trust ceremony first (see
[hook.md](hook.md#codex-session-start-codex-sessionstart)). Enrollment can't be verified up front, so Forge checks
delivery **after** the turn via the hook's receipt and records the outcome in the manifest
(`confirmed.codex.context_delivery`). If the hook didn't fire, the command exits 1 — the first turn ran without the
parent context; enroll the hook, or `forge session delete <name>` and retry with the default delivery.

### Interactive Codex sessions

```bash
forge session start scratch --runtime codex                  # bare: open the codex TUI as a managed session
forge session start impl --runtime codex --resume-from planner   # interactive bridge: curated context, then you type
forge session resume scratch                                 # reattach the TUI to the same thread
forge session show scratch                                   # thread id, rollout, how the thread was captured
```

Omitting `--task` launches the foreground `codex` TUI under Forge management: the session is indexed, the thread id and
rollout are recorded when the TUI exits, and a bare `forge session resume <name>` reattaches the same conversation with
`codex resume` — from any directory; the TUI opens in the session's recorded worktree. While a launch is active, a
second resume is refused (exit the running TUI first). With `--resume-from`, the curated parent context arrives as the
session's first message, framed with hold instructions so Codex acknowledges it and waits for you instead of acting on
its own; with `--context-delivery hook` (trust-enrolled homes) the context lands invisibly via `additionalContext` and
the TUI opens with no first message. Transfer-shaping flags (`--strategy`, `--depth`, `--context-delivery`) require
`--resume-from`.

**Shared-host note:** with the default `initial-message` delivery the curated context is passed as the `codex` process's
positional prompt, so it is visible to other users' process listings on the same machine (`ps`, `/proc/<pid>/cmdline`).
On a multi-user or shared host, prefer `--context-delivery hook` (trust-enrolled homes), which delivers the context out
of band via `additionalContext` rather than on the command line. (Headless `--task` turns pass the prompt on stdin, so
they are unaffected.)

Thread capture is automatic. In trust-enrolled homes the `codex-session-start` hook reports the thread directly; without
enrollment Forge discovers the rollout file Codex wrote during the run. Discovery refuses to guess: if several Codex
sessions were started concurrently in the same directory, the thread may stay unrecorded — the command warns, and
`forge session delete <name>` plus a fresh start is the recovery. Interactive turns do not appear in the usage ledger
(Codex reports no attributable usage for TUI turns); a bridge's transfer curation still does.

```bash
forge session fork auth-refactor --name auth-refactor-alt
```

A fork creates a new named session that branches the parent's Claude conversation. By default the fork stays in the same
directory, so Claude's `--resume --fork-session` finds the parent conversation and carries it over.

**What gets copied:**

- Session file (`intent`, `overrides`, `confirmed`) -> new session's location
- `confirmed.latest_plan_path` -> forked session inherits the same plan
- Claude Code conversation context -> carried over via `--fork-session` (same directory)

**With `--worktree` (code isolation):**

```bash
forge session fork auth-refactor --name auth-refactor-alt --worktree
```

Creates a git worktree for the fork. `--branch` implies `--worktree`. Because Claude conversations are project-scoped,
the fork starts a fresh Claude session in the new worktree and automatically injects a parent transfer context file
(`.forge/prev_sessions/<parent>/children/<fork-name>.md`). Claude knows where the parent left off, but the old visible
chat history is not replayed.

**Resume mode (`--resume-mode`):** cross-directory forks (`--worktree`/`--into`) default to `transfer` — the assembled,
editable context file above. For a byte-faithful alternative, pass `--resume-mode native-relocate`: Forge relocates the
parent's Claude transcript into the fork so the full conversation resumes verbatim. It is **host mode only** (rejected
in sidecar), the relocated history is opaque to Forge (lost on `/compact`, and historical tool paths still point at the
parent checkout — no path rewriting yet), and the default stays `transfer`.

The fork manifest and transfer file live under the new worktree's Forge root. For a root-level project, inspect
`<new-worktree>/.forge/sessions/<fork>/forge.session.json` and
`<new-worktree>/.forge/prev_sessions/<parent>/children/<fork-name>.md`.

**With `--into` (existing worktree):**

```bash
forge session fork planner-session --into /path/to/executor-worktree
```

Forks into an **existing** non-main worktree. The fork gets the parent's conversation context (via transfer file) but
lands in the target worktree's code. The target must be part of the same git repository (validated via
`git-common-dir`). The main checkout is rejected — use a same-directory fork instead.

The child manifest and transfer file live under the target worktree's Forge root, for example
`/path/to/executor-worktree/.forge/sessions/<child>/forge.session.json` for a root-level project.

Key differences from `--worktree`:

- No git worktree creation (target already exists)
- No `.env`/`.mcp.json` copying (target already has them)
- Auto-install of extensions is skipped if Forge already has a tracked local install for the target worktree
- The session does NOT own the worktree (`owns_worktree=False`): deleting it never removes the worktree, and if the
  owning session was deleted earlier, final worktree cleanup is left to you

**Transfer options:**

| Flag             | Purpose                                                                     | Default      |
| ---------------- | --------------------------------------------------------------------------- | ------------ |
| `--strategy <s>` | Context assembly strategy (`minimal`/`structured`/`full`/`ai-curated`)      | `structured` |
| `--inline-plan`  | Embed the approved plan content in the transfer (not just a path reference) | off          |

A plain same-directory fork uses native `--resume --fork-session` (full Claude continuity, no transfer file). On a
same-directory fork these transfer flags **switch it into transfer mode**: passing `--strategy` or `--inline-plan`
auto-switches the fork (with an info line), and `--resume-mode transfer` opts in explicitly. A same-directory transfer
fork generates the transfer file and starts a *fresh* child Claude session — the same file-based transfer that
`--worktree` and `--into` forks always use. `--resume-mode native-relocate` remains worktree/`--into`-only.

`ai-curated` uses OpenRouter directly and requires `OPENROUTER_API_KEY`. If OpenRouter auth is unavailable, Forge warns
and falls back to the deterministic `structured` strategy.

**Use case: Plan -> Execute -> Review workflow:**

```bash
# 1. Plan
forge session start planner
# ... plan, approve plan, /exit

# 2. Execute in worktree with plan supervision
forge session fork planner --worktree --supervise
# ... implement; supervisor auto-checks every Write/Edit against the plan

# 3. Review: fork planner into executor's worktree with plan inlined
forge session fork planner --into /path/to/executor-worktree --inline-plan
# Reviewer sees: planner context + approved plan + executor's code
```

The `--supervise` flag wires the parent as a semantic supervisor. Every code change is checked against the approved plan
at `PreToolUse` time. Supervisor config persists through `forge session resume`. You can also wire supervision on
existing sessions with `forge policy supervisor set <session>` or `%policy supervisor <session>` in-session.

**Supervisor routing:** By default, the supervisor inherits the planner's proxy. Use `--supervisor-proxy` or
`--no-supervisor-proxy` to override:

```bash
# Fork with supervisor on a different model (e.g., Gemini for checking, Opus for coding)
forge session fork planner --worktree --supervise --supervisor-proxy openrouter-gemini --no-proxy

# Fork with supervisor going direct to Anthropic
forge session fork planner --worktree --supervise --no-supervisor-proxy

# Same flags work on session start
forge session start executor --supervise planner --supervisor-proxy openrouter-gemini

# Or change supervisor routing on an existing session
forge policy supervisor set planner --supervisor-proxy openrouter-gemini
```

**Launch-time cascade and checker controls:** `fork` and `start` accept the same tier-1 cascade knobs as
`forge policy supervisor set`, so you can wire the cheap pre-check at launch instead of in a second command. All require
`--supervise`:

```bash
# Fork with the tier-1 plan check (cascade) and a specific checker model/provider
forge session fork planner --worktree --supervise \
  --cascade --checker-model google/gemini-3.5-flash --checker-provider openrouter

# Same knobs on session start
forge session start executor --supervise planner --cascade --checker-model google/gemini-3.5-flash
```

Launch-time `--cascade` only sets the flag; it does **not** resolve a plan eagerly. The runtime hook escalates to the
frontier supervisor when no plan exists yet. This differs from `forge policy supervisor set --cascade`, which resolves
the plan at the time you run it.

**Reasoning effort:** `--supervisor-effort` sets the frontier supervisor's `claude --effort`
(`low/medium/high/xhigh/max`; `max` is Claude-only). `--checker-effort` sets the tier-1 checker's reasoning effort
(`none/low/medium/high/xhigh`; `none` is checker-only — the checker is an API call, not a `claude -p` subprocess). The
two vocabularies are distinct: `max` is invalid for the checker and `none` is invalid for the supervisor.

```bash
forge session fork planner --worktree --supervise --cascade \
  --checker-effort low --supervisor-effort medium
```

**Supervisor lifecycle controls:**

```bash
# Suspend supervision (preserves config — resume_id, proxy, timeouts)
forge policy supervisor off
%policy supervisor off

# Resume suspended supervisor
forge policy supervisor on
%policy supervisor on

# Remove supervisor entirely
forge policy supervisor remove
%policy supervisor remove

# Reload plan when it evolves (searches current session, forks, target)
forge policy supervisor reload
%policy supervisor reload

# Reload from explicit file
forge policy supervisor reload --from ~/.claude/plans/updated-plan.md
%policy supervisor reload /path/to/plan.md
```

The planner session stays intact throughout — it can be forked multiple times for different executors or reviewers.

---

## Using sessions with proxies (proxy endpoints)

Sessions can record which proxy they started with, but they do **not** control routing.

**Key principle:** Proxies own routing. Sessions own workflow. See [proxy.md](proxy.md) for routing configuration.

### Launch Claude with a proxy

```bash
forge claude start --proxy <proxy_id>
```

This resolves the proxy, healthchecks it, sets `ANTHROPIC_BASE_URL`, applies `CLAUDE_CODE_ATTRIBUTION_HEADER=0` only for
translated/third-party proxy routes, sets `CLAUDE_CODE_AUTO_COMPACT_WINDOW`, and launches Claude.

### Start a session with a proxy

```bash
forge session start my-session --proxy openrouter-anthropic
```

`--proxy` sets the session's initial proxy intent. It accepts a proxy ID or template name. Without `--proxy`, sessions
default to direct mode (Anthropic API).

The invariant: choosing a proxy chooses routing defaults (model family, context limit).

For proxy context windows above Claude's 200K baseline, Forge also sets Claude Code's default Opus and Sonnet model
aliases to 1M Claude variants. This keeps Claude Code's local context estimator from stopping early while the proxy
still routes requests to the configured backend tier, such as Gemini or OpenAI.

### Pin a Claude model (`--model`)

```bash
forge session start review-pass --model claude-opus-4-8
forge session start long-sonnet --model claude-sonnet-4-6[1m]
forge session start review-pass --proxy openrouter-anthropic --model claude-opus-4-8
forge session resume review-pass --model claude-opus-4.6
forge session fork planner --name executor --model claude-opus-4.6
```

`--model` behavior depends on the session routing mode:

| Mode                                    | What `--model` does                                                | `[1m]` support                 |
| --------------------------------------- | ------------------------------------------------------------------ | ------------------------------ |
| Direct (no `--proxy`)                   | Pins Claude Code's `ANTHROPIC_MODEL` directly                      | Yes                            |
| Proxy + tier default or alternative     | Selects a tier or `model_alternatives` entry; proxy routes it      | Yes (stripped at proxy lookup) |
| Proxy + no matching default/alternative | Errors: "does not configure model alternative or tier default ..." | N/A                            |
| Subprocess proxy (`--subprocess-proxy`) | Pins Claude Code env vars (main is direct; subprocesses inherit)   | Yes                            |

Rejected for sidecar or host-proxy launches.

Forge stores the normalized model pin in the session intent and relaunches resume/fork children with the same
`ANTHROPIC_MODEL` and `ANTHROPIC_DEFAULT_*_MODEL` environment variables. `forge session resume --model ...` updates the
current session's stored pin; `forge session fork --model ...` writes the pin to the child session. This is useful when
moving a planner between Opus 4.8 execution and Opus 4.6 final review. The stable `claude-opus`/`opus` aliases point at
Claude Opus 4.6; use `claude-opus-4-8` explicitly for Opus 4.8.

For proxy-routed resume/fork overrides, pass `--proxy <proxy_id>` when the session has not yet been hook-confirmed with
a specific proxy id; Forge needs the proxy id to validate tier defaults and `model_alternatives`.

For proxy-mode `model_alternatives` configuration, see [proxy.md](proxy.md#model-alternatives).

### Resume with a routing override

```bash
forge session resume parent-session --fresh --proxy openrouter-gemini
forge session resume parent-session --model claude-opus-4.6
```

`--proxy` performs full proxy resolution (exact proxy_id match or active template lookup) with a healthcheck, then
routes the child session through the resolved proxy. It accepts both proxy IDs and template names.

`--no-proxy` forces direct Anthropic routing, bypassing any inherited proxy.

### Route only subprocesses through a proxy

Use `--subprocess-proxy` when the main session should use Claude Code's direct Anthropic auth, but Forge-spawned
subprocesses such as supervisor, panel, or memory-writer jobs should use a proxy:

```bash
forge session start my-session --subprocess-proxy openrouter
```

This records `intent.subprocess_proxy` and sets `FORGE_SUBPROCESS_PROXY` for child jobs. It is mutually exclusive with
`--proxy`: use `--proxy` when the main session itself should route through the proxy.

---

## Mid-session toggles (`set` / `reset`)

These commands modify **overrides** in the session file without mutating baseline intent.

Examples:

```bash
forge session set memory.tags '["project:foo","component:auth"]'

# Reset one key
forge session reset memory.tags

# Reset all overrides
forge session reset --all
```

**Policy/TDD enforcement** is managed separately via the Policy CLI, not session set:

```bash
forge policy list                                   # Show available bundles and rules
forge policy enable --bundle tdd                    # Enable TDD enforcement
forge policy enable --bundle tdd --permissive       # Warn instead of block
forge policy enable --bundle coding_standards       # Enable coding standards
forge policy disable                                # Disable all policy
forge policy status                                 # Show current policy state
```

### Ownership boundaries (session vs proxy)

**Session-owned** (you CAN toggle):

- policy enforcement (`forge policy enable/disable`)
- memory behavior (`memory.*`) — see [`memory.md`](memory.md) for automatic doc updates
- artifact capture settings
- worktree association
- session metadata

**Proxy-owned** (you CANNOT toggle via session):

- tier→model mapping
- provider/base_url
- reasoning_effort
- thinking_budget_tokens
- temperature/max_tokens defaults

Attempting to set proxy-owned keys is rejected. To change routing defaults, use a different proxy or edit your proxy
overlay. See [proxy.md](proxy.md) for proxy configuration.

---

## What a session did (`forge telemetry activity` + session-end summary)

Two read surfaces report what Forge's automation did during a session (supervisor, memory writer, workflow verbs,
transfer curation, action tagging, and policy decisions — **not** your full interactive Claude usage). They read
upstream operation outcomes, downstream model-call evidence, transitional usage events, and the capped policy-decision
fallback. Session-scoped spend figures are **best-effort attribution** — `forge telemetry costs show` stays the
authoritative dollar view (see [proxy.md](proxy.md#cost-tracking-and-spend-caps), and
[which surface answers which question?](proxy.md#which-surface-answers-which-question) for when to use each).

**Session-end summary (automatic).** When a session exits, the launcher prints a one-line rollup before the reconnect
tip. This is the one session-end channel Claude Code does not suppress — non-blocking hook output (including supervisor
**warnings**) is hidden from you mid-session, so without this line a `warn` verdict is invisible:

```text
Forge this session — supervisor: 12 checks (2 warn, 0 block, failing open: 2 timeout, 1 error) · ~$0.04 · 21k tok · 2 workflows
```

The `failing open` clause surfaces supervisor LLM calls that errored or timed out and **failed open** (the action
proceeded without frontier review), broken down by kind — for example a 45s timeout or an OpenRouter content-filter
rejection. The line is best-effort and prints only when the session had activity; incognito sessions are skipped.

**`forge telemetry activity [session]` (on demand).** Inspect any session's Forge automation activity anytime:

```bash
forge telemetry activity                      # current session ($FORGE_SESSION)
forge telemetry activity my-feature           # a named session (or Claude UUID)
forge telemetry activity my-feature --days 7  # last 7 days (default: 30)
forge telemetry activity my-feature --all     # full history
forge telemetry activity my-feature --json    # machine-readable
```

It renders two panes. **Operation outcomes** shows upstream outcomes such as policy checks, supervisor fail-open/no-call
results, memory writer, supervisor shadow drain, shadow curation, workflow worker failures, transfer curation, and
action tagging. **Model calls** shows the model-call/spend side: calls, workers, attempts, tokens, cost, legacy error
counts, and whether a row is `matched` to an upstream outcome or `downstream-only` evidence known through the session's
run tree. A workflow fan-out (panel/debate/...) counts as **one** call with its worker count tracked separately, so a
4-worker panel reads as one workflow, not five.

`--json` returns the same split as top-level `upstream`, `downstream`, `shadow`, `subagents`, and `notes` fields. Policy
success/cached counts come from the manifest fallback and may be capped at the last 100 decisions; the output marks that
with `log_capped`.

The Supervisor line appends `failing open: N timeout, N error` when recent frontier checks failed open — this is the
always-visible status line's `SUP!N <kind>` marker in detail (recent supervisor checks erroring/timing out means actions
may be proceeding without frontier review). The two are scoped differently, so the counts can differ: `SUP!N` is the
**current consecutive** fail-open streak (it resets on the supervisor's next successful check), while
`forge telemetry activity` totals fail-opens across the selected window (`--days`/`--all`).

> **Sidecar:** both surfaces work in sidecar mode when the session launched with a proxy id (the in-container usage
> ledger is mounted back to the host). A template-only sidecar shows only the policy-decision half.
>
> **Coverage:** model-call spend is session-attributed only when a session-tagged run tree or provider-session id can
> connect it to the session. Orphaned downstream records are not guessed into a session; the summary flags partial
> coverage rather than inventing attribution.

---

## Troubleshooting

### “I tried to change the model tier / LLM settings”

Sessions do not control routing or LLM defaults. Choose a different proxy or specify a tier explicitly in the request
model name.

### "I want multi-model A/B/C workflows without worktrees"

It works if sessions are run sequentially.

If you run sessions concurrently and both write code, use `--worktree` to avoid clobbering the working directory.

---

## Advanced

### Template vs Proxy ID

`--proxy` accepts both proxy IDs and template names. Resolution order:

1. Exact proxy_id match (any status)
2. Active template match (healthy/starting only; fails if ambiguous)
3. Auto-start from a config template of that name when nothing is running (reuse/adopt/spawn)

All launch commands (`start`, `resume`, `fork`, `claude start`) use the same `ensure_proxy()` function: it resolves via
the order above, auto-starts from a matching template when no proxy is running, then healthchecks. A name that matches
neither a running proxy nor a template fails with a `forge proxy template list` hint. `--supervisor-proxy` resolves the
same way.

`--template` and `--base-url` are deprecated hidden aliases for `--proxy` (warn on use).

### Sidecar specifics

- Sidecar sessions use a container-local proxy at `http://localhost:8085`
- `forge session shell [name]` only works for sessions started with `--sidecar`
- The project directory is mounted at `/workspace` inside the container

### Files to inspect (debugging)

| File                                                     | Purpose                                     |
| -------------------------------------------------------- | ------------------------------------------- |
| `<forge_root>/.forge/sessions/<name>/forge.session.json` | Session manifest (intent + confirmed state) |
| `~/.forge/sessions/index.json`                           | Global session registry (with UUIDs)        |
| `~/.forge/sessions/active.json`                          | Runtime live-session registry               |

### Gotchas

| Trap                              | Explanation                                                                                             |
| --------------------------------- | ------------------------------------------------------------------------------------------------------- |
| "Session didn't pick up my proxy" | `--proxy` resolves by proxy_id first, then active template match. If ambiguous, use the exact proxy_id. |
| "Hooks lost session identity"     | Hooks resolve via `FORGE_FORK_NAME` -> `FORGE_SESSION` -> UUID lookup (no dir scanning)                 |
| "Can't shell into session"        | `forge session shell` only works for `--sidecar` sessions                                               |
