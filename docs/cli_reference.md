# Forge CLI Reference

Command and direct-command inventory for Forge. Architecture and ownership rules live in [design.md](design.md);
workflow-layer behavior lives in [design_workflows.md](design_workflows.md).

---

## 1. Terminal Command Reference

**Command aliases:** `authentication` (canonical) has alias `auth`; `extension` (canonical) has alias `ext` and
`extensions`; `session` (canonical) has alias `sess`. Full names always work; aliases are convenience shortcuts.

**Command-shape policy:** Forge uses explicit verbs for all commands. Non-leaf groups print help when invoked without a
subcommand; they do not hide work behind bare group invocation. Leaf commands should do the sensible action when
optional arguments are omitted (for example, `forge proxy metrics` shows all proxies when more than one is registered).
Removed commands, options, and group-level shortcuts are clean breaks: they are deleted outright and the CLI framework
reports "no such command/option" — no tombstone shims. List/show commands support `--json` for scripting.

### Installation

| Command                   | Purpose                                                      |
| ------------------------- | ------------------------------------------------------------ |
| `forge extension enable`  | Install Forge extensions (commands, agents, hooks, settings) |
| `forge extension sync`    | Update existing installation to current version              |
| `forge extension disable` | Remove Forge installation cleanly                            |
| `forge extension status`  | Show installation status (`--json`)                          |

### Session management

| Command                                | Purpose                                                                                                                     |
| -------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| `forge session start [name]`           | Create and start a new session (auto-named if omitted)                                                                      |
| `forge session resume [name]`          | Reattach to an existing session (default), or derive a fresh child with `--fresh`                                           |
| `forge session fork <parent> [--name]` | Fork a session (same dir + native resume by default; `--worktree` to isolate, `--resume-mode transfer` for curated context) |
| `forge session show [session]`         | Show session details (`--json`, `--field`); accepts name or UUID                                                            |
| `forge session list`                   | List sessions (`--scope workspace\|project\|all`; default `workspace`; `--json`)                                            |
| `forge session set <key> <value>`      | Set a mid-session override                                                                                                  |
| `forge session reset [key]`            | Reset overrides to intent                                                                                                   |
| `forge session delete <name>...`       | Delete one or more sessions (`--all` for bulk deletion)                                                                     |
| `forge session clean --older-than N`   | Bulk-delete sessions older than N days                                                                                      |
| `forge session incognito [name]`       | Start an ephemeral session (auto-delete on exit)                                                                            |
| `forge session shell [name]`           | Open shell in sidecar container                                                                                             |

Note: `session context` is a deprecated alias for `session show`. `session resume --fresh --review` opens the per-child
user-notes overlay (`children/<child>.notes.md`) in `$EDITOR` before launching Claude; the AI snapshot stays read-only.
`forge session memory` is removed; use `forge memory`.

`fork` and `start` accept the tier-1 launch controls alongside `--supervise`: `--cascade`, `--checker-model`,
`--checker-provider`, `--checker-effort` (`none/low/medium/high/xhigh`), and `--supervisor-effort`
(`low/medium/high/xhigh/max`). Launch-time `--cascade` sets the flag only; the runtime hook escalates to the frontier
when no plan exists yet (unlike `forge policy supervise --cascade`, which resolves the plan eagerly). See
[session.md](end-user/session.md).

