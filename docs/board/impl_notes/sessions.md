# Implementation Notes: Sessions

Durable session, transcript, transfer, memory, and Codex-session decisions.

[Implementation-notes index](../impl_notes.md)

---

## Notes

### Binding a pre-existing conversation is a uniqueness problem, not a write problem (native_session_adoption, shipped 2026-07-27)

- **A lock only excludes what it encloses.** Uniqueness needs its guard at the narrowest scope covering *every* writer.
  The index write lock is the only lock shared across session names, so a cross-session id must live in the index row --
  but that is not sufficient on its own. Adoption holds a global per-conversation `flock` across its final scan and
  commit, with the index column as the second line. A pre-check plus a later write under a *different* lock is not
  exclusion at any ordering. (When this shipped, the gap was that creation wrote the manifest first, so a killed create
  owned a conversation without ever reaching the index. `session_create_crash_atomicity` closed that ordering in
  2026-08-01; the `flock` stays, because pre-existing orphans persist and the exclusion argument never depended on the
  write order.)
- **Session names are project-scoped, so a bare name is never an identity key.** This recurs: an unscoped rollback
  `remove_session` resolved by name prefix across projects, and a manifest-read dedup keyed on name let another
  project's session hide this project's orphan binding. Key on `(resolved forge_root, name)`, or scope the lookup.
- **A swallowed read is not an absent record.** Binding and uniqueness lookups must fail closed on *every* source they
  consult, not just the first. A skipped corrupt manifest reports exactly what an unbound conversation reports, so the
  degradation is invisible at the decision point that matters.
- **Validate a caller-supplied path component before joining it, never after.** `Path(base) / "/abs"` silently discards
  `base`. This bit three times here; the worst case aliased an artifact copy onto its own source, so rollback unlinked
  the user's native transcript.
- **Adoption inverts transcript ownership.** For a session Forge launched, the transcript is Forge's to delete; for an
  adopted one it is the user's. Deletion paths must exempt it -- including the automatic retention sweep that runs on
  CLI startup, not just an explicit `session delete`.

### Transcript role/turn parsing is single-sourced in `core/transcript.py` (test_mirror_and_contract_cleanup, shipped 2026-07-06)

- The four primitives -- `normalize_transcript_role`, `resolve_entry_role`, `extract_entry_blocks`,
  `group_entries_into_turns` -- are public in `core/transcript.py` and are the only home for transcript role/turn
  parsing. `session/transfer.py` (curation) and `session/rewind.py` consume them; `cli/statusline/sources.py` uses
  `resolve_entry_role` for its role counts. New consumers must reuse these, not reimplement locally.
- **Recurring-bug cause:** a divergent local copy in `status_line` had dropped the `human`/`ai` role-alias
  normalization, so those entries were miscounted (raw/`None` instead of `user`/`assistant`). Bypassing the shared
  primitive silently re-opens this class of miscount. Guard:
  `tests/regression/test_bug_statusline_transcript_role_alias.py`.
- **Facade vs shim (module moves):** keep a package `__init__` re-export that lets callers import a stable name while
  the implementation moves (a *facade* -- `forge.sidecar` still re-exports `get_secrets_for_template` from
  `core/auth/template_secrets`); delete a module that exists only to forward (a *shim* -- `sidecar/secrets.py`) and
  repoint callers. Clean break, no compatibility layer.

### Rewind resume: fresh-UUID truncated head + code-delta (shipped 2026-07-02)

Durable invariants for `--strategy rewind --drop-last N` (`session/rewind.py`, `cli/session_rewind.py`,
`cli/session_resume_modes.py`). Rewind resumes turns `1..(T-N)` as *real* relocated Claude history plus an AI code-delta
of the dropped window `(T-N)..T`.

- **`claude --resume <R> --fork-session` tolerates stem `<R>` != the transcript's embedded `sessionId` -- no envelope
  rewrite needed** (live-pinned, Claude Code 2.1.197, `parent_has_signature=yes`). This is the load-bearing empirical
  fact with **zero in-tree precedent** (`relocate_transcript` always produced `<uuid>.jsonl` where stem == embedded
  sessionId). It lets rewind write the truncated head under a fresh UUID while leaving the parent's embedded `sessionId`
  and signed `thinking`/`tool_result` blocks byte-intact. Re-pin with the slow real-Claude gate if a future
  codex-cli/claude version changes resume lookup. The in-tree gate is
  `tests/integration/docker/test_rewind_native_contract.py`: it covers the full truncated clean-prefix `<R>.jsonl`
  rewind shape, not just the original whole-copy stem probe.
