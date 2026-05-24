# Memory Enhancement

Status: done; historical card for the shipped memory enhancement

## Summary

Forge memory should treat the **memory doc** as the unit of ownership.

Today, designated memory docs are configured per session under `intent.memory`. That works as plumbing, but it makes
project-level memory behavior hard to discover, audit, inherit, and review. The next iteration should make each memory
doc carry its own contract in frontmatter, then let sessions resolve that contract into runtime execution state.

This card is intentionally write-side first. The goal is to make memory updates, shadows, inheritance, and visibility
usable enough to dogfood during runtime abstraction before Forge starts automatically feeding memory back into agent
context.

## Design Thesis

Memory ownership should live with the document, not in a separate registry.

```text
Memory doc frontmatter = authoritative contract
Session manifest        = resolved participation / runtime state
Shadow docs             = local proposal buffers
Search index            = derived cache
Handoff reports         = generated review artifacts
```

This avoids a split-brain model where a doc says one thing, a project config says another, and a session manifest says a
third. A session may opt in, opt out, inherit, or narrow participation, but it should not redefine what a memory doc is
for.

## Memory Doc Passport

Each memory doc may include a `forge_memory` frontmatter block. This is the doc's passport: it describes intent, update
rules, and update privileges.

Users should not need to understand or hand-edit this syntax for normal use. The passport is the visible, versionable
storage format; `forge memory` is the user-facing interface that creates, updates, explains, and validates it.

```yaml
---
forge_memory:
  version: 1
  intent: "Compact completed-work record for Forge implementation sessions."
  captures:
    - completed work
    - verification
    - deferred follow-ups
  excludes:
    - pending task plans
    - raw session summaries
    - detailed command output
  update:
    instruction: "Add compact newest-first entries with Goal, Key changes, and Verification."
    strategy: changelog
    mode: direct
    writers: all-sessions
    inherit_on_fork: true
    compact_when: "approaching documentation size limits"
---
```

For human-approved durable memory:

```yaml
---
forge_memory:
  version: 1
  intent: "Human-approved durable implementation memory for future Forge sessions."
  captures:
    - stable decisions
    - non-obvious invariants
    - recurring bug causes
    - operational constraints
  excludes:
    - raw session summaries
    - pending tasks
    - unverified hunches
  update:
    instruction: "Agents propose; humans promote selectively after review."
    strategy: suggested
    mode: shadow-only
    shadow_path: .forge/memory/suggested_impl_notes.md
    writers: all-sessions
    inherit_on_fork: true
    approval: human-promoted
---
```

`update.instruction` can be natural language, a supported strategy, or both. The strategy gives Forge a known prompt
shape; the natural-language instruction gives the agent the doc-specific judgment rules.

Manual edits remain allowed because the passport lives in a Markdown doc, but CLI-assisted creation should be the happy
path:

```bash
forge memory track docs/board/change_log.md \
  --intent "Compact completed-work record for implementation sessions" \
  --as changelog \
  --session planner
```

## Ownership Model

The passport describes the document's identity and update contract:

- **Intent**: what the doc captures, what it excludes, and who the future reader is.
- **Update instructions**: how to update it, how verbose to be, when to compact, and whether approval is required.
- **Update privilege**: who may update it (`all-sessions` or a named session).
- **Inheritance**: whether derived sessions inherit the privilege by default.

The passport does not store session runtime state. A session manifest may snapshot that a session is participating in a
doc's update contract, but the authoritative meaning of the doc stays with the doc.

**Resolution and timing.** The session manifest records which docs this session tracks and whether `auto_update` is
active. That participation record is authoritative: the handoff agent uses it to find the tracked-doc list at Stop time.
For each tracked doc, the agent then re-reads the passport for intent, instructions, strategy, writers, and inheritance.
Passport fields are never trusted from a manifest cache; passport edits therefore take effect on the next Stop without
re-track. `forge memory list` / `status` re-read passports for display.

**Flag-vs-passport conflicts.** CLI flags win over passport values for that invocation, and Forge warns when an override
happens. The same rule applies to `--inherit-memory` versus `forge_memory.update.inherit_on_fork`.

