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
[design_appendix.md §A.7b](design_appendix.md#a7b-forge-env-var-vocabulary).

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

### 3.3 Session file schema (`forge.session.json`)

A Forge session is a durable workflow record, not a process-invocation record. A Claude-runtime session records its
current or last-seen conversation in `confirmed.claude_session_id`; multiple process invocations may reattach to that
conversation, and hooks reconcile the identity when Claude rolls it over. Codex-runtime sessions use the analogous
`confirmed.codex.thread_id` and leave `claude_session_id` unset.

For Claude, `confirmed.claude_session_id` has field-specific CLI/hook ownership depending on the launch path.
`forge session start` **pre-seeds** it: the CLI generates a UUID, writes it to the manifest at creation, and imposes it
on Claude via `--session-id`; the SessionStart hook then **validates** that UUID. The same pre-seed applies to
**transfer/fresh children** (the cross-worktree default for `session fork` and `resume --fresh`): Forge mints a **new**
UUID and imposes it via `--session-id`. The exception is a **native** fork (`--resume-mode native`, which passes
`--fork-session`): Forge does **not** pre-seed — Claude mints the child UUID and SessionStart **discovers and records**
it (`native-relocate` instead reuses the parent's UUID). A third origination path is `forge session adopt`, which
**binds** an existing native UUID: the conversation already exists, so the CLI neither mints nor discovers, it records
what the user names and cross-checks the transcript's recorded `cwd` before writing (§3.3 identity is unchanged — one
manifest per conversation, and reattach behaves exactly as it does for a Forge-born session).

The same command adopts a native **Codex** thread: the runtime is decided by which store holds a matching conversation,
never by the shape of the id (both runtimes use UUIDs, and their differing versions are an undocumented third-party
detail), and a match in both is refused rather than guessed. The Codex arm records
`confirmed.codex.rollout_source="adopted"` and leaves `claude_session_id`/`confirmed.launch` unset; its lookup scans
every thread-id match and filters by the rollout head's `cwd`, refusing an ambiguous result instead of taking
`find_rollout_path`'s newest-mtime tie-break. The id must be a canonical UUID: it is the only caller-supplied component
of every path adoption reads or writes. Omitting it previews the unbound Claude conversations whose recorded `cwd` is
the current directory — a read-only CLI scan of one encoded project directory, which does not relax §3.10: hooks still
resolve sessions by identity and never scan. Adoption also inverts transcript ownership, so
`SessionManager.delete_session` exempts an adopted session's native transcript from `delete_transcripts` (including the
`delete_transcripts=True` automatic retention sweep) using the same filter that spares transcripts shared with another
session. Adoption resolves the `.forge/artifacts` root before enforcing destination containment, so relocating that root
with a symlink is supported; a descendant destination that escapes the resolved root or aliases the native transcript is
refused, and rollback only unlinks an artifact created by the current copy attempt. Stop and StopFailure also reconcile
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

Before strict decoding, a no-write allowlist migration strips legacy `intent.memory.generated_file` only at that path;
new writes omit it.

`intent` and `overrides` are required objects. Missing `confirmed` defaults empty; when present, it must be an object.
Other values are corruption, surfaced without rewriting.

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

**`intent.authority`**: optional, session-owned artifact authority:

```yaml
authority:
  role: advisory        # advisory | producer
  tier: shell_closed    # advisory only; named_tools | shell_closed
```

Absence is `unmarked` and retains legacy behavior. Advisory defaults to `shell_closed`; producer must not carry a tier.
The role is provider- and model-neutral. It is mutated only by authority-bearing creation flags or the typed inactive-
session `authority set|clear` operations, never by generic overrides. Fresh derivation inherits advisory authority and
its tier; producer authority is deliberately dropped. An explicit child designation wins before first launch.

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
- `intent.launch.runtime` is immutable dispatch identity: set rejects the direct key, a parent `launch` object carrying
  `runtime`, and `launch.*` before mutation. A whole-launch null clear remains valid because the section is optional and
  dispatch reads raw intent; reset accepts `launch` or `launch.runtime` so stale illegal overrides remain recoverable.
- `intent.authority` is not overrideable: set and keyed reset reject the parent, wildcard, and concrete leaves.
  `reset --all` clears only overrides and cannot alter authority intent.

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
  strict ordered reads, and lock/fsync-backed required appends. Authority control, launch, and hook surfaces are M1's
  sole shipped domain consumer; they write only `.forge/artifacts/<session>/authority/events.jsonl`. The reserved
  `routing` domain exists for the proposed M2 consumer but M1 never creates it.
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
  routing is authoritative. Tier hyperparameters have no direct provider/tier environment-variable layer. Authentication
  refresh rebuilds the same resolved `(model, tier)` client identity.
- **Proxy Template**: operational profile defining provider, endpoint, and tier mappings for proxy creation.
- **Model Catalog**: internal capability facts (`model_catalog.yaml`), not user-editable or a model ranking.
- **ModelRoute**: derived routing option pairing a model with a provider/credential/template. Generated by
  `derive_model_routes()`, not hand-authored.
- **RoutingResult**: structured subprocess routing result: base URL, proxy id, resolution source, selected route, and
  warning. Replaces bare `str | None`.

#### 3.6.2 Field ownership invariants (normative)

- **Proxy-owned**: tier→model mappings, provider/base_url, default hyperparams (`reasoning_effort`, `temperature`,
  `verbosity`, `thinking_budget_tokens`), and direct-OpenRouter-proxy ZDR settings; LiteLLM has no ZDR surface.
- **Forge-owned direct OpenRouter calls**: plan checking and transfer/rewind curation always require ZDR; proxy opt-outs
  do not apply.
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