- **Fresh rewind-owned UUID `<R>` makes cleanup unshared by construction -- no reference counting.** The truncated head
  is written as `<R>.jsonl` and tracked by a **distinct** `Derivation.rewind_relocated_session_id` (not
  `relocated_parent_session_id`, which byte-for-byte native-relocate uses for the *parent* UUID). Because `<R>` is
  unique to this child, the delete-time unlink branch keys only on `<R>` and is dir-scoped to the child's Claude project
  root, so same-dir resume rewind can **never** touch the parent's original transcript. Keep the two GC ids separate.
- **Turn-space cut vs raw-line prefix -- the contiguity guard fails closed.** Turns group by `requestId` in first-seen
  order (`_group_entries_into_turns`), but the writer emits a raw-LINE prefix while computing the boundary in TURN
  space. `_assert_kept_turns_form_raw_prefix` raises when the two coordinate systems disagree (interleaved requestIds
  would pull a dropped turn's lines into the kept prefix), forcing degrade-to-plain-native-relocate. Real-Claude
  transcripts are append-contiguous, so this guards malformed/unexpected input, not the normal path.
- **Rewind deliberately breaks `native-relocate => no context file` -- and that "invariant" was a convention, not a
  guard.** No code asserted `strategy null <=> native`. When extending native-relocate, branch on
  `resume_mode == "native-relocate"` + explicit `strategy`, never on "context_file is None => native". Additive
  `dropped_turns` + `rewind_relocated_session_id` on `Derivation` needed **no `SCHEMA_VERSION` bump** (strict dacite
  fills missing optionals; precedent: consumer_lanes T4).
- **Landmine for a future editor**: `session_fork.py`'s `uses_fresh_transfer` computes `True` for a rewind worktree fork
  (`(is_worktree_fork and not native_relocate) or same_dir_transfer`, where `native_relocate` excludes rewind). Rewind
  is handled by its own `elif rewind_active:` branch *before* that matters today, but anyone refactoring the fork
  launch-path branching must keep rewind out of the transfer-derivation-persistence path or it will double-write
  `strategy`.

### Memory System Architecture (shipped)

Two primitives: passports select docs (project-scoped, git-tracked frontmatter); session activation decides whether the
memory writer runs (`memory.auto_update.enabled`). No checkout-level config, no session-scoped doc lists.

- **Passports are the sole doc source**: `forge_memory` YAML frontmatter in docs declares strategy, writers, intent. The
  detached runner's `scan_passported_docs()` discovers them under hardcoded roots (`docs/` + `.forge/memory/`) when it
  executes; the Stop hook only enqueues the marker. No manifest doc lists; `DesignatedDoc` is a runtime-only type for
  the scanner -> memory-writer pipeline.
- **Session activation**: `forge session memory enable/disable --session` or `--memory on|off` at start/fork/resume.
  Both gates (Stop hook, detached runner) check `effective.memory.auto_update.enabled` directly. Incognito never
  enqueues.
- **Namespace (Slice 02, forge_cli_cleanup)**: the session-scoped activation/report verbs live under
  `forge session memory` (`enable`/`disable`/`status`/`report`, the last flattened from `forge memory report show`).
  This is now a **real** group, not a tombstone — the earlier hidden `forge session memory` tombstone is gone. Top-level
  `forge memory` keeps the project-doc passport verbs (`track`/`list`/`passport`/`shadows`). The verb modules live in
  `cli/session_memory.py` (+ the flattened `report` from `cli/memory_report.py`); both subgroups are wired onto the
  `session` group in `cli/main.py` (not `session.py`) because `transfer.py`/`session_memory.py` import `console` from
  `session.py`, so parent-imports-child would cycle.
- **Deferred chain**: stop hook -> work queue marker -> fire-and-forget `forge memory-writer run` -> passport scan ->
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

- **Memory writer** — deferred project-doc curation: `session/memory_writer.py` (`run_memory_writer`,
  `resolve_writer_base_url`, `memory_report_dir`), `MemoryWriterConfig`, `memory_writer_timeout`,
  `forge memory-writer run`, `forge session memory report`.
- **Transfer** — resume/fork context assembly: `session/transfer.py` (`assemble_transfer_context`, `TransferResult`),
  `--resume-mode transfer`.
- **3-layer memory taxonomy** (design.md §5.6): raw memory (`.forge/artifacts/`), project memory (passported docs under
  `docs/`, `.forge/memory/`), transfer memory (`.forge/prev_sessions/`).

**Intentional KEEPs — do NOT rename these to memory-writer/transfer; they are durable state, routing keys, or
fixtures:** work-queue marker `kind="handoff"` + `enqueue_handoff_marker()` (ephemeral routing key); the
`.forge/artifacts/<session>/handoff/` artifact path (kept even though `review_dir()` became `memory_report_dir()` — see
the intentional-mismatch comment in `memory_writer.py`); the `queued_handoff` Stop-hook JSON field; QA fixture filenames
(`manual-handoff-*.jsonl`); and the industry-English "design-to-code handoff" in the skills-writing guide.

**CLI tombstone reclamation (Slice 02):** the report command now lives at `forge session memory report` (flattened leaf
in the new `cli/session_memory.py` group). It earlier sat at `forge memory report show` only because a tombstone group
occupied `forge session memory`; Slice 02 removed that tombstone and reclaimed the path for the real session-scoped
memory group (`enable`/`disable`/`status`/`report`), wired onto `session` in `cli/main.py`. Durable lesson: before
renaming a CLI surface, check whether the target path is already a (possibly hidden) tombstone group.

**Durable-value rename pattern (resume_mode):** `confirmed.derivation.resume_mode` migrated `"handoff"` → `"transfer"`
via accept-and-tolerate, not reject — readers map legacy `"handoff"`/`None` to transfer with no branching; writers emit
`"transfer"`. Regression: `tests/regression/test_bug_resume_mode_rename.py`.

### Curated transfer: schema + three-file artifact model (runtime_abstraction Phase 1)

Shipped 2026-05-31 (commit `2b70c29`). Durable invariants for `src/forge/session/transfer.py` and
`src/forge/session/prev_sessions.py`:

- **Three-file artifact model** under `<forge_root>/.forge/prev_sessions/<parent>/`: `generated.md` (regeneratable
  parent cache), `children/<child>.md` (frozen AI snapshot, schema sections 1-7), `children/<child>.notes.md` (user
  overlay, section 8). `forge session transfer regenerate` rewrites only `generated.md`; `ensure_child` never overwrites
  an existing child; GC ties a notes file's liveness to its snapshot (never orphaned independently).
- **Child-agnostic frontmatter (load-bearing)**: the transfer frontmatter carries no `child` field, so `generated.md`
  and the copied `children/<child>.md` stay byte-identical. `ensure_child` and the auto-name retry byte-compare in
  `manager.py` both depend on this — do not add per-child fields to the frontmatter.
- **Citation honesty**: `schema: "full"` is stamped only for a successful ai-curated body; every other strategy or
  fallback is `"compatibility-fallback"`. `_validate_decision_citations()` drops any citation outside the `[turn N]`
  range the model actually saw (keeps the decision text, blanks false provenance), so `schema: full` never overstates
  evidence quality.
- **Namespace**: `forge session transfer` is a **session-scoped** group (Slice 02 of forge_cli_cleanup moved it under
  `forge session`; it pairs with the `forge session memory` activation verbs), distinct from top-level `forge memory`
  (project-doc passports). `forge session resume --fresh --review` is a delegating entry point that edits the
  `.notes.md` overlay, not a competing namespace. `forge session transfer show` (assembled artifact) is distinct from
  `forge session show`'s context view (`forge session context` was removed in the CLI cleanup; its `--field`/`--json`
  behavior folded into `session show`).