**Writer roles deferred.** v1 supports `all-sessions` and `<session-name>` only, where `<session-name>` matches the
exact Forge session name with no lineage interpretation (a fork of `planner` named `planner-v2` is not a `planner`
writer). Cross-session inheritance is handled explicitly by `inherit_on_fork` / `--inherit-memory`, not by reading
meaning into session names. Role-based writers and a `none` value are deferred until session roles exist as a
first-class concept. If lineage-based writers are added later, the syntax must be explicit (for example
`lineage:planner`), not implicit.

**Instruction trust = doc edit trust.** `update.instruction` flows into the handoff agent's prompt, so passport edit
rights translate to update-behavior control. Project-tracked docs (`docs/...`) inherit git PR review as the trust
boundary; gitignored shadow docs (`.forge/memory/...`) inherit local-edit trust.

**Passport required at rest.** Every tracked memory doc must have a `forge_memory` passport. Users do not hand-author
the YAML for normal use; `forge memory track` synthesizes a starter passport from CLI flags (`--as`, `--intent`,
optional `--propose`) when the doc has none. If those flags are insufficient, `track` fails with a clear command that
names the missing fields. A tracked doc without a passport is not a valid state.

## First PR Scope

The first implementation slice should improve the write-side UX without depending on memory for automated recall.

### Top-Level `forge memory`

Add a top-level memory command group as the canonical UX. The existing `forge session memory ...` group is removed in
the same release: only `forge memory ...` is public, with no compatibility alias. Internal helpers from the old surface
may be reused behind the new commands, but docs, tests, and user-facing guidance target `forge memory` exclusively. Old
invocations should fail with a helpful message that points to the equivalent `forge memory` command; they must not
execute old behavior.

```bash
forge memory enable --session planner
forge memory track docs/board/change_log.md --as changelog --session planner
forge memory track docs/board/impl_notes.md --propose --session planner
forge memory list --session planner
forge memory status --scope repo
forge memory status --doc docs/board/impl_notes.md
```

`forge memory` should default to project/repo context for visibility. Commands that mutate one session should require
`--session <name>` unless there is an active session.

### One-Command Activation

The biggest current friction is setup: users must separately enable `memory.auto_update`, choose a mode, and track docs.
The happy path should make memory active in one command.

```bash
forge memory enable --session planner
```

`enable` should:

- set `memory.auto_update.enabled=true`;
- set `memory.auto_update.mode=augment` by default, with `--review-only` for first-run dry runs;
- show the currently tracked and shadowed docs after enabling;
- avoid duplicating existing configuration if re-run.

Goal-oriented doc commands should also activate memory when needed. If a user runs `track` and the session has no
`auto_update` config, Forge should enable it with a clear message:

```text
Enabled memory auto-update for session planner (mode=augment).
Tracking docs/board/change_log.md as changelog.
```

### Track, Untrack, And List

Use `track` / `untrack` as the primary verbs. This matches the user's mental model: Forge is tracking docs for the
handoff agent, much like Git tracks files for version control.

```bash
forge memory track docs/board/change_log.md --as changelog --session planner
forge memory track docs/board/impl_notes.md --propose --session planner
forge memory untrack docs/board/change_log.md --session planner
forge memory list --session planner
```

`track` means "configure the handoff agent to update or propose updates for this doc at session stop." By default it
tracks the doc for direct updates. `--propose` switches to shadow mode: Forge derives a local shadow path, writes
suggestions there, and leaves the official doc human-approved.

Default shadow path:

```text
docs/board/impl_notes.md -> .forge/memory/suggested_impl_notes.md
```

Users may override the derived shadow path with `--shadow <path>`, but they should not need to think about shadow paths
for the common case.

`track --propose` implies the `suggested` strategy unless the passport provides a more specific compatible rule. Direct
tracking uses `--as <strategy>` or the passport's update strategy.

These commands have the following behavior:

- make `track` idempotent: add the doc when missing, update the existing entry when present, and never create duplicate
  entries for the same official target or shadow path;
- let `track` update strategy, direct-vs-shadow mode, and shadow path when a doc is already tracked;
- make `untrack` idempotent: succeed with a clear "not tracked" message when the doc is already absent;
- validate path safety and strategy/shadow consistency;
- read the doc's passport frontmatter; the passport must be present after `track` succeeds (per "Passport required at
  rest");
