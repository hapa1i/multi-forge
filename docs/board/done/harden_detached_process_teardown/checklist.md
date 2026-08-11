# Harden detached process teardown checklist

Current focus: closed after independent review and merge in PR #166 (`5b50acc8`).

## Activation and prior-member closeout

- [x] Merge D023/D028/O022 independently in PR #165 (`b3150184`).
- [x] Start `agent/harden-detached-process-teardown` from merged `main` at `b3150184`.
- [x] Move D023/D028/O022 to `done/`, activate only this member, and repoint inbound board links.

## Fail-first reproduction

- [x] Prove LiteLLM stop signals only the detached leader PID rather than its process group.
- [x] Prove an authorization/teardown failure is swallowed and the backend registry row is discarded.
- [x] Prove synchronous cancellation escapes single-shot headless execution without terminating and reaping its child
  (`3 failed, 2 passed` on merged `main` at `b3150184`).
- [x] Retain review-added guards proving backend delete falsely succeeds after a stop failure and failed startup health
  kills only the detached leader (`4 failed` across the two regressions and focused mirrors on `a4071346`).
- [x] Retain compatibility controls for missing processes, normal headless exits, timeout envelopes, missing binaries,
  and grouped parallel cancellation.

## Implementation

- [x] Terminate the owned LiteLLM process group and surface teardown failures so registry ownership is retained.
- [x] Fail backend config deletion visibly and retain the config when any required managed-process stop fails.
- [x] Kill the detached LiteLLM group on failed startup health and type any cleanup failure as `BackendStartError`.
- [x] Terminate and reap the current single-shot child group on `BaseException`, then re-raise the cancellation.
- [x] Preserve backend ids/startup health, headless result envelopes, and grouped five-worker behavior.

## Verification and closeout

- [x] Run focused backend adapter/manager/CLI and Claude/Codex/grouped invoker tests (`128 passed`).
- [x] Run backend CLI integration (`8 passed`) and real-process group teardown integration (`3 passed`); disclose the
  credential-blocked Codex smoke attempt.
- [x] Run `make test-unit` (`8,974 passed`, one existing platform skip, 122 deselected) and `make test-regression`
  (`747 passed`).
- [x] Run `make pre-commit` and final board integrity checks (286 files, 719 relative links, post-merge 12-member graph:
  3 `done` / 0 `doing` / 9 `todo`).
- [x] Record fail-first evidence, implementation outcome, verification, and compatibility boundaries.
- [x] Open independent draft PR #166 and merge it as `5b50acc8` without activating the next Wave 6 member.
