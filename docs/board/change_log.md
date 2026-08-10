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

## 2026-08-04

### Harden semantic supervisor verdict boundary

**Goal**: Prevent malformed external verdict data from denying, escaping into fail-closed handling, or masquerading as a
clean aligned result.

**Key changes**:

- Made verdict literals exact and observable, degraded malformed confidence to low confidence, filtered invalid
  violation elements, and shared normalized citations between the displayed violation and block predicate.
- Made restored throttle reuse strict: only the clean aligned/`1.0` write shape is reused; malformed or non-aligned
  state re-evaluates.
- Added one marked regression module for each of D002, D003, D004, and O028, covering direct enforcement, both engine
  fail modes, cache eligibility, telemetry, shadow classification, and valid controls.

**Verification**: Focused policy/supervision tests passed (321); hook-adapter tests passed (47); full regression suite
passed (632); `make test-unit` passed (8,702 passed, 1 skipped); Docker policy-hook integration passed (21);
`make pre-commit` passed after the review follow-up.

### Preserve policy intent on enable

**Goal**: Prevent terminal bundle re-enablement from silently deleting session-owned semantic and team supervisor
configuration.

**Key changes**:

- Changed `forge policy enable` to update only its four bundle-owned fields on the existing policy intent, creating a
  default intent only when none exists.
- Added regressions for preserving non-default supervisor configurations, replacing requested bundle fields, and the
  absent-policy path; `%policy` override ownership remains unchanged.

**Verification**: Focused policy and hook unit suite passed (252); full regression suite passed (595); Docker
policy-hook integration passed (21); `make pre-commit` passed.

### Repository maintenance decision wave

**Goal**: Resolve the four design gates from the combined whole-repository review before behavior changes or cleanup
deletions enter implementation.

**Key changes**:

- Approved the Stop verification latency/schema contract, manifest-owned missing-worktree liveness, global downstream
  retention ownership, and evidence-based deletion compatibility rubric.
- Corrected the shipped verification documentation, added the deletion-evidence standard, admitted U002/U003 with
  severity, and preserved design docs as shipped truth for DG2/DG3 until their code changes land.
- Created 13 accepted implementation members, moved DG1–DG4 to `done/`, and kept the repository-maintenance epic active
  for later execution waves.

**Verification**: `make pre-commit-md` and `git diff --check` passed; board links and lane references were checked after
the moves.

## 2026-08-03

### Git-derived workspace worktree view

**Goal**: Expose the complete Git worktree family with Forge session occupancy, including empty and currently missing
registered worktrees, without persisting a second workspace identity.

**Key changes**:

- Added a strict `git worktree list --porcelain -z` resolver with common-directory identity, exact path normalization,
  newline-safe parsing, bare-primary support, independent locked/prunable/availability facts, and a non-Git-only
  single-directory fallback.
- Added the UI-agnostic index join and `forge workspace worktrees [--json]`; counts include incognito and legacy index
  rows, preserve same-name sessions as separate occupants, and use existing active-session liveness.
- Moved Git executable and logical-repository path discovery into an acyclic leaf shared by execution context and
  worktree operations, then repointed the branch-in-use guard through the shared parser. Integration coverage preserves
  both the plain existing-branch error and the carrying-worktree variant.
- Kept the read exempt from retention cleanup, documented the deliberate one-leaf CLI exception, added end-user/design
  and QA coverage, and left activity aggregation plus `workspace status` blocked on root-scoped telemetry identity.

**Verification**: focused Git/workspace/session/CLI tests passed (99); `make test-unit` passed (8,680 passed, 1
skipped); required integration runner passed (38); `make pre-commit` passed. Shipped via PR #122 (`a5aee0a9`);
post-merge stale-lane sweep, `make pre-commit-md`, and `git diff --check` passed.

## 2026-08-02

### Proxy ingress + config wiring refactor (proxy_ingress_and_config_wiring)

**Goal**: Close the silent-drop bug class in per-proxy config wiring, single-source the wire-shape vocabulary, and
extract the anthropic passthrough ingress from `server.py` -- one card, five slices (B1, B3, B2, B4, A1).

**Key changes**:

- `core/wire_shapes.py` vocabulary leaf (shapes, `VALID_WIRE_SHAPES`, `PASSTHROUGH_WIRE_SHAPES`, default); all
  code-literal sites repointed, including env.py's half-centralized local constants.
- `PROXY_BLOCK_COERCERS`/`PROXY_BLOCK_FIELDS` registry in `config/schema.py` now drives both `__post_init__` coercion
  sequences, both loader hops, and `create_proxy_file` -- adding a block field is one registry entry, and
  `tests/src/config/test_proxy_block_wiring.py` forces live-read coverage to grow with it.
- `forge info` moved to `cli/info.py` (`install/cli.py` deleted); claude-version parse deduped through
  `install/version.py::get_claude_runtime_version`.
- `proxy/passthrough_ingress.py` extraction mirroring `responses_ingress.py`'s lazy-import pattern; a characterization
  test pinned cost->metrics order and wire-byte fidelity before the move (server.py 2361 -> 2088 lines).
- Three bugs found by the card's guards: `create_proxy_file` dropped template-declared `costs` (regression:
  `tests/regression/test_bug_create_proxy_file_costs_drop.py`); `gpt-5.5-pro` missing from `OPENAI_MODELS`; the
  `proxy_server_local_openai` integration fixture never routed `litellm_local` (template-only start, no
  `FORGE_PROXY_ID`), so it 500'd without `LITELLM_BASE_URL` set -- pre-existing on `main`, fixed by registering the
  proxy with its isolated upstream.

**Verification**: Full unit suite 8,655 passed; integration gate 12 passed (`test_proxy_local_litellm_e2e.py` +
`test_session_routing_e2e.py`); `make pre-commit` clean.

### Session orphan manifest repair (`forge session repair`)

**Goal**: Surface and re-index manifest-only session orphans -- invisible to `session list` yet still owning their name
and conversation binding -- covering both crash-era residue and the live producer (the `list_sessions` prune dropping
worktree-vanished rows).

**Key changes**:

- New preview-default `forge session repair` (`--yes` to apply, `--json`), scoped to the current Forge root. Six
  classifications: `repairable`, `missing-worktree` (report-only -- never publish a row the prune immediately deletes),
  `collision`, `corrupt` (owned by `forge clean`), `unreadable` (owned by neither), `unrepairable`. Per-item apply
  refusals; exit 1 on any refusal or failure.
- Apply publishes through `create_session_txn(require_uuid_unbound=True)` with a hash-verified callback
  (`SessionStore.update_if_unchanged`): apply-time identity is a content hash -- total over id-less manifests -- and a
  raced manifest fails the callback so compensation removes the row.
- Row identity derives from the manifest's **recorded** worktree metadata per session shape (ordinary, nested-project
  worktree, root-level worktree, `--into` guest); a moved ordinary checkout re-derives from its actual location,
  correcting `worktree.path` and `forge_root` on disk while preserving `confirmed.claude_project_root` (Claude's
  conversation namespace does not move with the checkout).
- Collision detection uses the three-source binding scans (`collect_bound_uuids`/`collect_bound_codex_threads` without
  the per-root orphan walk); review round 3 found column-only maps allowed a second binding when a row lagged its
  manifest.
