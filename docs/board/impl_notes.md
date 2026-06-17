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
- **`ctx` is prior art and inspiration only, never a dependency**: the transfer schema is Forge-owned and canonical
  (design_appendix.md §M.4). [`ctx`](https://github.com/dchu917/ctx) concepts informed it; Forge will not depend on it
  and no interop is planned. The self-contained schema means an optional future bridge would need no schema change.

### Status line: segment registry + Forge-unique segments (shipped)

Shipped 2026-06-03 (statusline-enhancement card). Durable rules for `src/forge/cli/status_line.py` +
`src/forge/cli/statusline/`:

- **Allowlist == producers invariant**: `names.SEGMENT_NAMES` must equal the set of `registry.SEGMENTS` producer names
  (enforced by `test_statusline_registry.py`). Add a segment's name and producer in the SAME change — a name without a
  producer would let `forge config set` accept a field that renders nothing. There are no reserved-but-unimplemented
  names. `forge config set`/`edit` is the strict gate (rejects unknown names/enums); the renderer drops unknown names
  and falls back to `DEFAULT_ORDER` when empty OR when a non-empty config resolves to nothing (never blanks the bar).
- **`DEFAULT_ORDER` is the golden contract**: empty `statusline.segments` reproduces the pre-config bar byte-for-byte
  (`test_statusline_registry.py` golden snapshots). It EXCLUDES `rate_limits` + every opt-in segment.
- **Lazy `RenderContext`**: derivations are `cached_property`, so a segment not in the active set does zero I/O (no
  transcript scan, git subprocess, or proxy-field access). Producers reach `format_*` via `sl.<name>` module-attribute
  lookup — keeps the import direction acyclic (registry/context import `status_line`; `status_line()` imports them
  lazily) and lets tests patch helpers.
- **Palette = output-level ANSI remap**: each role emits a unique code; `apply_palette` is a single-pass regex mapping
  default→themed. `default` palette == empty remap == byte-identical no-op (golden-safe). Glyphs thread ONLY into the
  `get_context_display` progress bar (block chars can't be safely output-remapped). Do not thread a `palette` arg
  through the `format_*` helpers.
- **Billing mode uses RAW `os.environ["ANTHROPIC_API_KEY"]`**, never `resolve_env_or_credential` (which falls back to
  the credential file / honors `auth_ignore_env` and would misclassify an OAuth session as API).
- **Forge-unique segments read EFFECTIVE state** (`apply_overrides(intent, overrides)` on the raw manifest, not raw
  intent) AND honor `policy.enabled` — a disabled policy makes the hook exit early (commands.py:1116), so
  `supervisor`/`policy` show `SUP(off)`/`pol:…(off)`, not active. `drift` must mirror proxy routing precedence: an
  explicit tier in stdin `model.id` (`explicit_tier_from_model`, 1:1 with the proxy's `_tier_from_model_name`) wins over
  `runtime.active_tier`, which is only the proxy `default_tier`. Using `active_tier` alone false-positives a pinned
  session on a different-default proxy.
- **Runtime-only state fails open**: the cache-hit throttle (`statusline/throttle.py`, keyed by
  `sha1(session_id|transcript_path)`) and all transcript/manifest reads degrade to recompute/None on any error — the
  status line must always exit 0. Guard value TYPES at point of use, not just shape at the boundary (a
  structurally-valid cache entry can carry a wrong-typed field).
- **Proxy spend caps**: `_attach_cap_summary` nests `CostTracker.cap_summary()` under `GET / metrics.costs.caps`,
  keeping `ProxyMetrics` decoupled from `CostTracker`. Cap amounts use `_fmt_cap_money` (four decimals below a cent),
  NOT `_fmt_dollars` (whose `int(usd*100)` collapses sub-cent caps to `0c`).

### Codex runtime (codex_frontend epic, shipped 2026-06-12)

Durable invariants for Forge's first alternate agent runtime. Sources: `src/forge/core/runtime/` (registry, preflight),
`src/forge/install/codex_hooks.py`, probe harness `scripts/experiments/codex-hooks/`.

- **Runtime seam = capability half + lifecycle half.** `core/runtime/registry.py` holds the capability matrix
  (`RUNTIMES`/`RuntimeSpec`); the invoker classes (`core/invoker/`) are the lifecycle half over a runtime-neutral
  `ActionContext`. Non-Claude runtimes encode their **limits as capability values** (`pretool_policy="partial"`,
  `native_hooks="enrollment_gated"`, `usage_source="jsonl_events"`), never as omissions — a consumer must never mistake
  a capability gap for parity. Adding a runtime = a new `RUNTIMES` row + an invoker, not scattered `if codex` branches.
- **Codex hooks are enrollment-gated; the `trusted_hash` is not black-box computable.** Stage 83 matched 0/13 harvested
  hashes across 15 canonicalizations, so Forge can never programmatically pre-enroll. The Phase 6 installer
  (`install/codex_hooks.py`) writes a marker-delimited managed TOML block to the Codex config its install scope maps to
  (`user -> $CODEX_HOME/config.toml`; `project`/`local -> <project>/.codex/config.toml`), but **registration is inert
  until the user's one-time interactive `codex` trust ceremony**. Trust keys on the registering config's path + the
  *command-string definition* (not script bytes): it survives `git worktree` checkouts of the enrolled project
  (canonicalization) but does NOT cross to an unrelated repo (stage 84). Rendered entry bytes are golden-pinned so
  sync/update never breaks enrollment. **Malformed PreToolUse hook output FAILS OPEN** (probe 30h) — never rely on Codex
  fail-closing on bad hook output.
- **Codex routes native-direct to OpenAI's Responses API by default; Forge governs at the seams, not the wire.**
  `core/runtime/codex_preflight.py`: no `--proxy` -> `native_direct` (preferred); `--proxy` is rejected unless that
  proxy already serves Responses on its Codex-facing endpoint (Forge adds no `/v1/responses` route). Usage therefore
  comes from `jsonl_events`, not a proxy transcript, and the proxy/cost-routing features stay Claude-side. **Test
  isolation:** codex hook/installer tests MUST use the autouse `isolate_codex_home` fixture (`tests/conftest.py`) or
  they write the real `~/.codex/config.toml` (a real leak caught and fixed in Phase 6 slice 2).

### Supervisor shadow sampling: deferred-audit + detached-worker reliability (shipped 2026-06-14)

Durable invariants for `src/forge/policy/semantic/shadow.py`, `shadow_runner.py`, `policy/semantic/plan_check.py`, and
the `_shadow_handler` in `cli/main.py`. The cascade's blind spot is the **false-aligned** case (a tier-1 `allow` the
frontier would have blocked); shadow sampling replays the frontier on a sampled subset without ever enforcing.

- **Capture/check split**: the frontier supervisor builds its OWN prompt from raw inputs (`raw_diff or new_content`) and
  reloads the plan at run time, so a deferred audit must freeze the **raw** `ActionContext` + a **copied** plan
  (`<hash>.plan.md`) + a routing snapshot — never tier-1's packed prompt text (it is local to `run_plan_check` and gone
  at the seam). Reconstruction fidelity is the locking test: rebuild → identical `SUPERVISOR_PROMPT`.
- **Work-queue reliability boundary is at spawn, not completion**: a handler "succeeds" the instant it `Popen`s and the
  marker is deleted, so the queue's poison cap never sees a detached worker's outcome. Idempotency for detached work
  must be **per-item** (atomic `os.rename` claim → `.processing`), not via the marker. A deterministic post-claim
  failure must **finalize** to a terminal state (`.done` `status="error"`), not stay `.processing` — otherwise it is
  phantom-`pending` forever and leaks a cap slot. Only a hard crash mid-write may orphan.
- **A detached worker outlives its spawner's invariants — re-establish them locally**: it must reset `FORGE_DEPTH=0` (a
  fresh top-level tree; inheriting depth ≥ 2 makes the depth guard skip its frontier call → false errors), and any path
  it replays must resolve the **same** way the consumer resolves it (a relative `plan_override_path` anchors at
  `forge_root`, not CWD — mirror `load_plan_override`, or the plan copy is silently skipped).
