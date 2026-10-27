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

## Second review correction

A follow-up review of `4ae3d437` found three fixture entries that placed text before `tool_result`. All 36 mixed entries
in the local native Claude Code transcripts lead with their results, so the fixtures now match. Rendering does not
depend on block order, and no expected output changed.

The same review found that the 500- and 100-character caps could cut an escape such as `\udc80` mid-sequence, and that
lone surrogates in user or assistant text still crashed child writes before and after this PR. Message text is now
escaped at extraction, so structured, full, the curation input and the rewind tail share the escaped text; every cap
moves its cut before an escape it would split. Eight unit cases and six regressions failed before the change. The local
native transcripts contain no lone surrogates, so this hardens transfers against damaged JSON rather than fixing an
observed session.

The 128,446-byte prompt recorded above sat 2,625 bytes below Linux's per-argument limit, and a `full` transfer of the
same parent is about 837 KB. Interactive Codex bridges now check the framed prompt against `max_initial_prompt_bytes()`
inside the pre-launch rollback scope: Linux `MAX_ARG_STRLEN` (32 pages including the NUL) and, on every host, `ARG_MAX`
less the native arguments, sanitized child environment, NUL terminators, pointer arrays and 16 KiB of launch-metadata
headroom. Sizing and invocation share their argument/environment builder. An oversized prompt refuses with only
applicable alternatives and leaves no session or snapshot; four ops cases failed with the check disabled. Headless
`--task` turns and hook delivery do not carry the transfer in argv. In Docker, a prompt of exactly the computed limit
launches intact through the mock executable, and one more byte fails with `E2BIG`.

The final review reproduced an aggregate-limit failure with a 32 KiB native config option: the old fixed-headroom
calculation admitted a prompt that the kernel rejected. The revised budget counts that option and repeated-argument
pointers explicitly, and the ops regression verifies refusal before announcement or invocation with session/snapshot
rollback. A Docker check lowers Linux's stack soft limit so `ARG_MAX` binds, then verifies that the revised prompt
launches intact while the budget that ignores native options fails with `E2BIG`. On macOS, a local `/usr/bin/true` probe
with the same 32 KiB config option accepted the revised 996,371-byte prompt; the previous 1,029,736-byte budget failed
with `E2BIG`. Neither probe invoked a model.

The rewind tail's final 50,000-character cap now uses the same escape-aware cut as the field caps. Boundary regressions
cover all five partial cuts of a surrogate escape and the complete-escape boundary, retaining the existing truncation
notice. Restoring the reviewed budget and raw rewind cut in an isolated test process produces nine expected failures:
three budget regressions, five split-escape boundaries and the pre-launch rollback case.

## Checks

- The initial implementation reproduced 13 focused failures and two additional mixed-message failures. The review
  correction added seven failing regressions: tool-traffic growth and six Unicode write cases. The second correction
  added 14 failing Unicode cases and four launch-size cases that fail with the check disabled.
- `PYTHON_DOTENV_DISABLED=1 .venv/bin/pytest tests/regression/test_bug_codex_prompt_budget_ignores_native_args.py tests/regression/test_bug_transfer_message_lone_surrogate.py tests/regression/test_bug_structured_transfer_tool_expansion.py tests/regression/test_bug_transfer_drops_block_list_tool_results.py tests/src/session/test_transfer.py tests/src/search/test_extractor.py tests/src/session/test_codex_invoke.py tests/src/core/ops/test_codex_interactive.py tests/src/session/test_rewind_strategy.py -q`:
  **292 passed**.
- `PYTHON_DOTENV_DISABLED=1 env -u GEMINI_API_KEY ./scripts/test-integration.sh tests/integration/cli/test_transfer_fidelity_integration.py tests/integration/cli/test_session_commands_integration.py::TestSessionResume -q`:
  **10 passed**. Covers regenerate/show/edit/diff, reviewed fresh resume, frozen-child preservation, the tool-heavy
  Linux launch, the exact Linux per-argument boundary and aggregate argument-budget consumption by native options with
  mock Claude/Codex executables.
- `PYTHON_DOTENV_DISABLED=1 make test-unit`: **11,223 passed, 120 deselected**.
- `PYTHON_DOTENV_DISABLED=1 make test-regression`: **2,202 passed**.
- `make pre-commit`: **passed**, including formatting, both type checkers, file-size limits and Markdown links. The
  `docs/end-user/session.md` provider count was refreshed to 26,203 tokens, under its 30,000-token limit.

No live model inference was required or performed. The synthetic transcripts use supported native block shapes; this
card does not claim new native-runtime lifecycle or child-discovery coverage. Search coverage remains green without a
production extractor change.

## Docker storage follow-up

The user's full local integration run reported 534 passes and three failures. The guarded worker image's retained npm
logs showed `ENOSPC`; the sidecar entrypoint likewise failed to create `/root/.claude` after proxy startup, leaving the
audit test with a stopped container. The legacy-builder warning obscured the npm error because the assertion printed
only stderr.

Reclaiming 5.34 GB of unused, unshared Forge build-cache records restored the targeted run: **3 passed** in 48.70
seconds, using Claude 2.1.245, Codex 0.149.1 and reviewer Claude 2.1.248. No source change was needed. This was a rerun
of the three failures, not a second full integration run:

```bash
CLAUDE_VERSION=2.1.245 CODEX_VERSION=0.149.1 PYTHON_DOTENV_DISABLED=1 env -u GEMINI_API_KEY \
  ./scripts/test-integration.sh \
  tests/integration/docker/test_worker_native_controls.py::test_guarded_worker_with_inherited_helper_from_clean_wheel \
  tests/integration/sidecar/test_audit_plumbing.py::test_sidecar_proxy_id_overlay_and_host_visible_audit_and_usage \
  tests/integration/sidecar/test_sidecar_omit.py::test_sidecar_omit_withholds_key_from_claude_but_proxy_keeps_it -vv --tb=long
```

## Review and closeout

[PR #283](https://github.com/hapa1i/multi-forge/pull/283) merged on 2026-10-27 as `9751470b`. Its tree matches reviewed
head `fa4c53b6` exactly. All five CI checks passed, including unit/regression, pre-commit, CodeQL and the clean-wheel
runtime check; [merged closeout](checklist.md#merged-closeout) links the runs. M2 is in `done/`; M1 and the broader epic
remain proposed.