- `SessionStore.read()` now rejects non-object JSON and directory/name mismatches as `ManifestCorruptedError`, giving
  repair and `forge clean` the same D4 ownership of both shapes.

**Verification**: unit suite 8,639 passed; CIT tier (`-m integration`) 117 passed; Docker `test_session_lifecycle.py` 22
passed including an end-to-end repair round-trip; `make pre-commit` clean. PR #120.

### Serialize session manifest deletion

**Goal**: Prevent an in-flight manifest update from recreating a deleted session after its index row is removed.

**Key changes**:

- Terminal deletion now holds the index lock while taking the manifest lock, removes the canonical manifest before the
  index row, and only then cleans up the session directory. A manifest-lock failure leaves the complete session intact;
  a later cleanup failure leaves only a prunable index row.
- Adoption rollback uses the same terminal transaction, closing its gap between index-row removal and manifest cleanup.
- The public storage contract now distinguishes read-first `update`, transaction-owned `create_exclusive`, and
  unconditional low-level `write`; deletion's possible five-second global-index contention is explicit. The deletion
  schedule has its own regression file, and adoption rollback reports the defensive replacement-owner outcome.

**Verification**: focused session/adoption coverage (130 passed), `make test-unit` (8587 passed, 1 skipped),
`make test-regression` (593 passed), component integration (`pytest tests/src -m integration`, 117 passed), Docker
session/adoption integration (22 passed), and `make pre-commit` clean.

## 2026-08-01

### Crash-atomic session creation

**Goal**: Stop a process killed mid-creation from leaving a session manifest with no index row -- an orphan nothing
lists, which still owns its name and its conversation binding.

**Key changes**:

- `IndexStore.create_session_txn` holds the index lock across both durable writes, **row first**, then the manifest via
  a caller-supplied callback, with in-lock compensation if the callback raises. All five creation sites use it
  (`start_session`, `_persist_resume_child`, `fork_session`, `relaunch_session`, `_restore_previous_target_state`),
  which collapses their per-site rollback blocks: the manifest write is now the last durable action, so a failure cannot
  leave one behind.
- A crash now leaves a prunable row. The transaction self-heals it: row-present + manifest-absent under the held lock
  can only be residue, so it is pruned and creation proceeds -- a direct same-name retry succeeds with no intervening
  `session list` or `session delete`. The prune runs before the `require_uuid_unbound` scan, so residue never blocks
  rebinding its own conversation.
- New `IndexStore.live_session_exists` (row **and** manifest) replaces the row-only pre-check at all four sites that
  hard-failed on it; `_name_is_taken` keeps the row-only check, where a residue name costs an auto-name suffix.
- `collect_bound_codex_threads` now reads the `codex_thread_id` column as well as manifests. Reading only manifests
  would report an in-flight adopted thread as free once the row precedes its manifest.
- `_restore_previous_target_state` restores with `create_exclusive`, not `write`: its old unlocked `exists()` guard
  meant the write never overwrote anything, and keeping `write` let a failed fork clobber a concurrent winner.
- Compensation keeps the row only on proof that *this* transaction published the manifest: nothing at the path before
  the callback, something there after. Neither half alone is enough -- an exception does not mean the write failed
  (`atomic_write_json` makes it durable at `os.replace`, and a signal can arrive later), and a manifest being present
  does not mean it is ours (a pre-existing orphan owns the path in exactly the case `create_exclusive` rejects).
  Compensation also never raises, for `BaseException` too, so it cannot replace the error it is unwinding.
- Deletion is coordinated with creation rather than assumed away. `delete_session` removes the manifest (or the worktree
  holding it) before its row, so mid-delete the name reads as residue and a concurrent create can reclaim it.
  `IndexStore.delete_session_txn` now removes the row and runs the manifest delete inside one index-lock scope, and
  declines outright once a replacement owns the name. The ownership signal is derived from what the delete does --
  manifest absent at entry, or provably inside the worktree being removed -- not from a filesystem probe, which a
  replacement can flip.
- `fork --force` reaches the same window through its own path and now uses the same primitive. After freeing the stale
  target it cleared the name with an unconditional `delete()`, so a creator that claimed the freed name lost its
  manifest and then its row to fork's own residue prune -- fork destroying a live session and taking its name. It now
  declines with `SessionExistsError` instead.
- design.md §3.2, `session/__init__.py`, and the `create_exclusive` / binding-scan docstrings describe the shipped
  ordering, including the delete-coordination contract. Repair of pre-existing orphans is split out to
  `proposed/session_orphan_manifest_repair`, because index identity fields cannot be derived from a manifest.

**Verification**: `tests/src` + `tests/regression` 9176 passed, 1 skipped, plus the component-integration tier
(`pytest tests/src -m integration`) 117 passed -- that tier is deselected by `-m "not integration"` and hid two
model-drift failures through two review rounds, so it is part of this card's gate. New
`tests/regression/test_bug_session_create_crash_atomicity.py` (37 tests) covers compensation and crash-residue as
separate families, interrupt-after-durable-manifest, compensation-write failure, delete/create coordination, the fork
stale-target schedule, a `threading.Barrier` double create, the pruner race guard, per-path compensation through the
real transaction, and the explicit-name retry. Every guard carries a mutation check confirming it is load-bearing.
Docker `test_session_lifecycle.py` + `test_adopt_binding_contract.py` 22 passed. `make pre-commit` clean.

**Review**: three adversarial rounds found seven defects in the implementation (five HIGH, one MEDIUM, one LOW), all
reproduced before fixing; see the card checklist's review-round sections. Six of the seven were the same root error -- a
filesystem probe standing in for a fact about what the operation did.

## 2026-07-31

### Runtime-scoped extension disable

**Goal**: Let users remove one runtime's managed extension surfaces without disabling or rewriting the runtime they
keep.

**Key changes**:

- `forge extension disable` now accepts repeatable `--runtime claude|codex|all` for one scope or `--all`. Plans narrow
  to the selected ownership, disclose Codex re-trust and retained legacy residue, and batch summaries distinguish
  `no-op`, `partial`, and `full`.
- Removal intersects schema-v3 attribution with tracked ownership, preserves unattributed rows during partial removal,
  and drops the selected owner pairs so a later sync cannot resurrect the runtime.
- Claude settings and every ownership sidecar form a reversible smart-unmerge transaction. Codex removal classifies and
  revalidates marker state, preserves manual outside-marker commands, and refuses malformed or changed blocks.
- Partial I/O failures reconcile the row to completed removals. A tracking-write failure restores settings ownership
  before reporting the remaining safe over-claim and retry path.
- End-user, CLI, design, and QA guidance now cover runtime removal, full-coverage behavior, failure recovery, and trust
  consequences.

**Verification**: focused install/CLI (`3366 passed, 1 skipped`); unit (`8581 passed, 1 skipped, 117 deselected`);
regression (`551 passed`); installer Docker integration (`21 passed`), including clean-wheel partial-disable, status,
and non-resurrection sync checks for both runtime directions; `make pre-commit`.

## 2026-07-30

### Runtime-scoped extension modules

**Goal**: Make `forge extension enable --runtime` govern every runtime-owned extension surface, so Claude-only selection
cannot mutate Codex state and Codex-only selection needs no module-level workaround.

**Key changes**:

- The live module vocabulary now has six values. `hooks` owns both Claude and Codex hook surfaces, and the released
  `codex-hooks` value is accepted only by the v1/v2 migration path.
