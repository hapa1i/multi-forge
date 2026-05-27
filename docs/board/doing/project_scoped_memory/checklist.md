# Project-Scoped Memory Checklist

Manual multi-session plan for executing [`card.md`](./card.md).

This card is in `doing/` on branch `project-scoped-memory`. Move the whole `project_scoped_memory/` directory to
`docs/board/done/` after closeout (final merge to `main`).

## Maintenance

- Update this file during implementation sessions and once before ending a session.
- Keep tasks high-level, with concrete assertions that prove completion.
- Tick a task only when the assertion is satisfied and verification is recorded.
- Add short blocker notes inline under the relevant phase.
- Move completed-session details to `docs/board/change_log.md`; keep only active plan state here.
- Promote durable lessons to `docs/board/impl_notes.md` after human review.
- Update design docs per-phase as code ships (design docs are normative, not aspirational).
- Move the card directory to `docs/board/done/<slug>/` after the card is fully executed.

```bash
wc -l docs/board/doing/project_scoped_memory/checklist.md
./scripts/count-tokens.py --model <agent-model> docs/board/doing/project_scoped_memory/checklist.md
```

## Current Focus

Slices 1-3 shipped the initial three-layer model. **Slices 4-7** simplified to two primitives (passports + session
activation), removing checkout config (`.forge/memory.yaml`), extras, session doc lists, and multi-flag inheritance. See
`change_log.md` 2026-05-26 "Slices 4-7" entry.

**Remaining: closeout** (`git mv doing/ -> done/` after final merge to `main`).

**Shipped model**: passports select docs (project-scoped, git-tracked frontmatter); `memory.auto_update.enabled` decides
whether the memory writer runs (session-scoped). `--memory on|off` on fork/resume/start. No `.forge/memory.yaml`, no
`designated_docs`, no extras, no `--inherit-extras`.

## Phase 0 - Baseline & Decisions

- [x] Verify the card's load-bearing code references (record file:line).
  - Verification: enqueue gate `src/forge/cli/hooks/commands.py:520` (`effective.memory.auto_update.enabled`); detached
    re-check `src/forge/cli/handoff.py:64` (`store.exists()` no-op) and `:74-79` (`auto_update.enabled`); writer
    selector `src/forge/session/passport.py:681` `check_writer_access`; `MemoryStrategy` enum `:35`;
    `validate_writer_spec` `:641` (rejects `lineage:`/`role:`); incognito read `src/forge/session/shadow_curation.py:70`
    (`list_sessions(include_incognito=False)`). No `memory.yaml` references exist anywhere yet (net-new state).
- [x] Re-confirm the second incognito read the card cites as `memory.py:743`.
  - Verification: citation accurate. `src/forge/cli/memory.py:743` is
    `list_sessions(ctx=ctx, include_incognito=False, scope=scope)` inside `status_cmd` (the `forge memory status`
    command). The card's `memory.py:743` is shorthand for `cli/memory.py:743`; no correction needed. Both incognito
    reads the resolver design relies on exist and pass `include_incognito=False`: `cli/memory.py:743` (status) and
    `session/shadow_curation.py:70` (curation).
- [x] Anchor Phase 1 test sites.
  - Verification:
    - **Enqueue gate** (`commands.py:520`) -> `tests/src/cli/test_artifact_hooks.py::TestStopHook` (asserts
      `queued is True` at `:147`, marker file exists at `:160`). Covers the positive path; resolver swap must keep it
      green and add a "project-enabled, session-silent" case.
    - **run_cmd gate** (`handoff.py:64` `store.exists()` no-op, `:74-79` `enabled` check) -> NO existing coverage.
      `tests/src/cli/test_handoff.py` holds only two proxy-resolution tests
      (`test_handoff_run_uses_manifest_subprocess_proxy`, `test_handoff_run_prefers_marker_subprocess_proxy_snapshot`).
      The Slice-1 "run_cmd gate uses resolver" and "run_cmd union/dedup" rows are **net-new tests**, not extensions.
    - **Writer selection** -> `tests/src/session/test_handoff_agent.py::TestWriterFiltering` (existing, unchanged --
      `run_handoff_agent` is not modified).
