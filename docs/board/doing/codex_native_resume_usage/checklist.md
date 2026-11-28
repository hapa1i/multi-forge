# Direct Codex resume token accounting

[Card](card.md) · Branch `codex/codex-native-resume-usage` · Base `86a10000` on `main`.

## Current focus

Measure what a direct `codex exec resume` reports on an existing thread. The proxy fixture established cumulative
counters on its route. The direct request builder currently forwards the native terminal counters to the usage event and
downstream attempt. The direct measurement determines whether the implementation needs to change.
[Request builder and parser](../../../../src/forge/core/invoker/codex.py) ·
[Usage emitter](../../../../src/forge/core/usage/emit.py)

## Measure one native thread

- [ ] Set up an isolated Forge project, a disposable native-auth `CODEX_HOME` and a fixture Claude parent. Record the
  Codex version and preflight auth source and billing mode. Set `CODEX_HOME` before starting pytest if using the
  native-auth fixture, which captures the configured home at import time.
  [Native lifecycle fixture](../../../../tests/integration/core/test_codex_session_start.py) ·
  [Auth fixture](../../../../tests/integration/conftest.py)
- [ ] Start with
  `forge session start meter --runtime codex --no-proxy --resume-from planner --strategy structured --task "Reply with one word."`.
  Run two successive `forge session resume meter --task "Repeat your previous answer."` launches. Exercise a failed
  resume followed by a successful one on the same thread. Verify the saved native route and record the thread ID and
  each launch's run ID, root run ID and outcome.
- [ ] Record the first turn's ending rollout totals. Before and after each resume, read input, cached input and output
  from the bound rollout's `total_token_usage`. For every launch, capture the raw JSONL `turn.completed.usage` at the
  parser boundary if emitted. Retain the numeric evidence and identifiers in the card.
- [ ] With nonzero prior usage, compare the resumed terminal counters against both the ending totals and the change
  since launch. Record which matches for each field. Compare with the matching `codex_exec` ledger event and direct
  attempt, then reconcile the sum of per-launch usage with `forge telemetry activity meter --period all --json`. Check
  input and output totals and cached tokens in the downstream rows. Count each launch once.

## Decide from the measurement

- [ ] If native terminal usage is cumulative, capture the baseline from the bound native thread before spawning and
  reuse `continued_usage_delta` for the result consumed by both telemetry writers. The proxy replay reader requires a
  `forge_proxy` rollout, so the native path must validate its own thread and provider.
  [Delta calculation](../../../../src/forge/core/runtime/codex_usage.py) ·
  [Proxy replay reader](../../../../src/forge/core/ops/codex_replay.py)
- [ ] If the native values are already per-launch, keep the current calculation and encode the observed behavior in a
  regression. If the observations disagree or a field is indistinguishable in the fixture, record that uncertainty
  before choosing a calculation.

## Acceptance fixtures

| Fixture                                                                | Observable result                                                                                                                                                                |
| ---------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Fresh direct start and two successful resumes on one thread            | Each event and its matching attempt report the measured launch usage. The activity total includes each launch once.                                                              |
| Failed resume followed by a successful resume                          | The failed attempt retains its outcome and available evidence. The next success excludes tokens from earlier launches.                                                           |
| Cumulative counters with zero, missing, malformed or decreasing values | A verified zero delta stays zero. An unusable baseline or terminal counter, including cached delta above input delta, leaves usage unknown.                                      |
| Direct native, managed proxy and native fork controls                  | Direct events preserve preflight billing mode, `codex_jsonl` reporting and unknown cost. Proxy charge attribution and fork baseline subtraction still pass their existing tests. |

## Verification and closeout

- [ ] Run the affected invoker, telemetry and regression tests. Exercise the native session and proxy controls through
  `./scripts/test-integration.sh`, retaining the native counters alongside the CLI totals.
  [Proxy integration](../../../../tests/integration/core/test_managed_codex_proxy.py) ·
  [Fork regression](../../../../tests/regression/test_bug_codex_fork_inherited_usage.py)
- [ ] Update the [telemetry design](../../../design_telemetry.md) with the observed wire behavior and how Forge reports
  it. Run the unit, regression, pre-commit and board-link checks. Record the PR and evidence before moving the card to
  `done/`.
