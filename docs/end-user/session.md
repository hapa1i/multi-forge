# Forge Sessions — Session Manager Guide

**Status:** Implemented for session management (naming, worktrees, artifacts). Updated here to match the **Session vs
Proxy** regime in `docs/design.md`.

- Canonical architecture: [`docs/design.md`](../design.md)
- Proxies (proxy endpoints): [`proxy.md`](proxy.md)
- Configuration system: [`config.md`](config.md)

---

## What a session is (and is not)

A **session** is a durable human unit of work. It tracks a runtime conversation, not one process invocation:

- named session identity (portable name)
- worktree association (optional for parallel work — multiple sessions can also run in the same directory)
- session manifest (`<forge_root>/.forge/sessions/<name>/forge.session.json`) storing intent/overrides/confirmed facts,
  including relaunch preferences
- artifacts (approved plans, transcripts)
- a single current runtime conversation identity when established: `confirmed.claude_session_id` for Claude or
  `confirmed.codex.thread_id` for Codex. Multiple process invocations may reattach to that conversation.

For Claude, `forge session start` **pre-seeds** `claude_session_id` (the CLI generates it and imposes it via
`--session-id`; the SessionStart hook validates it), so a non-null value does **not** by itself mean the session ran —
"used" means it has hook-confirmed or transcript-backed evidence (a `--no-launch` session carries a pre-seeded UUID but
never launched). `forge session resume` **reattaches** to the same conversation by default when that evidence is safe;
`resume --fresh` derives a **child session** (a fork with lineage). Related sessions are grouped by lineage
(`parent_session`), not by UUID accumulation.

A session is **not** a proxy routing identity.

- Proxy routing defaults are **proxy-owned**.
- Sessions cannot override proxy-owned routing/hyperparams.

---

## Session state: what files exist

- Session manifest (per Forge project): `<forge_root>/.forge/sessions/<name>/forge.session.json`
- Global session index: `~/.forge/sessions/index.json` (name, forge_root, project_root, last-used-at, UUID)
- Active-session registry: `~/.forge/sessions/active.json` (runtime-only live launches; self-heals stale entries)
- Launch journals: `<forge_root>/.forge/artifacts/<name>/{authority,routing}/events.jsonl` (strict append-only local
  evidence; each domain exists only after it is used)

<!-- forge-env-vocab: diagnostic:start -->

> **Session identity:** Hooks use Forge launch env vars only. Resolution order is: `FORGE_FORK_NAME` -> `FORGE_SESSION`
> -> IndexStore UUID lookup. No CWD-based directory scan.

<!-- forge-env-vocab: diagnostic:end -->

Multiple sessions can coexist in the same Forge project, each with its own directory under
`<forge_root>/.forge/sessions/`.

Session manifests are strict durable state. `intent` and `overrides` must be JSON objects; `confirmed` defaults to an
empty section when absent for legacy compatibility but must also be an object when present. Forge reports invalid shapes
as corruption and does not rewrite them during ordinary reads.

The session file includes hook-confirmed facts such as:

- `confirmed.claude_session_id` (launch-owned: pre-seeded by `forge session start` and by transfer/fresh children, then
  validated by the SessionStart hook; only a native `--fork-session` lets Claude mint it, which the hook records)
- `confirmed.transcript_path`
- `confirmed.started_with_proxy` (snapshot from the SessionStart hook; `{base_url, proxy_id?, template?, port?}`)
- `confirmed.route_commit` (the latest effective routing journal `{event_id, run_id}` pointer; not a copied route)

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

No managed-session environment, no session manifest, no artifacts. Session-specific hooks and status line are no-ops.
Does not require `.forge/`. Use `forge session start` for managed sessions.

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