- [x] Settle the two Slice-1 gating decisions (the rest defer to Phase 2/Open Decisions).
  - Decision (a) **Scan roots**: always scan `.forge/memory/` + a configurable doc-tree root list (default `["docs/"]`,
    overridable via a `roots:` key in `.forge/memory.yaml`). `roots:` REPLACES the doc-tree default; `.forge/memory/` is
    always unioned in and cannot be configured away -- shadows are written there unconditionally (`derive_shadow_path`
    hardcodes `.forge/memory/suggested_*.md`, `passport.py:180`), so dropping it would silently orphan shadow-propose
    docs. Walk recursively within roots; exclude `.git/`, `node_modules/`, etc. `track` warns when a passported doc
    falls outside the effective roots.
  - Decision (b) **Bare `enable`**: project-scoped always; ignores ambient `$FORGE_SESSION`. `--session X` keeps the
    current session-scoped behavior (sparse override via leaf keys `memory.auto_update.*`, `cli/memory.py:179-216`).
    This is a behavior change: today bare `enable` resolves the ambient session (`enable_cmd` -> `resolve_session` at
    `cli/memory.py:179`). Print a notice when bare `enable` runs with `$FORGE_SESSION` set; add a change_log entry + a
    regression test pinning the `--session` path as still session-scoped.
  - Decision (c) **Incognito** (already decided by the card, recorded for completeness): resolver returns `None` for
    `is_incognito` sessions.
  - Deferred OUT of Slice 1: **worktree activation copy** on `fork --worktree` and the **uncommitted-passport warning**
    are fork-path concerns (`session_fork.py`, `memory_inheritance.py`) with no Slice-1 acceptance coverage. Auto-copy
    by default also reverses the card's "inherits committed passports, but not the enable bit" consent model, so it
    needs explicit sign-off rather than a quiet default. Slice-1 default stays: a new checkout requires
    `forge memory enable`. Revisit later as an opt-in (e.g. `fork --worktree --copy-activation`).

> **Note:** Phases 1-3 (Slices 1-3) were superseded by Slices 4-7 (two-primitive simplification). Retained for
> historical context. See Current Focus above for the shipped model.

## Phase 1 - Slice 1: Project Activation + Shared Gate (additive, no schema break)

- [x] Add versioned project-scoped `<forge_root>/.forge/memory.yaml`.
  - Assertion: modeled on strict durable-state readers -- `SessionStore` (`store.py:40` `_SUPPORTED_SCHEMA_VERSIONS`,
    `:262-269` raises `ManifestCorruptedError` on unsupported version) and the session index (`index.py:109-116`,
    "Delete this file and retry"). NOT `runtime_config.py`, which is intentionally optional/fail-open/unversioned and
    ignores unknown keys -- the wrong precedent for Forge-owned durable state. Mandatory `version`, strict
    deserialization, clear unsupported-version error (coding-standards §5). Holds operational state only
    (`auto_update: {enabled, mode, min_turns, proxy}`); no `docs:` list.
  - Shipped: `ProjectMemoryConfig`/`ProjectAutoUpdateConfig` + `read/write_project_memory_config` in
    `src/forge/session/project_memory.py`; `ProjectMemoryConfigError` in `exceptions.py`.
- [x] Implement the shared resolver `memory_activation(session, project) -> ActivationConfig | None`.
  - Assertion: project config plus a *sparse field-wise* session override; returns `None` for `is_incognito` sessions.
  - Implementation note: derive the session override from a tri-state source -- raw `intent`/`overrides` leaf-key
    presence (overrides are persisted per-leaf-key, e.g. `memory.auto_update.enabled`, `memory.py:208`). Do NOT read
    `compute_effective_intent()`: it materializes `HandoffConfig` defaults (`models.py:95-99`: `enabled=False`,
    `mode="augment"`, `min_turns=5`), collapsing "unset" into "explicit false/default". Both gates currently consume the
    materialized config (`handoff.py:69`, `memory.py:187`); the resolver must not.
  - Shipped: `memory_activation()` reads the raw `overrides` dict via `_get_override_leaf` (sparse, can disable) and
    overlays `intent.memory.auto_update` as a whole block only when `enabled is True` (legacy; default `False` = unset).