**Inert config transition.** Config authored by Forge ≤0.9.4 remains readable for one release window. Explicit
`proxy.<provider>.enable_preamble`, `proxy.<provider>.openai_api_mode`, `session.manifest_filename`, and proxy-instance
`provider_settings.openai_api_mode` warn once per process; omission is silent and writers drop them. They are inert:
backend and `wire_shape` select transport; `MANIFEST_FILENAME` fixes paths. Later releases may reject them.

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

**Stop/delete ownership contract.** A required process stop that is refused or fails exits non-zero and keeps the
registry row and proxy configuration as actionable ownership. `delete` decides shared-port ownership under the registry
lock; when the target is the last live reference and termination is required, it completes that stop before removing the
row or overlay. A later overlay-removal failure restores the row with stopped state when termination already succeeded.
Default adopted detach, explicit `--no-kill`, already-stopped processes, and deletion while another live same-port alias
remains are intentional successful outcomes. Multi-delete continues independent targets but exits non-zero and reports
failures if any required stop fails.

**Create smoke-result contract.** On the normal reuse/adopt/spawn path, `proxy create --json` emits one creation result.
Without `--smoke-test`, its established top-level fields remain unchanged. With `--smoke-test`, the same object adds
`smoke_test: {passed, detail}`; a failed probe exits non-zero but retains the successfully created or resolved proxy.
Human-mode verification output remains unchanged. `--no-start` is config-only and does not run a smoke probe.

**Translated request-metadata contract.** The `openai_translated` route carries the inbound User-Agent through internal
`_user_agent` metadata for both LiteLLM (local or remote) and OpenRouter clients. The adapter strips control characters
and caps the upstream value at 256 characters. This is a narrow identity relay, not general header passthrough:
authorization, API keys, cookies, and internal `X-Forge-*` correlation headers do not enter it, and the Anthropic-native
and Responses passthrough allowlists are unchanged.

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

Forge subprocesses (workflow workers, semantic and team supervisors, memory writer) share `resolve_subprocess_routing()`
when they need Forge-owned transport selection. This replaced ad-hoc resolution paths that implemented different
fallback chains with different semantics. Intentional direct and runtime-native arms bypass the resolver.

**Resolution chain** (sources not supplied by a caller are skipped):

| Step | Source             | Behavior                                                                                        |
| ---- | ------------------ | ----------------------------------------------------------------------------------------------- |
| 1    | `explicit`         | Opaque base-URL override                                                                        |
| 2    | `explicit`         | Named CLI/config proxy; strict registration, reachability, and route compatibility              |
| 3    | `subprocess_proxy` | Ambient `FORGE_SUBPROCESS_PROXY`; strict, or host-injected sidecar URL/metadata                 |
| 4    | `preferred_proxy`  | Catalog hint (`ModelSpec.preferred_proxy`); soft -- skip if not running                         |
| 5    | `route_scan`       | Find any running proxy compatible with a derived `ModelRoute`                                   |
| 6    | `session_proxy`    | Inherited `ANTHROPIC_BASE_URL`; opaque URLs are accepted when the caller does not require route |
| 7    | `unresolved`       | No route found; callers decide fail-open vs fail-closed                                         |

`source="direct"` is produced by workflow routing (`review.routing`) for direct-only model specs (e.g., `claude-opus`
running `claude -p --bare`), not by the shared resolver. Workflow routing also produces `source="runtime_native"` for
the Codex worker; that source intentionally has no `ModelRoute` because Codex owns model selection and auth. More
generally, `route=None` can also mean unresolved or opaque/non-model-specific routing (e.g., explicit base URL), so
`source` and `base_url` distinguish the cases.

**Supervisor model scope:** When semantic-supervisor routing resolves to a proxy URL, it invokes
`claude -p --model opus` and clears inherited Claude model-pin env vars (`ANTHROPIC_MODEL`,
`ANTHROPIC_DEFAULT_*_MODEL`). This keeps executor/session `--model` pins local to the executor while allowing the
semantic supervisor to use the selected proxy's `opus` tier.

The team supervisor also clears inherited model pins whenever any source resolves a base URL, including explicit,
ambient, inherited, and sidecar-injected URLs. It deliberately does **not** pass `--model opus`: the resumed team
supervisor keeps its existing model posture instead of acquiring semantic-supervisor tier policy. `direct=True` skips
resolution, while a truly unresolved route dispatches direct; both retain inherited model pins.

**Team commitment boundary:** The team handler resolves routing before its `on_dispatch` callback. Explicit or ambient
named proxies are strict: missing, corrupt, or unreachable entries fail open by skipping the check before lane freeze or
dispatch-usage emission. This includes an ambient `FORGE_SUBPROCESS_PROXY` that is unregistered (previously silently
fell through to direct) and one that is registered but unreachable (previously failed after dispatch commitment).
Reachable ambient proxies, inherited `ANTHROPIC_BASE_URL`, and sidecar-injected URLs keep the same destination but are
now visible early enough for cost tracking and model-pin scrubbing. The team caller supplies no `ModelRoute`, so
`preferred_proxy` and `route_scan` are no-ops.