- Tracking moved to schema v3 with a sorted `(module, runtime)` ownership relation and required tagged attribution on
  every file and settings row. Frozen v1/v2 readers derive only path- or key-provable ownership; unprovable rows remain
  explicitly unattributed and cannot become runtime-scoped removal targets.
- Module planning now applies the shared runtime selection after profile, dependency, and scope resolution. Profile
  exclusions are visible skips, explicit wrong-owner requests and empty effective selections are blocking conflicts, and
  `--force` cannot bypass them.
- Explicit narrowing remains additive: a Claude-only re-enable preserves existing Codex packages, hook registration,
  ownership pairs, and disable metadata. Sync derives its runtime set from persisted ownership, including hooks-only and
  successful zero-output module ownership.
- `extension status --json` moved to schema v3 and reports `managed_runtimes`, `module_owners`, compatibility `modules`,
  and identity-only `unattributed_surfaces`. Recovery commands, design docs, end-user docs, and QA checks now describe
  the runtime-wide selector.

**Verification**: focused install/CLI (`3311 passed, 1 skipped`); unit (`8526 passed, 1 skipped, 117 deselected`);
regression (`551 passed`); installer Docker integration (`20 passed`), including clean-wheel Claude/Codex/all
enable-sync-status-disable lifecycles and Claude-only narrowing preservation; wheel and sdist built with `uv build`;
`make pre-commit`.

**Compatibility**: installed-state schema and status JSON both bump from v2 to v3. Existing v1/v2 tracking migrates in
memory and persists on the next successful mutation; no reset or manual migration is required.

**Deferred**: runtime-scoped removal remains in `extension_disable_runtime`, which can now consume the tagged ownership
contract without matching unattributed legacy rows.

### Codex disable scope-mismatch refusal

**Goal**: Prevent `forge extension disable` from orphaning an active managed Codex hook block when `$CODEX_HOME` no
longer maps to the config path recorded at installation.

**Key changes**:

- A typed preflight now refuses the whole operation before removal work, preserves the hook block and tracking row, and
  names both paths plus recovery. Single-scope disable checks before its plan/prompt; `--all` retains per-scope failure
  aggregation and continues disabling healthy scopes.
- The installer keeps the same matching-path, null-path, and user-owned leftover-command behavior.

**Verification**: focused install/CLI (`808 passed, 1 skipped`); unit (`8491 passed, 1 skipped, 117 deselected`);
regression (`550 passed`); installer Docker integration (`20 passed`); `make pre-commit`.

**Known limitation**: blocks orphaned by an older disable remain untracked and require manual discovery/removal.

## 2026-07-28

### README capability refresh

**Goal**: Make `README.md` advertise what shipped — above all that a read-only `codex exec` can supervise a Claude
session — and state nothing false.

**Key changes**:

- Four factual errors fixed: the `--into` worktree path (worktrees land at `../<repo-name>-<session-name>`),
  `forge clean` being dry-run by default, project memory presented as automatic when it is opt-in, and a Quick Start
  implying `forge proxy create` is required when `--proxy` accepts a template and auto-starts.
- `Example Workflow` promoted to `## Plan, Execute, Review` with the Codex-supervised fork as its second step, carrying
  both preconditions that decide whether the lane enforces or fails open: the mandatory plan reload (Codex has no
  `--resume`) and the cached preflight.
- Architecture diagram redrawn around consumer lanes, naming each consumer's real runtime support. Review workers are
  drawn as a separate axis because they are per-invocation `ModelSpec.runtime`, not a frozen lane.
- New `## Cost and Wire Control`, `## Skills`, and `## Troubleshooting` sections; CLI group table completed from 11 to
  all 17 groups; pre-OSS upgrade steps relocated to `docs/end-user/README.md`.
- Stale proxy-template tables corrected in `docs/design_appendix.md` §A.2 (15 of 21 rows listed) and
  `docs/end-user/proxy.md` (missing `anthropic-passthrough`). Twenty templates are user-facing; `litellm-gemini-test` is
  test infrastructure.

**Verification**: `make pre-commit-md` clean; all 18 relative links and both fragment anchors resolve; CLI table matches
`forge --help`; every command and flag shown confirmed against live `--help`. Lane labels, the supervisor throttle
cache, and the Claude-only `session fork` restriction verified against source.

**Deferred**: the README's Codex-supervisor sequence is verified at code level, not by a live run. It also omits that
the preflight cache carries a 30-minute TTL relative to the first Write/Edit, not to the fork.

## 2026-07-27

### native_session_adoption: `forge session adopt`

**Goal**: Bind a Forge session to a Claude conversation or Codex thread started outside Forge, so the normal session
surface (resume, fork, transfer, artifacts, search) applies to it.

**Key changes**:

- New command-core ops `session_adopt.py` (Claude) and `codex_adopt.py` (Codex) behind one CLI leaf. The runtime is
  chosen by which store holds a matching conversation, never by the shape of the id; a match in both is refused, naming
  both paths.
- Bare `forge session adopt` previews unbound Claude conversations launched from the current directory (`--json` for
  scripting). Both arms verify the conversation's recorded launch directory before binding, and refuse ambiguous or
  unverifiable rollout matches rather than guessing.
- One conversation, one manifest, enforced in two layers: a global per-conversation lock spanning adoption's final scan
  and commit, and a `codex_thread_id` index column checked under the index write lock. Neither alone is sufficient --
  the lock cannot survive process death, and the index cannot see a killed create's orphan manifest.
- `SessionStore.create_exclusive` makes the manifest the session-name reservation; an index row cannot reserve, because
  `list_sessions` prunes rows whose manifest is missing.
- Adoption inverts transcript ownership, so `delete_session` exempts an adopted session's native transcript from
  `delete_transcripts` — including the automatic retention sweep that runs on CLI startup.
- Binding lookups fail closed on the index and on every manifest they read, and are keyed by `(project, name)` because
  session names are project-scoped.

**Verification**: 9034 unit + regression tests (1 environmental skip); 45 session/codex integration tests; two
real-Claude Docker gates — the reattach-identity premise (`test_adopt_binding_contract.py`) and end-to-end discover →
bind → continue against a conversation Forge never launched (`test_adopt_native_conversation.py`). Four review rounds,
every finding reproduced before it was fixed. `make pre-commit` clean.

**Deferred**: session creation is still not crash-atomic across manifest and index — a kill between `create_exclusive`
and `add_from_state` leaves an orphan manifest. The conversation lock bounds adoption's exposure to it; removing the
orphan itself needs its own card.

## 2026-07-26

### July 2026 model refresh (Opus 5 default, K3, Qwen 3.7, Gemini 3.6 Flash)

**Goal**: Catalog and template support for Claude Opus 5 (new default opus tier), Kimi K3, Qwen3.7 Plus/Max, and Gemini
3.6 Flash, with the tier-1 cascade checker and dead gemini-2.0-flash tagger defaults migrated to 3.6 Flash.

**Key changes**:

- Fixed a latent proxy bug first: derived reasoning efforts now clamp to each model's catalog effort levels and explicit
  unsupported values are rejected (`forge.proxy.reasoning`, extracted from `server.py` for the size gate). Existing
  gemini-flash proxies stop receiving derived `xhigh`.
