# Forge Session Design

Canonical session-state, launch, transfer, hook, queue, Codex, and event-journal contracts.

---

## Session contracts

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
session. Relocated transcripts use the same ownership scan; a cached owner remains conservatively protected, while a
cached absence is rescanned at the unlink boundary after another process may have published a sibling during ordinary
cleanup. The final negative scan and unlink share the global index-publication lock, so a sibling manifest cannot be
published between the ownership decision and removal. Adoption resolves the `.forge/artifacts` root before enforcing
destination containment, so relocating that root with a symlink is supported; a descendant destination that escapes the
resolved root or aliases the native transcript is refused, and rollback only unlinks an artifact created by the current
copy attempt. Stop and StopFailure also reconcile `claude_session_id` and `transcript_path` from their hook payloads to
correct fork-session launches where SessionStart sees an inherited parent UUID. Because the start path pre-seeds, a
non-null `claude_session_id` does **not** by itself mean the session ran (a `--no-launch` or not-yet-launched start
session already carries a pre-seeded UUID); "used"/resumable requires hook confirmation or transcript-backed evidence
(see Default resume behavior).

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

Session manifests currently write schema v2. `forge.session.models::SCHEMA_VERSION` owns the writer version and
`forge.session.store::_SUPPORTED_SCHEMA_VERSIONS` admits v1 and v2 on read; unknown versions remain errors. After a
strict v1 validation, the reader projects the manifest to v2 in memory by adding only `intent.launch.model_route=null`
when `intent.launch` exists. A read never rewrites the file. The next ordinary write emits a complete v2 manifest.

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
  model_route: null
```

This keeps `forge session resume <name>` honest for sidecar sessions without overloading `confirmed` with user-owned
preferences.

In schema v2, a present `intent.launch` object must include `model_route`, either `null` or the complete neutral route
selection:

```yaml
model_route:
  requested_model: gpt-5.6-sol # canonical model-catalog id when written
  selected_tier: opus # haiku | sonnet | opus
  kind: proxy # direct | proxy
  source_id: openrouter # proven backend source; null for direct or unproven proxy routes
