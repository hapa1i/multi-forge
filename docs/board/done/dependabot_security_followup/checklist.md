# Dependency security follow-up checklist

**Status:** Done on 2026-10-29. [PR #288](https://github.com/hapa1i/multi-forge/pull/288) is merged, both requested
alerts are fixed, and default-branch Dependabot has zero open alerts. See [verification](verification.md).

- [x] Read both open alerts and verify patched releases against upstream advisories.
- [x] Trace development/runtime ownership and review the user-approved expansion to 14 additional advisories.
- [x] Capture advisory identities and pre-upgrade failures: three Bash transitions, existing-file preservation and three
  runtime metadata assertions.
- [x] Raise the five security floors/pins and review the selected lock changes.
- [x] Verify Bash prompt transitions, filelock/Hugging Face compatibility and wheel metadata separation.
- [x] Regenerate/check dependency exports and repeat the complete lock audit with no skipped packages.
- [x] Run unit/regression suites and focused proxy/backend integration checks without provider inference.
  - Unit: 11234 passed; regression: 2218 passed; integration: 19 passed.
- [x] Pass full pre-commit, build and the clean-wheel runtime smoke; refresh final documentation counts.
  - Provider counts match the final document bytes. The owner authorized routine token-count API calls without repeated
    confirmation; `AGENTS.md` records that standing permission.
- [x] Prepare the PR with exact verification and limitations.
- [x] After merge, verify default-branch alert closure and record card closeout.

## Review follow-up

- [x] Drain PTY output, isolate inherited history, and require the literal prompt; verify Bash 3.2 and 5.3 plus
  fail-first controls.
- [x] Make the stale-lock fixture resolvable offline and prove that removing `--locked` makes its regression fail.
- [x] Explain the transitive runtime floors and remove extra major-version caps without changing the locked versions.
- [x] Document stop-before-upgrade ordering and rebuilding sidecar base and final images before recreating containers.
- [x] Refresh document counts, run relevant checks and update the PR evidence.

## Acceptance fixtures

| Fixture                                                            | Assertion                                                                                      | Evidence                                                           |
| ------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| Virtualenv prompt containing a temporary marker command            | Enabling prompt expansion, entering POSIX mode or exporting `PS1` to a child never executes it | `test_bug_virtualenv_bash_prompt_expansion.py`                     |
| Existing lock target with content and mode `0640`                  | Lock acquisition preserves both bytes and permissions                                          | `test_bug_filelock_existing_target.py`                             |
| Built wheel and installed distribution metadata                    | Patched runtime floors ship; development tools remain absent                                   | `test_bug_wheel_dependency_floor_metadata.py` and wheel inspection |
| Local LiteLLM streaming response with outbound connections blocked | Cost, missing usage, zero cost and cap behavior remain intact                                  | `test_litellm_streaming_cost_e2e.py`                               |
| Fresh hash-checked wheel environment                               | Dependencies are compatible and the packaged LiteLLM starts and responds to health checks      | `scripts/test-wheel-runtime.sh`                                    |

## Merged closeout

- [PR #288](https://github.com/hapa1i/multi-forge/pull/288) merged as `982e589b` on 2026-10-29. Its tree matches
  reviewed head `80fe298b`; test, pre-commit, CodeQL, Analyze (python) and Analyze (actions) all passed.
- GitHub marks [virtualenv #61](https://github.com/hapa1i/multi-forge/security/dependabot/61) and
  [Black #62](https://github.com/hapa1i/multi-forge/security/dependabot/62) as fixed, with no dismissals. The
  default-branch open-alert query returns an empty list. The 138-package audited version inventory is unchanged.
- [Verification](verification.md) retains 11,234 passing unit tests, 2,218 regressions, focused integrations,
  cross-platform prompt controls, build/clean-wheel/image checks and full pre-commit. No provider inference ran.
- [Telemetry design](../../../design_telemetry.md#314-cost-tracking-and-spend-caps) reflects LiteLLM 1.102.2. The
  [upgrade guide](../../../end-user/proxy.md#applying-dependency-security-updates) and
  [session guide](../../../end-user/session.md) cover host stop/upgrade/start and sidecar image/container replacement;
  provider counts still match their final bytes.
- The
  [installation notes](../../impl_notes/core_installation.md#security-regressions-must-exercise-the-failure-path-dependabot_security_followup-reviewed-2026-10-29)
  retain the human-reviewed PTY/history and stale-lock test lessons. The change log records closeout, and the card is in
  `done`.
- Closeout validation passed documentation hooks, board links, file-size limits, cached-content hash checks and
  `git diff --cached --check`.
