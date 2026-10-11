# Change Log: 2026-08-18

Verbatim archived entries from the project change log.

[Current entries](../change_log.md)

---

## 2026-08-18

### Extract session-fork execution

**Goal/outcome**: Execute a validated fork plan behind one command-core mutation and compensation boundary.

**Key changes**:

- Added a typed execution op for child creation, routing/supervisor persistence, native/transfer/rewind artifacts,
  extension preparation, rollback, and launch-plan assembly; Click now realizes runtimes, renders events, and hands off.
- Made hard pre-launch failures remove owned manifest, index, worktree, branch, and transcript state, with an explicit
  recovery command when cleanup fails; a new test exposed and closed the previously surviving child-branch residue.
- Removed the unreachable proxy re-resolution, deleted mock-manager planner fallbacks, and shared stale-replacement and
  supervisor-proxy planning decisions between read-only preflight and mutation-time rechecks.
- Review hardening closes ready-fallback and partial-factory rewind transcript leaks, removes the dead model-pin module,
  preserves styled warnings, and shares pure launch-preference and prompt-file resolution.

**Verification**: 206 review-focused; 9,299 unit (one skip, 122 deselected); 925 regression; seven targeted Docker
fork/rewind checks; full pre-commit, diff, 29,993/29,966 design, and 368-document/894-link board checks pass. PR #211
merged as `e4a62d1b`; no Forge workflow command was used.

### Extract session-fork preflight

**Goal/outcome**: Refuse deterministic fork failures before child or runtime mutation.

**Key changes**:

- Added a typed, UI-free parent/target/strategy/routing plan; Click renders it and the manager retains race-safe
  revalidation and execution.
- Added durable/Git snapshot fixtures and proxy-start guards across option, parent, budget, routing, and collision
  failures.
- Applied the design §3.9 inherited-budget reference (started proxy ID before intent template), preserved notices on
  later refusal, and deferred unreadable runtime-registry repair to the manager's mutation-time guard.

**Verification**: 306 focused; 9,293 unit (one skip, 122 deselected); 923 regression; seven targeted Docker fork tests;
full pre-commit, diff, 29,979/29,966 design, and 367-document/894-link board checks pass. PR #210 merged as `85c050e2`;
no Forge workflow ran.

### Share passthrough SSE framing

**Goal/outcome**: Remove duplicated incremental SSE framing without collapsing provider-specific usage semantics.

**Key changes**:

- Added one tolerant data/JSON framer for split chunks, no-op lines, `[DONE]`, invalid UTF-8, and malformed JSON, with
  payload-free debug diagnostics.
- Routed the Anthropic and Responses usage taps through it while retaining each transport's event merge, lifecycle,
  normalization, forwarding, teardown, and completion behavior.
- Added direct framing and delegation contracts; both complete transport suites and raw-stream/accounting Docker paths
  pin the seam.

**Verification**: 130 focused plus 88 conversion/accounting tests; 9,263 unit (one skip, 122 deselected); 923
regression; six targeted Docker checks; full pre-commit, diff, 29,961/29,966 design, and 366-document/894-link board
checks pass. PR #209 merged as `a1efd5d7`; no Forge workflow command was used.

### Share transfer and rewind rendering primitives

**Goal/outcome**: Remove copied session-context rendering without collapsing transfer and rewind semantics.

**Key changes**:

- Added neutral trimmed-text, section-framing, and plain/cited bullet primitives with caller-owned labels.
- Routed both document renderers through them while retaining each strategy's envelope, budget, emitted-turn set, and
  citation validation; byte-level transfer, rewind, and rewind-prompt goldens pin the boundary.
- Left O018's separately gated truncated-turn citation defect outside this behavior-preserving member.

**Verification**: 198 focused plus 135 review-fix focused; 9,259 unit (one skip, 122 deselected); 923 regression; one
real rewind Docker test; pre-commit, diff, 29,989/29,966 design, and 365-document/894-link board checks pass. PR #208
merged as `ea5b9103`; no Forge workflow command was used.

