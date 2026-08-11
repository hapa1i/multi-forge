# Harden detached process teardown

**Epic**: [`epic_wave6_correctness_maintenance`](../../doing/epic_wave6_correctness_maintenance/card.md).

**Lane**: `done/` -- shipped in PR #166 (`5b50acc8`) after independent review.

**Findings**: D027 and O012.

## Goal

Terminate the process groups Forge deliberately detaches, including on synchronous cancellation, before ownership is
discarded or control returns to the caller.

## Evidence and Authority

Rechecked on merged `main` at `b3150184`: LiteLLM starts with `start_new_session=True` but stop signals only its leader
PID; the single-shot headless runner has no `BaseException` cleanup path around `communicate()`. The process lifecycle
contract is [`docs/design_workflows.md` §4.5](../../../design_workflows.md#45-operational-constraints).

Review of the first implementation at `a4071346` found two remaining paths through the same boundary: backend config
deletion swallowed a newly surfaced stop failure before deleting the config and claiming success, while failed startup
health still killed only the detached leader PID. Both review cases were retained fail-first before correction.

## Acceptance Criteria

- Backend stop signals the detached group and preserves the registry row when teardown cannot be authorized/completed.
- Backend config deletion reports every required stop failure, retains the config, and omits `Deleted` if any stop
  fails.
- Failed startup health kills the detached process group; cleanup failures remain typed, actionable start errors.
- A single-shot `KeyboardInterrupt`/cancellation terminates and reaps the current child group, then re-raises.
- Normal exits, timeout envelopes, missing binaries, and grouped parallel behavior remain unchanged.
- Retain regressions and run backend CLI plus invoker unit/integration slices.

## Implementation Outcome

LiteLLM stop now sends `SIGTERM` to the recorded process-group id created by `start_new_session=True`, so descendants
receive the same teardown signal even when the original leader has already exited. An already-missing group remains a
successful stop. Permission and other signal failures propagate through `BackendManager.stop_backend()`, whose existing
remove-after-adapter ordering therefore retains the registry row for a clean CLI error and later retry.

Backend config deletion now reports failures per managed process and continues attempting independent matching
processes, but aborts config removal and exits nonzero if any required stop fails. Failed startup health sends `SIGKILL`
to the same owned group instead of only its leader; an already-missing group remains a normal start failure, while other
cleanup errors are included in the typed `BackendStartError`.

The shared single-shot headless lifecycle now catches `BaseException` only to terminate and reap its current detached
child group through the existing `SIGTERM`/wait/`SIGKILL` helper, then re-raises the original cancellation. Ordinary
spawn errors still return `HeadlessResult` envelopes, and normal exits, timeouts, and grouped fan-out retain their
existing paths.

## Verification

The original retained five-case regression failed on merged `main` at `b3150184` in the three expected cases while the
missing-group and normal-exit controls passed (`3 failed, 2 passed`). The two review-added regression cases and their
focused mirrors then failed as expected on `a4071346` (`4 failed`). All seven regression cases now pass alongside the
backend adapter, manager, CLI, and Claude/Codex/grouped invoker slice (`128 passed`). Full unit tests pass
(`8,974 passed`, one existing platform skip, 122 deselected), as do all 747 marked regressions, 8 backend CLI
integration tests, and 3 real-process teardown integrations proving stop, failed-start, and cancellation group cleanup.

The real Codex single-shot smoke was attempted but stopped at its environment preflight because no Codex credential is
configured; no subprocess launched. The hermetic real-process integration exercises the changed shared lifecycle without
external authentication.

Final pre-commit passes after its expected Markdown normalization. All 719 relative links across 286 board Markdown
files have existing targets, changed-document fragments resolve, and the post-merge 12-member Wave 6 lane graph is 3
`done` / 0 `doing` / 9 `todo`; size and diff checks pass. All five GitHub checks passed before merge.

## Compatibility and Exclusions

Backend ids, startup health semantics, ordinary headless result envelopes, and the five-worker concurrency cap are
unchanged. This work does not alter proxy-process ownership or add escalation/wait policy to long-running backend stop.
