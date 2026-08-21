# Change Log

Completed-work record for Forge implementation sessions.

## Maintenance

- Updated by the memory writer with `strategy=changelog`, and by humans when closing a phase.
- Add compact entries for completed work only. Pending tasks belong in card checklists.
- Follow `docs/developer/board_contract.md` "Change Log Policy": each entry needs Goal, Key changes, and Verification.
- Keep entries short. Do not list every file unless the file list is the point of the work.
- Use newest-first order so active work stays near the top.
- When this file approaches the documentation size limits, compact the oldest entries at the bottom into a dated summary
  that preserves decisions, verification, and deferred items. Archive detailed old entries only if the summary is still
  too large.
- Check size before long sessions or when the file feels slow to scan:

```bash
wc -l docs/board/change_log.md
./scripts/count-tokens.py docs/board/change_log.md
```

## Entries

> Format: `## YYYY-MM-DD`, then `### Phase X.Y: Short Title`, with `**Goal**:`, `**Key changes**:` as bullets, and
> `**Verification**:`. Use newest-first order. See `docs/developer/board_contract.md` "Change Log Policy" for the full
> spec.

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

## 2026-08-14

### Close post-merge correctness gaps

**Goal/outcome**: Correct five verified edge cases from the review of PRs #170--#180 before resuming Wave 7 cleanup.

**Key changes**:

- Retained the canonical walkthrough root after environment loading, rejected impossible filtered tool selection, and
  honored IANA, TZif-path, and POSIX-rule process timezones.
- Surfaced failed child rollback with exact cleanup guidance, corrected positional shadow-session recovery, and kept
  optional `tool_choice:auto`/`none` behavior outside this unreproduced scope.

**Verification**: 230 focused and 71 review-strength tests, 9,115 unit tests (one skip, 122 deselected), 906
regressions, 28 targeted Docker integrations, full pre-commit, build and clean-wheel smoke, and board-integrity checks
pass. PR #185 merged as `8ccbf387` with all five GitHub checks passing. No Forge workflow command was used.

### Remove verified internal residue

**Goal/outcome**: Remove the admitted session metadata, zero-caller summary helper, and redundant cap-state guard
without changing public commands or runtime behavior.

**Key changes**:

- Session modules no longer advertise stale re-export metadata, and `session_fork` imports its rewind helper directly
  from the owner.
- Cap-state loading relies on the shared JSON object boundary, with non-object rejection pinned at that boundary.

**Verification**: 508 focused tests, 23 targeted Docker integrations, 9,113 unit tests (one skip, 122 deselected), 898
regressions, full pre-commit, and board-integrity checks pass. PR #184 merged as `95488c10`. No Forge workflow command
was used.

### Centralize CLI metric formatting

**Goal/outcome**: Give token and USD presentation one UI-free authority while preserving each CLI surface's named
rounding, precision, suffix, and sub-cent policy.

**Key changes**:

- Proxy metrics, cost reporting, activity summaries, and status-line rendering now select explicit shared token and
  currency policies; JSON values and all shipped human strings remain unchanged.
- Golden tests pin the distinct presentation contracts, including lowercase activity thousands, adaptive cost detail,
  fixed-cent session summaries, and whole- versus fractional-cent status metrics.

**Verification**: 648 focused tests, 17 targeted Docker status-line integrations, 9,109 unit tests (one skip, 122
deselected), 898 regressions, full pre-commit, and board-integrity checks pass. PR #183 merged as `cd3e50e8`. No Forge
workflow command was used.

### Centralize installer path authority

**Goal/outcome**: Give installer planning and runtime-scoped removal one lower-layer authority for target mapping, path
boundaries, tracked ownership, and preserve-the-leaf package canonicalization.

**Key changes**:

- `install.path_policy` now owns the shared pure path decisions, and `RuntimeRemovalExecutor` no longer receives four
  installer-owned policy callbacks.
- Fail-closed symlink, legacy-row, runtime-scope, and unmanaged-package behavior remains unchanged; duplicate CLI
  git-root cases were removed, and the remaining target-root test-fixture cleanup is assigned to Wave 7 order 33.

**Verification**: 347 focused tests, 23 targeted Docker installer integrations, 14 component installer integrations,
9,064 unit tests (one skip, 122 deselected), 898 regressions, clean-wheel lifecycle checks, full pre-commit, and board
integrity checks pass. PR #182 merged as `1a450143` with all five GitHub checks passing. No Forge workflow command was
used.

### Unify git-root discovery

**Goal/outcome**: Use one filesystem git-root walk while preserving optional and strict caller contracts and keeping
Git-backed repository identity separate.

**Key changes**:

- `core.paths.find_git_root` now owns `.git` directory and worktree-marker traversal; the Claude adapter retains its cwd
  default and exact `FileNotFoundError` behavior.
- The definition-only `ProjectRootNotFoundError` is removed, and filesystem marker discovery remains distinct from
  Git-subprocess checkout, logical-repository, worktree-membership, and bare-repository semantics.

**Verification**: 182 focused tests, 3 targeted Docker session integrations, 9,065 unit tests (one skip, 122
deselected), 898 regressions, full pre-commit, and board integrity checks pass. PR #181 merged as `a8cff31f` with all
five GitHub checks passing. No Forge workflow command was used.

### Centralize timestamp primitives

**Goal/outcome**: Use one timestamp and local-period boundary while retaining each caller's explicit compatibility and
presentation policy.

**Key changes**:

- Strict and tolerant ISO parsing now normalize valid offsets through `core.state.timestamps`; compatibility readers
  explicitly select naive-as-UTC behavior, and direct production `datetime.fromisoformat` calls are eliminated.
- One transition-aware local-calendar primitive serves four period callers, while named compact and full-word styles
  preserve the proxy and session relative-time contracts.

**Verification**: 721 focused tests, 7 targeted Docker proxy integrations, 9,064 unit tests (one skip, 122 deselected),
898 regressions, full pre-commit, and board integrity checks pass. PR #180 merged as `659d4966` with all five GitHub
checks passing. No Forge workflow command was used.

### Share policy activation rules

**Goal/outcome**: Share policy activation vocabulary and validation without merging terminal intent writes with direct
session-override writes.

**Key changes**:

- A UI-free command-core helper now derives bundle names and fail modes from their authorities and returns typed
  activation or deactivation values, including TDD permissive configuration.
- Both policy surfaces use the shared rules while retaining their state owners, syntax, errors, output, and mutable
  bundle-config handoff. Adjacent policy-check vocabulary remains a standalone parked follow-up.

**Verification**: 125 focused tests, 22 targeted Docker hook integrations, 9,022 unit tests (one skip, 122 deselected),
898 regressions, full pre-commit, and board integrity checks pass. PR #179 merged as `435f2bac` with all five GitHub
checks passing. No Forge workflow command was used.

### Decouple lane runtime vocabulary

**Goal/outcome**: Restore the documented import-light lane vocabulary boundary without changing runtime classification
or dispatch behavior.

**Key changes**:

- Lane validation now uses `AGENT_RUNTIME_IDS`, with the existing exact registry-parity test retaining authority over
  deliberate runtime-ID duplication.
- A fresh-interpreter regression rejects initialization of the runtime, LLM, and auth module trees when importing
  `forge.core.lanes`; the measured cumulative import fell from approximately 317 ms to 55 ms.

**Verification**: 49 focused lane assertions, 568 broader lane-consumer assertions, 9,005 unit tests (one skip, 122
deselected), 898 regressions, full pre-commit, and board integrity checks pass. PR #178 merged as `30f930b0` with all
five GitHub checks passing. No Forge workflow command was used.

## 2026-08-13

### Admit Wave 7 refactor and deletion

**Goal/outcome**: Turn the residual structural/deletion ledger into an evidence-backed execution sequence without
starting implementation or absorbing separately gated correctness work.

**Key changes**:

- The post-Wave 6 screen admitted 31 verified findings as 34 parked members, split compatibility migrations from
  deletion and decomposed the fork, installer, and status-line work at existing seams.
- O062/O063/O093 were rejected as written, O067/O095 were admitted only in verified scope, three broad or invalidated
  placeholders were retired, and unverified plus Wave 6 correctness/test-policy/output/docs rows remain excluded.

**Verification**: 58 focused lane, review-parser, model-mapping, and SSE characterization tests pass; fresh-process
import timing confirms O043's heavy registry edge. `make pre-commit-md`, the 326-file/852-link board audit, 55 changed
fragment checks, the 34-member lane graph, and `git diff --check` pass. No Forge workflow command was used.

### Close Wave 6 correctness maintenance

**Goal/outcome**: Prove walkthrough sandbox provenance before target-controlled shell execution and close the bounded
Wave 6 correctness-maintenance admission.

**Key changes**:

- The walkthrough wrapper now resolves the target canonically before denylist comparison and verifies its marker and
  required structure before sourcing its environment file.
- O036 closed the admission at 36/36 findings across 13 independent members. D056 and later Wave 6/7 work remain behind
  separate entry gates.

**Verification**: The retained O036 artifact produced 3 failures and 1 control on `88ac88c5`; 98 focused tests, 898
regressions, 9,004 unit tests (one skip, 122 deselected), the clean-wheel check, one targeted Docker integration,
pre-commit, and the 298-file/723-link board audit pass. Shipped in PR #177 (`3026b14a`) with all five GitHub checks
passing.