- Opus 5 replaces Opus 4.8 across catalog defaults, `opus`/`claude-opus` aliases, the four anthropic templates, and the
  proxy-context estimator pin; 4.8 stays selectable via `model_alternatives` and untouched explicit fixtures.
- Kimi K3 (`[low, high]` efforts; native `max` unreachable by design — no `max` in Forge's vocabulary) and Qwen3.7
  Plus/Max take over their family tiers; displaced 3.6-generation models become alternatives. OSS review workers now
  lock `provider_refs` to each family's derived default.
- Gemini 3.6 Flash ships with sampling overrides off (Google deprecates temperature/top_p/top_k), thinking default
  medium, and probe-backed `prompt_caching: false`; flash/haiku tiers, checker defaults, and all gemini-2.0-flash tagger
  defaults (model shut down 2026-06-01) move to it — zero 2.0-flash references remain in src/.
- LiteLLM floor raised 1.85.0 -> 1.88.0 (gate-proven; resolution unchanged). gemini-3.6-flash (2026-07-21) is newer than
  every stable LiteLLM release, so packaged cost-map pricing first ships in the v1.94 line; production relies on the
  remote cost-map refresh until then. A live gate proves completion/thinking/cost on 1.88.0 through a freshly
  materialized bundled route; a version-aware pin flips to a packaged-map assert at v1.94.

**Verification**: Full unit suite green per commit; regression suite incl. new effort-floor test; live LiteLLM gate
passed with GEMINI_API_KEY (cache probe negative, recorded in catalog). OpenRouter live matrix: Opus 5, Kimi K3, and
Gemini 3.6 Flash completions passed through their new template defaults; the qwen completions are blocked by this
account's OpenRouter data-policy settings (404 "no endpoints available" for every qwen slug, including the pre-existing
3.6-flash — environment limit, remediation at openrouter.ai/settings/privacy), so qwen live coverage here is the boot +
tier-mapping assertion. The pre-existing `test_sonnet_completion_resolves_to_gpt_56_sol` local-LiteLLM e2e fails
identically on main in this environment (OpenAI upstream 500 through the local backend — account/key limit, not a branch
regression). `make pre-commit` clean; `uv build` wheel smoke at closeout.

## 2026-07-24

### Policy shared-library seam

**Goal**: Extract the honest shared policy/reactive seams while preserving caller-specific telemetry and failure
contracts, then correct the team supervisor's routing, confidence, and model-pin behavior.

**Key changes**:

- Added one provider-aware direct-LLM transport helper for the action tagger, plan checker, workflow stages, transfer
  curation, and team tagger; parsing, telemetry emission, and fail behavior remain caller-owned and matrix-tested.
- Consolidated the semantic/workflow confidence-plus-citation predicate, supervisor lane resolution, and canonical
  resume-ID matcher without changing their decisions.
- Applied the decided D7 team contract: divergent verdicts block only at the shared confidence threshold; lower or
  malformed confidence allows with diagnostic stderr feedback. Team routing now resolves before commitment, so strict
  named-route failures skip before lane freeze/usage, while reachable ambient routes become visible to cost and usage.
- Fixed executor model-pin leakage for every resolved team-supervisor URL without imposing the semantic supervisor's
  `opus` pin. Added a deterministic Docker fixture covering both team hooks through the tagger HTTP and `claude -p`
  wires.

**Verification**: Focused acceptance (`449 passed`); `make test-unit` (`8314 passed, 1 skipped, 117 deselected`);
`make test-regression` (`529 passed`); targeted policy/supervisor/team-hook Docker integration (`32 passed`); mypy,
pyright, and `make pre-commit`.

## 2026-07-23

### Runtime-neutral workflow workers closeout

**Goal**: Close the shipped runtime-neutral workflow worker card after PR #110 merged to `main`.

**Key changes**:

- Moved the paired card and checklist from `doing/` to `done/`, recorded merge `26122901`, closed the final checklist
  item, and repointed the inbound cross-runtime-skills link.
- Promoted the reviewed execution/routing split, readiness snapshot, mixed lifecycle ownership, specialization,
  runtime-error, and portable-frontend invariants to durable implementation notes.

**Verification**: PR #110 merged as `26122901`; final merged package lifecycle integration (`2 passed, 18 deselected`);
QA parser v1.0.33 / 596 assertions; walkthrough parser v1.0.6 / 108 assertions; stale-lane and inbound-link audit;
`make pre-commit-md`; `git diff --check`.

## 2026-07-22

### Runtime-neutral workflow workers (implementation complete; review hold)

**Goal**: Let each panel, analyze, debate, or consensus worker select its own headless runtime while preserving the
existing Claude-backed defaults and truthful routing, telemetry, and failure semantics.

**Key changes**:

- Added an opt-in `codex` worker with explicit runtime-native routing, one cached readiness snapshot per invocation,
  read-only sandboxing, runtime-default model reporting, and fail-closed Claude-resume handling. No existing worker name
  or default quorum changed.
- Added one grouped five-child lifecycle domain for mixed-runtime fan-out, preserving input order and prompt
  cancellation. Single-runtime calls retain the existing `run_parallel` shape; shared result mapping now deliberately
  rejects reliable runtime-error envelopes on both runtimes. Runtime stream text takes precedence on non-zero failures,
  while an empty result retains its numeric exit code.
- Kept Codex auth, billing, and downstream-provider identity runtime-owned: worker and downstream records reuse the
  existing `codex_exec`/OpenAI emitter contract without fabricating a model route, backend, proxy, or cost.
- Migrated the four workflow frontends to neutral sources, expanding the portable Codex set from five to nine packages,
  and synchronized design, CLI, end-user, QA, and walkthrough documentation.

**Verification**: focused post-format suites (`731 passed`); `make test-unit`
(`8277 passed, 1 skipped, 117 deselected`); real Codex-only and mixed-runtime workflow integration (`2 passed`);
existing Claude workflow parity integration (`13 passed`); clean wheel installs for `--runtime claude`, `codex`, and
`all`, including status/sync/disable lifecycle; `uv build`; `make pre-commit`; QA parser v1.0.32 / 596 assertions;
walkthrough parser v1.0.5 / 108 assertions. The card remains in `doing/` for review and merge.

### Unmanaged skill packages closeout

**Goal**: Close the shipped unmanaged-skill-package detection and cleanup card after PR #109 passed review remediation
and merged to `main`.

**Key changes**:

- Moved the card and preserved checklist from `doing/` to `done/`, updated the lane header, and recorded the ratified
  fail-closed unsafe-root behavior (never traversed; surfaced as a human root-level diagnostic, never a fabricated JSON
  package row).
- Promoted the reviewed discovery-surface, deletion-proof, no-scan-boundary, and scope-ownership invariants to durable
  implementation notes.

**Verification**: PR #109 merged as `cbb58e16`; merged-`main` re-run of the focused suites (`289 passed`) and
`make test-unit` (`8230 passed, 1 skipped, 117 deselected`); inbound-link and stale-lane grep clean;
`make pre-commit-md`; `git diff --check`.

### Phase 8: Unmanaged skill packages (implementation complete; review hold)

**Goal**: Detect runtime skill packages no longer represented by coherent tracking, distinguish safe Forge cleanup from
report-only user content, and provide scope-correct recovery without adopting or overwriting either class.

**Key changes**:

- Added one-snapshot unmanaged-package discovery with append-only historical names, strict provenance-marker and tree
  validation, collision reporting, and immutable status records. The emitted marker intentionally causes a one-time
  research-preview compiled-cache digest change.
