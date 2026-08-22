# Change Log

Completed-work record for Forge implementation sessions.

Older entries are retained verbatim in [2026-08-05 through 2026-08-14](archive/change_log_2026-08-05_to_2026-08-14.md)
and [through 2026-08-04](archive/change_log_through_2026-08-04.md).

## 2026-08-22

### Correct recent review regressions

**Goal/outcome**: Close five independently reproduced regressions in recent session, hook, authority, configuration, and
repository-policy changes without weakening the surrounding ownership, read-only, or latency contracts.

**Key changes**:

- Revalidated relocated-transcript ownership at the destructive unlink boundary and translated malformed active-registry
  reads into actionable, non-repairing authority errors.
- Redacted diagnostics before and after terminal rendering, kept ordinary streams on the bulk C0/DEL path, and preserved
  failure-excerpt semantics and the Stop overhead budget.
- Emitted extension-sync reminders only when config edit/reset changed invocation overrides, and narrowed the
  40,000-token historical exception to the two ratified checklist snapshots.

**Verification**: 171 focused tests before review and 66 focused Stop/hook tests after review; four required targeted
Docker boundaries, with the Stop boundary rerun after final remediation; 9,588 unit tests with 117 deselected; 1,067
regressions; full pre-commit, diff, board, and link checks. A 1.01 MB control-free diagnostic measured 29.5 ms median
(36.6 ms for full excerpt selection). PR #239 merged as `60af6b66` with all five GitHub checks passing.

### Put context limits and document ownership in the repository

**Goal/outcome**: Make context-size enforcement visible to contributors and leave every living context document with
room to grow, without shortening the design contracts or historical evidence that exceeded the old limits.

**Key changes**:

- Added a tracked file-size policy, family-tagged Opus-first counting, conservative local screens, and a batched
  pre-commit gate whose provider use and thresholds are repository-owned. Near-target provider evidence is cached by
  exact content hash so keyless CI and keyful contributors reach the same verdict; missing evidence fails visibly.
- Partitioned the core architecture, workflow memory, changelog, implementation notes, and whole-repository review by
  stable domains; all appendix links now target their canonical owners and the retired appendix path is gone.
- Added a repository-wide Markdown path-and-fragment audit and changed contributor context loading to route through the
  overview, active card, and implementation-note index before selecting only relevant domain documents.
- Preserved all 142 original design headings, 985 non-navigation paragraphs, 52 fenced examples, 26 changelog blocks, 46
  implementation-note sections, and 11 review sections under a recorded lossless-migration audit.

**Verification**: 108 focused policy/link tests; 9,583 unit tests with 117 deselected; 1,057 regressions; all 566
tracked Markdown sources pass the link audit; the all-files size gate passes in 3.2 seconds; full pre-commit and diff
checks pass. The 20 living/context documents measured with `claude-opus-5` are below 25,000 tokens, and all migrated
canonical design documents are at or below the 23,000-token migration target.

### Validate artifact authority through real runtimes

**Goal/outcome**: Close the shipped authority feature's real-model gap by proving its production launch, hook, denial,
and journal chain inside disposable Docker identities.

**Key changes**:

- Versioned the runtime test image by both installed Claude Code and Codex CLI versions and installed both real runtimes
  in the cached toolchain layer.
- Added paid release tests for a real Claude advisory denial, its producer control, and a real Codex advisory denial;
  each uses the public session CLI and asserts filesystem plus correlated journal evidence instead of model prose.
- Recreated only Codex's non-secret hook trust hashes at their original absolute paths; no host config was mutated and
  no `auth.json` was copied.
- Synchronized the bundled QA image identity, isolated the installer's no-Codex boundary, bounded hung runtime
  processes, and moved paid credentials from process arguments into atomic owner-only stdin writes.

**Verification**: Three real-model Docker cases; 437 non-slow integration tests with 10,615 deselected plus 13
current-head canonical Docker-helper cases; 207 focused authority tests; 9,447 unit with 117 deselected; 1,057
regression; full pre-commit, diff, and 1,227-link checks. PR #235 merged as `8e47f017` with all five GitHub checks
passing; the card closed to `done/` on 2026-08-22.

## 2026-08-21

### Enforce managed-session artifact authority

**Goal/outcome**: Give humans an explicit advisory/producer session designation with honest managed-tool enforcement and
local evidence, while leaving route provenance, authorship, and admission outside the claim.

**Key changes**:

- Added strict session-owned authority intent, external inactive mutation controls, advisory-only inheritance, and one
  authority-neutral durable event-journal seam reusable by later route provenance.
