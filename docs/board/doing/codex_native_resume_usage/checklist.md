# Direct Codex resume token accounting

[Card](card.md) · Branch `codex/codex-native-resume-usage` · Base `86a10000` on `main`.

## Current focus

Determine whether a successful direct resume reports the thread total or this launch's usage. Extend
`test_start_then_resume_codex_session_real_turns`, which already verifies thread recall, the routing journal and event
attribution. Add the numeric assertions to those same launches. [Native lifecycle fixture][lifecycle]

## Capture one subscription thread

- [ ] Use an isolated Forge project and `FORGE_HOME`. Configure a disposable `CODEX_HOME` with
  `cli_auth_credentials_store = "file"` in its `config.toml`. Have the fixture operator sign in directly there with
  `CODEX_HOME=<fixture-home> codex login --device-auth`, then export that home **before** pytest starts. The fixture
  reads it at import and clears `CODEX_API_KEY` and `CODEX_ACCESS_TOKEN`. Verify `forge runtime preflight codex` and
  record the binary version, `auth_source=codex_store`, `billing_mode=subscription_quota`, native route and OpenAI
  provider. A paid API-key run is outside this measurement. [Auth fixture][auth] · [Verification guide][guide]
- [ ] On the fixture's existing headless session, run a fresh start, a rejected resume, then two consecutive successful
  resumes with short replies. Use the fixture's ordinary session authority so launch-only arguments are accepted. For
  the rejection, pass an unavailable native model
  (`forge session resume <name> --task "Reply OK" -- -m <unavailable-model>`). Verify that Codex rejected the request
  before generation from its error stream and absence of terminal usage. If Codex falls back to a model, the trial does
  not establish rejection. Resume with the supported model and retain the fixture's thread-recall assertion.
- [ ] Reproduce a mid-turn failure separately with a scripted child driving the real invoker. Emit `thread.started` and
  partial output, append a token sample, then emit `turn.failed` and exit nonzero without `turn.completed.usage`. Assert
  the outcome and unknown tokens in both records. Follow it with a success to verify that the failed turn's rollout
  growth is excluded by the next baseline.
- [ ] Write one sanitized row per launch to `evidence/native-resume-usage.json`. Record the run/root/thread IDs,
  returned thread, outcome and observed turn identity. Capture raw `turn.completed.usage` at the parser boundary. Read
  the rollout before spawning each resume and again after exit. For a fresh start, record the absent baseline and take
  the ending sample. For each source distinguish input, cached input and output, explicit zero and absence. Retain the
  rollout identity and sample offsets, and the sum of attributable new request records when available. Omit credentials
  and conversation text.
- [ ] For each successful resume compare the terminal triplet with both the post-launch total and the post-minus-pre
  delta. Use the second success to distinguish cached reporting if the first has a zero cached baseline. If both
  baselines are zero, record the live cached result as inconclusive and exercise a nonzero baseline in a scripted test.
- [ ] Retain the matching `codex_exec` event, native downstream attempt and
  `forge telemetry activity <name> --period all --json` totals. Check cached input in the attempt and sum each known
  launch once. Include the fixture's separate `transfer-curate` event (350 input, 80 output) in whole-session totals.

## Apply the measured semantics

- [ ] For cumulative counters, capture the baseline before spawn from the bound native rollout. Share the narrow
  `event_msg.token_count.info.total_token_usage` extraction and `CodexUsageBaseline.from_total_usage` validation used by
  native review. Its `last_token_usage` is for context sizing, and the post-compaction thread counter is a different
  series. The supervisor's admission rules and the proxy's `forge_proxy` turn grammar each apply to their own route.
  [Native selector][selector] · [Counter types and subtraction][delta] · [Proxy replay][proxy-reader]
- [ ] Before the invoker emits either record, require the returned thread to match the binding and the terminal triplet
  to equal a newly appended, launch-attributable rollout total on that thread and provider. Verify the pre-launch prefix
  is still intact and both samples use the same counter series. Require all three raw fields to be nonnegative integers.
  Then call `continued_usage_delta` once and pass that result to both writers. A larger per-launch terminal can pass
  monotonicity on its own. Direct preflight's validated version is advisory, so apply this guard at runtime. [Invoker] ·
  [Session continuation][session]