### Preserve session launch preconditions

**Goal/outcome**: Validate launch prerequisites before durable mutation and keep fallback or post-launch failures from
corrupting later session launches.

**Key changes**:

- Incognito and rewind failures now clean up derived state consistently, while JSON capability rejection and launch
  confirmation remain narrowly scoped and best-effort.
- Native fork UUIDs and resume names are validated before mutation; transfer and `--no-launch` paths remain UUID-free.

**Verification**: The retained artifact produced 15 failures and 7 controls on `967d9cae`; 168 focused tests, 9,004 unit
tests (one skip, 122 deselected), 894 regressions, 48 targeted integrations, pre-commit, and board integrity checks
pass. Shipped in PR #176 (`88ac88c5`).

### Harden command and state boundaries

**Goal/outcome**: Keep direct-command no-ops silent and reject malformed or reserved durable state at shared validation
boundaries.

**Key changes**:

- Five no-session direct commands now emit nothing, and every passport create/update path rejects reserved basenames
  before writing while preserving the intentionally informative `%plan` and `%policy check` outcomes.
- Search stores now reject wrong container and element shapes with rebuild guidance, and Optional unwrapping is limited
  to actual unions with `None`.

**Verification**: The retained artifact produced 21 failures and 5 controls on `095fcd90`; 681 focused tests, 9,004 unit
tests (one skip, 122 deselected), 872 regressions, 24 targeted Docker integrations, pre-commit, and board integrity
checks pass. Shipped in PR #175 (`967d9cae`).

### Align CLI failure surfaces

**Goal/outcome**: Make high-frequency command and status-line failures predictable without changing successful output.

**Key changes**:

- Status-line input parsing now fails open for malformed top-level, workspace, and proxy-URL data; missing-command and
  JSON workflow-preflight failures use non-zero, stderr-only contracts.
- Proxy, template, runtime-config, and Claude-preset editors now share shell-style `$EDITOR` argv parsing while
  preserving validation and recovery behavior.

**Verification**: The retained artifact produced 19 failures and 4 controls on `13ecef87`; 809 focused tests, 9,005 unit
tests (one skip, 122 deselected), 844 regressions, 19 targeted Docker integrations, QA/package checks, pre-commit, and
board integrity checks pass. Shipped in PR #174 (`095fcd90`).

### Exclude interactive usage cost on both planes

**Goal/outcome**: Keep the reserved interactive harness route out of Forge-added cost if it later gains both a usage
emitter and proxy run-tree correlation.

**Key changes**:

- Included event roots now exclude interactive events before the exact-cost query, and mixed-root results remove only
  run IDs proven interactive from dollar-bearing and presence-only records.
- Cost-only children without usage events remain included. The shipped path is latent contract hardening rather than a
  correction to observed live spend because neither interactive precondition is currently emitted.

**Verification**: The retained artifact produced 3 failures and 3 controls on `7280d177`; 223 focused tests, 9,001 unit
tests (one skip, 122 deselected), 821 regressions, one targeted Docker integration, pre-commit, and board integrity
checks pass. Shipped in PR #173 (`a55ab218`).

### Align policy routing context

**Goal/outcome**: Make supervisor routing comparisons and policy-shadow reads use the session state that actually
governs their behavior.

**Key changes**:

- Supervisor setup now compares source routing with CLI-confirmed launch proxy identity instead of probing `ProxyIntent`
  for a field it does not own.
- Shadow `show` and `status` share explicit/current/sole-local name resolution and machine-readable stderr failures; the
  former undocumented `shadow show <uuid>` input was intentionally narrowed to names.

**Verification**: The retained artifact produced 6 failures and 10 controls on `f6df4a40`; 248 focused tests, 9,001 unit
tests (one skip, 122 deselected), 815 regressions, 9 targeted Docker integrations, pre-commit, and board integrity
checks pass. Shipped in PR #172 (`366c216a`).

### Harden proxy boundary failures

**Goal/outcome**: Reject malformed transported proxy fields before request handling and make process-spawn failure
atomic and typed.

**Key changes**:

- Added shared load-boundary validation for the four directly transported proxy fields while preserving valid values and
  absent-key defaults.
- Failed proxy spawn now closes and removes its stderr capture and raises `ProxyStartError` with the original cause.

**Verification**: The 26-case retained regression, 253 focused tests, 9,001 unit tests (one skip, 122 deselected), 799
regressions, 2 targeted Docker integrations, pre-commit, and board integrity checks pass. Shipped in PR #171
(`5cd268c1`).

### Restore proxy request semantics

**Goal/outcome**: Keep proxy-owned tier and translated request constraints stable across initial calls, authentication
refresh, reasoning overrides, and both OpenAI client shapes.

**Key changes**:

- Removed undocumented tier-hyperparameter environment precedence while retaining the separately parked `_MODEL`
  fallback, and made authentication retry rebuild the resolved tier.
- Reasoning pins now remove incompatible sampling keys with key-name-only audit metadata. Anthropic `any` now remains
  required through the converter, core adapter, Chat Completions, and GPT Responses paths.

**Verification**: The final regression artifact collects six fail-first cases and three controls on `7f705aad`; D030 is
parametrized for both providers, the count includes the later adapter seam, and the configured-but-satisfied
reasoning-floor case adds the third control. The separate GPT Responses seam also failed before correction. The 204-test
focused slice, 9,001 unit tests (one platform skip, 122 deselected), 773 regressions, and 4 translated-proxy Docker
integrations pass. The first integration-file run exposed and corrected an older cumulative-event-count order dependency
before the 4-test rerun passed. Normative and end-user proxy contracts are synchronized. Final all-files and explicit
new-file hooks plus the 289-file/713-link board audit pass with no missing or stale lane targets. Shipped in PR #170
(`acae1b9e`).

### Harden process cleanup and retention status

**Goal/outcome**: Complete detached-group escalation and keep retention failures actionable without exposing internal
exception detail through public proxy status.

**Key changes**:

- Wait for complete owned process groups under shared grace deadlines, escalate surviving descendants to `SIGKILL`,
  retain cleanup-failure evidence, and retire completed child ownership before later hooks can raise.
- Publish stable retention resolution/enforcement recovery messages while keeping detailed resolver and pruner failures
  in server logs, closing CodeQL alert 32.

**Verification**: The retained real-process regression proves a `SIGTERM`-ignoring descendant is killed; stale-PGID and
single-attempt timeout controls cover the ownership edges. The 106-test invoker slice, 8,990 unit tests (one existing
platform skip, 122 deselected), 764 regressions, 4 targeted Docker integrations, and pre-commit pass. Shipped in PR #169
(`ece999d4`).

## 2026-08-12

### Complete proxy instance config wiring

**Goal/outcome**: Preserve template tool-ignore and prompt-cache settings through proxy creation and runtime reload.

**Key changes**:

- Added `tool_prefixes_to_ignore` to the user-owned proxy instance schema and copied it from templates alongside the
  selected provider's prompt-cache policy and threshold.
- Replaced hand-maintained direct copies with closed field registries while keeping tier construction and CLI override
  merging explicit transforms; absent keys retain compatibility defaults.

**Verification**: Three fail-first cases failed on `7c76a099` while two controls passed. The 1,015-test config/proxy
slice, 8,986 unit tests (one existing platform skip, 122 deselected), 758 regressions, 6 Docker proxy-creation
integrations, and pre-commit pass. The 288-file/713-link board audit has no missing targets and confirms the Wave 6 lane
split at 4 done/1 doing/7 todo. Design and end-user ownership contracts are synchronized.

### Close proxy failure lifecycles

**Goal/outcome**: Preserve proxy ownership after failed restarts and close both upstream contexts when a non-200 HTTP
transport read fails.

**Key changes**:

- Failed restarts now restore the prior registry entry, or retain config-only ownership as `stopped`, without
  overwriting a concurrent replacement.
- Anthropic and Responses raw transports now close stream/client contexts, report failure once, and return their stable
  HTTP 502 body when a non-200 body cannot be read; ordinary non-200 relay remains unchanged.

**Verification**: Four fail-first cases failed on `4774f69e` while two compatibility controls passed. The 193-test
focused slice, 814 proxy units, 8,981 unit tests (one existing platform skip, 122 deselected), 753 regressions, and 5
targeted Docker integrations pass. Full pre-commit plus board link/lane, size, and diff checks pass; design and end-user
lifecycle contracts are synchronized. The untracked regression/checklist also pass an explicit new-file hook run. Both
GitHub workflows passed, and the member shipped in PR #167 (`33e3db7f`).

## 2026-08-11

### Harden detached process teardown

**Goal/outcome**: Close both ownership gaps for Forge-created detached process groups without changing ordinary backend
or headless result contracts.

**Key changes**:

- Changed LiteLLM stop and failed-start cleanup from leader-only signaling to the recorded process group. Stop failures
  abort registry removal, and config deletion now reports those failures, retains the config, and omits `Deleted`.
- Added single-shot `BaseException` cleanup through the shared terminate/reap helper before re-raising cancellation,
  with mocked regressions and real parent/worker process-group integration coverage.

