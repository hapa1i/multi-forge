# Forge Memory Design

Canonical designated-memory, passport, writer, activation, and worktree-resolution contracts.

---

## 5. Designated Memory Docs

Cross-session continuity via designated markdown files that sessions keep updated—no knowledge graphs. Automated
project-memory synthesis is deferred through the pending-work queue.

Forge memory has three layers; this section covers **project memory** -- the designated docs the memory writer curates:

| Layer               | What it holds                                           | Location                  |
| ------------------- | ------------------------------------------------------- | ------------------------- |
| **Raw memory**      | Transcripts, plans, artifacts, reports (§3.8)           | `.forge/artifacts/`       |
| **Project memory**  | Passported docs (changelog, impl notes) -- this section | `docs/`, `.forge/memory/` |
| **Transfer memory** | Curated context for fork/resume ([session design §3.9]) | `.forge/prev_sessions/`   |

The Stop hook schedules the **memory writer**, which later curates project memory asynchronously; **transfer**
([session design §3.9]) assembles context for a child session.

The simplest memory system is:

1. Designated markdown files with templates
2. Sessions read them at start (via CLAUDE.md references)
3. Sessions update them before ending
4. Next session gets current state

### 5.1 Memory writer (automated doc maintenance)

The memory writer is requested at session end and runs later to fill gaps automatically:

```
Stop hook → enqueue handoff marker → later CLI drain → detached memory writer → read transcript/docs → update
```

The Stop hook never launches the writer. A later, non-exempt Forge CLI startup opportunistically drains the marker and
spawns `forge memory-writer run` as a detached process. The writer then dispatches its configured consumer lane on the
full session transcript (`claude -p` by default, or `codex exec` when pinned). It operates **retrospectively**,
selecting what mattered with full-session hindsight (higher signal than incremental capture).

```yaml
# In session intent (set via forge session memory enable or --memory on)
memory:
  auto_update:
    enabled: true
    mode: augment              # augment (add missing) | review-only (dry run)
    proxy: litellm-haiku       # cheap model for summarization
    min_turns: 5               # skip for very short sessions
```

**Multi-agent workflow:** In parallel session runs, each session's Stop hook enqueues its own handoff marker. Later
drains launch the corresponding detached writers. `augment` mode stays additive (no overwrites).

### 5.2 Memory doc passports

Each memory doc may include a `forge_memory` YAML frontmatter block -- the doc's **passport**. The passport is the
authoritative contract for that doc's intent, update strategy, and writer privileges. The detached memory writer reads
passports at execution time, not in the Stop hook. Newly tracked Markdown docs also receive a small outer metadata
envelope that is structurally compatible with the pinned OKF v0.1 concept shape:

```yaml
---
type: Memory Document
title: Change Log
description: Compact completed-work record for Forge implementation sessions.
forge_memory:
  version: 1
  intent: "Compact completed-work record for Forge implementation sessions."
  captures: [completed work, verification, deferred follow-ups]
  excludes: [pending task plans, raw session summaries]
  update:
    instruction: "Add compact newest-first entries with Goal, Key changes, and Verification."
    strategy: changelog
    mode: direct
    writers: all-sessions
    compact_when: "approaching documentation size limits"
---
```

`forge_memory` is the only marker of active Forge tracking. The outer `type`, `title`, and `description` keys describe
the document but do not make an OKF-only document Forge memory. Forge owns the `forge_memory` value; outer keys are
producer-owned and preserved at the parsed-value level when Forge rewrites frontmatter. On a new track, Forge adds
missing `type` (`Memory Document`), `title` (the first ATX H1 outside a fenced code block, then a filename fallback),
and `description` (the passport intent with whitespace collapsed). A present non-empty string `type` is preserved,
including an unknown value; a present null, non-string, empty, or whitespace-only `type` blocks envelope generation on a
new track or explicit upgrade.

Forge does not generate or maintain `resource`, `tags`, or `timestamp`. It cannot authoritatively timestamp meaningful
human and agent edits, and strategy-derived tags would become stale after later passport changes. Successful rewrites
preserve existing outer values semantically, but do not promise preservation of YAML comments, anchors, quoting, key
order, scalar spelling, or line endings.

**Ownership split**: passports own doc-level policy (strategy, intent, writers). Session manifests own activation state
(enabled, mode, min_turns). There are no session-scoped doc lists; the detached runner discovers all docs from passports
when it executes. Editing a passport before that scan takes effect without re-running `forge memory track`.

**Writer semantics**: `all-sessions` and exact session-name writers are supported. `lineage:` and `role:` prefixes are
rejected with deferral messages. The detached memory writer checks access when it executes.

