# Forge Design (Unified Architecture)

- **Session manager usage**: [session.md](end-user/session.md) (session management guide)
- **Memory writer usage**: [memory.md](end-user/memory.md) (automatic memory docs guide)
- **Search usage**: [search.md](end-user/search.md) (transcript search guide)
- **Skills usage**: [skills.md](end-user/skills.md) (review, understand, panel guide)
- **Workflow design**: [design_workflows.md](design_workflows.md) (policy, skills, workflow runners, memory writer)
- **CLI reference**: [cli_reference.md](cli_reference.md) (terminal and direct-command inventory)
- **Visual diagrams**: [diagrams.md](diagrams.md) (architecture diagrams)
- **Reference details**: [design_appendix.md](design_appendix.md) (schemas, config tables, runtime specifics)

## 1. Philosophy: The "Glue" Approach

Forge is **not** a monolith. It is the **connective tissue** between specialized tools -- a monorepo of tools sharing
common libraries (Auth, Models, State) under a unified interface (`forge` CLI).

## 2. Core components (the "pieces")

These components run independently but share code (libraries/config).

| Component           | Responsibility                     | Location                    |
| :------------------ | :--------------------------------- | :-------------------------- |
| **Forge Proxy**     | Model routing, Auth, Tool fixing   | `src/forge/proxy/`          |
| **Forge Session**   | Session isolation, Worktrees       | `src/forge/session/`        |
| **Forge Skills**    | Agent workflows (Review, Planning) | `src/skills/` + `forge` CLI |
| **Forge Status**    | Visual feedback & Dashboard        | `src/forge/status/`         |
| **Forge Policy**    | Policy enforcement (TDD, safety)   | `src/forge/policy/`         |
| **Commands/Agents** | Claude Code extensions             | `src/{commands,agents}/`    |
| **Hooks**           | Lifecycle events (Claude Code)     | `src/forge/cli/hooks/`      |

