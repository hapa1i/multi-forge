# Forge Memory Writer — Automatic Memory Docs Guide

Shadow/propose mode and topic strategies available.

The memory writer is queued automatically when a session ends and runs on the next Forge CLI startup to update tracked
memory docs based on what happened in the session. It reads the session transcript and writes updates to pre-existing
official files or Forge-owned shadow proposal files.

- Canonical architecture: [`docs/design.md` §5.6](../design.md)
- Sessions (unit of work): [`session.md`](session.md)
- Hooks (lifecycle events): [`hook.md`](hook.md)

> **Memory writer vs. transfer.** This guide covers the **memory writer**: the Stop-time worker that curates project
> memory docs (`docs/checklist.md`, shadow files for coding standards, etc.). Its per-session output lives under
> `<forge_root>/.forge/artifacts/<session>/handoff/review-*.md` -- see `forge memory report show`. For **transfer** --
> the parent-context file assembled for `forge session resume --fresh` (at
> `<forge_root>/.forge/prev_sessions/<parent>/{generated.md,children/<child>.md}`) -- see [`session.md`](session.md).

---

## What the memory writer does

After a session stops, the Stop hook enqueues a work marker. On next CLI startup, Forge spawns a headless `claude -p`
subprocess that:

1. Reads the session transcript
2. Reads each tracked memory doc
3. Applies per-doc strategy instructions (add completed tasks, record errors, propose changes)
4. Writes minimal updates to each file

The memory writer is **retrospective** — it sees the full session before deciding what to capture. This produces higher
signal-to-noise than incremental note-taking during a session.

---

## Two operating modes

### Mode 1: Direct update (writer is author)

The memory writer edits tracked docs in-place. Use for operational documents the writer has authority to maintain.

```bash
forge memory track docs/checklist.md --strategy checklist
forge memory track docs/changelog.md --strategy changelog
```

### Mode 2: Shadow/propose (writer is advisor)

The memory writer writes suggestions to a **shadow file** for human review, reading the official document first to avoid
redundant proposals. Use for standards and guidelines where human curation matters.

```bash
forge memory track docs/developer/coding-standards.md \
  --propose --shadow-path .forge/memory/shadow_standards.md
```

The shadow file contains `- [ ]` checkboxes with rationale. The human reviews and merges what's valuable into the
official doc. Already-merged items are self-pruned on the next run.

---

## Configuration

Use `forge memory` to author passports and enable the writer. `track` writes a `forge_memory` passport into each doc;
that passport is the doc-level contract for strategy, mode, and writer access. `track` is **sessionless** (project-
lifetime). Memory activation is **session-scoped** -- each session decides whether the memory writer runs.

```bash
# Author project passports (sessionless; runnable from a bare terminal)
forge memory track docs/checklist.md --strategy checklist
forge memory track docs/changelog.md --strategy changelog

# Author a human-reviewed shadow proposal passport
forge memory track docs/developer/coding-standards.md \
  --propose --shadow-path .forge/memory/shadow_standards.md

# Enable memory for a session (or start with --memory on):
forge memory enable --session planner
forge session start planner --memory on     # equivalent at start time

# Set the writer's reasoning effort (claude --effort: low/medium/high/xhigh/max).
# --effort updates effort even when memory is already enabled in the same mode.
forge memory enable --session planner --effort high

# Verify passported docs:
forge memory list
```

Example passport written by `forge memory track`:

```yaml
---
forge_memory:
  version: 1
  intent: "Compact completed-work record."
  captures: [completed work, verification]
  excludes: [pending task plans, raw session summaries]
  update:
    strategy: changelog
    mode: direct
    writers: all-sessions
---
```

### Setting up via CLI

```bash
# List passported docs under scan roots (sessionless)
forge memory list

# Author a project passport (sessionless)
forge memory track docs/checklist.md --strategy checklist

# Remove the project passport so the doc is no longer discovered by scans
forge memory passport remove docs/checklist.md

# Enable/disable memory for a session
forge memory enable --session planner
forge memory disable --session planner
```

One-off doc updates that don't need a passport are ordinary agent instructions -- just ask the agent to update a file
before it stops.