### Unify Claude session state-context derivation

**Goal/outcome**: Centralize Claude session state ownership.

**Key changes**:

- One typed context routes start/launch/resume/fork and post-create mutations: recorded `forge_root` owns
  `SessionStore`; worktree/CWD are legacy fallbacks; other behavior stays.

**Verification**: 223 focused; 9,249 unit (one skip, 122 deselected); 923 regression; 69 Docker; pre-commit/diff;
29,989/29,990 design; 364-doc/894-link board. PR #207 merged as `32c6917b` after five checks; no Forge workflow ran.

### Stabilize search-index snapshot fingerprints

**Goal/outcome**: Keep stored search bytes and their persisted transcript fingerprint aligned.

**Key changes**:

- Persisted the extracted fingerprint after incremental/bulk writes; drift retains markers or warns, with deterministic
  regressions and no schema/queue change.

**Verification**: 109 focused; 9,242 unit (one skip, 122 deselected); 923 regression; one Docker Stop/artifact test (12
deselected); pre-commit, diff, and 363-document/894-link board checks pass. No Forge workflow command was used.

### Share review worker preparation

**Goal/outcome**: Remove review worker-preparation drift without hiding consensus and adversarial domain semantics.

**Key changes**:

- Added typed pure helpers for resource marker validation/fill, stable worker IDs and labels, and common
  `model:assignment` parsing.
- Routed consensus and adversarial preparation plus all four optional JSON-metadata sites through shared mechanics while
  retaining distinct routing, fan-out, prompts, wire orders, and result schemas.
- Recorded the ownership boundary in the design while preserving the fresh cached Codex-preflight requirement.

**Verification**: 223 initial and 158 review-fix focused tests, 444 expanded review tests, 9,239 unit tests (one skip),
921 regressions, four targeted Docker workflow-worker tests, full pre-commit, 29,988/29,990 design-document counts, and
the 361-document/882-link board audit pass. PR #206 merged as `242ded2d` with all five GitHub checks passing. No Forge
workflow command was used.

### Centralize tolerant telemetry JSONL reads

**Goal/outcome**: Share telemetry shard/object/timestamp mechanics without collapsing each plane's schema and failure
policy.

**Key changes**:

- Added one sorted, tolerant JSONL object iterator with source-path context and lazy half-open period matching.
- Routed usage, downstream, and upstream reads through it while preserving schema/filter order, warnings, counters,
  merging, sorting, and retention.
- Kept cap bootstrap separate because it prunes shards by filename before opening and deduplicates `downstream_event_id`
  records.

**Verification**: 73 focused tests, 168 expanded telemetry/usage tests, 9,230 unit tests (one skip, 122 deselected), 921
regressions, five targeted Docker cost-visibility tests, full pre-commit, 29,978/29,990 design-document counts, and the
360-document/882-link board audit pass. PR #205 merged as `5c36f25f` with all five GitHub checks passing. No Forge
workflow command was used.

### Reuse Claude usage-measurement resolution

**Goal/outcome**: Remove the workflow aggregate's duplicate proxied-Claude precedence while preserving its event shape
and best-effort behavior.

**Key changes**:

- Routed `emit_verb_usage` through `resolve_claude_p_measurement` for cost, tokens, reporter, confidence, and source.
- Kept unmeasured snapshots authoritative when handed an impossible synthetic cost-evidence flag; production
  `track_verb_cost` still derives both flags from the same delta list.
- Added full aggregate-shape coverage and made the real proxy-panel integration publish and inspect the verb event.

**Verification**: 118 focused tests (891 deselected), 9,222 unit tests (one skip, 122 deselected), 921 regressions, one
targeted Docker proxy-panel test (four deselected), full pre-commit, 29,974/29,990 design-document counts, and the
359-document/882-link board audit pass. PR #204 merged as `356ea665` with all five GitHub checks passing. No Forge
workflow command was used.