- [x] Wire the resolver into **both** gates.
  - Assertion: the enqueue gate (`commands.py:520`) and the detached `run_cmd` (`handoff.py:74-79`) both call the single
    resolver. Load-bearing: if the hook does not enqueue, the runner never runs, so a project enable is inert unless
    both sites consult it.
  - Test note (Phase 0 finding): the run-side gate has NO existing coverage, so the `run_cmd` rows are net-new, not
    extensions. Pin current behavior first -- add the negative case (activation resolves to `None`/disabled -> `run_cmd`
    no-ops, `run_handoff_agent` not called) before the positive project-enabled case, so the gate cannot regress to
    always-open during the resolver swap.
  - Shipped: enqueue gate uses `memory_activation(...) is not None` (best-effort try/except, debug-log when forge_root
    None); `run_cmd` builds `HandoffConfig` from `ActivationConfig`; proxy-routing chain preserved (both legacy proxy
    tests green).
- [x] Stop discovery = scan + select.
  - Assertion: a session-layer discovery helper scans bounded memory roots for `forge_memory` frontmatter (unit-testable
    in isolation); `run_cmd` unions it with session `designated_docs` and de-dupes by passport source / write path at
    `handoff.py:97` (today `designated_docs = effective.memory.designated_docs`, passed to `run_handoff_agent` at
    `:106`). `run_handoff_agent` is unchanged -- selection stays via `check_writer_access` (already covered by
    `TestWriterFiltering` in `tests/src/session/test_handoff_agent.py`).
  - Shipped: `scan_passported_docs()`; `run_cmd` unions + de-dupes by `(resolve_passport_source(d), d.path)`, session
    docs win on collision.
- [x] Bound the scan.
  - Assertion: walk only configured roots (default `docs/`, `.forge/memory/`); never `.git/`, `node_modules/`, etc.
  - Shipped: roots validated via `is_safe_designated_doc_path`; always unions `.forge/memory/`; skips
    `.git/`/`node_modules/`/`__pycache__/`/`.venv/`/`.forge/sessions|artifacts`; deterministic sort; cap 50 after
    filtering.
- [x] `forge memory enable` (no `--session`) writes `.forge/memory.yaml`.
  - Assertion: `--review-only` sets review mode for the safe first run; consent output names the checkout; project-level
    enable removes the need for per-session enable/re-track for passported docs in this checkout.
  - Shipped: `_enable_project_scoped` writes the project config; mode-change preserves `roots`/`proxy`/`min_turns`.
- [x] Pin `enable` session-vs-project semantics (behavior change, not purely additive).
  - Assertion: `enable --session X` stays session-scoped (writes the sparse override via leaf keys
    `memory.auto_update.*`, current behavior at `memory.py:179-216`). Bare `enable` writes project config and does NOT
    consult ambient `$FORGE_SESSION` (mirrors the bare-`track` rule). This shifts the meaning of in-session bare
    `enable` (today it targets the ambient session) -- call it out in the change_log. Regression test the `--session`
    path stays session-scoped.
  - Shipped: `_enable_session_scoped` keeps the override path; bare prints a `Tip:` when `$FORGE_SESSION` is set;
    change_log entry added (2026-05-24).
- [x] Design docs: update `design.md §5.6` and `design_appendix.md §G`.
  - Assertion: ownership is stated as passport (doc contract) vs project activation (checkout consent) vs session
    override (sparse). Reflects shipped Slice-1 behavior, not the full card target.
  - Shipped: `design.md §5.6.6` (project-scoped activation) and `design_appendix.md §G.5` (config schema + resolver
    merge table).

Acceptance tests (Slice 1):

| Test                         | Fixture                                    | Assertion                                            | Test File                              |
| ---------------------------- | ------------------------------------------ | ---------------------------------------------------- | -------------------------------------- |
| resolver project-only        | project `memory.yaml`, session silent      | returns project `ActivationConfig`                   | `session/test_project_memory.py`       |
| resolver sparse override     | project enabled, session `mode=review`     | merged; unset fields inherit project                 | `session/test_project_memory.py`       |
| resolver unset vs false      | raw override `enabled` unset vs false      | distinguishes (tri-state, pre-materialize)           | `session/test_project_memory.py`       |
| resolver incognito           | `is_incognito` session                     | returns `None` (no enqueue)                          | `session/test_project_memory.py`       |
| discovery helper             | 2 in-root passports, 1 out-of-root         | only in-root passports returned                      | `session/test_project_memory.py`       |
| scan bounding                | repo with `.git/`, `node_modules/`         | excluded from walk                                   | `session/test_project_memory.py`       |
| run_cmd union/dedup          | scanned passports + session `designated`   | passes ∪, de-duped, into `run_handoff_agent`         | `cli/test_handoff.py`                  |
| enqueue gate uses resolver   | project-enabled, session silent            | Stop hook enqueues handoff marker                    | `test_artifact_hooks.py::TestStopHook` |
| run_cmd gate uses resolver   | project-enabled, session silent            | `run_cmd` proceeds (not gated out)                   | `cli/test_handoff.py`                  |
| run_cmd gate None -> no-op   | activation `None`/disabled, session silent | `run_cmd` returns early; no `run_handoff_agent` call | `cli/test_handoff.py`                  |
| enable writes project config | bare `enable`, no `--session`              | `.forge/memory.yaml` v1 written                      | `cli/test_memory.py`                   |
| enable --session scoped      | `enable --session X`                       | writes session override, not project file            | `cli/test_memory.py`                   |
| bare enable ignores ambient  | `$FORGE_SESSION` set, bare `enable`        | writes project, not the ambient session              | `cli/test_memory.py`                   |
| unsupported version          | `memory.yaml` `version: 999`               | clear error, no silent default                       | `cli/test_memory.py`                   |