**Verification**: Three fail-first cases failed on `b3150184` while two compatibility controls passed; four focused
review guards then failed on `a4071346`. The 128-test backend/invoker slice, 8,974 unit tests (one existing platform
skip, 122 deselected), 747 regressions, 8 backend CLI integration tests, and 3 real-process teardown integrations pass.
A real Codex smoke stopped at preflight because no Codex credential is configured and launched no subprocess. Final
pre-commit and board link/lane checks pass. All five GitHub checks passed, and the member shipped in PR #166
(`5b50acc8`).

### Strip inherited Forge headers from direct children

**Goal/outcome**: Prevent direct children from forwarding stale internal correlation identifiers inherited from a
proxied parent.

**Key changes**:

- Removed the four Forge-owned custom-header names before the proven-proxy gate while preserving unrelated and malformed
  user lines; proven Forge proxies still receive freshly derived identifiers.
- Retained mixed-header and Forge-only regressions, including the review-added assertion that an empty result removes
  `ANTHROPIC_CUSTOM_HEADERS` entirely.

**Verification**: The fail-first guard failed on `55fcda59`; 85 focused tests, 727 regressions, and 6 proxy-correlation
integration cases pass with clean pre-commit and board checks. Shipped in PR #164 (`26ab5f29`).

### Close Wave 5 and hand off correctness maintenance

**Goal/outcome**: Replace Wave 5's open-ended MEDIUM tail with an exact terminal scope and preserve valid remaining work
under the canonical Wave 6 boundary.

**Key changes**:

- Closed Wave 5 at 13/13 admitted and shipped findings. Rechecked the 36 unresolved MEDIUM rows that still described a
  CLI, proxy, or launch/runtime boundary; rejected D033 and O020 because current executable controls contradict their
  claimed impact.
- Accepted the 34 still-live rows into 12 parked Wave 6 members with explicit authorities, compatibility exclusions,
  test tiers, and fail-first activation gates. No implementation member was activated and later performance/docs,
  structural, deletion, and unverified rows remain outside this admission.

**Verification**: Two rejected-claim controls pass. Full pre-commit passes; 282 board Markdown files have no missing
relative target, all fragments in the 17 changed board files resolve, the 12-member epic graph/lane audit passes, and
`git diff --check` is clean.

### Fail non-streaming response conversion truthfully

**Goal/outcome**: Report an unrepresentable translated provider response as a client and accounting failure without
discarding the completed provider attempt's usage, cost, or trace evidence.

**Key changes**:

- Replaced the converter's successful assistant fallback with an explicit failure signal and one stable HTTP 500
  `api_error` path shared by initial and authentication-retry completions.
- Recorded provider-reported tokens and cost as failed, retained the provider-attempt trace, and kept provider response
  and exception text out of client content and ordinary logs. Malformed usage degrades to zero-token accounting without
  bypassing reported cost or trace recording. Successful, streaming/SSE, `ToolCallError`, and passthrough behavior
  remains unchanged.
- Closed the two-member proxy-conversion epic after synchronizing its shipped member paths and review-ledger
  dispositions.

**Verification**: Three original O007 tests failed on `8088ceae`, covering the converter, initial route, and
authentication-retry route. A fourth review-discovered malformed-usage regression failed against the initial
implementation. After hardening, 117 focused tests, 8,954 unit tests (one skip, 122 deselected), 723 regressions, and
three translated-proxy Docker cases pass. The first pre-commit run passed every code, type, and secret-scanning hook
before mdformat normalized the edited board Markdown. An explicit new-file pass then caught and corrected the regression
fixture's generator annotation; final all-files and new-file passes plus board-link, stale-lane, size, and diff checks
pass. Independent review and all five GitHub checks passed. Shipped in PR #162 (`31a0832f`). Post-merge closeout
compacted the July 10--17 tail from 23,306 tokens / 1,596 lines to about 20.6k / 1.35k; Markdown, 131-path/7-fragment
link, stale-lane, and diff checks pass.

### Sanitize proxy conversion-failure logs

**Goal/outcome**: Keep provider response-conversion failures diagnosable without rendering provider-controlled exception
text or tracebacks in ordinary logs.

**Key changes**:

- Replaced the non-streaming and streaming catch-all records plus the nested error-delivery record with fixed context,
  request ID, and safe exception-class metadata only. Streaming uses `exception_type` so the concrete Python class is
  distinct from the lifecycle summary's metrics-facing `error_type`.
- Retained the non-streaming fallback for O007's separate wire/accounting correction and preserved streaming error
  bytes, lifecycle/callback semantics, and explicit bounded raw diagnostics.

**Verification**: The two admitted regressions failed on `cf77c175` after their preservation controls; a follow-up
delivery guard failed against the remaining exception render. All three pass after correction. The 96-test focused
slice, 8,954 unit tests (one skip, 122 deselected), 719 regressions, and three translated-proxy Docker cases pass. Clean
pre-commit reruns plus board-link, stale-lane, and diff checks pass. D053 shipped in PR #161 (`8088ceae`), unblocking
O007 on its own execution branch.

## 2026-08-10

### Admit proxy conversion failure handling

**Goal/outcome**: Admit safe logging and truthful client/accounting behavior for provider response-conversion failures
without combining their internal-log and external-wire contracts.

**Key changes**:

- Closed the proxy-diagnostic hygiene epic after D036 shipped in PR #159, with all three member paths and ledger
  dispositions synchronized.
- Reproduced D053's provider-data ERROR rendering and O007's HTTP-200/`failed=false` outcome on merged `main`; parked
  them as two ordered members, with the log-only correction first.

**Verification**: Four disposable broken-behavior characterizations passed on `de02b09b`, and the module was removed
after evidence capture. Markdown hooks, relative-link, stale-lane, size, and diff checks passed; no implementation
member was activated.

### Validate client request IDs at proxy ingress

**Goal/outcome**: Preserve conventional client correlation IDs without allowing malformed, control-bearing, duplicate,
or overlong `X-Request-ID` values to become Forge diagnostic and response identifiers.

**Key changes**:

- Added one exact `[A-Za-z0-9._-]{1,128}` ingress contract that preserves accepted IDs and replaces invalid or ambiguous
  inputs with the endpoint's existing generated-ID prefix.
- Canonicalized supplied headers before downstream audit/header consumers can copy them, while leaving routing, upstream
  filtering, and the independent `X-Forge-*` validators unchanged.
- Pinned Forge's direct-path minter to the validator so `source_refs.cost_request_id` cannot silently diverge from the
  proxy cost key.

**Verification**: Five retained invalid-header assertions failed on `ce7eb1ec`; four valid-ID controls passed. After
implementation, 125 review-focused tests, 2 targeted Docker cases, 8,954 unit tests (one skip, 122 deselected), 716
regressions, final pre-commit, and board-link/diff checks passed. Shipped in PR #159 (`de02b09b`).

### Make tool-event diagnostics metadata-only

**Goal/outcome**: Keep debug tool-event records and the adjacent client-failure warning free of caller plaintext while
preserving the explicit opt-in tool-failure plane.

**Key changes**:

- Replaced arbitrary event details with a closed, bounded metadata schema and updated schema, lifecycle, sanitizer, and
  client-failure callers to retain only counts, types, flags, and normalized identifiers.
- Hardened directories touched by the tool-event writer to `0700` while retaining `0600` shards; left the opt-in
  `tool_failures` schema and global cleanup ownership unchanged.

**Verification**: Four retained broken-behavior assertions failed on `a2fb0638` while the existing-shard `0600` control
passed. After implementation, 49 focused tests, 55 CLI cleanup tests, 3 targeted Docker cases, 8,934 unit tests (one
skip, 122 deselected), 706 regressions, final pre-commit, and board-link/diff checks passed. Shipped in PR #158
(`ce7eb1ec`).

### Remove plaintext from proxy converter logs

**Goal/outcome**: Keep ordinary translated-converter diagnostics metadata-only and avoid formatting caller payloads for
suppressed DEBUG records without changing conversion behavior.

**Key changes**:

- Replaced full request/schema dumps and raw malformed-argument/tool-call records with parameterized counts, flags,
  value shapes, safe exception classes, and allowlisted key metadata.
- Preserved malformed-argument client fallback, tool sanitization, and the explicit guarded/capped `stream_chunks` raw
  plane; admitted the separate provider-side catch-all exception leak as D053.

**Verification**: The five-case regression failed on `46e6a309`. After implementation, 22 focused tests, the 82-test
converter/cache slice, 2 targeted Docker cases, 8,933 unit tests (one skip, 122 deselected), 701 regressions, final
pre-commit, and board-link/diff checks passed. Shipped in PR #157 (`a2fb0638`).

## 2026-08-09

### Admit proxy diagnostic data hygiene

**Goal/outcome**: Admit a bounded Wave 5 MEDIUM set that removes caller plaintext and untrusted identifiers from proxy
diagnostics without combining three independent compatibility boundaries.

**Key changes**:

- Rechecked D035, D036, O037, O038, and O042 on merged `main`; corrected D035's stale no-pruner wording and recorded its
  current `0600` shard mitigation while retaining the free-form payload, directory-hardening, and WARNING defects.
- Parked converter-log, structured tool-event, and request-ID members under one child epic; retained the explicit raw
  stream and opt-in bounded `tool_failures` planes as exclusions.