- [ ] If the observed terminal instead matches the independently established launch delta on a nonzero baseline,
  preserve per-launch reporting for the supported format and add a regression. Ambiguous formats, contradictory samples
  and unverified accounting yield three unknowns. Preserve the native launch, outcome and drift warning/rebind. Defer
  accounting for direct histories compacted before or during launch until comparable direct evidence exists.

## Acceptance fixtures

| Test                       | Fixture                                                                                                                                                                     | Assertion                                                                                                                                                                                   | Test File                                                     |
| -------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------- |
| Native totals              | Live subscription start, rejected resume and two successes                                                                                                                  | Each successful event and attempt agree with the measured launch. Session activity counts the Codex work once and includes curation. Native billing, reporter and unknown cost survive.     | [Lifecycle], [emitter][emit], [activity]                      |
| Rejection and interruption | Live rejection before generation, scripted mid-turn failure with partial rollout growth and no terminal usage                                                               | Failure retains its status and unknown tokens. The next success takes a fresh baseline that includes any partial work. Rollout-only growth cannot charge either launch for the failed turn. | [Lifecycle], [invoker tests][inv-tests]                       |
| Counter validation         | Per-launch terminal exceeds baseline but differs from post total, stale post sample, missing/malformed/decreasing counters, cached delta above input, and an evidenced zero | Invalid evidence yields three unknowns in both records. A newly observed, comparable zero delta stays zero.                                                                                 | [Invoker tests][inv-tests], [emitter][emit]                   |
| Identity and continuity    | Missing/ambiguous rollout, rewritten prefix, overlapping writers, unexpected provider, missing/changed returned thread, and compaction before or during launch              | Resume proceeds under existing session rules. Unknown tokens never use the old thread's baseline. Drift still warns and records the returned thread.                                        | [Session tests][session-tests], [invoker tests][inv-tests]    |
| Adopted native history     | Desktop-shaped header and token events with unrelated or absent proxy-style turn records                                                                                    | Adoption and resume proceed. Comparable launch-bound totals suffice for accounting. Insufficient evidence leaves usage unknown.                                                             | [Adoption][adopt], [session tests][session-tests]             |
| Other routes               | Managed proxy resume and native review fork with inherited cached input                                                                                                     | Existing proxy charge attribution and native fork delta assertions pass.                                                                                                                    | [Proxy integration][proxy-test], [fork regression][fork-test] |

## Verification and closeout

- [ ] Run the focused unit and regression files and the real native and managed proxy fixtures via
  `./scripts/test-integration.sh`. Record the measured version/route, artifact and any inconclusive fields.
- [ ] Update the [telemetry design](../../../design_telemetry.md) and [change log](../../change_log.md) with the
  verified behavior and first corrected release or commit, if applicable. Explain how activity spanning that boundary
  can include inflated historic direct resumes. Ordinary rows have no baseline or terminal evidence for a reliable
  backfill. Document the boundary without a schema marker or ledger rewrite.
- [ ] Run unit, regression, pre-commit and board-link checks. Record the PR and evidence before moving the card to
  `done/`.

[activity]: ../../../../tests/src/core/ops/test_usage_summary.py
[adopt]: ../../../../tests/src/core/ops/test_codex_adopt.py
[auth]: ../../../../tests/integration/conftest.py
[delta]: ../../../../src/forge/core/runtime/codex_usage.py
[emit]: ../../../../tests/src/core/usage/test_codex_emit.py
[fork-test]: ../../../../tests/regression/test_bug_codex_fork_inherited_usage.py
[guide]: ../../../developer/verification.md#codex-runtime-consumer-lanes-and-supervision
[inv-tests]: ../../../../tests/src/core/invoker/test_codex_invoker.py
[invoker]: ../../../../src/forge/core/invoker/codex.py
[lifecycle]: ../../../../tests/integration/core/test_codex_session_start.py
[proxy-reader]: ../../../../src/forge/core/ops/codex_replay.py
[proxy-test]: ../../../../tests/integration/core/test_managed_codex_proxy.py
[selector]: ../../../../src/forge/core/runtime/codex_review_source.py
[session]: ../../../../src/forge/core/ops/codex_session.py
[session-tests]: ../../../../tests/src/core/ops/test_codex_session.py