## Phase 2 - Slice 2: Sessionless `track` + participation-only `extra add`

Verb taxonomy this slice locks in: **`track`** = make a doc project memory by writing a passport (project-lifetime,
git-tracked); **`extra add`** = include a doc for this session only (session-lifetime, no passport); **`enable`** = turn
the runner on for this checkout/session. Each verb owns exactly one lifetime.

- [x] `track_cmd` becomes passport-only (stateless).
  - Assertion: drop the participation write (`_write_docs` / `memory.designated_docs` override at `memory.py:70-78`) and
    the `_auto_enable_memory` call; stop calling `resolve_session` / `_current_docs`. Validate the path against
    `ctx.forge_root` (as `passport_show_cmd` does, `memory.py:1348`). Warn when the doc is outside the effective scan
    roots (`.forge/memory.yaml` `roots:` ∪ always-on `.forge/memory/`). `--propose`/`--shadow` still write the
    shadow-only passport, but no participation.
- [x] Bare `track` never consults the ambient session.
  - Assertion: `forge memory track <doc>` is passport-only even when `$FORGE_SESSION` is set (mirrors bare `enable`; no
    invisible ambient-session behavior).
- [x] New `forge memory extra add <doc> --as <strategy> [--session <name>]` (participation-only escape hatch).
  - Assertion: writes ONLY `memory.designated_docs` (reuse `_write_docs`); never calls
    `synthesize_passport`/`write_passport`/`resolve_with_overrides`. `--as` is REQUIRED — it is the `resolve_doc_spec`
    fallback strategy for passport-less docs (`handoff_agent.py:431`). Resolves ambient `$FORGE_SESSION` when
    `--session` is omitted and ECHOES the resolved session; errors (via `resolve_session`) outside a session with no
    `--session`. Drops `--intent`/`--writers`/`--propose`/`--shadow`.
- [x] `extra add` warns by reading the target's passport + `writers` (three-way; case B folded in).
  - Assertion (A, redundant): passport present AND under a scan root AND `check_writer_access` authorizes the session ->
    warn "already project-discovered for this session; no extra needed."
  - Assertion (B, passport vetoes): passport present AND `writers` EXCLUDES the session -> warn "passport restricts
    writers to `<spec>`; an extra is filtered at Stop (`handoff_agent.py:404`) — edit the passport's writers instead."
    Independent of scan-root membership: `:404` filters on the passport regardless of how the doc entered the set.
  - Assertion (C, allow silent): no passport anywhere, OR passported+authorizing but out-of-root -> record the entry
    with no warning (genuine session-only state, e.g. `docs/scratch.md`).
  - Invariant to assert + document: an `extra` cannot grant write access a passport denies (passport is authoritative
    for `writers` whether the doc arrives via scan or `designated_docs`).
