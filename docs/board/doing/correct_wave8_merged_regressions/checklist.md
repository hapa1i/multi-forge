# Correct Wave 8 merged regressions checklist

Current focus: review and merge the verified corrective PR.

- [x] Branch from pushed order-6 closeout `113b5670` without activating Wave 8 order 7.
- [x] Independently reproduce all three automated-review findings on merged code.
- [x] Confirm and cover the equivalent streaming pre-dispatch trace failure.
- [x] Move provider-attempt marking behind adapter validation while preserving failed-dispatch and auth-retry traces.
- [x] Recheck destination safety after Git I/O and immediately before the worktree copy mutation.
- [x] Restore conflict-bearing dry-run previews to stdout with only the terminating diagnostic on stderr.
- [x] Pass the 72-test direct regression slice and the 57-test adjacent proxy-routing/auth slice.
- [x] Pass four targeted proxy/session/extension Docker integration checks.
- [x] Pass 9,328 unit tests, 964 regression tests, pre-commit, the 59,979-token design-doc size check, the 402-document/
  975-link board check, and diff checks.
- [ ] Merge the corrective PR and retain this card in `doing/` until its closeout lands on `main`.

## Acceptance tests

| Test | Fixture | Assertion | Test file |
| ---- | ------- | --------- | --------- |
| Local adapter validation | invalid `temperature=3.0`, real adapter, mocked upstream | no provider await and no trace in streaming or non-streaming mode | `tests/regression/test_bug_o045_failed_provider_attempt_traces.py` |
| Failed provider dispatch | callback-aware failing provider fake | exactly one incomplete joined trace remains | `tests/regression/test_bug_o045_failed_provider_attempt_traces.py` |
| Late destination swap | parent replaced during `is_file_tracked` | no copied file or directory appears outside the worktree | `tests/regression/test_bug_o089_o090_worktree_config_safety.py` |
| Conflicting dry-run streams | local enable plan with one conflict | preview is stdout; terminating diagnostic is stderr | `tests/regression/test_bug_d056_o097_cli_failure_diagnostics.py` |
