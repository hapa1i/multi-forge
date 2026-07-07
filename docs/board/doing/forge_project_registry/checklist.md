# Execution checklist: T3 `forge_project_registry`

Epic: [`epic_global_forge_runtime`](../epic_global_forge_runtime/card.md). Card: [`card.md`](card.md). Branch:
`forge-project-registry`.

## Current focus

**Pre-implementation review checkpoint.** The card is picked up (`proposed/ -> doing/`) but **no code is written yet**.
The trust-model and file-format Phase 0 decisions are resolved below; the enrollment surface remains open as D-T3-b.
Phase 1 can proceed on the durable `~/.forge/projects.json` schema/read helper, while Phase 2 enrollment wiring and
Phase 3 CLI reference sync wait on D-T3-b. Everything below is unticked until its assertion is verified (Phase 0's
re-verification and greenfield items are already done and ticked).

T3 is the head of the user-scope-model track (T3 -> T4 -> T5 -> T6). Its **read half** is the dependency for T4's
dispatcher no-op gate, so "schema + read helper" (Phase 1) is the load-bearing deliverable; enrollment/lifecycle (Phase
2\) makes the gate correct.

**Module home:** `src/forge/install/project_registry.py`; test mirror `tests/src/install/test_project_registry.py` (the
test-mirror rule -- the acceptance-table paths below are valid iff the module lives there).

## Scope boundary (what is NOT in T3)

Record hand-offs so the ticket does not creep:

- **Backfill from `installed.json` -> T6** (`forge_hook_migration_cleanup`; moved out of T3 in the epic's Round-5
  review). T3 only defines canonicalization + the registry write API that T6's backfill calls.
- **Dispatcher no-op gate + end-to-end fail-open integration test -> T4** (`forge_hook_dispatcher` owns
  `test_hook_dispatcher.py`, which does not exist when T3 closes). T3 tests the **read helper's** fail-open in its own
  suite; the `FORGE_SESSION` short-circuit *gate logic* is T4's, its *semantics* are T3's contract.
- **User-scope-only registration + reconcile/prune actions -> T5/T6.** T3 adds a `forge extension doctor` registry
  section in this ticket: corrupt/newer registry strict-read report + basic stale-root report. Reconcile/prune actions
  and broader ownership/cleanup UI live with the ownership/cleanup tickets.
- **Authoring `.forge/project.toml` is NOT here (and is not T3 work).** T7's hand-off pointer resolves to this decision:
  **v1 authoring of the compat pin is hand-edit** (T7 documents the file format for humans; consistent with its opt-in
  framing). An optional "author this file for me" convenience is **deferred**; if ever built it would attach to T3's
  enrollment surface -- but it is not scheduled and T3 ships nothing for it.

## Phase 0 -- Decisions + seam re-verification (the review checkpoint)

