# Forge Session Context Design

Canonical plan, transcript, resume, and transfer-context contracts. See [session design](design_sessions.md) for durable
state and the domain map.

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
[design_session_execution.md §I.1](design_session_execution.md#i1-recorded-codex-facts-confirmedcodex).

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
([design_session_context.md §H](design_session_context.md#h-transfer-context-schema)) and is the substrate for
cross-worktree, cross-project, and cross-runtime moves.

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
then catalog order without side effects. The first candidate whose prerequisites pass admission is the winner;
compatibility, startup, identity, and health failures from that winner never fall through. After Claude proxy-pin
validation, the launch environment applies the neutral route's selected tier as `ANTHROPIC_MODEL`. Non-Claude routes
also project the canonical requested model through that tier's `ANTHROPIC_DEFAULT_*_MODEL` and carry the selected tier
in the Forge-owned `X-Forge-Model-Tier` custom header. The proxy resolves an explicit tier in the request model first,
then that validated header, then its configured default; it consumes the header locally. Planner and proxy dispatch
resolve `model_alternatives` through one rule: an exact key wins, catalog aliases share their canonical route identity,
and uncatalogued keys match exactly only. The launch journal materializes the resolved alternative under the exact
persisted request spelling so historical validation never depends on a future catalog. Within one tier, distinct keys
that resolve to the same catalog identity cannot select different backend models. The selected context window preflights
resume/fork before the proxy, legacy direct pin, and `model_route` transition is written atomically. Bare resume and an
inherited-route fork reuse that route or fail. Their refusal output preserves the intended lifecycle action when it
offers an explicit replacement route, including explicit fresh-resume or fork options.

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
stable across resumes. A matching `[1m]` execution projection is inherited with that intent. An explicit model must
remain compatible with that persisted proxy; `--proxy <name>` or `--no-proxy` is required to cross the route boundary.

**Authority launch transaction:** Every managed launch path mints one root `RunIdentity` before invocation and rereads
authority intent under the session authority lock. Launch arguments are revalidated against that locked state before
runtime-seam checks, journal events, or active registration; a late advisory designation therefore refuses passthrough.
An unmarked launch retains that lock for the complete legacy child lifetime, preventing a concurrent control-plane
command from assigning authority after the launcher committed to an unmarked environment; its existing active
registration remains best-effort. A marked launch instead proves the runtime seam, requires active registration, and
durably appends `launch_preflight` then `run_started` under the lock before releasing it and invoking the child.
Set/clear use the same lock and turn live-launch contention into a short, actionable refusal. The invoker does not
remint the identity. Outside an explicitly compensated pre-invocation abort, Forge attempts same-run `run_ended` and
clears marked active state. A failed preflight produces `launch_aborted` and no started claim. A spawn exception after
the commit is `child_never_spawned`; a spawned child returning nonzero is `child_exited_nonzero`, so `run_started` means
“Forge committed to invoke,” not “the child was observed alive.”

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