- Preflighted and journaled one root launch attempt across Claude and Codex, enforced advisory requests before ordinary
  policy, preserved producer/unmarked behavior, and exposed a read-only posture report plus the human-courier workflow.
- Closed review-found enforcement gaps with exact Codex policy-row attestation, full-lifetime unmarked launch locking,
  sidecar authority-row exclusion, marker isolation, and event-specific journal validation.

**Verification**: 212 repaired authority-contract tests; 9,447 unit with 117 deselected; 1,053 regression; eight
targeted Docker and CLI integration boundaries; full pre-commit; wheel/sdist build plus isolated packaged enable/sync;
dispatcher p95 26.79 ms across 50 runs with 40 registry entries at depth 5. The design-size gate was intentionally
deferred. PR #234 merged as `a1c54a05` with all five GitHub checks passing; M1 closed to `done/` on 2026-08-22.

### Remove the experimental manifest WorkflowPolicy

**Goal/outcome**: Retire the stale CLI-graduation proposal and remove a hidden semantic-policy pipeline whose blocking
reviewer had no repository or other normative project authority.

**Key changes**:

- Deleted the manifest-only workflow package and behavior tests, then made unknown bundles and configuration owners fail
  atomic engine construction with override-aware recovery for stale `workflow` state.
- Preserved the documented shared reactive library, removed the caller-less reverse bundle lookup, and synchronized the
  policy design, end-user, and repository-agent contracts.

**Verification**: 574 focused policy/reactive/CLI tests; 9,302 unit with 117 deselected; 1,053 regression; one targeted
Docker policy-hook boundary; both policy-check content modes; pre-commit/diff, board/link, and design-size gates. PR
#233 merged as `4f95d88d` with all five GitHub checks passing.

### Close Wave 8 Batch 5 and the repository maintenance round

**Goal/outcome**: Close the final verified residuals and leave the whole-repository review with terminal dispositions
without treating the separately proposed D040 design choice as accepted work.

**Key changes**:

- Removed every unexplained production type suppression, retained concrete reasons on the unavoidable remainder, and
  added a source guard against recurrence.
- Synchronized the conditional sidecar runtime-config mount, auth/workflow CLI inventory, and consensus precedence
  comment, then closed Wave 8 at 23 findings across 19 members and the parent maintenance round.

**Verification**: 446 focused suppression/touched-module tests; 203 focused auth/workflow documentation tests; 60 PR
review follow-up tests; 9,332 unit with 124 deselected; 1,059 regression; three targeted integration boundaries;
pre-commit/diff, board/link, and document-size gates. PR #230 merged as `7e5ea8c4` with all five GitHub checks passing.

### Close daily-review regressions

**Goal/outcome**: Keep provider traces, workflow integer controls, and Stop failure diagnostics aligned with their
shipped contracts at local setup and terminal-control edge cases.

**Key changes**:

- Moved provider-attempt signaling after local credential/client setup and rejected booleans in all manifest integer
  controls before workflow evaluation.
- Sanitized terminal controls before pytest-summary selection, including line-bounded OSC/DCS strings and decoded C1
  controls.

**Verification**: 249 focused tests; targeted proxy, policy-hook, and Stop Docker boundaries; 9,331 unit with 124
deselected; 1,059 regression; pre-commit/diff, board/link, and design-size gates. PR #229 merged as `da34bcb3` with all
five GitHub checks passing.

### Close Wave 8 Batch 4 isolated runtime fixes

**Goal/outcome**: Reject invalid proxy-audit limits, expose best-effort info-probe degradation, and avoid repeated
transcript-reference scans during native-relocate cleanup.

**Key changes**:

- Rejected zero and negative audit limits before shard or period reads while preserving positive/default ordering.
- Added secret-safe debug evidence and uniform `uv_version` fallback for failed info probes, and resolved ordinary,
  artifact, and relocated-parent transcript ownership in one shared scan.

**Verification**: 165 focused card tests; three targeted Docker boundaries; 9,331 unit with 124 deselected; 1,035
regression; pre-commit/diff and board/link gates. PR #228 merged as `559a3453` with all five GitHub checks passing.

### Close Wave 8 Batch 3 policy CLI contracts

**Goal/outcome**: Make missing supervisor prerequisites and ambiguous policy-check inputs fail explicitly while sharing
one policy-bundle vocabulary across terminal and direct-command parsing.

**Key changes**:

- Returned non-zero stderr diagnostics for enabling supervisor actions without configured state while preserving
  idempotent teardown commands.
- Rejected simultaneous policy-check file and diff sources before either read, and replaced three residual bundle
  literals with the shared registries without changing unknown-token behavior.