- Added per-package enable/sync recovery, status JSON schema v2, and guarded `unmanaged_skill_packages` cleanup across
  project, workspace, and all scopes. The status `--json` top-level object is the second research-preview clean break.
- Anchored cleanup to real runtime-root descriptors, revalidated ownership and filesystem proof immediately before
  removal, covered cache-reset and drift boundaries, and synchronized operator, design, QA, and walkthrough docs.
- Review remediation restored a displaced runtime-selection assertion, added human diagnostics for unsafe selected roots
  without inventing JSON package rows, and replaced full source parsing on status/clean with names-only discovery plus a
  historical fallback.

**Verification**: focused acceptance (`289 passed`); related compiler/cache/tracking/validation (`170 passed`);
`make test-unit` (`8230 passed, 1 skipped, 117 deselected`); `make test-regression` (`522 passed`); wheel-installed
Docker lifecycle (`1 passed, 19 deselected`); `uv build`; `make pre-commit`; QA parser v1.0.31 / 592 assertions;
walkthrough parser v1.0.5 / 108 assertions; `git diff --check`. The card remains in `doing/` for human review.

## 2026-07-17

### Cross-runtime skill packages closeout

**Goal**: Close the shipped cross-runtime skill package card after PR #107 passed human review and merged to `main`.

**Key changes**:

- Moved the card and preserved checklist from `doing/` to `done/`, repointed inbound board references, and recorded the
  merge boundary.
- Promoted the reviewed runtime-selection, compiler-source, package-ledger, symlink-ownership, and cache-lifetime
  invariants to durable implementation notes.

**Verification**: PR #107 merged as `d2a94bf7`; board-path and unchecked-closeout scans, `make pre-commit-md`, and
`git diff --check` passed.

### Cross-runtime skill boundary hardening

**Goal**: Close fail-open source, ownership, teardown, and probe-evidence paths found during the second review without
moving the card out of its review hold.

**Key changes**:

- Batch disable now exits nonzero after any failed row, and complete uninstall preserves tracking and `$FORGE_HOME` when
  tracked teardown cannot complete.
- Skill loading rejects symlinked roots and applies checkout Git eligibility before discovery, reads, or caching.
  Tracking strictly cross-validates package ownership against the canonical file ledger, and status treats dangling
  tracked leaf symlinks as missing.
- Neutral invocation policy is typed-only, packaged executables honor their entry point, negative Codex probes require
  successful turns plus exact command/exit evidence, Codex model-family selection is host-authoritative, and lifecycle
  help names exact tracking-row discovery.

**Verification**: affected suite (`381 passed`); unit (`8,158 passed`, one skipped); regression (`521 passed`); targeted
Docker lifecycle (`2 passed`); `uv build`, pre-commit, Markdown, and diff checks passed; QA parser v1.0.30 / 589
assertions; strengthened real-Codex stages 40 and 50 passed on codex-cli 0.144.5.

### Cross-runtime skill review remediation

**Goal**: Close the review-found ownership, duplicate-classification, status, compiler-boundary, and clean-package gaps
without weakening the one-visible-Codex-scope contract or moving the card out of review hold.

**Key changes**:

- Automatic re-enable now refreshes the union of detected and managed runtimes; explicit narrowing emits preservation
  rows and retains omitted package files/tracking. Cross-scope duplicates use validated Forge provenance, consistent
  path normalization, and executable scope-aware recovery instead of untracked-file advice. User-scope planning also
  blocks on tracked project/local packages outside the current directory chain.
- Status is safe outside projects, policy conflicts no longer advertise ineffective `--force`, cache failures map to
  retryable installer errors, and typed/Claude frontmatter conflicts fail at manifest load.
- Runtime package roots and descendant directories must remain real entries. Status rejects symlink substitution, and
  enable, sync, apply, rollback, and disable revalidate before mutation instead of following links into sibling content.
- Added Claude-worker, smoke-script, HOME-isolation, genuine v1, and lifecycle regressions; replaced mutable checkout
  packaging simulation with an offline-built, target-installed wheel covering both runtime outputs; synchronized QA and
  operator docs.

**Verification**: review suite (`302 passed`), symlink-boundary suite (`216 passed`), full regression (`515 passed`),
and `make test-unit` (`8134 passed, 1 skipped, 117 deselected`); targeted Docker lifecycle (`2 passed`); `uv build`;
`make pre-commit`; `make pre-commit-md`; QA v1.0.28 / 585 assertions; walkthrough-state (`93 passed`);
`git diff --check`. The card remains in `doing/`, and no proposed lesson was promoted to `impl_notes.md`.

## 2026-07-16

### Cross-runtime skill packages (implementation complete; review hold)

**Goal**: Compile, install, and operate Forge skills natively under Claude Code and Codex without duplicating the
authoring source or weakening runtime ownership boundaries.

**Key changes**:

- Added a typed neutral skill manifest/compiler, Claude and Codex adapters, whole-tree validation, and content-addressed
  package caching. Five portable skills now ship for both runtimes; six remain explicitly Claude-only.
- Added runtime skill-scope capabilities, scope × runtime × profile planning, Codex user/project targets, duplicate
  safety, and schema-v2 package tracking across enable, status, sync, disable, copy, and symlink lifecycles.
- Made apply failures retryable by restoring newly created files, Claude settings, ownership sidecars, and tracking
  state; hardened source/cache/reference/script boundaries found by adversarial review.
- Synchronized architecture, CLI, end-user, manual-testing, QA, walkthrough, authoring, and downstream board guidance.

**Verification**: adversarial acceptance (`142 passed`); `make test-unit` (`8099 passed, 1 skipped, 117 deselected`);
Docker installer integration (`20 passed`); seven-stage real Codex probe plus compiled user/project smoke (`8/8` each);
clean wheel project/Codex and sdist user/all-runtime lifecycles, including Claude (`11/11`) and Codex (`8/8`) smoke;
`make pre-commit`; package and token-limit inspection. The card remains in `doing/` for the requested review, and no
proposed lesson was promoted to `impl_notes.md`.

### GPT-5.6 catalog and Sol proxy defaults

**Goal**: Add GPT-5.6 Sol, Terra, and Luna and promote Sol across Forge's bundled OpenAI defaults.

**Key changes**:

- Added the three canonical catalog profiles plus base/provider aliases, kept GPT-5.5 compatible, left haiku on GPT-5.4
  Mini, and moved OpenAI sonnet/opus and workflow provider references to Sol.
- Updated all six affected OpenAI proxy templates and the fresh local LiteLLM adapter routes; existing user-owned proxy,
  backend, and custom-template snapshots remain unchanged and now have an explicit upgrade path.
- Synchronized bundled multi-model skills, CLI help, and user docs; added drift guards for executable workflow examples;
  documented intelligence scores as coarse peer buckets; and added hermetic LiteLLM Responses routing plus live
  OpenRouter coverage for the exact Sol slug.

**Verification**: focused implementation suite (`611 passed`) and review follow-up suite (`554 passed`);
`make test-unit` (`7936 passed, 1 skipped, 117 deselected`); targeted LiteLLM/OpenRouter integration (`2 passed`);
`make pre-commit`; `uv build`; separate wheel and sdist clean installs, full-profile extension enables, doctor checks,
and packaged catalog/template/backend/skill assertions. Additional live probes found environment limits rather than code
failures: the direct OpenAI key returned 401 for GPT-5.6, and remote LiteLLM credentials were absent.

