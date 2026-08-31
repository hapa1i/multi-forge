# Forge Design (Unified Architecture)

- **Session manager usage**: [session.md](end-user/session.md) (session management guide)
- **Memory writer usage**: [memory.md](end-user/memory.md) (automatic memory docs guide)
- **Search usage**: [search.md](end-user/search.md) (transcript search guide)
- **Skills usage**: [skills.md](end-user/skills.md) (review, understand, panel guide)
- **Session design**: [design_sessions.md](design_sessions.md) (session state, launches, transfer, hooks, queues, Codex)
- **Runtime design**: [design_runtime.md](design_runtime.md) (proxies, backends, routing, shared clients, isolation)
- **Telemetry design**: [design_telemetry.md](design_telemetry.md) (status, spend, audit, usage, provider lifecycle)
- **Installation design**: [design_installation.md](design_installation.md) (configuration, credentials, extensions)
- **Workflow design**: [design_workflows.md](design_workflows.md) (policy, skills, and workflow runners)
- **Memory design**: [design_memory.md](design_memory.md) (designated memory, passports, writers, activation)
- **Architecture history**: [design_history.md](design_history.md) (retired contracts and removal rationale)
- **CLI reference**: [cli_reference.md](cli_reference.md) (terminal and direct-command inventory)
- **Visual diagrams**: [diagrams.md](diagrams.md) (architecture diagrams)

