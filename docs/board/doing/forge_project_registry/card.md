# Project registry + enrollment (`~/.forge/projects.json`)

**Epic**: [`docs/board/doing/epic_global_forge_runtime/card.md`](../epic_global_forge_runtime/card.md)

**Lane**: `doing/`. **Precedes `forge_hook_dispatcher`** -- the dispatcher's shipped no-op gate reads this registry, so
the schema + read half must land first (correction from the first decomposition, which called it parallel). On the
user-scope-model critical path.

## Goal

A user-side registry of **trusted Forge project roots** so user-scope hooks activate only inside enrolled projects and
no-op everywhere else -- plus the enrollment surface, lifecycle, and read semantics that make the gate correct.

## Why

User-scope hooks fire in every repository. Without a trusted-root gate, a random repo could activate Forge hook behavior
just by containing a `.forge/` directory. The registry is the gate that makes user-scope-only hooks
(`user_scope_hook_ownership`) safe, and its **read path** is what the dispatcher's no-op check consumes.

## Design

- **Schema `~/.forge/projects.json`** -- **versioned** (`schema_version`), a list of enrolled roots with metadata
  (canonical absolute path, `enrolled_at`, enrollment source).
- **Canonical path form (epic shared contract)**: resolve symlinks and normalize absolute paths (macOS
  case-insensitivity, moved worktrees, symlinked checkouts) on **both write and read**, so enrollment lookups do not
  miss or duplicate.
- **Reuse existing detection**: build the "am I inside an enrolled root?" check on `find_forge_installation`
  (`installer.py:280`) / `find_forge_root` (`core/ops/context.py:106`); the *new* piece is the trusted-root registry,
  which does not exist today.

## Registry lifecycle (2026-07-02 finding)

The registry is not just a schema -- it needs a full lifecycle, or user-scope hooks silently miss real projects:

- **Enroll on enable.** `forge extension enable` (or the committed enrollment surface below) adds the canonical root.
  This ticket **commits to owning an enrollment surface** so downstream references resolve (`forge_project_compat`
  points at it); whether that surface is a dedicated `forge project` command or folded into `extension enable` is the
  open question below, but its *existence* is committed here, not left dangling.
- **Auto-enroll on worktree create / fork.** Forge's own session worktrees are new canonical roots. Worktree creation
  copies `**/.claude/settings*.json` into the new tree (`session/worktree/config_copy.py:24-33`), so in the **T2
  interim** a worktree inherits the absolute-path hook (same host, still resolvable) with no enrollment step. But under
  **T5 user-scope** there is no project hook block to copy, so the new root must be **enrolled** in `projects.json` (or
  covered by the `FORGE_SESSION` short-circuit) or the managed session lands in an unenrolled directory and loses hooks.
- **Backfill from `installed.json`.** `installed.json` already keys tracked installs by root (`local:` / `project:<abs>`
  forms, `install/models.py`) -- it is the de-facto existing list of Forge project roots. Migration
  (`forge_hook_migration_cleanup`) backfills the registry from those keys so existing installs enroll without a manual
  step. Note the overlap: two root lists (registry + `installed.json`) risk drift; the canonicalization rule plus later
  reconcile/prune actions keep them aligned.
- **Doctor registry section.** T3 adds a `forge extension doctor` registry section: corrupt/newer registry strict-read
  report + basic stale-root report. Reconcile/prune actions stay with `user_scope_hook_ownership` /
  `forge_hook_migration_cleanup`.
- **`FORGE_SESSION` short-circuit (contract with T4).** A managed session sets `FORGE_SESSION` (reaches the hook env,
  `cli/hooks/commands.py:1298`). The dispatcher's no-op gate must treat a managed session as active **even if cwd is not
  enrolled**, so a session in a not-yet-enrolled root does not silently lose hooks. The gate logic lives in
  `forge_hook_dispatcher`; the semantics are part of this registry's contract.