**Verification**: Six disposable broken-behavior characterizations passed on `c9c4bc2e`; one also confirmed the current
`0600` shard mode, and the module was removed after evidence capture. Board Markdown, relative-link, stale-lane,
token-size, and diff checks passed; no implementation member was activated.

### Make status-line sources segment-lazy

**Goal/outcome**: Avoid proxy and managed-session discovery when the configured status-line fields cannot consume those
facts, without changing the default bar.

**Key changes**:

- Added registry-owned proxy/session dependencies and one immutable render plan shared by source acquisition and segment
  rendering; each required source is acquired at most once per refresh.
- Made `path,branch` skip both shared probes while preserving default/unknown fallback, output bytes, source fail-open,
  and segment-specific git, transcript/cache, and hook-diagnostic work; synchronized design, operator, and bundled QA
  guidance.

**Verification**: The retained D018 regression failed on `8f030ef4`. After implementation, 494 focused tests, 14
targeted Docker cases, 8,929 unit tests (one skip, 122 deselected), 696 regressions, wheel/sdist and packaged-resource
checks, final pre-commit, and documentation-link checks passed. Independent review found no issues; GitHub Tests,
Pre-commit, and CodeQL passed. Shipped in PR #154 (`c4f14037`).

### Relay safe Anthropic response headers

**Goal/outcome**: Preserve actionable upstream retry and rate-limit metadata without exposing framing, credentials,
cookies, or proxy-owned response fields.

**Key changes**:

- Gave Anthropic and Responses passthrough one case-insensitive header boundary across buffered and streaming
  success/error paths, including dynamic `Connection` exclusions.
- Kept Forge request/cost/cache overlays authoritative and preserved response bodies, SSE chunks, accounting callbacks,
  and stream teardown; synchronized design, operator, and bundled QA guidance.

**Verification**: The retained O004 regression failed in all four 429/529 streaming/non-streaming cases on `983e4470`.
After implementation, 131 focused tests, the 787-test proxy slice, 8,921 unit tests (one skip), 695 regressions, both
fresh-image Docker cases, wheel/sdist build, final pre-commit, and documentation-link checks passed. Independent review
found no issues. Shipped in PR #153 (`8f030ef4`).

### Forward LiteLLM User-Agent metadata

**Goal/outcome**: Preserve Claude Code's inbound identity across translated LiteLLM requests without widening any
request-header allowlist.

**Key changes**:

- Replaced incompatible backend-string comparisons with the typed client-factory provider gate, covering local/remote
  LiteLLM and retaining OpenRouter parity.
- Kept sanitization and the 256-character cap at the adapter boundary; excluded credentials, cookies, and Forge
  correlation headers; synchronized design, operator, and bundled QA guidance.

**Verification**: The retained O001 regression failed on `efbefce9` with missing `_user_agent`. After implementation, 49
focused tests, 8,913 unit tests (one skip), 691 regressions, targeted Docker integration, wheel/sdist build, final
pre-commit, and documentation-link checks passed. Shipped in PR #152 (`983e4470`).

### Align search corruption failures

**Goal/outcome**: Make corrupt search state fail consistently across query/status and human/JSON modes without changing
missing, unreadable, or scope-all partial-result policy.

**Key changes**:

- Unified corruption rendering as stderr-only exit-1 failures, delayed status output until every store was readable, and
  preserved explicit rebuild recovery plus successful not-built/empty outcomes.
- Added store, stream, and scope-all controls; synchronized CLI/operator/QA guidance and admitted the separate D051/D052
  unreadable-query and clean-recovery inconsistencies.

**Verification**: The retained D017 regression failed on `61580fdb`. After implementation and review amendment, 92
focused tests, 8,905 unit tests (one skip), 690 regressions, wheel/sdist build, final pre-commit, and documentation-link
checks passed. Shipped in PR #151 (`efbefce9`).

## 2026-08-08

### Stabilize proxy create smoke-test JSON

**Goal/outcome**: Make create-time proxy verification one scriptable result whose process status reflects probe failure
without discarding the successfully resolved proxy.

**Key changes**:

- Nested optional smoke facts into the single creation JSON object and made failed probes exit non-zero across
  spawn/reuse/adopt while preserving the proxy for inspection and retry.
- Kept JSON without smoke, human output, and config-only `--no-start` behavior compatible; synchronized operator docs
  and bundled QA coverage.

**Verification**: The retained D016 regression failed on `c20b8d10` with two JSON documents and exit 0. After
implementation, 176 focused tests, 8,899 unit tests (one skip), 686 regressions, all 3 Docker proxy create/start cases,
package build, final pre-commit, and documentation-link checks passed. Shipped in PR #150 (`61580fdb`).

### Preserve proxy ownership on stop failure

**Goal/outcome**: Make proxy stop/delete failures visible without discarding the registry and configuration needed for
recovery.

**Key changes**:

- Made refused or failed required stops exit non-zero and retain ownership; delete now completes last-owner teardown
  inside the registry transaction before removing the row or overlay.
- Preserved intentional detach/shared/already-stopped outcomes, truthful post-stop rollback, and independent
  multi-delete progress; synchronized lifecycle docs and bundled QA coverage.

**Verification**: The retained O002 regression failed on `8b997e6a`. After implementation, 168 focused tests, 8,890 unit
tests (one skip), 685 regressions, all 6 Docker proxy-delete cases, package build, and final pre-commit passed.
Independent review's stderr assertion was resolved; its separate pre-lock `proxy stop` race remains recorded outside
O002. Shipped in PR #149 (`c20b8d10`).

### Unify downstream retention ownership

**Goal/outcome**: Give shared downstream telemetry one global retention policy and one startup pruner without silently
choosing among conflicting legacy proxy policies.

**Key changes**:

- Added runtime-owned `telemetry.downstream` policy resolution, fail-closed legacy conflict handling, one post-cap
  startup prune, and current-UTC-month shard preservation.
- Added preview-first migration, effective/source/conflict/deprecation status, and explicit guidance for the bounded
  multi-sidecar compatibility limitation.

**Verification**: The retained D015 regression reached the dual-pruner failure on `92b981a5`. After implementation,
8,884 unit tests (one skip), 684 regressions, the targeted Docker retention integration, final pre-commit, wheel build,
and independent review passed. Shipped in PR #148 (`8b997e6a`).

### Close installer safety and sequence CLI/proxy correctness

**Goal/outcome**: Close Wave 4 after D019 shipped and admit the seven remaining Wave 5 HIGH findings as separate parked
members.

**Key changes**:

- Closed D019 and the installer transaction epic after PR #146, then repointed their parent/member/review-ledger links.
- Rechecked D015--D018, O001, O002, and O004 on merged `main`; excluded already-shipped O003 and sequenced retention,
  lifecycle, CLI, request/response metadata, and status-line I/O without activating implementation.

**Verification**: Independent D019 review found no violations; 148 focused host tests, both targeted Docker installer
cases, and focused Ruff passed. Seven disposable Wave 5 broken-behavior characterizations passed on `3f3a3c6d` and the
module was removed after evidence capture. Markdown hooks passed; a fragment-aware scan resolved all 178 relative paths
and 44 fragments across the 19 changed documents. The repository-wide scan found only seven pre-existing fragment
failures in unchanged documents. No stale Wave 4 lane references remained, and both diff checks passed. The change log
measured 20,244 tokens / 1,350 lines.

### Preserve legacy settings user edits

**Goal/outcome**: Make full disable's legacy no-sidecar fallback remove only scalar and environment values that still
match their tracked Forge values.

**Key changes**:

- Compared legacy scalar/environment values with their tracking entries before removal, preserving modified and absent
  values while still removing unchanged owned siblings.
- Retained hook and permission matching, the sidecar-backed path, settings-baseline selection, and successful tracking
  cleanup; added fail-first, unit, installer, Docker, and packaged-wheel coverage.

**Verification**: The marked regression failed on merged `main` at `f069226f`. After implementation, 148 focused
settings/installer/D019 regression tests and 105 CLI tests passed; the broader install slice passed 828 with one skip.
All 683 marked regressions, the targeted Docker disable case, the clean wheel lifecycle, and final `make pre-commit`
passed. Independent review found no violations and reran the 148 focused host tests, both targeted Docker installer
cases, Ruff, and the diff check. Shipped in PR #146 (`3f3a3c6d`).

### Preserve the installation settings baseline

**Goal/outcome**: Keep one pre-Forge Claude settings baseline across repeated enable/sync and both disable paths.

**Key changes**:

- Preserved the first settings baseline, including authoritative null, while collision-safe later snapshots remain
  rollback history instead of replacing it.
- Made full and runtime-scoped disable validate and read the tracked baseline before mutation; invalid paths retain
  ownership, and null legacy rows never adopt newer Forge-bearing history.

**Verification**: The retained regression failed on merged `main`. After implementation and review amendment, 826
installer/D012 tests (one skip), 109 focused CLI/regression tests, 682 regressions, and the targeted Docker and isolated
wheel lifecycles passed; final `make pre-commit` also passed. Independent review's one LOW tracked-baseline deletion
race is closed by direct decoding and a deterministic regression; its two informational observations remain unchanged.
Shipped in PR #145 (`f069226f`).

## 2026-08-07

### Restore Codex install transaction rollback

**Goal/outcome**: Restore every owned surface when Codex registration or the final install record fails.

**Key changes**:

