# Close Daily Bug Scan Follow-ups 2026-08-24 Checklist

Activation base: `3820b32d` (`main`, 2026-08-24).

Current focus: PR #246 review and CI.

## Transcript Cleanup

- [x] Add a corrupt-manifest sibling-publication regression for aliased native-relocate cleanup.
- [x] Recover the narrow raw derivation identity needed to route cleanup through the locked owner decision.
- [x] Cover and reclaim nested Claude subagent logs while preserving legacy top-level discovery.

## Model Routing

- [x] Add config-derived sidecar regressions for fresh selection and stored-route replay.
- [x] Reject unsupported effective sidecar mode before routing side effects.
- [x] Add blank-template replay coverage and preserve explicit replacement recovery.

## Markdown Enforcement

- [x] Add composed external-alias/internal-symlink coverage.
- [x] Canonicalize only the external repository prefix.
- [x] Add a deletion-only hook invocation regression and make the hook run without matching staged Markdown files.

## Verification

- [x] Run focused cleanup, routing, CLI, and Markdown tests.
- [x] Run targeted session integration tests.
- [x] Run `make test-unit`, `make test-regression`, and `make pre-commit`.
- [x] Run Markdown, board-link, and diff checks.

## Delivery

- [x] Review the integrated diff for scope and architecture conformance.
- [x] Commit, push, and open [PR #246](https://github.com/hapa1i/multi-forge/pull/246) with verification evidence.

## Review Follow-ups

- [x] Require the exact canonical lowercase spelling in nested sidechain discovery and raw-alias recovery.
- [x] Pin flag-vs-config sidecar refusal routing and add the `--host-proxy` recovery to the configured-mode message.
- [x] Name the explicit `--proxy` replacement alongside `--no-proxy` in sidecar replay refusals.

## Acceptance Tests

| Test                      | Fixture                                                | Assertion                                              | Test File                                                           |
| ------------------------- | ------------------------------------------------------ | ------------------------------------------------------ | ------------------------------------------------------------------- |
| Corrupt alias race        | schema-invalid native-relocate child plus late sibling | sibling retains transcript and nested logs             | `tests/regression/test_bug_o085_reuse_transcript_reference_scan.py` |
| Nested log ownership      | UUID-scoped `subagents` directory                      | unowned logs are reclaimed without path escape         | `tests/src/session/claude/test_claude_paths.py`                     |
| Effective sidecar refusal | configured or persisted sidecar plus model route       | failure precedes planning, proxy startup, and mutation | `tests/src/cli/test_session_model_pins.py`                          |
| Blank-template replay     | neutral proxy route with empty template                | bare replay fails; explicit replacement succeeds       | `tests/src/core/ops/test_session_model_routing.py`                  |
| Composed repository alias | external repo alias plus internal directory symlink    | internal lexical target remains invalid                | `tests/src/scripts/test_check_markdown_links.py`                    |
| Deletion-only hook        | no present Markdown filenames                          | repository Markdown audit still runs                   | `tests/src/scripts/test_check_markdown_links.py`                    |

Evidence:

- Integrated focused cleanup, routing, resume/fork, and Markdown slice: 235 passed.
- `make test-unit`: 9,897 passed, 117 deselected.
- `make test-regression`: 1,072 passed.
- `./scripts/test-integration.sh tests/integration/docker/test_session_routing.py`: 2 passed.
- `make pre-commit`: all hooks passed; the 579-source Markdown audit, board file-limit preview, and `git diff --check`
  passed.
- Integrated review found and closed a nested-log symlink escape before final verification; both UUID-directory and
  `subagents`-directory escape regressions pass.
- PR #246 opened from `fix/daily-bug-scan-followups-2026-08-24` against `main` with the `bug` label.
- Review follow-ups closed fail-first: a case-variant raw alias could reclaim the canonical spelling's sidechain logs
  past the exact-string ownership scans; nested discovery and raw-alias recovery now require canonical form. 97 focused
  cleanup/routing/CLI tests; `make test-unit` 9,901 passed (117 deselected); `make test-regression` 1,073 passed; full
  pre-commit passed.
