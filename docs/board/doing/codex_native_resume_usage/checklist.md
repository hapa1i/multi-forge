# Direct Codex resume token accounting

[Card](card.md) · Branch `codex/codex-native-resume-usage` · Base `86a10000` on `main`.

## Live subscription measurement

- [x] Ran Codex 0.172.0 on a native OpenAI route. The operator signed into a disposable file-backed `CODEX_HOME`. Forge
  preflight reported `codex_store` and `subscription_quota`. The fixture isolated the Forge home and excluded API
  credentials. [Verification procedure](../../../developer/verification.md#codex-runtime-consumer-lanes-and-supervision)
- [x] On one bound thread per run, started a session, rejected an unavailable model before generation, restored the
  original model, and ran two successful resumes. The rejection reported `model_not_found`, emitted no terminal usage,
  and appended no request tokens. The first success recalled the word from the original turn. Codex can replay item
  events before `turn.started`, so rejection evidence is scoped to the attempted turn.
- [x] Captured each launch's raw JSONL usage, independent rollout samples, appended request sums, matching ledger event
  and attempt, and CLI activity totals. Both successful resumes had a nonzero cached baseline. On every success the
  terminal matched the ending rollout, and the rollout delta matched the new request sum in all three fields.
  [Sanitized before-and-after evidence](evidence/native-resume-usage.json) · [Live fixture][lifecycle]
- [x] Before the correction, activity reported 167,502 input and 119 output tokens for measured work of 95,341 and 101.
  On the corrected thread, activity and independently summed work both reported 103,453 input and 101 output tokens.
  These whole-session comparisons include the fixture's separate `transfer-curate` event (350 input, 80 output).

## Accounting and acceptance fixtures

- [x] Capture the bound rollout baseline before launch. Before emitting either record, verify the returned thread,
  stable rollout prefix, provider, single foreground turn and fresh post-launch sample. Check the sum of new request
  records when present. Reuse the fork reader's token-count semantics and subtract once for both telemetry writers.
  [Native resume reader][reader] · [Shared counter calculation][delta]
- [x] Leave the entire token triplet unknown when evidence is incomplete or contradictory. Direct resume keeps its
  existing admission, exit status and thread-drift recovery. Direct compacted histories remain launchable with unknown
  usage. The live measurement covers the subscription route on 0.172.0.

| Test                            | Fixture                                                                                                       | Assertion                                                                                                           | Test file                                                           |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------- |
| Direct billing and activity     | Four native launches and one mocked curation event                                                            | Each event and attempt reports the measured usage once. Billing remains subscription and dollar cost stays unknown. | [Live lifecycle][lifecycle]                                         |
| Failed turn followed by success | Rejection before generation and a separate scripted mid-turn failure with partial rollout growth              | Failed tokens stay unknown. The next success excludes the earlier work.                                             | [Lifecycle], [regression]                                           |
| Counter continuity              | Stale or malformed sample, reset, prefix rewrite, mismatching terminal, impossible cached delta, genuine zero | Only a new corroborated sample can establish zero. Unusable evidence yields three unknowns.                         | [Reader tests][reader-tests], [regression], [fork tests][fork-test] |
| Turn ownership                  | Overlap, conflicting stream identities or terminals, and returned-thread drift                                | Uncertain usage stays unknown. Drift still warns and rebinds the session.                                           | [Reader tests][reader-tests], [stream], [regression]                |
| Adopted histories               | Desktop-shaped usage history and a bound rollout that later becomes missing or corrupt                        | The session resumes. Comparable native evidence supplies usage independently of the proxy turn grammar.             | [Regression]                                                        |
| Existing routes                 | Managed proxy resume and native review fork                                                                   | Proxy dispatch attribution and fork subtraction retain their existing behavior.                                     | [Proxy integration][proxy-test], [fork regression][fork-test]       |

## Verification and closeout

- [x] Ran the native lifecycle and the three managed proxy integration controls through `./scripts/test-integration.sh`.
  All four passed. Replaying the saved before/after byte ranges through the late-counter guard at `59b53d62` reproduced
  the request sums for all four measured successful resumes. All three token fields were distinguishable on this route.
- [x] Documented per-launch and historical reporting in the [telemetry design](../../../design_telemetry.md) and
  [session guide](../../../end-user/session.md#derive-a-codex-session-from-a-claude-parent-cross-runtime). Ordinary
  historical rows lack the baseline needed for a reliable backfill.
- [x] The two-worker runs passed all 12,166 unit tests and 2,761 regressions. The four-worker regression run missed one
  retry in the supervisor deadline test, which also passed in isolation. `make pre-commit` passed, including the
  repository-wide Markdown link audit.
- [ ] At merge, record the shipped revision and historical cutover in the [change log](../../change_log.md) and move the
  card to `done/`.

[delta]: ../../../../src/forge/core/runtime/codex_usage.py
[fork-test]: ../../../../tests/regression/test_bug_codex_fork_inherited_usage.py
[lifecycle]: ../../../../tests/integration/core/test_codex_session_start.py
[proxy-test]: ../../../../tests/integration/core/test_managed_codex_proxy.py
[reader]: ../../../../src/forge/core/runtime/codex_resume_usage.py
[reader-tests]: ../../../../tests/src/core/runtime/test_codex_resume_usage.py
[regression]: ../../../../tests/regression/test_bug_codex_native_resume_usage.py
[stream]: ../../../../tests/src/core/invoker/test_codex_stream.py
