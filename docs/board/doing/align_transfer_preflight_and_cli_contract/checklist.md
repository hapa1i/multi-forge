# Align transfer preflight and CLI contract checklist

Current focus: complete independent review and merge PR #165 without activating the next Wave 6 member.

## Activation and prior-member closeout

- [x] Merge D020 independently in PR #164 (`26ab5f29`).
- [x] Start `agent/align-transfer-preflight-cli-contract` from merged `main` at `26ab5f29`.
- [x] Move D020 to `done/`, activate only this member, and repoint inbound board links.

## Fail-first reproduction

- [x] Retain a marked regression module naming D023, D028, and O022 (`7 failed, 2 passed` on `26ab5f29`).
- [x] Prove manager full-strategy preflight misses an over-budget `confirmed.transcript_path` fallback; assert the
  repaired path leaves no child state.
- [x] Prove fork full-strategy preflight misses the same fallback and reaches `fork_session()`.
- [x] Prove `--depth all` is rejected by Click while zero and negative values produce empty lineage; retain a positive
  integer control.
- [x] Prove explicit `--strategy` and `--depth` without `--fresh` reach ordinary reattach; retain the default reattach
  control.

## Implementation

- [x] Extract one transcript-source resolver with the assembler's artifact, confirmed-path, and live-Claude precedence.
- [x] Use that resolver in manager and fork full-strategy budget preflights before child state or launch.
- [x] Accept positive integer depth or `all`, traverse `all` to lineage termination, and keep durable depth numeric.
- [x] Reject zero and negative depth cleanly without context artifacts or child state.
- [x] Reject explicit transfer strategy/depth on non-fresh Claude resume while preserving defaults and native/rewind
  semantics.
- [x] Synchronize CLI help and the end-user session guide without changing the normative §3.9 contract.

## Acceptance coverage

| Test                       | Fixture                                                           | Assertion                                                     | Test file                                                       |
| -------------------------- | ----------------------------------------------------------------- | ------------------------------------------------------------- | --------------------------------------------------------------- |
| Manager fallback preflight | Parent with no copied artifact and oversized confirmed transcript | Raises before child manifest, index row, or transfer artifact | `tests/regression/test_bug_d023_d028_o022_transfer_contract.py` |
| Fork fallback preflight    | CLI parent with the same oversized fallback source                | Exits before `fork_session()` or Claude launch                | `tests/regression/test_bug_d023_d028_o022_transfer_contract.py` |
| Complete lineage           | Three-generation chain with `--depth all`                         | Traverses to the terminal ancestor and records numeric depth  | `tests/regression/test_bug_d023_d028_o022_transfer_contract.py` |
| Invalid depth              | Explicit zero and negative values                                 | Fails cleanly before transfer or child state                  | `tests/regression/test_bug_d023_d028_o022_transfer_contract.py` |
| Non-fresh shaping flags    | Existing Claude session plus explicit strategy/depth              | Rejects before reattach; omitted defaults still reattach      | `tests/regression/test_bug_d023_d028_o022_transfer_contract.py` |
| Resolver precedence        | Copied, missing-copied, confirmed, and live sources               | Preserves assembler precedence for every preflight consumer   | `tests/src/session/test_transfer.py`                            |
| Unbounded lineage safety   | Terminal and cyclic ancestry graphs                               | Traverses a finite lineage fully and rejects cycles           | `tests/src/session/test_transfer.py`                            |
| Typed ops boundary         | Cyclic and non-positive depth through regenerate and Codex ops    | Raises `ForgeOpError` with the `ValueError` retained as cause | `tests/regression/test_bug_d023_d028_o022_transfer_contract.py` |

## Review follow-up

- [x] Reproduce raw cyclic-lineage `ValueError` at both command-core assembly boundaries (`2 failed` on PR #165 head
  `ab60f86d`).
- [x] Translate assembly validation failures to `ForgeOpError` in transfer regeneration and Codex transfer assembly
  without masking state-corruption classifications.
- [x] Retain cyclic and non-positive depth coverage at both ops boundaries (`4 passed`).

## Verification and closeout

- [x] Run the focused transfer, resume-path, resume-CLI, fork-CLI, and retained regression slices (`134 + 192 passed`).
- [x] Run `./scripts/test-integration.sh tests/src/session/test_resume_integration.py` (`9 passed`).
- [x] Run the review-focused ops/CLI slice (`132 passed`), `make test-regression` (`740 passed`), and final
  `make pre-commit`; explicitly pass both new files through all applicable hooks.
- [x] Record implementation outcome, verification, and compatibility boundaries.
- [x] Run board relative-link, fragment, lane-graph, size, and diff checks (285 files, 719 relative links, 12-member
  graph: 1 `done` / 1 `doing` / 10 `todo`).
- [x] Open independent draft PR #165 without activating the next Wave 6 member.
