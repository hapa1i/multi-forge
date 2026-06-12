# Forge Transfer — Resume/Fork Context Guide

**Status:** Implemented (`forge transfer show|regenerate|edit|diff`). The cross-runtime hop is one command:
`forge session start <name> --runtime codex --resume-from <parent> --task "…"` (see [session.md](session.md)); the
manual `regenerate → show → codex exec` recipe below remains for sessionless handoffs.

- Canonical architecture: [`docs/design.md`](../design.md) §3.9 (transfer) · schema:
  [`design_appendix.md`](../design_appendix.md) §M
- Sessions (resume/fork): [`session.md`](session.md)
- Authentication (Codex, OpenRouter): [`authentication.md`](authentication.md)

---

## What transfer is

**Transfer** is the curated context that carries a session forward across a resume, a fork, or — with
`--target-runtime codex` — a different agent runtime. It is the editable, inspectable half of session continuity:
`forge memory` curates project docs, `forge transfer` shapes the resume/fork context. Every `forge transfer` verb takes
a **parent session** argument; transfer is session-derived, not a session subresource.

Native `--resume --fork-session` carries the full conversation but is opaque and locked to one runtime and working
directory. **Curated transfer is the portable substrate**: a parent's context is distilled into a Markdown doc you can
read, edit, and hand to another runtime. See [session.md](session.md#derive-a-fresh-session-from-an-existing-one) for
how resume and fork produce it.

## The three files

Each parent gets a directory under `.forge/prev_sessions/<parent>/`:

| File                        | Role                                    | Who writes it                                        |
| --------------------------- | --------------------------------------- | ---------------------------------------------------- |
| `generated.md`              | Parent AI cache — the distilled context | `regenerate` (overwritten each time)                 |
| `children/<child>.md`       | Per-child frozen AI snapshot            | created at the child's launch; **never edited**      |
| `children/<child>.notes.md` | Per-child user-notes overlay            | you, via `edit`; merged after the snapshot at launch |

Regenerating the parent cache never disturbs an existing child snapshot or its notes — so your curation survives a
re-resume.

## Commands

```bash
forge transfer show <parent>                       # show the parent AI cache
forge transfer show <parent> --child <c>           # show a child's composed launch view (snapshot + notes)
forge transfer show <parent> --json                # frontmatter + sections + content, as JSON
forge transfer regenerate <parent>                 # rebuild the cache (same strategy/depth/runtime as before)
forge transfer regenerate <parent> --strategy ai-curated --depth 2
forge transfer edit <parent> --child <c>           # edit the child's user-notes overlay in $EDITOR
forge transfer diff <parent> --child <c>           # how the cache has drifted from the child's frozen snapshot
```

| Command      | What it does                                                                                                                                                                                                                          |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `show`       | Print the parent cache, or a child's composed launch view with `--child`. `--json` for tooling.                                                                                                                                       |
| `regenerate` | Rebuild **only** `generated.md` (children and notes untouched). Flags default to the cache's current `--strategy`/`--depth`/`--target-runtime`, so a regenerate never silently downgrades or flips them. Creates the cache if absent. |
| `edit`       | Open the child's `.notes.md` overlay in `$EDITOR` (created if absent). Notes merge into the child's launch context on the next resume.                                                                                                |
| `diff`       | Show the cache-vs-snapshot drift for a child (empty when there is none).                                                                                                                                                              |

> **Note:** `--child` is inferred when the parent has exactly one child; otherwise name it.

**Strategies** (`--strategy`): `minimal` | `structured` (default) | `full` | `ai-curated`. Only `ai-curated` calls a
model — it distils the transcript into the full schema; the others are deterministic. `ai-curated` needs
`OPENROUTER_API_KEY` (see [authentication.md](authentication.md)); without it, curation falls back to `structured`.

## Hand a plan to Codex (cross-runtime)

Reasoning state is **not** portable across agent runtimes, so the cross-runtime hop is the **curated transfer**, not a
native resume: you plan in Claude, then hand the distilled context to a headless `codex exec` run.

**Prerequisites:** `codex` installed and authenticated (`forge runtime preflight codex` → `Ready YES`);
`OPENROUTER_API_KEY` for `ai-curated`.

**The one-command flow** creates a real Codex-runtime Forge session — derivation lineage, the `codex exec` thread id,
and per-turn usage all recorded — and runs the first turn:

```bash
# 1. Plan in a normal Claude session (e.g. `forge session start planner`), then exit.

# 2. Derive a Codex session from it and run the first turn (curates the transfer for you):
forge session start impl --runtime codex --resume-from planner --task "Implement the plan."

# 3. Continue the same Codex thread, turn by turn:
forge session resume impl --task "Now add tests for the edge cases."

# 4. Inspect what happened:
forge session show impl     # Runtime, thread id, rollout path, auth posture
forge activity impl         # transfer-curate + codex turns under one run tree
```

By default the curated context rides the first `codex exec` prompt (zero setup). With a trust-enrolled
`codex-session-start` hook you can opt into SessionStart delivery instead — `--context-delivery hook` — which keeps the
prompt as your task alone and injects the context as `additionalContext`; see
[session.md](session.md#derive-a-codex-session-from-a-claude-parent-cross-runtime) and
[hook.md](hook.md#codex-session-start-codex-sessionstart) for the registration and failure semantics.

**The manual recipe** stays available when you want the handoff without a Forge session:

```bash
# Distil into a Codex-targeted curated transfer (creates the cache if absent):
forge transfer regenerate planner --target-runtime codex --strategy ai-curated

# Review the curated context:
forge transfer show planner

# Hand it to Codex as the initial message, with your task appended:
codex exec "$(forge transfer show planner)

Your task: implement the change described in the context above."
```

`--target-runtime codex` stamps the transfer for Codex: the `## Runtime Hints` section names Codex idioms (`codex exec`,
sandbox modes) instead of Claude's. `ai-curated` makes a billed `core.llm` curation call; Forge records it in the usage
ledger (`transfer-curate` in `forge activity`) **only when it runs inside a Forge run tree** — the cross-runtime bridge
does, but a bare `forge transfer regenerate` from a shell runs the curation without a ledger row (no ambient run tree).

> **Note:** `forge transfer show` prints the transfer's YAML frontmatter (metadata — strategy, lineage,
> `target_runtime`) ahead of the curated body; both are harmless context for Codex, and the `## Runtime Hints` section
> tells Codex how to run.

> **Note:** The one-command flow rejects `--resume-from` without `--runtime codex` — with the default (Claude) runtime
> it would just be `forge session resume <parent> --fresh`, which already exists. Omitting `--task` makes the bridge
> interactive: the curated context opens a `codex` TUI session instead of a headless turn (see
> [session.md](session.md#interactive-codex-sessions)).

## Troubleshooting

- **`No transfer context for '<parent>'`** — the parent has no cache yet. Run `forge transfer regenerate <parent>` (or
  `forge session resume <parent> --fresh`) to create it.
- **`ai-curated` produced a plain (structured) body** — no `OPENROUTER_API_KEY`, or the parent has no transcript.
  Curation is best-effort; the deterministic body still ships.
- **Codex isn't ready** — run `forge runtime preflight codex` for the blocking reason (install / authenticate `codex`).