- [x] `_check_legacy_docs` stops scolding intentional extras.
  - Mechanism: add an optional provenance field to `DesignatedDoc` (`models.py:103`) —
    `origin: Literal["extra"] | None = None` (named `origin`, not `source`: `resolve_passport_source` returns a path and
    `shadows` is the official source doc, so "source" is already taken). `extra add` sets `origin="extra"`; legacy
    manifest entries and scan results (`project_memory.py:303,315`) keep `None`. Persist it by adding
    `"origin": d.origin` to the `_write_docs` payload (`memory.py:72`); strict dacite reads pre-Slice-2 manifests fine
    (missing key -> default `None`). Preserve `origin` through `--inherit-memory` fork copy (the manifest copy path has
    dropped memory fields before; do not regress).
  - Assertion: `_check_legacy_docs` (`memory.py:81-112`) skips entries with `origin == "extra"`; an `origin is None`
    entry with no passport still warns. Update the warning's remediation text — it currently names the REMOVED
    `track ... --session` spelling (`memory.py:104-106`); point it at `forge memory track <path> --as <strategy>`
    (passport-ize, project-level) or `forge memory extra add <path> --as <strategy>` (re-add as session-only).
- [x] Authoring no longer requires a session.
  - Assertion: `track` succeeds from a bare terminal; the removed `track --session` participation coupling fails
    helpfully (names `extra add`) per coding-standards §5 clean break + changelog entry.