**Passport CLI**: `forge memory track --strategy <strategy>` synthesizes a passport and envelope for a Markdown doc
without a passport. Re-tracking an existing passport updates only the requested Forge contract; it never adds or repairs
the outer envelope. `forge memory passport upgrade <path>` is the explicit migration for an existing passport: it adds
only missing envelope fields while preserving the raw `forge_memory` value. `forge memory passport show <path>` displays
passport fields, and `remove` deletes only `forge_memory`, leaving outer metadata in place.

### 5.3 Two operating modes

The memory writer has two distinct modes:

**Mode 1: Direct Update** — agent updates the doc in place per strategy. Used for project docs the agent is allowed to
maintain.

**Mode 2: Shadow/Propose** — the agent is the proposer, the human is the author. `forge memory track --propose` derives
a shadow path under `.forge/memory/` (encoding the immediate parent directory for disambiguation). The agent reads
transcript + official doc, proposes additions to the shadow; the human reviews and merges at their own pace.

Shadow curation: `forge memory shadows review --for <doc> --curate` runs an LLM pass that reads the official doc plus
matching shadows, removes duplicates and already-promoted notes, groups related suggestions, and emits source-cited
output. Curation reports persist at `.forge/artifacts/<session>/memory/curation-{slug}-{hash}-{ts}.md`. Curation never
mutates official docs.

### 5.4 Memory activation on fork and fresh resume

Children inherit the parent's memory activation by default. The `--memory` flag overrides:

```bash
forge session fork parent                    # inherit parent's memory on/off
forge session fork parent --memory on        # force memory on in child
forge session fork parent --memory off       # force memory off in child

forge session resume parent --fresh          # inherit parent's memory on/off
forge session resume parent --fresh --memory off
```

Inheritance copies only `auto_update` (enabled, mode, min_turns, proxy). Other `MemoryIntent` fields do not propagate.
`--memory off` writes an explicit `MemoryWriterConfig(enabled=False)` so the child is deliberately off even if later
defaults change. `--memory on` reuses the parent's non-enabled config (mode, proxy, min_turns) or `MemoryWriterConfig`
defaults.

Memory docs are not inherited. Passports are git-tracked and discovered live by the detached writer in whatever checkout
the child session runs in. This applies equally to same-checkout forks, `--worktree`, and `--into`.

### 5.5 Strategy registry

Per-doc strategies control how each file is updated. Strategies are defined in `MemoryStrategy` enum in
`src/forge/session/passport.py` (single source for CLI, passport, and memory-writer prompts).

**No file creation.** Designated docs must already exist; missing files are skipped. Humans choose which docs to
maintain; the agent maintains them. `forge memory track` enforces this at configuration time; runtime skip handling
remains for stale manifests.

Direct update strategies: `project-state`, `checklist`, `changelog`, `generic`. Shadow mode (`--propose`) works with any
strategy.

The memory writer resolves designated doc paths relative to `forge_root`, so git-tracked docs target the correct branch
in worktrees. Trackedness is controlled by path choice -- the writer doesn't distinguish.

**Relationship to Claude Code auto-memory:** Complementary, not competitive. Auto-memory captures during sessions
(incremental, free-form); the memory writer synthesizes after sessions (retrospective, per-doc strategies). The memory
writer deliberately does not read auto-memory — different targets, different information, occasional duplication is
cheaper than cross-format deduplication.