- **`target_runtime`** is reserved in the frontmatter (`TRANSFER_TARGET_RUNTIME = "claude"`) for Phase 5 cross-runtime
  tuning: Phase 5 retargets presentation without changing transcript source artifacts or schema semantics.
- **`ctx` is prior art and inspiration only, never a dependency**: the transfer schema is Forge-owned and canonical
  (design_sessions.md §H.4). [`ctx`](https://github.com/dchu917/ctx) concepts informed it; Forge will not depend on it
  and no interop is planned. The self-contained schema means an optional future bridge would need no schema change.

### Codex runtime (codex_frontend epic, shipped 2026-06-12)

Durable invariants for Forge's first alternate agent runtime. Sources: `src/forge/core/runtime/` (registry, preflight),
`src/forge/install/codex_hooks.py`, probe harness `scripts/experiments/codex-hooks/`.

- **Runtime seam = capability half + lifecycle half.** `core/runtime/registry.py` holds the capability matrix
  (`RUNTIMES`/`RuntimeSpec`); the invoker classes (`core/invoker/`) are the lifecycle half over a runtime-neutral
  `ActionContext`. Non-Claude runtimes encode their **limits as capability values** (`pretool_policy="partial"`,
  `native_hooks="enrollment_gated"`, `usage_source="jsonl_events"`), never as omissions — a consumer must never mistake
  a capability gap for parity. Adding a runtime = a new `RUNTIMES` row + an invoker, not scattered `if codex` branches.
- **Codex hooks are user-scope-only and enrollment-gated; the `trusted_hash` is not black-box computable.** Stage 83
  matched 0/13 harvested hashes across 15 canonicalizations, so Forge cannot programmatically pre-enroll. The installer
  writes its marker-delimited runtime-hook block only to `$CODEX_HOME/config.toml`; project/local extension installs
  write no Codex runtime block, and explicit project/local `--with codex-hooks` is rejected. Per-project managed blocks
  are legacy migration inputs, not a supported installation target. Registration remains inert until the user's one-time
  interactive `codex` trust ceremony; `forge runtime preflight codex --verify-enrollment` verifies firing empirically
  after enrollment. Rendered entry bytes are golden-pinned because trust covers the config location and command-string
  definition (not dispatcher script bytes). **Malformed PreToolUse hook output FAILS OPEN** (probe 30h) — never rely on
  Codex fail-closing on bad hook output.
- **Native Codex uses OpenAI's Responses API; proxy mode uses Forge-owned passthrough routes.**
  `core/runtime/codex_preflight.py`: no `--proxy` -> `native_direct` (preferred); `--proxy` requires the full Responses
  capability conjunction. Forge registers `POST /v1/responses` plus the method-aware `/v1/responses/{rest:path}` surface
  in `proxy/responses_ingress.py`, capability-gates it, and relays raw Responses traffic through
  `proxy/responses_passthrough.py` without chat translation. The generation route also owns spend-cap, cost/usage, and
  provider-lifecycle accounting; native-direct usage still comes from Codex `jsonl_events`. **Test isolation:** Codex
  hook/installer tests MUST use the autouse `isolate_codex_home` fixture (`tests/conftest.py`) or they write the real
  `~/.codex/config.toml` (a real leak caught and fixed in Phase 6 slice 2).

### Same-directory transfer forks: decouple transfer mode from worktree isolation (shipped 2026-06-15)

Durable invariants for `forge session fork` after `same_dir_transfer_forks` (#28). A same-dir fork is native by default;
an explicit `--resume-mode transfer` (or explicit `--strategy`/`--inline-plan` that auto-switch it) routes the existing
worktree-transfer machinery into the same checkout. Sources: `src/forge/cli/session_fork.py`,
`src/forge/cli/session_lifecycle.py`, `src/forge/session/manager.py`. Invariants adversarially verified against the
shipped code before promotion.

- **Fork derivation is written twice — baseline + best-effort refinement, not a clobber.** `manager.fork_session`
  pre-records a baseline `Derivation` (`resume_mode` + `context_file` set, `strategy=None`); the CLI
  `_persist_fork_transfer_derivation` then refines it per-field (a `SessionStore.update` `_mutate`), overriding
  `resume_mode`/`context_file` and being the ONLY writer of a real `strategy` for a fork. That CLI step is gated to
  transfer forks (`elif uses_fresh_transfer`) and best-effort (try/except swallows failures), so a refinement failure
  degrades to the correct `strategy=None` baseline instead of losing transfer intent — which is exactly why the manager
  pre-records at all. Scope caveat: "only writer of `strategy`" is fork-specific; `resume_session` records `strategy` on
  its own non-fork resume/transfer path.
- **`_get_deferred_same_dir_fork_resume_id` must stay `derivation.resume_mode`-aware, or it re-natives deferred transfer
  forks.** Fork creation never pre-seeds `claude_session_id` (launch-owned), so a `--no-launch` same-dir transfer fork
  has no UUID to short-circuit on. The resolver returns `None` when `confirmed.derivation.resume_mode == "transfer"`;
  without that guard it falls through to `return parent.confirmed.claude_session_id` and relaunches the child as
  `--resume --fork-session` of the parent, silently discarding the recorded transfer. Correctness depends on
  `resume_mode` being persisted at fork-creation (the manager baseline). For a same-dir fork the value is only ever
  `native` or `transfer` — `native-relocate` requires a worktree and is filtered earlier.
- **fork and resume `--resume-mode` are different value sets — do not conflate.** fork's `--resume-mode` is a
  `click.Choice(["transfer", "native-relocate"])`; resume's is NOT a Choice — it is `default=None` plus a
  `_validate_resume_mode` callback accepting `{"native", "transfer"}`. Both default to `None`; resume's `None` resolves
  to `transfer` behaviorally. `native-relocate` is fork/worktree-only; `native` is resume-only.
- **Auto-switch is one pre-fork assignment, not scattered special-casing.** Explicit `--strategy`/`--inline-plan` on a
  same-dir fork is detected via `ParameterSource.COMMANDLINE` (never truthiness — so the `structured` default never
  trips it) and resolves `resume_mode = "transfer"` exactly once, gated on `not is_cross_dir and resume_mode is None`
  (so an explicit `--resume-mode native-relocate` never auto-switches). Because it is set before `manager.fork_session`,
  every downstream site (the `--strategy full` budget gate, the manager call, the `same_dir_transfer` launch flag, the
  no-launch resume tip) keys uniformly on `resume_mode == "transfer"`. When extending this path, branch on
  `resume_mode == "transfer"`, never on re-reading the flags.
