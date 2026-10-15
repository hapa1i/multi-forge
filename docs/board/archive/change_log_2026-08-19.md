# Change Log: 2026-08-19

Verbatim archived entries from the project change log.

[Current entries](../change_log.md)

---

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