Detailed schemas and operational references are divided among the domain documents above. Path identity remains in
[the project identity model](#project-identity-model); memory-passport ownership is in
[design_memory.md §5.2](design_memory.md#52-memory-doc-passports).

## 1. Philosophy: The "Glue" Approach

Forge is **not** a monolith. It is the **connective tissue** between specialized tools -- a monorepo of tools sharing
common libraries (Auth, Models, State) under a unified interface (`forge` CLI).

## 2. Core components (the "pieces")

These components run independently but share code (libraries/config).

| Component           | Responsibility                     | Location                                       |
| :------------------ | :--------------------------------- | :--------------------------------------------- |
| **Forge Proxy**     | Model routing, Auth, Tool fixing   | `src/forge/proxy/`                             |
| **Forge Session**   | Session isolation, Worktrees       | `src/forge/session/`                           |
| **Forge Skills**    | Agent workflows (Review, Planning) | `src/skills/` + `forge` CLI                    |
| **Forge Status**    | Visual feedback & Dashboard        | `src/forge/cli/status_line.py` + `statusline/` |
| **Forge Policy**    | Policy enforcement (TDD, safety)   | `src/forge/policy/`                            |
| **Commands/Agents** | Claude Code extensions             | `src/{commands,agents}/`                       |
| **Hooks**           | Lifecycle events (Claude Code)     | `src/forge/cli/hooks/`                         |

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
[design_installation.md §A.7b](design_installation.md#a7b-forge-env-var-vocabulary).

#### Project identity model

Path scopes nest as logical repo -> checkout -> Forge project -> working directory.

| Level             | Identity source                                  | Stored as       | Purpose                                               |
| ----------------- | ------------------------------------------------ | --------------- | ----------------------------------------------------- |
| **Logical Repo**  | `get_main_repo_root()` (git)                     | `project_root`  | Cross-project ops, `session list` default scope       |
| **Checkout**      | `git rev-parse --show-toplevel`                  | `checkout_root` | Worktree targeting for `--into`, relative_path anchor |
| **Forge Project** | Successful project/local extension enable        | `forge_root`    | Session root, artifact root, state scoping anchor     |
| **Working Dir**   | Launch CWD (= `forge_root` for managed sessions) | implicit        | Managed sessions always launch from `forge_root`      |

`core.paths.find_git_root` owns optional filesystem `.git` discovery; Claude's `find_project_root` retains its strict
`FileNotFoundError`. Git-subprocess helpers keep checkout/logical identity and bare/worktree behavior.

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
- **`workspace worktrees`**: derives the registered worktree family from Git's common directory and overlays
  workspace-scoped session and active counts. Membership is read-only and never persisted by Forge; outside Git, the
  command degrades to one directory member. Git records whose checkout is unavailable remain visible as `missing`.
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
  `--resume` across CWD boundaries (see [session design §3.9](design_sessions.md#39-session-resume-context-management)).

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
`--resume` structurally cannot offer (see
[session design §3.9](design_sessions.md#39-session-resume-context-management)).

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

| Artifact              | Path                                                             | Owned by                 | Purpose                                                                                 |
| --------------------- | ---------------------------------------------------------------- | ------------------------ | --------------------------------------------------------------------------------------- |
| Session file          | `<forge_root>/.forge/sessions/<session_name>/forge.session.json` | Forge Session + Hooks    | Session `intent`, `overrides`, and field-owned `confirmed` runtime facts                |
| Global session index  | `~/.forge/sessions/index.json`                                   | Forge Session            | Session metadata (name, `forge_root`, `project_root`); fast listing + project filtering |
| Active session index  | `~/.forge/sessions/active.json`                                  | Forge Session            | Ephemeral live-launch registry for delete warnings + stale pruning                      |
| Session event journal | `<forge_root>/.forge/artifacts/<session>/<domain>/events.jsonl`  | Forge Session            | Durable domain events using the shared schema-v1 envelope and required append seam      |
| Proxy registry        | `~/.forge/proxies/index.json`                                    | Forge Proxy Orchestrator | Running proxies (template ↔ base_url/port ↔ pid)                                        |
| Runtime config        | `~/.forge/config.yaml`                                           | Forge CLI                | Global runtime preferences (proxy mode, timeouts, context limit)                        |
| Installed manifest    | `~/.forge/installed.json`                                        | Forge Installer          | Tracks what `forge extension enable` installed for update/uninstall                     |
| Project registry      | `~/.forge/projects.json`                                         | Forge Installer          | Versioned trusted-root registry for user-scope hook gating                              |
| Project compat pin    | `<forge_root>/.forge/project.toml`                               | User / Forge Installer   | Optional `required_forge` guardrail for project-local state mutations                   |
| Work queue            | `~/.forge/pending-work/*.json`                                   | Forge Work Queue (§3.13) | Deferred work markers (stop, index, handoff, shadow)                                    |
| Usage ledger          | `~/.forge/usage/events/<month>_<pid>.jsonl`                      | Forge Usage Ledger       | Usage attribution events; schema §A.13                                                  |
| Optional events       | `~/.forge/events/*.jsonl`                                        | TBD                      | Debugging/analytics; optional                                                           |

The active session index is intentionally runtime-only. It is self-healed via launcher PID / sidecar container liveness
checks and must not be treated as durable session truth like the manifest or global session index.

Marked authority launches add the root run id and authority config/hook digests to their active entry. Those fields are
current-run evidence used by `session authority show`; they are not durable history and do not replace the session event
journal.

**Session liveness and launchability are separate.** A valid session manifest is the durable reservation for its name,
provenance, and conversation bindings. The global index is a derived publication layer: readers may prune a row only
when its corresponding manifest is absent, not when the recorded checkout is unavailable. Worktree presence is derived
at read time and is never persisted as another authority. `session list` and `session show` expose `launchability` as
`launchable`, `missing_worktree`, or `unknown` (when no validated recorded path is available); human output also names
the missing path and recovery command. If that path later reappears as a directory, the session becomes launchable
without a state migration.

A valid manifest with a missing recorded worktree remains a live, degraded session. Operations divide at the checkout
boundary:

| Operation                                     | Missing-worktree behavior                                                                                                      |
| --------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| list, get, show, and binding/name reads       | Retain the row and reservation; expose the derived degraded status.                                                            |
| resume, fork, launch, worktree-local mutation | Refuse before durable mutation, naming the recorded path and the recreate-or-delete recovery.                                  |
| `session repair`                              | Re-publish an orphan as degraded after the existing collision, binding, and unchanged-manifest checks; never claim a checkout. |
| `session delete`                              | Remove the manifest/index reservation explicitly; an already absent checkout is not an error.                                  |
| `forge clean`                                 | Report the degraded session but never auto-delete its valid manifest.                                                          |

Corrupt, unreadable, newer-schema, and identity-conflicting manifests retain their strict classifications and are not
promoted to valid degraded sessions. A nested project whose manifest disappeared with its checkout has no durable
reservation; any remaining row is ordinary prunable residue.

**Creation is one transaction; the manifest is the durable reservation.** Every path that mints a session
(`start_session`, fork, resume-child, relaunch) commits through `IndexStore.create_session_txn`, which holds the index
write lock across both durable writes: uniqueness checks, then the index row, then `SessionStore.create_exclusive` for
the manifest, then release. If the manifest write raises, the transaction removes its row inside the lock it already
holds and re-raises unchanged. Lock order is index -> manifest and never the reverse; `file_lock_for_target` is not
reentrant, so nothing inside the transaction may call a locking `IndexStore` method.

Two reservations, at different timescales. The manifest is the reservation that survives the process: `create_exclusive`
tests and writes under that manifest's own lock, so a successful call is an ownership token, and an index row alone
reserves nothing because `list_sessions` prunes rows whose manifest is missing. During creation, the held index lock is
the reservation -- which is what makes writing the row first safe. `write` remains an unconditional low-level primitive
for storage tests and controlled bootstrap paths; because it recreates a missing manifest, production mutations of a
published session use `update`, while creation and restoration use `create_session_txn` plus `create_exclusive`.

Row-first makes the crash residue prunable rather than durable:

| Killed                   | Residue                | Healing                                                             |
| ------------------------ | ---------------------- | ------------------------------------------------------------------- |
| before the row write     | nothing                | none needed                                                         |
| between row and manifest | index row, no manifest | pruned by `list_sessions`/`get_session`, or by the next transaction |
| after the manifest write | both present           | none needed                                                         |

Creation can no longer produce a manifest with no index row. A residue row is not a name reservation: the next same-name
transaction sees row-present + manifest-absent, prunes it, and proceeds -- so a direct retry succeeds with no
intervening `session list` or `session delete`. Creation pre-checks use `live_session_exists` (row **and** manifest) so
they fail fast on a real collision without rejecting a residue; `_name_is_taken` keeps the cheaper row-only check, where
skipping a residue name costs an auto-name suffix rather than an error.

**Deletion is the other producer of row-without-manifest, and is coordinated with creation.** `delete_session` removes
the manifest -- or the worktree containing it, for a nested project -- before it removes the row, and its transcript
phase runs in between, so the name reads as residue for as long as that takes. A concurrent creation may therefore
reclaim the name and publish a whole new session mid-delete; that is allowed, since the session being deleted is on its
way out. What must not happen is the delete then removing the replacement's row and manifest, so its terminal removal
goes through `IndexStore.delete_session_txn`, which removes the row **and** runs the manifest delete inside one index-
lock acquisition, and declines outright when a manifest exists at a name whose manifest that delete had already
destroyed. Verifying ownership and then deleting outside the lock would let a replacement land in between. The "already
destroyed" fact is derived from what the delete did -- the manifest was absent when it started, or it lives inside the
worktree being removed -- never from a probe taken later, which may already be looking at the replacement. Timestamps
cannot substitute either: `now_iso` has second granularity, so a same-second replacement is indistinguishable by
`created_at`. `fork --force` frees a stale target the same way and so declines the same way, raising
`SessionExistsError` rather than replacing a session that claimed the name during its cleanup.

The terminal transaction deletes the manifest before its row while holding the index lock, and `SessionStore.delete`
takes the same manifest lock as `update`. This preserves index -> manifest lock order, prevents an in-flight hook update
from recreating a manifest after the row is gone, and means manifest-lock failure leaves the still-complete session
published. Creation is protected separately by the outer index transaction; unconditional `write` is not a supported
production mutation of a published session. Deletion may wait up to the five-second CLI manifest-lock timeout while it
holds the global index lock, preferring a completed user-requested delete over a shorter contention failure. Once the
manifest is absent, any later failure leaves only a prunable row.

An exception from the manifest callback does not prove the manifest is absent -- `atomic_write_json` makes it durable at
`os.replace`, and a signal can arrive after that -- so compensation removes the row only when the manifest is provably
not there. Compensation itself never raises: it is unwinding the callback's exception, which the caller must receive
unchanged, and a row it fails to remove is prunable.

Locked readers never observe the in-flight state -- `list_sessions` and `get_session` take the index lock -- and their
unlocked filesystem probes are safe because every prune delete is re-verified under a re-acquired lock, which spares a
row republished in the meantime. Readers that deliberately skip the lock *can* see a row before its manifest, so the
binding scans read the row's conversation columns as well as the manifest, leaving an in-flight conversation reported as
bound: the safe direction for a uniqueness check.

Orphan manifests with no row still exist -- written by crashes before row-first creation shipped, or by older Forge
versions -- and still own their name and conversation binding invisibly to any index-driven check. Reads that decide
whether a **conversation** is already bound therefore also scan manifest directories under the project root —
`collect_bound_uuids(forge_root)` and `collect_bound_codex_threads(forge_root)`, which additionally read without pruning
and fail closed on the index *and* on every manifest they touch, so a read-only caller neither mutates the index nor
reports "unbound" because a read failed. An unreadable manifest raises `BindingLookupError` naming the directory to
repair: a swallowed read is indistinguishable from an absent binding, which is what would let one conversation bind
twice. `forge session repair` surfaces and re-indexes these orphans (preview by default, `--yes` to apply), scoped to
the current Forge root. The scan classifies each unindexed manifest — `repairable`, `missing-worktree`, `collision`,
`corrupt` (owned by `forge clean`), `unreadable`, or `unrepairable`. A missing-worktree record is an apply target:
repair republishes its recorded identity as degraded without recreating, probing through, or claiming the checkout.
Identity otherwise derives from the manifest's **recorded** worktree metadata, not its on-disk location, so a root-level
worktree session repairs to its linked worktree rather than the main checkout that stores its manifest. Collision
detection uses the same binding scans adoption uses (rows **and** the manifest behind each row, fail-closed; columns lag
or lead manifests), invoked without the per-root orphan walk so the manifests under classification are not counted as
live holders. A moved ordinary checkout is re-derived from its actual location: apply corrects the recorded
`worktree.path` and `forge_root` on disk, and leaves `confirmed.claude_project_root` alone — it points at Claude Code's
conversation namespace, which a checkout move does not relocate. Apply goes through `create_session_txn` with
`require_uuid_unbound=True` and a callback that verifies the manifest is byte-identical to the scanned copy
(`SessionStore.update_if_unchanged`), so a raced manifest compensates the row away instead of indexing somebody else's
session.

**A pre-existing conversation is bound by the same write that publishes the session.** Adoption passes its binding into
`start_session` — `claude_session_id` for the Claude arm, `confirmed.codex` for the Codex arm — rather than writing it
afterwards. Two properties follow. The id reaches the index row, so `require_uuid_unbound` can re-check uniqueness
**inside the index write lock**, the only lock shared across session names; the pre-check alone runs under a separate
acquisition and cannot stop two differently-named adopts of one conversation from both passing it. And no window exists
in which a published session lacks its binding. Codex therefore has its own index column (`codex_thread_id`) mirroring
`confirmed.codex.thread_id`. Ordinary paths learn the thread after a run, so shared `core/ops/codex_thread_index.py`
reconciles the column after manifest persistence, including drift; a stale value would guard a thread the session no
longer uses.

**Adoption also holds a conversation-scoped lock across its final scan and commit** (`conversation_lock`, under
`FORGE_HOME/locks/`). The index write lock is not sufficient on its own: the binding scans read manifest directories
without holding it, so a scan that ran before a competing adopt's manifest appeared would publish a second binding, and
the orphan scan could then only refuse the *third* attempt. Serializing scan-and-commit per conversation means the
loser's scan cannot run until the winner has published. This mattered most when creation wrote the manifest first and a
kill left an orphan owning the conversation; creation is now row-first, so that particular orphan is no longer produced,
but orphans predating the change persist and the scans still cover them. The lock is global rather than per-project
because a conversation is not project-scoped, and `flock` releases on process death, so a killed adopt frees it.

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
    codex_thread_id: str | None = None   # mirrors confirmed.codex.thread_id -- see the uniqueness note above
```

`session list --scope` controls filtering: **`workspace`** (default) filters by `project_root` -- shows sessions across
all worktrees and Forge projects within the same logical repo (the workspace). **`project`** filters by `forge_root` --
just this Forge project. **`all`** shows everything globally.

### 3.5 File ownership boundaries (normative)

To avoid writer conflicts:

- Forge Session (CLI) writes:
  - `~/.forge/sessions/index.json` (includes `forge_root`, `checkout_root`, `project_root` per entry)
  - `intent` + `overrides` sections in `<forge_root>/.forge/sessions/<session_name>/forge.session.json`
  - `intent.launch` records relaunch mode plus sidecar-specific options (image, extra mounts) when the session is
    created or derived
  - `intent.authority` records an optional advisory/producer designation. Creation, set/clear, and derivation serialize
    intent mutation with marked launch preflight under the session authority lock; a required journal failure rolls the
    manifest transition back (or removes a newly created session) before returning an error
  - `intent.consumer_lanes.<consumer>` (a `LaneRecord`) when a command requests a non-default lane for a consumer:
    `forge session lane set --consumer <id> --runtime/--backend` is the general surface for all four consumers
    (supervisor, memory-writer, shadow-curation, team-supervisor); the supervisor also has
    `forge session start`/`fork --supervisor-runtime` and `forge policy supervisor set <target> --runtime/--backend`.
    All write the same slot via `set_intent_lane` -- never a raw `set` override (epic consumer_lanes/T1b, T6a)
  - `confirmed` bootstrap/runtime fields written by the CLI: `derivation` (resume metadata), `is_sandboxed` (updated at
    launch time to reflect whether Claude is running via sidecar), `launch` (immutable launch facts recorded once at
    start — routing mode, proxy id/base URL, and whether/how an API key was made available to the child)
  - `confirmed.route_commit`, a runtime-neutral `{event_id, run_id}` pointer to the newest effective event in the
    session's routing journal. The route projector updates only this field atomically; it does not rotate `confirmed_by`
    or rewrite other confirmed facts
  - `confirmed.codex` for Codex-runtime sessions — `thread_id`, rollout path/source, auth posture, `last_run_at`,
    `context_delivery` — is CLI-written like `launch`: Codex hooks only fire from trust-enrolled homes
    (`enrollment_gated`), so the CLI records these from the `codex exec --json` stream (headless), receipt files, and
    filesystem discovery. Thread/rollout/auth/`last_run_at` refresh per turn; `context_delivery` is a start-turn
    delivery fact resume never rewrites. The `codex-session-start` hook's only writes are small receipt files under the
    session directory — `context-receipt.json` (staged-handoff delivery,
    [session design §3.9](design_sessions.md#39-session-resume-context-management)) or `observation-receipt.json`
    (nothing-staged turns — interactive thread capture) — and the CLI reconciles them into `confirmed.codex` after the
    turn, so the manifest stays CLI-owned. `confirmed.launch` stays unset for Codex sessions (it documents the ANTHROPIC
    key posture of interactive Claude and would misread), and `claude_session_id` stays `None` — which is what makes
    every Claude-resume predicate refuse Codex sessions.
  - `confirmed.adoption` — `source_runtime`, `adopted_at`, `source_path`, `model_basis` — is CLI-owned and written once
    when a manifest is bound to a **pre-existing** native conversation. No hook writes it. It exists as a separate field
    rather than a `confirmed_by` value because `confirmed_by` records who touched the manifest **most recently**: at
    least three writers stamp it (`cli:adopt`, `hook:stop`, `hook:pre-compact`), so origin recorded there would be
    overwritten within one turn. `model_basis` (`explicit` | `inferred` | `none`) records what produced
    `intent.launch.direct_model`, since a transcript that justified an inference is user-owned and may be gone before
    anyone asks why the session resumes on that model. Adoption writes `direct_model` **only** when it has a basis; with
    none it warns and leaves the field unset rather than persisting the current default, which would otherwise be
    applied unvalidated on a later `resume --proxy`.
  - Sets `FORGE_SESSION=<session_name>` when launching Claude
  - `claude_session_id` whenever the CLI starts a **new** Claude conversation — `forge session start` and transfer/fresh
    children (`session fork`, `resume --fresh`): the command core **pre-seeds** it (generates a UUID, writes it at
    creation, imposes it via `--session-id`) and the SessionStart hook validates it. **Native** fork launches
    (`--resume-mode native`, `--fork-session`) do **not** pre-seed — Claude mints the child UUID and the hook records
    it; Stop/StopFailure reconcile when native fork launches materialize a child UUID after startup.
- Shared session-event storage (`forge.session.events`) owns contained domain paths, schema-v1 envelopes, ids, enums,
  strict ordered reads, and lock/fsync-backed required appends. Authority control, launch, and hook surfaces write only
  `.forge/artifacts/<session>/authority/events.jsonl`; managed launch routing writes only
  `.forge/artifacts/<session>/routing/events.jsonl`. Each domain validates its own payload and continuity rules while
  reusing the same envelope and root run identity.
- Hooks write:
  - `confirmed` section **during the session**: `claude_session_id`, proxy identity, artifacts, policy state, transcript
    paths. SessionStart **validates** the pre-seeded `claude_session_id` (start and transfer/fresh-child paths) or
    **records** the Claude-minted one (native `--fork-session`); Stop and StopFailure are authoritative reconciliation
    points for the final live conversation identity. Hooks **never** write `confirmed.adoption`, and their rewrites of
    `confirmed_by` and `claude_session_id` leave it intact.
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
- Forge Installer writes after shared `install.path_policy` target and boundary validation:
  - `~/.forge/installed.json`
  - installed extension files + merged settings per chosen scope
- Forge memory passport commands write:
  - `forge_memory`, the Forge-owned tracking and writer contract
  - missing outer `type`, `title`, and `description` only when a passport is first created or explicitly upgraded
  - does not generate or maintain producer-owned `resource`, `tags`, or `timestamp`; removal deletes only `forge_memory`
  - detailed generation, preservation, and mutation boundaries are normative in
    [design_workflows.md §5.2](design_memory.md#52-memory-doc-passports)
- Proxy writes:
  - proxy-owned snapshot/cache files (if any)
- Status:
  - read state; do not invent truth
- Policy:
  - reads state; enforces policy decisions at well-defined boundaries (hooks, proxy)
  - writes only hook-owned confirmed state (e.g., `confirmed.policy`) when running as a hook adapter

> See [diagrams.md §4: Ownership Boundaries](diagrams.md#4-ownership-boundaries).

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

Shared terminal (`forge ...`) and direct (`%...` via `forge hook user-prompt-submit`) operations live in
`src/forge/core/ops/`, without Click, output, or hook JSON, and return typed results. Fork resolves one read-only plan;
`session.launch` owns pure preference/prompt resolution; command core owns creation, artifacts, rollback, and launch
planning; Click realizes routes, renders, and hands off; the manager rechecks races. Claude lifecycle paths share a
manifest context: recorded `forge_root` owns `SessionStore`; worktree is the guarded launch path.

`core/ops/policy.py` owns the registry-derived activation vocabulary, validation, and typed values shared by terminal
`forge policy enable|disable` and direct `%policy enable|disable`. The terminal surface still writes policy intent while
the direct surface writes session overrides; their session resolution, mutations, rendering, exit codes, and JSON shape
remain surface-owned. The module also owns the semantic supervisor lifecycle mutations shared by
`forge policy supervisor ...` and `%policy supervisor ...` (set/off/on/remove/reload/cascade), with each surface owning
its renderer. This keeps shared rules UI-free without collapsing distinct state owners.

## 4. CLI and command surfaces

`forge` exposes sessions, proxies, transfer, memory, policy, workflows, search, configuration, and internal hook/status
commands. Shared UI-agnostic operations live in `src/forge/core/ops/`.

`forge.core.metric_formatting` owns human token/USD strings. Callers select named policies; JSON stays numeric, and
status-line context size stays separate.

**Command-shape policy:** Forge uses explicit verbs. Non-leaf groups print help when invoked without a subcommand; leaf
commands should perform the sensible action when optional arguments are omitted. Removed commands, options, and
shortcuts are clean breaks: the CLI framework reports unknown commands/options rather than carrying compatibility shims.

Full command inventories live in [cli_reference.md](cli_reference.md): terminal commands in
[§1](cli_reference.md#1-terminal-command-reference), `%` direct commands in
[§2](cli_reference.md#2-direct-command-reference).

## 5. Extensions, workflows, and testing

### 5.2 Policy, skills, workflows, and memory

Forge's workflow layer is documented in [design_workflows.md](design_workflows.md): policy enforcement and supervisor
composition, skills as the scripting layer, workflow runners, memory writer/project memory, and their reference tables.
The main design doc keeps the ownership boundary: workflow settings are session-owned unless explicitly proxy-owned;
enforcement results are hook-written runtime facts. For project-memory documents, `forge_memory` is Forge-owned while
outer concept metadata is producer-owned; the normative compatibility and mutation contract lives in
[design_workflows.md §5.2](design_memory.md#52-memory-doc-passports).

## 6. Directory structure (monorepo)

```text
multi-forge/
├── src/
│   ├── forge/    # Python package
│   │   ├── core/        # Shared libraries
│   │   │   ├── llm/     # LLM client abstraction (see design.md §E)
│   │   │   ├── auth/    # Auth flows (LiteLLM, credential store)
│   │   │   ├── models/  # Model catalog (forge.models.yaml) + direct-model pins
│   │   │   ├── paths.py # Cross-cutting path helpers, including git-root discovery
│   │   │   ├── transcript.py # Shared Claude transcript parsing primitives
│   │   │   ├── tiers.py # Shared tier-word detection primitives
│   │   │   ├── wire_shapes.py # Wire-shape vocabulary leaf (shapes, validity, default)
│   │   │   └── state/   # File-based state helpers
│   │   ├── session/     # Session manager
│   │   │   ├── git.py       # Shared Git executable and logical-repository path discovery
│   │   │   └── workspace.py # Git-derived worktree-family discovery
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

### 3.4 Proxy vs no-proxy mode

- **Proxy mode**: Claude is configured to send requests to a proxy base URL (`ANTHROPIC_BASE_URL`).
  - The proxy (template ↔ base_url) is the **routing identity**.
  - Status/other tools may query the proxy (`GET /`) for tier→model mapping and context windows.
  - The optional always-on audit/intercept chokepoint (observe or control outbound traffic,
    [runtime design §7.x](design_runtime.md#7x-optional-always-on-proxy-audit-and-control)) is **proxy-mode only** —
    direct mode has no wire to observe.
- **No-proxy mode**: Claude talks to Anthropic directly.
  - Sessions, worktrees, hooks, and overrides still work (for session-owned fields).
  - `forge session start` and `forge session incognito` default to direct mode. Use `--proxy` for proxy routing.
  - `forge claude start --no-proxy` is a bare launcher (no session state) -- see below.
  - Tier/model routing doesn't apply—it's proxy-only. Claude Code uses Anthropic models directly.

Interactive model-first selection lives in `forge.core.ops.session_model_routing`, separately from the subprocess
resolver. Its read-only stage normalizes one explicit model request, applies strict explicit proxy/no-proxy constraints,
then preserves a compatible persisted route before consulting ordered `model_routes.yaml` candidates. A new Claude
request remains direct. Runtime proxy-registry order never changes automatic candidate order.

Proxy compatibility comes from the concrete template or instance's effective tier defaults and `model_alternatives`; an
opaque custom base URL cannot establish compatibility for an explicit model request. Automatic candidate admission reads
template ownership and credential/lifecycle requirements from `forge.backend.sources` without starting anything. After
the first admissible candidate is selected, a separate realization step invokes `ensure_proxy()` at most once for that
exact route, validates live identity and the concrete config, and never falls through to another source on failure. The
catalog loader requires a plain integer schema version and rejects `direct/claude_code` candidates whose model does not
normalize to a Claude tier.

Tier resolution is deterministic: explicit model tier, serving intrinsic Claude tier, serving proxy default, then a
unique serving tier. Remaining ambiguity is an error. The plan carries the selected tier's effective model and exact
catalog context window so resume/fork budget checks can run before the atomic session-intent transition.

**Normative rule:** A session records which proxy it is running with (`confirmed.proxy`), but **cannot override**
proxy-owned routing properties. (Proxy requests do not carry a stable session identifier.)

**Normative requirement: Launch Claude through Forge.** Two launch paths exist:

**Session-managed launch** (`forge session start`, `forge session resume`):

- Requires `.forge/` at `forge_root` (i.e. `forge extension enable` must have run -- see project identity model above)
- Creates/reuses session state in `<forge_root>/.forge/sessions/`
- Sets `FORGE_SESSION` env var -- hooks and status line can locate the correct session file
- Sets `ANTHROPIC_BASE_URL` env var in proxy mode -- routes requests to the correct proxy
- Validates preconditions (proxy healthy, session file exists)
- On a bare host resume, healthchecks the persisted proxy endpoint and every recorded identity field before committing
  launch routing or invoking Claude. It does not silently replace a dead or mismatched recorded proxy; an explicit
  `--proxy <template-or-id>` authorizes realization of a different live route.
- Records `confirmed.proxy` at session start when proxy mode is active

**Codex-runtime sessions** (`forge session start --runtime codex`, see
[session design §3.9](design_sessions.md#39-session-resume-context-management)) use the same session-managed path, but
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

## E. Shared LLM Client (`src/forge/core/llm/`)

`get_client()` returns `LiteLLMClient` for `litellm_remote`/`litellm_local` and `OpenRouterClient` for explicit
`provider="openrouter"`. Both use OpenAI-compatible endpoints; native `AnthropicClient` remains deferred.

**Purpose:** Unified async-first LLM client abstraction for Proxy, Policy, and Skills components.

### E.1 Design principles

1. **Async-first**: All clients async; sync usage via `SyncAdapter` wrapper
2. **Canonical types**: `Message`, `CompletionResponse`, `StreamEvent` -- no raw dicts
3. **Injectable credentials**: `CredentialManager` with TTL caching, testable
4. **Separation**: LLM calls only; tier orchestration stays in Proxy

### E.2 Module structure

```text
src/forge/core/llm/
├── __init__.py          # Factory + SyncAdapter
├── types.py             # Request/response models
├── protocols.py         # LLMClient protocol
├── credentials.py       # CredentialManager
├── detection.py         # Prefix detection
├── errors.py            # Client errors
├── openrouter_policy.py # Shared ZDR request-policy merge
└── clients/
    ├── base.py          # Shared helpers
    ├── litellm.py       # Remote/local LiteLLM
    ├── openai_compat.py # OpenAI-shape conversion
    └── openrouter.py    # Direct OpenRouter
```

### E.3 Core types

- `ModelHyperparameters`: token/temperature/top-p, reasoning/thinking/verbosity, timeout, prompt caching, `strict`, and
  provider-specific `extra` settings.
- `Message`: role/content plus optional `tool_call_id` and `tool_calls`.
- `CompletionResponse`: text/tool calls plus optional usage, cost, provider trace, and raw response.
- `StreamEvent`: text/tool-call/end/usage/error event with the corresponding optional payloads.

### E.4 Client protocol

```python
class LLMClient(Protocol):
    @property
    def model(self) -> str: ...
    async def complete(self, messages: list[Message], *, tools=None, hyperparams=None) -> CompletionResponse: ...
    def stream(self, messages, *, tools=None, hyperparams=None) -> AsyncGenerator[StreamEvent, None]: ...
    async def count_tokens(self, messages, tools=None) -> int: ...
```

`stream()` returns an async generator directly; callers consume it with `async for`.

### E.5 Factory and provider detection

```python
def get_client(
    model: str,
    *,
    provider: ProviderType | None = None,
    credentials: CredentialManager | None = None,
    default_hyperparams: ModelHyperparameters | None = None,
) -> LLMClient:
    """Sync factory, async methods. Provider auto-detected from model prefix."""
    # provider="openrouter" -> OpenRouterClient
    # gemini/ -> local LiteLLM; other known prefixes -> remote LiteLLM
```

Without `provider`, unprefixed or unknown model IDs fail closed. Explicit OpenRouter bypasses prefix detection. Direct
Anthropic remains unimplemented; `anthropic/<model>` intentionally selects remote LiteLLM.

### E.6 Sync adapter

```python
class SyncAdapter:
    """Wraps async client for sync contexts. Uses asyncio.run() -- cannot nest in event loop."""
    def ask(self, prompt: str, *, system: str | None = None) -> str: ...
```

> **Trap:** Policy uses `SyncAdapter`; Proxy is async. Don't import sync Policy logic into Proxy -- `asyncio.run()`
> crashes in running loop. Use async-first at boundaries.

### E.7 Unsupported parameter policy

`ModelHyperparameters.strict`, `UnsupportedParamError`, and `handle_unsupported_param()` define the intended
warn-or-raise policy, but the current clients do not invoke that helper. Callers must not rely on `strict=True` to
reject provider-unsupported parameters until client wiring lands.

### E.8 Relationship to Proxy

| Concern                        | Owner              |
| ------------------------------ | ------------------ |
| LLM API calls, auth, streaming | `core.llm`         |
| Tier mappings, templates       | `proxy.templates`  |
| Format conversion              | `proxy.converters` |

---