### Memory-passport CLI preflight cleanup

**Goal**: Consolidate repeated document-target preflight without changing leaf-specific mutation or output contracts.

**Key changes**:

- Added a structured private resolver for project root, compatibility, path safety, and file checks while keeping each
  leaf's wording and rendering; removed dead `ExecutionContext.from_cwd()` `ForgeOpError` wrappers and superseded weak
  tests with exact stream, precedence, and no-mutation characterization.

**Verification**: PR #105 merged at `9288bed2`; focused CLI suites (`228 passed`); `make test-unit`
(`7907 passed, 1 skipped, 117 deselected`); `make pre-commit`; post-merge `make pre-commit-md`; `git diff --check`.

## 2026-07-15

### Existing shadow-only reserved-target hotfix

**Goal**: Prevent ordinary re-track of a hand-authored shadow-only passport from materializing an OKF-reserved file.

**Key changes**:

- Existing-shadow re-track now applies generic path safety followed by logical and resolved reserved-basename checks
  before shadow creation or passport mutation; regressions cover direct `log.md`, resolved aliases, and error ordering.

**Verification**: `make test-unit` (`7886 passed, 1 skipped, 117 deselected`); `make test-regression` (`514 passed`);
`make pre-commit`; `git diff --check`.

### okf_compatible_memory_passports remediation

**Goal**: Close the verified post-closeout parser, reserved-target, host-walkthrough, and atomic-mode gaps without
expanding the passport compatibility contract.

**Key changes**:

- Unified read/mutation delimiter selection and pinned the three-delimiter corruption case; blank intent now fails at
  both CLI and synthesis boundaries.
- Case-folded logical/resolved reserved official and proposal-shadow targets, blocked hand-authored reserved shadows at
  discovery, and made the walkthrough's envelope verifier host-stdlib-only.
- Added opt-in mode preservation to the shared atomic writer, migrated passport and Codex config rewrites, consolidated
  mutation apply paths, and avoided discarded work on unchanged re-track flows. The non-identical CLI preflight cleanup
  remains a proposed follow-up.

**Verification**: remediation commit `58b7e97`; `make test-unit` (`7884 passed, 1 skipped, 117 deselected`);
`make test-regression` (`513 passed`); handoff integration (`10 passed`); installer asset/mode integration
(`2 passed, 16 deselected`); `make pre-commit`; `git diff --check`; `uv build`; isolated wheel and sdist full-profile
installs plus delimiter, reserved-path, blank-intent, and packaged-walkthrough smokes.

## 2026-07-14

### okf_compatible_memory_passports original closeout (superseded by 2026-07-15 remediation)

**Goal**: Make newly tracked and explicitly upgraded Forge Markdown memory docs recognizable as OKF v0.1 concept
documents without weakening Forge's passport write policy or claiming bundle conformance.

**Key changes**:

- Added creation-only `type`/`title`/`description` envelopes and an explicit idempotent `forge memory passport upgrade`
  path that preserves the raw legacy passport value; ordinary re-track remains non-migrating, and Forge still generates
  no `resource`, `tags`, or `timestamp`.
- Split permissive frontmatter reads from strict mutation parsing, made unsafe shapes fail byte-identically, preserved
  file modes, and preflighted effective passports and logical/resolved path rules before official or shadow writes.
- Synchronized architecture, CLI, end-user, QA, walkthrough, packaging, and board guidance; proposed the reusable
  mutation-boundary lessons through `.forge/memory/shadow_impl_notes.md` for human review.

**Verification**: implementation commit `fae54345`; `make test-unit` (`7846 passed, 1 skipped, 117 deselected`);
`make test-regression` (`507 passed`); required handoff integration (`10 passed`) and installer asset integration
(`1 passed, 17 deselected`); `make pre-commit`; `git diff --check`; `uv build`; separate isolated wheel and sdist
full-profile enables, packaged-asset inspection, legacy-upgrade/idempotence checks, and empty-writer refusal smokes.

## 2026-07-13

### epic_global_forge_runtime closeout

**Goal**: Close the global Forge runtime epic with its shipped hook ownership, binary-resolution, migration, and
execution-environment contracts reflected consistently in code, docs, and the board.

**Key changes**:

- Verified all five epic seams and reconciled the normative install, dispatcher, recovery, status-line, and sidecar
  documentation with the shipped model.
- Added the terminal `retired/` lane and retired unshipped T2 as superseded; the narrower GUI-safe status-line concern
  remains a standalone proposed follow-up.
- Moved the epic to `done/`, corrected stale member state, and repointed every inbound board link.

**Verification**: PR #99 merged at `168b7db7`; focused hook/runtime suite (`285 passed, 1 skipped`); merged-main Docker
installer suite (`17 passed`); closeout doctor/dispatcher tests (`86 passed`); pre-commit checks; relative-link and
stale-lane sweeps; `git diff --check`.

## 2026-07-12

### forge_project_compat_mutator_sweep closeout

**Goal**: Finish `.forge/project.toml` enforcement across every classified project-state mutator without gating unowned
global runtime state.

**Key changes**:

- Enforced the target state owner's Forge root across explicit session, policy, transfer, memory, search, cleanup, and
  direct-command mutations; hooks diagnose without changing their wire, while detached writers and queue work refuse
  through bounded background contracts.
- Made managed worktree refusal atomic, including pre-destroy validation of stale roots, the exact replacement commit,
  and branch safety; retained post-create checks and surfaced incomplete rollback instead of hiding state loss.
- Kept proxy/backend registries and proven-stale derived-index repair narrowly exempt, added per-root partial cleanup
  reporting, and documented that `forge clean --yes --json` exits 1 when failures or compatibility skips are present.
- Moved the card to `done/`, repointed the epic and T7/T8 references, and promoted the reviewed ownership, posture,
  background-refusal, and exemption invariants to `impl_notes.md`.

**Verification**: PR #98 merged at `aa45114d`; `make test-unit` (`7724 passed, 1 skipped, 117 deselected`);
`make pre-commit`; required targeted integration suites (`151 passed`) plus focused compatibility/fork regressions
(`35 passed`). The real Claude-to-Codex bridge command was invoked but failed at its Codex readiness gate before the
bridge body ran because isolated `CODEX_HOME` requires `CODEX_API_KEY`; host Codex preflight was ready, the no-skip test
stayed intact, and no product change is pending on that result.

### forge_dev_runtime_override closeout

**Goal**: Close T8 after PR #97 merged and hand the global-runtime epic its final coordinator closeout.

**Key changes**:

- Moved `forge_dev_runtime_override` from `doing/` to `done/`, preserved its implementation checklist, and repointed the
  epic and status-line follow-up links.
- Recorded T8 as shipped via PR #97 and left the epic in `doing/` with no active member; its five seam boxes,
  durable-doc verification, inbound-link sweep, and lane move are now actionable as a separate epic closeout.
- Kept the already-reviewed durable override and launcher-recording lessons in `impl_notes.md`; no additional promotion
  was needed at lane closeout.

**Verification**: PR #97 merged at `46ff9ef6`; `make pre-commit-md`; post-merge relative-link and stale-status sweep;
`git diff --check`.

### forge_dev_runtime_override implementation and branch verification