**Verification**: 370 focused card tests; three direct container-boundary policy checks; 9,331 unit with 124 deselected;
1,015 regression; pre-commit/diff and board/link gates. PR #227 merged as `f3353042` with all five GitHub checks
passing.

## 2026-08-20

### Close Wave 8 Batch 2 telemetry reads

**Goal/outcome**: Make cost-breakdown selection unambiguous and proxy-metrics JSON byte-safe with one stable bare shape.

**Key changes**:

- Rejected conflicting cost selectors before telemetry reads and counted unique joined Forge run IDs separately from
  downstream request rows.
- Bypassed terminal rendering for metrics JSON and kept the bare zero/one/many-proxy result as one proxy-ID mapping.

**Verification**: 97 focused CLI/regression tests; 9,331 unit with 124 deselected; 1,005 regression; targeted
cost-visibility and live proxy-health Docker boundaries; pre-commit/diff and board/link gates. PR #226 merged as
`5f02bb0f` with all five GitHub checks passing.

### Close Wave 8 Batch 1 correctness fixes

**Goal/outcome**: Make cleanup failures truthful, lazy LLM client initialization singular, and failed Stop diagnostics
retain the useful pytest summary.

**Key changes**:

- Reported scoped active-registry cleanup failures while continuing later removals and counting only confirmed work.
- Serialized concurrent LiteLLM/OpenRouter cold starts and closed a custom-CA transport when construction fails.
- Selected redacted pytest short-summary failures across mixed streams without captured ERROR logs displacing node IDs.

**Verification**: 101 focused GC/CLI, 211 focused LLM/auth, 22 focused Stop, four no-`.env` credential, and one targeted
Docker test; 9,331 unit with 124 deselected; 992 regression; pre-commit/diff and board/link gates. PR #225 merged as
`fd548c8e` with all five GitHub checks passing.

### Preserve assistant block boundaries

**Goal/outcome**: Keep standalone completion promises recognizable across separate assistant text blocks without
creating false matches across block boundaries.

**Key changes**:

- Applied one shared boundary-preserving join to both supported Claude transcript projections.
- Retained single-block and existing-newline behavior while pinning later-block promises, split-block false positives,
  and the real Stop-hook path.

**Verification**: 77 focused tests including 14 O087 regressions; 9,328 unit with zero skips; 983 regression; two
targeted Docker Stop-hook checks; pre-commit/diff; design-size and board-link checks. PR #224 merged as `4727deaa` with
all five GitHub checks passing.

### Reject unknown workflow-policy keys

**Goal/outcome**: Stop manifest-backed workflow policy typos from silently selecting permissive defaults.

**Key changes**:

- Strictly deserialized workflow entries and nested stages, with actionable entry and field diagnostics at the existing
  atomic hook-build boundary.
- Documented the build-failure blast radius, aligned config-shape tests with production strictness, and parked the
  analogous TDD unknown-key gap as O101 instead of expanding this member.

**Verification**: 128 focused plus 25 review-follow-up tests; 9,328 unit; 969 regression; two targeted Docker policy
hook checks; pre-commit/diff; design and board checks. PR #223 merged as `92d71a6d` with all five GitHub checks passing.

### Correct Wave 8 merged regressions

**Goal/outcome**: Restore the provider-trace, worktree-copy, and dry-run stream contracts after three independently
reproduced post-merge regressions.

**Key changes**:

- Moved provider-attempt marking to the adapter's actual dispatch seam for both request modes while retaining failed
  dispatch and auth-retry traces.
- Rechecked worktree destination safety after Git I/O and before copying, and kept conflict-bearing dry-run previews on
  stdout with only the terminating diagnostic on stderr.

**Verification**: 72 direct plus 57 adjacent focused tests; 9,328 unit; 964 regression; four targeted Docker checks;
pre-commit/diff; design/appendix 59,979 combined; board 402 documents/975 links. PR #222 merged as `02e0ced9` with all
five GitHub checks passing; no Forge workflow ran.

### Eliminate runtime test skips

**Goal/outcome**: Make the unit suite pass or fail cleanly instead of conditionally skipping credential-template and
filesystem-identity coverage.

**Key changes**:

- Parameterized every local-template credential expectation and replaced symlink guards with one actionable fixture.
- Exercised alias and distinct-root semantics deterministically in the registry and rendered dispatcher, with a
  repository-wide AST guard against runtime skip constructs.

**Verification**: 119 focused with zero skips; 9,326 unit with zero skips and 124 deselected; 961 regression;
pre-commit/diff; design/appendix 59,979 combined; board 400 documents/972 links. PR #221 merged as `9d6deb7f`; no Forge
workflow ran.

