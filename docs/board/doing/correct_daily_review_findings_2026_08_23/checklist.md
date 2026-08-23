# Correct Daily Review Findings 2026-08-23 Checklist

Activation base: `effff0b4` (`main`, 2026-08-23).

Current focus: review and merge [PR #243](https://github.com/hapa1i/multi-forge/pull/243); the routing-provenance
follow-up is implemented and verified.

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

## Review Follow-up

- [x] Persist proxy `wire_shape` in new route events while preserving reads of legacy journals that predate the field.
- [x] Round-trip Anthropic-passthrough model selection through strict event validation.
- [x] Compensate marked authority attempts when routing construction or validation fails before append.
- [x] Keep custom-route selection explicitly null and document the deliberate manifest-I/O lock hold.
- [x] Re-run focused, full, integration, and repository gates on the amended PR head.

## Closeout

- [x] Record verification evidence and design synchronization.
- [x] Keep the remediation implementation distinct from the retired commit-hook work.

## Verification Evidence

- Focused Codex/session, routing, proxy, config, PID, and Markdown regression groups pass; the final routing and
  authority follow-up set passes 121 tests.
- `make test-unit`: 9,764 passed, 117 integration-marked tests deselected.
- `make test-regression`: 1,068 passed.
- Required Codex start, direct Claude model-pin, Docker session-routing, and proxy runtime-truth integration slices
  pass.
- `make pre-commit`, the 567-source Markdown audit, and `git diff --check` pass on the integrated head.