**Goal**: Let contributors run unreleased checkout hook code explicitly without sticky-pointing global dispatcher
metadata at a project venv.

**Key changes**:

- Added the process-scoped `FORGE_DEV=<absolute-checkout-root>` dispatcher branch after the no-op gate and handler
  validation; invalid or unlaunchable checkout targets fail with exit 127 and never fall back to the global resolver.
- Replaced implicit launcher recording with the reviewed four-step transition table, preserving custom stable launchers
  while excluding lexically classified venv launchers and migrating legacy sticky metadata on enable/sync.
- Added doctor validity/effectiveness diagnostics, managed Claude/Codex env-propagation coverage, and the Public
  env-vocabulary plus architecture, CLI, contributor, and end-user hook documentation.

**Verification**: focused dispatcher/doctor/installer/env/golden suite (`308 passed`); Docker installer integration
(`17 passed`); wheel + sdist build and isolated `uv tool` enable/sync/doctor check; live checkout dispatcher smoke
(valid exit 0, invalid exit 127 without fallback); `make pre-commit` clean. The active T8 checklist keeps the
command-level evidence; shipment/lane closeout remains post-merge.

## 2026-07-11

### forge_hook_migration_cleanup closeout

**Goal**: Close T6 after PR #96 merged and leave the global-runtime epic at an explicit no-active-member cursor.

**Key changes**:

- Moved `forge_hook_migration_cleanup` from `doing/` to `done/`, preserved its implementation checklist, and repointed
  its epic links.
- Recorded T6 as shipped in the epic while leaving the epic seam boxes open until epic closeout; T8 remains parked
  pending a separate activation decision.
- Promoted the reviewed registry-activation and selected-root migration-ordering invariant to `impl_notes.md`.

**Verification**: PR #96 merged at `93312179`; `make pre-commit-md`; post-merge relative-link and stale-lane sweep;
`git diff --check`.

## 2026-07-10

### forge_hook_migration_cleanup implementation

**Goal**: Give pre-user-scope installations an explicit, reviewable migration to one dispatcher-backed runtime source
without silently mutating or activating other tracked checkouts.

**Key changes**:

- Added tracked-root candidate reporting plus `forge extension cleanup-project` preview/`--yes`; user enable/sync never
  reads the registry or another root, while explicit cleanup validates one selected root, removes legacy state first,
  installs user runtime hooks, scans for duplicates, and enrolls that root last with `backfill` provenance.
- Restricted automatic Claude cleanup to canonical tracked entries or a frozen additive released-shape inventory,
  reconciled `.forge-added`/installation ownership, migrated balanced project Codex blocks with backups and re-trust
  guidance, and retained ambiguous/manual state as an operation-scoped blocker.
- Added independent doctor/status-line cleanup state (`HOOK!`) without broadening genuine `HOOKx2`, and synchronized
  architecture, CLI, Day-1/recovery, QA, and isolated walkthrough guidance.

**Verification**: focused migration suite (`320 passed`); CLI command/output/vocabulary guards (`68 passed`);
`make test-unit` (`7556 passed, 1 skipped, 116 deselected`); installer Docker suite (`16 passed`) plus final targeted
migration-and-disable rerun; real-Claude migration (`1 passed, 2 deselected`) with user-dispatcher SessionStart/Stop
effects; isolated walkthrough migration exercise; `make pre-commit`.

### forge_hook_sidecar_resolution closeout

**Goal**: Close T10 after PR #94 restored Forge runtime hooks inside Claude sidecars.

**Key changes**:

- Shipped fresh canonical hook staging in the persisted sidecar user scope, idempotent entrypoint auth merging, and an
  image PATH that resolves bare hook and project status-line commands without mutating project `.claude` settings.
- Persisted deferred work through a host-drainable queue with host-path normalization and container-side drain
  suppression; retained the stale-image skew guard and PATH breadth as explicit follow-ups.
- Moved `forge_hook_sidecar_resolution` from `doing/` to `done/`, repointed its epic links, and advanced the epic cursor
  to T6 with T8 parked.

**Verification**: `make test-unit` (`7517 passed, 1 skipped, 116 deselected`);
`./scripts/test-integration.sh tests/integration/sidecar/test_sidecar_hook_inject.py -v` (`3 passed`);
`make pre-commit`; PR #94 GitHub checks (test, pre-commit, CodeQL analyses); `make pre-commit-md`; post-merge board
link/stale-reference scan.

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

Consumer-lanes, corrupt-state, CLI-taxonomy, and Codex proxy-launch arc. Detailed card history remains in the matching
`docs/board/done/` cards and PRs; this summary preserves the decisions, behavior changes, verification anchors, and
deferred items.

- **consumer_lanes T0-T7**: introduced runtime-native subscription sources (`chatgpt`, then `claude-max`) and the pure
  `core.lanes` model, moved the semantic supervisor onto lane resolution, then made codex the first real non-Claude
  supervisor lane. Later slices added lane observability, persisted/frozen supervisor lane bindings,
  `forge session lane set/show/clear --consumer`, aux-consumer `claude-max` billing, shadow-curation codex dispatch, and
  sticky fail-open degrade from exhausted codex subscription lanes back to the default `claude -p` lane. Decisions:
  runtime-native auth is endpoint semantics, not a relaxed credential; T3 kept Claude byte-identical; T4 bypasses the
  proxy chain; aux freeze happens on real dispatch while supervisor freeze stays tied to its registered lifecycle;
  shadow-curation codex failures are fail-loud, not fail-open. Deferred: memory-writer codex dispatch, team-supervisor
  plan-context/codex arm, live codex subscription-exhaustion trigger, and some release-tier real-API validation.
  Verification included focused lane/source/supervisor/session/usage suites, full unit sweeps around 7k tests, Docker
  real-Claude supervisor/handoff coverage, and a host ChatGPT `codex exec` shadow-curation smoke.
- **State corruption/unreadable handling**: unified durable corruption under `StateCorruptedError` with one reset tip,
  added `forge clean` corrupt-state recovery, removed legacy baggage, then completed fail-closed GC/reset-tip coverage
  and strict cost-config validation. Follow-up split transient `OSError` reads into `StateUnreadableError`, so
  unreadable files surface check/retry guidance and are never deleted as corruption. Decisions: best-effort scan/list
  sites may still degrade, but specific-target paths propagate corruption/unreadable to the top-level handlers; hook
  commands emit `{decision:block}` JSON envelopes. Verification: 6.9k-7.3k unit/regression passes, corrupt/unreadable
  regression files, adversarial review findings fixed, `make pre-commit` clean.
- **forge_cli_cleanup slices 02-12 + closeout**: moved transfer/memory under `forge session`, moved telemetry under
  `forge telemetry`, moved backend under `forge model`, removed `forge session context`, removed alias shims
  (`authentication`, `extensions`), normalized non-leaf behavior, routed Rich errors/tips through output helpers, split
  `policy supervisor` into explicit leaves, standardized destructive `clean`/`delete`/`reset` prompts, enumerated
  editable-config verb parity, and drained read-output JSON/stream ledgers. Breaking clean-breaks intentionally return
  Click native errors; kept aliases are `ext`/`sess`/`mem`/`cfg`, with no new aliases for `telemetry`/`model`. Durable
  lessons promoted: alias policy and the Python-symbol-vs-CLI-alias trap. Verification included CLI unit sweeps, command
  tree invariants, JSON shape/stream tests, Docker installer/search/backend integrations, `uv build`, and
  `make pre-commit`.