- **Count all lifecycle states for cap/dedup**: a content-addressed candidate exists as `.json`/`.processing`/`.done`;
  counting only `*.json` undercounts mid-drain and lets identical content re-capture (over-cap + double billing).
- **Single ledger emitter via `usage_command`**: `run_supervisor_check` is the sole cost/usage emitter; the shadow path
  parameterizes the label (`supervisor-shadow`) instead of re-emitting, so a run is never double-counted.
- **Parse-status flag separates `error` from `inconclusive`**: `parse_supervisor_verdict` collapses empty/unparseable →
  divergent+0.0 (a warn that looks like a real low-confidence verdict). The audit needs
  `parse_supervisor_verdict_with_status`'s `parsed` flag to classify a failed run as `error`, distinct from a genuine
  low-confidence `inconclusive`.
- **Re-root detached spend under the origin session**: snapshot `origin_run_id`/`origin_root_run_id` into the marker at
  enqueue (the Stop hook runs in the session env) and re-root via `_memory_writer_env` at drain; otherwise spend
  attributes to whoever drained the queue. Scrub `FORGE_SESSION` (don't re-inject) to avoid a self-spawning hook loop.

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

### Supervisor launch controls + per-caller reasoning effort (shipped 2026-06-15)

Durable invariants for `supervisor_launch_controls` (#29): launch-time cascade parity for
`forge session fork/start --supervise`, plus a per-caller `--effort` lever on every Forge `claude -p` subprocess.
Sources: `src/forge/core/effort.py`, `core/llm/types.py`, `core/reactive/session_runner.py`,
`policy/semantic/supervisor.py`, `policy/semantic/plan_check.py`, `session/models.py`,
`cli/{session_fork,session_lifecycle,policy,memory}.py`. Each invariant was adversarially verified against the shipped
code (file:line) before promotion.

- **Two effort vocabularies, two validator homes — do not merge them.** Claude `--effort` =
  `{low,medium,high,xhigh,max}` (`validate_claude_effort`, `core/effort.py`); core.llm `ReasoningEffort` =
  `{none,low,medium,high,xhigh}` (`validate_reasoning_effort`, `core/llm/types.py`). `max` is Claude-only; `none` is
  checker-only; a drift-guard test asserts they stay unequal. The Claude validator lives in the dependency-light leaf
  `core/effort.py`, **not** `core/reactive/effort.py`, because `core/reactive/__init__.py` eagerly imports the heavy
  session runner — importing it from the foundational `session/models.py` would re-create an import cycle. So
  `session/models.py` keeps an inline `_CHECKER_EFFORT_LEVELS` mirror (drift-guarded by `test_effort.py`) instead of
  importing the core.llm vocab.
- **`run_claude_session` `--effort` is fail-loud, NOT retry-latch.** It appends `--effort` after `--model`; if an older
  `claude` rejects the flag (`_is_effort_flag_rejection`) the run fails loud with `call_count == 1` — no silent
  rerun-at-default. This is deliberately the opposite of the `--output-format json` telemetry path, which
  retries-once-and-latches (`headless_json.mark_json_output_unsupported`). Rationale: effort changes model behavior, so
  a silent default-rerun would misreport what actually ran.
- **Cascade-at-launch is flag-only — the asymmetry with `policy supervise --cascade` is intentional.**
  `fork`/`start --supervise --cascade` set `cascade=True` only; the runtime hook escalates to the frontier when no
  approved plan exists yet. `forge policy supervise --cascade` instead resolves the approved-plan snapshot eagerly (via
  the `--reload` machinery) and exits 1 if none resolves. Do not "fix" the divergence: launch time legitimately has no
  plan snapshot yet.
- **One Click-free checker-helper source prevents launch/policy drift.** `CHECKER_PROVIDER_CHOICES`,
  `normalize_checker_provider_arg`, `validate_checker_model` (raises `ValueError` containing "prefixed model id"), and
  `apply_checker_options` live in `policy/semantic/supervisor.py` (no Click). `cli/policy.py` and `plan_check.py` import
  them, so launch commands, persistent `policy supervise`, and the tier-1 checker share one validation/normalization
  source. Add new checker controls there, not at each CLI surface.
- **Effort is per-caller by design — no global knob.** Wired per consumer: `SupervisorConfig.supervisor_effort` /
  `.checker_effort`, `MemoryWriterConfig.effort`, `TeamSupervisorConfig.effort`, `run_multi_review(reasoning_effort=)`.
  `checker_effort` feeds `ModelHyperparameters` via `merge_hyperparams` **and** is part of the plan-check throttle cache
  key (a different effort must not reuse a cached verdict). All additive optional `str | None` fields — no
  `SCHEMA_VERSION` bump.
- **Memory-enable early-return must compare effort too (recurring silent-drop shape).** `_set_memory_activation`
  short-circuits only when enabled AND mode AND effort are all unchanged. The bug was short-circuiting on enabled+mode
  alone, silently dropping `forge memory enable --effort high` on an already-enabled, same-mode session. Regression in
  `test_memory.py`. When adding a new persisted activation field, add it to the no-op comparison or it joins this class
  of silent drop.

### Supervisor status-line health: surface fail-open from the usage ledger (shipped 2026-06-16)

Durable invariants for `supervisor_statusline_health` (#30): make a silently fail-open supervisor visible on the
always-on status line (`SUP!N <kind>`) and in `forge activity` (`failing open: N timeout, N error`), reading the outcome
the usage ledger already records. Sources: `src/forge/core/ops/usage_summary.py`, `src/forge/cli/status_line.py`,
`src/forge/cli/statusline/{throttle,context,registry}.py`, `src/forge/cli/activity.py`.

- **Read the ledger, not the decision log — the on-model source.** The supervisor's timeout/subprocess fail-open is
  already in the usage ledger as a non-`success` `UsageEvent.status`/`failure_type` (`emit_usage_for_session_result`).
  Surfacing it needed **no** new durable field. The rejected alternative — a structured `failure_kind` on
  `PolicyDecision` — patches the *accidental* outcome record (the decision log) instead of the real one; it is deferred
  to `upstream_downstream_ledgers` along with the kinds the ledger can't yet see (parse fail-opens logged `success`,
  auth fail-opens that emit no event, and exact cached-allow reset).
- **Two read shapes off one ledger, one kind vocabulary.** `read_supervisor_health` returns the **newest-first
  contiguous fail-open streak** (resets on the first `success`) for the status-line `SUP!N`; `_aggregate_ledger` returns
  the **window total** per kind (`CommandUsage.error_kinds`) for `forge activity`. They are deliberately different
  numbers and the docs say so. Both map `failure_type` through the single `_failure_kind` helper (`timeout` exact,
  everything incl. `None`/subprocess/exit/runtime → `error`) — keep that the only source of the kind mapping or the two
  surfaces drift.
- **Generic data, supervisor-only interpretation.** `CommandUsage.error_kinds` is a generic per-kind split of the
  existing generic `errors` count, populated uniformly for every command in `_aggregate_ledger` (no
  `command == "supervisor"` branch). "Failing open" is applied **only** by the supervisor formatter
  (`format_failing_open`); a memory-writer/panel error is an error, not a fail-open. Non-supervisor rows still carry
  `error_kinds` in `--json` as an honest generic breakdown.
- **`format_failing_open` is gated on `error_kinds`, not `errors` — with an explicit caller fallback.** Real ledger rows
  co-populate both (`_failure_kind(None) == "error"`), so `errors>0 / error_kinds={}` is exclusively a hand-built /
  internal summary. The helper returns `None` there; `render_summary_line` falls back **locally** to the legacy
  `"{errors} errors"` so the count is never silently dropped (regression: `test_errors_only_falls_back_to_count`; the
  three pre-existing hand-built `TestRenderLine` tests stay green unchanged). `forge activity` needs no fallback — its
  commands table already shows the lumped count, so the Supervisor line carries pure breakdown detail.
- **Status-line health stays fail-open + posture-preserving.** The throttled read (`read_or_compute_session_health`,
  same `forge_cost_ttl` window, distinct `fhealth-` cache) degrades a read error to **posture-only** (no suffix), never
  hiding the posture — unlike `forge_cost`, whose whole value is ledger-derived. `SUP!N` attaches to any posture
  (`SUP`/`SUP(susp)`/`SUP(off)`) so suspended/off keeps prior fail-open history visible. `recent_failures==0` is
  byte-identical to today (golden-safe; `supervisor` stays out of `DEFAULT_ORDER`). Frontier-only:
  `command="supervisor"` excludes `supervisor-shadow`/`plan-check`. `forge proxy costs reset` clears `fhealth-*.json`
  alongside `fcost-*.json` so a wiped ledger can't replay cached health.

### OpenRouter provider trace: local lifecycle evidence for aborted streams (shipped 2026-06-16)

Durable invariants for `openrouter_observability`: Forge can explain a timed-out OpenRouter request from local metadata
even when OpenRouter never indexes the cancelled stream.

- **Provider trace is a fourth plane, not a cost-log embellishment.** Cost remains spend truth, audit remains redacted
  body/control evidence, usage remains run/session attribution, and provider trace records provider lifecycle +
  correlation evidence under `~/.forge/providers/openrouter/traces/`. The plane is metadata-only, owner-only, bounded
  like audit, and is intentionally **not** wiped by `forge proxy costs reset`.
- **The shared SSE seam owns lifecycle flags.** The provider metadata carrier is consumed at the converter seam, which
  records stream-start, first user-visible chunk, final usage, and client-disconnect state exactly once through the
  existing `on_complete` path. `CancelledError`/`GeneratorExit` must be caught to mark disconnect and then re-raised;
  the writer remains best-effort so diagnostics never break a successful or already-cancelling request.
- **Synthetic response ids and provider ids are separate namespaces.** Forge may mint OpenAI-compatible `chatcmpl-...`
  ids for downstream clients, but OpenRouter's `gen-...` id lives in optional `ProviderTraceMeta`. Streaming emits
  metadata as soon as the first provider id is seen so a stream killed before final usage still keeps the provider
  generation id.
- **OpenRouter grouping uses `user`, not a custom `session_id`.** Probe evidence showed OpenRouter retains the
  OpenAI-standard `user` field and ignores custom `session_id`. Proxied injection is therefore opt-in per proxy via
  `provider_trace.inject_openrouter_user`, sends only hashed Forge ids, and defaults off. Direct `core.llm` callers are
  a separate card because they need an in-process opt-in owner, not a proxy-owned setting.

### Per-proxy config blocks must be wired through BOTH loader hops (proxy_log_hygiene, shipped 2026-06-16)

A `proxy.yaml` block reaches the running proxy through two independent constructors:
`load_proxy_instance_config_from_dict` (dict -> `ProxyInstanceConfig`) and `_proxy_instance_to_forge_config`
(`ProxyInstanceConfig` -> `ProxyConfig`, which `config.proxy` exposes). Both in `config/loader.py`.

- **Recurring silent-drop bug.** A new block added to the dataclasses but to neither hop loads fine in unit tests of the
  schema yet is silently dropped at runtime — the live proxy sees the default. `provider_trace` shipped with exactly
  this gap (the running proxy never saw a configured block); `logging.requests` would have repeated it. When you add a
  per-proxy config block, grep both hops and pass it through both, or it never reaches `config.proxy`.
- **Regression must cover the live-read path, not just coercion.** Assert the value survives BOTH hops AND is read where
  the server consumes it (e.g. `config.proxy.provider_trace.*`). A schema-only test passes while the runtime drops it.
- **Best-effort telemetry reads tolerate a partial `config.proxy`.** Hot-path and startup reads of telemetry blocks use
  `getattr(config.proxy, "<block>", None)` / a tolerant accessor (`_request_log_config`, `_maybe_prune_*`) and degrade
  to defaults — request logging and prune must never raise into a response path. This is deliberate best-effort
  degradation, distinct from the strict durable-state coercion that rejects malformed blocks at load time.
- **One pruner for all JSONL planes.** `proxy/retention.py::prune_jsonl_shards` (age-then-size, `0` = disable a bound)
  backs the audit, provider-trace, and request planes. New JSONL telemetry planes should delegate to it, not re-copy the
  delete-by-age/oldest-first loop.

### No caller content in proxy logs; redactor excludes caller free-text (proxy_log_hygiene review, 2026-06-16)

The "redacted = sanitized structure, never plaintext" contract binds two surfaces: the redacted JSONL diagnostics/audit
files AND the proxy module logger. Both leaked.

- **The shared `_redact_body_for_log` must never verbatim-copy a caller free-text key.** `stop_sequences` sat in
  `_SAFE_KEYS` (verbatim copy) and leaked arbitrary caller strings onto BOTH the audit and request-diagnostics planes.
  Safe keys are scalars/enums/ids/token-counts only; any field a caller fills with free text (stop_sequences, and watch
  future additions) must go through a structural branch (`{"redacted": True, "count": N}`), never `_SAFE_KEYS`.
- **The SSE converter logger leaked content at DEBUG in ~8 spots.** Per-delta text/tool-args, whole-chunk/`tc_delta`
  WARNING dumps, and the buffered-tool close-event `json.dumps(event_data)` (carried `partial_json` = `Read`'s
  `file_path`). The opt-in `stream_chunks` dump is the ONLY sanctioned raw-content path; every other stream log must be
  metadata (lengths, key-names, indices, token counts, enums, tool names/ids).
- **Hunt log leaks by data provenance, not variable name.** A name-based grep (`{chunk}`, `{args_delta}`) missed
  `json.dumps(event_data)` because the caller content was one indirection away (built event dict -> `partial_json`).
  When auditing a logging surface, trace whether each interpolated value *derives* from caller input, and grep
  `logger.*json.dumps` plus `%s`-style calls, not just known leaky names.

### Proposed Promotions From Metric Evidence (awaiting human review, 2026-06-06)

Drafted by the `metric_evidence_simplification` Phase 6 closeout. **Not yet promoted** — a human should review and move
the durable items into the body above, then delete this section.

- **"Forge is not a cost oracle" — cost-unavailable must be `None`, never `0`.** The original bug was `cost_micros: int`
  - hardcoded `estimated: True`, so `0` meant both "free" and "unknown". Cost is now nullable + provenance-tagged
    (`reporter` + `confidence`); a route reporting no dollars logs `cost_micros=null` / `confidence="unavailable"` and
    does **not** advance spend caps. Never reintroduce a local price table on the accounting path.
- **The two strict-preflight catalog callsites had to die together.** `cap_mode: strict` priced an unsent request from
  the catalog at two sites — `server.py` passthrough **and** translated. Removing only one would have left the catalog
  dependency (and strict semantics) alive on the other path. When deleting a cross-path behavior, the type-checker (not
  a hand list) is the change-detector — grep every call site.
- **One `isinstance(record, dict)` guard for every JSONL cost/usage/audit reader.** A valid-but-non-object line
  (`[]`/`1`/`"x"`) must skip, not crash `.get()`. `cost_tracker.bootstrap_from_logs` is already broad-except guarded
  (its guard is an honesty fix, tested by calling `_parse_record` directly); the other readers genuinely crash without
  it.
- **`billing_mode` ≠ key presence.** The status line must never infer an API payer from `ANTHROPIC_API_KEY` in the env
  (Forge may hydrate it into an OAuth session). `RenderContext.has_api_key` was deleted; `billing_mode` is a declaration
  (`cost_mode`) + `rate_limits` evidence. The interactive/headless key axis is `interactive_anthropic_api_key: omit`,
  distinct from `auth_ignore_env` (source-only, both interactive + headless).
- **Rename the user-facing surface, not the domain plane.** `forge usage` → `forge activity` (it reports Forge
  *automation* activity, not total interactive usage), but the durable **usage ledger** plane (`UsageEvent`,
  `usage/events/`, `read_usage_events`, `usage_summary.py`) keeps its name. Removed CLI commands become hidden,
  **flag-tolerant** tombstones (`ignore_unknown_options` + `UNPROCESSED`) so old `--flag` invocations reach the rename
  message, not Click's "No such option".