## Read semantics: strict in CLI, fail-open in the hook (2026-07-02 finding)

`projects.json` is durable state, but it is read from two very different call sites, and one rule does not fit both:

- **CLI path -> strict.** `forge project` / `doctor` / enable read it with strict versioned deserialization
  (`coding_standards` §5): an unsupported `schema_version` fails with a clear "written by newer Forge -- upgrade"
  message; unknown fields are corruption.
- **Hook/dispatcher path -> fail-open.** The dispatcher reads it on **every** `PreToolUse:Read` and prompt. A corrupt or
  newer registry there must **not** error every hook (that bricks the coding session) -- it degrades to "treat as not
  enrolled" and lets the session proceed, surfacing the corruption via `doctor`/CLI, not the hook. This mirrors the
  fail-open posture for policy evaluations (`design_workflows` §1.2). This ticket tests the **read helper's** fail-open
  (returns not-enrolled with a `degraded` reason on corrupt/newer input, never raises) in its own suite; the end-to-end
  **dispatcher-integration** fail-open assertion belongs to `forge_hook_dispatcher` (it owns `test_hook_dispatcher.py`,
  which does not exist when this ticket closes).

## Grounding (verified 2026-07-02)

- `projects.json` appears only in the epic; it is absent from `src/`, `tests/`, and other docs.
- No `forge project` command group exists (`cli/main.py:402-432` registers no `project`); no `project init`/`enroll`
  handlers.
- `installed.json` already keys installs by root (`local:` / `project:<abs>`), so a backfill source exists
  (`install/models.py`).
- `FORGE_SESSION` is present in the hook subprocess env (`cli/hooks/commands.py:1298`).
- Root-detection helpers exist and walk up from cwd today, but there is **no** user-side trusted-root registry.

## Risks

- **Registry drift**: moved worktrees or deleted projects leave stale roots; the registry and `installed.json` can
  disagree -- T3's doctor section reports, while T5/T6 prune/reconcile.
- **Canonicalization correctness**: the single normalization rule is shared with the dispatcher and the
  ownership/cleanup tickets; a mismatch causes silent no-fires or double-enrollment.
- **Two read policies**: forgetting the fail-open hook path turns a corrupt registry into a session-wide brick.

## Open questions

- **Trust model** -- **RESOLVED (D-T3-a):** enroll-on-enable + auto-enroll-on-managed-worktree, keeping
  `enrollment_source` provenance. Explicit-only rejected (`extension enable` is the consent; the dangerous design is
  enroll-on-*detection*, never proposed). See the T3 checklist Phase 0.
- **Surface**: a new `forge project` group vs folding enroll into `forge extension enable` (existence committed above;
  shape open).

## Acceptance tests

| Test                           | Fixture                                       | Assertion                                                                                                                                                | Test File                                          |
| ------------------------------ | --------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------- |
| Enroll canonicalizes           | symlinked checkout / moved worktree           | enrollment stores + looks up the canonical registered root                                                                                               | `tests/src/install/test_project_registry.py` (new) |
| Registry gates dispatch        | enrolled root vs unrelated repo               | lookup hits inside the root, misses outside                                                                                                              | same                                               |
| Worktree auto-enrolls          | `forge session` worktree/fork create          | the new worktree root is enrolled (managed session keeps hooks)                                                                                          | same                                               |
| CLI strict read                | `projects.json` with unknown `schema_version` | CLI raises a clear unsupported-version error, no silent default                                                                                          | `tests/src/install/test_project_registry.py`       |
| Read helper detect-and-surface | corrupt/newer `projects.json`, read helper    | helper returns not-enrolled **with a `degraded` reason** (a result object, not silent-empty), never raises; `doctor` strict-read surfaces the corruption | same (+ doctor test)                               |
| Stale root reported            | registered root now deleted                   | `doctor` reports the stale entry; prune/reconcile actions are deferred                                                                                   | `tests/src/cli/test_extension_enable.py` (doctor)  |
