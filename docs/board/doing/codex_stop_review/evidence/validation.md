# B4 candidate validation

Candidate: `c4354a9c48917d874d28a9807ca3fbf3092a0dd5`, 2026-10-11. Evidence publication follows in a separate commit.
The card remains `doing/` until merge and closeout. See [results and qualifications](README.md).

| Check                                                         | Result                                                                                                                                                      |
| ------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `make test-unit`                                              | 10,670 passed, 117 deselected; one failure in `test_shipped_provider_cache_matches_exact_file_bytes`.                                                       |
| `make test-regression`                                        | 1,483 passed.                                                                                                                                               |
| `SKIP=file-size-limits make pre-commit`                       | Passed formatting, types, secret scan, repository links and the other local hooks; provider-backed size check excluded pending permission.                  |
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

## Remaining check blocker

Four changed documents have stale SHA-keyed Anthropic token counts: `docs/design_installation.md`,
`docs/design_telemetry.md`, `docs/design_workflows.md`, and `docs/end-user/session.md`. Automatic approval review
rejected transferring unpublished document text to the external count-only API without explicit permission. The cache
was left intact and its regression test was not weakened. This is not a failed product test and not a passed size check.
The PR remains a draft until the operator authorizes the refresh or chooses another acceptable documentation change.

After permission, refresh those four exact files with `scripts/check-file-limits.py --refresh-token-cache`, then rerun
the cache contract and full `make pre-commit`. Counting is not model inference. Do not retry the external operation
while the permission question remains unanswered.

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