- [x] **DECISION D-T3-c (file format) -- RESOLVED 2026-07-07: JSON (`~/.forge/projects.json`), not TOML.** The registry
  is machine-written Forge-owned durable state, so it follows the house pattern of every sibling registry
  (`sessions/index.json`, `proxies/index.json`, `backends/index.json`, `installed.json`) and **reuses existing
  primitives for free**: the versioned-JSON read helper, `atomic_write_text`, and the corrupted-vs-unreadable error
  taxonomy (`state_primitive_hoist` impl_note). **Write mechanism:** those shared JSON helpers -- Forge ships no TOML
  *writer* (stdlib `tomllib` is read-only; `codex_hooks.py` hand-renders only because it merges into a codex-owned
  file). Bonus: JSON dissolves T4's "TOML-parse-in-shim tension" (the hot-path gate parses stdlib `json`) and signals
  "not a hand-edit surface." Epic seam 2 amended to match. (T7's `.forge/project.toml` stays TOML -- user-authored.)
- [x] **DECISION D-T3-a (trust model) -- RESOLVED 2026-07-07: enroll-on-enable + auto-enroll-on-managed-worktree**,
  keeping `enrollment_source` as meaningful provenance (`manual | enable | worktree | backfill`).
  - **Why not explicit-only:** the guarantee to protect is "a random repo with a stray `.forge/` cannot activate
    user-scope hooks." `forge extension enable` targeting a root is itself the consent; a managed worktree/fork is
    *derived* consent (a user-initiated session command from an already-enrolled root). Neither is triggered by merely
    `cd`-ing into a hostile repo -- the dangerous design is enroll-on-**detection** (a hook seeing `.forge/`
    self-enrolls), which nobody proposed. So explicit-only adds a friction step **without a safety property** while
    creating the unenrolled-managed-session failure mode.
  - **Sub-decision (name it in Phase 2):** "enroll on enable" enrolls the **project root the enable targets**
    (`--scope project`/`local`). A `--scope user` global enable has no project target and enrolls **nothing** by itself;
    managed sessions self-cover via worktree auto-enroll and the `FORGE_SESSION` short-circuit.
- [ ] **DECISION D-T3-b (enrollment surface) -- OPEN (lean: fold into `forge extension`).** A new `forge project` group
  vs folding enroll into the existing `forge extension` family. The epic CLI-surface rule prefers attaching to existing
  groups and a new top-level group needs explicit justification, so the lean is **fold enrollment into
  `forge extension enable` (+ an explicit `forge extension` verb if a standalone enroll/prune is warranted)**. Confirm
  or justify a new group here; T3 owns whatever surface is chosen so `forge_project_compat` / `forge_hook_dispatcher`
  references resolve.
- [x] **Seam re-verify (done 2026-07-07, recorded):** `find_forge_installation` -> `install/installer.py:280` (card said
  `:279`); `find_forge_root` **relocated** to `core/ops/context.py:106` (card said `context.py:122` -- the ops
  extraction moved it); `FORGE_SESSION` reaches the hook env, now a single comment at `cli/hooks/commands.py:1298` (card
  said `:90,:1302`; the fact holds). Build the enrolled-root check on the *current* helpers, not the stale refs.
- [x] **Greenfield confirmed (2026-07-07):** no `project(s).toml` / `projects.json` references exist in `src/` or
  `tests/` -- no colliding prior art to reconcile.

## Phase 1 -- Schema + canonicalization + versioned read helper (the T4 dependency)

- [ ] **Schema `~/.forge/projects.json`** -- versioned (`schema_version`) durable state; a list of enrolled roots, each
  `{ canonical_path, enrolled_at, enrollment_source }`. Written via the shared versioned-JSON helper +
  `atomic_write_text` (D-T3-c). Follows Forge durable-state rules (mandatory version field, strict shape on the CLI read
  path).
- [ ] **Concurrent-write posture:** every registry writer (enable, managed-worktree auto-enroll, and future backfill)
  performs read-modify-write under `file_lock_for_target(target_path=projects_path, timeout_s=5.0)`, then persists with
  `atomic_write_text`. This follows Forge's credentials/install-tracking pattern, not unguarded last-writer-wins.
- [ ] **One canonicalization rule** applied on **both write and read** (epic seam-2 contract -- T4/T5/T6 must reuse the
  identical rule or the gate silently no-fires / double-enrolls). Resolve symlinks + normalize absolute path, and **pin
  the mechanism** here rather than "account for":
  - Tradeoff -- **inode / `os.path.samefile`** is robust against macOS default case-insensitivity and APFS's
    normalization-insensitive matching, **but requires the path to exist** (a moved/deleted root can't be stat'd, which
    collides with Phase-2 stale-root handling). **Resolved-string comparison** is existence-independent **but must
    explicitly case-fold + Unicode-normalize**: note APFS preserves the caller's spelling/normalization,
    `posixpath.normcase` is a **no-op** on POSIX, and `Path.resolve()` preserves case, so none unifies `/Users/x` vs
    `/users/x` on its own.
  - **Lean:** store a canonical *resolved string* for lookup (existence-independent) with documented case/Unicode
    handling; reserve `samefile` for existence-confirmed reconciles only.
- [ ] **Dual read semantics from one parser:**
  - **CLI path -> strict.** Unsupported `schema_version` fails with a clear "written by newer Forge -- upgrade" message;
    unknown fields are corruption (coding_standards §5).
  - **Hook path -> fail-open, but detect-and-surface (NOT silent-empty).** The read helper returns a **result object**
    (`enrolled_roots` + a machine-readable `degraded` reason), not a bare list: on corrupt/newer input it returns
    not-enrolled **with `degraded` set** and **never raises**. coding_standards §5 forbids stale recognized state
    degrading into an apparently-valid empty default -- and once T5 lands, a silent-empty registry means every
    user-scope hook is silently off *everywhere*, indistinguishable from "nothing enrolled." The dispatcher ignores the
    flag for its routing decision and never raises (a bounded one-time notice is optional); the **authoritative §5
    surface is `doctor`'s own strict read** (a fresh process re-reads, reports the corruption, and names the reset path)
    -- not the ephemeral hook's in-memory flag.
- [ ] **"Am I inside an enrolled root?"** builds on the *current* root-detection helpers (Phase 0 re-verified:
  `install/installer.py:280`, `core/ops/context.py:106`), not a new walker; the new piece is the trusted-root lookup
  against the canonicalized registry.

Acceptance (Phase 1):

| Test                      | Fixture                                                         | Assertion                                                                                                             | Test File                                          |
| ------------------------- | --------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------- |
| Enroll canonicalizes      | symlinked checkout / moved worktree                             | enrollment stores + looks up the canonical registered root                                                            | `tests/src/install/test_project_registry.py` (new) |
| Case-variant path unifies | enroll `/Users/x/repo`, lookup `/users/x/repo` (case-insens fs) | resolves to the same enrolled root (or documented-unsupported with rationale)                                         | same                                               |
| Relative / trailing slash | enroll `repo`, lookup `repo/` and `./repo`                      | canonicalize to the identical stored root                                                                             | same                                               |
| Registry gates lookup     | enrolled root vs unrelated repo                                 | lookup hits inside the root, misses outside                                                                           | same                                               |
| CLI strict read           | `projects.json` with unknown `schema_version`                   | CLI raises a clear unsupported-version error, no silent default                                                       | same                                               |
| Corrupt registry detected | corrupt/newer `projects.json`, hook read helper                 | helper returns not-enrolled with `degraded` set, never raises; `doctor` strict-read reports it + names the reset path | same (+ doctor test)                               |

## Phase 2 -- Enrollment surface + lifecycle

Both items below assume the D-T3-a outcome (enroll-on-enable + auto-enroll-on-managed-worktree); there is no
explicit-only fork to reframe.

- [ ] **Enroll on enable** via the D-T3-b surface: enabling for a project root adds that canonical root (idempotent -- a
  re-enroll of an already-enrolled canonical root is a no-op, not a duplicate). A `--scope user` global enable enrolls
  nothing by itself (sub-decision above).
- [ ] **Auto-enroll on managed worktree / fork create.** Forge session worktrees are new canonical roots; under T5
  user-scope there is no project hook block to copy into them, so the new root is **enrolled** at create time (derived
  consent) and covered meanwhile by the `FORGE_SESSION` short-circuit -- otherwise a managed session lands unenrolled
  and loses hooks.
- [ ] **`FORGE_SESSION` short-circuit semantics (contract with T4):** a managed session (`FORGE_SESSION` set, reaches
  the hook env at `commands.py:1298`) is treated as active **even if cwd is not enrolled**. Gate logic ships in T4; the
  semantics are pinned here so T4 implements the agreed contract.
- [ ] **Doctor registry section + stale-root primitive:** `forge extension doctor` strict-reads `projects.json`, reports
  corrupt/newer registry state with the reset path, and reports moved or deleted roots. It does not prune/reconcile;
  those actions stay with T5/T6. (Interacts with the canonicalization mechanism: a deleted root cannot be stat'd, so
  lookup must not depend on `samefile` for stale entries.)

Acceptance (Phase 2):

| Test                | Fixture                              | Assertion                                                         | Test File                                    |
| ------------------- | ------------------------------------ | ----------------------------------------------------------------- | -------------------------------------------- |
| Enable enrolls root | project-scope enable at a root       | that canonical root is enrolled; re-enable is an idempotent no-op | `tests/src/install/test_project_registry.py` |
| Worktree enrolls    | `forge session` worktree/fork create | the new worktree root is enrolled (managed session keeps hooks)   | same                                         |
| Stale root reported | registered root now deleted          | `doctor` reports the stale entry (no `samefile`); prune is deferred | same                                         |

## Phase 3 -- Design-doc sync (ship with the code)

- [ ] `design.md` §3.2 contract-files table: add `~/.forge/projects.json` (owner, purpose, versioned durable state).
- [ ] `design_appendix.md`: document the schema, the single canonicalization rule (mechanism + macOS case/Unicode
  handling), and the strict-CLI / fail-open-hook read split (with the detect-and-surface `degraded` contract).
- [ ] **Disambiguate the lookalike files** in the docs: `~/.forge/projects.json` (user-global, machine-written trust
  registry) vs `.forge/project.toml` (repo-local, user-authored compat pin) -- one line so a reader never conflates
  them.
- [ ] **Document the `FORGE_SESSION` short-circuit unconditionally** (not gated on D-T3-a): T4 implements against it
  regardless, so it belongs in the appendix as a standing contract.
- [ ] **User-facing vocabulary:** new enrollment output, doctor registry messages, reset/fix hints, and CLI reference
  text follow the env-var-boundary vocabulary: normal-flow output says "managed session" / `--session`, not
  `FORGE_SESSION`; diagnostic doctor output may name internals only when the variable itself is the diagnosis.
- [ ] `cli_reference.md`: add the enrollment surface chosen in D-T3-b.

## Closeout

- [ ] All Phase 1--3 assertions verified; acceptance tests green.
- [ ] `make pre-commit` clean; **named integration targets:** installer integration for the enable-enroll path
  (`tests/integration/docker/test_installer.py`); session worktree/fork integration if auto-enroll wires into worktree
  create.
- [ ] `change_log.md` entry; durable lessons proposed for `impl_notes.md` (canonicalization mechanism, dual-read
  detect-and-surface posture, JSON-registry house pattern).
- [ ] Epic checklist: tick the T3 lines under "Decisions owed"; update seam-2/seam-3 drift-watch notes.
- [ ] Move `doing/forge_project_registry/ -> done/`; repoint inbound epic/member links.