### Unify CLI failure diagnostics

**Goal/outcome**: Keep every line of one terminating human CLI diagnostic on stderr without changing successful or JSON
output.

**Key changes**:

- Routed workflow preflight details, extension failure plans/recovery, and policy supervisor input tips through the
  diagnostic console.
- Buffered extension auto-scope and anchor-creation notices until the outcome was known, preserving first-enable success
  order while keeping non-zero paths stderr-only.

**Verification**: 239 focused plus 153 post-review stream/order checks; 9,322 unit (one skip); 959 regression; six
targeted Docker workflow/extension checks; clean-wheel runtime; pre-commit/diff; design/appendix 59,979 combined; board
972 links. PR #220 merged as `61be7d80`; no Forge workflow ran.

### Harden worktree config-copy safety

**Goal/outcome**: Keep tracked and user-owned config safe during worktree copy and dirty-worktree cleanup.

**Key changes**:

- Replaced directory-level ownership assumptions with per-file copy and cleanup decisions while preserving exact-file
  behavior and dirty-retry ordering.
- Rejected symlinked directory components before discovery, writes, unlink, and pruning; excluded nested repository
  metadata and dependency trees without widening cleanup authority.

**Verification**: 39 focused; 9,318 unit (one skip); 955 regression; 35 targeted Docker worktree/session checks;
pre-commit/diff; design 29,991/29,988; board 970 links. PR #219 merged as `43a3b29c`; no Forge workflow ran.

### Strip OpenAI account response headers

**Goal/outcome**: Keep upstream OpenAI account identity from crossing the shared proxy response boundary.

**Key changes**:

- Added organization/project selectors to the shared case-insensitive response denylist while retaining safe provider
  metadata, connection-token filtering, and Forge's canonical request ID.
- Pinned the shared policy plus Messages, Responses, and packaged proxy behavior, and recorded the re-enumeration
  requirement for future providers and wire shapes.

**Verification**: 135 focused; 9,312 unit (one skip); 944 regression; eight Docker proxy-routing checks;
pre-commit/diff; design 29,991/29,988; board 968 links. PR #218 merged as `4cd859cb`; no Forge workflow ran.

### Offload proxy accounting persistence

**Goal/outcome**: Keep proxy completion responsive while cost, lifecycle, and cap evidence reaches durable storage.

**Key changes**:

- Moved detached cost/provider-lifecycle records and coalesced cap snapshots through one FIFO worker while keeping live
  accounting synchronous.
- Retained failed cap checkpoints for runtime or shutdown retry, removed the test-only cost writer, and recorded the
  audit and overload-policy boundaries.

**Verification**: 828 original focused plus 203 review-remediation checks; 9,312 unit (one skip); 942 regression; seven
Docker proxy/telemetry/cap checks (one workflow case deselected); pre-commit/diff; design 29,986/29,976; board 967
links. PR #217 merged as `6b2e0129`; no Forge workflow ran.

## 2026-08-19

### Trace failed provider attempts

**Goal/outcome**: Preserve provider lifecycle evidence when an upstream attempt fails before normal completion.

**Key changes**:

- Joined failed Messages and Responses traces to their downstream cost event while keeping local pre-dispatch failures
  trace-free.
- Distinguished pre-open failures from received non-200 streams so trace explanations retain observed status, cost, and
  stream facts.

**Verification**: 108 focused plus 10 CLI; 9,309 unit (one skip); 936 regression; six Docker proxy/telemetry checks;
pre-commit/diff; design 29,990/29,979; board 965 links. PR #216 merged as `634ff40e`; no Forge workflow ran.

### Correct fork transfer snapshot rollback

**Goal/outcome**: Keep a failed transfer fork from leaving stale immutable child context for a same-name retry.

**Key changes**:

- Tracked only the exact child snapshot created by the current preparation attempt, including write-then-raise
  factories, and removed it after successful child/session compensation.
- Preserved pre-existing snapshots and the parent cache; cleanup failures now name the retained path and recovery
  action.

**Verification**: 104 focused; 9,309 unit (one skip, 122 deselected); 929 regression; six Docker fork-lifecycle checks;
pre-commit/diff; design 29,990; board 393 docs/965 links. PR #215 merged as `7736d0d0`; no Forge workflow ran.

### Admit Wave 8 verified residual maintenance

**Goal/outcome**: Convert only evidence-backed post-Wave-7 residue into bounded parked work.

**Key changes**:

- Rechecked the gated ledger on `bad273ef`; admitted 23 findings as 19 members, kept D040 proposed, rejected O078/O079
  as bugs, and recorded resolved or narrowed scopes.