```

`requested_model` records user intent independently of transport. Forge writes the then-canonical model id. `source_id`
records an automatic, explicit, or preserved proxy source only when Forge can prove its then-canonical identity; direct
routes require `null`. Catalog membership is a writer- and relaunch-time invariant, not a manifest-decode dependency. A
later model- or source-catalog removal therefore leaves the durable session record readable while relaunch reports the
unavailable route contextually. `intent.launch.direct_model` remains the Claude Code execution pin, including an
optional `[1m]` transport modifier, and `intent.proxy` remains the concrete proxy template/base URL.
`forge.core.ops.session_model_routing` owns the pure transition that replaces `intent.proxy`,
`intent.launch.direct_model`, and `intent.launch.model_route` together for a resolved route. Clearing neutral route
intent alone does not change the legacy proxy or Claude-pin fields. Legacy creation, adoption, `default_direct_model`,
and Codex paths do not synthesize `model_route`.

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
`authority show` reads the manifest, authority journal, and runtime active registry without repairing any of them. A
malformed active registry is therefore an actionable read error; `session list` remains the explicit runtime-state
self-healing path.

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
- Resolved `intent.launch.model_route` is lifecycle-owned: set rejects its subtree and enclosing `launch` objects; reset
  accepts stale paths.
- `intent.authority` is not overrideable: set and keyed reset reject the parent, wildcard, and concrete leaves.
  `reset --all` clears only overrides and cannot alter authority intent.

> **Note:** There is no "merging"—overrides simply win. The only subtlety is nested dicts: you can override
> `memory.tags` without losing `memory.auto_recall`. This applies to session-owned fields only (`tdd_mode`, `memory.*`,
> etc.). Proxy-owned fields come directly from the proxy.

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

- The authority domain writes `<forge_root>/.forge/artifacts/{session_name}/authority/events.jsonl`; managed route
  provenance writes `<forge_root>/.forge/artifacts/{session_name}/routing/events.jsonl`. The shared runtime-neutral
  `forge.session.events` module owns the schema-v1 envelope, `sevt_` ids, UTC timestamps, frozen
  origin/operation/outcome enums, strict JSON validation, and domain payload hook. Authority and routing keep separate
  payload and continuity validators and never read each other's journal to authorize behavior.
- Path construction validates the session name, uses an explicit domain allowlist, resolves beneath the owning
  `forge_root`, and rejects absolute/traversal/symlink escape shapes before creation. Each journal has its own lock.
  Appends write one compact UTF-8 JSON object plus newline, reject non-JSON values, flush/fsync the file and directory,
  and propagate lock/open/write/fsync failure to required callers. The reader rejects unreadable, truncated, unknown,
  malformed, duplicate-id, and newer-schema records without skipping a line.
- Authority configuration, inheritance, preflight, and lifecycle appends are required transactions. Denial logging is
  best effort only after the runtime deny is already fixed; a journal failure cannot weaken it.
- Absence is not proof. Authority and routing readers distinguish absent history, unsupported projection, and malformed
  history according to their domain contracts; malformed history is an error. The append-only convention is local
  evidence, not tamper resistance against humans or external processes.
- Session delete/clean never selectively removes either journal directory, regardless of transcript flags. Both follow
  their containing Forge root: root-level worktree sessions retain them in the parent root, while deleting an owned
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
`CodexHeadlessInvoker().run`, all under **one run tree** joining on `root_run_id`
([telemetry design §3.14](design_telemetry.md#314-cost-tracking-and-spend-caps)) — a UI-agnostic command-core op.

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
[design_sessions.md §I.1](design_sessions.md#i1-recorded-codex-facts-confirmedcodex).

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
([design_sessions.md §H](design_sessions.md#h-transfer-context-schema)) and is the substrate for cross-worktree,
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

**Interactive model-route selection:** Claude-runtime `start`, `resume`, `fork`, and `incognito` accept catalog models
through `--model`; `--model-tier` disambiguates proxy tiers. Unlike Claude's in-process `/model`, this is durable
prelaunch intent. The shared planner applies explicit constraints, a compatible stored route, new-Claude direct routing,
then catalog order without side effects; only its winner may start, and failure never falls through. The selected
context window preflights resume/fork before the proxy, legacy direct pin, and `model_route` transition is written
atomically. Bare resume reuses that route or fails.

A non-Claude selection may start a paid proxy. `--no-launch` persists it without a route event or child;
`--subprocess-proxy` is incompatible. Codex, adoption, `default_direct_model`, sidecar/host-proxy modes, and bare
commands never initiate fresh selection.

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

**Proxy inheritance:** The child inherits the parent's proxy and neutral model-route intent by default, keeping routing
stable across resumes; `--proxy <name>`, `--no-proxy`, or an explicit model that the inherited route cannot serve
authorizes a complete replacement.

**Authority launch transaction:** Every managed launch path mints one root `RunIdentity` before invocation and rereads
authority intent under the session authority lock. An unmarked launch retains that lock for the complete legacy child
lifetime, preventing a concurrent control-plane command from assigning authority after the launcher committed to an
unmarked environment; its existing active registration remains best-effort. A marked launch instead proves the runtime
seam, requires active registration, and durably appends `launch_preflight` then `run_started` under the lock before
releasing it and invoking the child. Set/clear use the same lock and turn live-launch contention into a short,
actionable refusal. The invoker does not remint the identity. Outside an explicitly compensated pre-invocation abort,
Forge attempts same-run `run_ended` and clears marked active state. A failed preflight produces `launch_aborted` and no
started claim. A spawn exception after the commit is `child_never_spawned`; a spawned child returning nonzero is
`child_exited_nonzero`, so `run_started` means “Forge committed to invoke,” not “the child was observed alive.”

Advisory Claude requires the exact catch-all registration and current executable dispatcher. Advisory Codex requires
exactly one user-scope no-matcher `codex-policy-check` row with the installed command bytes and timeout, then performs
the empirical `codex-session-start` enrollment check for every attempt. Advisory sidecar is unsupported until its
selected image has an equivalent pre-spawn proof; Forge therefore does not stage the host-only authority catch-all in
sidecar settings. Producer launches record config/lifecycle posture without requiring an enforcement seam; unmarked
launches keep the legacy path and create no authority events. Only a validated advisory attempt receives the internal
marker, containing session/runtime, the one root run id, and config/hook digests.

**Routing launch transaction:** After routing, context/runtime preparation, and child argv/environment are fixed, every
managed Claude host/sidecar and Codex headless/interactive attempt appends `launch_routing_committed`, then atomically
projects its `{event_id, run_id}` into `confirmed.route_commit`, before invoking the child. Marked launches do this in
the yielded authority transaction body, after `launch_preflight` and `run_started`; unmarked launches use the same
serialized boundary without authority events. Both journals and the projection reuse the one root `RunIdentity`.

For explicit model selection, one stderr route line and the journal share the immutable payload, including proven
backend identity and `billing_mode=unknown` absent payer evidence. Later payload, projection, or child failure does not
roll back persisted route intent.

Routing construction, validation, or append failure compensates any authority journal already touched. Projection
failure compensates in reverse touch order: the exact immutable route payload is appended as same-run
`launch_aborted:route_projection_failed`, then authority receives its same-run abort. Every compensation is attempted
and secondary failures are aggregated without invoking the child. A landed authority abort supersedes `run_started`,
active-state clear is attempted, and no `run_ended` is appended for that pre-invocation failure. If both the authority
abort and active-state clear fail, diagnostics disclose the remaining temporary ambiguity. Spawn or child failure after
a successful projection retains the effective route, session, transfer snapshot, worktree, and any completed child work;
authority records its normal terminal outcome. Claude routing provenance records only an actually applied model pin as
`selected_model`: an ignored request remains visible as `requested_model`, and Anthropic passthrough records the
canonical unchanged client model rather than substituting a tier default. Proxy route payloads carry `wire_shape` as the
durable discriminator for that validation; legacy events without the field retain translated-mapping validation.

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
> [design_sessions.md §B](design_sessions.md#b-work-queue-internals).

## B. Work Queue Internals

Extracted from [design.md §3.13](design_sessions.md#313-async-work-queue). Design goals and rationale remain in
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

## H. Transfer Context Schema

The transfer contract builds on [session design §3.9](#39-session-resume-context-management). The transfer document is a
stable, frontmatter-backed Markdown contract produced by `assemble_transfer_context` (`src/forge/session/transfer.py`).

### H.1 Frontmatter (child-agnostic)

Every strategy prepends one YAML block. It carries **no `child` field** — child identity is path-derived, so
`generated.md` and the `children/<child>.md` copy stay byte-identical (the `ensure_child` copy and the auto-name retry
byte-compare in `manager.py` both depend on this).

```yaml
---
forge_transfer:
  schema_version: 1
  parent: <parent-session-name>
  strategy: ai-curated | structured | full | minimal | rewind
  schema: full | compatibility-fallback | rewind-code-delta
  depth: <int>                              # lineage depth (regenerate restores this)
  generated_at: <ISO8601>
  lineage: [<parent>, <grandparent>, ...]
  transcript_artifact: <forge-root-rel path | null>
  token_estimate: <int | null>
  target_runtime: claude                    # claude (default) | codex — shipped (5d relabel, 5e bridge)
