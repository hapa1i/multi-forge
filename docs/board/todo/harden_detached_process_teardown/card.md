# Harden detached process teardown

**Epic**: [`epic_wave6_correctness_maintenance`](../../doing/epic_wave6_correctness_maintenance/card.md).

**Lane**: `todo/` -- accepted Wave 6 work; parked pending fail-first regressions.

**Findings**: D027 and O012.

## Goal

Terminate the process groups Forge deliberately detaches, including on synchronous cancellation, before ownership is
discarded or control returns to the caller.

## Evidence and Authority

On `246aaff1`, LiteLLM starts with `start_new_session=True` but stop signals only its leader PID; the single-shot
headless runner has no `BaseException` cleanup path around `communicate()`. The process lifecycle contract is
[`docs/design_workflows.md` §4.5](../../../design_workflows.md#45-operational-constraints).

## Acceptance Criteria

- Backend stop signals the detached group and preserves the registry row when teardown cannot be authorized/completed.
- A single-shot `KeyboardInterrupt`/cancellation terminates and reaps the current child group, then re-raises.
- Normal exits, timeout envelopes, missing binaries, and grouped parallel behavior remain unchanged.
- Retain regressions and run backend CLI plus invoker unit/integration slices.

## Compatibility and Exclusions

Do not change backend ids, startup health semantics, headless result envelopes, or the five-worker concurrency cap.
