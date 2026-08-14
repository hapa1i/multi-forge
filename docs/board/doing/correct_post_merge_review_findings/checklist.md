# Correct post-merge review findings checklist

Current focus: implementation and primary verification are complete on `fix/post-wave-review-findings`; finish the
review-strength and board-integrity amendments before opening the PR.

## Evidence and implementation

- [x] Reproduce and verify the five reported defects against merged production code rather than accepting the review
  claims wholesale.
- [x] Retain an immutable canonical walkthrough root across `env.sh` and pin reassignment rejection plus safe-alias
  compatibility.
- [x] Reject filtered `any` and named tool selections before upstream acquisition while preserving other mappings.
- [x] Resolve absolute/colon TZif paths and POSIX rule strings with transition-aware process-local semantics.
- [x] Surface rollback deletion failure, retained child identity, and exact worktree-aware cleanup guidance.
- [x] Give shadow `show` and `status` positional-session recovery in both human and JSON modes.
- [x] Synchronize normative design, end-user proxy/session/transfer guidance, and bundled walkthrough safety docs.

## Acceptance tests

| Boundary         | Fixture                                                | Assertion                                                 | Test file                                                                                                                                            |
| ---------------- | ------------------------------------------------------ | --------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| Walkthrough root | marked target whose `env.sh` redirects to home         | command never runs; immutable-root error names both paths | `tests/regression/test_bug_o036_walkthrough_sandbox_provenance.py`                                                                                   |
| Tool filtering   | all tools filtered under `any`, or named tool filtered | typed 400 occurs before upstream client acquisition       | `tests/src/proxy/test_converters.py`; `tests/regression/test_bug_d030_o008_o015_o035_proxy_request_semantics.py`                                     |
| Local periods    | New York TZif path/colon path and POSIX DST rule       | exact UTC bounds and winter/summer offsets                | `tests/regression/test_bug_timezone_environment_forms.py`                                                                                            |
| Rollback failure | rewind/native-relocate child whose deletion raises     | retained child and exact cleanup command are visible      | `tests/regression/test_bug_o017_rewind_resume_unready_fallback.py`; `tests/src/cli/test_session_fork.py`; `tests/src/cli/test_session_rewind_cli.py` |
| Shadow recovery  | multiple local sessions with no explicit target        | human/JSON guidance uses positional `SESSION`             | `tests/regression/test_bug_o013_o034_policy_routing_context.py`                                                                                      |

## Verification and closeout

- [x] Run the focused correction suite (`230 passed`).
- [x] Run `make test-unit` (`9,115 passed, 1 skipped, 122 deselected`) and `make test-regression` (`906 passed`).
- [x] Run targeted proxy/rewind Docker coverage (`5 passed`) and the full session-lifecycle Docker target (`23 passed`).
- [x] Run `uv build` and the clean-wheel LiteLLM runtime smoke; confirm the wheel contains the walkthrough wrapper and
  declares the direct `python-dateutil` dependency.
- [x] Run full `make pre-commit` after the implementation changes.
- [x] Pin `--keep-worktree` absence for both worktree-fork recovery variants and rerun their focused tests
  (`71 passed`).
- [x] Run final Markdown, link/lane, pre-commit, and diff checks after board synchronization (338 board documents, 871
  relative links, none missing; three active cards, including the two coordinating epics; all hooks pass).
- [ ] Open the corrective PR without activating Wave 7 order 8.
- [ ] After merge, add the compact change-log outcome, move this card to `done/`, repoint links, and only then select
  the next Wave 7 member.