---
```

Reads are **best-effort** (`parse_transfer_frontmatter`): the doc is an LLM-consumed artifact with a user-editable
overlay (a system boundary), so missing/malformed frontmatter warns and still returns the body — it never hard-fails.

### H.2 Sections

`ai-curated` emits eight sections. Code owns the skeleton; the model returns structured JSON parsed with
`extract_json_from_response`. Decisions cite a transcript turn (`[turn N]`) or file; `_validate_decision_citations`
drops fabricated citations with a warning so `schema: full` does not overstate evidence quality.
`forge.session.context_rendering` owns trimmed text, section framing, and plain/cited bullet mechanics; transfer and
rewind supply their section/empty/citation labels and retain their envelopes, budgets, emitted-turn sets, and citation
validation. Sections 1–7 live in the AI snapshot; section 8 is the notes overlay (so the snapshot has 7 headers and the
composed launch view has 8):

1. `## Lineage`
2. `## Goal / Current Task`
3. `## Decisions` (cited)
4. `## Current State`
5. `## Relevant Files` (`file:line`)
6. `## Open Questions`
7. `## Runtime Hints`
8. `## User Notes` (overlay)

`minimal | structured | full` keep their existing bodies and set `schema: compatibility-fallback`. `rewind` is written
only for resume/fork launches, not `transfer regenerate`: a successful rewind context sets `schema: rewind-code-delta`
and contains the dropped-window code delta. If code-delta curation fails, Forge falls back to plain native resume /
native-relocate and does not write a rewind context snapshot.

### H.3 File layout and overlay

```
<forge_root>/.forge/prev_sessions/<parent>/generated.md               # parent AI cache (regenerate rewrites)
<forge_root>/.forge/prev_sessions/<parent>/children/<child>.md        # per-child AI snapshot (frozen; never edited)
<forge_root>/.forge/prev_sessions/<parent>/children/<child>.notes.md  # per-child user overlay (the editable surface)
```

The launcher appends the snapshot plus the notes overlay (when it has user content) to one `--append-system-prompt-file`
via `_combine_prompt_files`. `forge session transfer regenerate` rewrites only `generated.md`; snapshots and notes are
never overwritten. GC pairs a notes file's liveness to its snapshot — it is never orphaned independently
(`_detect_orphan_transfer_files`).

### H.4 Relationship to `ctx` (prior art)

The transfer schema is **Forge-owned and canonical**. [`ctx`](https://github.com/dchu917/ctx) is prior art only: its
workstreams, exact transcript binding, branching, indexed retrieval, local storage, and curation informed this
substrate. Forge will not depend on it; this load-bearing session/policy/usage contract lives in-tree. No `ctx` interop
is planned. A future optional import/export bridge could use the existing schema unchanged, but is not committed work.

---

## I. Codex Runtime Reference

This reference builds on [session design §3.9](#39-session-resume-context-management) and
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
  `CLAUDE_VERSION_VALIDATED` guard; bump after a green probe round.
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
