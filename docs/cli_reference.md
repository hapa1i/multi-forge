# Forge CLI Reference

Command and direct-command inventory for Forge. Architecture and ownership rules live in [design.md](design.md);
workflow-layer behavior lives in [design_workflows.md](design_workflows.md).

---

## 1. Terminal Command Reference

**Command aliases:** `extension` (canonical) has alias `ext`; `session` has alias `sess`; `memory` has alias `mem`;
`config` has alias `cfg`. Full names always work; aliases are convenience shortcuts. Credential management is
canonically `forge auth` (there is no `authentication` alias).

**Command-shape policy:** Forge uses explicit verbs for all commands. Non-leaf groups print help when invoked without a
subcommand; they do not hide work behind bare group invocation. Leaf commands should do the sensible action when
optional arguments are omitted (for example, `forge proxy metrics` shows all proxies when more than one is registered).
Removed commands, options, and group-level shortcuts are clean breaks: they are deleted outright and the CLI framework
reports "no such command/option" — no tombstone shims. List/show commands support `--json` for scripting.

### Installation

| Command                           | Purpose                                                                                                                   |
| --------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| `forge extension enable`          | Install Forge extensions; user scope installs runtime hooks, project/local installs project settings and enrolls the root |
| `forge extension sync`            | Update existing installation to current version                                                                           |
| `forge extension cleanup-project` | Preview/apply one legacy project-hook migration (`--root`, `--yes`)                                                       |
| `forge extension disable`         | Remove Forge installation cleanly                                                                                         |
| `forge extension status`          | Show installation status (`--json`)                                                                                       |
| `forge extension doctor`          | Report install, dispatcher/dev override, hook migration, registry, and compatibility status (`--json`)                    |

`forge extension cleanup-project [--root <dir>] [--yes]` targets one Forge root. The default invocation is a read-only
preview that lists settings/config removals, backups, tracking reconciliation, user runtime registration, and final
registry activation. `--yes` recomputes the plan and applies it; ambiguous registrations or invalid selected/global
state exit non-zero without a preflight write. If cleanup has begun and user registration or final enrollment fails, the
command retains backups and prints the exact retry command for the temporary hooks-off state. There is no `--json` mode;
`forge extension doctor --json` is the scriptable diagnostic surface.

Doctor reports `FORGE_DEV` under `hook_dispatcher.dev_override` as
`{present: bool, value: string|null, target: string|null, valid: bool, effective: bool, advice: string|null}`. `valid`
means the value names an absolute checkout whose `.venv/bin/forge` is executable; `effective` also requires the
installed dispatcher to be current and executable. This is environment-derived state for the doctor process, not proof
that a separately launched hook inherited the same value. Host runtime registrations invoke the absolute
`<forge-home>/bin/forge-hook <name>` command. With `FORGE_DEV` present, that dispatcher uses only the checkout target;
otherwise it resolves `forge` from `runtime.json` and then known user-tool directories, independent of inherited `PATH`.
`on_path_minimal` reports bare `forge` reachability for consumers such as project `statusLine`, not dispatcher health.

User-scope `enable`/`sync` may report one cleanup command per tracked legacy root, but never opens, edits, or enrolls
those roots. Doctor reports `runtime_hooks.cleanup_required` and `legacy_registrations` independently from
`double_fire_risk`. `forge extension status` remains the installation/tracking view and does not report migration state.

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
| `forge session clean --older-than N`   | Preview sessions older than N days; `--yes` to delete                                                                       |
| `forge session incognito [name]`       | Start an ephemeral session (auto-delete on exit)                                                                            |
| `forge session shell [name]`           | Open shell in sidecar container                                                                                             |

Note: `session resume --fresh --review` opens the per-child user-notes overlay (`children/<child>.notes.md`) in
`$EDITOR` before launching Claude; the AI snapshot stays read-only. Session-scoped memory activation lives under
`forge session memory` (enable/disable/status/report); top-level `forge memory` keeps the project-doc passport verbs.
Session transfer context lives under `forge session transfer`.