- synthesize a starter passport from `--as` / `--intent` (and optional `--propose`) when the doc has no passport, or
  fail with a suggested command when those flags are insufficient;
- when CLI flags disagree with the passport, apply the flag and warn (flag-wins rule, per Ownership Model);
- enable `memory.auto_update` if this is the first configured memory doc for the session;
- persist resolved participation to the session's `intent.memory` or override path.

The CLI should explain passport fields in product terms (`intent`, `captures`, `update rules`, `writers`) and explain
commands in terms of outcomes (`tracks changelog directly`, `tracks impl_notes through a shadow proposal`) rather than
requiring users to know the YAML shape or internal memory-doc terminology. A future `forge memory passport show|set`
command can expose advanced editing without making frontmatter syntax part of the basic workflow.

### Status Visibility

Add project/repo scoped visibility for direct updates and shadow proposals:

```bash
forge memory status --scope project
forge memory status --scope repo
forge memory status --scope all
forge memory status --doc docs/board/impl_notes.md
```

Scope nomenclature mirrors `docs/design.md` §3's project identity hierarchy: `project` = current `forge_root` (the
`.forge/` install root, where session state lives), `repo` = logical `project_root` (the shared git identity across
worktrees), `all` = global.

The status table should distinguish:

- direct writers of a doc;
- shadow writers proposing changes for a doc;
- handoff mode (`augment` or `review-only`);
- configured strategy;
- session/worktree when known;
- missing shadow files or missing official `shadows` targets.

### Shadow Doc Auto-Create

For Forge-owned local scratch paths, `track --propose` should create missing shadow docs automatically:

```bash
forge memory track docs/board/impl_notes.md --propose --session planner
```

This should derive `.forge/memory/suggested_impl_notes.md`, create `.forge/memory/`, and create the empty shadow doc
when the path is under `.forge/memory/`. Keep the current no-file-creation rule for tracked official docs such as
`docs/board/change_log.md` and `docs/board/impl_notes.md`.

### Shadow Accumulation And Review Visibility

Users need a first-class way to inspect what has accumulated in shadow docs:

```bash
forge memory shadows list
forge memory shadows show --for docs/board/impl_notes.md
forge memory shadows show --scope repo
```

The view should group shadow content by official target and source worktree/session where possible. This answers a
different question than `status`: `status` shows who is configured to write or shadow; `shadows` shows what pending
suggestions actually exist.

### AI-Curated Shadow Review

Shadow docs are a write-heavy, read-light medium. The handoff agent should be allowed to take notes liberally when it
finds potentially durable information, because humans should not have to read the raw accumulation directly. Curation is
the read path that turns noisy proposals into a compact promotion surface.

Raw shadow files are good append targets but poor human review surfaces. Add a read-only curated review path:

```bash
forge memory shadows review --for docs/board/impl_notes.md --curate
forge memory shadows review --scope repo --curate
```

The curator should read the official doc plus matching shadow docs, remove duplicates and already-reflected suggestions,
group related items, and emit a compact report with source citations. It may produce a proposed patch or promotion
checklist, but it must not update the official durable-memory doc unless the user explicitly applies or approves it.

The handoff-agent prompt can lean into this asymmetry: write potentially useful suggestions to shadows, keep each note
sourceable, and rely on the curator to compact or reject later. Direct-write docs should stay more conservative.

**Cost routing.** `--curate` is an LLM call. It routes through `forge.core.llm`, respects the active session's proxy
configuration and the proxy spend caps surfaced by `forge proxy costs`, and reports per-invocation usage like other
workflow verbs. `--scope repo` or `--scope all` fans out across worktrees; the caller should expect proportional token
cost.

**Report location.** Curated reports persist alongside other per-session artifacts at
`<forge_root>/.forge/artifacts/<session>/memory/review-<timestamp>.md`, mirroring the existing
`<forge_root>/.forge/artifacts/<session>/handoff/review-<timestamp>.md` path used by `forge session handoff show`.
Surface the latest via `forge memory shadows review --show-latest` (parallels `forge session handoff show --latest`).

