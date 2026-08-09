# Unify downstream telemetry retention ownership

**Epic**: [`epic_cli_proxy_runtime_correctness`](../epic_cli_proxy_runtime_correctness/card.md).

**Decision**: [`downstream_retention_ownership`](../downstream_retention_ownership/card.md) (DG3; D015).

**Lane**: `done/` -- shipped in PR #148 (`8b997e6a`) after independent review.

## Goal

Give `~/.forge/telemetry/downstream/` one global retention policy and one startup pruner without silently resolving
conflicting legacy proxy policies.

## Evidence

Rechecked on merged `main` at `3f3a3c6d` with one 30-day-old downstream shard. Audit's 90-day wrapper preserved it;
provider trace's subsequent 14-day wrapper deleted the same shard. Both server startup latches still call wrappers that
delegate to `prune_downstream_records()` over the same directory, so the effective policy is the stricter pair.

## Scope

- Add global `telemetry.downstream.retention_days` and `max_total_mb` runtime configuration.
- Replace audit/provider-trace wrapper pruning with one downstream pruner call per proxy process.
- Resolve identical legacy values as a warned compatibility source; explicit global config wins.
- On conflicting legacy policies, skip pruning, start degraded, and expose the conflicting proxy IDs.
- Preserve spend-cap bootstrap order and current-UTC-month protection from age and size pruning.
- Provide an explicit user-owned config migration path; normal startup must not rewrite proxy files.

## Recorded Compatibility Limit

During the first-release compatibility window, a sidecar sees only its mounted proxy directory while sharing the host
downstream telemetry directory. Distinct sidecars therefore cannot detect each other's conflicting legacy inputs unless
the host has an explicit global policy. Operators must migrate or set that policy before multi-sidecar use; the approved
following-release rejection of proxy-local keys retires this limitation.

## Acceptance Criteria

- Human and JSON status report configured/effective/source values plus deprecations or conflicts.
- Tests cover defaults, omitted values, global precedence, identical/conflicting legacy values, one-call startup,
  best-effort errors, cap bootstrap, and current-month retention boundaries.
- Add a marked D015 regression that fails on the dual-pruner merged-main baseline.
- `docs/design.md`, `docs/design_appendix.md`, runtime configuration docs, and operator guidance move ownership only
  when the implementation ships.

## Verification

Run focused config/telemetry/proxy tests, targeted proxy integration tests, and `make pre-commit`.