This chain applies to the supervisor's default `claude_code` lane. The `codex` lane arm (the supervisor's
`consumer_lanes` binding, epic consumer_lanes) bypasses it entirely: `codex exec` runs **direct** to OpenAI with no
Forge proxy. See [design_appendix.md §G](design_appendix.md#g-subprocess-routing-reference) for the consumer-lane layer.

**Fail behavior by subprocess type:**

| Subprocess          | On unresolved   | Rationale                                                        |
| ------------------- | --------------- | ---------------------------------------------------------------- |
| Workflows           | Fail closed     | User asked for this work; partial results worse than an error    |
| Semantic supervisor | Fail open       | Blocking the coding session is worse than skipping a check       |
| Team supervisor     | Dispatch direct | No configured route is a valid direct resumed-session posture    |
| Memory writer       | Fail open       | Async/best-effort; benefits future sessions, not the current one |

**Review worker preparation:** `review.worker_preparation` owns role/stance marker validation and fill, stable worker
IDs/labels, and `model:assignment` parsing. Commands retain domain types, routing/fan-out, and JSON schemas.

**Per-invocation routing plan:** Workflow commands resolve one frozen `WorkerRoutingPlan` for all workers at invocation
start. With Codex, it freezes one fresh cached readiness/auth/billing preflight; no workflow verb runs an inline doctor.
This prevents fan-out drift and keeps two-round consensus on one snapshot. Workflow JSON exposes decisions in
`resolved_models`: runtime, requested/actual model, provider, proxy, template, source, and selection state. Codex
entries report `resolved_model=null` and `model_selection="runtime_default"` because Forge neither pins nor observes the
exact model.

> **Routing reference details** — data type schemas (`ModelRoute`, `RoutingResult`, `WorkerRoutingPlan`), function
> signatures, route derivation ranking, and sidecar constraints are in
> [design_appendix.md §G](design_appendix.md#g-subprocess-routing-reference).

### 3.7 Proxy runtime truth

When reachable, live proxy `GET /` is authoritative for tier→model mappings and context windows; caches are not:

```json
{
  "is_proxy": true,
  "status": "running",
  "proxy": { "template": "litellm-openai", "base_url": "http://localhost:8085" },
  "wire_shape": "openai_translated",
  "intercept_mode": "passthrough",
  "intercept": { "mode": "passthrough", "can_inspect": { "...": "..." } },
  "tiers": {
    "haiku": { "model": "gpt-4o-mini", "context_window": 128000 },
    "sonnet": { "model": "gpt-4o", "context_window": 128000 },
    "opus": { "model": "o3", "context_window": 200000 }
  },
  "runtime": {
    "configured_tier_mappings": { "...": "..." },
    "tier_mappings": { "...": "..." },
    "data_policy": { "zdr": "not_applicable", "zdr_fallbacks": {} }
  }
}
```

**Key points:**

- Proxy and session state remain independent; status tools read both (see §3.6.2).
- Top-level `status` is `running` when downstream retention resolves and completes without an enforcement error; it is
  `degraded` when retention resolution or pruning fails. Degraded retention remains reachable and keeps the proxy
  identity fields available; the nested `downstream_retention` object carries the recovery detail.
- Spend cap rejections return HTTP 429 with `error.type=spend_cap_exceeded`
- Warn-mode spend caps allow the request and attach `X-Spend-Warning`
- `wire_shape` is the authoritative wire truth (a passthrough proxy may carry `provider: litellm` as a credential slot
  only); `intercept_mode` + `intercept.can_inspect` let a launcher report "inspect active (signature-safe)" vs "inspect
  active (lossy)" before launch (§7.x)
- `wire_shape: openai_responses_passthrough` is the **Codex-facing** raw OpenAI **Responses** shape on `/v1/responses*`
  (create + retrieve/cancel/input_items/delete/compact/input_tokens). It forwards traffic byte-for-byte (signature-safe;
  `can_inspect.*=false`, like `anthropic_passthrough`). Routing requires that wire shape plus backend
  `responses_ingress`; `GET /`'s `capabilities.responses_ingress` and Codex preflight's `proxy_supported` expose the
  conjunction. Reported `x-litellm-response-cost` is USD→micros; an OpenAI-direct upstream is token-telemetry-only. The
  launcher is `forge codex start --proxy` (§3.4). The shared `proxy.sse_framing` incremental data/JSON framer serves
  both raw passthrough usage taps; accumulators own protocol event merging and lifecycle semantics.

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

**Session event journals:**

- The authority domain writes `<forge_root>/.forge/artifacts/{session_name}/authority/events.jsonl`. The shared
  authority-neutral `forge.session.events` module owns the schema-v1 envelope, `sevt_` ids, UTC timestamps, frozen
  origin/operation/outcome enums, strict JSON validation, and domain payload hook. M1 is the only shipped consumer;
  route history remains proposed and no routing journal is created.
- Path construction validates the session name, uses an explicit domain allowlist, resolves beneath the owning
  `forge_root`, and rejects absolute/traversal/symlink escape shapes before creation. Each journal has its own lock.
  Appends write one compact UTF-8 JSON object plus newline, reject non-JSON values, flush/fsync the file and directory,
  and propagate lock/open/write/fsync failure to required callers. The reader rejects unreadable, truncated, unknown,
  malformed, duplicate-id, and newer-schema records without skipping a line.
- Authority configuration, inheritance, preflight, and lifecycle appends are required transactions. Denial logging is
  best effort only after the runtime deny is already fixed; a journal failure cannot weaken it.
- Absence is not proof. A marked session with missing or manifest-inconsistent history reports `unproven`; an unmarked
  session with no journal reports `null`. Malformed history is an error. The append-only convention is local evidence,
  not tamper resistance against humans or external processes.
- Session delete/clean never selectively removes the authority directory, regardless of transcript flags. The journal
  follows its containing Forge root: root-level worktree sessions retain it in the parent root, while deleting an owned
  checkout that contains a nested/forked Forge root removes the complete artifact tree with that checkout.

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
- Canonical manifest identity is the pair `(session_id, copied_path)`. Stop refreshes that record after overwriting the
  UUID-named copy; rollover retains an existing successful record when its idempotent copy is skipped. Repeated writes
  reconcile duplicates for that identity without deleting distinct transcript records.

**Session file fields (hook-owned, additive):**

- `confirmed.latest_plan_path`: pointer to the latest plan file in `.claude/plans/…` (draft pointer)
- `confirmed.artifacts.plans[]`: entries like:
  - `{ kind: "approved", captured_at, source_path, snapshot_path }`
- `confirmed.artifacts.transcripts[]`: entries like:
  - `{ captured_at, reason: "stop"|"stop-failure"|"rollover"|"adopt", source_path, session_id, copied_path, copied }`
- `confirmed.compaction.transcript_snapshots[]`: PreCompact-only entries like:
  - `{ captured_at, reason: "pre-compact", source_path, snapshot_path, copied }`

The canonical transcript list is validated at its shared session-layer write and latest-read seams. A non-list field or
an unrelated malformed entry is surfaced rather than clobbered or skipped. Readers explicitly tolerate older
`copied_path`-only records, warn about them, and preserve them because no stable `session_id` can be reconstructed
safely; new writes always carry complete identity. The known legacy shape where PreCompact also appended a
`snapshot_path` record to the canonical list emits a compatibility diagnostic and moves to the compaction collection on
the next transcript-related write. Manager derivation, transfer assembly, and both full-strategy budget preflights use
the same latest-canonical-record selector, so a trailing legacy snapshot cannot hide the resumable transcript.

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
creates a real Codex-runtime session (manifest `intent.launch.runtime="codex"`, immutable — direct, parent-object, and
wildcard override writes are rejected), keys the transfer snapshot by the **real session name** so
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

Both Codex frontends share one post-turn deletion boundary. If an explicit delete removes the session while Codex is
running, the completed runtime result or TUI exit status still returns with a warning, while manifest and index fact
reconciliation are skipped. A delete that lands between the manifest-presence check and the locked update may make the
lock layer recreate an empty or lock-only session directory; Forge removes only that shell. Any other directory content
is preserved, and corruption, unreadability, or lock timeout remains a strict error rather than being mistaken for
deletion.

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

Transfer accepts only these values before writes and persists the value used.

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

Null strategy on native rows is a writer convention, not a schema guard: strict reads tolerate `native-relocate` with
non-null `strategy` and `context_file`. `rewind` writes truncated Claude JSONL under a fresh UUID and launches
`--resume <R> --fork-session` with a code-delta prompt. A Claude Code 2.1.197 probe and
`tests/integration/docker/test_rewind_native_contract.py` confirm that `<R>` may retain the parent's embedded
`sessionId`, resume across CWD, and stay unmutated; no envelope rewrite is needed. Unusable code-delta curation removes
the temporary JSONL, falls back to plain native resume/native-relocate, and reports the fallback; dropped-window
curation emits the `ai-curated` privacy warning. Fork rollback removes newly owned transfer snapshots, preserves
existing snapshots and shared worktrees, and reports cleanup failures.

**Context budget enforcement:** Every resume mode chooses the same reference: explicit proxy ID then template; direct
mode none; otherwise inherited proxy ID then template. For `full`, Forge **fails fast** before spawn when the parent
transcript exceeds that proxy's window, naming `structured`/`ai-curated` as fixes. Other strategies need no budget
preflight.

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
`context_file`. Worktree and `--into` forks start with `resume_mode: transfer`; the execution op enriches `strategy` and
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

**Authority launch transaction:** Every managed launch path mints one root `RunIdentity` before invocation and rereads
authority intent under the session authority lock. An unmarked launch retains that lock for the complete legacy child
lifetime, preventing a concurrent control-plane command from assigning authority after the launcher committed to an
unmarked environment; its existing active registration remains best-effort. A marked launch instead proves the runtime
seam, requires active registration, and durably appends `launch_preflight` then `run_started` under the lock before
releasing it and invoking the child. Set/clear use the same lock and turn live-launch contention into a short,
actionable refusal. The invoker does not remint the identity. Forge always attempts same-run `run_ended` and clears
marked active state. A failed preflight produces `launch_aborted` and no started claim. A spawn exception after the
commit is `child_never_spawned`; a spawned child returning nonzero is `child_exited_nonzero`, so `run_started` means
“Forge committed to invoke,” not “the child was observed alive.”

Advisory Claude requires the exact catch-all registration and current executable dispatcher. Advisory Codex requires
exactly one user-scope no-matcher `codex-policy-check` row with the installed command bytes and timeout, then performs
the empirical `codex-session-start` enrollment check for every attempt. Advisory sidecar is unsupported until its
selected image has an equivalent pre-spawn proof; Forge therefore does not stage the host-only authority catch-all in
sidecar settings. Producer launches record config/lifecycle posture without requiring an enforcement seam; unmarked
launches keep the legacy path and create no authority events. Only a validated advisory attempt receives the internal
marker, containing session/runtime, the one root run id, and config/hook digests. The transaction exposes the future M2
insertion point after authority preflight, but M1 writes no routing journal or projection.

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

**Authority precedes ordinary policy.** Claude installs a dedicated catch-all `authority-check` at 60 seconds while
retaining the existing Write/Edit `policy-check` rows. The standalone dispatcher examines only marker presence before
project gating or Forge resolution: absent returns immediately; present, even malformed, dispatches for fail-closed
validation. Codex keeps its trust-sensitive no-matcher `codex-policy-check` registration bytes unchanged and evaluates
authority at the top of that handler, before tool filtering, `policy.enabled`, bundles/supervisor, and its patch
adapter. Both guards classify the raw tool name before path/payload normalization. A covered request or guard failure
denies; denial-journal failure is diagnostic and cannot change that decision. An authority decline never grants
permission and ordinary runtime permission/policy behavior continues.

The guarantee ends at a functioning delivered handler response. Runtime non-delivery, command timeout, dispatcher
startup/execution failure, and a runtime discarding malformed output remain fail-open seams. This is not OS-level
immutability or an authorship/admission attestation.

**Deployment model:** Forge installs hook **settings only** (no scripts in `.claude/`). Runtime hook registrations are
user-scoped and contain the literal absolute dispatcher command `<forge-home>/bin/forge-hook <name>`; project/local
installs do not write hook blocks. The hidden hook-handler surface remains `forge hook <name>`, so runtime + deps live
with the Forge package (single upgrade surface). For `authority-check`, the advisory-marker fast gate described above
runs before every ordinary dispatcher check. For other hooks, the dispatcher first applies its no-op gate: a managed
session dispatches regardless of cwd, while an unmanaged launch dispatches only from an enrolled root. After validating
the handler name, a present `FORGE_DEV` selects exactly `<absolute-checkout-root>/.venv/bin/forge`; an empty, relative,
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
- `forge hook pre-compact` (PreCompact): Captures the full transcript before compaction and records it only under
  `confirmed.compaction.transcript_snapshots`. This is the canonical compaction snapshot; SessionStart rollover is
  fallback for `/clear` and defense-in-depth.
- `forge hook post-compact` (PostCompact): Records compaction metadata (`last_compact_at`, `last_compact_type`).
- `forge hook worktree-create` (WorktreeCreate): Replaces Claude Code worktree creation and installs Forge extensions.
  It strict-checks source, creates the checkout, maps nested roots, then strict-checks target before writes. Refusal
  removes the checkout/branch and reports incomplete cleanup. `config_copy.py` expands only symlink-free directories per
  file, excluding tracked and nested `.git`/`node_modules` paths; dirty cleanup unlinks rechecked untracked files and
  `rmdir`-prunes empty directories. `.forge/project.toml` stays uncopied, preserving tracked pins. Prints worktree path
  to stdout; only this hook exits non-zero.
- `forge hook subagent-stop` (SubagentStop): Tracks subagent activity (`total_count`, `by_type`, transcript path,
  message preview). Observe-only (phase 1).

**Stop hook pipeline:**

The Stop hook does multiple things. To avoid blocking exit and ensure idempotency across repeated invocations, it
performs synchronous capture/verification and then only enqueues deferred work:

```
Stop Pipeline:

  [Sync - blocks exit decision, must be <100ms except explicit test_suite wall time]
   1. capture_artifacts()    Copy transcript and reconcile its canonical record (idempotent via UUID)
  2. run_verification()     Classify completion promise or fixed test suite result
  3. apply_verification()   Apply block|warn|allow posture → returns allow|block

  [Deferred - Stop writes markers; it does not launch a writer]
  4. enqueue stop/index markers
  5. enqueue handoff marker when memory is enabled
  6. enqueue shadow marker when pending shadow candidates exist

  return verification_decision

Later eligible Forge CLI startup:
  7. opportunistically drain pending work
  8. handoff handler launches detached `forge memory-writer run` and returns
  9. detached writer scans passports and synthesizes updates
```

The under-100-ms budget covers Forge-owned work, including verification dispatch and result persistence. A session that
explicitly selects `test_suite` asks Stop to synchronously run the fixed `uv run pytest` subprocess, so only that
external process's bounded wall time is excluded from the budget. The subprocess runs without a shell in the resolved
session worktree and inherits the session environment. No user-configurable command is executed at Stop.

New writes accept only `completion_promise | test_suite` and `block | warn | allow`. Legacy unknown strings remain
readable but warn and fail open as `misconfigured`; they never become a pass or acquire implicit blocking semantics. The
result classifier records `passed`, `incomplete`, `misconfigured`, or `infrastructure_error`. A configured promise
absent from the last assistant message, a non-zero test exit, or a test timeout after launch is incomplete and follows
the configured posture. Missing or multiline promise configuration is misconfigured. Unavailable inputs, worktree or
executable failures, and other execution errors are infrastructure failures and allow Stop with a diagnostic.
Persistence failure also allows Stop. Captured subprocess diagnostics are secret-redacted and bounded before display or
persistence.

The memory writer runs asynchronously in a detached process after a later, non-exempt Forge CLI startup drains the
handoff marker. Memory doc updates are eventually consistent; this is acceptable because they benefit future sessions,
not the exiting session.

**Idempotency rules** (verification can trigger Stop multiple times per session):

| Step             | Multiple invocations safe? | How                                                 |
| ---------------- | -------------------------- | --------------------------------------------------- |
| Artifact copy    | ✔ Yes                      | Writes to UUID-named path, overwrites are identical |
| Verification     | ✔ Yes                      | Stateless check of last message                     |
| Deferred enqueue | ✔ Yes                      | Same marker ID atomically refreshes one work item   |

**Deferred enqueue:** The Stop hook attempts stop and index markers, a handoff marker when memory is enabled, and a
shadow marker when pending shadow candidates exist. A later eligible CLI startup drains the handoff marker and launches
the detached writer; the Stop hook never spawns it. See §3.13 (Async Work Queue) for the queue contract, schema, and
processing model.

This keeps the ordinary Stop hook fast (\<100ms) while arranging memory-writer work and indexing after subsequent
eligible CLI activity; the explicitly selected blocking test-suite mode is the named exception above.

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
handling deletes the marker; poison markers (5+ attempts) move to `pending-work/failed/`. An existing marker that cannot
be read stays byte-identical and pending without consuming a retry; startup emits a diagnostic and continues with later
markers. A readable marker with a strictly newer integer schema is also left byte-identical and pending: the older
consumer does not interpret or dispatch its payload, consume a retry, or move it to `failed/`, and startup emits
actionable upgrade guidance once per process. The startup scan remains capped: when a bounded window leaves unreadable,
newer-schema, lock-contended, or unhandled markers pending, an internal `.scan-cursor` resumes after that window on the
next drain so every marker gets a turn. A nonempty window with no resident deferred or skipped work clears the cursor;
an empty queue simply ignores it. Malformed JSON is known-bad content and moves directly to `failed/`.

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

`core.telemetry.jsonl_io` owns sorted telemetry-shard reads, object-line decoding, and period matching; plane readers
retain schema fences, warnings, counters, filters, typed decoding, and sorting. `core.state.timestamps` owns ISO parsing
and local bounds: telemetry permits naive-as-UTC, each CLI owns `all`, and `TZ` accepts IANA, absolute/colon TZif, and
POSIX forms with `/etc/localtime` fallback. Relative display selects compact/full-word styles.

Downstream attempts are the proxy-spend source of truth. **Forge is not a cost oracle:** it records only route-reported
cost (OpenRouter `usage.cost` or LiteLLM `x-litellm-response-cost`) with its reporter/confidence, and records
`cost_micros:null`/`confidence="unavailable"` otherwise; no local price catalog infers dollars from tokens. Nullable
`backend_id` names the logical backend instance, distinct from the telemetry-origin `source_id`/`source_kind`; direct
emitters set it only when the mapping is unambiguous. Schema-v2 readers fence older records with a warning and expose
skip counts rather than reattribute them.

`CostTracker` takes the larger attempt/checkpoint total. Completion updates counters before an unbounded FIFO worker
persists cost/trace and coalesced snapshots. Shutdown drains jobs and retries failed checkpoints; hangs can delay it.
Passthrough response-body audit and overload/drop stay separate. Current-month shards preserve restart evidence.

The directory's lifecycle owner is global `telemetry.downstream` in `~/.forge/config.yaml` (`14` days/`512` MB by
default; `0` disables either bound). After cap bootstrap, each process resolves once and prunes once. Explicit global
config wins; otherwise agreeing explicit legacy values become warned `legacy_consensus`, omissions do not conflict, and
conflicting/unreadable inputs disable pruning with degraded status. Startup never rewrites proxy files. Explicit
`forge config migrate-retention [--yes]` writes the global owner before removing still-matching legacy keys; human/JSON
status exposes configured/effective/source plus deprecations and conflicts.

The legacy `costs/verbs/` writer and reader have been removed. The default `forge telemetry costs show` by-verb view
joins downstream attempts to `usage/events` by `forge_run_id`. Unique joined run IDs count runs; downstream rows count
requests, and unjoined requests remain "Interactive"/unattributed. The usage ledger itself remains during the transition
for session activity and run-tree joins, but it is no longer the durable spend source.

The transitional **usage-attribution ledger** (`~/.forge/usage/events/`, schema in
[§A.13](design_appendix.md#a13-usage-attribution-ledger-schema-314)) records which run/workflow/session invoked each
model and carries `route`, `reporter`, `confidence`, consumption, and latency. It remains physically separate from
downstream, where spend, audit, and provider-lifecycle evidence coexist. Workflow verbs and headless consumers emit
best-effort events that never gate measured work. Direct `core.llm` calls may join by `source_refs.cost_request_id`;
`claude -p` cannot know individual proxy request ids, so its `source_refs` stays null. Instead, validated run-tree
headers let the proxy record `forge_run_id`/`forge_root_run_id`, and `forge telemetry activity`/`forge +$Y` join exact
downstream cost by root run id (one run can make many requests, so a single request ref is the wrong shape).

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

**Provider lifecycle evidence.** Backend-gated fields record dispatch, provider, and stream progress
([§A.14](design_appendix.md#a14-provider-lifecycle-fields-in-downstream-telemetry-314)); trace reads are local and
exclude prompts/secrets. Global `provider_trace.inject_provider_user` hashes run grouping across proxy/direct paths and
affects observability only.

Each proxy may define:

```yaml
costs:
  caps:
    per_day: 20.00
    per_month: 100.00
  on_cap_hit: reject  # reject | warn
```

The user-injection opt-in is global in `~/.forge/config.yaml` (`provider_trace.inject_provider_user`, governing both
proxied and direct routes). Downstream lifecycle is also global, under `telemetry.downstream`. The old proxy-local
`audit`/`provider_trace` retention keys remain deprecated migration inputs for one compatibility release; new proxy
files do not author them. A stale `inject_provider_user` left in `proxy.yaml` loads with a one-time relocation warning
and is ignored.

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

`forge extension enable` installs repository extensions at user/project/local scope with `minimal`, `standard`, or
`full` profiles. Six modules (commands, agents, skills, hooks, status-line, permissions) have durable runtime owners.
Commands, agents, status line, and permissions are Claude-owned; skills and hooks are owned by both Claude and Codex.
`module_planning.py` owns module policy; `installer.py` owns discovery/apply order: setup/cache, dispatcher/files,
settings/ownership, stale reconciliation, Codex, assembly, tracking. Skills compile per runtime: Claude targets are
`$CLAUDE_HOME/skills` (user) and `<root>/.claude/skills` (project/local); Codex targets are `$HOME/.agents/skills`
(user) and `<root>/.agents/skills` (project). Codex has no local skill scope and skills never use `$CODEX_HOME`.

Portable skills use `forge-skill.yaml` plus `content.md`; typed Claude/Codex adapters bind runtime capabilities and emit
a complete validated package. A legacy `SKILL.md` package remains a Claude-only compatibility source. The current
portable set is `challenge`, `smoke-test`, `review`, `review-docs`, `understand`, `panel`, `analyze`, `debate`, and
`consensus`. The workflow frontends do not imply Codex workers by default: worker runtime is selected independently and
the default worker set remains Claude-backed. `walkthrough` and `qa` remain Claude-only manual-test frontends.

Skill selection permission is global user configuration, not an enable-time flag. Every shipped source defaults to
human/explicit-only invocation, and `~/.forge/config.yaml` may opt individual names into model invocation under
`skills.invocation`. Installer planning resolves that mapping with an absent-name default of `explicit`, then gives the
effective boolean to the compiler for both Claude's `disable-model-invocation` frontmatter and Codex's
`agents/openai.yaml` policy. Enable materializes the current mapping; sync recompiles tracked runtime packages after a
configuration change. The Claude settings preset is not an authority because it cannot govern Codex output. Malformed
skill configuration degrades to the explicit-only default.

`forge extension enable --runtime claude|codex|all` is repeatable and filters every resolved module against its declared
runtime owners. Profile-selected wrong-owner modules become visible skips; a wrong-owner module named through `--with`
is a conflict, as is an explicit runtime selection that leaves no effective module. With no flag, a new enable keeps
Claude and adds Codex when its binary is detected. Re-enabling an existing installation retains its managed runtimes
even when a binary is temporarily absent. Explicit narrowing refreshes selected surfaces and preserves omitted tracked
runtime ownership; sync derives its runtime set from the durable ownership relation. Removal belongs to disable.

Settings merge remains additive (hooks append + dedupe, permissions union). The shared `hooks` module registers Claude
settings and, when Codex is selected, `codex-session-start` and `codex-policy-check` in a marker-delimited user Codex
config block (`$CODEX_HOME/config.toml`). Project/local installs write no runtime hook blocks. The Codex half remains
best-effort when Codex is absent or its config conflicts; explicit Codex skill conflicts instead fail the whole install
preflight. An automatically selected package that Forge already manages also blocks if a new same-name Codex duplicate
appears, preventing sync from silently dropping ownership. Duplicate classification cross-references all valid tracking
rows: a package managed by another Forge scope remains a conflict whose recovery names that scope's exact disable
command, while only an untracked package receives remove-or-rename guidance. User-scope planning/status checks every
valid, present tracked project/local package of the same name, even outside the current directory chain, because a new
user package would be visible inside all of those projects. Registration alone is inert — Codex hooks fire only after
the user's one-time interactive trust ceremony (§3.9). `forge runtime preflight codex --verify-enrollment` confirms
enrollment by effect with one cheap managed turn. `~/.forge/installed.json` schema v3 records a sorted `module_owners`
relation and a required tagged attribution on every file/settings row; v1/v2 migrate in memory through frozen historical
readers and persist v3 on the next successful mutation, so no reset is required. Runtime skill packages remain backed by
the canonical file ledger for clean sync, status, and disable. A successful project/local enable then establishes the
Forge project described in §3. Package roots and descendant directory entries must remain real directories: status marks
a substituted symlink `invalid-target`, and every write, rollback, or removal revalidates the directory chain before
mutation. Tracked leaf-file symlinks remain valid for symlink install mode.

Every compiled runtime package also emits a deterministic `.forge-package.json` provenance sentinel. It records schema
version 1, producer, runtime, skill name, and sorted payload file digests/modes; it contains no timestamps, absolute
paths, cache locations, or Forge version and is excluded from its own file list. The sentinel is always installed as a
regular copy, participates in cache digests, tracking, sync, and disable, and introduces one intentional cache-digest
change on upgrade.

Runtime targets are also scanned independently of tracked-package health. The scanner reads one validated tracking
snapshot, treats only exact canonical package targets in coherent schema-v3 rows as managed, and observes direct
children whose name is current/historical Forge output or whose real directory carries the sentinel. Unknown unmarked
directories remain user content. Unmanaged entries are reported separately from the four tracked states, including
partial and unsafe blockers, malformed/newer markers, modified trees, and Codex visibility collisions. Corrupt or
unreadable tracking is a no-scan boundary. Current names come from names-only source discovery, so malformed source
contents do not block status or unrelated cleanup categories; if source-name discovery itself is unavailable, the scan
continues with the append-only historical set while installer planning retains full source/Git validation.

The scanner never traverses a selected runtime root that is a symlink, another non-directory type, or unreadable. Such a
root cannot supply the skill name required by the fixed package record, so the scan carries a separate immutable root
issue: human status renders its path/runtime/reason, JSON emits no synthetic package row, and clean never lists it.
Missing roots remain silently skipped.

Cleanup is intentionally narrower than detection. `forge clean` lists an unmanaged package only when a regular strict
sentinel, exact tree, bytes/modes (or the bounded compiled-cache dangling-link reset case), real writable/package/
descendant directories, target scope, and absent tracking all prove that the exact directory is Forge output with no
extra content. Project/workspace scopes inspect known project/local roots; `all` also inspects both fixed user roots.
Apply performs a fresh scan, retains a private filesystem-identity proof, anchors the real runtime root, and immediately
rechecks proof/identity/compatibility before removing the direct child. Enable/sync never adopts or overwrites an
unmanaged package: a proven orphan names the matching clean preview/apply and retry sequence, while every report-only
entry keeps exact-path remove-or-rename guidance.

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
undermines port isolation). The launcher stages the canonical sidecar-compatible Claude runtime-hook inventory at
`<forge_root>/.forge/sidecar-home/settings.json`, mounted as the in-container user scope at
`/root/.claude/settings.json`. Those entries use the image-resolvable bare form (`forge hook <name>`), because every
sidecar is already a managed session and does not need the host dispatcher's enrollment gate. The unsupported advisory
authority catch-all is host-only and omitted from this inventory because its bare command lacks the dispatcher fast
gate. The file is replaced on every launch and the entrypoint merges `apiKeyHelper` into it idempotently; project
`.claude/settings*.json` bytes are never rewritten. `FORGE_FORGE_ROOT` is normalized to `/workspace` for hook reads,
while deferred-work markers retain the host checkout and manifest-owned Forge root separately. Stop therefore probes for
pending shadow candidates through the mounted `/workspace` Forge root and translates only the resulting marker payload
back to host-resolvable paths.

The host `~/.forge/pending-work/` queue is mounted read-write at `/root/.forge/pending-work/`, so Stop-enqueued
index/memory/shadow markers survive `--rm` for host-CLI draining. **Narrow exception (§7.x audit path):** a proxy-id
session also mounts its `~/.forge/proxies/<id>/` read-only for intercept/audit config and, when the host file exists,
`~/.forge/config.yaml` read-only at `/root/.forge/config.yaml` for global runtime settings. It mounts `~/.forge/audit/`,
`~/.forge/costs/`, `~/.forge/usage/`, and `~/.forge/telemetry/` read-write so legacy audit/cost files,
downstream/upstream telemetry, cap state, and the usage-attribution ledger survive container removal. That ledger is the
only record of in-container supervisor/verb activity and feeds `forge telemetry activity` and the session-end summary
for sidecar sessions. These are the only global `~/.forge` subdirectories mounted, preserving the port-isolation
rationale. On Linux the sidecar runs as the host `--user uid:gid`; that uid has no passwd entry, so the launcher pins
`HOME=/root` and the image makes `/root` traversable/writable (`chmod 0777 /root`) so the mapped uid can reach the
`/root/.forge` and `/root/.claude` mounts — an accommodation for the ephemeral single-session `--rm` sandbox, **not** a
security-sandbox guarantee. Sidecar sessions also persist their launch mode, extra mounts, and image in `intent.launch`
so `forge session resume <name>` can replay the same runtime wiring later. Project-scoped `statusLine` remains the D3
exception to user-scope hook ownership and resolves through the sidecar image's `PATH`.

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
     `thinking`/`redacted_thinking` blocks** — inspectable but **not** signature-safe (lossy). Tool choice maps `any` →
     `required`, `auto` → `auto`, named → named function, and `none` → `none` across GPT Responses; impossible filtered
     required/named choices return HTTP 400 before upstream acquisition.
   - `anthropic_passthrough`: forwards the raw Anthropic body unchanged and streams the response back unchanged.
     **Preserves thinking blocks byte-for-byte** (signature-safe). Shipped as the `anthropic-passthrough` template
     (`provider: litellm` is a credential slot only; `wire_shape` is the wire truth, and `GET /` labels it so).

2. **Intercept mode** (`intercept.mode`, per proxy):

   - `passthrough` (default): no body inspection.
   - `inspect`: observe only — hash the system prompt + tool surface, detect drift, write redacted audit metadata.
   - `override`: inspect **plus** apply mutations to the current request. **Requires
     `wire_shape: anthropic_passthrough`** (rejected at config load otherwise) so mutations are signature-safe.

At proxy ingress, optional client `X-Request-ID` values are untrusted correlation metadata. Forge preserves values of
1--128 ASCII letters, digits, `.`, `_`, and `-` exactly; absent or invalid values are replaced with a fresh endpoint
identifier (`req_`, `tok_`, or `inf_`) before request state, logs, telemetry, audit, or response handling diverges. The
rejected value is neither normalized nor recorded.

Forge's direct `core.llm` request-ID minter is contract-tested against this ingress validator. That coupling preserves
the exact `source_refs.cost_request_id` join when a registered Forge proxy is the resolved target.

Both raw passthrough transports share one response-header boundary. Safe provider metadata such as `retry-after` and
rate-limit counters is relayed on successful, error, streaming, and non-streaming upstream responses. Hop-by-hop fields
(including names nominated by `Connection`), authentication/cookie fields, OpenAI account selectors, content
length/encoding, and upstream proxy-owned fields (`x-request-id`, cost/resolution headers, and `X-Forge-*`) are stripped
case-insensitively. Forge then overlays its own request id, spend warning, and streaming `Cache-Control` with
case-insensitive replacement. Header handling never mutates the relayed response body or SSE chunks.

**Observe (`inspect`).** Before forwarding, the proxy records a redacted metadata audit record (hashes of the system
prompt and tool surface, cache markers, token counts — never plaintext) and runs drift detection: the first observation
of a hash dimension seeds a baseline; a later change emits a `drift` record. `audit.audit_full_body` (opt-in, OFF by
default) additionally captures **redacted** bodies (structure only — never plaintext, no raw-body mode): the request
body on every path, the response body only for non-streaming passthrough today (streaming/translated deferred; §A.12 has
the per-path contract). The global `telemetry.downstream` policy bounds these shared shards; audit does not own a
separate pruner or effective retention promise.

**Control (`override`).** Builds → validates → applies a mutation plan to the **current request's control surfaces
only** — the system prompt and generation parameters, **never** historical messages:

- cache-aware `system_prompt_augment` (inserted after the last `cache_control` marker so the cached prefix stays
  byte-identical; markerless appends and flags cache invalidation);
- `system_prompt_guards` (`warn`/`block`/`strip`; all `block` checks run first, so a strip can't half-mutate a blocked
  request — a block returns HTTP 403 `intercept_guard_blocked`);
- reasoning-effort pin — **reuses** `tier_overrides.<tier>.reasoning_effort` as a floor (not a new key), in Anthropic
  `thinking.budget_tokens` units. If the pin changes `thinking`, Forge removes `temperature`, `top_p`, and `top_k` from
  that request because Anthropic rejects the combination; a no-op pin leaves those fields unchanged.

**Mutation-safety invariant (normative):** override fingerprints the `messages` list (SHA256) before and after apply and
raises (`RuntimeError`, fail-closed, no forward) if it changed. Override never writes `messages[0..n-1]`, so signed
reasoning in historical turns is untouched. Mutation records carry hashes/lengths/budgets and removed sampling key names
only, never sampling values.

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