Codex runtime ([design.md §3.9](design.md#39-session-resume-context-management)):
`forge session start <name> --runtime codex` launches the interactive `codex` TUI (bare, or an interactive bridge with
`--resume-from <parent>`); adding `--task "…"` instead runs a headless first turn and requires `--resume-from`
(`--strategy` default `ai-curated`, `--sandbox` default `workspace-write`; Claude-only flags rejected).
`forge session resume <name>` reattaches the TUI; with `--task "…"` it runs the next headless `codex exec resume` turn.
`--task` is Codex-only.

### Transfer context

| Command                              | Purpose                                                                    |
| ------------------------------------ | -------------------------------------------------------------------------- |
| `forge transfer show <parent>`       | Show the parent AI cache, or a child's composed view (`--child`, `--json`) |
| `forge transfer regenerate <parent>` | Rebuild the parent cache only (defaults to its current strategy/depth)     |
| `forge transfer edit <parent>`       | Edit a child's user-notes overlay in `$EDITOR` (`--child`)                 |
| `forge transfer diff <parent>`       | Show cache-vs-child-snapshot drift (`--child`)                             |

`forge transfer` pairs with `forge memory` as the two halves of the former "handoff": `forge memory` curates project
docs; `forge transfer` assembles resume/fork context. Every verb takes a parent session argument. `show`/`regenerate`
default to the parent cache; `edit`/`diff` resolve a child (inferred when the parent has exactly one, else `--child`).

### Memory management

- `forge memory track <path>`: author a project passport on a doc, sessionless (`--strategy`, `--intent`, `--writers`,
  `--propose`, `--shadow-path`).
- `forge memory enable|disable`: toggle session memory auto-update (`--session`, resolves `$FORGE_SESSION`). `enable`
  takes `--effort` (`claude --effort` for the writer; updates effort even when already enabled in the same mode).
- `forge memory list`: list passported memory docs under scan roots (`--json`).
- `forge memory status`: show memory activation across sessions (`--scope`, `--json`).
- `forge memory report show`: inspect memory writer review reports for a session (`--latest`, `--all`).
- `forge memory shadows list|show|review`: list accumulated shadow proposals, inspect one doc's proposals, or curate
  them (`--scope`, `--for`, `--curate`, `--show-latest`, `--effort` with `--curate`).
- `forge memory passport show|remove`: inspect or remove the project passport embedded in a memory doc (`--json`).

### Proxy management

| Command                              | Purpose                                                                |
| ------------------------------------ | ---------------------------------------------------------------------- |
| `forge proxy create <template>`      | Create a proxy from template and start it                              |
| `forge proxy list`                   | List all proxies (`--json`)                                            |
| `forge proxy show <id>`              | Show proxy configuration (`--json`, `--raw`)                           |
| `forge proxy edit <id>`              | Edit proxy overlay in $EDITOR                                          |
| `forge proxy set <id> <key>=<value>` | Set a proxy configuration value                                        |
| `forge proxy start <id>`             | Start server for existing proxy                                        |
| `forge proxy stop <id>`              | Stop server (keeps config)                                             |
| `forge proxy delete <id>...`         | Delete one or more proxies (`--all` for bulk deletion)                 |
| `forge proxy clean`                  | Remove stale proxies (dead pids)                                       |
| `forge proxy validate <id>`          | Validate proxy configuration                                           |
| `forge proxy metrics [id]`           | Show runtime metrics (`--json`, `--all`)                               |
| `forge proxy costs show [id]`        | Show cost summary (`--period`, `--by-model`, `--by-verb`, `--json`)    |
| `forge proxy costs reset`            | Wipe cost, usage, upstream/downstream telemetry (`--yes`, `--dry-run`) |
| `forge proxy audit show [id]`        | Show redacted audit records (hashes/counts, no secrets)                |
| `forge proxy audit diff [id]`        | Show system/tool drift + override mutations over time                  |
| `forge proxy template list`          | List available templates                                               |
| `forge proxy template show <name>`   | Show template configuration (`--raw`)                                  |
| `forge proxy template edit <name>`   | Customize a template (copy-on-first-edit)                              |
| `forge proxy template reset <name>`  | Reset template to built-in defaults                                    |

### Provider trace

| Command                                     | Purpose                                                                                       |
| ------------------------------------------- | --------------------------------------------------------------------------------------------- |
| `forge provider trace list`                 | List recent OpenRouter traces (`--session`, `--root-run-id`, `--period`, `--limit`, `--json`) |
| `forge provider trace show <request_id>`    | Show one trace record (`--json`)                                                              |
| `forge provider trace explain <request_id>` | Local-only provenance narrative for a request (`--json`)                                      |

Metadata-only, owner-only diagnostics read from downstream telemetry under `~/.forge/telemetry/downstream/`. `explain`
answers "what happened to this request?" from local records only -- no remote lookup. `--session` matches the hashed
session *label*; use `--root-run-id` for an exact match.

### Claude Code management

| Command                           | Purpose                                     |
| --------------------------------- | ------------------------------------------- |
| `forge claude start --proxy <id>` | Launch Claude configured for a proxy        |
| `forge claude start --no-proxy`   | Launch Claude without proxy (Anthropic API) |
| `forge claude preset show`        | Show current settings preset (`--raw`)      |
| `forge claude preset edit`        | Edit settings preset in $EDITOR             |
| `forge claude preset reset`       | Reset preset to built-in defaults           |

### Backend management

| Command                                     | Purpose                                                               |
| ------------------------------------------- | --------------------------------------------------------------------- |
| `forge backend list`                        | List built-in backend sources and local runtime state (`--json`)      |
| `forge backend show <source-or-backend-id>` | Show source details or legacy runtime details (`--raw`)               |
| `forge backend test-auth <source-id>`       | Check source credentials and run a reachability/auth probe (`--json`) |
| `forge backend create <adapter>`            | Create local backend adapter config                                   |
| `forge backend start <source-or-adapter>`   | Start a local lifecycle source or adapter instance                    |
| `forge backend stop <source-or-adapter>`    | Stop a local lifecycle source or adapter instance                     |
| `forge backend delete <adapter>`            | Delete local backend instance or adapter config                       |

### Policy enforcement

| Command                                          | Purpose                                              |
| ------------------------------------------------ | ---------------------------------------------------- |
| `forge policy enable --bundle <name>`            | Enable policy enforcement for current session        |
| `forge policy disable`                           | Disable policy enforcement                           |
| `forge policy status`                            | Show current policy state (`--json`)                 |
| `forge policy list`                              | List available bundles and rules (`--json`)          |
| `forge policy check --bundle <name> -f <path>`   | Evaluate policies on demand                          |
| `forge policy supervisor -f <path> -r <id>`      | Evaluate file against approved plan                  |
| `forge policy supervise <target>`                | Set persistent supervisor for session                |
| `forge policy supervise --cascade/--no-cascade`  | Toggle the tier-1 plan check (cascade)               |
| `forge policy supervise --checker-effort <lvl>`  | Tier-1 checker effort (`none/low/medium/high/xhigh`) |
| `forge policy supervise --supervisor-effort <l>` | Frontier effort (`low/medium/high/xhigh/max`)        |
| `forge policy supervise --off / --on`            | Suspend/resume supervisor (preserves config)         |
| `forge policy supervise --remove`                | Remove supervisor entirely                           |
| `forge policy supervise --reload`                | Reload latest relevant approved plan                 |
| `forge policy supervise --reload-from <path>`    | Reload plan from explicit file                       |
| `forge policy shadow show [session]`             | Show shadow-audit disagreements (`--all`/`--json`)   |

### Workflow

| Command                              | Purpose                                    |
| ------------------------------------ | ------------------------------------------ |
| `forge workflow panel [targets]`     | Fan out review to multiple models          |
| `forge workflow analyze [topic]`     | Deep single-model analysis                 |
| `forge workflow debate [subject]`    | Adversarial evaluation with stance workers |
| `forge workflow consensus [subject]` | Two-round multi-model convergence          |
| `forge workflow list-models`         | Show available model backends              |

Workflow model specs support proxy-backed workers and explicit direct Claude workers. The stable `claude-opus` worker is
kept on Claude Opus 4.6; newer direct workers such as `claude-opus-4.8` are opt-in and can attach per-worker prompt
hints through `ModelSpec.prompt`. All workflow execution commands (panel, analyze, debate, consensus) accept
`--proxy <proxy_id>` to route proxy-backed workers through a specific proxy, overriding preferred_proxy and route scan
([design.md §3.6.12](design.md#3612-subprocess-routing-resolution-normative)). All four execution commands also accept
`--effort <level>` (`claude --effort`: `low/medium/high/xhigh/max`), applied to every worker's `claude -p` argv. Direct
workers (e.g., `claude-opus`) remain on Anthropic routing regardless of `--proxy`.

### Search

| Command                      | Purpose                              |
| ---------------------------- | ------------------------------------ |
| `forge search query <query>` | Search transcripts                   |
| `forge search rebuild-index` | Full index rebuild from artifacts    |
| `forge search status`        | Show index statistics                |
| `forge search clean`         | Remove orphaned documents from index |

### System

| Command                       | Purpose                                                                                              |
| ----------------------------- | ---------------------------------------------------------------------------------------------------- |
| `forge info`                  | Show global system information (`--json`)                                                            |
| `forge activity [session]`    | Per-session two-pane activity: operation outcomes + model calls/cost (`--json`, `--days`, `--all`)   |
| `forge clean`                 | Remove orphaned state (`--scope`, `--yes`)                                                           |
| `forge config`                | Manage global runtime preferences                                                                    |
| `forge authentication login`  | Store credentials for LLM providers                                                                  |
| `forge authentication status` | Show credential status per provider                                                                  |
| `forge logs`                  | Show log file locations/status; notes per-proxy request-diagnostics capture (redacted, no plaintext) |

### Internal (hidden from `forge --help`)

| Command                   | Purpose                                       |
| ------------------------- | --------------------------------------------- |
| `forge hook <name>`       | Hook dispatcher (SessionStart, Stop, etc.)    |
| `forge status-line`       | Generate status line output                   |
| `forge memory-writer run` | Run the memory writer for a completed session |

**Design principles:**

- **Narrow global config** -- `forge config` owns runtime preferences only; routing stays per-proxy and workflow state
  stays per-session
- **Explicit verbs** -- non-leaf groups print help; leaves perform the action
- **Launch through Forge** -- `forge session start`, `forge session resume`, or `forge claude start --proxy` sets up env
  vars correctly

---

## 2. Direct Command Reference

Extracted from [design.md §3.11](design.md#311-direct-commands-userpromptsubmit-dispatcher). Design goal, mechanism, and
scope rationale remain in design.md.

### 2.1 Scope policy table

- **Session / plan**: allow `%session list` and `%plan`.
- **Proxy**: allow read-only `%proxy list`, `%proxy show`, and `%proxy audit show/diff`; disallow `%proxy create`,
  `%proxy edit`, `%proxy set`, and `%proxy delete`.
- **Provider trace**: allow read-only `%provider trace list`, `%provider trace show`, and `%provider trace explain`
  (metadata only, never secrets).
- **Policy / verification**: allow `%policy status`, `%policy enable`, `%policy disable`, `%policy check`,
  `%policy supervise`, and `%cancel-verification`.
- **Cleanup**: allow `%clean [--scope workspace|project|all]` as a read-only report. Destructive cleanup stays in the
  terminal via `forge clean --yes`.
- **Utilities / config**: allow `%h`, `%help`, and `%config`.

### 2.2 Current shipped commands

%-only utilities:

- `%h` / `%help`: show direct command help
- `%config`: show effective runtime config (read-only)

Shared commands (mirrors CLI syntax):

- `%session list` (calls the same command-core op as `forge session list`)
- `%plan` (shows the current session's recorded plan file path)
- `%proxy list` (read-only: shows available proxies)
- `%proxy show <id>` (read-only: shows proxy details and tier mappings)
- `%proxy audit show|diff [id]` (read-only: recent audit metadata / wire changes; metadata only, never secrets)
- `%provider trace list|show|explain` (read-only: recent provider traces / one record / local provenance narrative)
- `%policy status` (shows current policy config and state)
- `%policy enable --bundle tdd [--permissive]` (enables policy enforcement)
- `%policy disable` (disables all policies for the session)
- `%policy check [--staged] [--bundle <name>]` (diagnostic policy evaluation against git diff)
- `%policy supervise <target>` (set supervisor), `off` (suspend), `on` (resume), `remove` (delete)
- `%policy supervise reload [path]` (reload latest approved plan, or from explicit path)
- `%cancel-verification` (bypasses the active Stop-hook verification loop)
- `%clean [--scope workspace|project|all]` (read-only: shows orphaned state report, default scope=project)

---
