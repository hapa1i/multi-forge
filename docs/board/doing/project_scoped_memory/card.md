# Project-Scoped Memory

Status: proposal. Executes the deferred *Project-Level Defaults* from the archived memory-enhancement proposal
([`docs/board/done/memory_enhancement/card.md`](../../done/memory_enhancement/card.md), "Deferred Work") and resolves
its open question (snapshot-at-create vs. resolve-live-at-Stop) in favor of **live resolution by passport scan** at Stop
— no per-session participation, no project doc-list.

## Motivation

`forge memory` (PR #1) made the **passport** — the `forge_memory` frontmatter block in a doc — the authoritative,
durable, doc-level contract for how a doc is updated and who may update it. But the write-side UX welded two unrelated
lifetimes into one session-scoped verb. `forge memory track <doc>` does two things at once:

1. writes the **passport** into the doc — a project-lifetime, git-tracked edit; and
2. writes **participation** (`memory.designated_docs`) into the *session manifest* — session-lifetime state that dies
   with the session.

Both require a session (`track` calls `resolve_session`). That coupling produces three recurring friction points:

- **Authoring needs a session it should not.** `forge memory enable` / `track` fail from a terminal with "No session
  specified," even though writing a passport is just editing a git-tracked file. Users reasonably expect docs to be
  configurable at the project level — the passport itself even says `writers: all-sessions`.
- **Per-session re-tracking.** Every session that should maintain the changelog must re-run `track`. Forks inherit it,
  but standalone sessions do not. The passport already declares "any session may write me," yet no session does unless
  it re-declares participation.
- **Orphaned passports on delete.** Deleting a session leaves the passport in the doc (correct — it is the doc's
  property) but strips the only participation record. The passport now describes a contract that no session executes.

The redundancy is the tell: the passport's `writers` field and the session's `designated_docs` list encode overlapping
intent. `check_writer_access` (`passport.py`) is already a selector (`all-sessions` → true, else exact-name match);
today it only *filters* a list that was assembled per session.

## Design thesis

A doc participates in project memory **iff it has a passport and lives under a configured memory root** (the scan path;
default `docs/`, `.forge/memory/`). The passport is the declaration; the memory root bounds where Forge looks for one. A
passport outside the roots does not participate — `track` warns at authoring time so that is never a silent surprise.

- **Passport** = authoritative doc-level contract (unchanged), including `writers`, which already states who may write.
- **`writers`** = the selector at Stop: a session updates exactly the passported docs whose `writers` authorize it.
- **Activation config** = checkout-local operational consent: on/off, mode, `min_turns`, proxy. It is project-scoped
  because it lives under one `<forge_root>`, but it is not git-tracked contract. It never says what a doc is for, only
  whether handoff runs in this checkout and how it routes.
- **Session manifest** = optional per-session extras only.

This keeps the passport the single source of "which docs, and who writes them," and avoids the split-brain the original
thesis warns against — *"a doc says one thing, a project config says another, and a session manifest says a third."*
Deleting a session then has zero effect on memory configuration.

## Current vs. proposed data flow

| Concern           | Today                                                    | Proposed                                                                |
| ----------------- | -------------------------------------------------------- | ----------------------------------------------------------------------- |
| Author a passport | `track --session X` (passport + participation)           | `track` (sessionless, stateless — passport only)                        |
| Enable handoff    | `memory enable --session X` (manifest)                   | `memory enable` (local project activation); session may override fields |
| "Which docs?"     | session `designated_docs` list                           | scan passported docs (∪ optional session extras)                        |
| Doc selection     | `writers` filters the session list (`run_handoff_agent`) | `writers` selects from the scan (same code, unchanged)                  |

## Changes by code path

**1. Sessionless, stateless `track`.** `track_cmd` (`cli/memory.py`) writes/updates the passport into the doc and
nothing else — no participation write, no registry. It validates against `ctx.forge_root` (the path `passport_show_cmd`
already uses) and warns when the doc is outside the configured memory roots.

**Bare `forge memory track <doc>` always means "passport only" — even when `$FORGE_SESSION` is set.** It deliberately
does not consult the ambient session; ambient-dependent behavior would be invisible and surprising. Recording a
per-session extra (the one case scan cannot express; see Risks) requires a separate explicit spelling, for example
`forge memory extra add <doc> --session <name>` or `forge memory track <doc> --session <name> --extra`. This is the
minimum-friction rule: authoring is a pure project act, and the only session coupling is one you typed.

`--session` must not remain a hidden participation side effect on passport authoring. If a command writes or updates a
passport under a memory root, that doc is project-discovered by definition; a session-specific extra either points at a
doc outside the scan roots or is a legacy manifest-only entry. The CLI should warn when a user asks for a "session" doc
whose passported path will actually be discovered by every activated session.

**2. Project activation config.** A new versioned, project-scoped file holding operational state only:

```yaml
# <forge_root>/.forge/memory.yaml
version: 1
auto_update: { enabled: true, mode: augment, min_turns: 5, proxy: litellm-haiku }
```

No `docs:` list — participation is the set of passported docs. `forge memory enable` (no `--session`) writes this;
`--review-only` sets mode for the safe first run. Durable Forge-owned state: mandatory `version`, strict
deserialization, clear error on unsupported version (coding-standards §5).

`<forge_root>/.forge/memory.yaml` is intentionally checkout-local because `.forge/` is ignored. Passports are the
git-tracked contract; activation is local consent to run the writer in this checkout. A worktree fork therefore inherits
the committed passports, but not the enable bit. The new checkout participates only after `forge memory enable` runs
there, unless a future `fork --worktree` option explicitly copies the local activation file and reports that choice.

Session-level `auto_update` is a sparse field-wise override on top of the project activation config, not a full
replacement. Unset fields inherit from project config. `enabled=false` is an explicit per-session disable;
`enabled=true` plus `mode=review-only` can put one session in review-only while the checkout default is augment. The
resolver must preserve "unset" vs. "explicit false" instead of treating dataclass defaults as user intent.

**3. Activation resolved by a shared gate — at enqueue *and* at run.** This is the load-bearing implementation note.
Today the Stop hook enqueues a handoff marker only when the *session* `effective.memory.auto_update.enabled` is true
(`cli/hooks/commands.py:520`), and the detached runner re-checks the same field (`cli/handoff.py`, `run_cmd`). A
project-level enable therefore has **no effect unless both sites consult it** — if the hook does not enqueue, the runner
never runs. Introduce one shared resolver, `memory_activation(session, project) -> ActivationConfig | None` (project
config plus sparse session override), and call it at the enqueue gate *and* in `run_cmd`. A single source prevents the
two gates from drifting, and it returns `None` for incognito sessions (`is_incognito`) so ephemeral sessions never
enqueue (see Risks).

**4. Stop = scan + select by writers.** Once activated, the runner discovers candidate docs by scanning bounded memory
roots (default `docs/`, `.forge/memory/`; configurable) for `forge_memory` frontmatter, unioned with any per-session
extras. De-dupe by passport source / write path before invoking the agent so a legacy manifest entry cannot cause a doc
to be updated twice. `run_handoff_agent` is unchanged — `check_writer_access` selects the authorized subset, so a
`writers: planner` doc is skipped by every session but `planner`.

## Why not a project doc-list (rejected alternative)

A `docs:` registry in the project config would list memory docs explicitly and avoid the scan. Rejected: it is a second
source of "which docs are memory docs," redundant with passport presence, and it can drift — a passport added but
unregistered is silently never updated; a registered entry whose passport was removed is stale. That disagreement is
precisely the split-brain the passport model exists to prevent. The scan reads ground truth and cannot drift. Its only
cost is bounded frontmatter I/O at Stop, negligible beside the `claude -p` call the handoff already makes.

## Risks

- **Blast radius / consent.** Every qualifying session updates `writers: all-sessions` docs at Stop. `min_turns` and the
  project-enable are the throttles; the project-enable is the explicit consent surface for the current checkout. "Adopts
  any passported doc" is intended semantics, not a hazard — a passport *is* the declaration.
- **Scan bounding and the participation qualifier.** Discovery must not walk the whole repo. Default to `docs/` +
  `.forge/memory/`, configurable; never `.git/`, `node_modules/`, etc. The consequence is that participation is
  "passport *and* under a memory root," not passport alone — `track` warns at authoring time when a doc falls outside
  the roots so the qualifier is never a silent no-op.
- **Incognito / ephemeral sessions (verified).** The Stop hook fires inside Claude and enqueues *before* the incognito
  `finally` block deletes the session (`session_lifecycle.py:1103`), so under a project-level gate an incognito session
  *would* enqueue. The detached `forge handoff run` then usually no-ops because the manifest is already gone
  (`cli/handoff.py`, `store.exists()` is false) — but that is a race, not a guarantee; concurrent queue draining could
  let it run while the manifest still exists. The shared activation resolver therefore excludes incognito explicitly
  (`is_incognito`), matching the existing `include_incognito=False` memory reads (`memory.py:743`,
  `shadow_curation.py:70`).
- **Local activation surprise.** Because `.forge/memory.yaml` is not git-tracked, a new worktree can have the right
  passports and still not run project memory until it is enabled locally. That is the cost of making write automation a
  checkout-local consent surface. The CLI should make this visible in `forge memory status` and optionally in
  `fork --worktree` warnings.
- **Per-session exclusivity gap.** Scan + `writers` cannot express "only session X writes this `all-sessions` doc, just
  this once" without changing the doc's contract for everyone. Retained per-session extras cover the inverse (a session
  adds a manifest-only doc the project scan does not adopt); true per-session narrowing is deferred.
