# Transfer summarizer fidelity verification

Verified on 2026-10-27 from `codex/transfer-summarizer-fidelity`, based on `484dfe04`.

## Retained evidence

Structured/full transfers and AI-curation input retain ordered text from list-form tool results. The shared fixture
includes text/image/text results, Agent delegation, a native-shaped SendMessage, a string result and neighboring user
text. Structured output also retains tool-only turns. Search already preserved the result text and needs no production
change.

Results retain the existing 500-character cap; each labeled delegation argument retains the 100-character cap. Both
append `...` when truncated. Images, malformed fields and unsupported blocks are omitted without hiding valid neighbors.
AI curation still chooses its output; the tests establish its input fidelity, not model behavior. Source discovery,
strategy selection, curated JSON and child capture are unchanged.

## Checks

- The initial focused run reproduced 13 failures. Two additional mixed-message regression cases failed before the
  structured renderer was corrected to retain user text beside supported results.
- `PYTHON_DOTENV_DISABLED=1 .venv/bin/pytest tests/regression/test_bug_transfer_drops_block_list_tool_results.py tests/src/session/test_transfer.py tests/src/search/test_extractor.py -q`:
  **164 passed**.
- `PYTHON_DOTENV_DISABLED=1 env -u GEMINI_API_KEY ./scripts/test-integration.sh tests/integration/cli/test_transfer_fidelity_integration.py tests/integration/cli/test_session_commands_integration.py::TestSessionResume -q`:
  **7 passed**. Docker covers transfer regenerate/show/edit/diff, fresh resume with review, delivery to the launch
  context, and preservation of the frozen child after later regeneration.
- `PYTHON_DOTENV_DISABLED=1 make test-unit`: **11,199 passed, 120 deselected**. The initial aggregate run found one
  board-link failure because the new checklist was not staged; staging the task files corrected the candidate Git state,
  and the complete rerun passed.
- `PYTHON_DOTENV_DISABLED=1 make test-regression`: **2,180 passed**.
- `make pre-commit`: **passed**, including both type checkers, repository file-size limits and Markdown links.

The Docker tests use the existing mock Claude fixture, and AI-curation coverage replaces the provider call. No live
model inference was required or performed. The synthetic transcript matches the supported native block shapes; this card
does not claim new native-runtime lifecycle or child-discovery coverage.

## Review and closeout

Self-review covered the complete implementation, tests and documentation diff. PR review, CI and merged-tree closeout
remain pending. The card remains in `doing/`; M1 and the broader epic remain proposed.