> Strategy tables, example config, worktree resolution details, and full auto-memory comparison in
> [§6](#6-memory-doc-reference).

### 5.6 Session-scoped activation

Memory activation is session-scoped. Each session decides whether the memory writer runs via
`intent.memory.auto_update.enabled` (or an override). There is no checkout-level config file.

```bash
forge session memory enable                    # resolves $FORGE_SESSION
forge session memory enable --session planner  # named session
forge session memory disable --session planner
forge session start planner --memory on
```

Both gates (Stop-hook enqueue in `src/forge/cli/hooks/commands.py` and the detached runner `forge memory-writer run`)
check `effective.memory.auto_update.enabled` directly. Incognito sessions never enqueue regardless of activation state.

**Deferred discovery.** When activation is on, the detached runner scans hardcoded roots (`docs/` plus `.forge/memory/`)
for `forge_memory` passports the session is authorized to write, materializes shadow files for shadow-only passports,
and passes the result to `run_memory_writer()`. Capped at 50 docs after filtering. The Stop hook only decides whether to
enqueue; the scan runs in the background runner.

**Scan roots** are hardcoded: `DEFAULT_SCAN_ROOTS = ("docs/",)` plus always `.forge/memory/`. Configurable roots are
deferred.

### 5.7 CLI verbs

- **`forge memory track <path>`** authors a **passport** (project-lifetime, git-tracked frontmatter). On a new Markdown
  doc it also fills the missing `type`, `title`, and `description` envelope fields. Re-track never migrates an existing
  passport. `--propose` authors a shadow-only passport on the official doc; an auto-created shadow file receives no
  envelope of its own. A passported doc outside the scan roots is written but warns.
- **`forge memory passport upgrade <path>`** explicitly adds missing envelope fields to an existing valid passport. It
  preserves the raw `forge_memory` mapping and is a byte-identical, exit-0 no-op when the envelope is complete.
- **`forge memory passport remove <path>`** removes only `forge_memory`, preserving outer and unrelated frontmatter.
- **`forge session memory enable`** / **`disable`** sets session activation (`memory.auto_update.enabled`). Resolves
  `$FORGE_SESSION` when `--session` is omitted; errors outside a session without `--session`.
- **`forge memory list`** shows passported docs under scan roots (sessionless scan, no writer filtering).

**Shadow discovery** scans passports under the scan roots for shadow-only docs (unfiltered by writer).

New tracking and explicit upgrade require a logical project-relative path ending exactly in `.md`. Logical and resolved
official basenames are compared case-insensitively against the OKF-reserved `index.md` and `log.md` names before any
passport mutation or shadow write. Proposal shadow paths use the same logical/resolved reserved-name guard, including
custom git-tracked shadows; they do not use the official document's `.md` envelope-generation check. Existing legacy
passports on reserved paths remain readable and removable, and a flag-free `track` remains a byte-identical no-op, but a
re-track that would rewrite the passport is rejected. Legacy non-Markdown passports remain readable, removable, and
re-trackable without envelope generation. Discovery skips a hand-authored shadow-only passport whose write target is
reserved, so bypassing CLI authoring cannot route the memory writer into an OKF index or log.

---

## 6. Memory Doc Reference

Reference details for [Designated Memory Docs](#5-designated-memory-docs).

### 6.1 Strategy registry (from §5.5)

Strategies are defined in `MemoryStrategy` enum (`src/forge/session/passport.py`).

**Direct update strategies:**

| Strategy        | Behavior                                         |
| --------------- | ------------------------------------------------ |
| `project-state` | Update focus, active work, decisions, next steps |
| `checklist`     | Mark `[x]` completed, add discovered tasks       |
| `changelog`     | Add accomplishments, follow existing format      |
| `generic`       | Add any new information (default fallback)       |

Shadow mode (`--propose`) is orthogonal to strategy: any strategy works with `--propose`.

### 6.2 Passport example (from §5.2)

Memory doc passports are `forge_memory` YAML frontmatter blocks. The passport is the doc-level source of truth for
strategy, writers, and update mode; the surrounding concept metadata is descriptive and producer-owned.

```yaml
---
type: Memory Document
title: Implementation Notes
description: Human-approved durable implementation memory for future Forge sessions.
forge_memory:
  version: 1
  intent: "Human-approved durable implementation memory for future Forge sessions."
  captures: [stable decisions, non-obvious invariants, recurring bug causes]
  excludes: [raw session summaries, pending tasks, unverified hunches]
  update:
    strategy: generic
    mode: shadow-only
    writers: all-sessions
    approval: human-promoted
    shadow_path: .forge/memory/shadow_impl_notes.md
---
```

**CLI setup** (equivalent to the passport above):

```bash
# Passports are project-lifetime and sessionless:
forge memory track docs/board/change_log.md --strategy changelog
forge memory track docs/board/impl_notes.md \
  --propose --shadow-path .forge/memory/shadow_impl_notes.md

# Enable memory for a session:
forge session memory enable --session planner

# Verify:
forge memory passport show docs/board/change_log.md
forge memory list

# Explicitly add the envelope to an older passport:
forge memory passport upgrade docs/board/change_log.md
```

`forge memory track` is idempotent and sessionless: re-running with different flags updates the passport in place; with
no flags on an already-passported doc it is a no-op. Existing passports gain the outer envelope only through
`forge memory passport upgrade`; ordinary re-track does not migrate them. `forge memory passport remove <path>` removes
only `forge_memory`, so any outer `type`, `title`, `description`, and other producer metadata remain. One-off doc
updates that don't need a passport are ordinary agent instructions. All docs are processed in one `claude -p` call with
per-doc strategy instructions.

This is document-shape compatibility for newly tracked and explicitly upgraded Markdown docs, not a declaration of an
OKF bundle. Forge does not generate bundle metadata or maintain reserved `index.md` / `log.md` files. In proposal mode,
the envelope belongs to the explicitly tracked official document. An auto-materialized `.forge/memory/` shadow does not
receive one unless a user later tracks that shadow as a separate memory document.

### 6.3 Worktree resolution (extends §5.5)

Managed sessions always launch from `forge_root`. The memory writer resolves designated doc paths relative to
`forge_root`, so git-tracked docs (for example, a card checklist under `docs/board/doing/<slug>/checklist.md`) target
the correct branch when working in a worktree.

Trackedness is controlled by path choice; the agent doesn't distinguish:

- `docs/board/doing/<slug>/checklist.md` -> git-tracked, branch-specific (moves with the branch)
- `.forge/memory/debugging.md` -> untracked, per-Forge-project (`.forge/` is in `.gitignore`)
- `docs/suggested/coding_standards.md` -> git-tracked shadow doc (visible in PRs if desired)

Shadow docs also resolve relative to `forge_root`, so the agent reads the branch-correct official doc.

**Transcript path handling:** Transcripts live under `<forge_root>/.forge/artifacts/`. Because `cwd` is `forge_root`,
transcript paths in the prompt must be **absolute**; designated doc paths remain relative (resolved against `cwd`).

> **Note:** Artifacts (transcripts/plans) consolidate at `forge_root` for per-project visibility. Designated docs are
> working documents and belong with branch content.

### 6.4 Comparison with Claude Code auto-memory (from §5.5)

Claude Code (Feb 2026) ships **auto-memory**: Claude writes free-form notes to `~/.claude/projects/<project>/memory/`
during sessions. `MEMORY.md` (first 200 lines) loads at startup; topic files load on demand.

Forge's memory writer is complementary, not competitive:

| Aspect          | Auto-Memory                  | Memory Writer                              |
| --------------- | ---------------------------- | ------------------------------------------ |
| Timing          | During session (incremental) | After session (retrospective)              |
| Signal quality  | In-the-moment judgment       | Full-session hindsight                     |
| Structure       | Free-form, model-organized   | Per-doc strategies with constraints        |
| Target files    | User-local memory dir        | Project docs (repo-tracked, shareable)     |
| Curation        | None -- entries accumulate   | Shadow pattern provides human review gate  |
| Graduation path | None                         | Shadow doc -> human review -> official doc |

**Key design rationale:** Free-form capture relies on model judgment and tends to accumulate noise over time. The memory
writer reduces this via (a) retrospective synthesis, (b) per-doc topic constraints, and (c) the shadow pattern (human
curation gate).

Auto-memory is better for long-lived preferences; the memory writer is better for structured project docs and proposed
standards evolution.

**Deliberate non-integration:** The memory writer does not read auto-memory (`~/.claude/projects/<project>/memory/`) as
input. It's outside the project root (containment guard), is free-form (hard to dedupe against structured strategies),
and targets different information (preferences/patterns vs project state/standards). Occasional duplication is cheaper
than cross-format deduplication. If overlap becomes painful, a small prompt tweak can address it.

### 6.5 Session activation (from §5.6)

Memory activation is session-scoped. The effective `memory.auto_update.enabled` (intent + overrides via
`compute_effective_intent()`) is the sole gate. No checkout-level config file.

| Field                   | Type        | Default   | Meaning                                    |
| ----------------------- | ----------- | --------- | ------------------------------------------ |
| `auto_update.enabled`   | bool        | `false`   | Whether Stop enqueues deferred writer work |
| `auto_update.mode`      | str         | `augment` | `augment` (edit) or `review-only` (report) |
| `auto_update.min_turns` | int         | `5`       | Skip sessions shorter than this            |
| `auto_update.proxy`     | str \| null | `null`    | Optional `proxy_id` for the memory writer  |

Scan roots are hardcoded: `DEFAULT_SCAN_ROOTS = ("docs/",)` plus always `.forge/memory/`. Configurable roots deferred.

**Stale `.forge/memory.yaml`**: existing checkouts may have this file from a previous version. It is no longer read.
Safe to delete.

**Stale `designated_docs` in manifests**: old session manifests may contain `designated_docs` entries. These are
stripped on read with a one-time `logger.warning()` per coding-standards §5. The field no longer exists on
`MemoryIntent`.

**Stale `generated_file` in manifests**: Forge-authored `intent.memory.generated_file` is stripped from the in-memory
read payload without rewriting the manifest. It never selected a runtime output path, and new writes omit it; the same
key outside `intent.memory` remains a strict schema error.

---

[session design §3.9]: design_sessions.md#39-session-resume-context-management