- **forge_codex_command_group Phase 1/3/4 + closeout**: shipped `forge codex status`, the `openai_responses_passthrough`
  wire shape and Responses ingress, then `forge codex start --proxy`. The transport forwards Codex `/v1/responses*`
  byte-for-byte to preserve signed reasoning; route/preflight/proxy capability gates all require
  `wire_shape == openai_responses_passthrough` plus `responses_ingress`; generation-only accounting prevents retrieve
  double-counting; launcher strips native OpenAI/Codex auth and relies on proxy-owned upstream credentials. Review
  hardening added proxy identity verification so stale registry entries on reused ports cannot misroute Codex.
  Verification: status/transport/launcher unit suites, full CLI suite, real codex 0.141.0 routing through Forge to
  `POST /v1/responses`, proxy identity live-check, and `make pre-commit`; deferred live 200 reasoning round-trip
  remained blocked by a dead OpenAI key.
- **2026-06-25 real-checker fix**: the cascade short-circuit E2E was not flaky; its plan said "Create" a file that the
  harness pre-created, so the conservative checker correctly escalated. The plan now authorizes overwriting the existing
  file. Verification: Docker real-supervisor E2E 10/10; fixed test passed repeated real-checker runs.

## 2026-06-18 -- 2026-06-20 (compacted)

Telemetry backend-attribution + remote-reconciliation arc (cards: `upstream_downstream_ledgers`, `unified_backend`,
`backend_remote_reconciliation`, `openrouter_user_direct_callers`).

- **upstream_downstream_ledgers** (06-18): re-cut telemetry into `~/.forge/telemetry/{downstream,upstream}/` JSONL
  planes (downstream = model-attempt evidence; upstream = operation outcomes, default volume `non_success`). Cap-safe
  migration: caps persist `telemetry/caps/<proxy_id>.json` and bootstrap from `max(cap_state, downstream, legacy)` so
  the path move never zeroes monthly caps; `proxy costs reset` wipes all new planes + caches; provider-trace reads
  project downstream fields. Closeout: two-pane `forge activity` (Operation outcomes / Model calls), shared measurement
  resolution, engine writes via `record_upstream_operation`. Verified: 264 + 32 + 434/237/517 + 36 integration;
  `make pre-commit`.
- **unified_backend** (06-18, closeout 06-19): built-in `ModelSource` catalog (local/remote LiteLLM, OpenRouter,
  Anthropic passthrough, direct); templates moved to `proxy.source` deriving endpoint/auth/lifecycle from the catalog;
  downstream `backend_id` attribution while `source_id`/`source_kind` stay writer-origin; OpenRouter-specific gates
  replaced by source capabilities. `backend list/show` mark a shared local LiteLLM instance (display-only, never feeds
  `backend_id`). Follow-up: custom templates preflight credentials from declared `proxy.source`. Verified: 526 + 11
  integration; 175; 156 focused; `make pre-commit`. Shipped via PR #39 (`ab690ac9`).
- **backend_remote_reconciliation** (PR 1 06-19, PR 2 06-20): generalized provider-trace/user-grouping off OpenRouter
  (`openrouter_user_grouping` -> `provider_user_grouping`; capability-gated by `backend_id`; a source-less proxy writes
  no trace). PR 2 shipped `forge backend reconcile <source-id>` (single-id MVP): `backend/remote/` adapter protocol +
  registry, `OpenRouterRemoteAdapter` (metadata-only `GET /generation`, never content), buckets
  joined/remote/missing-remote/not-queryable; remote/network failures are renderable data, never raised (hardened by a
  32-agent review, 21 findings: NaN/overflow bodies -> `unavailable`). Verified: 185 + 52 + 2322; live
  `test_provider_trace_e2e.py`; `make pre-commit`.
- **openrouter_user_direct_callers** (06-20): extended OpenRouter `user`-field grouping to direct `core.llm` callers
  under ONE global toggle `provider_trace.inject_provider_user` (`~/.forge/config.yaml`, default off) instead of
  per-proxy; `forge config set/edit` gained nested-section support. Breaking (research preview): per-proxy `proxy.yaml`
  `inject_provider_user`/`inject_openrouter_user` removed (stale key ignored with a one-time relocation warning).
  Verified: 432 tests; mypy/pyright; sidecar Docker integration; `make pre-commit`.

## 2026-05-22 -- 2026-06-16 (compacted)

Runtime, Codex frontend, session transfer, proxy observability, and status-line foundation. Detailed history remains in
the corresponding `done/` cards and PRs.

- **05-22--06-03 -- runtime and handoff foundations:** added origin-rooted `RunIdentity`, the schema-v1 usage ledger,
  shared invoker/fan-out, frozen runtime registry, runtime-tagged actions, and host-only opt-in native relocation. Split
  Stop-time memory writing from resume/fork transfer, made passports authoritative for document ownership, and shipped
  schema-backed transfer artifacts. Added the redact-before-persist audit proxy and configurable status line. Path
  rewriting, sidecar relocation, a native-relocation default flip, and slow-upstream replay remained deferred.
- **06-04--06-09 -- runtime and CLI closeout:** confirmed `codex exec` hooks were unavailable headlessly, retaining the
  initial-message bridge and transfer-curation attribution. Cost accounting became reported-or-unavailable;
  `forge usage` became `forge activity`, `--scope repo` became `--scope workspace`, and stale shims were removed. Linked
  worktrees gained git-common-dir project roots, strict JSONL object guards, and retry/cleanup/delta regressions.
- **06-10--06-14 -- first-class Codex frontend:** shipped Codex start/resume, hook adapter/responder surfaces,
  SessionStart transfer delivery, interactive TUI, enrollment, and capability/version guards. Enrollment evidence kept
  trust scoped and policy enrollment-gated. App-server transport, an upstream fail-open draft, and
  PermissionRequest/`trusted_hash` research remained deferred. Supervisor cascade/effort controls, shadow sampling, and
  same-directory curated transfer forks shipped alongside it.
- **06-15 -- provider tracing and launch controls:** live probes established OpenRouter generation-id and cancellation
  semantics before Forge added leak-gated session/command headers and a separate `ProviderTraceMeta`. Review fixes made
  cancelled streams emit metadata early and preserved metadata through fallback/non-stream paths. Session launchers
  gained tier-1 cascade controls and per-caller Claude effort without a schema bump; explicit same-directory transfer
  options no longer disappear into native resume.
- **06-16 -- proxy and operator observability:** fixed dropped logging/provider-trace config, made successful and opt-in
  stream logging DEBUG-only, added strict redacted request logging and shared JSONL retention, and closed two plaintext
  leak paths. Provider traces gained owner-only lifecycle records, `list/show/explain`, cancellation state, and proxied
  OpenRouter `user` grouping; direct callers remained deferred. Status-line health derives supervisor failure streaks
  from the usage ledger without new durable state; parse/auth fail-opens remained deferred.
- **Verification:** successive unit suites ranged from roughly 6.1k to 6.4k tests, with focused integration and
  real-provider/Codex paths covering policy, transfer, generation, cancellation, and launch behavior. Regression, mypy,
  pyright, adversarial-review follow-ups, and final `make pre-commit` checks passed at each closeout.
