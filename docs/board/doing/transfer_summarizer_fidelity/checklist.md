# Transfer summarizer fidelity checklist

**Current focus:** Review the corrected M2 implementation in PR #283. Structured preserves text-bearing-group admission;
UTF-8-safe message and tool text and the Codex launch-size refusal pass local verification. See
[verification](verification.md).

M2 executes independently. Strategy selection, source discovery, curated JSON, child capture and the broader epic remain
outside this card. Preserve the pre-existing `AGENTS.md` working-tree edit.

## Implementation

- [x] Verify the card against transfer assembly, transcript grouping, search extraction and current documentation.
- [x] Create the standalone branch, move M2 to doing and update the epic link.
- [x] Reproduce list-form result loss and missing delegation fields with regression tests: 13 initial failures.
- [x] Retain ordered text blocks within the existing 500-character result cap; omit image/unsupported blocks.
- [x] Label and bound Agent/SendMessage fields using the existing 100-character tool-argument limit.
- [x] Verify structured/full output and mocked ai-curated input, preserving each strategy's turn-admission rule.
- [x] Preserve user text beside a supported result: two additional regressions failed before the correction.
- [x] Preserve ordinary tool formatting and search extraction behavior.
- [x] Update the session-context design and transfer guide.

## Review correction

- [x] Reproduce structured growth on the reported 10.7 MB transcript: 31,215 to 150,298 local `cl100k_base` tokens.
- [x] Restore text-bearing-group admission; all three sampled large transcripts return to their pre-PR sizes.
- [x] Reproduce and fix lone-surrogate failures independently of turn admission; escape before existing field caps.
- [x] Add tool-heavy and Unicode regressions: all seven new cases failed on the reviewed head.
- [x] Verify the corrected transfer/resume paths and Linux Codex launch with a mock executable in Docker: eight passed;
  restoring the reviewed condition separately reproduced `E2BIG` in a network-disabled container.
- [x] Run aggregate unit/regression and full pre-commit checks on the revised implementation.

## Second review correction

- [x] Order mixed user entries as native transcripts do, with tool results before neighboring text, in the shared
  fixture, both mixed-entry regressions and the late-result integration case.
- [x] Keep surrogate escapes whole at every cap and escape lone surrogates in message text, covering structured/full
  output and the curation and rewind inputs: 14 new or tightened cases failed before the change.
- [x] Refuse an interactive Codex bridge whose initial prompt exceeds the host's exec argument limit inside the
  pre-launch rollback scope, offering only applicable alternatives: four ops cases failed with the check disabled.
- [x] Confirm in Docker that the computed limit is Linux's exact `E2BIG` boundary and rerun aggregate checks.
- [x] Count native launch arguments, the sanitized child environment and pointer arrays in the aggregate prompt budget;
  share argument/environment construction with invocation and retain pre-launch rollback on refusal.
- [x] Apply escape-aware truncation to the rewind tail's final cap, preserving its existing truncation notice.
- [x] Verify the final fixes with aggregate checks and the Linux aggregate argument-limit reproduction: 11,223 unit
  tests, 2,202 regressions and 10 Docker tests passed.

## Acceptance

| Test                  | Fixture and assertion                                                                              | Test home                                                                             |
| --------------------- | -------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| Result fidelity       | Text/image/text results retain ordered text; unsupported neighbors and image data stay absent      | `tests/regression/test_bug_transfer_drops_block_list_tool_results.py`                 |
| Delegation fields     | Agent type/description/prompt and SendMessage recipient/message fields remain labeled and bounded  | `tests/src/session/test_transfer.py`                                                  |
| Strategy input/output | Structured retains admitted groups; full and mocked curation also receive tool-only evidence       | `tests/src/session/test_transfer.py`                                                  |
| Search parity         | The same list-form result remains searchable without an extractor rewrite                          | `tests/src/search/test_extractor.py`                                                  |
| User-facing transfer  | Docker CLI regenerate/show and fresh resume preserve available tool evidence                       | `tests/integration/cli/test_transfer_fidelity_integration.py`                         |
| Tool traffic volume   | 1,000 call/result pairs keep three text-bearing groups and launch through the Linux Codex path     | `tests/regression/test_bug_structured_transfer_tool_expansion.py`, Docker test above  |
| Unicode writes        | Message/tool lone surrogates become whole escapes within caps; valid Unicode survives child writes | `tests/regression/test_bug_transfer_message_lone_surrogate.py`, tool regression above |
| Codex launch size     | Prompts up to the host's argument limit launch; larger ones refuse before launch and roll back     | `tests/src/core/ops/test_codex_interactive.py`, `test_codex_invoke.py`, Docker test   |

## Validation and review

- [x] Run focused unit/regression checks and relevant Docker integration tests without provider inference: 176 focused
  checks and eight Docker transfer/resume/launch tests passed.
- [x] Run aggregate unit/regression, full pre-commit and board/link checks: 11,204 unit tests and 2,187 regressions
  passed; 120 integration-marked cases were deselected by the unit target.
- [x] Record evidence and limitations, review the complete diff and prepare the standalone PR.
- [ ] Address valid review findings and verify CI.
- [ ] After merge, verify the merged tree, record closeout and move M2 to done.