- Kept an exact pre-write Codex config snapshot through apply, read-back, and tracking commit; rollback now restores
  bytes/mode or removes the attempt-created config together with settings ownership and new extension files.
- Preserved later config edits with an actionable incomplete-path error, while retaining best-effort conflicts and the
  direct merge helper's `OSError` boundary.

**Verification**: The marked regression failed on the base. After the fix, 74 focused, 921 broader installer/CLI (one
skip), 678 regression, and 8,818 unit tests (one skip) passed; an isolated wheel-installed enable/status/disable smoke
and final `make pre-commit` also passed. Independent review found no design violations and passed 793 install unit tests
plus all 6 Docker Codex installer tests. Shipped in PR #144 (`37a03209`).

### Close session/state safety and sequence installer transactions

**Goal/outcome**: Close the eight-member Wave 3 boundary and admit Wave 4 as three parked installer transaction fixes.

**Key changes**:

- Closed D010 and the session/durable-state epic after PR #142, then repointed their parent and review-ledger links.
- Reproduced D012--D014 and D019 on merged `main`, corrected D012's stale tracked-baseline claim, and sequenced Codex
  rollback, settings-baseline ownership, and legacy value-aware removal without activating implementation.

**Verification**: Four disposable broken-behavior characterizations and a separate two-run D012 characterization passed;
both temporary modules were removed. The Markdown hooks, a 236-file relative-link scan, and stale-lane and diff checks
passed; after compaction, the log measured approximately 19.3k tokens and 1,278 physical lines, below both size guides.

### Align the incognito worktree root guard

**Goal/outcome**: Apply the main-checkout guard to `session incognito --worktree` before launch while retaining the
repository-root guard for ordinary incognito.

**Verification**: D010 failed on `d2ed2349` with exit 0; then 12 focused, 23 Docker lifecycle, and 669 regression tests
plus `make pre-commit` passed. Shipped in PR #142 (`2461e3fa`).

### Reject unknown resume strategies

**Goal/outcome**: Reject unsupported transfer strategies before writes. `resume_session` rejects unknown values and
`rewind` and persists the value used; valid, native, and legacy-read paths are unchanged.

**Verification**: 107 host, 12 Docker, and 668 regression tests plus `make pre-commit` passed. Shipped in PR #141
(`d2ed2349`).

### Preserve newer-schema workqueue markers

**Goal/outcome**: Preserve newer-schema work and keep later current-schema markers reachable. Newer schemas remain
byte-exact without dispatch, retry, or poison; one diagnostic per process and the cursor advance preserve later work.

**Verification**: 82 focused, 10 Docker, 667 regression, and 8,804 unit tests plus `make pre-commit` passed. Shipped in
PR #140 (`ecc79aa2`).

### Prevent bounded queue starvation and publish wheel dependency floors

**Goal**: Let every resident queue window yield to later actionable work and make the clean wheel's LiteLLM runtime
dependencies explicit and security-patched.

**Key changes**:

- Added a persistent bounded-scan cursor for unreadable, lock-contended, and unhandled markers without changing
  retryable handler or validation failures.
- Replaced LiteLLM's proxy extra with the start-validated dependency set, capped compatibility at 1.95.0, and added a
  clean-wheel start/health/stop CI gate.

**Verification**: Unit tests passed (8,798 with one pre-existing platform skip and 118 deselected), regressions passed
(666), targeted startup-queue and LiteLLM integration passed (10), the clean Python 3.13 wheel smoke passed, and final
`make pre-commit` passed. Shipped in PR #139 (`de8adaac`).

### Preserve explicit deletion during headless Codex turns

**Goal**: Keep session deletion terminal when it lands during a long Codex start or resume without discarding the
completed turn result.

**Key changes**:

- Shared one post-turn manifest-presence guard across headless and interactive Codex frontends; deleted sessions return
  their completed runtime result with a warning and skip manifest/index fact reconciliation.
- Removed only empty or lock-only directory shells created by the exists-to-update race while preserving unrelated
  content and strict corruption, unreadability, and lock-timeout errors.
- Hoisted the existing non-autouse real-Codex-home integration fixture so core lifecycle and session-consumer E2Es both
  exercise the host subscription-auth path past the global test isolation fixture.

**Verification**: The marked O003 regression failed on `cce6e8c6` because the completed resume raised
`SessionFileNotFoundError` and recreated a lock-only session directory. Focused tests passed (72), Codex preflight was
ready, the live two-turn start/resume integration passed (1), and regressions passed (664). Independent review found no
production design violation, caught a stale fixture import that broke CLI integration collection, and admitted the
separate SessionStart receipt-shell race as D049. Post-amendment CLI integration collection (166), the focused suite
(72), and final `make pre-commit` passed. Shipped in PR #138 (`4a601dc2`).

### Retain sessions whose recorded worktree disappears

**Goal**: Keep a valid manifest authoritative for session identity while treating checkout presence as derived
launchability.

**Key changes**:

- Stopped list self-healing from pruning valid missing-worktree sessions and exposed derived launchability in terminal
  and `%session` list/show output without changing manifest or index schemas.
- Made repair republish valid degraded orphans through the existing identity, binding, collision, and unchanged-bytes
  transaction; clean reports them without deleting, while explicit delete remains available.
- Refused Claude and Codex resume, fork, relaunch, and shared launch paths before mutation when the recorded directory
  is unavailable; recreating the same path restores launchability automatically.

**Verification**: The marked D009 regression failed on `8ebdb644` because listing returned no session and deleted the
row accepted by direct lookup. Focused tests passed (398); complete Docker session-command and lifecycle files passed
(46 and 23); regressions passed (663); unit tests passed (8,790 with one pre-existing platform skip and 118 deselected);
the review-amendment slice passed (188); final `make pre-commit` passed. Independent review found no design violations.
Shipped in PR #137 (`cce6e8c6`).

## 2026-08-06

### Enforce launch-runtime override immutability

**Goal**: Prevent effective overrides from contradicting the raw runtime identity used for launcher dispatch.

**Key changes**:

- Rejected direct, parent-object, and wildcard writes that introduce `launch.runtime` before override or manifest
  mutation, using one actionable diagnostic.
- Preserved supported sibling launch overrides, whole-launch and nullable-field null clears, and reset-based cleanup of
  illegal runtime overrides written by older Forge versions.
- Kept raw intent as the dispatch authority and documented the immutable write boundary without changing consumer lanes
  or runtime creation flags.

**Verification**: The marked D008 regression failed on `00692356` because the parent-object write returned normally and
mutated the override dictionary. Focused override/CLI tests passed (113), Docker session-command integration passed
(45), regressions passed (662), and unit tests passed (8,771 with one pre-existing platform skip and 118 deselected).
Independent review found no design violations; its adjacent stale-override relaunch-inheritance observation is tracked
separately as D048 rather than assigning a scrub policy inside this fix. Final `make pre-commit` passed. Shipped in PR
#136 (`8ebdb644`).

### Reject non-object confirmed manifest state

**Goal**: Classify an explicitly present non-object `confirmed` section as manifest corruption without rewriting it.

**Key changes**:

- Validated the `confirmed` container before nested reads while preserving the missing-field legacy default.
- Kept repair and delete on their typed corruption paths; delete retains the manifest and session reservation, and the
  Docker CLI reports actionable stderr without a traceback.
- Synchronized the strict section-container contract in design and end-user session documentation without changing D009
  liveness or D011 read-error behavior.

**Verification**: The marked O006 regression failed with raw `AttributeError` on `6be815bf`; focused tests passed (95),
Docker session-command integration passed (44), regressions passed (661), and unit tests passed (8,751 with one
pre-existing platform skip and 118 deselected). Independent review found no design violations; its adjacent status-line
raw-reader observation is tracked separately as D047. Final `make pre-commit` passed. Shipped in PR #135 (`00692356`).

### Preserve unreadable JSON state classification

**Goal**: Distinguish transient JSON read failures from malformed content and preserve unreadable queue markers.

**Key changes**:

- Mapped shared JSON read `OSError` to `StateUnreadableError`; missing, malformed, and non-object outcomes stay
  distinct.
- Audited all five production callers: audit/team and Codex caches degrade to safe misses, spend-cap bootstrap visibly
  rebuilds, and unreadable workqueue markers remain byte-identical and pending.
- Added a structured queue diagnostic rendered on CLI stderr, preserved parseable foreground JSON and later-marker
  progress, and documented unreadable versus malformed, retry, and poison outcomes without implementing D021.
- Corrected stale GC exception docs and admitted the analogous proxy YAML misclassification as D046.

**Verification**: The marked D011 regression failed with `StateCorruptedError` on the branch base; focused tests passed
(198), Docker startup-queue integration passed (9), regressions passed (660), and unit tests passed (8,742 with one
pre-existing platform skip and 118 deselected). Independent review found no design violations; final `make pre-commit`
passed after Markdown normalization. Shipped in PR #134 (`6be815bf`).

### Close Stop/artifact work and sequence session/state safety

**Goal**: Close the shipped Wave 2 coordination record and admit Wave 3 as bounded, independently reviewable work.

**Key changes**:

- Closed the Stop/artifact epic after PR #132 shipped D039 and repointed its parent, member, and review-ledger links to
  the completed records.
