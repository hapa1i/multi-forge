# Preserve proxy ownership on stop failure

**Epic**: [`epic_cli_proxy_runtime_correctness`](../epic_cli_proxy_runtime_correctness/card.md).

**Finding**: O002 (HIGH) in [`review_combined.md`](../../review_combined.md#code-and-maintenance-findings).

**Lane**: `doing/` -- active on `fix/preserve-proxy-ownership-on-stop-failure` from merged PR #148 (`8b997e6a`).

## Goal

Make `proxy stop` and `proxy delete` fail visibly and retain actionable ownership whenever an attempted process stop is
refused or fails.

## Design Authority

- [`docs/design.md` §3.6.3](../../../design.md#363-proxy-lifecycle-ux): the proxy surface owns configuration and process
  lifecycle.
- [`cli_style_guidelines.md` failure rules](../../../developer/cli_style_guidelines.md#review-checklist): a failed leaf
  exits non-zero and must not present success.

## Evidence

Rechecked on merged `main` at `8b997e6a` by forcing `_stop_proxy_process()` to return `error`. `proxy stop` returned
without raising and exited 0. `proxy delete` removed the registry row and proxy directory, ignored the stop outcome,
printed `Deleted`, and exited 0 while the simulated process remained live.

## Expected Behavior

- `proxy stop` exits non-zero and retains the registry state when an attempted stop returns `error`.
- `proxy delete` does not remove the last registry/config ownership or print `Deleted` unless its required stop
  succeeds.
- Adopted default detach, explicit `--no-kill`, already-stopped processes, and shared-port survivors remain intentional
  successful outcomes with accurate messages.
- Multi-delete continues independent targets, counts stop failures, and exits non-zero when any target fails.

## Acceptance Criteria

- Add a marked O002 regression covering both stop and delete when their required stop reports failure.
- Cover permission failure and identity refusal plus managed/adopted, last/shared reference, `--kill-adopted`,
  `--no-kill`, already-stopped races, and multi-delete aggregation in focused tests.
- Assert registry/config/process facts and output text/exit status; run focused proxy CLI tests, targeted process-backed
  integration, and `make pre-commit`.

## Compatibility and Exclusions

- Do not kill adopted processes without `--kill-adopted` or stop a shared server while another live alias owns it.
- Do not weaken the health/identity guard or erase recovery state merely to make delete look atomic.
