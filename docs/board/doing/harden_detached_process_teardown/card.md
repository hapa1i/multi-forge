# Harden detached process teardown

**Epic**: [`epic_wave6_correctness_maintenance`](../epic_wave6_correctness_maintenance/card.md).

**Lane**: `doing/` -- active on `agent/harden-detached-process-teardown` from merged `main` at `b3150184`; production
changes remain blocked on retained fail-first regressions.

**Findings**: D027 and O012.

## Goal

Terminate the process groups Forge deliberately detaches, including on synchronous cancellation, before ownership is
discarded or control returns to the caller.

## Evidence and Authority

Rechecked on merged `main` at `b3150184`: LiteLLM starts with `start_new_session=True` but stop signals only its leader
PID; the single-shot headless runner has no `BaseException` cleanup path around `communicate()`. The process lifecycle
contract is [`docs/design_workflows.md` §4.5](../../../design_workflows.md#45-operational-constraints).

## Acceptance Criteria

- Backend stop signals the detached group and preserves the registry row when teardown cannot be authorized/completed.
- A single-shot `KeyboardInterrupt`/cancellation terminates and reaps the current child group, then re-raises.
- Normal exits, timeout envelopes, missing binaries, and grouped parallel behavior remain unchanged.
- Retain regressions and run backend CLI plus invoker unit/integration slices.

## Implementation Outcome

LiteLLM stop now sends `SIGTERM` to the recorded process-group id created by `start_new_session=True`, so descendants
receive the same teardown signal even when the original leader has already exited. An already-missing group remains a
successful stop. Permission and other signal failures propagate through `BackendManager.stop_backend()`, whose existing
remove-after-adapter ordering therefore retains the registry row for a clean CLI error and later retry.

The shared single-shot headless lifecycle now catches `BaseException` only to terminate and reap its current detached
child group through the existing `SIGTERM`/wait/`SIGKILL` helper, then re-raises the original cancellation. Ordinary
spawn errors still return `HeadlessResult` envelopes, and normal exits, timeouts, and grouped fan-out retain their
existing paths.

## Verification

The retained five-case regression failed on merged `main` at `b3150184` in the three expected cases while the
missing-group and normal-exit controls passed (`3 failed, 2 passed`). It now passes alongside the backend adapter,
manager, CLI, and Claude/Codex/grouped invoker slice (`124 passed`). Full unit tests pass (`8,972 passed`, one existing
platform skip, 122 deselected), as do all 745 marked regressions, 8 backend CLI integration tests, and 2 real-process
teardown integrations proving both a worker-group signal and cancellation cleanup.

The real Codex single-shot smoke was attempted but stopped at its environment preflight because no Codex credential is
configured; no subprocess launched. The hermetic real-process integration exercises the changed shared lifecycle without
external authentication.

Final pre-commit passes after its expected Markdown normalization. All 719 relative links across 286 board Markdown
files have existing targets, changed-document fragments resolve, and the 12-member Wave 6 lane graph is 2 `done` / 1
`doing` / 9 `todo`; size and diff checks pass.

## Compatibility and Exclusions

Backend ids, startup health semantics, ordinary headless result envelopes, and the five-worker concurrency cap are
unchanged. This work does not alter proxy-process ownership or add escalation/wait policy to long-running backend stop.