- Reproduced D008–D011, D021–D022, O003, and O006 on merged `main`, then created one parked session/durable-state epic
  with eight ordered members and explicit regression/integration requirements.
- Kept every Wave 3 member in `todo/`; D011 is first in sequence, but no implementation card or checklist was activated.

**Verification**: One disposable pytest module passed eight assertions of the documented broken behavior and was removed
after the evidence was recorded; `make pre-commit-md` and `git diff --check` passed; relative board links were checked
after the lane moves and card creation.

### Repair sidecar shadow-drain routing

**Goal**: Make sidecar Stop candidate discovery and deferred host-drain routing use paths visible at their respective
execution boundaries.

**Key changes**:

- Probed pending shadow candidates through the hook process's mounted Forge root while retaining host worktree and
  Forge-root paths in the deferred marker.
- Preserved marker/candidate schemas, host-mode routing, and no-candidate inertness, with a marked D039 regression.
- Exercised the real sidecar Stop hook and then handled its host-visible marker through the host drain path.

**Verification**: PR #132 merged as `dc963a7c`; focused hook/shadow/workqueue tests passed (120); full sidecar hook
integration passed (4); regression suite passed (659); `make test-unit` passed (8,734 passed, 1 pre-existing platform
skip, 118 deselected); final `make pre-commit` passed after Markdown normalization.

## 2026-08-05

### Preserve transcript artifact identity

**Goal**: Keep transcript artifacts idempotent and schema-safe across Stop, rollover, adoption, and PreCompact.

**Key changes**:

- Reconciled canonical `(session_id, copied_path)` records through one session-layer writer without deleting distinct
  identities or replacing malformed durable state.
- Moved new PreCompact metadata exclusively to its compaction collection and added lazy migration for the recognized
  legacy mixed-list shape.
- Shared strict latest-canonical selection across manager derivation, transfer assembly, and both full-strategy budget
  preflights, with marked D007/D024 regressions and Docker hook coverage.
- Rejected explicit-null canonical state and incomplete dedicated snapshots without mutation, and moved manager fork
  validation ahead of Git branch/worktree creation.
- Made write-side legacy migration and PreCompact corruption visible at warning level, pinned retained-record tail
  ordering, and documented the intentionally tolerant supervisor and model-history projections.

**Verification**: PR #131 merged as `3e090ef5`; focused transcript/session suites passed (333); full regression suite
passed (658); `make test-unit` passed (8,734 passed, 1 pre-existing platform skip, 118 deselected); Docker artifact-hook
integration passed (12); final `make pre-commit` passed after Markdown normalization.

### Align Stop verification contract

**Goal**: Enforce the approved two-type Stop-verification schema without silent success or infrastructure-induced
blocking.

**Key changes**:

- Added strict authoring validation while preserving legacy unknown strings for visible non-passing fail-open handling.
- Kept the fixed no-shell test suite synchronous in the resolved session worktree, separated its wall time from
  Forge-owned overhead, and classified incomplete, configuration, and infrastructure outcomes explicitly.
- Made verification-state persistence failure visible and fail open so it cannot cause an infrastructure-induced block.
- Bounded and redacted captured diagnostics, added marked D006/U002/U003 regressions, and exercised the real Stop hook
  in Docker without activating the next Wave 2 member.

**Verification**: Focused Stop/config/model tests passed (166); full regression suite passed (649); `make test-unit`
passed (8,724 passed, 1 skipped); Docker policy-hook integration passed (22); `make pre-commit` passed.

### Preserve plus-prefixed Codex Write identity

**Goal**: Prevent valid plus-prefixed Codex file content from collapsing to an empty, reusable policy identity.

**Key changes**:

- Replaced the unified-diff extractor at the Codex apply-patch boundary with grammar-specific removal of exactly one
  transport `+`, preserving Add and Update content that begins with plus signs.
- Kept true unified-diff header handling and the existing fingerprint schema unchanged while restoring complete
  deterministic-policy input and distinct semantic cache identity.
- Extended D005 regression coverage across both semantic cache layers and recorded the correction without reopening the
  shipped Wave 1 epic.

**Verification**: Focused parser/adapter/policy tests passed (76); full regression suite passed (643); `make test-unit`
passed (8,712 passed, 1 skipped); Docker policy-hook integration passed (21); `make pre-commit` passed.

### Close policy wave and sequence Stop/artifact work

**Goal**: Close the shipped policy/supervision wave and admit Wave 2 as bounded, independently reviewable work.

**Key changes**:

- Closed the policy/supervision epic after PRs #125–#127 shipped all three members and repointed its parent, member, and
  review-ledger links to the completed record.
- Reproduced D006–D007 and characterized D024/D039 on merged `main`, then created one parked Stop/artifact epic with
  separate verification, transcript-artifact, and sidecar-shadow members.
- Kept every Wave 2 member in `todo/`; no implementation card or execution checklist was activated.

**Verification**: Four isolated executable characterizations passed; `make pre-commit-md` and `git diff --check` passed;
relative board links were checked after the lane move and card creation.

### Preserve complete supervisor edit identity

**Goal**: Prevent materially different edits from sharing a semantic supervisor or plan-check clean allow.

**Key changes**:

- Added a versioned canonical action fingerprint computed before adapter presentation truncation, shared by the frontier
  and tier-1 cache paths and frozen into shadow replay candidates.
- Included Claude matched and replacement fragments in the bounded frontier prompt while retaining Codex raw-diff
  context and deterministic policies' existing `new_content` input.
- Added a marked D005 regression for Claude removed text, Codex delete-only hunks, and both runtimes' post-truncation
  tails; left D026 configuration reconstruction and whole-file deletion behavior unchanged.

**Verification**: Focused identity/policy/hook tests passed (304); full regression suite passed (641); `make test-unit`
passed (8,709 passed, 1 skipped); Docker policy-hook integration passed (21); `make pre-commit` passed.

## 2026-07-22 -- 2026-08-04 (compacted)

Session transaction safety, runtime-scoped extensions, proxy/config seams, workspace/adoption surfaces, model and
workflow refreshes, and the repository-maintenance decision gate. Detailed history remains in the matching done cards
and PRs; this summary preserves the contracts, verification anchors, compatibility decisions, and deferred items.

- **Maintenance decision and policy boundaries (08-04):** approved the Stop verification, missing-worktree liveness,
  downstream retention, and evidence-based deletion gates; admitted 13 bounded members while keeping shipped design docs
  authoritative until implementation. Semantic supervisor verdicts became exact and observable, malformed confidence
  degrades safely, throttle reuse accepts only clean aligned/1.0 state, and terminal bundle re-enable preserves
  session-owned supervisor configuration. Verification covered 321 focused policy/supervision, 47 hook-adapter, 8,702
  unit (one skip), 632 regression, 21 Docker policy-hook checks, Markdown, links, lanes, and pre-commit.
- **Git-derived workspace worktrees (08-03):** added strict porcelain-z worktree parsing, common-directory identity,
  occupancy joins, and `forge workspace worktrees [--json]` without persisting a second workspace identity; Git
  discovery moved to an acyclic shared leaf. Activity aggregation and `workspace status` remained gated on root-scoped
  telemetry. PR #122 (`a5aee0a9`) passed 99 focused, 8,680 unit (one skip), 38 integration, and pre-commit checks.
- **Proxy ingress and config wiring (08-02):** centralized wire shapes and proxy-block coercion/field registration,
  extracted Anthropic passthrough ingress, and moved `forge info` to its CLI owner. The guards exposed and fixed dropped
  template costs, a missing GPT-5.5 Pro catalog entry, and an unrouted local-LiteLLM fixture. Verification: 8,655 unit,
  12 proxy/session integration, and pre-commit.
- **Session orphan repair (08-02):** added preview-default, root-scoped `forge session repair` with explicit repairable,
  missing-worktree, collision, corrupt, unreadable, and unrepairable outcomes; apply uses hash-verified transactional
  publication and fails closed on raced identity or bindings. PR #120 passed 8,639 unit, 117 component integration, 22
  Docker lifecycle/adoption checks, and pre-commit.
- **Crash-atomic session creation and serialized deletion (08-01--08-02):** made index-row-first `create_session_txn`
  span all five creation sites with in-lock compensation and residue retry; strengthened binding scans, replacement
  ownership, adoption rollback, and force-fork/delete coordination. Terminal deletion now holds index then manifest
  locks and removes the manifest before its row. Review reproduced and fixed seven transaction defects; 9,176
  unit/regression (one skip), 117 component integration, 22 Docker session/adoption checks, focused deletion coverage,
  and pre-commit passed. Pre-existing orphan repair shipped separately the next day.
- **Runtime-scoped extension ownership and disable (07-30--07-31):** schema-v3 `(module, runtime)` attribution now
  drives enable, sync, status, and partial removal while legacy unattributed rows remain non-targetable. Runtime-scoped
  disable uses reversible settings/sidecar unmerge, guarded Codex marker removal, truthful partial reconciliation, and
  recovery when tracking writes fail. A changed `CODEX_HOME` refuses before mutation and names both config paths; older
  already-orphaned blocks remain a manual limitation. Verification peaked at 3,366 focused, 8,581 unit (one skip, 117
  deselected), 551 regression, 21 Docker lifecycle checks, builds, and pre-commit.