To learn these boundaries without changing your real Forge or runtime-extension state, run `/walkthrough` from Claude
Code. Its default creates a model-pinned direct session without launching it, shows intent without fabricated route
commitment, then uses `forge session resume` to produce hook-confirmed lifecycle and route evidence. See
[manual_testing.md](manual_testing.md#walkthrough).

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
  [--authority advisory|producer] [--authority-tier named_tools|shell_closed] \
  [--system-prompt/-s <text>] \
  [--system-prompt-file/-S <path>] \
  [--sidecar|--host-proxy] [--mount <host:container>] [--image <name>] \
  [--no-launch]

# Adopt a conversation you started outside Forge (run from its launch directory)
forge session adopt [--json]                          # preview unbound conversations here
forge session adopt <conversation-id> [--name/-n <name>] [--model/-m <model>] [--yes/-y]

# Resume an existing session (default: reattach when safe; --fresh: context assembly)
forge session resume <name>
forge session resume <name> --force  # active Claude session: launch a lineage child
forge session resume <name> --fresh

# Derive a fresh child session (PARENT optional; interactive picker)
forge session resume [parent] --fresh \
  [--child-name/-n <child_name>] \
  [--authority advisory|producer] [--authority-tier named_tools|shell_closed] \
  [--strategy/-s minimal|structured|full|ai-curated] \
  [--depth/-d <N|all>] \
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
forge session show            # Current session
forge session show <name>     # Named session details
forge session list            # Sessions across the workspace (default: --scope workspace)
forge session list --scope project  # Sessions in current Forge project only
forge session list --scope all      # All sessions globally

# Model-route provenance (read-only)
forge session model show [name] [--json]
forge session model history [name] [--json]

# What a session did (operation outcomes + model calls)
forge telemetry activity [name]         # Per-session Forge automation outcomes, model calls, cost, tokens
forge telemetry activity [name] --period week --json
forge telemetry activity [name] --period all

# Fork (conversation branching)
forge session fork <parent> [--name <name>] [--proxy <proxy_id>] [--no-proxy] [--model <claude-model>] [--incognito] [--branch <branch>] [--worktree] [--into <path>] [--authority advisory|producer] [--authority-tier named_tools|shell_closed] [--supervise] [--supervisor-proxy <id>] [--no-supervisor-proxy] [--cascade] [--checker-model <id>] [--checker-provider <p>] [--checker-effort <level>] [--supervisor-effort <level>] [--no-launch]

# Delete
forge session delete <name> [--keep-worktree] [--delete-branch] [--force] [--keep-transcripts]

# Clean (age-based bulk delete; previews by default, --yes to delete)
forge session clean --older-than DAYS [--yes] [--force] [--keep-transcripts] [--delete-worktree] [--delete-branch]

# Repair (re-index orphaned session manifests; previews by default, --yes to apply)
forge session repair [--yes] [--json]

# Incognito (same options as start, auto-deletes on exit)
forge session incognito [name] [--proxy <proxy_id>] [--no-proxy]
  [--worktree/-w] [--branch/-b] [--system-prompt/-s] [--system-prompt-file/-S]
  [--sidecar|--host-proxy] [--mount] [--image] [--extensions/--no-extensions]

# Mid-session toggles (session-local only)
forge session set <key> <value> [--session <name>]
forge session reset [key] [--all] [--session <name>]

# Artifact authority (human terminal only for mutations)
forge session authority show [name] [--json]
forge session authority set <name> --role advisory [--tier named_tools|shell_closed]
forge session authority set <name> --role producer
forge session authority clear <name>

# Sandboxed session shell
forge session shell [name]
```

### Inspect model-route provenance

`forge session model show [name] --json` keeps configured intent, the durable launch commitment, and current proxy facts
separate. A supported `route_commit` is dereferenced through the exact routing journal event and includes the committed
billing mode and route-scope tags. For proxy sessions, `live_proxy.evidence_source` is resolved in order: live
`runtime`, current `proxy_config`, supported `route_commit`, then `unavailable`. Only `runtime` is authoritative live
evidence; the other values are labelled fallback. The terminal read cannot see a specific request, so
`current_request_tier` stays null rather than reporting the proxy default as though the user selected it.

`forge session model history [name] --json` returns every validated event in append order. `history_status` means:

- `supported`: the projected event is the newest effective commit, or a complete aborted-only history needs no
  projection.
- `unproven`: a journal exists but is empty, inconsistent with the projection, or contains an uncompensated effective
  commit. An empty file can be residue from a failed first append; complete abort events are interpretable evidence.
- `null`: neither a projection nor a routing journal exists.

Existing manifests are not backfilled. If only legacy `confirmed.launch` exists, `show` labels it
`legacy_confirmed_launch`, uses null event/run ids, and invents neither history nor marking snapshots. `supported`
starts with the first route-provenance journal event. Missing journals and malformed/unreadable records are not silently
repaired: inconsistent evidence stays `unproven`, while malformed history is an actionable read error. Historical
route-model strings remain immutable route facts if a later package catalog removes an id; that removal makes the
current provider-declaration result unknown instead of invalidating an otherwise valid journal.

These surfaces report the route Forge committed before invoking a managed child. They do not prove which route handled
each request, what content a model authored, or whether any marking exists in generated text. Route and authority
journals survive ordinary session delete/clean with the containing artifact tree, including `--keep-transcripts`
choices; they disappear together only when cleanup removes an owning nested Forge root.

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

Compatibility is evaluated per Forge root. Preview output identifies sessions that apply would refuse. On `--yes`,
manual cleanup skips incompatible roots, continues compatible roots, reports every skipped target, and exits 1 if any
requested target was refused or failed. Automatic retention uses the same per-root skip but only logs it and never
changes the foreground command's exit status. `--force` does not bypass `.forge/project.toml`.

For automatic cleanup, set `session_retention_days` in `~/.forge/config.yaml`:

```bash
forge config set session_retention_days=90    # Auto-clean sessions > 90 days on CLI startup
```

Auto-cleanup runs opportunistically on each `forge` command (same pattern as log retention). It never deletes worktrees
or branches automatically.

Authority journals are Forge artifacts under `.forge/artifacts/<session>/authority/events.jsonl`. Delete and clean do
not selectively remove them, and `--keep-transcripts` does not change their lifetime. They remain when the recorded
Forge root remains. If deletion removes an owned worktree that contains that Forge root (for example, a nested Forge
project in a worktree), the journal disappears with the containing checkout.

### Repairing invisible sessions

A session can end up with its manifest on disk but no entry in the session index — a crash during creation on an older
Forge or manual index damage can produce this shape. Such an orphan does not appear in `forge session list`, yet its
name stays taken and its conversation stays bound. From the project root:

```bash
forge session repair          # Report orphaned manifests and what repair would do
forge session repair --yes    # Re-index repairable and degraded records
```

Repair never deletes or recreates anything. The preview labels each orphan: `repairable` and valid `missing-worktree`
manifests are re-indexed by `--yes`; `collision` means the conversation now belongs to a live session and is refused;
`corrupt` manifests are `forge clean`'s job. Repairing a `missing-worktree` record restores discovery only — it does not
claim the missing checkout. With `--yes`, the command exits 1 if any repair was refused or failed. A
`.forge/project.toml` version pin refuses `--yes` the same way other session mutations are refused.

Current Forge keeps an already indexed session visible when its valid manifest survives but its recorded worktree is
gone. `session list` and `session show` report `launchability=missing_worktree` and name the recorded path; their JSON
forms expose the same `launchability` field. Resume, fork, and launch refuse before changing session state. Recreate a
directory at the recorded path to make the session launchable again without migration, or run
`forge session delete <name>` to remove its durable reservation. `forge clean` reports this degraded state but never
auto-deletes the valid manifest.

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

If `<forge_root>/.forge/project.toml` declares `required_forge`, every explicit session mutation checks the root that
owns the target manifest and artifacts. This includes named cross-project settings/deletion, transfer edits, lane and
memory settings, resume, fork, and cleanup. A refusal occurs before proxy startup, editor launch, lane freeze, or
filesystem mutation. Run a satisfying Forge version, or edit/reset project state; changing `FORGE_DEV` requires
relaunch, and a sidecar needs a satisfying Forge in its image.

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

| Command                          | Scope                | Notes                                             |
| :------------------------------- | :------------------- | :------------------------------------------------ |
| `session list`                   | Workspace (default)  | `--scope project` / `--scope all`                 |
| `session show`                   | Workspace-wide       | Prefers current project; shows cross-project note |
| `session delete` (named)         | Workspace-wide       | Prefers current project; shows cross-project note |
| `session delete --all`           | Current project only | Requires being inside a Forge project             |
| `session set` / `reset`          | Workspace-wide       | Via `--session` flag                              |
| Claude `session resume` / `fork` | Current project only | CWD-dependent (Claude Code constraint)            |
| Codex `session resume`           | Resolved session     | Cross-CWD; runs in the recorded worktree          |
| `session clean`                  | Global               | All projects regardless of CWD                    |

When the same session name exists in multiple Forge projects within the repo, the current project wins. If you're not in
any of them, you'll see an error listing the locations.

### Inspect the workspace's worktrees

`--scope workspace` groups sessions whose index entries share the same logical repository (`project_root`). To inspect
the Git membership behind that scope, including registered worktrees with no Forge sessions, run:

```bash
forge workspace worktrees
forge workspace worktrees --json
```

The view joins `git worktree list` with the workspace-scoped session index. Counts include incognito sessions because
they still occupy a worktree; session names remain available through `forge session list --scope workspace`. A
registered path that is unavailable now is shown as `missing`, never "gone." `missing (prunable)` is Git's stale-record
annotation; `missing (locked)` can be intentional, such as a worktree on unmounted portable media. Those are
point-in-time facts, and Forge does not prune the Git records.

Outside Git, the command returns the current directory as a one-member workspace. Bare-backed worktree families are
listed in full, with the bare repository as the primary record, but session counts are currently grouped per checkout in
those families because their stored `project_root` identity is not yet common across linked checkouts.

When forking `--into` another worktree, the child session lands at the **equivalent position** — if the parent was at
`monorepo/packages/app`, the child lands at `target-worktree/packages/app`. The target must have Forge enabled at that
path. Forge strict-checks that target root before routing/proxy preflight and again before manager writes.

---

## Artifact authority for managed sessions

Artifact authority separates sessions that may produce project changes from sessions intended only for inspection,
reasoning, planning, or review. It is an explicit property of a managed session, independent of provider, model,
consumer lane, and ordinary policy configuration:

- `advisory` denies covered runtime-tool requests before ordinary policy evaluation;
- `producer` is a positive human designation that allows the runtime to proceed to its normal permissions and policy;
- no designation means `unmarked`, which preserves legacy behavior and makes no authority claim.

The default advisory tier is `shell_closed`. For Claude, only the exact read and conversation/control tools printed by
`authority show` decline the authority gate; mutation, shell, delegation, skill, MCP, and unknown tools are denied. For
Codex, `Bash`, `apply_patch`, and unknown tools are denied, so a shell-closed advisory Codex run reasons over context
already in its conversation. The weaker `named_tools` tier denies only `Write`, `Edit`, `NotebookEdit`, and
`apply_patch`; its report names shell and external surfaces as uncovered.

### One-time runtime setup

Authority depends on the runtime delivering a Forge hook, so enable user-scoped runtime hooks before creating an
advisory session:

```bash
forge extension enable --scope user --runtime all
forge extension doctor --json

# Codex only: verifies enrollment by running one cheap codex exec turn
forge runtime preflight codex --verify-enrollment
```

Claude advisory launch requires the current executable Forge dispatcher and exactly one catch-all `authority-check`
registration. Codex advisory launch requires exactly one user-scope no-matcher `codex-policy-check` row with the
installed command bytes and timeout, then empirically verifies SessionStart enrollment on **every launch attempt**; each
headless resume turn therefore spends an additional Codex turn of latency and quota. Static registration is necessary
but not enough because an unenrolled Codex home silently omits hooks. Advisory sidecar launch is unsupported in v1.
Producer and unmarked sidecars retain their existing behavior.

### Assign, inherit, and inspect authority

Assign a role at creation or while an existing session is inactive:

```bash
forge session start planner --authority advisory
forge session start implementer --worktree --authority producer

forge session authority set existing --role advisory --tier shell_closed
forge session authority clear existing
forge session authority show existing --json
```

These are human control-plane operations. Authority-bearing creation, set, and clear refuse from inside any managed
session; set/clear also refuse a target that is launching or active. Unmarked launches keep their legacy best-effort
active registration, while the per-session authority lock prevents a concurrent designation during the child lifetime.
Stop the session, change it from another terminal, then resume. Generic `session set` and keyed `session reset` cannot
mutate authority intent.

Fresh resumes and forks inherit advisory authority and its tier. Producer authority is deliberately not inherited: a
derived child is unmarked unless the human gives it an explicit role, and an explicit child role wins before launch.
In-place resume rejects authority flags. `session adopt` also creates an unmarked session: stop the native client, adopt
it, set authority while inactive, and only then resume through Forge.

`authority show` is read-only. It reports configured role/tier, exact covered/read/control inventories, the locally
observed configuration epoch and denials, and one of four launch-support states: `verified`, `unverified`,
`unsupported`, or `not_running`. A marked session whose journal is missing or inconsistent reports its configuration
history as `unproven`; malformed journals are errors. An unreadable runtime active registry is also an error because
this command never repairs state; run `forge session list` to apply the registry's normal self-healing policy, then
retry. The local append-only journal is not tamper-proof.

### Human-courier planner/producer workflow

The supported v1 workflow keeps both the checkout and conversation independent:

```bash
forge session start planner --authority advisory
# Human reviews the planner's findings and ends the session.

forge session start implementer --worktree --authority producer
# Human gives the producer only the requirements/findings they choose.
```

Do not use `resume --fresh`, `fork`, or transfer context for this boundary: those are derivation surfaces and advisory
authority would inherit. Forge does not automatically courier a transcript, generated patch, transfer snapshot, or
model-curated handoff from advisory to producer.

The guarantee is intentionally narrow. During a preflighted Forge-managed advisory run, a functioning authority handler
denies every delivered request covered by the active tier, including malformed or unnormalizable mutation envelopes. It
does not provide OS-level read-only filesystems, protect against raw runtimes/editors/humans, prove byte authorship or
semantic independence, or decide admission. Runtime hook non-delivery, timeout, dispatcher failure, and a runtime
discarding valid deny output remain disclosed fail-open seams.

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
- records the session identity in the launch environment
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
- Forge injects its runtime hooks into the container's user settings on every launch; project `.claude` files are not
  rewritten
- indexing, memory, and shadow markers enqueued at Stop persist in the host queue for a later host `forge` drain
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

**Dispatch rules:**

- A session with no durable hook confirmation or usable transcript launches in place, including a never-launched session
  that carries only its pre-seeded UUID.
- A session with safe **resumable evidence** (hook confirmation or a usable transcript) reconnects in place when it is
  inactive. A pre-seeded UUID by itself is not enough evidence.
- If that resumable session appears active, resume fails unless `--force` is supplied; `--force` launches a new lineage
  child instead of attaching a second process to the active conversation.
- `--strategy` and `--depth` shape a fresh transfer child, so explicit uses require `--fresh`; omitted defaults do not
  change ordinary reattach. A positive `--depth N` bounds ancestry traversal, while `--depth all` follows the lineage to
  its terminal ancestor.

### Adopt a conversation you started outside Forge

You started `claude` or `codex` directly, the conversation turned out to matter, and now you want Forge to manage it.
Adoption binds a Forge session to that existing conversation instead of copying or replaying it. The Claude arm is
described first; [Adopting a Codex thread](#adopting-a-codex-thread) covers the differences.

```bash
# Run from the directory you launched the native session in
forge session adopt                                            # see what is adoptable here
forge session adopt 470b1a1b-202b-4ead-a3ea-d0dca69243f2 --name auth-spike
forge session resume auth-spike
```

Bare `forge session adopt` previews the unbound conversations launched from the current directory — id, when it was last
active, how many turns you took, and your first message — and names the directory it scanned. Already-adopted
conversations are omitted. The preview writes nothing and takes no binding flags; add `--json` for a scriptable shape.

You can also pass the id directly: it is the transcript filename without `.jsonl` under
`~/.claude/projects/<encoded-cwd>/`. Pass the full UUID, not a prefix.

**Why the directory matters:** Claude stores transcripts under an encoding of the launch directory, and that encoding is
lossy — `api.v2`, `api_v2`, and `api-v2` all collapse to the same folder. Adoption reads the directory recorded inside
the transcript and refuses to bind one that was launched elsewhere, so a sibling project's conversation cannot be
adopted by accident.

**What adoption does and does not do:**

- **Does**: bind the conversation to a new Forge session, and record where it came from under `confirmed.adoption`.
- **Does** (Claude only): copy the transcript into `.forge/artifacts/<name>/transcripts/` for search. Codex sessions
  record the live rollout path instead, exactly as Codex sessions Forge started itself do.
- **Does not**: attach hooks, env, policy, or supervision to a client that is already running. Those begin with the next
  Forge-managed `resume` or `--fresh` child.
- **Does not**: delete or move your original transcript or rollout — including when you later delete the adopted session
  or when automatic retention cleanup runs.

**Model pin (Claude only):** Forge infers the model from the transcript's last assistant turn. A conversation with no
assistant turn yet, or one on a model Forge's catalog does not know, is adopted without a pin and resumes on the current
direct default. Set one explicitly with `--model`, or later with `forge session resume <name> --model <model>`.

**If the conversation was active in the last 30 minutes**, Forge asks for confirmation: it cannot see whether a native
client is still attached, and adopting then resuming would put two clients on one conversation. Close the other client
first, or pass `--yes` if you know it is gone.

A conversation can only be adopted once — a second attempt names the session that already owns it.

#### Adopting a Codex thread

The same command adopts a native `codex` thread. Forge picks the runtime by looking for the id on disk — a Claude
transcript or a Codex rollout — so you pass the id and nothing else:

```bash
forge session adopt 019f0b65-b51c-7683-99c7-bb48107f7b83 --name codex-spike
forge session resume codex-spike --task "keep going"
```

Get the thread id from `codex resume --list`. Two differences from the Claude arm:

- **No preview.** Bare `forge session adopt` lists Claude conversations only. Codex files rollouts by date rather than
  by directory, so there is no per-directory listing to show.
- **No `--model`.** Codex resolves its own model; pin one per turn on `resume` instead.

The directory rule still applies: Codex records the launch directory inside the rollout, and adoption refuses to bind
one recorded elsewhere. If more than one rollout matches the thread id — or if one of them is unreadable, so Forge
cannot rule it out — adoption refuses rather than guessing which conversation you meant.

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

If the session is explicitly deleted while a Codex turn is still running, deletion wins. Forge returns the completed
turn result with a warning but does not recreate the manifest, index entry, or a lock-only session directory; the
post-turn Codex facts have nowhere to be saved.

**Context delivery (`--context-delivery`):** `initial-message` (default) prepends the curated transfer to the first
prompt without Codex hook setup. `hook` delivers it via a trust-enrolled Codex `SessionStart` hook instead
(`additionalContext`): use the [hooks-only user-scope recipe](hook.md#installing-runtime-hooks) to register the
dispatcher-backed Codex hook, then complete the one-time trust ceremony first. Enrollment can't be verified up front, so
Forge checks delivery **after** the turn via the hook's receipt and records the outcome in the manifest
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

Managed worktree creation checks the source pin before creating the checkout, then checks the equivalent target Forge
root before copying runtime config or writing project state. If a tracked target pin is incompatible, Forge removes the
new checkout and branch. Runtime config copying handles allowlisted directories file by file without following symlinked
directory components: tracked files and nested `.git`/`node_modules` content remain untouched, and dirty cleanup removes
only individually rechecked untracked files through symlink-free parents. It also excludes `.forge/project.toml`, so an
ignored source pin is not copied into the worktree and a tracked target pin remains authoritative. When
`fork --worktree --force` targets a stale Forge-owned child, Forge checks that child's existing pin, the exact
replacement commit, and branch safety before removing anything. A refusal preserves its checkout, branch, dirty files,
and session state.

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

`ai-curated` uses OpenRouter directly, always requires a ZDR endpoint, and requires `OPENROUTER_API_KEY`. Proxy-level
non-ZDR opt-outs do not apply. If OpenRouter auth or a ZDR route is unavailable, Forge warns and falls back to the
deterministic `structured` strategy.

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

**Supervisor runtime (lane):** By default the supervisor runs on `claude_code` (`claude -p --resume`). Pin
`--supervisor-runtime codex` (requires `--supervise`) to route checks to OpenAI's Codex instead; `claude_code` and
`codex` are the shipped runtimes.

```bash
# Fork with the supervisor running on codex
forge session fork planner --worktree --supervise --supervisor-runtime codex

# Or set the runtime on an existing supervised session
forge policy supervisor set planner --runtime codex
```

The runtime is **frozen on the first check** and immutable for the session: `set --runtime <other>` then refuses to
change it (re-pinning the same lane is a no-op). Fork or start a fresh session for a different lane, or run
`forge policy supervisor remove` (clears the binding) and re-add. `forge session fork` / `resume` carry the requested
lane to the child, which re-freezes on its own first check. See [policy.md](policy.md#supervisor-runtime-lane).

**Launch-time cascade and checker controls:** `fork` and `start` accept the same tier-1 cascade knobs as
`forge policy supervisor set`, so you can wire the cheap pre-check at launch instead of in a second command. All require
`--supervise`:

```bash
# Fork with the tier-1 plan check (cascade) and a specific checker model/provider
forge session fork planner --worktree --supervise \
  --cascade --checker-model google/gemini-3.7-flash --checker-provider openrouter

# Same knobs on session start
forge session start executor --supervise planner --cascade --checker-model google/gemini-3.7-flash
```

Launch-time `--cascade` only sets the flag; it does **not** resolve a plan eagerly. The runtime hook escalates to the
frontier supervisor when no plan exists yet. This differs from `forge policy supervisor set <target> --cascade` (or
`forge policy supervisor cascade on`), which resolves the plan at the time you run it.

**Reasoning effort:** `--supervisor-effort` sets the Claude arm's `claude --effort` (`low/medium/high/xhigh/max`); the
Codex arm does not consume this field. `--checker-effort` sets the tier-1 checker's reasoning effort
(`none/low/medium/high/xhigh`; the checker is an API call, not a `claude -p` subprocess). The two vocabularies are
distinct: `max` is invalid for the checker and `none` is invalid for the Claude supervisor arm.

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

Sessions can select and remember a launch route, but they do **not** own proxy tier maps or hyperparameters.

**Key principle:** Session intent owns the chosen model/source/template/tier; the selected proxy owns how that tier is
served. See [proxy.md](proxy.md) for proxy configuration.

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

### Select a model and route (`--model`)

```bash
forge session start review-pass --model claude-opus-4-8
forge session start long-sonnet --model claude-sonnet-5[1m]
forge session start analyst --model gpt-5.6-sol
forge session resume analyst --model gemini-3.1-pro-preview
forge session fork planner --name executor --model gpt-5.6-sol --model-tier opus
forge session incognito --model gpt-5.6-sol
```

On Claude-runtime `start`, `resume`, `fork`, and `incognito`, `--model` accepts a Forge catalog model id or alias. Forge
normalizes the request and chooses a launch route before starting Claude Code:

| Situation                                         | Result                                                               |
| ------------------------------------------------- | -------------------------------------------------------------------- |
| Explicit `--proxy <id-or-template>`               | That proxy is required; incompatibility is an error                  |
| Explicit `--no-proxy`                             | Direct Claude only; non-Claude models are rejected                   |
| Compatible persisted/inherited route              | The route is preserved                                               |
| New session with a Claude model and no route flag | Direct Claude, regardless of running proxies                         |
| New session with a non-Claude model               | First admissible packaged-catalog proxy; no fallback after selection |

If more than one proxy tier serves the request and no default decides it, add `--model-tier haiku|sonnet|opus`. It
requires `--model`; it does not select a second model. Direct Claude requests must use their intrinsic tier. Claude
`[1m]` aliases keep their transport behavior on bare resume and inherited fork; non-Claude `[1m]` is invalid. For a
proxied Claude route, the selected tier is what Claude sends to the proxy even when that tier differs from the model's
intrinsic family.

Forge stores the canonical request and resolved source/template/tier alongside the legacy Claude execution pin. A bare
resume reuses that route; if it is unavailable, Forge fails with recovery guidance rather than silently choosing another
provider. Replay also refuses a same-URL template substitution or a changed proven source. Use the reported
`--model ... --proxy ...` or `--model ... --no-proxy` command to replace malformed stored routing; explicit replacement
does not depend on reading that broken route first. An explicit `--model` authorizes replacement when an otherwise valid
inherited route cannot serve it. Before an explicit selection launches, one stderr line reports provider,
template/proxy, tier, effective model, and known billing posture. The billing value remains `unknown` when Forge has no
payer evidence.

Selecting a non-Claude model can create or start a paid proxy. `--no-launch --model ...` still resolves/starts the route
and persists intent, but invokes no child and writes no route event; the proxy remains independently managed. A
non-Claude main-session route cannot combine with `--subprocess-proxy`. Explicit sidecar/host-proxy modes and Codex
sessions reject this model-route surface, while `session adopt --model` remains a Claude-only native-conversation pin.

Forge `--model` is distinct from Claude Code's `/model`. The CLI flag decides durable routing before process launch;
`/model` changes Claude-native state inside the running conversation. For proxy-mode alternatives and tier ownership,
see [proxy.md](proxy.md#model-alternatives).

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

This records `intent.subprocess_proxy` and routes child jobs through the proxy. It is mutually exclusive with `--proxy`:
use `--proxy` when the main session itself should route through the proxy.

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

Launch runtime is immutable session identity. `session set` rejects `launch.runtime`, a parent `launch` object that
contains `runtime`, and `launch.*`; create a new session with `--runtime` instead. Whole-launch and nullable sibling
null clears remain supported, while `session reset launch.runtime` and `session reset launch` can remove stale illegal
overrides written by an older Forge.

The resolved `launch.model_route` is also not a mid-session override surface. Choose or replace it with `--model` on
`session start`, `resume`, `fork`, or `incognito`; `session set` rejects the route object, its leaves, and a parent
`launch` object carrying it. Keyed reset remains available to remove a stale route override written by an older Forge.

Artifact authority is intent, not an override. `session set` rejects `authority`, `authority.*`, and concrete authority
leaves; keyed `session reset` rejects the same paths. `session reset --all` only clears overrides and cannot remove
authority intent. Use `forge session authority set|clear` from outside a managed session while the target is inactive.

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
- artifact authority (`forge session authority ...`, inactive target only)
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
forge telemetry activity                      # current session
forge telemetry activity my-feature           # a named session (or Claude UUID)
forge telemetry activity my-feature --period week  # this week (default: today)
forge telemetry activity my-feature --period all   # full history
forge telemetry activity my-feature --json    # machine-readable
```

`today`, `week`, and `month` use the same process-local calendar as telemetry costs and traces, including IANA,
absolute/colon TZif, and POSIX-rule `TZ` forms.

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
`forge telemetry activity` totals fail-opens across the selected `--period` window.

> **Sidecar:** both surfaces work in sidecar mode when the session launched with a proxy id (the in-container usage
> ledger is mounted back to the host). A template-only sidecar shows only the policy-decision half.
>
> **Coverage:** model-call spend is session-attributed only when a session-tagged run tree or provider-session id can
> connect it to the session. Orphaned downstream records are not guessed into a session; the summary flags partial
> coverage rather than inventing attribution.

---

## Troubleshooting

### “I tried to change the model tier / LLM settings”

Use `--model <catalog-id>` and, only for an ambiguous proxy match, `--model-tier <haiku|sonnet|opus>` to select the
session's launch route. Sessions do not edit the chosen proxy's tier models or hyperparameter defaults; change those in
the proxy overlay or select a different proxy.

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

Explicit `--proxy` launch routes (`start`, `resume`, `fork`, `claude start`) use `ensure_proxy()`: it resolves via the
order above, auto-starts from a matching template when no proxy is running, then healthchecks. A name that matches
neither a running proxy nor a template fails with a `forge proxy template list` hint. `--supervisor-proxy` resolves the
same way.

A bare host `forge session resume <name>` preserves the exact proxy route recorded by the session and healthchecks its
endpoint and recorded identity before launching Claude. Forge does not silently replace a dead or mismatched proxy. The
error prints two recovery paths when the corresponding configuration is available: restart the recorded proxy with
`forge proxy start <proxy-id>`, or explicitly authorize template realization with
`forge session resume <name> --proxy <template>`. If `--fresh` or `--force` has already created a derived child before
the launch check fails, the error names the retained child. Resume that child after recovery rather than retrying the
parent, which would create another child.

### Sidecar specifics

- Sidecar sessions use a container-local proxy at `http://localhost:8085`
- `forge session shell [name]` only works for sessions started with `--sidecar`
- The project directory is mounted at `/workspace` inside the container
- Runtime hooks use the container's `forge` executable; custom sidecar images must keep `forge` on `PATH`

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

<!-- forge-env-vocab: diagnostic:start -->

| "Hooks lost session identity" | Hooks resolve via `FORGE_FORK_NAME` -> `FORGE_SESSION` -> UUID lookup (no dir
scanning) |

<!-- forge-env-vocab: diagnostic:end -->

| "Can't shell into session" | `forge session shell` only works for `--sidecar` sessions |
