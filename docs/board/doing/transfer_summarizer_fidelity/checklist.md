# Transfer summarizer fidelity checklist

**Current focus:** Standalone M2 review on `codex/transfer-summarizer-fidelity`, based on `484dfe04`. Implementation and
local verification are complete; see [verification](verification.md). PR review and CI remain pending.

M2 executes independently. Strategy selection, source discovery, curated JSON, child capture and the broader epic remain
outside this card. Preserve the pre-existing `AGENTS.md` working-tree edit.

## Implementation

- [x] Verify the card against transfer assembly, transcript grouping, search extraction and current documentation.
- [x] Create the standalone branch, move M2 to doing and update the epic link.
- [x] Reproduce list-form result loss and missing delegation fields with regression tests: 13 initial failures.
- [x] Retain ordered text blocks within the existing 500-character result cap; omit image/unsupported blocks.
- [x] Label and bound Agent/SendMessage fields using the existing 100-character tool-argument limit.
- [x] Verify structured/full output and mocked ai-curated input, including tool-only turns.
- [x] Preserve user text beside a supported result: two additional regressions failed before the correction.
- [x] Preserve ordinary tool formatting and search extraction behavior.
- [x] Update the session-context design and transfer guide.

## Acceptance

| Test                  | Fixture and assertion                                                                             | Test home                                                             |
| --------------------- | ------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------- |
| Result fidelity       | Text/image/text results retain ordered text; unsupported neighbors and image data stay absent     | `tests/regression/test_bug_transfer_drops_block_list_tool_results.py` |
| Delegation fields     | Agent type/description/prompt and SendMessage recipient/message fields remain labeled and bounded | `tests/src/session/test_transfer.py`                                  |
| Strategy input/output | Shared transcript survives structured/full rendering and reaches the mocked curation request      | `tests/src/session/test_transfer.py`                                  |
| Search parity         | The same list-form result remains searchable without an extractor rewrite                         | `tests/src/search/test_extractor.py`                                  |
| User-facing transfer  | Docker CLI regenerate/show and fresh resume preserve available tool evidence                      | `tests/integration/cli/test_transfer_fidelity_integration.py`         |

## Validation and review

- [x] Run focused unit/regression checks and relevant Docker integration tests without provider inference: 164 focused
  checks and seven Docker transfer/resume tests passed.
- [x] Run aggregate unit/regression, full pre-commit and board/link checks: 11,199 unit tests and 2,180 regressions
  passed; 120 integration-marked cases were deselected by the unit target.
- [x] Record evidence and limitations, review the complete diff and prepare the standalone PR.
- [ ] Address valid review findings and verify CI.
- [ ] After merge, verify the merged tree, record closeout and move M2 to done.