- **README capability truth (07-28):** corrected worktree placement, clean preview behavior, opt-in memory, and proxy
  auto-start guidance; documented Codex-supervised Claude execution, consumer lanes, cost/wire control, skills, and all
  CLI groups. Links, anchors, live help, lane labels, and Markdown passed. The documented Codex-supervisor sequence
  remained code-verified rather than live, and the preflight-cache TTL nuance stayed omitted.
- **Native session adoption (07-27):** added evidence-selected Claude/Codex adoption, directory verification, global
  conversation locking plus index binding uniqueness, exclusive manifest reservation, and native transcript preservation
  on deletion. PR coverage included 9,034 unit/regression (one environmental skip), 45 integrations, and two real-Claude
  Docker gates. Crash atomicity across manifest/index was deferred here and closed by the 08-01 transaction work.
- **July model refresh (07-26):** promoted Claude Opus 5, Kimi K3, Qwen3.7, and Gemini 3.6 Flash; clamped derived
  reasoning to catalog-supported efforts, retained displaced models as alternatives, removed dead Gemini 2.0 Flash
  defaults, and raised LiteLLM to 1.88.0 while relying on remote pricing until v1.94. Live Opus/Kimi/Gemini checks
  passed; Qwen remained blocked by account data-policy settings and one local OpenAI control failed identically on
  `main`. Unit, regression, build, live LiteLLM, and pre-commit gates passed.
- **Policy shared-library seam (07-24):** shared provider-aware direct-LLM transport without moving caller-owned
  parsing, telemetry, or failure behavior; consolidated confidence/citation, lane, and resume-ID rules; applied the D7
  team threshold, pre-commit routing, and executor model-pin contracts. Verification: 449 focused, 8,314 unit (one skip,
  117 deselected), 529 regression, 32 Docker policy/team-hook checks, mypy, pyright, and pre-commit.
- **Runtime-neutral workflow workers (07-22--07-23):** added opt-in read-only Codex workers, one invocation readiness
  snapshot, grouped mixed-runtime lifecycle ownership, runtime-native auth/billing/error attribution, and nine portable
  workflow packages without changing Claude defaults or quorum. PR #110 merged as `26122901`; 731 focused, 8,277 unit
  (one skip, 117 deselected), Codex/mixed/Claude integrations, clean runtime-scoped wheel lifecycles, QA/walkthrough,
  build, pre-commit, link, and lane checks passed.
- **Unmanaged skill packages (07-22):** added one-snapshot discovery, per-package recovery, status schema v2, and
  provenance/tree/ownership-gated cleanup; unsafe roots remain report-only, while the marker digest and status top-level
  shape were explicit research-preview breaks. PR #109 merged as `cbb58e16`; 289 acceptance, 170 related, 8,230 unit
  (one skip), 522 regression, one wheel Docker lifecycle, build, pre-commit, QA/walkthrough, link, lane, and diff checks
  passed.

## 2026-07-10 -- 2026-07-17 (compacted)

Global-runtime closeout, cross-runtime skill packaging, model-catalog refresh, and memory-passport hardening. Detailed
execution history remains in the matching done cards and PRs; this summary preserves the goals, decisions, verification
anchors, and deferred items.

- **Cross-runtime skill packages (07-16--07-17):** compiled one typed neutral skill source into native Claude and Codex
  packages, with five portable skills and six explicit Claude-only skills; added runtime/scope/profile planning,
  content-addressed caching, schema-v2 ownership tracking, rollback, duplicate classification, and clean wheel/sdist
  lifecycles. Review hardening made explicit runtime narrowing preserve omitted packages, rejected symlinked roots and
  descendants, cross-validated canonical file ledgers, required successful exact-evidence Codex probes, and kept model
  family selection host-authoritative. Durable selection, compiler, ownership, symlink, and cache invariants were
  promoted at closeout. Verification peaked at 381 affected, 8,158 unit (one skip), and 521 regression tests, plus two
  Docker lifecycle cases, real-Codex stages, QA v1.0.30/589 assertions, builds, and pre-commit. Shipped in PR #107
  (d2a94bf7).
- **GPT-5.6 catalog and Sol defaults (07-16):** added Sol, Terra, and Luna profiles and aliases, promoted Sol across
  bundled OpenAI defaults/templates and fresh LiteLLM routes, preserved existing user-owned snapshots, and synchronized
  workflows, skills, docs, and package assets. Verification covered 611 focused tests, 8k-scale unit runs, two targeted
  provider integrations, builds, clean wheel/sdist installs, and pre-commit. Live direct OpenAI validation remained
  environment-limited by a 401 key response, and remote LiteLLM credentials were unavailable.
- **Memory-passport CLI preflight (07-16):** consolidated project-root, compatibility, path-safety, and file preflight
  behind a structured private resolver while preserving leaf wording, rendering, mutation, and stream precedence.
  Focused CLI (228), unit (7,907 with one skip), pre-commit, Markdown, and diff checks passed. Shipped in PR #105
  (9288bed2).
- **OKF-compatible memory passports (07-14--07-15):** added creation-only OKF v0.1 concept envelopes and an explicit
  idempotent passport upgrade while keeping ordinary re-track non-migrating and avoiding bundle-conformance claims.
  Remediation unified delimiter parsing, rejected blank intent and unsafe frontmatter, case-folded logical/resolved
  reserved targets, preserved modes through atomic writes, and blocked existing shadow-only reserved paths before any
  mutation. The proposed non-identical CLI preflight cleanup shipped separately in PR #105. Verification across commits
  fae54345 and 58b7e97 included 7.8k-scale unit runs, 500-plus regressions, handoff/installer integration, builds,
  isolated wheel/sdist enables, packaged walkthrough smokes, pre-commit, and diff checks. The reviewed mutation-boundary
  lessons remain proposed in `.forge/memory/shadow_impl_notes.md` pending promotion.
- **Global Forge runtime epic (07-13):** closed the five shipped hook-ownership, binary-resolution, migration, and
  execution-environment seams; synchronized normative docs and inbound links; added the retired lane and retired
  unshipped T2 as superseded. GUI-safe status-line reachability remained a standalone proposed follow-up. PR #99
  (168b7db7), 285 focused tests (one skip), 17 Docker installer cases, 86 closeout checks, pre-commit, link, lane, and
  diff sweeps verified the closeout.
- **Project compatibility mutator sweep (07-12):** enforced each target state owner's Forge root across session, policy,
  transfer, memory, search, cleanup, hook, and detached-writer mutations while retaining narrow global registry and
  proven-stale index exemptions. Managed-worktree refusal became atomic, and partial cleanup reports compatibility skips
  truthfully. PR #98 (aa45114d), 7,724 unit tests (one skip), 151 targeted integrations, 35 focused regressions, and
  pre-commit passed. The real Claude-to-Codex bridge stopped at an isolated CODEX_HOME key-readiness gate; host
  preflight was healthy and no product change remained pending.
- **Checkout runtime override (07-12):** added process-scoped FORGE_DEV checkout dispatch with fail-closed
  invalid-target exit 127, preserved stable custom launchers through a four-step recording transition, diagnosed
  override validity/effectiveness, and synchronized public environment guidance. PR #97 (46ff9ef6), 308 focused tests,
  17 Docker cases, wheel/sdist and uv-tool smokes, live valid/invalid dispatcher checks, pre-commit, Markdown, link, and
  lane checks verified implementation and closeout.
- **Hook migration cleanup (07-10--07-11):** added explicit preview/apply cleanup for pre-user-scope installations,
  selected one tracked root without implicitly mutating others, migrated canonical Claude/Codex ownership with backup
  and re-trust guidance, enrolled the root last with backfill provenance, and surfaced independent cleanup state without
  broadening genuine double-hook diagnostics. PR #96 (93312179), 320 migration tests, 68 CLI guards, 7,556 unit tests
  (one skip), Docker and real-Claude migration coverage, an isolated walkthrough, pre-commit, Markdown, link, lane, and
  diff checks verified implementation and closeout. T8 remained parked at that closeout and shipped separately the next
  day.
- **Sidecar hook resolution (07-10):** restored Forge runtime hooks inside Claude sidecars through canonical persisted
  hook staging, idempotent entrypoint auth merging, image PATH resolution, and a host-drainable deferred queue with path
  normalization and container drain suppression. Stale-image skew and PATH breadth remained explicit follow-ups.
  Verification included 7,517 unit tests (one skip), three targeted sidecar integrations, pre-commit, all PR #94 GitHub
  checks, Markdown, and post-merge link/lane scans.

## 2026-07-01 -- 2026-07-08 (compacted)

Global-runtime foundations, session/rewind work, CLI boundary cleanup, and model/backend changes. Detailed execution
history remains in the matching `docs/board/done/` cards and PRs; this summary preserves the goals, decisions,
verification anchors, and deferred items.

- **Global install and runtime hooks (07-06--07-08)**: made global-tool installation the Day-1 path and added read-only
  `forge extension doctor` install-kind/PATH diagnostics; removed the untracked `forge hook enable|disable` writer;
  single-sourced Forge hook matching and pinned registered command bytes; then shipped the fail-open
  `~/.forge/bin/forge-hook` dispatcher and moved Claude/Codex runtime-hook ownership to user scope. Project/local
  installs retained project settings such as `statusLine`, old project/local hook rows stayed removable, and detection
  accepted both dispatcher and legacy command forms while diagnosing logical double-fire risk. Decisions: minimal-PATH
  status is a reported fact, dispatcher drift is doctor-owned, and legacy user-local settings were a clean break. At
  closeout, T10 sidecar resolution and T6 migration cleanup were next and T8 remained parked. Verification: full unit
  runs around 7.5k tests, focused install/hook/doctor/regression suites, Docker installer and real-Claude hook
  integrations, dispatcher latency characterization, and `make pre-commit`.
