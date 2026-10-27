# Transfer summarizer fidelity verification

Verified on 2026-10-27 from `codex/transfer-summarizer-fidelity`, based on `484dfe04`.

## Retained evidence

The shared summarizer joins ordered text from list-form tool results and labels Agent/SendMessage arguments. Structured
retains these summaries only in groups containing user or assistant text, including user text alongside results. Full
output and AI-curation input also retain tool-only groups. Images and unsupported blocks remain omitted.

Results retain the existing 500-character cap; each labeled delegation argument retains the 100-character cap. Lone
surrogates in tool text become literal Unicode escapes before truncation. Valid Unicode stays intact. AI curation still
selects its output within the existing input budget; the tests establish input fidelity, not model behavior.

## Review correction

The initially reviewed head, `68e93e0f`, admitted tool-only groups to structured output. The small fixture and passing
aggregate suites did not catch the resulting expansion. Replaying three local transcripts confirmed the review:

| Transcript                          | Source bytes | Before PR tokens | Reviewed-head tokens | Revised tokens |
| ----------------------------------- | -----------: | ---------------: | -------------------: | -------------: |
| encouraging-parakeet, current       |   10,748,944 |           31,215 |              150,298 |         31,215 |
| encouraging-parakeet, 17:03 compact |    8,313,410 |           24,574 |              112,942 |         24,574 |
| gracious-cougar, current            |    7,841,108 |            3,265 |               45,391 |          3,265 |

Counts use local `cl100k_base` with the same renderer metadata. The largest output grew from 127,362 to 601,639 UTF-8
bytes and from 419 to 2,135 groups. Restoring the text-bearing-group condition restores the original sizes; none of the
three sampled structured outputs contains result excerpts after the correction. No transcript content was sent to a
provider or added to the repository.

Public transfer assembly for the largest transcript produces 127,882 UTF-8 bytes; adding the Codex interactive handoff
wrapper produces a 128,446-byte positional prompt with no assembly warnings.

The shared synthetic fixture now includes 1,000 tool-call/result pairs with modern request IDs. Reinstating the reviewed
condition in a network-disabled Linux container reproduces `OSError` / `E2BIG` through `invoke_codex_interactive` with a
mock executable. The corrected rendering launches successfully through the same path.

The surrogate failure is independent of that condition: newly retained list-form results and delegation arguments can
contain a JSON-escaped lone surrogate even in a small text-bearing group. All six structured/full write regressions
failed on the reviewed head and now pass. Escaping happens before the field caps, so the escape spelling cannot expand
the retained field beyond its existing cap plus `...`.

Restoring turn admission does not add an aggregate budget or change the launch context's trust contract. Structured can
still carry raw result excerpts inside text-bearing groups. A size cap does not make those excerpts trusted or guarantee
that every possible conversation fits a model or operating-system limit.

## Checks

- The initial implementation reproduced 13 focused failures and two additional mixed-message failures. The review
  correction added seven failing regressions: tool-traffic growth and six Unicode write cases.
- `PYTHON_DOTENV_DISABLED=1 .venv/bin/pytest tests/regression/test_bug_structured_transfer_tool_expansion.py tests/regression/test_bug_transfer_drops_block_list_tool_results.py tests/src/session/test_transfer.py tests/src/search/test_extractor.py -q`:
  **176 passed**.
- `PYTHON_DOTENV_DISABLED=1 env -u GEMINI_API_KEY ./scripts/test-integration.sh tests/integration/cli/test_transfer_fidelity_integration.py tests/integration/cli/test_session_commands_integration.py::TestSessionResume -q`:
  **8 passed**. Covers regenerate/show/edit/diff, reviewed fresh resume, frozen-child preservation and the Linux
  argument-size regression with mock Claude/Codex executables.
- `PYTHON_DOTENV_DISABLED=1 make test-unit`: **11,204 passed, 120 deselected**.
- `PYTHON_DOTENV_DISABLED=1 make test-regression`: **2,187 passed**.
- `make pre-commit`: **passed**, including formatting, both type checkers, file-size limits and Markdown links.

No live model inference was required or performed. The synthetic transcripts use supported native block shapes; this
card does not claim new native-runtime lifecycle or child-discovery coverage. Search coverage remains green without a
production extractor change.

## Review and closeout

PR #283 remains open. The initial head passed CI, including unit/regression, pre-commit, CodeQL and the clean-wheel
runtime check; revised-head CI and merged-tree closeout remain pending. The card stays in `doing/`; M1 and the broader
epic remain proposed.
