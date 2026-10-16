# Reconcile daily bug scan findings

Status: **done**, closed 2026-10-16. [PR #266](https://github.com/hapa1i/multi-forge/pull/266) merged as `74eb9afa` on
2026-10-13. The [merged closeout](checklist.md#merged-closeout) records merge, validation and evidence limits.

User-authorized single fix PR, activated 2026-10-13 from `2ec4a22a` on `fix/daily-bug-scan-reconciliation-2026-10-13`.

The October 13 review reproduced six supervisor/Stop defects and sixteen older lifecycle, installer, and QA defects. Two
documentation corrections accompany them. The API-home publication race was already fixed by `f0d1d52c` and is a
regression control, not additional implementation scope.

## Scope

- Supervisor: disabled-policy relaunch, empty interrupted turns, submodule coverage, bounded patch evidence, fresh
  reviewer hook isolation, and fail-closed denied-action cleanup.
- Lifecycle: corrupt UUID cleanup, symlinked Claude project cleanup, Codex positional arguments, compaction validation,
  and invalid sidecar recovery guidance.
- Installation: runtime-scoped settings reads, unattributed file preservation, Codex path validation, immutable
  migration baselines, and descriptor-confined worktree config copying.
- QA: installed-driver source lookup, provider evidence, prerequisite closure, reused credentials, certificate cache
  identity, and section `.0` addressing.
- Documentation: spend-cap evidence ownership and the August 24 closeout's historical Markdown count.

The existing design contracts in `design_sessions.md`, `design_session_execution.md`, `design_installation.md`,
`design_subprocesses.md`, and the QA skill remain authoritative. Fixes restore those contracts without broad refactors.
Empirical quota exhaustion, historical config drift, and live cancellation qualifications are evidence limits, not
unproven bugs to fix in this PR.

## Execution ownership

One work item and PR contained separate reviewable commits. Supervisor, lifecycle, installer, and QA implementation used
disjoint files; the integrator owned shared documentation reconciliation, the board, aggregate tests, and PR. No paid
model probes were required. Review and merge are complete.