### Inspecting writer output

The memory writer runs detached from the Stop work queue, so its stdout is not visible at the terminal. Every run is
captured to a per-session review file:

```text
<forge_root>/.forge/artifacts/<session>/handoff/review-<YYYYMMDD-HHMMSS-micros>.md
```

Inspect via:

```bash
forge memory report show                    # Latest report for current session
forge memory report show my-session         # Latest report for named session
forge memory report show --all              # List every report (paths + timestamps)
```

In `review-only` mode this is where the proposed-but-not-applied changes appear; in `augment` mode it records the
summary of what was actually written.

---

## Strategies

Each tracked memory doc has a strategy that controls how the writer updates it.

### Direct update strategies

| Strategy        | What the writer does                                             |
| --------------- | ---------------------------------------------------------------- |
| `project-state` | Update current focus, active work, decisions, next steps         |
| `checklist`     | Mark completed tasks `[x]`, add newly discovered tasks           |
| `changelog`     | Add accomplishments not already recorded, follow existing format |
| `generic`       | Add any new information missing from the file (default fallback) |

All direct strategies are **additive** — the writer does not remove, rewrite, or restructure existing content.

Shadow mode (`--propose`) is orthogonal to strategy: any strategy works with `--propose`. The writer reads the official
doc first, then proposes only what's missing as `- [ ]` checkboxes with rationale in the shadow file.

---

## File requirements

**Official docs must already exist.** The writer does not create official project docs for you. Forge-owned shadow files
under `.forge/memory/` are created by `forge memory track --propose`; non-Forge-owned shadow paths must already exist.

Before enabling the memory writer, seed the files you want maintained:

```bash
# Direct update docs
echo "# Implementation Checklist" > docs/checklist.md
echo "# Change Log" > docs/changelog.md

# Shadow docs (official doc must exist; Forge-owned shadow is created by track --propose)
# docs/developer/coding-standards.md should already exist
```

Missing official files are skipped at runtime. `forge memory track` catches missing official docs up front.

---

## Path resolution

Tracked memory doc paths are **forge-root-relative**. When working in a git worktree, the writer edits the correct
branch's content.

Transcript paths are stored as **forge-root-relative** paths and resolved against `forge_root` at runtime. Transcripts
are artifacts stored at `<forge_root>/.forge/artifacts/`.

| Path type              | Resolves against | Why                               |
| ---------------------- | ---------------- | --------------------------------- |
| tracked official doc   | `forge_root`     | Edits branch-specific content     |
| passport `shadow_path` | `forge_root`     | Writes branch-specific proposals  |
| `transcript_rel`       | `forge_root`     | Artifacts scoped to Forge project |

The `claude -p` subprocess runs with `cwd=forge_root`.

---

## Memory on fork and resume

Children inherit the parent's memory activation by default. The `--memory` flag overrides:

```bash
forge session fork parent-session --worktree                 # inherit parent's on/off
forge session fork parent-session --worktree --memory on     # force on in child
forge session fork parent-session --worktree --memory off    # force off in child

forge session resume parent-session --fresh --memory off     # requires --fresh
```

Memory docs are not inherited -- they are discovered from passports at Stop time in whatever checkout the child runs in.
Passports are git-tracked, so worktree forks see the same docs as the parent.

---

## Execution flow

```
Session stops
  → Stop hook captures transcript to <forge_root>/.forge/artifacts/
  → Stop hook enqueues "handoff" work marker
  → (session ends)

Next CLI startup (any forge command)
  → Work queue processes pending markers
  → Memory-writer handler spawns detached background process:
      forge memory-writer run --session-name <name> --worktree-path <path> --transcript-rel <rel>

Background process:
  → Reads session manifest → compute effective intent
  → Checks: enabled? min_turns met? claude available? mode valid?
  → Validates tracked docs (path safety, passport validity, writer access, file existence)
  → Builds multi-doc prompt with per-doc strategy instructions
  → Runs: claude -p (stdin=prompt, cwd=forge_root, timeout=5min)
```

### Proxy routing

The memory writer inherits the session's proxy by default (same model routing). Override with `proxy`:

```yaml
auto_update:
  enabled: true
  proxy: openrouter-gemini-flash   # Use a cheaper proxy for summarization
  effort: high                     # claude --effort for the writer's claude -p run (optional)
```

Priority chain: `proxy` -> `confirmed.started_with_proxy` -> `ANTHROPIC_BASE_URL` env -> Anthropic direct.

`effort` (optional) sets the writer's `claude --effort` level (`low/medium/high/xhigh/max`). Set it with
`forge memory enable --effort <level>`. Shadow curation (`forge memory shadows review --curate`) inherits this effort
unless overridden with its own `--effort`.

---

## Validation rules

The memory writer validates tracked docs before processing. For passported docs, the passport on the official doc is
authoritative; session manifests store only activation and runtime state.

| Rule                 | Rejected or skipped if                                                  |
| -------------------- | ----------------------------------------------------------------------- |
| Path safety          | A write, official, or shadow path is absolute, unsafe, or escapes root  |
| Passport validity    | `forge_memory` frontmatter is malformed or violates the passport schema |
| Mode consistency     | `mode=shadow-only` lacks `shadow_path`, or `mode=direct` has one        |
| Self-shadowing       | Shadow path resolves to the same file as the official doc               |
| Writer authorization | Passport `writers` does not allow the current session                   |
| File existence       | Write target is missing, or a shadow entry's official doc is missing    |
| Legacy manifest only | Passport-less entries violate old `suggested`/`shadows` coupling        |

`forge memory track` validates these rules up front and writes or updates the passport. Older session manifests are
still revalidated at runtime; invalid or missing docs are skipped with a log warning. If all docs are invalid or
missing, the writer exits cleanly (not an error).

The transcript path is also validated (same safety checks) since it comes from CLI args / work queue markers.

---

## Troubleshooting

### "Memory writer didn't run"

Checklist:

- `memory.auto_update.enabled` must be `true` in effective intent (`forge memory enable`)
- Session must have ≥ `min_turns` conversation turns (default: 5)
- `claude` CLI must be on PATH
- At least one memory doc must be discoverable: a passported doc under the scan roots
- At least one doc must exist on disk

### "File wasn't updated"

- The file must exist before the writer runs (no file creation)
- For shadow docs, the official doc must exist and the passport `shadow_path` must be valid
- Check the strategy — does it match what you expect the writer to do?
- Try `forge memory enable --review-only --session <name>` to see what the writer would change without modifying files

### "Wrong file was updated" (path issues)

- Tracked memory docs resolve against `forge_root`
- If working in a worktree, verify the file exists at the Forge project root (not just the main repo)
- Check `forge session show <name>` to see the forge_root path

### "Writer timed out"

Default timeout is 5 minutes. For large transcripts or many docs, the writer may need more time. Set via CLI:

```bash
forge memory-writer run --session-name <name> --worktree-path <path> --transcript-rel <rel> --timeout 600
```

---

## Files to inspect (debugging)

| File                                                     | Purpose                                         |
| -------------------------------------------------------- | ----------------------------------------------- |
| `<forge_root>/.forge/sessions/<name>/forge.session.json` | Session manifest (activation + runtime state)   |
| `<forge_root>/.forge/artifacts/<name>/transcripts/`      | Captured transcripts (writer input)             |
| `~/.forge/pending-work/`                                 | Work queue markers (handoff-\<session_id>.json) |
| `~/.forge/pending-work/failed/`                          | Poison markers (exceeded retry limit)           |

### Gotchas

| Trap                                 | Explanation                                                                |
| ------------------------------------ | -------------------------------------------------------------------------- |
| "Memory enabled but nothing happens" | No passported docs are under the scan roots (`docs/` + `.forge/memory/`)   |
| "Shadow doc not updating"            | Official doc must exist and passport `shadow_path` must be valid           |
| "Writer uses wrong model"            | Inherits session proxy by default; set `proxy` for explicit routing        |
| "File created by writer"             | Writer never creates files — seed them first                               |
| "Stale suggestions in shadow doc"    | Writer self-prunes merged items; run again after merging into official doc |
