# Change Log Archive: 2026-08-21

Completed-work entries retained verbatim from the [current log](../change_log.md).

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
