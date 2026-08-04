# Unify downstream telemetry retention ownership

**Epic**: [`epic_repo_maintenance_round`](../../doing/epic_repo_maintenance_round/card.md).

**Decision**: [`downstream_retention_ownership`](../../done/downstream_retention_ownership/card.md) (DG3; D015).

**Lane**: `todo/` -- accepted Wave 5 implementation work.

## Goal

Give `~/.forge/telemetry/downstream/` one global retention policy and one startup pruner without silently resolving
conflicting legacy proxy policies.

## Scope

- Add global `telemetry.downstream.retention_days` and `max_total_mb` runtime configuration.
- Replace audit/provider-trace wrapper pruning with one downstream pruner call per proxy process.
- Resolve identical legacy values as a warned compatibility source; explicit global config wins.
- On conflicting legacy policies, skip pruning, start degraded, and expose the conflicting proxy IDs.
- Preserve spend-cap bootstrap order and current-UTC-month protection from age and size pruning.
- Provide an explicit user-owned config migration path; normal startup must not rewrite proxy files.

## Acceptance Criteria

- Human and JSON status report configured/effective/source values plus deprecations or conflicts.
- Tests cover defaults, omitted values, global precedence, identical/conflicting legacy values, one-call startup,
  best-effort errors, cap bootstrap, and current-month retention boundaries.
- `docs/design.md`, `docs/design_appendix.md`, runtime configuration docs, and operator guidance move ownership only
  when the implementation ships.

## Verification

Run focused config/telemetry/proxy tests, targeted proxy integration tests, and `make pre-commit`.