- **Project and environment contracts (07-07)**: established `~/.forge/projects.json` as the locked trusted-root
  registry and `.forge/project.toml` as an opt-in hand-edited compatibility pin enforced by extension/session paths and
  surfaced by doctor. Uncovered confirmed-state, memory-writer, and proxy/backend mutators moved to the accepted
  `forge_project_compat_mutator_sweep` follow-up. The public/internal `FORGE_*` vocabulary was documented and guarded
  across CLI and user docs so normal guidance names sessions and CLI flags rather than internal wiring. Verification:
  355-test and 38-test focused suites, three named Docker checks, 169 env-vocabulary/CLI tests, pyright, Markdown hooks,
  and `make pre-commit`.
- **Shared proxy, policy, and test seams (07-06)**: single-sourced raw tier-word detection while deliberately preserving
  display-name fallback behavior; unified message/count-token model resolution and loopback port probing without
  changing routing, cost, or caller exception contracts; moved policy-supervisor mutations behind UI-free ops; and
  consolidated session inheritance, runtime/lane, TDD-sort, supervisor-option, and hook-capture twins. Test mirrors and
  support helpers were reorganized, fixing the surfaced status-line role-alias miscount and malformed transcript-path
  leak. Verification: focused suites from 392 to 1,045 tests, a 7,379-test unit run, proxy/status-line/policy/hook
  Docker integrations, and `make pre-commit`.
- **Durable state and session-test structure (07-05)**: hoisted atomic byte/text writes, JSONL append/retention, and
  versioned reads into core leaves while keeping telemetry planes and schemas separate; unreadable search state now maps
  to domain errors and all-scope search skips unreadable project indexes. The 4,933-line session CLI test catch-all was
  split by command family with a narrow shared launcher fixture. Verification: focused state/search/install/backend
  suites, full unit tests, targeted search/proxy/backend integrations, merged PR #77 layout checks, and
  `make pre-commit`.
- **Rewind and session-layer extraction (07-02--07-05)**: shipped PR #66 rewind resume/fork using a fresh UUID,
  turn-boundary-truncated native history, and an AI code delta over dropped turns; interleaved history fails closed,
  code-delta failure falls back to native relocation, and fork rewind remains worktree/`--into` only. PR #68 then
  excluded `rewind` from transfer-context parsers before expensive preflight. A real-Claude Docker gate later closed the
  disclosed truncated-prefix gap without mutating the prefix. In parallel, session preflight/model-pin helpers and fork
  supervisor wiring moved behind core seams, the parent CLI shim was retired, and sidecar sandbox confirmation was
  delayed until immediately before launch. Verification: rewind/fork units, 2,681 CLI/regression tests, 21 lifecycle and
  10 supervisor Docker tests, the real-Claude rewind integration, and `make pre-commit`.
- **CLI and backend boundaries (07-03--07-04)**: routed top-level errors/diagnostics to stderr; made bare
  `policy enable` fail loudly without `--bundle`; replaced activity `--days|--all` with `--period today|week|month|all`;
  split logs into scriptable `show` and preview-default `clean`; and normalized help/lane errors. Backend stop now
  targets live runtime instance ids, while delete remains adapter-config ownership. The backend identity clean break
  made `proxy.backend` canonical, upgraded backend/downstream schemas to v2, and separated backend instance, managed
  process, and telemetry origin fields. Verification: 2,207 CLI tests, 7.3k unit tests, 482 regressions, focused
  command/help/stream tests, targeted integration, and `make pre-commit`.
- **Accidental-complexity closeout (07-01--07-04)**: removed verified dead code and duplicate workflow templates/search
  scoring/secrets plumbing, narrowed proxy providers to `litellm|openrouter`, and made malformed legacy proxy/template
  config fail contextually. Fixed backend delete's double-stop, live session activity reporting, the auth-retry
  provider-trace hole, and fail-open supervisor exit status; demoted the test-only workflow policy surface and corrected
  the marker schema to v1. Decisions: retain `SearchDocument.tokens`, accept-and-ignore the legacy passport key, keep
  the real Env+File credential chain, and put shared telemetry vocabulary in a neutral leaf to avoid a cycle. Deferred:
  a durable `server.py` extraction and a separately proposed workflow-policy CLI graduation. Verification: full unit
  runs from 7,222 tests upward, focused suites and integration checks, manual malformed-config repros, adversarial
  review, static checks, and `make pre-commit`.
- **Model catalog and defaults (07-01)**: added Claude Sonnet 5, promoted Sonnet 5/Opus 4.8 across Anthropic and
  OpenRouter defaults/templates, retained older models as alternatives, updated context-estimator defaults, and allowed
  any Claude pin through Anthropic passthrough. Verification: 7,231 unit tests, 470 focused tests, two Docker model-pin
  smokes, the passthrough regression, and `make pre-commit`. Shipped in PR #64.
- **Consumer lanes closeout (07-01--07-02)**: completed the lane contract and the memory-writer Codex dispatch arm.
  Memory writing resolves its runtime before Claude availability, uses read-only or workspace-write Codex sandboxes,
  degrades asynchronously, and leaves spawned-run telemetry to the invoker. Team-supervisor Codex dispatch was carved
  out because Codex lacks Claude's resume-based plan context; runtime-neutral plan/context delivery remained the
  explicit follow-up rather than holding the lane substrate open. Verification: 189 unit/bridge tests, two live Codex
  E2Es with one subscription-quota event and no duplicate upstream row, board-link checks, and `make pre-commit`.

## 2026-06-22 -- 2026-06-30 (compacted)

Consumer lanes, state boundaries, CLI taxonomy, and Codex proxy launch. Detailed evidence remains in the matching done
cards and PRs.

- **Consumer lanes T0--T7:** added `chatgpt`/`claude-max` subscription sources, pure lane vocabulary, frozen bindings,
  lane CLI, Codex supervisor/curation dispatch, billing, and sticky fail-open fallback. Runtime-native auth remained
  endpoint semantics; direct lanes bypass proxies; aux bindings freeze on dispatch. Memory-writer/team-supervisor Codex
  work and live exhaustion/release checks stayed deferred. Focused suites, ~7k unit tests, Docker real-Claude, and a
  host Codex curation smoke passed.
- **State boundaries:** split corruption from transient unreadability, added guarded cleanup/recovery, and made targeted
  paths propagate actionable failures while best-effort scans may degrade. Corrupt/unreadable regressions, 6.9k--7.3k
  unit/regression runs, review fixes, and pre-commit passed.
- **CLI cleanup:** moved session/telemetry/model commands to their durable taxonomy, removed stale aliases/surfaces,
  normalized groups, errors, destructive prompts, config parity, and JSON streams. Kept aliases are
  `ext`/`sess`/`mem`/`cfg`; clean breaks use Click errors. CLI invariants, Docker integration, build, and pre-commit
  passed.
- **Codex proxy launch:** shipped status, byte-preserving Responses ingress, and proxied start with capability and proxy
  identity gates, generation-only accounting, and proxy-owned auth. Unit/CLI suites, a real Codex-to-Forge request, and
  pre-commit passed; a live 200 reasoning round-trip remained blocked by the unavailable key.
- **Checker fixture:** corrected the plan from create to overwrite; the Docker supervisor E2E passed 10/10 and repeated
  real-checker runs.

## 2026-06-18 -- 2026-06-20 (compacted)

Telemetry backend-attribution and remote-reconciliation arc; detailed history remains in the matching done cards.

- Split telemetry into downstream attempts and upstream outcomes, added two-pane activity/shared measurement, and made
  cap bootstrap use the maximum durable source. `ModelSource` owns endpoint/auth/lifecycle; backend identity stays
  distinct from writer origin and local LiteLLM is display-only.
- Generalized provider grouping and metadata-only remote reconciliation; failures render unavailable, direct grouping
  has one global opt-in, and per-proxy preview keys were removed. Custom-template credential preflight stayed deferred.
  Focused/live provider-trace and sidecar Docker checks, static checks, and pre-commit verified PR #39.

## 2026-05-22 -- 2026-06-16 (compacted)

Runtime, Codex frontend, transfer, proxy observability, and status-line foundations; detailed history remains in the
matching done cards and PRs.

- Added rooted run/usage identity, shared invocation, frozen actions, schema-backed transfer, passports, native
  relocation, Codex lifecycle/TUI/hooks, supervisor controls, redacted provider traces, and status-line health.
  Initial-message delivery and scoped enrollment stayed canonical; costs became reported-or-unavailable.
- Deferred app-server transport, upstream fail-open, PermissionRequest research, path rewriting, sidecar/default native
  relocation, direct provider callers, and parse/auth fail-opens. Roughly 6.1k--6.4k unit tests, regressions, static and
  pre-commit checks, plus focused real provider/Codex policy, transfer, generation, cancellation, and launch paths
  verified the arc.
