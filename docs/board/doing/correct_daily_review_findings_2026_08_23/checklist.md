# Correct Daily Review Findings 2026-08-23 Checklist

Activation base: `effff0b4` (`main`, 2026-08-23).

Current focus: risk-required integration and aggregate verification.

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
- [ ] Run focused tests and required Codex/session/proxy integration slices.

## Closeout

- [ ] Record verification evidence and design synchronization.
- [ ] Keep this member's implementation commits contiguous before the hook member begins.