- **Decommissioning.** The shipped CLI uses `forge memory passport remove <path>` to remove a doc's project passport.
  `forge memory untrack` remains session-participation-only.

## Staging

1. **Slice 1 (additive, no schema break):** checkout-local project activation config + a shared activation resolver
   wired into **both** the Stop-hook enqueue gate (`commands.py:520`) and `run_cmd` + Stop scan discovery (∪ existing
   `designated_docs`) + explicit project-enable consent messaging. No `track` change. Immediately removes per-session
   enable and re-tracking for passported docs in the current checkout.
2. **Slice 2:** make `track` sessionless + stateless (passport-only write; drop the participation write).
3. **Slice 3 (optional):** decommission verb; deprecate per-session `designated_docs`, or keep it as the per-session
   extras escape hatch.

## Worked example: the dogfood workflow

The current `docs/board/README.md` "Advanced Workflow" configures memory per session (`--no-launch` to attach docs
before the first Stop, `track --session`, `--inherit-memory` on forks). Under this proposal it becomes a one-time
passport setup plus a per-checkout activation step; sessions carry no memory commands.

**Project memory setup — once; commit passports so worktrees inherit the contract via git:**

```bash
forge memory track docs/board/change_log.md --as changelog          # writes passport into the doc
forge memory track docs/board/impl_notes.md \
  --propose --shadow .forge/memory/suggested_impl_notes.md           # shadow-only passport
git add docs/board/change_log.md docs/board/impl_notes.md
git commit -m "chore: project memory passports"
forge memory enable --review-only                                     # local activation, safe first run
```

