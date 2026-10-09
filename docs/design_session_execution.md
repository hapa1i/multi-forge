# Forge Session Execution Design

Canonical hook, work-queue, Codex-runtime, and session-journal contracts. See [session design](design_sessions.md) for
durable state and the domain map.

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
Persistence failure also allows Stop. Captured subprocess diagnostics have terminal sequences removed, then secret
redaction brackets C0 cursor rendering so neither raw secrets nor render-reconstructed secrets cross the boundary;
remaining unsafe controls are removed before the result is bounded for display or persistence. Control-free streams use
bulk translation instead of Python character iteration to preserve the Forge-owned latency budget.

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
> [design_session_execution.md §B](design_session_execution.md#b-work-queue-internals).

## B. Work Queue Internals

Extracted from [design.md §3.13](design_session_execution.md#313-async-work-queue). Design goals and rationale remain in
design.md.

### B.1 Marker schema (v1)

```json
{
    "schema_version": 1,
    "kind": "stop",
    "marker_id": "uuid-123",
    "forge_version": "<current Forge version>",
    "created_at": "2026-01-07T12:00:00Z",
    "payload": {
        "session_id": "uuid-123",
        "worktree_path": "/abs/path/to/checkout",
        "forge_root": "/abs/path/to/forge/project",
        "session_name": "my-session",
        "transcript_snapshot_rel": ".forge/artifacts/..."
    },
    "attempt_count": 0,
    "last_attempt_at": null,
    "last_error": null
}
```

**Key fields:** `kind` routes to a handler; `marker_id` is the idempotency/filename key and must match
`^[A-Za-z0-9._-]+$`; `payload` is kind-specific; `attempt_count`/`last_error` track retries. `forge_root` is optional
when resolvable from `worktree_path`. `handoff` and `shadow` snapshot available origin run IDs so detached workers
retain session attribution ([design_workflows.md §4.5](design_workflows.md#45-operational-constraints)); `handoff` may
also snapshot the Stop-time `subprocess_proxy`.

### B.2 Processing contract

Handlers are passed explicitly as a `handlers` dict (no global registry -- avoids import-order coupling and test state
leakage): `process_pending_work(handlers={"stop": handler, "index": handler})`.

Byte preservation is a consumer-drain guarantee. A producer that re-enqueues the same `marker_id` retains the existing
atomic-replacement behavior, refreshing the current representation of that logical work item.

A bounded window containing unreadable, newer-schema, lock-contended, or unhandled resident work advances the scan
cursor past the whole window. This preserves the startup cap while allowing later actionable markers to run on a
subsequent drain.

| Outcome                                      | Behavior                                                                                                |
| -------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| Handler succeeds                             | Delete marker under lock                                                                                |
| Handler raises                               | Keep marker, increment `attempt_count`, write `last_error` under lock                                   |
| Marker read is unreadable (`OSError`)        | Leave bytes unchanged and pending; diagnose, skip, and advance the bounded scan cursor                  |
| `schema_version` is a strictly newer integer | Leave bytes unchanged and pending; diagnose once per process, skip, and advance the bounded scan cursor |
| Marker contains malformed JSON               | Move directly to `pending-work/failed/`                                                                 |
| Lock contention                              | Skip, leave pending, and advance the bounded scan cursor                                                |
| No handler for kind                          | Skip, leave pending (debug log), and advance the bounded scan cursor                                    |
| `attempt_count >= MAX_ATTEMPTS` (5)          | Move to `pending-work/failed/` (poison marker, preserved for debugging)                                 |

### B.3 Known marker kinds

| Kind      | Producer                                       | Handler                                  |
| --------- | ---------------------------------------------- | ---------------------------------------- |
| `stop`    | Stop / StopFailure hooks                       | No-op (delete only)                      |
| `index`   | Stop / StopFailure hooks                       | Index transcript for search              |
| `handoff` | Stop hook when memory auto-update is enabled   | Spawn detached `forge memory-writer run` |
| `shadow`  | Stop hook when pending shadow candidates exist | Spawn detached `forge policy shadow run` |

`handoff` remains the ephemeral queue routing key for memory-writer work; it is distinct from session-transfer context.

---

## I. Codex Runtime Reference

This reference builds on [session design §3.9](design_session_context.md#39-session-resume-context-management) and
[design_workflows.md §3.5](design_workflows.md#35-workflow-runners). Lifecycle narrative (headless turns, interactive
TUI sessions, delivery modes, post-exit reconciliation) remains in design.md.

### I.1 Recorded Codex facts (`confirmed.codex`)

All CLI-owned (§3.5):

| Field                                          | Source                                                                                                                     |
| ---------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| `thread_id`                                    | Stream `thread.started` (headless) or post-exit reconciliation (interactive)                                               |
| `rollout_path` / `rollout_source`              | See provenance table below                                                                                                 |
| `auth_method` / `auth_source` / `billing_mode` | Preflight's secret-free auth posture (refreshed per turn)                                                                  |
| `last_run_at`                                  | Per turn                                                                                                                   |
| `context_delivery`                             | `initial_message \| session_start_hook \| hook_undelivered`; `None` for bare interactive starts (a transfer-delivery fact) |

`rollout_source` provenance (the matching file is `$CODEX_HOME/sessions/…/rollout-*-<thread_id>.jsonl`):

- `discovered_by_thread_id`: glob located by a stream-known thread_id.
- `session_start_hook`: a receipt's codex-reported `transcript_path` supersedes the glob; a receipt can also recover a
  `thread_id` the stream missed.
- `discovered_post_exit`: interactive time+cwd discovery — the rollout **filename** is the thread source (filename
  timestamps are local time, so discovery filters by mtime).
- `adopted`: `forge session adopt <thread-id>` bound a rollout that predates the session, so `last_run_at` and
  `context_delivery` stay `None` until the first managed turn. Lookup scans **all** thread-id matches and filters by the
  rollout head's `cwd`, refusing zero, mismatched, or multiple matches. It must not use `find_rollout_path`'s
  newest-mtime tie-break because adoption binds its choice.

`confirmed.launch` and `claude_session_id` stay unset (§3.5). Shared `core/ops/codex_thread_index.py` mirrors post-turn
`thread_id` into the adoption-guarded index after manifest persistence.

### I.2 Codex `RuntimeSpec` declarations

Load-bearing values (probe evidence in `scripts/experiments/codex-hooks/README.md`):

- `native_hooks="enrollment_gated"`: hooks fire only after a one-time interactive TUI trust ceremony. Trust keys on the
  registering config's path; `trusted_hash` is not black-box computable, so enrollment is never verifiable pre-turn.
- `pretool_policy="partial"`: post-enrollment PreToolUse deny + `updatedInput` are pinned headless, but enforcement
  exists only in enrolled homes. Malformed hook output fails open; PermissionRequest has not been observed firing.
- `interactive="default"`: Forge-managed interactive sessions (bare TUI start and `codex resume` reattach, §3.9).
- `skill_scopes=("user", "project")`: Codex skills target `$HOME/.agents/skills` and project `.agents/skills` only. This
  is independent of `install_scopes`; local remains unsupported because Codex has no private local-only skill directory.
  Claude declares user/project/local for both fields.
- `hook_min_version`: machine-readable registration floor a preflight checks — not a firing guarantee.
- `hook_feature_flag=None`: Codex hooks are default-on.

`forge runtime list` shows `SKILL SCOPES` separately from general `SCOPES`; its JSON records both `skill_scopes` and
`install_scopes`.

### I.3 Codex operational guards (probe-churn + enrollment)

Codex's trust/enrollment and `apply_patch`/argv behavior are pinned **empirically**, not contractually, so two
operator-facing guards backstop version churn and the unverifiable trust ceremony:

- **Validated-version ceiling.** `CODEX_VERSION_VALIDATED` (`core/runtime/codex_preflight.py`) names the newest
  codex-cli the probe harness was run against end-to-end. `CodexPreflight.version_beyond_validated` is `True` when the
  installed binary sorts strictly above it; `forge runtime preflight codex` then prints a non-blocking re-probe notice
  (a bump never fails readiness — the facts are just unverified for that version). Mirrors the 4g
  `CLAUDE_VERSION_VALIDATED` guard; bump after a green probe round. The
  [2026-10-09 B2 round](board/doing/codex_0160_validation/evidence/README.md) covers 0.161.0: current dispatcher
  enrollment, product hooks, managed/native resume, interactive paths, and native usage. It does not validate live quota
  exhaustion or proxy transport. The QA release pin and its shared provenance are independent of this ceiling.
- **Empirical enrollment check.** `forge runtime preflight codex --verify-enrollment` (`core/ops/codex_enrollment.py`)
  confirms user-scope hooks are trust-enrolled by *effect*: it runs one trivial managed `codex exec` turn in a throwaway
  git repo and reports enrolled iff `codex-session-start` fired (the observation receipt appeared). Short-circuits with
  no turn when the answer is already knowable (not ready / not registered); a turn that fails to complete reports
  `UNVERIFIED`, not "not enrolled". Tests **user** scope only (path-stable, one-ceremony-covers-all); project-scope
  hooks need a turn inside the project.

Artifact-authority launch first requires exactly one user-scope, no-matcher `codex-policy-check` row with the installed
dispatcher command bytes and timeout. That proves the policy handler is statically present; it does not prove Codex
trust. Launch therefore also invokes the empirical `codex-session-start` verifier for **every advisory Codex launch
attempt**, including each `session resume --task` turn. A 20-turn headless advisory workflow therefore pays roughly 20
additional probe turns of latency and quota. The existing readiness cache observes binary and auth/credential mtimes
plus a TTL; it is not proven to observe trust revocation. Any future enrollment cache requires separate probe evidence
locating the trust state and demonstrating sound invalidation.

### I.4 Artifact-authority runtime seam

Authority preflight and hooks share canonical, secret-free digests:

- the effective-config digest hashes coverage version, runtime, role, and nullable tier as sorted compact JSON;
- Claude's hook digest covers the `PreToolUse` event, omitted matcher, exact dispatcher command, 60-second timeout, and
  current generated-dispatcher source digest;
- Codex's hook digest covers the code-owned built-in registration entries while preserving their existing command bytes.

The launcher mints one root run identity before preflight. A validated advisory attempt sets the compact schema-v1
`FORGE_AUTHORITY_MARKER` only in the child environment; stale inherited copies are explicitly removed from producer,
unmarked, and bare invocations. The marker contains `session`, `runtime`, `run_id`, `effective_config_sha256`, and
`hook_registration_sha256`. It carries no prompt, path, payload, patch, source, or credential, and has no public
configuration surface.

Claude host preflight requires exactly one current executable catch-all `authority-check` registration. The generated
dispatcher parses enough argv to recognize that handler and checks only whether the marker is absent before project
registry lookup, contributor override resolution, imports, or exec. Any present value, including malformed JSON, is
forwarded to Forge so marker/schema/session/digest mismatches deny in the handler. Advisory Claude sidecar remains
`unsupported`: staged settings do not prove that the selected image can execute the handler before spawn. The
sidecar-owned hook inventory omits this host-only catch-all because its bare `forge hook authority-check` form has no
dispatcher fast gate and could never enforce an advisory launch in v1.

Codex uses the same launch identity and marker for headless start/resume and interactive TUI start/reattach. Preflight
requires both the exact installed policy row and a positive empirical SessionStart enrollment probe. Its combined
handler evaluates authority before `apply_patch` filtering or adapter normalization and emits the probe-pinned strict
deny JSON. Handler-internal resolution/classification failures deny when the runtime can receive a response.
Non-delivery, command timeout, dispatcher failure, and runtime rejection of malformed output remain outside this handler
boundary and are disclosed as fail-open seams.

## J. Session Event Journal Reference

`forge.session.events` is the runtime-neutral owner of the schema-v1 event envelope and storage mechanics. Artifact
authority and launch routing are separate shipped consumers with separate domain validators and journal paths.

```json
{
  "schema_version": 1,
  "event_id": "sevt_<32-lowercase-hex>",
  "timestamp": "<RFC-3339 UTC>",
  "session": "<validated session name>",
  "runtime": "claude_code|codex",
  "event_type": "<domain token>",
  "run_id": "<Forge run id|null>",
  "origin_surface": "external_cli|session_derivation|launcher|claude_authority_hook|codex_policy_hook",
  "operation": "start|resume|fork|incognito|set|clear|tool_request|runtime_event|null",
  "outcome": "success|denied|refused|cancelled|error",
  "reason_code": "<lowercase token|null>",
  "payload": {}
}
```

Unknown or missing envelope fields, invalid ids/timestamps/enums/nullability, non-JSON values, duplicate event ids,
blank/truncated/non-object lines, non-UTF-8 bytes, and newer schema versions are errors. A domain supplies exact payload
and full-event validators; authority uses the latter to enforce each event type's run-id, origin, operation, outcome,
reason-code nullability, and runtime-hook correspondence. The shared layer never serializes arbitrary objects with
`default=str`.

The authority payload has exactly `role`, `tier`, `effective_config_sha256`, `hook_registration_sha256`, and
`covered_tool`. It stores no prompt, raw tool payload, candidate patch, source bytes, command text, or candidate path.
The authority event set is `authority_configured`, `authority_cleared`, `authority_inherited`, `launch_preflight`,
`launch_aborted`, `run_started`, `run_ended`, `request_denied`, and `mutation_refused`.

The routing event set is `launch_routing_committed` and `launch_aborted`. Its exact secret-free payload freezes route
identity, selected/default model facts, effective tier and alternative maps, billing mode, route-scope tags, and
provider-declaration snapshots. An abort must repeat the same run, operation, and payload as its preceding commit.
`confirmed.route_commit` stores only the effective event and run ids; it is a latest-state pointer, not another copy of
the route.

The contained path is `.forge/artifacts/<session>/<domain>/events.jsonl`. Path resolution requires an existing Forge
root, validates the session and domain before creating directories, rejects existing symlink components, and uses one
per-journal lock. Required append opens without following symlinks, accepts only a singly linked regular file, enforces
private modes, writes one compact UTF-8 record plus newline, and fsyncs both file and containing directory. Failures are
typed and propagated. The ordered reader returns an empty sequence for an absent or zero-record file and skips no
malformed record; a domain that distinguishes those states also checks the contained journal path's existence.

Domain readers preserve distinct absence meanings. Routing history is `null` only when both projection and journal are
absent, `supported` when the projection and effective commit agree (or a complete aborted-only journal needs no
projection), and `unproven` for empty or inconsistent evidence. Malformed/unreadable history is an error. Local
append-only storage is not a tamper-proof audit log.

### Semantic review within executor hooks

Claude Write/Edit and Codex's supported `apply_patch` adapter share plan/conversation presence and lifecycle predicates.
A single hook-entry deadline covers every normalized file and checker/frontier stage. Read-only reviewer containment,
sidecar admission, frozen reviewer identity, and unavailable-review handling follow
[workflow supervision](design_workflows.md#12-semantic-policy-the-supervisor). Durable attempt records live in global
telemetry, independently of a hook's ability to write its terminal policy result. Codex shell writes and deletion-only
patches outside the adapter remain outside semantic supervision.
