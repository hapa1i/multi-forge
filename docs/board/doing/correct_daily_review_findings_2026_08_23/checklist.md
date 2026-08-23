# Correct Daily Review Findings 2026-08-23 Checklist

Activation base: `effff0b4` (`main`, 2026-08-23).

Current focus: review and merge [PR #243](https://github.com/hapa1i/multi-forge/pull/243); implementation and required
verification are complete.

## Session Safety

- [x] Add fail-first coverage for retained Codex state after spawn/post-child failure and preserved rollback before
  route projection.
- [x] Disarm destructive creation rollback after route projection and clear only one-shot staged hook context on
  retained failures.
- [x] Add a publication-lock transaction for the final relocated-transcript ownership decision and unlink.
- [x] Prove the exact publication/deletion interleaving with deterministic synchronization.

## Provenance and Recovery

- [x] Thread the actually applied Claude model pin into route payload construction, including ignored and passthrough
  cases.
- [x] Compose proxy server identity with runtime-truth parsing when optional tiers are empty.
- [x] Read stored `skills.invocation` independently for config edit/reset comparisons.
- [x] Validate active-registry PID representability for strict and repairing reads.

## Repository Correctness

- [x] Audit tracked plus supplied Markdown and validate local targets against candidate Git state.
- [x] Repoint living design references without changing terminal board history.
- [x] Run focused tests and required Codex/session/proxy integration slices.

## Closeout

- [x] Record verification evidence and design synchronization.
- [x] Keep this member's implementation commits contiguous before the hook member begins.

## Verification Evidence

- Focused Codex/session, routing, proxy, config, PID, and Markdown regression groups pass.
- `make test-unit`: 9,772 passed, 117 integration-marked tests deselected.
- `make test-regression`: 1,068 passed.
- Required Codex start, Docker session-routing, and proxy runtime-truth integration slices each pass.
- `make pre-commit`, the 567-source Markdown audit, and `git diff --check` pass on the integrated head.
