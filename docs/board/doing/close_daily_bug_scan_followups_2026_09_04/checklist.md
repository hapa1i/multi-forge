# Close Daily Bug Scan Follow-ups 2026-09-04 Checklist

Activation base: `0087e81e` (`origin/main`, 2026-09-04).

Current focus: review [PR #253](https://github.com/hapa1i/multi-forge/pull/253); keep the card in `doing/` until merge
and closeout.

## Model Route Execution Projection

- [x] Add a fail-first launcher-to-proxy regression for an explicit historical Gemini Flash model.
- [x] Project the requested non-Claude model through the selected Claude tier without changing stored proxy mappings.
- [x] Preserve direct-Claude pins, default-tier launches, and route evidence.

## Passthrough Native Effort

- [x] Add fail-first regressions for canonical and provider-prefixed `[1m]` native-effort models.
- [x] Normalize the transport suffix before catalog lookup.
- [x] Add a fail-first sparse-effort regression and implement floor-specific upward normalization.
- [x] Preserve translated-path clamping and sanitized handler errors.

## Resume Recovery

- [x] Add a fail-first fresh-resume recovery regression covering explicit lifecycle options.
- [x] Build a resume-specific recovery action and pass it through planning, realization, and health-refusal paths.
- [x] Preserve bare-resume recovery output and pre-launch non-mutation.

## Documentation and Verification

- [x] Synchronize normative design and end-user guidance if implementation ownership or public behavior changes.
- [x] Run focused unit and regression tests for all four findings.
- [x] Run targeted session/proxy integration tests.
- [x] Run `make test-unit`, `make test-regression`, `make pre-commit`, build, link, size, and diff checks.

Review follow-ups:

- [x] Keep adaptive-only manual-thinking requests on the documented sanitized HTTP 400 path.
- [x] Use one model-alternative resolver across planning, launch evidence, dispatch, and status reporting.
- [x] Reject conflicting catalog-equivalent alternative keys while preserving exact private-slug matching.
- [x] Make recovery-action provenance explicit and cover long copyable commands at the renderer boundary.

Evidence on the final pre-commit tree:

- Focused changed tests: `403 passed`.
- Unit: `10,216 passed, 117 deselected`.
- Regression: `1,211 passed`.
- Targeted Docker integration: `6 passed` across session routing, persisted-route resume, packaged route loading, and
  passthrough headers.
- `make pre-commit`: passed all hooks, including Ruff, Black, mypy, Pyright, file-size limits, and Markdown links.
- `make build`: produced the 0.9.4 wheel and source distribution.
- `git diff --check`: passed.

## Acceptance Tests

| Test                            | Fixture                                                       | Assertion                                                               | Test File                                                  |
| ------------------------------- | ------------------------------------------------------------- | ----------------------------------------------------------------------- | ---------------------------------------------------------- |
| Non-Claude execution projection | historical Gemini Flash model plus compatible proxy           | launch request preserves selected model and tier; dispatch matches plan | `tests/regression/test_bug_non_claude_model_projection.py` |
| Native `[1m]` effort            | canonical and provider-prefixed Claude model references       | native effort is used; legacy budget/error path is not                  | `tests/regression/test_bug_passthrough_native_effort.py`   |
| Sparse effort floor             | `xhigh` with `low/medium/high/max` support                    | effective floor is `max`                                                | `tests/regression/test_bug_passthrough_native_effort.py`   |
| Fresh resume recovery           | unavailable persisted proxy route plus explicit fresh options | suggested reroute reproduces the complete intended action               | `tests/regression/test_bug_fresh_resume_route_recovery.py` |

## Delivery

- [x] Review the integrated diff for scope and architecture conformance.
- [ ] Add the completed-work change-log entry and close the card.
- [x] Commit, push, open one PR against `main`, and add available `bug`, `codex`, and `codex-automation` labels.

Delivery evidence:

- PR: [#253 — fix: preserve model routing and recovery intent](https://github.com/hapa1i/multi-forge/pull/253).
- Added the available `bug` label. The repository has no `codex` or `codex-automation` labels.