- Sequenced proxy observability/I/O, security, tracked-content safety, CLI/state, test-policy, and docs boundaries
  without activating implementation.

**Verification**: Rich JSON failure reproduced; full pre-commit and diff check passed; 391 board docs/959 local links
resolve; 19 unique members/23 unique findings; no Forge workflow ran.

### Close Wave 7

**Goal/outcome**: Put status-line presentation below the entrypoint and close Wave 7.

**Key changes**:

- Moved formatting/layout below the command with public helpers and `fmt`; command is 130 lines/two definitions with no
  upward imports.
- Removed ineffective caches/empty parameters, retained caching, and closed the 32-finding/35-member admission without
  absorbing gated work.

**Verification**: 357 focused; 9,309 unit (one skip, 122 deselected); 925 regression; 17 Docker; pre-commit/diff; design
29,993/29,970; board 371 docs/894 links. PR #214 (`4c9dee34`) passed five checks; no Forge workflow ran.

### Extract status-line source facts

**Goal/outcome**: Put status-line sources below the command.

**Key changes**:

- Moved neutral types and fail-open proxy/transcript/session/Git acquisition to `statusline`; consumers use it directly.
- Deferred rendering and caches to order 35.

**Verification**: 348 focused; 9,304 unit (1 skip, 122 deselected); 925 regression; 17 Docker; pre-commit/diff; design
29,993/29,956; board 370 docs/894 links. PR #213 merged as `e761d0d1`; no Forge workflow ran.

### Decompose the extension install transaction

**Goal/outcome**: Make the extension install transaction reviewable by phase without changing mutation or rollback
semantics.

**Key changes**:

- Split the apply path into typed setup, cache, file, settings, stale-reconciliation, Codex, assembly, and tracking
  phases; conflict return remains before mutation and tracking remains the final write.
- Replaced namespace-specific target-root patches with one environment-backed fixture and proved installer, legacy
  path-policy fallback, and runtime removal resolve the same root.
- Recorded the phase/fault matrix and install ownership order while preserving stale deletion, settings/Codex rollback,
  runtime preservation, and disable behavior.

**Verification**: 829 installer tests (one skip); 9,303 unit (one skip, 122 deselected); 925 regression; 23 targeted
Docker installer/runtime-skill lifecycle checks; build, clean-wheel smoke, full pre-commit, diff, 29,985/29,984 design,
and 369-document/894-link board checks pass. PR #212 merged as `f1afb30c`; no Forge workflow command was used.

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

## 2026-08-17

### Unify resume routing-reference resolution

**Goal/outcome**: Replace three drifted fresh-resume routing calculations with the existing shared reference rule while
preserving context-budget and launch behavior.

**Key changes**:

- Routed transfer, native, and rewind fresh-resume context-limit lookup through `_resume_context_ref`.
- Preserved explicit and inherited proxy-ID precedence, template fallback for legacy or injected routing, and
  direct-mode null routing.
- Added precedence regressions plus a structural guard against restoring local routing-field reads in the three modes.

**Verification**: 79 focused tests, 9,220 unit tests (one skip, 122 deselected), 921 regressions, 16 targeted Docker
resume tests (53 deselected), full pre-commit, 29,974/29,990 design-document counts, and the 358-document/882-link board
audit pass. PR #203 merged as `0d041b83` with all five GitHub checks passing. No Forge workflow command was used.

### Share Codex thread index synchronization

**Goal/outcome**: Replace the duplicated Codex post-turn index writer with one UI-free operation while preserving the
manifest-first and adoption-safety contracts.

**Key changes**:

- Routed interactive and headless start/resume paths through one writer after successful manifest persistence, retaining
  the no-thread skip and `IndexStore.update_codex_thread` as the scoped, durable, best-effort authority.
- Preserved collision logging and live-thread adoption guards, with keyed state assertions that do not depend on index
  iteration order.
- Added a shared deleted-identity failure fixture, a guard against restoring the legacy private copies, and real Codex
  start/resume integration assertions for the durable index column.

**Verification**: 205 focused tests, 504 command-core tests, 9,220 unit tests (one skip, 122 deselected), 915
regressions, one targeted real Codex start/resume integration, full pre-commit, 29,972/29,990 design-document counts,
and the 357-document/882-link board audit pass. PR #202 merged as `d1abccc7` with all five GitHub checks passing. No
Forge workflow command was used.

### Align count-tokens mode and model defaults

**Goal/outcome**: Remove the unread token-count mode field without deleting its public selector, and align the omitted
model with the repository's canonical Opus default.

**Key changes**:

- Made `--local` and `--provider-api` write one authoritative mode while preserving local default behavior, help, mutual
  exclusion, output, and provider fallback semantics.
- Changed the omitted model from `claude-opus-4-6` to `claude-opus-5`; both use the same offline `cl100k_base` fallback,
  while opt-in provider counting now targets the canonical Opus model by default.
- Added hermetic subprocess contracts for the model default, omitted and explicit local modes, provider mode,
  conflicting flags, and help output.

**Verification**: Six focused tests, 9,216 unit tests (one skip, 122 deselected), 915 regressions, real default/local/
provider token-count smokes, full pre-commit, unchanged 29,986/29,987 design-document counts, and the
356-document/882-link board audit pass. PR #201 merged as `b350b4d5` with all five GitHub checks passing. No Forge
workflow command was used.

### Retire test-only settings helpers

**Goal/outcome**: Remove three internal settings helpers that had no supported caller without weakening the live backup,
rollback, or conflict contracts.

**Key changes**:

- Removed `restore_settings_backup` and `check_scalar_conflict` with their five direct-only tests; the installer
  continues to use backup snapshots, rollback-state capture/restore, and `set_scalar` conflict handling.
- Removed the zero-caller `_extract_command_paths` helper while preserving the active canonical hook deduplication path.
- Reverified that none of the removed symbols was exported, documented as supported, registered as an entry point, or
  referenced by packaged extension assets.

**Verification**: 106 focused tests, 9,210 unit tests (one skip, 122 deselected), 915 regressions, 23 targeted Docker
installer tests, the clean-wheel runtime smoke, full pre-commit, design-size checks, and the 355-document/880-link board
audit pass. PR #200 merged as `63ae0f74` with all five GitHub checks passing. No Forge workflow command was used.

### Wire the transcript reindex guard

**Goal/outcome**: Avoid re-extracting and rewriting unchanged transcript snapshots without allowing optimization
bookkeeping to gate searchability.

**Key changes**:

- Wired the existing modification-time/size fingerprint into deferred indexing after project, containment, and
  transcript validation; unchanged snapshots now skip extraction and all three search-store writes.
- Preserved full idempotent indexing for new, changed, invalidated, and unreadable-state snapshots, with the strict
  state mark last so failed bookkeeping remains retryable without hiding searchable content.
- Made explicit full rebuild replace fresh index state once under lock, repairing corrupt/newer bookkeeping and removing
  the per-transcript read-modify-write loop.

**Verification**: 107 focused tests, 9,215 unit tests (one skip, 122 deselected), 915 regressions, one targeted Docker
Stop/artifact integration, full pre-commit, design-size checks, and the 354-document/880-link board audit pass. PR #199
merged as `7b3ac2df` with all five GitHub checks passing. No Forge workflow command was used.

### Deprecate the supervisor verdict compatibility wrapper

**Goal/outcome**: Mark the deliberately exported legacy verdict parser for later removal without changing its return or
fallback behavior in the first warning release.

**Key changes**:

- Kept `parse_supervisor_verdict` importable and behaviorally identical while issuing a caller-attributed
  `FutureWarning` that is visible under Python's default filters and names the fully qualified status-bearing
  replacement.
- Moved internal parser and regression coverage to `parse_supervisor_verdict_with_status`; retained one focused
  compatibility contract for the package export, valid and fallback parity, warning count, message, attribution, and a
  warning-free replacement path.
- Corrected the execution card's return-type and release-window wording after reverifying production, test, export,
  resource, extension, documentation, string-target, and history references.

**Verification**: 198 focused tests, 272 semantic-policy tests, 9,207 unit tests (one skip, 122 deselected), 913
regressions, a fresh-process consumer-module warning smoke, full pre-commit, design-size checks, and board-integrity
checks pass. PR #198 merged as `7fd701b5` with all five GitHub checks passing. No Forge workflow command was used.

## 2026-08-16

### Remove verified dead session helpers

**Goal/outcome**: Remove three internal-only O092 session residues without changing live discovery or relaunch behavior.

**Key changes**:

- Removed the unused shadow session filter and its private CLI pass-through; live callers continue through the same
  passport-based project/workspace discovery and deduplication path.
- Deleted the uncalled session-tip no-op and removed the unused relaunch parent argument while retaining parent lineage
  and `forge_root`-scoped name generation.
- Replaced the direct-only filtered-shadow test with controls for live shadow collection, exact relaunch call shape, and
  project-scoped collision inputs.

**Verification**: 552 focused tests, 9,205 unit tests (one skip, 122 deselected), 913 regressions, 23 targeted Docker
session-lifecycle tests, full pre-commit, design-size checks, and board-integrity checks pass. PR #197 merged as
`86a83a1d` with all five GitHub checks passing. No Forge workflow command was used.