> See [diagrams.md §1: Core Architecture Overview](diagrams.md#1-core-architecture-overview) for a visual overview.

## 3. Shared contracts: File-based state system

Forge uses file-based state instead of a DB. Two concepts are first-class and **must not be conflated**:

- **Session**: a Claude coding session (worktree, artifacts, user intent, hook-confirmed facts)
- **Proxy**: a proxy endpoint identity (base URL / port / template) that the proxy can actually enforce

> **Why proxy instances?** Claude Code proxy requests do **not** include a session identifier, so the proxy cannot know
> which session made a request. The only way to apply different routing or hyperparameters is to run separate proxy
> instances on different ports. A **proxy instance** is one such endpoint (base_url + port + template). Sessions
> reference proxies but cannot change proxy-owned routing—this is a technical constraint, not a design choice.

> See [diagrams.md §2: Session vs Proxy Separation](diagrams.md#2-session-vs-proxy-separation) for a visual explanation.

The **Proxy Orchestrator** lives in the Forge CLI (`forge proxy` subcommands). It manages proxy lifecycle: start
instances, register them in the proxy registry, and clean up stale proxies.

Forge uses a **three-part** contract:

1. **Session file** (per Forge project): `<forge_root>/.forge/sessions/<session_name>/forge.session.json`
2. **Proxy registry** (global): `~/.forge/proxies/index.json` → running proxies (template ↔ base_url ↔ pid)
3. **Runtime truth** (proxy mode only): live proxy introspection (`GET /` at the proxy base URL)

> **Clarification:** The session file is for **session UX** (artifacts, status, `forge session` commands), **not** proxy
> routing. The proxy's routing identity is the **proxy base URL** only.
>
> **Parallel sessions:** Multiple sessions can run in the same Forge project. Each session has its own subdirectory
> under `.forge/sessions/`. Hooks identify the session via `FORGE_SESSION` set at launch.

The `FORGE_*` launch environment is a tiered interface: a few names are public or public-diagnostic, while launcher
wiring remains internal vocabulary. The classification table lives in
[design_appendix.md §A.7b](design_appendix.md#a7b-forge-env-var-vocabulary).

#### Project identity model

Forge has four scoping levels. They must be explicitly defined to avoid path confusion:

```text
project_root    (logical repo -- git identity, shared across worktrees)
  +-- checkout_root    (this worktree -- git rev-parse --show-toplevel)
       +-- forge_root      (enabled project/local extension root with .forge/ state)
            +-- working_dir    (launch CWD -- for managed sessions, equals forge_root)
```

| Level             | Identity source                                  | Stored as       | Purpose                                               |
| ----------------- | ------------------------------------------------ | --------------- | ----------------------------------------------------- |
| **Logical Repo**  | `get_main_repo_root()` (git)                     | `project_root`  | Cross-project ops, `session list` default scope       |
| **Checkout**      | `git rev-parse --show-toplevel`                  | `checkout_root` | Worktree targeting for `--into`, relative_path anchor |
| **Forge Project** | Successful project/local extension enable        | `forge_root`    | Session root, artifact root, state scoping anchor     |
| **Working Dir**   | Launch CWD (= `forge_root` for managed sessions) | implicit        | Managed sessions always launch from `forge_root`      |

**Four foundational rules (normative):**

1. A session may start only where `forge extension enable` has established a project/local install (`.forge/` exists).
2. The session root is exactly that install root (the **Forge project root**, `forge_root`).
3. Session state is scoped to `forge_root` -- manifests, artifacts, search index, `prev_sessions/` all live under that
   `.forge/`.
4. Project/local `forge extension enable` creates `.claude/` only when the resolved plan mutates a Claude extension or
   settings surface. A skills-only project install explicitly targeting Codex can establish `.forge/` plus
   `.agents/skills/` without creating `.claude/`. User scope has no project anchor; each runtime uses its own user skill
   target.

`.forge/project.toml` is an optional compatibility guardrail, not part of project identity. Missing means unconstrained
and is silent. Compatibility follows the **target-state owner**: an explicit command checks the `forge_root` whose state
it will change, even when a named session was resolved from another CWD. Command mutations fail closed; lifecycle and
context hooks continue after at most one debug diagnostic per invocation; detached/background work refuses the write
without changing an unrelated foreground command's exit status. Proxy/backend registries and read-time repair of the
derived global session/active indexes are exempt because they are not owned by a Forge project root.

**Definitions:**

- **Forge project** = project/local extension root established by a successful `forge extension enable`; `.forge/` is
  its state anchor, while `.claude/` and `.agents/` exist only when the selected modules/runtime packages require them.
- **`forge_root`** = the Forge project root (where `.forge/` lives). Field in `SessionIndexEntry`.
- **`relative_path`** = `forge_root` relative to `checkout_root`. Preserved on `fork --into`.

Extension lifecycle auto-detection walks ancestors and accepts either managed Claude settings evidence or an exact
project/local row in `installed.json`. This keeps Codex-only skill roots discoverable by status, sync, and disable even
when no `.claude/` directory exists.

**Fork `--into` rules (normative):**

- `--into` targets a **worktree** (different checkout), not an arbitrary path.
- Child session lands at the equivalent `forge_root` in the target worktree: `target_checkout_root / relative_path`.
- Target must have Forge enabled at that relative path. If not: error with "Run `forge extension enable` in
  `<target_checkout_root>/<relative_path>` first, or use `--worktree` to create a new checkout with auto-enable."
- No arbitrary path targeting -- you pick the worktree, the position is computed.

**Session command scoping (normative):**

- **`session list`**: workspace-scoped by default (`--scope workspace`, filters by `project_root`). Shows sessions
  across all worktrees and Forge projects within the same logical repo (the workspace). `--scope project` narrows to
  current `forge_root`. `--scope all` shows everything globally.
- **`session show`, `session delete` (named), `session set`, `session reset`**: workspace-scoped with current-project
  preference. Two-tier resolution: try current `forge_root` first (O(1)), fall back to a workspace-scoped scan. Prefers
  current `forge_root` as tiebreaker when the same name exists in multiple projects. Raises `AmbiguousSessionError` if
  truly ambiguous. Prints a cross-project note when resolving from a different `forge_root`.
- **`session delete --all`**: project-scoped (current `forge_root` only). Requires being inside a Forge project
  (`_cwd_forge_root() != None`); refuses to run outside one to prevent accidental global deletion.
- **Claude `session resume`, `session fork`**: project-scoped. Cannot resolve cross-project because Claude Code's
  `--resume` and CWD namespace are tied to the project directory. Hints where the session lives on cross-project miss.
  **Codex `session resume`** is intentionally cross-CWD: Forge resolves the named session and runs `codex resume` or
  `codex exec resume` in its recorded worktree, so compatibility keys on that resolved session's `forge_root`, not the
  caller's CWD.
- **`session clean`**: global by default (no `forge_root` filter).
- **Artifacts, transfer, search**: Forge-project-scoped (all under `<forge_root>/.forge/`).
- **Cross-project resume** (transfer mode only): allowed within the same logical repo
  (`parent_project_root == child.project_root`). Reads parent artifacts by absolute path via `parent_forge_root` in the
  derivation record. **Native resume** (`--resume-mode native`) requires the same `forge_root` -- Claude Code cannot
  `--resume` across CWD boundaries (see §3.9).

**Exception:** `forge claude start` (bare launcher) works without `.forge/`. It does not create session state, does not
set `FORGE_SESSION`, and session-specific hooks/status behavior is a no-op. See §3.4.

> See [diagrams.md §10: Project Identity Hierarchy](diagrams.md#10-project-identity-hierarchy) for a visual overview.

#### Context model: Forge vs Claude Code

Claude Code scopes conversations to the project directory (`.claude/`). `--resume <uuid>` only finds conversations in
the current project's `.claude/`. Forge's project model (N sessions per Forge project, cross-project forking) extends
this.

When sessions cross **Forge project boundaries** (worktree forks, `fork --into`, resume), Forge uses **file-based
transfer**: `assemble_transfer_context()` reads the parent's transcript artifacts and generates a portable context file
at `<forge_root>/.forge/prev_sessions/<parent>/generated.md`, then copies it to the launch-time child artifact at
`<forge_root>/.forge/prev_sessions/<parent>/children/<child>.md`, appended via `--append-system-prompt-file`. Transfer
trades the full conversation for a runtime-neutral, **user-editable** view: it is the only substrate that crosses
worktree, project, and (later) runtime boundaries, and the user can inspect and prune what propagates — something native
`--resume` structurally cannot offer (see §3.9).

The `--strategy` knob controls fidelity: `minimal` (lineage pointer) → `structured` (conversation skeleton, default) →
`full` (complete transcript) → `ai-curated` (LLM-selected highlights). `--inline-plan` embeds the approved plan content
(from ExitPlanMode snapshots) directly into the transfer file — critical for review and supervision workflows where the
reader cannot access the original plan file.

Checkouts are **shared resources** (like proxies): multiple sessions can live in the same checkout. `delete_session()`
scans for co-resident sessions before removing a worktree, and sessions created via `--into` (`owns_worktree=False`)
never remove the worktree they're visiting. If the owning session is deleted before the last guest, Forge preserves the
checkout and leaves final cleanup to the user.

### 3.1 User story: Multi-proxy multi-session workflow

This workflow motivates Forge's separation of **Session** and **Proxy**.

**Goal:** Combine planning/review through one proxy (e.g., OpenAI-based) with implementation through another, while
keeping artifacts and the working directory shared.

> See [diagrams.md §7: Multi-Proxy Workflow](diagrams.md#7-multi-proxy-workflow).

**Baseline flow:** Session A (planner, OpenAI proxy) → fork to Session B (executor, Anthropic proxy) → review loop
(resume A to review B's changes, feed fixes back). Optional Session C on a third proxy for independent review/synthesis.

**Why proxies, not session overrides:** Per-session routing is impossible without a session identifier in requests (see
§3). Sessions within a Forge project share the working directory; artifacts (plans, reviews) are captured per-session
for cross-session transfer. Worktrees are used when sessions write concurrently.

### 3.2 Contract files (authoritative paths)

| Artifact             | Path                                                             | Owned by                 | Purpose                                                                                 |
| -------------------- | ---------------------------------------------------------------- | ------------------------ | --------------------------------------------------------------------------------------- |
| Session file         | `<forge_root>/.forge/sessions/<session_name>/forge.session.json` | Forge Session + Hooks    | Session `intent`, `overrides`, and field-owned `confirmed` runtime facts                |
| Global session index | `~/.forge/sessions/index.json`                                   | Forge Session            | Session metadata (name, `forge_root`, `project_root`); fast listing + project filtering |
| Active session index | `~/.forge/sessions/active.json`                                  | Forge Session            | Ephemeral live-launch registry for delete warnings + stale pruning                      |
| Proxy registry       | `~/.forge/proxies/index.json`                                    | Forge Proxy Orchestrator | Running proxies (template ↔ base_url/port ↔ pid)                                        |
| Runtime config       | `~/.forge/config.yaml`                                           | Forge CLI                | Global runtime preferences (proxy mode, timeouts, context limit)                        |
| Installed manifest   | `~/.forge/installed.json`                                        | Forge Installer          | Tracks what `forge extension enable` installed for update/uninstall                     |
| Project registry     | `~/.forge/projects.json`                                         | Forge Installer          | Versioned trusted-root registry for user-scope hook gating                              |
| Project compat pin   | `<forge_root>/.forge/project.toml`                               | User / Forge Installer   | Optional `required_forge` guardrail for project-local state mutations                   |
| Work queue           | `~/.forge/pending-work/*.json`                                   | Forge Work Queue (§3.13) | Deferred work markers (stop, index, handoff, shadow)                                    |
| Usage ledger         | `~/.forge/usage/events/<month>_<pid>.jsonl`                      | Forge Usage Ledger       | Usage attribution events; schema §A.13                                                  |
| Optional events      | `~/.forge/events/*.jsonl`                                        | TBD                      | Debugging/analytics; optional                                                           |

The active session index is intentionally runtime-only. It is self-healed via launcher PID / sidecar container liveness
checks and must not be treated as durable session truth like the manifest or global session index.

**Global session index entry schema** (`~/.forge/sessions/index.json`):

```python
@dataclass
class SessionIndexEntry:
    project_root: str       # Logical repo -- cross-project ops, session list default scope
    checkout_root: str      # Worktree root -- --into targeting, relative_path anchor
    forge_root: str         # Forge project root -- state scoping anchor
    relative_path: str      # forge_root relative to checkout_root
    last_accessed_at: str
    is_fork: bool = False
    is_incognito: bool = False
    parent_session: str | None = None
    claude_session_id: str | None = None
```

`session list --scope` controls filtering: **`workspace`** (default) filters by `project_root` -- shows sessions across
all worktrees and Forge projects within the same logical repo (the workspace). **`project`** filters by `forge_root` --
just this Forge project. **`all`** shows everything globally.

### 3.3 Session file schema (`forge.session.json`)

A Forge session is a durable workflow record, not a process-invocation record. A Claude-runtime session records its
current or last-seen conversation in `confirmed.claude_session_id`; multiple process invocations may reattach to that
conversation, and hooks reconcile the identity when Claude rolls it over. Codex-runtime sessions use the analogous
`confirmed.codex.thread_id` and leave `claude_session_id` unset.

For Claude, `confirmed.claude_session_id` has field-specific CLI/hook ownership depending on the launch path.
`forge session start` **pre-seeds** it: the CLI generates a UUID, writes it to the manifest at creation, and imposes it
on Claude via `--session-id`; the SessionStart hook then **validates** that UUID. The same pre-seed applies to
**transfer/fresh children** (the cross-worktree default for `session fork` and `resume --fresh`): the CLI mints a
**new** UUID and imposes it via `--session-id`. The exception is a **native** fork (`--resume-mode native`, which passes
`--fork-session`): there the CLI does **not** pre-seed — Claude mints the child UUID and SessionStart **discovers and
records** it (`native-relocate` instead reuses the parent's UUID). Stop and StopFailure also reconcile
`claude_session_id` and `transcript_path` from their hook payloads to correct fork-session launches where SessionStart
sees an inherited parent UUID. Because the start path pre-seeds, a non-null `claude_session_id` does **not** by itself
mean the session ran (a `--no-launch` or not-yet-launched start session already carries a pre-seeded UUID);
"used"/resumable requires hook confirmation or transcript-backed evidence (see Default resume behavior).

**Default resume behavior.** `forge session resume <name>` reattaches to the same Claude conversation without creating a
child when the session has resumable evidence (hook confirmation or transcript-backed state) and is not currently
active. Reattach refreshes `confirmed` runtime facts such as `confirmed_at` and `transcript_path`; those fields reflect
last-seen state rather than immutable launch facts. A never-launched session with no durable confirmation or transcript
evidence launches in place, even though `session start --no-launch` may have pre-seeded its UUID. Use `--fresh` to
derive a new child session with context assembly. `--force` against an active, resumable session launches a lineage
child instead of attaching a second process to that conversation.

The session file has three sections:

> Schema is intentionally strict: unknown fields and unknown override keys are rejected.

| Section         | Definition                    | Written by              | Semantics                                    |
| --------------- | ----------------------------- | ----------------------- | -------------------------------------------- |
| **`intent`**    | Baseline config Forge *wants* | `forge session start`   | Session-owned fields only                    |
| **`overrides`** | Live toggles on top of intent | `forge session set`     | Diff (can be cleared)                        |
| **`confirmed`** | Ground truth of what happened | CLI and hooks, by field | Recorded facts; mutability is field-specific |

`confirmed` ownership and mutability are not section-wide. The CLI owns bootstrap, derivation, launch, and Codex runtime
facts; hooks own observed Claude runtime facts, artifacts, and enforcement state. Some fields are write-once or frozen
(`launch`, explicit consumer-lane bindings), some are additive (`artifacts`), and some are reconciled or refreshed as
the runtime advances (`claude_session_id`, `transcript_path`, `confirmed_at`, and Codex turn facts). The field-level
rules in §3.5 are normative.

**`intent.launch`**: Forge-owned relaunch preferences for reproducible session launch:

```yaml
launch:
  mode: sidecar
  sidecar:
    mounts: [/data:/mnt/data:ro]
    image: my-dev-image:latest
```

This keeps `forge session resume <name>` honest for sidecar sessions without overloading `confirmed` with user-owned
preferences.

**`intent.subprocess_proxy`**: optional proxy ID used only by Forge-spawned subprocesses:

```yaml
subprocess_proxy: openrouter-anthropic
```

This supports direct-mode main sessions that still need panel, supervisor, or memory-writer subprocesses routed through
a proxy for API-key auth and cost visibility. It is session-owned launch intent, not a proxy-owned tier/model override.
Resume, fork, and relaunch children inherit it unless the launch path explicitly chooses different routing.

**`confirmed.started_with_proxy`**: the proxy this session is running with (set at start, immutable for the run):

```yaml
started_with_proxy:
  proxy_id: my-high-reasoning        # optional, same-machine convenience
  template: litellm-openai           # which template this proxy came from
  base_url: http://localhost:8085    # the actual routing identity
```

**Normative semantics:** `proxy_id` is optional. The portable fields are `template/base_url`.

#### Effective vs Confirmed (normative distinction)

| Term            | What it answers                | How computed                       | Stored?                |
| --------------- | ------------------------------ | ---------------------------------- | ---------------------- |
| **`effective`** | "What *should* the config be?" | `intent` with `overrides` applied  | No (derived on-demand) |
| **`confirmed`** | "What *actually happened*?"    | CLI/hooks record field-owned facts | Yes (persisted)        |

**Override rules** (for session `intent + overrides` only):

- Scalars: override replaces
- Lists: override replaces entirely (no concat)
- Dicts: recurse into nested keys (untouched keys preserved)
- Explicit `null`: clears the field

> **Note:** There is no "merging"—overrides simply win. The only subtlety is nested dicts: you can override
> `memory.tags` without losing `memory.auto_recall`. This applies to session-owned fields only (`tdd_mode`, `memory.*`,
> etc.). Proxy-owned fields come directly from the proxy.

### 3.4 Proxy vs no-proxy mode

- **Proxy mode**: Claude is configured to send requests to a proxy base URL (`ANTHROPIC_BASE_URL`).
  - The proxy (template ↔ base_url) is the **routing identity**.
  - Status/other tools may query the proxy (`GET /`) for tier→model mapping and context windows.
  - The optional always-on audit/intercept chokepoint (observe or control outbound traffic, §7.x) is **proxy-mode only**
    — direct mode has no wire to observe.
- **No-proxy mode**: Claude talks to Anthropic directly.
  - Sessions, worktrees, hooks, and overrides still work (for session-owned fields).
  - `forge session start` and `forge session incognito` default to direct mode. Use `--proxy` for proxy routing.
  - `forge claude start --no-proxy` is a bare launcher (no session state) -- see below.
  - Tier/model routing doesn't apply—it's proxy-only. Claude Code uses Anthropic models directly.

**Normative rule:** A session records which proxy it is running with (`confirmed.proxy`), but **cannot override**
proxy-owned routing properties. (Proxy requests do not carry a stable session identifier.)

**Normative requirement: Launch Claude through Forge.** Two launch paths exist:

**Session-managed launch** (`forge session start`, `forge session resume`):

- Requires `.forge/` at `forge_root` (i.e. `forge extension enable` must have run -- see project identity model above)
- Creates/reuses session state in `<forge_root>/.forge/sessions/`
- Sets `FORGE_SESSION` env var -- hooks and status line can locate the correct session file
- Sets `ANTHROPIC_BASE_URL` env var in proxy mode -- routes requests to the correct proxy
- Validates preconditions (proxy healthy, session file exists)
- Records `confirmed.proxy` at session start when proxy mode is active

**Codex-runtime sessions** (`forge session start --runtime codex`, see §3.9) use the same session-managed path, but
every entry point dispatches on `intent.launch.runtime` **before** any Claude machinery: the session runs `codex` turns
direct to OpenAI (no proxy, no `ANTHROPIC_BASE_URL`) — headless `codex exec` with `--task`, the foreground `codex` TUI
without it — Claude-only flags are rejected rather than ignored, and `_launch_claude_for_session` refuses codex
manifests as a backstop. The CLI accepts `--runtime claude|codex` but manifests persist registry ids only
(`claude_code`/`codex`), mapped at the CLI boundary.

**Bare launch** (`forge claude start`):

- Convenience proxy launcher -- does NOT create session state
- Does NOT set `FORGE_SESSION` -- session-specific hooks, status line session display, and artifacts are all no-ops
- Does NOT require `.forge/` -- works from any directory
- Only sets `ANTHROPIC_BASE_URL` (proxy mode) or nothing (direct mode)

**Bare launch (Codex)** (`forge codex start --proxy <id-or-template>`):

- Codex analog of `forge claude start` -- sessionless, no `FORGE_SESSION`, no `.forge/` required.
- Requires a **Responses-capable** proxy (`wire_shape: openai_responses_passthrough` + a `responses_ingress` source,
  §3.7); the launcher re-checks that conjunction against `GET /` and fails closed (`ProxyNotResponsesCapableError`). The
  same `GET /` also re-verifies proxy **identity** (`is_proxy` + `proxy_id` + `template`) -- `ensure_proxy` resolves an
  exact proxy_id by registry presence, not liveness, so a stale entry whose port is now held by a *different* capable
  proxy is rejected (`ProxyIdentityMismatchError`), not silently routed.
- Routes Codex through the loopback proxy via list-mode
  `-c model_providers.forge_proxy.{base_url,wire_api=responses,env_key}` overrides (never `--strict-config`); a custom
  provider means Codex needs no OpenAI login.
- **Scrubbed child env**: drops native codex/OpenAI auth and OpenAI account/routing vars (the proxy owns upstream auth
  -- no native-account leakage) plus session/run-tree identity, and advances `FORGE_DEPTH`. Unlike session-managed
  `invoke_codex_interactive`, it re-establishes **no** native auth (`invoke_codex_bare_proxy`).
- Hard-blocks a codex older than the proxy-contract-validated version (`0.141.0`) *before* starting a proxy.

**Subprocess proxy launch variant** (`forge session start --subprocess-proxy <proxy_id>`):

- Creates a normal direct-mode Forge session for the main Claude process
- Records `intent.subprocess_proxy=<proxy_id>`
- Sets `FORGE_SUBPROCESS_PROXY` so Forge-spawned subprocesses resolve the proxy and set `ANTHROPIC_BASE_URL`
- Leaves the main Claude process on direct Anthropic routing
- Is mutually exclusive with `--proxy`; `--proxy` routes the main session through the proxy, while `--subprocess-proxy`
  is specifically dual-auth routing for direct sessions and their child jobs

Running `claude` directly bypasses both paths; neither proxy routing nor session integration will work.

> See [diagrams.md §6: Proxy Routing Flow](diagrams.md#6-proxy-routing-flow) for a sequence diagram.

### 3.5 File ownership boundaries (normative)

To avoid writer conflicts:

- Forge Session (CLI) writes:
  - `~/.forge/sessions/index.json` (includes `forge_root`, `checkout_root`, `project_root` per entry)
  - `intent` + `overrides` sections in `<forge_root>/.forge/sessions/<session_name>/forge.session.json`
  - `intent.launch` records relaunch mode plus sidecar-specific options (image, extra mounts) when the session is
    created or derived
  - `intent.consumer_lanes.<consumer>` (a `LaneRecord`) when a command requests a non-default lane for a consumer:
    `forge session lane set --consumer <id> --runtime/--backend` is the general surface for all four consumers
    (supervisor, memory-writer, shadow-curation, team-supervisor); the supervisor also has
    `forge session start`/`fork --supervisor-runtime` and `forge policy supervisor set <target> --runtime/--backend`.
    All write the same slot via `set_intent_lane` -- never a raw `set` override (epic consumer_lanes/T1b, T6a)
  - `confirmed` bootstrap/runtime fields written by the CLI: `derivation` (resume metadata), `is_sandboxed` (updated at
    launch time to reflect whether Claude is running via sidecar), `launch` (immutable launch facts recorded once at
    start — routing mode, proxy id/base URL, and whether/how an API key was made available to the child)
  - `confirmed.codex` for Codex-runtime sessions — `thread_id`, rollout path/source, auth posture, `last_run_at`,
    `context_delivery` — is CLI-written like `launch`: Codex hooks only fire from trust-enrolled homes
    (`enrollment_gated`), so the CLI records these from the `codex exec --json` stream (headless), receipt files, and
    filesystem discovery. Thread/rollout/auth/`last_run_at` refresh per turn; `context_delivery` is a start-turn
    delivery fact resume never rewrites. The `codex-session-start` hook's only writes are small receipt files under the
    session directory — `context-receipt.json` (staged-handoff delivery, §3.9) or `observation-receipt.json`
    (nothing-staged turns — interactive thread capture) — and the CLI reconciles them into `confirmed.codex` after the
    turn, so the manifest stays CLI-owned. `confirmed.launch` stays unset for Codex sessions (it documents the ANTHROPIC
    key posture of interactive Claude and would misread), and `claude_session_id` stays `None` — which is what makes
    every Claude-resume predicate refuse Codex sessions.
  - Sets `FORGE_SESSION=<session_name>` when launching Claude
  - `claude_session_id` whenever the CLI starts a **new** Claude conversation — `forge session start` and transfer/fresh
    children (`session fork`, `resume --fresh`): the CLI **pre-seeds** it (generates a UUID, writes it at creation,
    imposes it via `--session-id`) and the SessionStart hook validates it. **Native** fork launches
    (`--resume-mode native`, `--fork-session`) do **not** pre-seed — Claude mints the child UUID and the hook records
    it; Stop/StopFailure reconcile when native fork launches materialize a child UUID after startup.
- Hooks write:
  - `confirmed` section **during the session**: `claude_session_id`, proxy identity, artifacts, policy state, transcript
    paths. SessionStart **validates** the pre-seeded `claude_session_id` (start and transfer/fresh-child paths) or
    **records** the Claude-minted one (native `--fork-session`); Stop and StopFailure are authoritative reconciliation
    points for the final live conversation identity.
  - `confirmed.consumer_lanes` (a frozen `ConsumerLaneBinding` per consumer): freezes a consumer's chosen lane
    **write-once** (epic consumer_lanes/T1b, T6a) -- but **only when an explicit lane was chosen**. All four mirror one
    guard: resolve the lane once (the read `backend_id` comes from), then under the lock re-check
    `read_bound_lane(m) == dispatched_lane` before freezing, so a concurrent re-pin/clear drops the stale write instead
    of recording a lane the run never billed. The *freeze trigger* differs by lifecycle, by design: the supervisor is a
    registered, session-scoped entity (`resume_id`) and freezes eagerly at the **first policy check**
    (`cli/hooks/policy.py`), its commitment point; memory-writer, shadow-curation, and team-supervisor have no
    registration, so they freeze only on a **real dispatch** -- from an `on_dispatch` hook at the actual runtime
    dispatch (the `run_claude_session` call, or `codex exec` on shadow-curation's (T6b, read-only) or the
    memory-writer's (T6c, read-only or workspace-write) codex lane) (`persist_lane_freeze`, best-effort -- a lock
    failure never blocks the run, and a skipped/throttled run never freezes). A consumer running on its default lane
    never freezes, so the default stays re-pinnable. Once frozen it governs dispatch directly (confirmed-first) and the
    resolving commands refuse to change it to a *different* lane.
  - Locate session via `FORGE_SESSION`
- Forge Proxy Orchestrator writes:
  - `~/.forge/proxies/index.json`
  - per-proxy override files (if any)
- Forge Installer writes:
  - `~/.forge/installed.json`
  - installed extension files + merged settings per chosen scope
- Forge memory passport commands write:
  - `forge_memory`, the Forge-owned tracking and writer contract
  - missing outer `type`, `title`, and `description` only when a passport is first created or explicitly upgraded
  - does not generate or maintain producer-owned `resource`, `tags`, or `timestamp`; removal deletes only `forge_memory`
  - detailed generation, preservation, and mutation boundaries are normative in
    [design_workflows.md §5.2](design_workflows.md#52-memory-doc-passports)
- Proxy writes:
  - proxy-owned snapshot/cache files (if any)
- Status:
  - read state; do not invent truth
- Policy:
  - reads state; enforces policy decisions at well-defined boundaries (hooks, proxy)
  - writes only hook-owned confirmed state (e.g., `confirmed.policy`) when running as a hook adapter

> See [diagrams.md §4: Ownership Boundaries](diagrams.md#4-ownership-boundaries).

### 3.6 Configuration System

#### 3.6.1 Definitions (normative)

- **Proxy**: base_url/port/template + tier→model + default hyperparams. Canonical routing identity for a proxy.
- **Session**: Forge-project-scoped intent, overrides, and artifacts. May reference a proxy; cannot change proxy-owned
  fields.
- **Config**: in-repo defaults plus user credentials/connection values (env vars and/or `~/.forge/credentials.yaml`).
  Connection values (for example `LITELLM_BASE_URL`) bootstrap proxy creation; once `proxy.yaml` exists, proxy-owned
  routing is authoritative.
- **Proxy Template**: operational profile defining provider, endpoint, and tier mappings for proxy creation.
- **Model Catalog**: authoritative internal data for model capabilities (`model_catalog.yaml`), not user-editable.
- **ModelRoute**: derived routing option pairing a model with a provider/credential/template. Generated by
  `derive_model_routes()`, not hand-authored.
- **RoutingResult**: structured subprocess routing result: base URL, proxy id, resolution source, selected route, and
  warning. Replaces bare `str | None`.

#### 3.6.2 Field ownership invariants (normative)

- **Proxy-owned**: tier→model mappings, provider/base_url, and default hyperparams (`reasoning_effort`, `temperature`,
  `verbosity`, `thinking_budget_tokens`).
- **Session-owned**: policy/TDD mode, memory/artifacts, `forge_root`, `checkout_root`, `relative_path`, and session
  metadata.
- **Consumer-lane binding** (epic consumer_lanes/T1b, T6a): `intent.consumer_lanes.<consumer>` is the *requested* lane
  (a `LaneRecord`, set by the dedicated lane commands -- `forge session lane set` for all four consumers, plus the
  supervisor's `forge policy supervisor set` / `--supervisor-runtime` -- never a raw `set` override);
  `confirmed.consumer_lanes.<consumer>` is the `(runtime, backend, model)` the consumer *froze* at its first engagement
  -- the supervisor at its first policy check, the aux consumers at their first real dispatch (§3.5). **Only an explicit
  lane choice freezes; the default lane never freezes** (a binding exists iff a lane was explicitly pinned), so an
  unpinned consumer stays re-pinnable. Frozen is **write-once and immutable** -- the resolving commands reject a change
  to a *different* lane (re-pinning the same lane is an idempotent no-op), and dispatch reads confirmed-first. Removing
  a consumer (`policy supervisor remove`, `%policy supervisor remove`) clears both its intent and confirmed slots, so a
  later re-add starts from the default. The post-eval freeze runs lock-free during the (multi-second) check, so it lands
  only when the fresh under-lock manifest still dispatches the lane it ran on — a concurrent remove/reconfigure drops
  the stale write rather than resurrecting a cleared binding. See
  [design_appendix.md §G](design_appendix.md#g-subprocess-routing-reference).
- **Routing chain**: tier resolution is request explicit tier → proxy default tier. Subprocess resolution is explicit →
  subprocess proxy → preferred proxy → route scan → session proxy → unresolved (see §3.6.12).

**CLI enforcement:** Enforced in the CLI: `forge proxy` edits proxy settings; `forge session` edits session settings.
Session commands can't set proxy-owned keys.

#### 3.6.3 Proxy lifecycle UX

**Implemented:**

```bash
# List proxies
forge proxy list

# Create a proxy from template with optional per-tier overrides
forge proxy create litellm-openai \
  --opus-reasoning high \
  --sonnet-temperature 0.7
```

**Also implemented:**

```bash
# Start Claude pinned to this proxy
forge claude start --proxy <proxy_id>

# Edit proxy config
forge proxy edit <proxy_id>
# OR: forge proxy set <proxy_id> tier_overrides.opus.reasoning_effort=high

# Delete proxy
forge proxy delete <proxy_id>
```

**Launch-time auto-start (lookup-or-start).** `--proxy` (session start/resume/fork, `forge claude`) and
`--supervisor-proxy` (session start/fork, `forge policy supervisor set`) accept a template name. When the name is a
template, the launcher routes through `ensure_proxy()` → `start_proxy()` (reuse a live proxy, else adopt/spawn) instead
of a lookup-only `resolve_proxy()`. This makes a template name with no running proxy — or a registry entry marked
`healthy` that is no longer reachable — start a live proxy rather than fail. A bare proxy_id is still presence-only
(revive with `forge proxy start <id>`); a name matching neither a proxy nor a template fails with a
`forge proxy template list` hint.

**Overlay boundary:** You do NOT edit internal templates/model catalog—only your proxy overlay.

> **Configuration reference details** — proxy overlay schema, template inventory, confusion traps, secrets, runtime
> config (`~/.forge/config.yaml`), model catalog, and status line guidance are in
> [design_appendix.md §A](design_appendix.md#a-configuration-reference).

#### 3.6.12 Subprocess routing resolution (normative)

All Forge subprocesses (workflow workers, supervisor, memory writer) resolve proxy routing through a single shared
function (`resolve_subprocess_routing()`). This replaced four ad-hoc resolution paths that each implemented different
fallback chains with different semantics.

**Resolution chain** (same for every subprocess type):

| Step | Source             | Behavior                                                                 |
| ---- | ------------------ | ------------------------------------------------------------------------ |
| 1    | `explicit`         | CLI flag override (`--proxy`, `--supervisor-proxy`, config URL)          |
| 2    | `subprocess_proxy` | Session ambient (`FORGE_SUBPROCESS_PROXY`) -- user intent for child jobs |
| 3    | `preferred_proxy`  | Catalog hint (`ModelSpec.preferred_proxy`); soft -- skip if not running  |
| 4    | `route_scan`       | Find any running proxy compatible with a derived `ModelRoute`            |
| 5    | `session_proxy`    | Inherited `ANTHROPIC_BASE_URL`                                           |
| 6    | `unresolved`       | No route found; callers decide fail-open vs fail-closed                  |

`source="direct"` is produced by workflow routing (`review.routing`) for direct-only model specs (e.g., `claude-opus`
running `claude -p --bare`), not by the shared resolver. `route` is present when model compatibility is known; `None`
can mean unresolved or opaque/non-model-specific routing (e.g., explicit base URL). `source` and `base_url` distinguish
them.

**Supervisor model scope:** When supervisor routing resolves to a proxy URL, the supervisor invokes
`claude -p --model opus` and clears inherited Claude model-pin env vars (`ANTHROPIC_MODEL`,
`ANTHROPIC_DEFAULT_*_MODEL`). This keeps executor/session `--model` pins local to the executor while allowing the
supervisor to use the selected proxy's `opus` tier. Direct supervisors do not get this proxy-tier reset because there is
no Forge proxy mapping to resolve.

This chain applies to the supervisor's default `claude_code` lane. The `codex` lane arm (the supervisor's
`consumer_lanes` binding, epic consumer_lanes) bypasses it entirely: `codex exec` runs **direct** to OpenAI with no
Forge proxy. See [design_appendix.md §G](design_appendix.md#g-subprocess-routing-reference) for the consumer-lane layer.

**Fail behavior by subprocess type:**

| Subprocess    | On unresolved | Rationale                                                        |
| ------------- | ------------- | ---------------------------------------------------------------- |
| Workflows     | Fail closed   | User asked for this work; partial results worse than an error    |
| Supervisor    | Fail open     | Blocking the coding session is worse than skipping a check       |
| Memory writer | Fail open     | Async/best-effort; benefits future sessions, not the current one |

**Per-invocation routing plan:** Workflow commands resolve routing for all workers **once** at invocation start as a
frozen `WorkerRoutingPlan`. No per-worker resolution at runtime. This prevents registry drift during parallel fan-out
and ensures preflight checks match runtime behavior. User-facing workflow JSON surfaces this decision as
`resolved_models`, including requested model, actual model ref, provider, proxy, template, and routing source for each
worker.

> **Routing reference details** — data type schemas (`ModelRoute`, `RoutingResult`, `WorkerRoutingPlan`), function
> signatures, route derivation ranking, and sidecar constraints are in
> [design_appendix.md §G](design_appendix.md#g-subprocess-routing-reference).

### 3.7 Proxy runtime truth

When the proxy base URL is reachable, **live proxy introspection is authoritative** for tier→model mappings and context
windows. File caches are allowed but non-authoritative.

The proxy exposes runtime truth via `GET /`:

```json
{
  "is_proxy": true,
  "proxy": { "template": "litellm-openai", "base_url": "http://localhost:8085" },
  "wire_shape": "openai_translated",
  "intercept_mode": "passthrough",
  "intercept": { "mode": "passthrough", "thinking_blocks_preserved": false, "can_inspect": { "...": "..." } },
  "tiers": {
    "haiku": { "model": "gpt-4o-mini", "context_window": 128000 },
    "sonnet": { "model": "gpt-4o", "context_window": 128000 },
    "opus": { "model": "o3", "context_window": 200000 }
  }
}
```

**Key points:**

- The proxy does **not** know about sessions (see §3.6.2)
- Session info comes from the session file, not the proxy
- Status line tools read both sources independently
- Spend cap rejections return HTTP 429 with `error.type=spend_cap_exceeded`
- Warn-mode spend caps allow the request and attach `X-Spend-Warning`
- `wire_shape` is the authoritative wire truth (a passthrough proxy may carry `provider: litellm` as a credential slot
  only); `intercept_mode` + `intercept.can_inspect` let a launcher report "inspect active (signature-safe)" vs "inspect
  active (lossy)" before launch (§7.x)
- `wire_shape: openai_responses_passthrough` is the **Codex-facing** shape: it serves the OpenAI **Responses** API on
  `/v1/responses*` (create + retrieve/cancel/input_items/delete/compact/input_tokens), forwarding Codex's raw traffic
  byte-for-byte so reasoning items survive (signature-safe; like `anthropic_passthrough`, `can_inspect.*` is uniformly
  false). The route is served only when `wire_shape == openai_responses_passthrough` **and** the proxy's backend
  instance declares the `responses_ingress` capability — the same conjunction `GET /`'s `capabilities.responses_ingress`
  field advertises and the codex preflight's `proxy_supported` posture mirrors. Dollar cost is recorded only when the
  upstream reports it (`x-litellm-response-cost`, USD→micros); an OpenAI-direct upstream is token-telemetry-only. The
  launcher that consumes this shape is `forge codex start --proxy` (§3.4, Bare launch (Codex)).

**Tier selection precedence:**

1. Request explicit tier (model name contains `haiku|sonnet|opus`)
2. Proxy default tier (configured for that base URL)

Tier-word detection for raw model names is single-sourced in `forge.core.tiers.detect_tier_word()`. The status line's
display-name helper remains separate because it has different display fallback behavior (defaults to `sonnet` when no
tier word is visible).

This applies to tier selection *within* a resolved proxy. Which proxy a subprocess uses is decided by the resolution
chain (§3.6.12).

### 3.8 Session artifacts (plans + transcripts)

Forge hooks capture **session-associated artifacts** to make sessions self-contained and inspectable later.

**Artifact storage (Forge-project-scoped):**

- `<forge_root>/.forge/artifacts/{session_name}/plans/`
- `<forge_root>/.forge/artifacts/{session_name}/transcripts/`

Notes:

- Artifacts are scoped to the **Forge project root** (`forge_root`). All sessions in a Forge project share one artifact
  namespace.
- Paths recorded into the session file under `confirmed` are **forge_root-relative** (portable across machines/paths).
- Cross-project operations (resume from a different checkout) read parent artifacts by **absolute path** via
  `parent_forge_root` in the derivation record (see §3.9).

**Plan snapshots:**

- We capture **approved** plan snapshots only (no drafts).
- Approval boundary: `ExitPlanMode`.
- Snapshot filename includes a timestamp suffix to handle replans (multiple approvals in a session).

**Transcript copies:**

- We copy the full transcript only at low-frequency boundaries:
  - `Stop` hook event (session end)
  - `/compact` or `/clear` rollover (captured by `SessionStart` with `source=compact|clear` before overwriting
    `confirmed.transcript_path`)
- Destination filename is `{session_id}.jsonl` (idempotent per Claude session UUID).

**Session file fields (hook-owned, additive):**

- `confirmed.latest_plan_path`: pointer to the latest plan file in `.claude/plans/…` (draft pointer)
- `confirmed.artifacts.plans[]`: entries like:
  - `{ kind: "approved", captured_at, source_path, snapshot_path }`
- `confirmed.artifacts.transcripts[]`: entries like:
  - `{ captured_at, reason: "stop"|"compact"|"clear", source_path, session_id, copied_path, copied }`

### 3.9 Session Resume (context management)

When context nears limits, `forge session resume --fresh` creates a new session with context assembled from the parent.
It's **two-phase**: raw artifacts stay immutable (full history for debugging and audit); context assembly is flexible —
the same raw data serves different fidelity/size needs.

**Phase 1: Capture (parent session end)**

The Stop hook captures everything to artifacts — this is the **source of truth**:

```
<forge_root>/.forge/artifacts/<session>/
├── transcript.jsonl    # Full conversation (our normalized copy)
├── metadata.json       # Confirmed state, lineage pointer
└── plans/              # Approved plans
```

The hook also updates designated memory docs if work was completed.

**Phase 2: Resume (child session start)**

The resume command supports two **resume modes** (`--resume-mode`):

- **`transfer`** (default): Assembles parent context into a markdown file passed via `--append-system-prompt-file`.
  Lossy but survives `/compact` (lives in the system prompt). Size controlled by `--strategy`.
- **`native`**: Uses `--resume --fork-session` to carry full conversation history. Lossless but lost on `/compact`. No
  context file generated. Requires the parent to have a confirmed `claude_session_id`.

The transfer doc carries a `target_runtime` frontmatter field and a `## Runtime Hints` section. `claude` (default)
renders byte-identically to the original output; `codex` relabels both (the curated body stays Claude-worded). Delivery
is runtime-specific: Claude uses `--append-system-prompt-file`. Codex has **no** system-prompt-file flag, so by default
the curated context is prepended to the **initial `codex exec` message** — the zero-setup path. The opt-in
`--context-delivery hook` instead stages the framed body at `<session_dir>/codex/pending-context.md`, sends only the
task as the prompt, and lets a trust-enrolled `forge hook codex-session-start` emit the staged body as SessionStart
`additionalContext` (a probe-pinned wire contract), consuming the file and writing `context-receipt.json` — the hook's
**only** write. Enrollment is unverifiable pre-turn (`trusted_hash` not computable), so the CLI reconciles the receipt
**after** the turn into CLI-written `confirmed.codex.context_delivery`
(`initial_message | session_start_hook | hook_undelivered`); undelivered keeps the session, records the honest fact, and
exits 1 with ceremony/delete-and-retry guidance. Staging is one-shot: the staged file never survives the start turn, and
resume turns defensively clear leftovers. The cross-runtime hop is `bridge_session_to_codex`
(`core/ops/codex_bridge.py`): parent session -> ai-curated Codex-targeted transfer -> body prepended via
`compose_codex_initial_message` (or staged via `compose_codex_handoff_context` in hook mode) ->
`CodexHeadlessInvoker().run`, all under **one run tree** joining on `root_run_id` (§3.14) — a UI-agnostic command-core
op.

**Codex session lifecycle.** The headless frontend over it is
**`forge session start <name> --runtime codex --resume-from <parent> --task "…"`** (`core/ops/codex_session.py`): it
creates a real Codex-runtime session (manifest `intent.launch.runtime="codex"`, immutable —
`forge session set launch.runtime` is rejected), keys the transfer snapshot by the **real session name** so
`Derivation.context_file` GC-protects it (no synthetic per-run transfer children), and runs the first `codex exec` turn.
A failed first turn keeps the session (a turn that never reached `thread.started` leaves no `thread_id`; resume refuses
with delete-and-retry guidance). Headless continuation is `forge session resume <name> --task "…"` ->
`codex exec resume <thread_id>`, cross-CWD in the session's recorded worktree with the prompt on stdin — both codex-cli
behaviors pinned live by a standing E2E. `forge session transfer regenerate <parent> --target-runtime {claude|codex}`
remains the sessionless surface (re-stamps a cache, defaulting the runtime from the existing frontmatter so a regenerate
never silently flips it back).

**Interactive Codex sessions** (`core/ops/codex_interactive.py`): omitting `--task` launches the foreground `codex` TUI
as a managed session — bare (no parent, no transfer, `context_delivery` stays `None`) or an interactive bridge
(`--resume-from` without `--task`; `--task` alone is rejected — headless turns need a parent). The bridge default rides
the **positional initial prompt**: `[PROMPT]` starts a real model turn, so `compose_codex_interactive_context` wraps the
body in explicit hold instructions (acknowledge and wait — no edits/commands/tools yet); `--context-delivery hook` stays
the only truly passive path. Bare `forge session resume` reattaches via `codex resume <thread_id>` in the recorded
worktree — active-session gated with **no** `--force` escape (two TUIs would interleave one rollout), and cross-CWD by
design (Claude's project-scoped refusal is unchanged). The TUI owns stdout — no JSONL stream — so thread identity
reconciles **post-exit**, receipts first: a trust-enrolled `codex-session-start` hook's delivery receipt (hook mode) or
its nothing-staged **observation receipt** (`observation-receipt.json`, cleared pre-launch); otherwise filesystem
discovery over rollouts created after a tight pre-launch timestamp, cwd-narrowed and requiring **exactly one** candidate
— ambiguity refuses to guess and leaves the thread unrecorded (delete-and-retry guidance). Interactive turns emit **no
usage event** (mirrors the reserved `claude_interactive` route); the bridge's transfer curation still emits, under the
same run root the TUI inherits.

**Recorded Codex facts** are CLI-owned, written to `confirmed.codex`; `confirmed.launch` and `claude_session_id` stay
unset (§3.5). Field-by-field sources and the `rollout_source` provenance table:
[design_appendix.md §I.1](design_appendix.md#i1-recorded-codex-facts-confirmedcodex).

> **Why not native for worktree forks?** Claude stores sessions at `~/.claude/projects/<encoded-cwd>/`, so a bare
> `--resume` can't cross the CWD boundary (2.1.90/2.1.158 fail "No conversation found"). **Worktree forks default to
> transfer.** The opt-in `fork --resume-mode native-relocate` (host only) relocates the parent JSONL and resumes
> byte-for-byte; tool paths are not rewritten. See `scripts/experiments/native-resume/`.

**Transfer mode strategies** (`--resume-mode transfer`, default; selected via
`forge session resume <parent> --fresh --strategy <strategy> [--depth N]`):

| Strategy     | What child session sees                                        |
| ------------ | -------------------------------------------------------------- |
| `minimal`    | Lineage pointer only — "read parent if needed"                 |
| `structured` | Conversation skeleton with truncated tool results              |
| `full`       | Complete parent context (fails if exceeds proxy context limit) |
| `ai-curated` | AI-selected highlights from ancestry chain                     |

**Curated transfer is the primary cross-boundary substrate, not a lossy fallback.** Native resume is byte-faithful but
same-runtime, same-CWD, and opaque (the user cannot inspect or prune the carried conversation); curated transfer is
runtime-neutral and *user-editable* — the only way to carry context across worktrees, projects, and runtimes while
shaping what propagates. `structured` stays the CLI default; `ai-curated` emits the full schema
([design_appendix.md §H](design_appendix.md#h-transfer-context-schema)) and is the substrate for cross-worktree,
cross-project, and cross-runtime moves.

**Native mode** (`--resume-mode native`): no context assembly; the full conversation history is carried over via
Claude's `--fork-session`.

**Resume-mode / strategy contract**:

| Surface                | `resume_mode`     | `strategy`     | Real conversation carried | `context_file`  |
| ---------------------- | ----------------- | -------------- | ------------------------- | --------------- |
| Native same-CWD resume | `native`          | null           | yes, full                 | no              |
| Native relocate fork   | `native-relocate` | null           | yes, full                 | no              |
| Transfer               | `transfer`        | selected value | no, generated context     | yes             |
| Rewind                 | `native-relocate` | `rewind`       | yes, prefix `1..T-N`      | yes, code-delta |

The null-strategy native rows are a writer convention, not a schema guard: strict manifest reads tolerate
`native-relocate` with non-null `strategy` and `context_file`. The shipped `rewind` strategy uses that extension point:
it writes a fresh truncated Claude JSONL under a rewind-owned UUID and launches `--resume <R> --fork-session` together
with a generated code-delta prompt file. A live Slice-1 probe on Claude Code 2.1.197 confirmed the filename stem may be
`R` while embedded JSONL `sessionId` remains the parent UUID; no envelope rewrite is required. The slow real-Claude gate
`tests/integration/docker/test_rewind_native_contract.py` extends that probe to the full rewind shape: a fresh `<R>`
stem holding a truncated clean-prefix JSONL resumes across CWD and stays unmutated under `--fork-session`. If code-delta
curation fails or returns unusable output, Forge removes the temporary `<R>.jsonl`, falls back to plain native resume /
native-relocate, and tells the user that the code delta is unavailable. When rewind does send dropped-window content to
the curation model, Forge emits the same style of privacy warning as `ai-curated`.

**Context budget enforcement:** Resume knows the target proxy (inherited or via `--proxy`). For `full`, it **fails
fast** before spawning Claude when the parent transcript exceeds the proxy context window, naming
`structured`/`ai-curated` as the fix. Bounded strategies (truncation/AI selection) need no pre-flight check.

**Depth control:** `--depth N|all` traverses lineage beyond the immediate parent (default `1`), pulling context from
earlier sessions in the ancestry chain.

**Processed context location:**

```
<forge_root>/.forge/prev_sessions/<parent-name>/generated.md              # Regeneratable parent AI cache
<forge_root>/.forge/prev_sessions/<parent-name>/children/<child>.md        # Per-child AI snapshot (frozen; never edited)
<forge_root>/.forge/prev_sessions/<parent-name>/children/<child>.notes.md  # Per-child user-notes overlay (edit this)
```

The child snapshot is a **pure AI artifact**: `forge session resume --fresh --review` and `forge session transfer edit`
write user edits to the separate `.notes.md` overlay, which is merged after the snapshot at launch (via
`--append-system-prompt-file`). You can resume the same parent with different strategies — the parent cache is
regenerated, while existing per-child snapshots **and** their notes are never overwritten. Inspect and reshape transfer
context with `forge session transfer show|regenerate|edit|diff`; §4 links the CLI inventory.

**Session derivation tracking:**

Resumes and forks both populate `confirmed.derivation`; top-level `parent_session` remains a legacy lookup fallback for
older manifests.

```yaml
# In confirmed section of forge.session.json
derivation:
  parent_session: feature-auth-v1
  parent_forge_root: /abs/path/to/parent/forge/root
  parent_project_root: /abs/path/to/repo
  parent_transcript: .forge/artifacts/feature-auth-v1/transcript.jsonl
  inherited_proxy: litellm-anthropic    # From parent's proxy intent, if inherited
  resume_mode: transfer                 # "native" or "transfer" (authoritative)
  strategy: structured                  # null when resume_mode=native or not generated yet
  dropped_turns: null                   # set for strategy=rewind
  rewind_relocated_session_id: null     # fresh truncated-copy UUID for strategy=rewind
  depth: 1
  resumed_at: 2025-01-02T15:30:00Z
  lineage: [feature-auth-v1, feature-auth-v0, initial-planning]  # computed from parent pointers
```

Same-directory forks default to `resume_mode: native`, `strategy: null`, `depth: 1`, and lineage containing the parent.
Passing `--resume-mode transfer` -- or any transfer flag (`--strategy`/`--inline-plan`), which auto-switches a
same-directory fork to transfer with an info line -- instead yields a same-directory *transfer* fork:
`resume_mode: transfer`, a fresh child Claude session (no parent `--resume --fork-session`), and a generated
`context_file`. Worktree and `--into` forks start with `resume_mode: transfer`; the CLI enriches `strategy` and
`context_file` when it generates a transfer context file. `--resume-mode native-relocate` stays worktree/`--into`-only.
`fork --strategy rewind --drop-last N` is also worktree/`--into`-only: it records `resume_mode: native-relocate`,
`strategy: rewind`, `context_file`, `dropped_turns`, and `rewind_relocated_session_id` for the fresh truncated copy.
`resume --fresh --strategy rewind --drop-last N` may be a same-directory child because it resumes the fresh truncated
UUID `<R>`, not the parent's UUID.

**Cross-project resume:** `parent_forge_root` locates the parent's artifacts (may differ from the child's `forge_root`);
`parent_project_root` must equal the child's `project_root` -- cross-repo resume is not supported.

**Context assembly (what child loads at start):**

1. Designated memory docs (always, via CLAUDE.md)
2. Processed transfer: `<forge_root>/.forge/prev_sessions/<parent>/children/<child>.md` (strategy-dependent)
3. Lineage reference: pointer to raw artifacts for deep reads

**Proxy inheritance:** The child inherits the parent's proxy by default, keeping routing stable across resumes;
`--proxy <name>` overrides.

### 3.10 Hook handlers

The session manager writes `intent` and user `overrides`; CLI launch/derivation paths and hooks write their field-owned
`confirmed` facts. Hooks own observed Claude facts such as transcript and plan paths, while the CLI owns launch facts
and reconciled Codex runtime state (§3.5). The Codex `codex-session-start` hook writes only receipt files (delivery or
observation), never the manifest; the CLI reconciles those receipts after the turn.

**Session identification:** Hooks locate the session via `FORGE_SESSION` (set at launch), enabling multiple sessions per
Forge project. Hooks use `FORGE_SESSION` + UUID lookup only. No CWD-based scan or fallback detection.

**Implementation:** Artifact capture uses first-class hook handlers (testable Python entrypoints), not ad-hoc scripts.

Before their first project-owned write, lifecycle, policy, team, and Codex hooks perform one lenient compatibility
diagnostic for all Forge roots that invocation may write. An incompatible, malformed, unreadable, or newer-schema pin is
debug-logged once and the hook proceeds with its existing stdout, stderr, JSON, and exit-code contract unchanged.

**Deployment model:** Forge installs hook **settings only** (no scripts in `.claude/`). Runtime hook registrations are
user-scoped and contain the literal absolute dispatcher command `<forge-home>/bin/forge-hook <name>`; project/local
installs do not write hook blocks. The hidden hook-handler surface remains `forge hook <name>`, so runtime + deps live
with the Forge package (single upgrade surface). The dispatcher first applies its no-op gate: a managed session
dispatches regardless of cwd, while an unmanaged launch dispatches only from an enrolled root. After validating the
handler name, a present `FORGE_DEV` selects exactly `<absolute-checkout-root>/.venv/bin/forge`; an empty, relative,
missing, non-executable, or unlaunchable target exits 127 without falling back. When the variable is absent, the
dispatcher resolves a durable `forge` launcher from `~/.forge/runtime.json` and then known user-tool locations, without
consulting the inherited `PATH`. It `exec`s `forge hook <name>` with stdin/stdout/stderr/exit code preserved.
`statusLine` remains project/local-scoped because it is a scalar setting, not a runtime hook.

**Operational requirement:** normal dispatch needs an executable `forge` launcher in recorded metadata or a known
user-tool location. Enable/sync persists only executable non-venv launchers; legacy metadata remains usable until the
next sync migrates it. A stale or missing launcher is surfaced by the dispatcher error and by `forge extension doctor`.
`FORGE_DEV` is the explicit, process-scoped contributor exception: it changes binary resolution only, mutates no runtime
metadata, and adds no project-compatibility bypass.

**Legacy migration:** user-scope `forge extension enable` and `sync` may report tracked project/local cleanup
candidates, but they neither open those checkouts nor enroll them. Repository mutation requires an explicit
`forge extension cleanup-project [--root <dir>] --yes`; without `--yes`, the command is a side-effect-free preview. The
apply path validates the selected root, global tracking, user targets, and the project registry before writing. It then
removes exact tracked or frozen known-released direct-hook entries, reconciles tracking, verifies the selected root is
clean, installs/updates the user runtime hooks, and enrolls that root with source `backfill` as the final
ambient-dispatch activation. Ambiguous entries block only that selected operation. Because project and user files cannot
be swapped atomically, a failure after project removal is reported as a hooks-off recovery state with backups and an
exact retry command; Forge does not roll legacy hooks back or create a known double-fire window.

Doctor exposes cleanup-required registrations separately from actual duplicate `(event, matcher, handler)` triggers. The
opt-in status-line `hooks` segment follows the same distinction: `HOOK!` means cleanup is required, while `HOOKx2` means
a genuine duplicate trigger; both may appear.

**Why `forge hook …` instead of installed scripts:**

1. **No dependency ambiguity** — install Forge once; deps resolved at install.
2. **No version drift** — hooks run the current Forge version.
3. **Auditable footprint** — `.claude/` contains config/markdown, not executables.
4. **Testable** — regular Python entrypoints (unit-testable, type-checkable).
5. **Session-aware** — reads session file; per-session decisions.

**Artifact capture hooks:**

- `forge hook plan-write` (PostToolUse:Write): Updates `confirmed.latest_plan_path` for plan files.
- `forge hook exit-plan-mode` (PreToolUse:ExitPlanMode): Snapshots approved plan to artifacts.
- `forge hook stop` (Stop:\*): Runs the Stop pipeline (see below).
- `forge hook pre-compact` (PreCompact): Captures full transcript before compaction to artifacts. Canonical compaction
  snapshot; SessionStart rollover is fallback for `/clear` and defense-in-depth.
- `forge hook post-compact` (PostCompact): Records compaction metadata (`last_compact_at`, `last_compact_type`).
- `forge hook worktree-create` (WorktreeCreate): Replaces Claude Code's default `git worktree add` to auto-install Forge
  extensions. It strict-checks the source Forge root before creating a checkout, maps a nested source root to the same
  relative path in the new checkout, then strict-checks that target before config copy, enrollment, or install. A target
  refusal removes the checkout and any branch created for it; incomplete Git cleanup is surfaced on stderr. Runtime
  config copying never copies the ignored `.forge/project.toml`; a tracked target pin is authoritative. Prints the
  worktree path to stdout on success. Only hook that exits non-zero on failure.
- `forge hook subagent-stop` (SubagentStop): Tracks subagent activity (`total_count`, `by_type`, transcript path,
  message preview). Observe-only (phase 1).

**Stop hook pipeline:**

The Stop hook does multiple things. To avoid blocking exit and ensure idempotency across repeated invocations, it
performs synchronous capture/verification and then only enqueues deferred work:

```
Stop Pipeline:

  [Sync - blocks exit decision, must be <100ms]
  1. capture_artifacts()    Copy transcript to .forge/artifacts/ (idempotent via UUID)
  2. run_verification()     Check completion promise → returns allow|block

  [Deferred - Stop writes markers; it does not launch a writer]
  3. enqueue stop/index markers
  4. enqueue handoff marker when memory is enabled
  5. enqueue shadow marker when pending shadow candidates exist

  return verification_decision

Later eligible Forge CLI startup:
  6. opportunistically drain pending work
  7. handoff handler launches detached `forge memory-writer run` and returns
  8. detached writer scans passports and synthesizes updates
```

The memory writer runs asynchronously in a detached process after a later, non-exempt Forge CLI startup drains the
handoff marker. Memory doc updates are eventually consistent; this is acceptable because they benefit future sessions,
not the exiting session.

**Idempotency rules** (verification can trigger Stop multiple times per session):

| Step             | Multiple invocations safe? | How                                                 |
| ---------------- | -------------------------- | --------------------------------------------------- |
| Artifact copy    | ✔ Yes                      | Writes to UUID-named path, overwrites are identical |
| Verification     | ✔ Yes                      | Stateless check of last message                     |
| Deferred enqueue | ✔ Yes                      | Marker file is idempotent (same content = no-op)    |

**Deferred enqueue:** The Stop hook attempts stop and index markers, a handoff marker when memory is enabled, and a
shadow marker when pending shadow candidates exist. A later eligible CLI startup drains the handoff marker and launches
the detached writer; the Stop hook never spawns it. See §3.13 (Async Work Queue) for the queue contract, schema, and
processing model.

This keeps the Stop hook fast (\<100ms) while arranging memory-writer work and indexing after subsequent eligible CLI
activity.

Design rule: hooks emit machine-readable JSON; no `systemMessage` required (the memory writer replaces manual
reminders).

> See [diagrams.md §5: Hook Deployment Model](diagrams.md#5-hook-deployment-model).

### 3.11 Direct commands (UserPromptSubmit dispatcher)

Forge supports a **direct command** channel to invoke Forge actions inline from the Claude prompt without adding slash
commands or changing hook wiring.

**Design goal:** install **one** `UserPromptSubmit` hook, then add new `%<cmd>` handlers over time **without
reinstalling hooks**.

> **⚠︎ Limitation:** `UserPromptSubmit` hooks only fire in **interactive** Claude sessions. They do NOT fire in
> `claude --print` mode (non-interactive/piped). `--print` has no user prompt submission event. Do not rely on `%`
> commands working in `--print` mode or automated scripting that uses `--print`.

Mechanism:

- Claude Code `UserPromptSubmit` hook runs: `forge hook user-prompt-submit`
- The handler parses prompts that begin with `%` and dispatches to the appropriate command implementation.
- Unknown `%<cmd>` strings are ignored (normal Claude flow continues).

Response contract:

- When a direct command is handled, the hook returns a Claude Code decision payload:
  - `{ "decision": "block", "reason": "..." }`
- When not handled, it emits no output and exits successfully.

**Scope policy:** `%` commands are primarily session-scoped. Proxy commands are restricted to read-only operations
because proxies are global (modifying a proxy mid-session could affect other sessions using the same proxy). Proxy
management should be done deliberately from terminal.

> Full command list and scope policy table in [cli_reference.md §2](cli_reference.md#2-direct-command-reference).

### 3.12 Command-core ops (shared implementation)

Forge implements "Shared" operations once in a UI-agnostic command-core layer and exposes them via both:

- terminal CLI (`forge ...`), and
- direct commands (`%...` via `forge hook user-prompt-submit`).

**Location:** `src/forge/core/ops/`

**Contract:** ops contain pure logic (no Click, no printing, no hook JSON). They return structured data and raise typed
exceptions on failure.

`core/ops/policy.py` owns the semantic supervisor lifecycle mutations shared by `forge policy supervisor ...` and
`%policy supervisor ...` (set/off/on/remove/reload/cascade); the terminal CLI and hook responder own only rendering,
exit codes, and JSON response shape. This avoids duplicating business logic between terminal and in-session entry
points.

### 3.13 Async work queue

A **general-purpose, file-based queue** for deferred work. Producers enqueue markers; CLI startup processes them
opportunistically. This is a core primitive used by the Stop pipeline, search indexing, the memory writer, and deferred
semantic-supervisor shadow drains.

**Module:** `forge.core.workqueue`

**Queue location:** `~/.forge/pending-work/` (respects `FORGE_HOME`)

#### Design goals

- **Best-effort enqueue**: failures are non-fatal (never block hooks or CLI)
- **Fast path**: no-op when queue is empty (cheap directory scan)
- **Concurrent-safe**: per-marker advisory locks (`<marker_id>.json.lock`)
- **Exactly-once-ish**: markers deleted on successful handler completion
- **Eventually consistent**: deferred work benefits future sessions, not the current one

Each marker is a JSON file with `kind` (routing key), `marker_id` (idempotency key), `payload` (kind-specific data), and
retry tracking (`attempt_count`/`last_error`). Handlers are passed as an explicit dict (no global registry). Successful
handling deletes the marker; poison markers (5+ attempts) move to `pending-work/failed/`.

> Marker schema, processing contract, and known kinds in
> [design_appendix.md §B](design_appendix.md#b-work-queue-internals).

### 3.14 Cost tracking and spend caps

Forge records model-call evidence in a unified downstream telemetry plane under `~/.forge/telemetry/downstream/`. Legacy
`~/.forge/costs/*` files may still exist from older installs, but new proxy spend, redacted audit/drift/mutation facts,
provider lifecycle metadata, direct `core.llm` evidence, and native Codex token evidence write to downstream records.
Operation outcomes (policy checks, including no-call fail-opens) write to `~/.forge/telemetry/upstream/`.

| Path                                       | Writer                                    | Purpose                                                     |
| ------------------------------------------ | ----------------------------------------- | ----------------------------------------------------------- |
| `telemetry/downstream/<month>_<pid>.jsonl` | Proxy + Forge runtime emitters            | Per-attempt model-call evidence + audit/drift/mutation data |
| `telemetry/upstream/<month>_<pid>.jsonl`   | Operation/policy boundaries               | Per-operation outcomes; default volume is non-success       |
| `telemetry/caps/<proxy_id>.json`           | Proxy spend-cap tracker                   | Durable cap checkpoint used at restart bootstrap            |
| `telemetry/audit_state/<proxy_id>.json`    | Audit drift detector in proxy-id sidecars | Writable sidecar drift baseline                             |
| `usage/events/<month>_<pid>.jsonl`         | Legacy usage emitters                     | Transitional session activity/read-surface attribution      |

Downstream attempt records are the source of truth for proxy spend. **Forge is not a cost oracle:** it records the cost
a route actually reported — OpenRouter's response-body `usage.cost` (`confidence="reported"`) or a LiteLLM gateway's
`x-litellm-response-cost` header (`confidence="gateway_calculated"`) — and writes `cost_micros:null` /
`confidence="unavailable"` when no route reported one (Anthropic passthrough always; LiteLLM streaming, whose header
predates the cost). There is no local price catalog; cost is never inferred from token counts. Each record carries
`reporter` + `confidence` (the Phase-1 metric-evidence vocabulary). Downstream records also carry a nullable
`backend_id`: the canonical backend instance id (`openrouter`, `litellm-remote`, `anthropic-direct`, etc.). For local
LiteLLM this is the logical backend instance (`litellm-gemini-local`), not the managed process id (`litellm-4000`).
Proxy-origin writers populate it from `proxy.backend`; direct emitters populate it only where the provider/reporter maps
unambiguously (`anthropic-direct`, `openrouter`) and otherwise leave it null for v1. `source_id`/`source_kind` remain
the telemetry-origin axis (`proxy` or `provider`) and are not overloaded with backend identity. New downstream writes
use `schema_version=2`; current readers skip missing/older downstream schemas with a one-time warning and surface
`skipped_legacy_schema` counts in activity/cost views rather than silently reattributing historical records. The proxy
bootstraps its in-memory `CostTracker` from downstream attempts on startup, then reconciles with
`telemetry/caps/<proxy_id>.json` using the larger monthly total so a clean-cut path migration or dropped best-effort
JSONL write does not silently reset spend caps to `$0`. Live request handling remains in-memory authoritative: a
downstream write failure warns but does not block successful model traffic. The fail-closed posture lives at bootstrap
via the durable cap checkpoint, not by turning a transient telemetry write failure into a live-request denial. Cap-state
writes are coalesced by request count/time and flushed on graceful proxy shutdown so the request path does not fsync on
every costed request. Downstream retention preserves current-calendar-month shards even when their mtime is old or the
size budget is tight, so unkeyed/template-mode caps that have no cap snapshot do not lose the active month's JSONL spend
on restart.

The legacy `costs/verbs/` writer and reader have been removed. The default `forge telemetry costs show` by-verb view
derives attribution by joining downstream attempts to `usage/events` via `forge_run_id`; unjoined requests remain
"Interactive"/unattributed. The usage ledger itself remains during the transition for session activity and run-tree
joins, but it is no longer the durable spend source.

A third plane, the **usage-attribution ledger** (`~/.forge/usage/events/`, schema in
[§A.13](design_appendix.md#a13-usage-attribution-ledger-schema-314)), records *which run/workflow/session* invoked which
runtime/provider/model and what it consumed, referencing the cost and audit planes via a shared proxy `request_id`
(nullable `source_refs`). The planes stay physically separate by design — cost is the spend source of truth, audit is
the redacted wire record, usage is attribution, and the **provider-trace** plane (below) is provider lifecycle /
correlation evidence. Each event also carries metric-evidence provenance — `route` (how the work reached the model),
`reporter` (source of the metric evidence), and `confidence` (trustworthiness of *that event's own* `cost_micro_usd`:
`reported` | `gateway_calculated` | `inferred` | `unavailable` | `unknown`). Emission is wired everywhere: the workflow
verbs (`panel`/`analyze`/`debate`/`consensus`) record one estimated verb-level event each; the memory writer, semantic
supervisor, and shadow curation record one event per headless dispatch through either their Claude or Codex arm; the
team supervisor records one event per `claude -p` run; and the action tagger records exact provider tokens from its
direct `core.llm` call (and, when that call resolves to a registered Forge proxy, an exact `source_refs.cost_request_id`
join via a forwarded `X-Request-ID`; direct `billing_mode` stays `unknown` unless provably direct + credentialed). All
emit best-effort, never gate the work they measure, and record `latency_ms`. `claude -p` events carry null `source_refs`
because Forge is not the HTTP client and can't know the proxy `request_id`. Run-tree correlation instead ties a proxied
`claude -p` run to its **exact** cost through the run tree, not a per-request ref: Forge stamps the headless
subprocess's outbound requests with validated `X-Forge-Run-ID`/`X-Forge-Root-Run-ID` headers (only when the target is a
proven Forge proxy), the proxy records `forge_run_id`/`forge_root_run_id` on each cost record, and the read surface
(`forge telemetry activity`, `forge +$Y`) sums cost records by `forge_root_run_id` — superseding the concurrency-fragile
verb snapshot rather than adding to it. `source_refs` stays null by design (one run makes many requests; the
single-valued ref is the wrong shape — see [§A.13](design_appendix.md#a13-usage-attribution-ledger-schema-314)).

**Headless self-report.** Every `claude -p` run requests `--output-format json` (capability-gated with a
retry-once-and-latch backstop, so an older CLI that rejects the flag self-heals), so the runtime can self-report cost
and usage. Exactly **one** reporter attributes cost per run: a **proxied** run keeps the proxy snapshot
(`forge_proxy`/`reported`, Claude's Anthropic-priced `total_cost_usd` ignored as wrong-and-duplicate); a **direct** run
self-reports (`claude_code`/`reported`/`runtime_native`) — closing the prior `unavailable` gap on direct verbs — or,
when the envelope carries usage but no dollar figure (OAuth), records exact tokens with cost honestly `unavailable`.
Tokens follow the cost source (no mixed provenance). The run's `billing_mode` is resolved separately from cost: a
keyless direct `claude -p` consumer bound to a subscription lane (the `claude-max` backend) is labeled
`subscription_quota` (`resolve_billing_mode`, gated on the bound backend's `subscription_quota` posture; a resolvable
key still wins as `api`), while cost stays `unavailable` — only the label changes, never a fabricated dollar figure. The
opt-in `forge_cost` status-line segment surfaces this as `forge +$Y`: Forge-added LLM spend for the session,
**excluding** the main interactive harness (`route=claude_interactive`), reported-or-unavailable and distinct from
Claude's native cost ([§A.8](design_appendix.md#a8-status-line-guidance-3611)).

**Native Codex usage.** A `codex exec` run goes **direct to OpenAI** (no Forge proxy), so there is no proxy cost record
to join: `emit_codex_usage` records `route=codex_exec`/`reporter=codex_jsonl`/`runtime_native` with the **exact** tokens
from the JSONL `turn.completed.usage`, but `cost_micro_usd=null`/`source_refs=null` and `confidence=unavailable` (the
ledger's `confidence` is a cost signal, and Codex reports no dollars — honest absence, not a fabricated $0). The event
carries the resolved `billing_mode` from `CodexPreflight`. Because the Codex child shares its parent's run tree
(`stamp_run_identity`), a Codex leaf and a Claude leaf join under the same `root_run_id` in `forge telemetry activity`.

**Transfer curation usage.** The `ai-curated` transfer's curation step makes a `core.llm` call (an Anthropic model via
OpenRouter) that is now attributed: it emits `route=core_llm`/`reporter=provider`/`runtime=forge_cli`/
`command=transfer-curate` with the provider's exact tokens (cost `unavailable` — `emit_direct_llm_usage` computes no
dollar figure for a direct `core.llm` call, so the event records exact tokens but no cost). The emit no-ops without an
ambient run identity, so a plain `forge session resume --strategy ai-curated` stays silent; the cross-runtime bridge
mints a run-tree root, so there the curation event and the `codex exec` run share one `root_run_id` and
`forge telemetry activity` shows both sides of the hop.

**Provider lifecycle evidence.** Provider-trace data is now stored as fields on downstream attempt records, answering
"what happened to this provider request?" after a timeout — born from an incident where a supervised fork's checks
routed through an OpenRouter proxy, timed out before the final streaming usage chunk, and left no trace locally or in
OpenRouter's UI. The proxy `on_complete` seam writes one downstream attempt record per request
([§A.14](design_appendix.md#a14-provider-trace-plane-schema-314), owner-only 0600, versioned). It is gated by the
selected backend instance's provider-trace capability (`ModelSource.capabilities.provider_trace`), with `openrouter`
enabled in v1 and gateway-routed OpenRouter through non-capable backend instances kept quiet. The record carries the
provider/generation id (probe 1: OpenRouter's `gen-…` id rides every stream `chunk.id`), the selected upstream,
allowlisted correlation headers (never auth/cookie), stream lifecycle flags
(`stream_started`/`first_chunk_seen`/`final_usage_seen`/`client_disconnected`), and a local `local_usage_status`
(`available` when the proxy saw a final usage/cost figure, else `unavailable`). The generation id is captured on the
**first** stream event, so a stream **cancelled before the final usage chunk** — the incident — still surfaces its id.
`timeout_seen` is always `false` at the proxy boundary: the proxy observes only its own client disconnect, never the
parent's `subprocess.run` timeout (that is a later run-tree-correlation join target). Traces join the cost/usage planes
by shared `request_id` + run-tree ids; probe 2 (`[REMOTE-ABSENT]`) confirmed an aborted stream is not remotely
retrievable, which is why the plane answers from local evidence only (no remote `/generation` lookup). The read surface
is `forge telemetry trace list|show|explain` (op-backed `core/ops/provider_trace.py`; no in-session `%` mirror);
`explain` answers the incident's five questions from the trace plus a bounded (±5m) cost-plane join for confidence,
never a remote lookup. An opt-in `provider_trace.inject_provider_user` (default off, a **global** toggle in
`~/.forge/config.yaml`) also records the Forge session grouping id in the provider's top-level `user` field for
OpenRouter routes — probe 3 confirmed `user` (not a custom `session_id`) survives in the indexed `/generation` record
for account-side lookup; observability only (probe 4 stickiness-neutral). One toggle governs **both** proxied routes
(server-gated `_provider_user_value`) and direct `core.llm` callers (plan-check, curation); both planes derive the id
from the same `derive_provider_session_id` hash, so a run's proxied and direct OpenRouter calls group identically
account-side.

Each proxy may define:

```yaml
costs:
  caps:
    per_day: 20.00
    per_month: 100.00
  on_cap_hit: reject  # reject | warn
provider_trace:
  retention_days: 14   # diagnostics, not spend truth; matches the audit plane
  max_total_mb: 512
```

`provider_trace` in `proxy.yaml` is **retention-only**. The user-injection opt-in moved to the global
`~/.forge/config.yaml` (`provider_trace.inject_provider_user`, governing both proxied and direct routes); a stale
`inject_provider_user` left in `proxy.yaml` loads with a one-time relocation warning and is ignored.

Caps are enforced after each completed request, from accumulated recorded spend: a request may cross a cap and complete,
then the next request is blocked once spend has reached the cap. Because spend accrues only from reported cost, **dollar
caps fire only for routes that report cost** (OpenRouter, LiteLLM non-streaming); Anthropic-passthrough and
LiteLLM-streaming dollar caps are no-ops (their tokens are still tracked). `reject` returns HTTP 429 with:

```json
{
  "type": "error",
  "error": {
    "type": "spend_cap_exceeded",
    "message": "daily spend cap reached: ..."
  }
}
```

`warn` mode forwards the request and returns the same message in `X-Spend-Warning`. Cost tracking is best effort:
cost-capture or log write failures must not break successful LLM responses.

#### Per-session usage read surface

`forge telemetry activity [session]` aggregates the captured per-session planes into a two-pane human-readable view. The
**Operation outcomes** pane reads upstream outcomes by `session` (policy checks, supervisor fail-open/no-call outcomes,
memory writer, supervisor shadow drain, shadow curation, workflows/workers, transfer curation, and action tagging). The
**Model calls** pane reads downstream spend/token evidence joined by run tree, with `usage/events` retained as a
transitional source for session-tagged run correlation, labels, legacy error counts, and fallback cost.
`downstream_only` therefore means "downstream/model-call evidence whose run tree is known to this session but has no
matching upstream outcome"; fully orphaned downstream records with no session-known run tree are not attributable to a
session. When older downstream schemas are fenced during an upgrade, the activity downstream pane reports
`skipped_legacy_schema` so a fully legacy window does not look like ordinary empty data.

The manifest's **`confirmed.policy.decisions`** remains a compatibility fallback for success/cached policy counts and
warning text that upstream suppresses at the default `upstream_event_volume=non_success`; it is capped at
`MAX_DECISION_LOG`, so `log_capped` marks that older success/cached counts may be missing. Upstream non-success outcomes
are uncapped, and manifest/upstream duplicate warnings are deduped. The aggregation is a UI-agnostic command-core
builder (`forge.core.ops.usage_summary.build_session_activity_summary`, §3.12) shared by the CLI and the compact
`render_summary_line(...)` launcher exit line (host, sidecar, and fork). Cost is reported-or-estimated and may be
partial; `forge telemetry costs show` stays the authoritative spend view. See
[design_appendix.md §A.13](design_appendix.md#a13-usage-attribution-ledger-schema-314) for the read surface and
coverage.

## 4. CLI and command surfaces

The `forge` CLI is the user-facing entry point for sessions, proxies, transfer, memory, policy, workflows, search,
configuration, and internal hook/status commands. Command-core operations live in `src/forge/core/ops/` and keep shared
business logic UI-agnostic for terminal commands and `%` direct commands.

**Command-shape policy:** Forge uses explicit verbs. Non-leaf groups print help when invoked without a subcommand; leaf
commands should perform the sensible action when optional arguments are omitted. Removed commands, options, and
shortcuts are clean breaks: the CLI framework reports unknown commands/options rather than carrying compatibility shims.

Full command inventories live in [cli_reference.md](cli_reference.md): terminal commands in
[§1](cli_reference.md#1-terminal-command-reference), `%` direct commands in
[§2](cli_reference.md#2-direct-command-reference).

## 5. Extensions, workflows, and testing

### 5.1 Extensions install model

**Installing the `forge` tool.** Forge ships on PyPI and is installed as a global tool (`uv tool install multi-forge` or
`pipx install multi-forge`), placing the bare `forge` launcher on `PATH` so it resolves from any shell and for
project-scoped `statusLine`, not only inside an activated project venv. Host Claude and Codex runtime hook registrations
instead invoke the literal absolute dispatcher path `<forge-home>/bin/forge-hook <name>` and do not depend on inherited
`PATH`; the dispatcher resolves `forge` from `~/.forge/runtime.json` and then known user-tool locations. A GUI/Dock
process inherits launchd's minimal `PATH` (which excludes `~/.local/bin`), so bare `forge` consumers can still be
unreachable there; `forge extension doctor` surfaces that fact via `on_path_minimal`. Contributors use an editable
install (`uv sync` → `.venv/bin/forge`); `FORGE_DEV=<absolute-checkout-root>` is a hard dispatcher branch that selects
that checkout for hook subprocesses in a relaunched managed session, while `scripts/setup.sh --local` provides the
persistent global editable launcher. `forge extension doctor` reports how Forge is installed and whether the bare
launcher is globally reachable — install kind (`global` / `editable` / `venv` / `unknown`), the resolved launcher path,
PATH reachability, dispatcher state, and the current process's dev-override state. This tool install is the prerequisite
to installing the extensions described below.

Forge extensions live in this repo and are installed via `forge extension enable`. Forge keeps the user/project/local
scope model and modular profiles (`minimal` / `standard` / `full`). Seven modules (commands, agents, skills, hooks,
status-line, permissions, codex-hooks) are combined into profiles. Commands, agents, and Claude settings remain Claude
surfaces. The SKILLS module instead compiles one logical skill into each selected runtime package: Claude user and
project/local packages go to `$CLAUDE_HOME/skills` and `<root>/.claude/skills`; Codex user and project packages go to
`$HOME/.agents/skills` and `<root>/.agents/skills`. Codex has no local skill scope and skills never use `$CODEX_HOME`.

Portable skills use `forge-skill.yaml` plus `content.md`; typed Claude/Codex adapters bind runtime capabilities and emit
a complete validated package. A legacy `SKILL.md` package remains a Claude-only compatibility source. The current
portable set is `challenge`, `smoke-test`, `review`, `review-docs`, and `understand`. `panel`, `analyze`, `debate`, and
`consensus` remain Claude-only until their `claude -p` worker engine is runtime-neutral; `walkthrough` and `qa` remain
Claude-only manual-test frontends.

`forge extension enable --runtime claude|codex|all` is repeatable and selects only SKILLS targets; it does not filter
commands, agents, settings, or hooks from the chosen profile. With no flag, a new enable keeps Claude and adds Codex
when its binary is detected. Re-enabling an existing installation retains its managed runtimes even when a binary is
temporarily absent. An explicit runtime selection refreshes those runtimes and preserves tracked packages for omitted
runtimes; sync uses the complete tracked runtime set. Removal belongs to disable. A pure Codex project skill install can
therefore avoid both the Claude version gate and `.claude/`, but only when the resolved module set contains no Claude
mutation.

Settings merge remains additive (hooks append + dedupe, permissions union). The `codex-hooks` module is separate from
Codex skill delivery: it registers `codex-session-start` and `codex-policy-check` as a marker-delimited managed block in
the user Codex config (`$CODEX_HOME/config.toml`) while project/local installs write no runtime hook blocks. This hook
module remains best-effort when Codex is absent or its config conflicts; explicit Codex SKILLS conflicts instead fail
the whole install preflight. An automatically selected package that Forge already manages also blocks if a new same-name
Codex duplicate appears, preventing sync from silently dropping ownership. Duplicate classification cross-references all
valid tracking rows: a package managed by another Forge scope remains a conflict whose recovery names that scope's exact
disable command, while only an untracked package receives remove-or-rename guidance. User-scope planning/status checks
every valid, present tracked project/local package of the same name, even outside the current directory chain, because a
new user package would be visible inside all of those projects. Registration alone is inert — Codex hooks fire only
after the user's one-time interactive trust ceremony (§3.9). `forge runtime preflight codex --verify-enrollment`
confirms enrollment by effect with one cheap managed turn. `~/.forge/installed.json` v2 tracks runtime skill packages
alongside the canonical file ledger for clean sync, status, and disable. A successful project/local enable then
establishes the Forge project described in §3. Package roots and descendant directory entries must remain real
directories: status marks a substituted symlink `invalid-target`, and every write, rollback, or removal revalidates the
directory chain before mutation. Tracked leaf-file symlinks remain valid for symlink install mode.

For pre-user-ownership installations, user-scope enable/sync prints one cleanup command per tracked root without opening
or enrolling it. `forge extension cleanup-project` previews one root by default and applies only with `--yes`; it
removes safe legacy Claude registrations and project Codex marker blocks, preserves unrelated settings/TOML, installs
the user-scoped runtime registrations, and enrolls the root last. A Codex block moved to user scope must be trusted
again because its config location and command bytes changed.

> Scope model, module inventory, merge rules, and tracking file details in
> [design_appendix.md §C](design_appendix.md#c-install-model-reference). Multi-scope installation behavior (dual user +
> project) is documented in [§C.5](design_appendix.md#c5-multi-scope-installation-skill-resolution).

### 5.2 Policy, skills, workflows, and memory

Forge's workflow layer is documented in [design_workflows.md](design_workflows.md): policy enforcement and supervisor
composition, skills as the scripting layer, workflow runners, memory writer/project memory, and their reference tables.
The main design doc keeps the ownership boundary: workflow settings are session-owned unless explicitly proxy-owned;
enforcement results are hook-written runtime facts. For project-memory documents, `forge_memory` is Forge-owned while
outer concept metadata is producer-owned; the normative compatibility and mutation contract lives in
[design_workflows.md §5.2](design_workflows.md#52-memory-doc-passports).

### 5.3 Test Infrastructure (Docker-based)

**Runtime architecture (host-based)**: Proxy runs on host (`subprocess.Popen`), Claude Code runs on host. End users do
NOT need Docker.

**Test infrastructure (Docker-based)**: Integration tests run inside Docker containers (developers/CI only) to ensure:

- No Dockerfile/fixture drift (single source of truth)
- Tests catch real bugs (e.g., proxy startup failures)
- Deterministic test environment across machines

**Test workflow**:

```bash
# Unit tests (no Docker needed)
uv run pytest tests/src -m "not integration"

# Integration tests (Docker required for developers/CI only)
make test-integration  # Runs: docker build + docker run pytest
```

### 5.4 Interactive manual testing

Checklist-driven manual testing covers UX, latency, and real-system failures that unit and integration tests miss. The
portable smoke test runs as `/forge:smoke-test` or `$smoke-test`; the Claude-only `/forge:walkthrough` and `/forge:qa`
provide the higher isolation tiers. The detailed pattern, annotation types, and wrappers live in
[design_appendix.md §D](design_appendix.md#d-interactive-manual-testing). The end-user guide is
[manual_testing.md](end-user/manual_testing.md).

## 6. Directory structure (monorepo)

```text
multi-forge/
├── src/
│   ├── forge/    # Python package
│   │   ├── core/        # Shared libraries
│   │   │   ├── llm/     # LLM client abstraction (see design_appendix.md §E)
│   │   │   ├── auth/    # Auth flows (LiteLLM, credential store)
│   │   │   ├── models/  # Model catalog (forge.models.yaml) + direct-model pins
│   │   │   ├── paths.py # Cross-cutting path helpers, including git-root discovery
│   │   │   ├── transcript.py # Shared Claude transcript parsing primitives
│   │   │   ├── tiers.py # Shared tier-word detection primitives
│   │   │   └── state/   # File-based state helpers
│   │   ├── session/     # Session manager
│   │   ├── install/     # Installer system
│   │   ├── proxy/       # Proxy - uses core.llm
│   │   │   └── ports.py # Loopback port probing shared by proxy startup paths
│   │   ├── policy/      # Policy - uses core.llm
│   │   └── status/      # Status dashboard
│   │
│   ├── commands/        # Slash commands (installed to ~/.claude/commands)
│   ├── agents/          # Agents (installed to ~/.claude/agents)
│   └── skills/          # Neutral/legacy sources compiled to runtime skill targets (design_workflows.md §3)
│
├── docs/
└── pyproject.toml
```

---

## 7. Isolation and Proxy Modes

| Concern                  | Solution                                     | Owner                                                                                             |
| ------------------------ | -------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| Security isolation       | Seatbelt/bubblewrap per-command              | Claude Code native ([sandbox-runtime](https://github.com/anthropic-experimental/sandbox-runtime)) |
| Full container isolation | microVMs via `docker sandbox run`            | [Docker Sandboxes](https://docs.docker.com/ai/sandboxes/claude-code/)                             |
| Proxy lifecycle coupling | `--sidecar` bundles proxy + Claude in Docker | Forge sidecar mode                                                                                |

**Sidecar mode** solves operational problems (not security): lifecycle coupling, port isolation, version consistency,
log isolation. Configurable via `~/.forge/config.yaml` (`proxy_mode: host|sidecar`), overrideable with `--sidecar` /
`--host-proxy`. The launch checkout supplies `.claude/`, while the session manifest's Forge root supplies `.forge/`;
Forge mounts both at their corresponding paths under `/workspace`. It does NOT mount all of `~/.forge` (UID issues,
undermines port isolation). The launcher stages the canonical Claude runtime-hook inventory at
`<forge_root>/.forge/sidecar-home/settings.json`, mounted as the in-container user scope at
`/root/.claude/settings.json`. Those entries use the image-resolvable bare form (`forge hook <name>`), because every
sidecar is already a managed session and does not need the host dispatcher's enrollment gate. The file is replaced on
every launch and the entrypoint merges `apiKeyHelper` into it idempotently; project `.claude/settings*.json` bytes are
never rewritten. `FORGE_FORGE_ROOT` is normalized to `/workspace` for hook reads, while deferred-work markers retain the
host checkout and manifest-owned Forge root separately.

The host `~/.forge/pending-work/` queue is always mounted read-write at `/root/.forge/pending-work/`, so
index/memory/shadow markers enqueued at Stop survive `--rm` and are drained only by the host CLI. **Narrow exception
(§7.x audit path):** when a session launches with a proxy id, the sidecar additionally mounts that proxy's
`~/.forge/proxies/<id>/` read-only (so the in-container proxy loads its intercept/audit overlay) and `~/.forge/audit/`,
`~/.forge/costs/`, `~/.forge/usage/`, and `~/.forge/telemetry/` read-write (so legacy audit/cost files,
downstream/upstream telemetry, cap state, and the usage-attribution ledger persist on the host instead of dying with the
`--rm` container — the ledger is the only record of the in-container supervisor/verb activity, and it feeds
`forge telemetry activity` and the session-end summary for sidecar sessions). These are the only global `~/.forge`
subdirectories mounted, preserving the port-isolation rationale. On Linux the sidecar runs as the host `--user uid:gid`;
that uid has no passwd entry, so the launcher pins `HOME=/root` and the image makes `/root` traversable/writable
(`chmod 0777 /root`) so the mapped uid can reach the `/root/.forge` and `/root/.claude` mounts — an accommodation for
the ephemeral single-session `--rm` sandbox, **not** a security-sandbox guarantee. Sidecar sessions also persist their
launch mode, extra mounts, and image in `intent.launch` so `forge session resume <name>` can replay the same runtime
wiring later. Project-scoped `statusLine` remains the D3 exception to user-scope hook ownership and resolves through the
sidecar image's `PATH`.

**Forge still owns:** Docker test infrastructure, runtime config. `src/forge/sidecar/` provides sidecar mode —
operational, not a security sandbox.

### 7.x Optional Always-On Proxy (audit and control)

A Forge proxy can be a user-controlled chokepoint that **observes** and optionally **controls** the wire between Claude
Code and the model provider. The audit/intercept fields default to inert, so existing proxies are unchanged; the shipped
`anthropic-passthrough` template is the deliberate exception (it opts into `inspect`). The motivation is operational:
agent quality can change at the harness boundary without leaving local evidence. A Forge-controlled proxy gives Forge a
durable observation point and a signature-safe control point.

**Two orthogonal axes** (kept distinct everywhere):

1. **Wire shape** (`wire_shape` on the proxy config) — how the request reaches the upstream:
   - `openai_translated` (default): `convert_anthropic_to_openai` → upstream → `convert_openai_to_anthropic`. **Strips
     `thinking`/`redacted_thinking` blocks** — inspectable but **not** signature-safe (lossy).
   - `anthropic_passthrough`: forwards the raw Anthropic body unchanged and streams the response back unchanged.
     **Preserves thinking blocks byte-for-byte** (signature-safe). Shipped as the `anthropic-passthrough` template
     (`provider: litellm` is a credential slot only; `wire_shape` is the wire truth, and `GET /` labels it so).
2. **Intercept mode** (`intercept.mode`, per proxy):
   - `passthrough` (default): no body inspection.
   - `inspect`: observe only — hash the system prompt + tool surface, detect drift, write redacted audit metadata.
   - `override`: inspect **plus** apply mutations to the current request. **Requires
     `wire_shape: anthropic_passthrough`** (rejected at config load otherwise) so mutations are signature-safe.

**Observe (`inspect`).** Before forwarding, the proxy records a redacted metadata audit record (hashes of the system
prompt and tool surface, cache markers, token counts — never plaintext) and runs drift detection: the first observation
of a hash dimension seeds a baseline; a later change emits a `drift` record. `audit.audit_full_body` (opt-in, OFF by
default) additionally captures **redacted** bodies (structure only — never plaintext, no raw-body mode): the request
body on every path, the response body only for non-streaming passthrough today (streaming/translated deferred; §A.12 has
the per-path contract). Retention (`audit.retention_days`, `audit.max_total_mb`) is enforced by `prune_audit_logs()` at
startup, so it is not a dangling promise.

**Control (`override`).** Builds → validates → applies a mutation plan to the **current request's control surfaces
only** — the system prompt and generation parameters, **never** historical messages:

- cache-aware `system_prompt_augment` (inserted after the last `cache_control` marker so the cached prefix stays
  byte-identical; markerless appends and flags cache invalidation);
- `system_prompt_guards` (`warn`/`block`/`strip`; all `block` checks run first, so a strip can't half-mutate a blocked
  request — a block returns HTTP 403 `intercept_guard_blocked`);
- reasoning-effort pin — **reuses** `tier_overrides.<tier>.reasoning_effort` as a floor (not a new key), in Anthropic
  `thinking.budget_tokens` units.

**Mutation-safety invariant (normative):** override fingerprints the `messages` list (SHA256) before and after apply and
raises (`RuntimeError`, fail-closed, no forward) if it changed. Override never writes `messages[0..n-1]`, so signed
reasoning in historical turns is untouched. Mutation records carry hashes/lengths/budgets only.

**Route-bound caveat.** Intercept is a property of the resolved proxy/route, not the session. A direct-mode session has
no chokepoint; launch-time preflight reports visibility explicitly (it never silently "degrades to passthrough").
`GET /` surfaces both axes (`wire_shape`, `intercept_mode`, `intercept.can_inspect`, `thinking_blocks_preserved`) so a
launcher can say "inspect active (signature-safe)" vs "inspect active (lossy)".

**Sidecar-recommended, host-supported.** Both modes support the audit path; sidecar is recommended for an always-on
posture (lifecycle-coupled, port-isolated), with the narrow mounts of §7 making in-container records host-visible.

**Read surface.** `forge proxy audit show [id]` and `forge proxy audit diff [id]` (drift + override mutations in one
timeline) render redacted records; `%proxy audit show|diff` is the in-session equivalent. Redaction happens **before**
persistence — the typed builders redact, then call the writer — so no raw body reaches disk.

See [design_appendix.md §A.11](design_appendix.md#a11-intercept-audit-and-request-logging-configuration-7x) (config
schema) and [§A.12](design_appendix.md#a12-audit-log-schema-7x) (audit record schema + log paths).

**Request-log hygiene (separate plane).** Normal proxy logging stays quiet by default so the durable answer to "what
happened to my request?" comes from the structured cost/audit/usage/provider-trace planes, not log volume. Successful
`GET /` runtime-truth polls log at DEBUG; INFO is reserved for `status >= 400` or slow polls (`elapsed > 1.0s`).
Streaming no longer dumps per-chunk bodies — a clean stream emits one DEBUG lifecycle summary (request id, chunk count,
first-chunk/final-usage flags), and INFO only on error or client disconnect (the passthrough relay surfaces disconnects
that were previously logged nowhere). The optional `logging.requests` block (per-proxy, strict, bounded, redacted —
[§A.11](design_appendix.md#a11-intercept-audit-and-request-logging-configuration-7x)) governs the debug
`~/.forge/logs/requests/` plane; `body_capture=full` is rejected (audit no-plaintext policy), and one shared
`prune_jsonl_shards` helper bounds the audit, provider-trace, and request planes alike.