**Session ownership for multi-scope runs.** For `--scope repo`, the curate command requires an active session (resolved
from `FORGE_SESSION` env or `--session <name>`) as the artifact owner — the session is the runner of the curate, not its
subject. `--scope all` is read-only friendly for `status`/`shadows show` but is deferred for `--curate` until cross-repo
artifact ownership is designed.

### Memory Inheritance

Derived sessions need explicit memory inheritance controls:

```bash
forge session fork planner --name executor --worktree --inherit-memory all
forge session fork planner --name reviewer --into ../multi-forge-executor --inherit-memory shadowed
forge session fork planner --name scratch --worktree --inherit-memory none
```

Candidate modes:

- `all`: inherit auto-update settings and all tracked memory docs;
- `none`: inherit no memory participation;
- `shadowed`: inherit shadow/proposal docs only.

The flag-vs-passport rule applies: `--inherit-memory` overrides any `forge_memory.update.inherit_on_fork` value in
tracked passports, with a warning when it does.

Default to `all` so memory feels sticky across forks the same way other session config inherits; revisit if dogfooding
shows it is too aggressive. Do not add finer-grained modes until dogfooding proves they are needed; `auto-update` and
`project-docs` are deferred candidates, not first-slice UX.

**Shadow auto-create on inheritance.** When `--inherit-memory shadowed` (or any inheritance mode that brings shadow
participation into the child) materializes a fork into a different worktree, Forge auto-creates the target's local
shadow files — but only for paths under `.forge/memory/` (Forge-owned scratch). It reports what it created. For shadow
paths outside `.forge/memory/`, Forge does not auto-create; it reports the missing paths and lets the user resolve them.
This matches the existing "Shadow Doc Auto-Create" rule and the broader principle that handoff never creates official
tracked docs.

## Deferred Work

### Project-Level Defaults

The doc passport may eventually let Forge discover project memory docs automatically, or a future
`forge memory defaults ...` surface may materialize defaults for new sessions. Defer this until the write-side flow has
been dogfooded and the storage boundary is clearer.

Key unresolved question: should new sessions snapshot defaults at creation, resolve them live at Stop time, or snapshot
with an explicit refresh command such as `forge memory apply-defaults --session <name>`?

### Memory Search

Memory search should be built by abstracting the current transcript-search machinery around source adapters:

```text
SearchSource adapter -> list[SearchableDocument]
SearchableDocument    -> id, content, metadata, freshness/version
Shared search core    -> tokenize, index, rank, snippet, store maintenance
```

Then transcripts, tracked memory docs, local shadow docs, and handoff review reports can share the same ranking and
indexing engine.

Possible UX:

```bash
forge memory search -q "runtime handoff"
forge search -q "runtime handoff" --source transcripts,memory
```

### Read/Recall Side

Memory docs are also context sources for agents. Today this is manual through commands such as
`.claude/commands/gather-context.md` and the `gather-context` skill. Future work could generate memory packs or
system-prompt snapshots from selected docs.

Do not include this in the first PR. Prove that Forge can accumulate and curate memory cleanly before automated recall
depends on it.

Potential later shape:

```bash
forge memory pack build --session planner
forge memory recall --session planner --mode skill-read
```

## Migration

Pre-OSS designated-memory state under `intent.memory.designated_docs[]` is not migrated. v1 of the passport model is a
clean break: docs become tracked when `forge memory track` is run against them, and the existing JSON configuration is
ignored. There is no compat shim or deprecation period.

Forge should still detect a non-empty legacy `intent.memory.designated_docs[]` and surface a one-time notice instead of
silently reporting "nothing tracked." The notice should explain that legacy designated docs are ignored by the passport
model and point to `forge memory track ...` / `forge memory enable ...` as the replacement setup path.

This matches `README.md`: Multi-Forge is a research preview whose APIs, commands, and file formats may change without
notice between releases, and pre-OSS Forge installs are not supported in-place. It also follows
`docs/developer/coding-standards.md` §5: pre-release schema breaks still need strict validation and clear reset
instructions, but not compatibility wrappers.

## Open Questions

None at this time. New questions should be added here as they emerge during implementation.