**Planner / Executor / Reviewer — no memory commands:**

```bash
forge session start planner --proxy openrouter-openai
# plan, /exit -> Stop scans passported docs under the memory roots, selects by writers (review-only report)
forge session handoff show planner --latest
forge memory enable                                                   # flip project memory to augment

forge session fork planner --name executor --worktree --supervise --inline-plan
# In the new checkout, before executor exits:
(cd ../multi-forge-executor && forge memory enable --review-only)      # local activation for that worktree
forge session fork planner --name reviewer --into ../multi-forge-executor --inline-plan
```

**What changes vs. today:**

- The planner's `--no-launch` was only there "so memory docs are attached before the first Stop"; that reason is gone.
- No per-session `track` / `enable`; sessions run clean. New checkouts still need one local `forge memory enable`.
- **`--inherit-memory` becomes obsolete for doc participation.** Git carries passports into worktrees, so a worktree
  fork knows which docs are memory docs by virtue of the committed passports. It does not inherit the checkout-local
  enable bit.
- **New rule: commit passports before a worktree fork**, or the new checkout will not have them — a silent
  non-participation, mirroring the scan-root qualifier. Same-checkout forks need no commit.
- **Shadow files auto-materialize at Stop**, not at fork time. The handoff agent creates `.forge/memory/suggested_*.md`
  when a shadow-only passport's target is missing (the auto-create logic exists; it moves from fork-time to Stop-time).

## Relationship to runtime abstraction

Curated handoff is the cross-runtime transfer substrate ([`runtime_abstraction/card.md`](../runtime_abstraction/card.md)
Phase 1). Project-scoped memory is complementary: it removes per-session setup friction during dogfooding, and
live-at-Stop resolution composes more cleanly with cross-runtime handoff than create-time snapshots — a Codex session
resuming from a Claude session should resolve project memory from the project, not from an inherited snapshot.

## Open questions

- Scan roots: is `docs/` + `.forge/memory/` the right default, and how is it configured (a project-config key vs. a
  fixed convention)?
- Should `writers: all-sessions` stay the synthesized default once any session can write, or should authoring default to
  a more conservative writer to bound blast radius?
- What exact CLI spelling should replace `track --session` for manifest-only extras?
- Should `fork --worktree` offer to copy the local activation config, or only warn that the new checkout needs
  `forge memory enable` before its first Stop?
- Should `--inherit-memory` be deprecated once git carries passports into worktrees, and should `fork --worktree` warn
  when uncommitted passports would be left behind (the commit-before-fork footgun)?
