# Change Log Archive: 2026-08-20

Completed-work entries retained verbatim from the [current log](../change_log.md).

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