### Remove the dead session-context retry

**Goal/outcome**: Remove an index-only retry that could not observe the manifest corruption named by its comment.

**Key changes**:

- Explicit session identifiers now perform one scoped and one unscoped name lookup before UUID-index and stale-manifest
  fallback, without repeating the unscoped lookup.
- Added direct controls for corruption, unreadable-state, and ambiguity propagation plus both fallback stages and their
  call order.

**Verification**: 185 focused tests, 9,205 unit tests (one skip, 122 deselected), 913 regressions, 23 targeted Docker
session-lifecycle tests, full pre-commit, design-size checks, and board-integrity checks pass. PR #196 merged as
`bc4f3a0c` with all five GitHub checks passing. No Forge workflow command was used.

### Replace legacy environment-based tier inference

**Goal/outcome**: Remove the nonexistent proxy tier environment shim and make the factory's tier provenance explicit.

**Key changes**:

- `get_client` now requires a resolved tier; the dead `_MODEL` lookup and false auto-detection log are gone.
- Exact-tier authentication retry is unchanged, while the retained all-tier invalidation path rebuilds the configured
  `proxy.default_tier` instead of guessing from undeclared environment variables.
- Recorded the provider-scoped authentication-invalidation question as a separate proposed decision instead of widening
  O051 during review.

**Verification**: 50 focused tests, 794 proxy unit tests, 9,200 full unit tests (one skip, 122 deselected), 913
regressions, seven targeted Docker proxy-routing tests, full pre-commit, design-size checks, and board-integrity checks
pass. PR #195 merged as `aca65c7f` with all five GitHub checks passing. No Forge workflow command was used.

### Retire unsafe public index mutators

**Goal/outcome**: Remove row-only public index mutation paths after every supported caller moved to the durable session
transactions.

**Key changes**:

- Deleted `IndexStore.add_session`, `add_from_state`, and `remove_session` plus their direct-only contracts, leaving
  durable publication and deletion under the transaction lock and compensation rules.
- Replaced the temporary direct-call allowlist with a zero-attribute-reference guard, removed stale live references, and
  added transaction coverage proving a scoped delete preserves the same session name in another Forge root.

**Verification**: 217 focused tests on the final head, 9,199 unit tests (one skip, 122 deselected), 913 regressions, 69
targeted Docker session tests, full pre-commit, design-size checks, and board-integrity checks pass. PR #194 merged as
`ae7519fc` with all five GitHub checks passing. No Forge workflow command was used.

### Make durable session test state transactional

**Goal/outcome**: Replace unsafe row-only test setup with shared builders that preserve the production row-plus-manifest
transaction contract.

**Key changes**:

- Routed ordinary test publication and deletion through transaction-backed builders, with contract coverage for write
  order, compensation, binding uniqueness, and ownership-aware deletion.
- Isolated deliberate crash residue, orphan manifests, and race states behind explicit raw helpers, leaving only 18
  direct mutator-contract calls for the independent API-deletion member.

**Verification**: 1,775 focused session/core-ops tests, 9,211 unit tests (one skip, 122 deselected), 913 regressions, 69
targeted Docker session tests, full pre-commit, design-size checks, and board-integrity checks pass. PR #193 merged as
`56dfc27b` with all five GitHub checks passing. No Forge workflow command was used.

### Migrate legacy memory-intent state

**Goal/outcome**: Remove the behaviorless `MemoryIntent.generated_file` field without making Forge-authored legacy
session manifests unreadable.

**Key changes**:

- Removed the field from current writes and added a narrow, no-rewrite compatibility pass for legacy
  `intent.memory.generated_file` before strict decoding.
- Kept malformed containers, unrelated unknown fields, the same key under overrides, and unsupported schema versions
  strict, with byte-preservation coverage for successful and failed reads.

**Verification**: 243 focused tests, 9,204 unit tests (one skip, 122 deselected), 913 regressions, 23 targeted Docker
session-lifecycle tests, full pre-commit, design-size checks, and board-integrity checks pass. PR #192 merged as
`b7a8ad9e` with all five GitHub checks passing. No Forge workflow command was used.

## 2026-08-15

### Deprecate inert configuration fields

**Goal/outcome**: Stop authoring three behaviorless user-config fields while preserving readable 0.9.4-era configuration
through an explicit warning window.

**Key changes**:

- Raw template, global, and proxy-instance loaders now warn once for explicitly present compatibility keys; omission
  stays silent, new serialization omits the keys, and runtime transport and manifest-path authorities remain unchanged.