Rewind resume is available on Claude sessions with `--strategy rewind --drop-last N`.
`forge session resume <parent> --fresh --strategy rewind --drop-last N` may create a same-directory child: Forge writes
a fresh truncated transcript UUID and resumes that UUID, not the parent's.
`forge session fork <parent> --worktree|--into <path> --strategy rewind --drop-last N` is cross-directory only;
same-directory and sidecar rewind forks are rejected. If the code-delta curation step fails, Forge falls back to plain
native resume/native-relocate and prints a code-delta-unavailable note.

`fork` and `start` accept the tier-1 launch controls alongside `--supervise`: `--cascade`, `--checker-model`,
`--checker-provider`, `--checker-effort` (`none/low/medium/high/xhigh`), `--supervisor-effort`
(`low/medium/high/xhigh/max`), and `--supervisor-runtime` (`claude_code/codex` -- the supervisor's consumer lane, frozen
at its first policy check; a fork's child gets its own binding). Launch-time `--cascade` sets the flag only; the runtime
hook escalates to the frontier when no plan exists yet (unlike `forge policy supervisor set <target> --cascade` or
`forge policy supervisor cascade on`, which resolves the plan eagerly). See [session.md](end-user/session.md).

Codex runtime ([design.md §3.9](design.md#39-session-resume-context-management)):
`forge session start <name> --runtime codex` launches the interactive `codex` TUI (bare, or an interactive bridge with
`--resume-from <parent>`); adding `--task "…"` instead runs a headless first turn and requires `--resume-from`
(`--strategy` default `ai-curated`, `--sandbox` default `workspace-write`; Claude-only flags rejected).
`forge session resume <name>` reattaches the TUI; with `--task "…"` it runs the next headless `codex exec resume` turn.
`--task` is Codex-only.

### Session transfer context

| Command                                      | Purpose                                                                    |
| -------------------------------------------- | -------------------------------------------------------------------------- |
| `forge session transfer show <parent>`       | Show the parent AI cache, or a child's composed view (`--child`, `--json`) |
| `forge session transfer regenerate <parent>` | Rebuild the parent cache only (defaults to its current strategy/depth)     |
| `forge session transfer edit <parent>`       | Edit a child's user-notes overlay in `$EDITOR` (`--child`)                 |
| `forge session transfer diff <parent>`       | Show cache-vs-child-snapshot drift (`--child`)                             |

`forge session transfer` and `forge memory` are the two halves of session continuity: `forge memory` curates project
docs; `forge session transfer` assembles resume/fork context. Every verb takes a parent session argument.
`show`/`regenerate` default to the parent cache; `edit`/`diff` resolve a child (inferred when the parent has exactly
one, else `--child`).

### Memory management

Project-doc passports (project-scoped, git-tracked; sessionless):

- `forge memory track <path>`: author a project passport on a Markdown doc, sessionless (`--strategy`, `--intent`,
  `--writers`, `--propose`, `--shadow-path`). A new passport also receives missing `type`, `title`, and `description`
  envelope fields; re-track does not migrate an existing passport.
- `forge memory list`: list passported memory docs under scan roots (`--json`).
- `forge memory shadows list|show|review`: list accumulated shadow proposals, inspect one doc's proposals, or curate
  them (`--scope`, `--for`, `--curate`, `--show-latest`, `--effort` with `--curate`).
- `forge memory passport show|remove`: inspect or remove the project passport embedded in a memory doc (`--json`).
  Removal deletes only `forge_memory`; outer metadata remains.
- `forge memory passport upgrade <path>`: explicitly add missing envelope fields to an existing valid Markdown passport.
  The raw `forge_memory` value is preserved, and an already-complete envelope is an exit-0 no-op.

### Session memory

Session-scoped activation and reports (whether the memory writer runs for a session):

- `forge session memory enable|disable`: toggle session memory auto-update (`--session`, resolves the current session).
  `enable` takes `--effort` (`claude --effort` for the writer; updates effort even when already enabled in the same
  mode).
- `forge session memory status`: show memory activation across sessions (`--scope`, `--json`).
- `forge session memory report`: inspect memory writer review reports for a session (`--latest`, `--all`, `--json`).
  `--json` emits the latest report's path + content, or the report list under `--all`. Flattened leaf (the former
  `forge memory report show`).

### Session lane

Per-consumer lane placement (session-owned `intent.consumer_lanes`). An explicit supervisor lane freezes at the first
registered policy check; auxiliary-consumer lanes freeze at first real dispatch. Binds a Forge LLM-work consumer --
`supervisor`, `memory_writer`, `shadow_curation`, `team_supervisor` (hyphens accepted) -- to a
`(runtime, backend, model)` lane:

- `forge session lane set --consumer <id>` (`--runtime`, `--backend`, `--session`): record a consumer's requested lane.
  `--backend claude-max` attributes a keyless+direct run to a Claude Max subscription
  (`billing_mode=subscription_quota`); rejected once a *different* lane is frozen. The general surface for all four
  consumers -- the supervisor also has `forge policy supervisor set <target> --runtime/--backend` (same slot).
  `--runtime codex` selects a real `codex exec` dispatch arm, but only for consumers that declare a codex lane -- the
  `supervisor` (T4), `shadow_curation` (T6b, read-only), and `memory_writer` (T6c, read-only for review-only /
  workspace-write for augment); only `team_supervisor` has no codex lane and rejects it.
- `forge session lane show` (`--session`, `--json`): each consumer's requested (`intent`) and frozen (`confirmed`) lane,
  flagging drift and (supervisor-only) a T7 `degraded` overlay when its spent codex lane is routed to the default.
- `forge session lane clear --consumer <id>` (`--session`): drop a consumer's requested lane (an already-frozen binding
  stays until it resets next session).

### Proxy management

| Command                              | Purpose                                                 |
| ------------------------------------ | ------------------------------------------------------- |
| `forge proxy create <template>`      | Create a proxy from template and start it               |
| `forge proxy list`                   | List all proxies (`--json`)                             |
| `forge proxy show <id>`              | Show proxy configuration (`--json`, `--raw`)            |
| `forge proxy edit <id>`              | Edit proxy overlay in $EDITOR                           |
| `forge proxy set <id> <key>=<value>` | Set a proxy configuration value                         |
| `forge proxy start <id>`             | Start server for existing proxy                         |
| `forge proxy stop <id>`              | Stop server (keeps config)                              |
| `forge proxy delete <id>...`         | Delete one or more proxies (`--all` for bulk deletion)  |
| `forge proxy validate <id>`          | Validate proxy configuration                            |
| `forge proxy metrics [id]`           | Show runtime metrics (`--json`; aggregates all when >1) |
| `forge proxy audit show [id]`        | Show redacted audit records (hashes/counts, no secrets) |
| `forge proxy audit diff [id]`        | Show system/tool drift + override mutations over time   |
| `forge proxy template list`          | List available templates                                |
| `forge proxy template show <name>`   | Show template configuration (`--raw`)                   |
| `forge proxy template edit <name>`   | Customize a template (copy-on-first-edit)               |
| `forge proxy template reset <name>`  | Reset template to built-in defaults                     |

### Telemetry

`forge telemetry` groups operator observability surfaces: per-session activity, proxy-scoped cost telemetry, and local
provider traces. `activity` is best-effort per-session attribution; `costs show` is the authoritative proxy-scoped spend
view. JSON output from activity/cost views includes `skipped_legacy_schema` when older downstream telemetry was fenced
from the current backend-instance schema instead of reattributed.

| Command                                      | Purpose                                                                                                                    |
| -------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| `forge telemetry activity [session]`         | Per-session two-pane activity: operation outcomes + model calls/cost/lane (`runtime`/`billing_mode`; `--json`, `--period`) |
| `forge telemetry costs show [id]`            | Show cost summary (`--period`, `--by-model`, `--by-verb`, `--json`)                                                        |
| `forge telemetry costs reset`                | Wipe cost, usage, upstream/downstream telemetry (`--yes`, `--dry-run`)                                                     |
| `forge telemetry trace list`                 | List recent provider traces (`--session`, `--root-run-id`, `--period`, `--limit`, `--json`)                                |
| `forge telemetry trace show <request_id>`    | Show one trace record (`--json`)                                                                                           |
| `forge telemetry trace explain <request_id>` | Local-only provenance narrative for a request (`--json`)                                                                   |

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

### Codex management

| Command                          | Purpose                                                                                      |
| -------------------------------- | -------------------------------------------------------------------------------------------- |
| `forge codex status`             | Inspect Codex binary, config, and Forge hook registration (`--scope`, `--all`, `--json`)     |
| `forge codex start --proxy <id>` | Launch the Codex TUI routed through a Responses-capable proxy (`--sandbox`, `-- codex-args`) |

`status` is read-only and reports registration from a static config read; it never claims enrollment. Default scope is
the detected Forge install scope (else user); `--scope user|project|local` and `--all` widen it. Prove enrollment
empirically with `forge runtime preflight codex --verify-enrollment`.

`start --proxy <id-or-template>` launches the Codex TUI routed through a Responses-capable proxy
(`wire_shape: openai_responses_passthrough` + a `responses_ingress` source). It is **sessionless and scrubbed** — the
proxy owns upstream auth, so no native codex/OpenAI login is required or leaked. It hard-blocks a codex older than the
proxy-contract-validated version (≥0.141.0) before starting a proxy, auto-defaults `-m` from the proxy's default tier
(override with `-- -m <model>`), and accepts `--sandbox read-only|workspace-write|danger-full-access` (default
`workspace-write`). For direct use without a proxy, run native `codex`.

### Model management

`forge model catalog` lists Forge's static model catalog: canonical model ids, aliases, provider defaults, context
windows, and model capabilities. `forge workflow list-models` is separate: it checks runtime readiness for workflow
runners.

| Command                                          | Purpose                                                                                    |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------ |
| `forge model catalog`                            | List the static model catalog (`--json`)                                                   |
| `forge model backend list`                       | List model backends and managed local processes (`--json`)                                 |
| `forge model backend show <backend-or-process>`  | Show backend details or managed process details (`--raw`)                                  |
| `forge model backend test-auth <backend>`        | Check backend credentials and run a reachability/auth probe (`--json`)                     |
| `forge model backend create <adapter>`           | Create local backend adapter config                                                        |
| `forge model backend start <backend-or-adapter>` | Start a local lifecycle backend or adapter config                                          |
| `forge model backend stop <process-id>...`       | Stop live managed local processes by id, or all with `--all`                               |
| `forge model backend delete <adapter>`           | Delete local backend adapter config, stopping matching managed processes first             |
| `forge model backend reconcile <backend>`        | Join local telemetry to a backend's remote record (`--request-id`/`--remote-id`, `--json`) |

### Policy enforcement

| Command                                                        | Purpose                                                                                                                                                                                         |
| -------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `forge policy enable --bundle <name>`                          | Enable policy enforcement for current session                                                                                                                                                   |
| `forge policy disable`                                         | Disable policy enforcement                                                                                                                                                                      |
| `forge policy status`                                          | Show current policy state (`--json`)                                                                                                                                                            |
| `forge policy list`                                            | List available bundles and rules (`--json`)                                                                                                                                                     |
| `forge policy check --bundle <name> -f <path>`                 | Evaluate policies on demand                                                                                                                                                                     |
| `forge policy supervisor status`                               | Show supervisor config + the bound `(runtime, backend, model)` lane (frozen binding, else intent/default; `not executable` on drift; T7 `degraded` line when the codex lane is spent; `--json`) |
| `forge policy supervisor evaluate -f <path> -r <id>`           | Evaluate file against approved plan                                                                                                                                                             |
| `forge policy supervisor set <target>`                         | Set persistent supervisor for session                                                                                                                                                           |
| `forge policy supervisor cascade on/off`                       | Toggle the tier-1 plan check (cascade)                                                                                                                                                          |
| `forge policy supervisor cascade on --checker-effort <lvl>`    | Tier-1 checker effort (`none/low/medium/high/xhigh`); also on `set`                                                                                                                             |
| `forge policy supervisor set <target> --supervisor-effort <l>` | Frontier effort (`low/medium/high/xhigh/max`)                                                                                                                                                   |
| `forge policy supervisor set <target> --runtime <r>`           | Set the supervisor consumer lane (`claude_code/codex`); rejected once the lane is frozen                                                                                                        |
| `forge policy supervisor set <target> --backend <b>`           | Set the supervisor lane backend (`claude-max` = Max subscription billing); rejected once the lane is frozen                                                                                     |
| `forge policy supervisor off / on`                             | Suspend/resume supervisor (preserves config)                                                                                                                                                    |
| `forge policy supervisor remove`                               | Remove supervisor entirely                                                                                                                                                                      |
| `forge policy supervisor reload`                               | Reload latest relevant approved plan                                                                                                                                                            |
| `forge policy supervisor reload --from <path>`                 | Reload plan from explicit file                                                                                                                                                                  |
| `forge policy shadow show [session]`                           | Show shadow-audit disagreements (`--all`/`--json`)                                                                                                                                              |
| `forge policy shadow status [session]`                         | Show shadow sample rate + pending/done audit counts (`--json`)                                                                                                                                  |

### Workflow

| Command                              | Purpose                                    |
| ------------------------------------ | ------------------------------------------ |
| `forge workflow panel [targets]`     | Fan out review to multiple models          |
| `forge workflow analyze [topic]`     | Deep single-model analysis                 |
| `forge workflow debate [subject]`    | Adversarial evaluation with stance workers |
| `forge workflow consensus [subject]` | Two-round multi-model convergence          |
| `forge workflow list-models`         | Show available workflow models             |

Workflow model specs support proxy-backed workers and explicit direct Claude workers. The default `claude-opus` worker
resolves to Claude Opus 4.8; the older `claude-opus-4.6` worker is opt-in, and explicit workers can attach per-worker
prompt hints through `ModelSpec.prompt`. All workflow execution commands (panel, analyze, debate, consensus) accept
`--proxy <proxy_id>` to route proxy-backed workers through a specific proxy, overriding preferred_proxy and route scan
([design.md §3.6.12](design.md#3612-subprocess-routing-resolution-normative)). All four execution commands also accept
`--effort <level>` (`claude --effort`: `low/medium/high/xhigh/max`), applied to every worker's `claude -p` argv. Direct
workers (e.g., `claude-opus`) remain on Anthropic routing regardless of `--proxy`.

### Search

| Command                      | Purpose                                                         |
| ---------------------------- | --------------------------------------------------------------- |
| `forge search query <query>` | Search transcripts (table; `--json` for JSON)                   |
| `forge search rebuild-index` | Full index rebuild from artifacts                               |
| `forge search status`        | Show index statistics                                           |
| `forge search clean`         | Preview orphaned documents; `--yes` to prune; `--json` for JSON |

### System

| Command             | Purpose                                                                                                         |
| ------------------- | --------------------------------------------------------------------------------------------------------------- |
| `forge info`        | Show global system information (`--json`)                                                                       |
| `forge clean`       | Preview/remove orphaned state (`--scope`, `--yes`, `--json`)                                                    |
| `forge config`      | Manage global runtime preferences                                                                               |
| `forge auth login`  | Store credentials for LLM providers                                                                             |
| `forge auth status` | Show credential status per provider                                                                             |
| `forge logs show`   | Show log file locations/status (`--json`); notes per-proxy request-diagnostics capture (redacted, no plaintext) |
| `forge logs clean`  | Preview log cleanup; `--yes` to remove files; `--older-than DAYS` to filter by age                              |

`forge clean --yes --json` still emits its result object on stdout and exits 1 when either `failed` or
`skipped_project_compatibility` is non-empty.

### Internal (hidden from `forge --help`)

| Command                   | Purpose                                                         |
| ------------------------- | --------------------------------------------------------------- |
| `forge hook <name>`       | Hidden hook-handler surface invoked by the installed dispatcher |
| `forge status-line`       | Generate status line output                                     |
| `forge memory-writer run` | Run the memory writer for a completed session                   |

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
- **Policy / verification**: allow `%policy status`, `%policy enable`, `%policy disable`, `%policy check`,
  `%policy supervisor`, and `%cancel-verification`.
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
- `%policy status` (shows current policy config and state)
- `%policy enable --bundle tdd [--permissive]` (enables policy enforcement)
- `%policy disable` (disables all policies for the session)
- `%policy check [--staged] [--bundle <name>]` (diagnostic policy evaluation against git diff)
- `%policy supervisor <target>` (set supervisor), `off` (suspend), `on` (resume), `remove` (delete)
- `%policy supervisor reload [path]` (reload latest approved plan, or from explicit path)
- `%cancel-verification` (bypasses the active Stop-hook verification loop)
- `%clean [--scope workspace|project|all]` (read-only: shows orphaned state report, default scope=project)

---