- [x] Docs: rewrite `docs/board/README.md` "Handoff Agent Setup" + "Advanced Workflow" to passport-once +
  per-checkout-enable (the card's Worked Example); update `design.md §5.6` with the verb taxonomy and the "extra cannot
  override passport writers" invariant.

Acceptance tests (Slice 2):

| Test                        | Fixture                                         | Assertion                                              | Test File                       |
| --------------------------- | ----------------------------------------------- | ------------------------------------------------------ | ------------------------------- |
| track passport-only         | doc w/o passport, `--as changelog`              | passport written, NO `designated_docs` override        | `cli/test_memory.py`            |
| track ignores ambient       | `$FORGE_SESSION` set, bare `track`              | passport only, no participation write                  | `cli/test_memory.py`            |
| track warns out-of-root     | doc outside effective roots                     | warning emitted; passport still written                | `cli/test_memory.py`            |
| extra passport-less (C)     | `docs/scratch.md --as generic`, no passport     | `designated_docs` entry, no passport write, no warning | `cli/test_memory.py`            |
| extra written at Stop       | passport-less designated entry, file exists     | `run_handoff_agent` includes it via `doc.strategy`     | `session/test_handoff_agent.py` |
| extra requires `--as`       | `extra add <doc>` with no `--as`                | fails with strategy guidance                           | `cli/test_memory.py`            |
| extra ambient echo          | `$FORGE_SESSION=planner`, no `--session`        | resolves planner, prints the resolved session          | `cli/test_memory.py`            |
| extra case A (redundant)    | passported, under root, `all-sessions`          | warns "already project-discovered for this session"    | `cli/test_memory.py`            |
| extra case B (excluded)     | passport `writers: planner`, session `executor` | warns "passport restricts writers"                     | `cli/test_memory.py`            |
| legacy warning skips extras | extra entry (`origin="extra"`), no passport     | no "re-track to attach passports" warning              | `cli/test_memory.py`            |
| legacy still warns          | legacy entry (`origin=None`), no passport       | warning still emitted; remediation names the new verbs | `cli/test_memory.py`            |

## Phase 3 - Slice 3: Fork activation copy + retire `--inherit-memory`

Thesis: memory inheritance is no longer a thing. Project memory is discovered live from passports; activation follows
Forge-created worktrees; only session extras can be inherited.

### Fork activation copy

- [x] Copy `.forge/memory.yaml` into the new checkout on `fork --worktree` by default.
  - Assertion: when source `.forge/memory.yaml` exists and destination does not, the file is copied after the worktree
    is created. Print one dim line: `Copied memory activation to <path>`. No prompt.
  - Shipped: `project_memory.py:156-186` (`copy_memory_activation()`), called from `manager.py:1176-1183`.
- [x] `fork --into` does NOT copy activation.
  - Assertion: target checkout already exists and may have its own local consent; no implicit copy. Consistent with
    `--into` rules in `design.md` (target must already have Forge enabled).
  - Shipped: `manager.py:1176` guards on `not is_into`.
- [x] Never overwrite an existing destination `.forge/memory.yaml`.
  - Assertion: if destination file exists, skip copy silently. The destination checkout's activation is authoritative.
  - Shipped: `project_memory.py:171-173` early return if dest exists.
- [x] `--no-copy-memory-activation` opt-out flag on `fork --worktree`.
  - Assertion: flag suppresses the copy; child checkout starts with no memory activation. Flag is a no-op when source
    config does not exist.
  - Shipped: `session_fork.py:167-172` (flag definition), threaded to `manager.fork_session()`.
- [x] Corrupt source config: warn and skip copy (do not block the fork).
  - Assertion: `ProjectMemoryConfigError` during read -> warning printed, fork proceeds without activation copy.
  - Shipped: `project_memory.py:175-178` catches error, returns result with warning; `manager.py:1180-1181` appends
    warning non-blocking.

### Retire `--inherit-memory`

- [x] Replace `--inherit-memory all|none|shadowed` with `--inherit-extras` / `--no-inherit-extras` on both `fork` and
  `resume --fresh`.
  - Assertion: default inherits extras (`origin="extra"` entries in `designated_docs`). `--no-inherit-extras` strips
    session extras from the child. Project-discovered docs (passport-scanned) are not affected by this flag -- they are
    discovered live in the child checkout.
  - Shipped: `session_fork.py:162-166` + `session_lifecycle.py:1411-1415` (flags); `memory_inheritance.py:62-63` (extras
    filter).
- [x] Simplify `memory_inheritance.py`: remove `InheritMemoryMode` enum and the `all|none|shadowed` branching.
  - Assertion: `filter_docs_for_inheritance` and `apply_memory_inheritance` reduce to extras-only logic. Shadow
    materialization (`materialize_inherited_shadows`) is removed -- shadows are passport-discovered in the child
    checkout, not carried by manifest.
  - Shipped: `InheritMemoryMode` enum removed; `apply_memory_inheritance()` is binary (`inherit_extras: bool`).
- [x] `--inherit-memory` becomes a helpful tombstone (coding-standards §5).
  - Assertion: errors with actionable replacement guidance per value:
    - `all`: "No longer needed; passports are discovered from the project. Use --inherit-extras if you meant session
      extras."
    - `none`: "Use --no-inherit-extras and --no-copy-memory-activation."
    - `shadowed`: "Shadow docs are passport-discovered; use 'forge memory track --propose'."
  - Shipped: `session_fork.py:221-233` + `session_lifecycle.py:1461-1473` (hidden option, per-value error messages).
- [x] `resume --fresh`: same `--inherit-extras` / `--no-inherit-extras` semantics.
  - Assertion: `session_lifecycle.py` resume path uses the same extras-only inheritance as fork. `--inherit-memory`
    tombstone applies here too.
  - Shipped: `session_lifecycle.py:1411-1415` (flags), passed through to `manager.resume_session()`.
- [x] `designated_docs` retained as extras backing store only.
  - Assertion: decision recorded. `designated_docs` is the *only* per-session participation surface; it no longer
    carries project-discovered docs or participates in inheritance of passport-scanned memory.
  - Shipped: `memory_inheritance.py:62-63` filters to `origin="extra"` only; project docs are passport-discovered at
    Stop time.

### Passport removal path

- [x] Add `forge memory passport remove`.
  - Shipped: sessionless passport removal (`passport remove <path>`) removes only the `forge_memory` frontmatter key,
    preserves unrelated frontmatter/body content, no-ops when no passport exists, and leaves `.forge/memory.yaml` plus
    session extras untouched. `untrack` remains session-participation-only and points users to `passport remove` when a
    passported doc remains project-discovered.

### Docs and design sync

- [x] Update `design.md §5.6.4` (memory inheritance on fork and fresh resume).
  - Assertion: reflects the new model -- activation copy for Forge-created worktrees, extras-only inheritance. No
    `--inherit-memory`. `--into` exception documented.
  - Shipped: `design.md:1651-1667` documents activation copy rules, extras-only inheritance, `--into` exception.
- [x] Update `docs/end-user/handoff.md` fork/resume memory sections.
  - Shipped: new "Memory on fork and resume" section with activation copy and extras inheritance guidance.
- [x] Changelog entry with goal/key changes/verification.
  - Shipped: `change_log.md` 2026-05-26 entry.

Acceptance tests (Slice 3):

| Test                                        | Fixture                              | Assertion                            | Test File                                        |
| ------------------------------------------- | ------------------------------------ | ------------------------------------ | ------------------------------------------------ |
| activation helper copies config             | source `.forge/memory.yaml`, no dest | dest file written; copied path       | `session/test_project_memory.py`                 |
| activation helper skips existing dest       | source + dest both exist             | dest unchanged, no warning           | `session/test_project_memory.py`                 |
| activation helper corrupt source            | corrupt `.forge/memory.yaml`         | warning returned, no dest            | `session/test_project_memory.py`                 |
| worktree fork `--no-copy-memory-activation` | source present, flag set             | no dest file created                 | **coverage gap**                                 |
| `--into` no activation copy                 | source present, `--into` target      | no copy attempted                    | **coverage gap**                                 |
| `--inherit-extras` default                  | parent with `origin="extra"` docs    | child has extras                     | `session/test_memory_inheritance.py`             |
| `--no-inherit-extras` strips extras         | parent with extras, flag set         | child `designated_docs` empty        | `session/test_memory_inheritance.py`             |
| `--no-inherit-extras` ignores project docs  | non-extra/passported docs            | project docs are not manifest-copied | `session/test_memory_inheritance.py`             |
| `--inherit-memory` tombstone `all`          | `--inherit-memory all`               | error with replacement guidance      | `session/test_memory_inheritance.py`             |
| `--inherit-memory` tombstone `none`         | `--inherit-memory none`              | error with replacement guidance      | `session/test_memory_inheritance.py`             |
| `--inherit-memory` tombstone `shadowed`     | `--inherit-memory shadowed`          | error with replacement guidance      | `session/test_memory_inheritance.py`             |
| resume `--inherit-extras`                   | `resume --fresh` with extras         | child has extras                     | core coverage via inheritance helper             |
| resume `--no-inherit-extras`                | `resume --fresh` with extras, flag   | child `designated_docs` empty        | core coverage via inheritance helper             |
| passport remove preserves frontmatter       | doc with passport + unrelated YAML   | only `forge_memory` removed          | `session/test_passport.py`, `cli/test_memory.py` |

## Open Decisions

Tracks Forge-local execution decisions. For broader card framing, see
[`card.md` Open questions](./card.md#open-questions).

- [x] Scan roots default + config mechanism (`docs/` + `.forge/memory/`; project-config key vs fixed convention)? --
  SETTLED (Phase 0 decision a): always-on `.forge/memory/` + configurable doc-tree roots (default `["docs/"]`) via a
  `roots:` key in `.forge/memory.yaml`.
- [x] Keep `writers: all-sessions` as the synthesized default, or default to a more conservative writer to bound blast
  radius? -- SETTLED: keep `all-sessions` (already the synthesized default; no code change). The blast-radius gate is
  local activation + `--review-only` + `min_turns`, not a per-doc named writer.
- [x] Exact CLI spelling that replaces `track --session` for manifest-only extras? -- SETTLED:
  `forge memory extra add <doc> --as <strategy> [--session <name>]`. Participation-only (writes
  `memory.designated_docs`, never a passport); `--as` required; resolves+echoes ambient `$FORGE_SESSION`; three-way
  warning keyed on the passport's `writers` (cases A/B/C in Phase 2). Rejected `track --session --extra` because it
  re-conflates the two lifetimes the slice splits apart.
- [x] `fork --worktree`: copy the local `.forge/memory.yaml`, or only warn that the new checkout needs
  `forge memory enable`? -- SETTLED (Slice 3): copy by default for Forge-created worktrees (`fork --worktree`); skip for
  `--into` (existing checkout, own consent). Never overwrite existing dest. `--no-copy-memory-activation` opt-out. The
  consent surface is "I am using Forge to create a child worktree from this active checkout."
- [x] Deprecate `--inherit-memory` for doc participation once git carries passports; warn on uncommitted passports
  before a worktree fork? -- SETTLED (Slice 3): retire `--inherit-memory` entirely. Replace with narrower
  `--inherit-extras` / `--no-inherit-extras` (extras only, not project memory). Old values become helpful tombstones.
  Uncommitted passport warning deferred (orthogonal to inheritance retirement).

## Closeout (per [work-board contract](../../../developer/work-board-contract.md#closeout))

- [x] Final compact `change_log.md` entry with verification.
- [x] Promote durable lessons to `impl_notes.md` after human review.
- [x] Verify `design.md §5.6`, `design_appendix.md §G`, and `docs/board/README.md` reflect all shipped changes.
- [x] Create `docs/board/todo/memory_substrate/card.md` (intermediate card).
- [x] Update `docs/board/todo/runtime_abstraction/card.md` to reference memory substrate.
- [ ] `git mv` the card directory `doing/ -> done/` after final merge to `main`.
