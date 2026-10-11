# B4 candidate validation

The latest [PR review follow-up](review-followup.md) records the revised implementation's checks. The results below
belong to the original native candidate and are retained as historical evidence.

Candidate: `c4354a9c48917d874d28a9807ca3fbf3092a0dd5`, 2026-10-11. Evidence publication follows in a separate commit.
The card remains `doing/` until merge and closeout. See [results and qualifications](README.md).

| Check                                                         | Result                                                                                                                                                      |
| ------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `make test-unit`                                              | 10,671 passed, 117 deselected.                                                                                                                              |
| `make test-regression`                                        | 1,483 passed.                                                                                                                                               |
| `make pre-commit`                                             | Passed all hooks, including repository file-size limits, formatting, types, secret scanning and links.                                                      |
| Targeted installer Docker owners                              | 8 passed: `TestCodexHooksModule`, `TestCrossRuntimeSkillLifecycle`, `TestHookDispatcherRuntime`.                                                            |
| Claude Stop/supervisor/auth-isolation Docker controls         | 21 passed, one slow real-inference test deselected.                                                                                                         |
| `tests/integration/core/test_codex_stop_review.py --reruns 0` | One installed-wheel native integration test passed.                                                                                                         |
| `make build` and clean wheel install                          | Passed; every `src/forge/**/*.py` matches the installed candidate wheel.                                                                                    |
| Wheel lifecycle and logged-out reviewer                       | Enable/status/sync/runtime-scoped disable passed, packaged smoke-test asset present, unrelated config preserved; logged-out refusal dispatched no reviewer. |
| Offline product verifier                                      | Passed all recorded assertions; 32 reserved Codex units, one real Claude dispatch, no API inference.                                                        |
| Fixture teardown                                              | No recorded processes left; only the round's Codex login removed.                                                                                           |

Deterministic `forge policy check --bundle coding_standards` passed with both a file and stdin diff; the diff reported
one checked file. Both exited zero with clean result/diagnostic streams.

All integration owners ran through `./scripts/test-integration.sh`. The no-inference control invocation was:

```bash
./scripts/test-integration.sh \
  tests/integration/cli/test_stop_verification_integration.py \
  tests/integration/docker/test_supervisor_auth_isolation.py \
  tests/integration/docker/test_supervisor_e2e.py -m 'not slow'
```

The wheel correction used the same runner with `B4_TEST_ROUND` naming the owned round and `--reruns 0`. That test
requires an explicit independently authenticated fixture; it cannot default to the developer's login. The closed round
must not be reused. `b4-fixture.py` creates a new round; enrollment and fresh budget authorization precede another live
run.

## Documentation count gate

The initial unit/pre-commit runs detected four stale provider-count entries. Automatic approval review first refused
sending unpublished document text. After [PR #263](https://github.com/hapa1i/multi-forge/pull/263) published the exact
files, unauthenticated reads at commit `86cdc6bb` matched every local SHA-256. Automatic review accepted counting those
public bytes, and the four entries were refreshed. This was a count-only operation with no model inference. Full
`make pre-commit` and the final aggregate unit rerun pass. The original cache contract remains intact.

## Material limits

- Admission is limited to managed host Codex 0.162.1 with exact empirical event enrollment. General QA ceiling, release
  pin and shared QA provenance were not changed.
- Missing, incomplete or stale evidence cannot establish whole-turn approval. Capture covers bounded raw repository
  changes and observed actions; ignored/external effects and authorship by concurrent editors are outside that scope.
- Native cancellation capture 22 predates the parent-death fix and needed harness cleanup. The fix is verified with a
  model-free real-process regression; native cancellation was not repeated within the exhausted 32-unit ceiling.
- The single real subscription review replayed capture 15's frozen aggregate outside the hook. It did not assess the
  later correction, prove an invoice, or measure remaining quota. Quota-exhaustion detection remains unverified.
- Source hashes identify the actual helpers for each attempt. Publication-only changes post-date the final live
  controls; earlier failed or superseded attempts remain published.
