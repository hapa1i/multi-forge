# Implementation Notes

Human-approved memory for details that future Forge sessions should retain.

This file is intentionally selective. The memory writer should propose additions in a shadow doc; humans promote only
the notes that are worth carrying forward.

## Maintenance

- Updated by humans after reviewing proposed notes, not directly by the memory writer.
- Source for proposed additions: `.forge/memory/shadow_impl_notes.md`.
- Keep notes durable and actionable. Prefer bullets with links to the source doc, issue, test, or file.
- Remove or rewrite notes when they become obsolete.
- Check size periodically and prune stale notes before appending:

```bash
wc -l docs/board/impl_notes.md
./scripts/count-tokens.py --model <agent-model> docs/board/impl_notes.md
```

## What Belongs Here

- Stable architecture decisions and the rationale behind them.
- Non-obvious invariants, ownership boundaries, and path or state rules.
- Bug causes, fixes, and test patterns likely to recur.
- Operational constraints that future sessions must remember.
- Conventions for executing multi-session work in this repo.

## What Does Not Belong Here

- Raw session summaries.
- Pending tasks or phase plans.
- Detailed command output.
- Unverified hunches.
- Duplicates of `docs/board/change_log.md`.

## Notes

### Memory System Architecture (shipped)

Two primitives: passports select docs (project-scoped, git-tracked frontmatter); session activation decides whether the
memory writer runs (`memory.auto_update.enabled`). No checkout-level config, no session-scoped doc lists.

- **Passports are the sole doc source**: `forge_memory` YAML frontmatter in docs declares strategy, writers, intent.
  Stop-time `scan_passported_docs()` discovers them under hardcoded roots (`docs/` + `.forge/memory/`). No manifest doc
  lists; `DesignatedDoc` is a runtime-only type for the scanner -> memory-writer pipeline.
- **Session activation**: `forge memory enable/disable --session` or `--memory on|off` at start/fork/resume. Both gates
  (Stop hook, detached runner) check `effective.memory.auto_update.enabled` directly. Incognito never enqueues.
- **Tombstone for old CLI**: `forge session memory` is a hidden tombstone group that errors with replacement guidance.
- **Stop-time chain**: stop hook -> work queue marker -> fire-and-forget `forge memory-writer run` -> passport scan ->
  writer filter -> `run_claude_session()`. Detached failures are not retried.
- **Shadow path encoding**: `derive_shadow_path()` encodes the immediate parent directory to avoid collisions.
  `check_shadow_path_collision_in_roots()` catches remaining edge cases.
- **Fork/resume**: children inherit parent's `auto_update` by default; `--memory on|off` overrides. No doc inheritance.
  Passports are git-tracked and discovered live in the child checkout.
- **Curation artifacts**: `curation-` prefix (distinct from the memory writer's `review-` reports) at
  `.forge/artifacts/<session>/memory/curation-{slug}-{hash}-{ts}.md`. Curation never mutates official docs.
- **Stale state**: old `.forge/memory.yaml` is ignored (safe to delete). Old `designated_docs` in manifests are stripped
  on read with a logger warning per coding-standards section 5.

### Memory vocabulary: memory writer vs transfer (memory_substrate rename)

The `memory_substrate` card split the overloaded "handoff" term into two concepts. Keep them distinct in future work:

- **Memory writer** — Stop-time project-doc curation: `session/memory_writer.py` (`run_memory_writer`,
  `resolve_writer_base_url`, `memory_report_dir`), `MemoryWriterConfig`, `memory_writer_timeout`,
  `forge memory-writer run`, `forge memory report show`.
- **Transfer** — resume/fork context assembly: `session/transfer.py` (`assemble_transfer_context`, `TransferResult`),
  `--resume-mode transfer`.
- **3-layer memory taxonomy** (design.md §5.6): raw memory (`.forge/artifacts/`), project memory (passported docs under
  `docs/`, `.forge/memory/`), transfer memory (`.forge/prev_sessions/`).

**Intentional KEEPs — do NOT rename these to memory-writer/transfer; they are durable state, routing keys, or
fixtures:** work-queue marker `kind="handoff"` + `enqueue_handoff_marker()` (ephemeral routing key); the
`.forge/artifacts/<session>/handoff/` artifact path (kept even though `review_dir()` became `memory_report_dir()` — see
the intentional-mismatch comment in `memory_writer.py`); the `queued_handoff` Stop-hook JSON field; QA fixture filenames
(`manual-handoff-*.jsonl`); and the industry-English "design-to-code handoff" in the skills-writing guide.

**CLI tombstone collision (gotcha):** the report command is `forge memory report show` (new `cli/memory_report.py`), not
`forge session memory show`, because `forge session memory` was already an occupied tombstone group. Before renaming a
CLI surface, check whether the target path is already a tombstone.

**Durable-value rename pattern (resume_mode):** `confirmed.derivation.resume_mode` migrated `"handoff"` → `"transfer"`
via accept-and-tolerate, not reject — readers map legacy `"handoff"`/`None` to transfer with no branching; writers emit
`"transfer"`. Regression: `tests/regression/test_bug_resume_mode_rename.py`.

### Curated transfer: schema + three-file artifact model (runtime_abstraction Phase 1)

Shipped 2026-05-31 (commit `2b70c29`). Durable invariants for `src/forge/session/transfer.py` and
`src/forge/session/prev_sessions.py`:

- **Three-file artifact model** under `<forge_root>/.forge/prev_sessions/<parent>/`: `generated.md` (regeneratable
  parent cache), `children/<child>.md` (frozen AI snapshot, schema sections 1-7), `children/<child>.notes.md` (user
  overlay, section 8). `forge transfer regenerate` rewrites only `generated.md`; `ensure_child` never overwrites an
  existing child; GC ties a notes file's liveness to its snapshot (never orphaned independently).
- **Child-agnostic frontmatter (load-bearing)**: the transfer frontmatter carries no `child` field, so `generated.md`
  and the copied `children/<child>.md` stay byte-identical. `ensure_child` and the auto-name retry byte-compare in
  `manager.py` both depend on this — do not add per-child fields to the frontmatter.
- **Citation honesty**: `schema: "full"` is stamped only for a successful ai-curated body; every other strategy or
  fallback is `"compatibility-fallback"`. `_validate_decision_citations()` drops any citation outside the `[turn N]`
  range the model actually saw (keeps the decision text, blanks false provenance), so `schema: full` never overstates
  evidence quality.
- **Namespace**: `forge transfer` is a **top-level** group (pairs with `forge memory`), not `forge session transfer`.
  `forge session resume --fresh --review` is a delegating entry point that edits the `.notes.md` overlay, not a
  competing namespace. `forge transfer show` (assembled artifact) is distinct from the deprecated
  `forge session context` (folded into `forge session show`).
- **`target_runtime`** is reserved in the frontmatter (`TRANSFER_TARGET_RUNTIME = "claude"`) for Phase 5 cross-runtime
  tuning: Phase 5 retargets presentation without changing transcript source artifacts or schema semantics.
