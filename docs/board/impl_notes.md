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
  marker is deleted, so the queue's poison cap never sees a detached worker's outcome. Idempotency for detached work must
  be **per-item** (atomic `os.rename` claim → `.processing`), not via the marker. A deterministic post-claim failure must
  **finalize** to a terminal state (`.done` `status="error"`), not stay `.processing` — otherwise it is phantom-`pending`
  forever and leaks a cap slot. Only a hard crash mid-write may orphan.
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