- The compatibility fields remain accepted for the release carrying the warning, and a schema parity guard keeps the
  provider scan registry aligned with every `ProviderConfig` block.

**Verification**: 438 focused tests, six O049 regressions, 9,197 unit tests (one skip, 122 deselected), 913 regressions,
34 targeted Docker proxy tests, wheel/sdist build and clean-wheel smoke, exact-wheel resource checks, full pre-commit,
and board-integrity checks pass. PR #191 merged as `e0be9a60` with all five GitHub checks passing. No Forge workflow
command was used.

### Remove obsolete proxy abstractions

**Goal/outcome**: Remove unsupported proxy surfaces after proving they had no production, resource, extension, or
documentation consumers.

**Key changes**:

- Removed the test-only model-spec module, unused abstract client, unproduced tool-call exception and handlers, and two
  zero-caller factory diagnostics while preserving the live adapter, streaming error, conversion, cache, and metrics
  contracts.
- Moved synthetic failure-metrics coverage to the reachable generic client-error path and pinned its sanitized response
  plus total, error-type, tier, and model counters.

**Verification**: 829 pre-deletion proxy tests, 808 post-deletion proxy tests, 9,193 unit tests (one skip), 907
regressions, four hermetic Docker proxy tests, full pre-commit, and board-integrity checks pass. PR #190 merged as
`ca2f289b` with all five GitHub checks passing. No Forge workflow command was used.

### Honor explicitly empty process timezone

**Goal/outcome**: Restore process-local UTC period boundaries when `TZ` is explicitly empty without changing unset,
valid non-empty, or invalid non-empty timezone behavior.

**Key changes**:

- Empty `TZ` now selects `datetime.UTC` before dependency or filesystem resolution; unset and invalid values retain the
  host-local fallback.
- Host-independent regressions pin UTC identity and exact local-period bounds while retaining the four shared telemetry
  consumers.

**Verification**: 114 focused tests, 9,214 unit tests (one skip, 122 deselected), 907 regressions, six targeted Docker
telemetry integrations, full pre-commit, and board-integrity checks pass. An extra cancelled-stream provider-trace test
failed twice on an untouched lifecycle seam and was disclosed in the PR. PR #189 merged as `f0afc0c4` with all five
GitHub checks passing. No Forge workflow command was used.

### Lock walkthrough and QA state-script parity

**Goal/outcome**: Keep both installed skills self-contained while preventing their shared state machine from drifting
silently.

**Key changes**:

- A byte-and-mode parity contract permits only the two skill-identity lines to differ and requires both scripts to stay
  owner-executable.
- The complete 93-case behavioral matrix runs against each copy, while clean-wheel lifecycle coverage verifies both
  packaged scripts through enable, sync, status, and disable.

**Verification**: 188 focused tests, 9,212 unit tests (one skip), 906 regressions, one targeted Docker lifecycle, build,
clean-wheel smoke, full pre-commit, and board-integrity checks pass. PR #188 merged as `b8e4b32c` with all five GitHub
checks passing. No Forge workflow command was used.

### Share proxy transport test fakes

**Goal/outcome**: Replace parallel proxy HTTP fake families with one instance-safe test scaffold without changing
production transport behavior.

**Key changes**:

- Both passthrough suites now configure transport-specific defaults through a shared per-test response, stream, client,
  request-capture, failure-injection, and teardown fixture.
- Direct contracts cover instance isolation and request, iteration, read, context-entry, and teardown failures; the
  original factory-leak claim was corrected because pytest already restored those monkeypatches.

**Verification**: 128 focused tests, 14 targeted regressions, 9,117 unit tests (one skip), 906 regressions, full
pre-commit and Markdown hooks, and board-integrity checks pass. PR #187 merged as `be321ad2` with all five GitHub checks
passing. No Forge workflow command was used.

### Remove redundant development dependency metadata

**Goal/outcome**: Remove the duplicate dev `python-dotenv` floor without weakening runtime or test dependencies.

**Key changes**:

- Removed only the redundant dev-group `python-dotenv>=1.2.1` edge; runtime still requires `>=1.2.2`, with no package or
  version churn in the lockfile.
- Rejected O071's stale `httpx2` claim after Starlette source, repository history, and a warnings-as-errors control
  proved it is a live test-client dependency.

**Verification**: 17 focused tests, 9,115 unit tests (one skip, 122 deselected), 906 regressions, build and clean-wheel
smoke, full pre-commit, and board-integrity checks pass. PR #186 merged as `19dcf9cb` with all five GitHub checks
passing. No Forge workflow command was used.
