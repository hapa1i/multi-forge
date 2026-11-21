# Change Log Archive: 2026-08-22

Completed-work entries retained verbatim from the [current log](../change_log.md).

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
