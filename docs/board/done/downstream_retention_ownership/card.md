# Decide retention ownership for unified downstream telemetry

**Epic**: [`epic_repo_maintenance_round`](../epic_repo_maintenance_round/card.md) (DG3; D015).

**Lane**: `done/` -- approved on 2026-08-04; implementation shipped in PR #148 under
[`unify_downstream_retention`](../unify_downstream_retention/card.md).

## Problem

Audit and provider-trace retention settings drive separate pruner wrappers over the same unified downstream shard
directory. Running both makes the effective retention the stricter minimum, so one configured plane can silently defeat
the other's retention promise.

The design also points in both directions: appendix §A.11 exposes audit-specific retention, while §A.14 says provider
trace retention delegates to unified downstream pruning. The implementation cannot preserve independent retention
semantics when records share shards without a record-aware compaction contract.

## Decision Required

Choose and document:

- whether unified downstream storage has one retention owner and one configuration;
- or whether audit/provider record classes remain independently retainable;
- precedence and migration for existing `audit` and `provider_trace` settings;
- current-calendar-month and spend-cap bootstrap preservation requirements;
- startup pruning ownership and failure behavior; and
- what each CLI/status surface reports as configured versus effective retention.

## Evidence

- Review: [`review_combined.md` DG3 and D015](../../review_combined.md#decision-gates).
- Audit configuration: `docs/design_telemetry.md` §A.11.
- Unified provider lifecycle retention: `docs/design_telemetry.md` §A.14.
- Startup pruners: `src/forge/proxy/server.py:228,245` at the review baseline.

## Decision

**Status:** approved on 2026-08-04.

The physical directory `~/.forge/telemetry/downstream/` has one global retention policy and one pruner. Record classes
are not independently retainable because audit, cost, and provider-lifecycle fields can coexist in the same JSONL shard;
class-specific deletion would require a separate compaction and rewrite design.

The normative configuration becomes runtime-owned rather than proxy-owned:

```yaml
telemetry:
  downstream:
    retention_days: 14
    max_total_mb: 512
```

`0` means no age bound or no size bound respectively, matching the shared retention primitive. The owner is the global
runtime config (`~/.forge/config.yaml`), not any `proxy.yaml`. Proxy audit and provider-trace enablement remain per
proxy; only the lifecycle of their shared storage moves.

### Startup and preservation contract

- Proxy startup resolves the global policy once and calls `prune_downstream_records` once per process. The audit and
  provider-trace wrapper pruners are removed.
- Spend-cap state is bootstrapped before pruning, preserving the existing startup order. The current UTC calendar
  month's shards remain protected from both age and size pruning so restart cannot erase the evidence needed to rebuild
  daily/monthly cap state.
- Pruning remains best-effort for proxy availability, but a failure is logged as a warning naming the directory and
  policy. It must not be mislabeled as a successful enforcement.
- Request-diagnostic logs remain a separate per-proxy directory and policy; this decision does not merge them into the
  downstream plane.

### Existing configuration migration

`audit.retention_days`, `audit.max_total_mb`, `provider_trace.retention_days`, and `provider_trace.max_total_mb` become
deprecated compatibility inputs:

1. An explicitly configured global policy always wins. In the first release containing the migration, any legacy key is
   accepted, ignored, and reported with the exact replacement path.
2. Without an explicit global policy, Forge inspects installed proxy configs. If all explicitly configured legacy pairs
   agree, that pair is the effective compatibility value and a migration warning is emitted.
3. If legacy pairs conflict, Forge skips downstream pruning, starts the proxy with degraded retention status, and prints
   the conflicting proxy IDs plus a command/path for choosing the global policy. Selecting one silently could destroy
   data under a policy the user did not choose; disabling a destructive maintenance action is the safe fallback.
4. With no legacy values, the global defaults are `14` days and `512` MB.
5. A dedicated implementation migration updates user-owned proxy files only through an explicit CLI action; normal
   startup never rewrites them. In the following release, old keys become actionable unknown-key errors.

The compatibility resolver treats omitted values as omitted, not as an explicit default, so untouched generated proxy
files do not manufacture conflicts.

### Operator surfaces

Human and JSON status show `configured`, `effective`, and `source` (`global`, `legacy_consensus`, or `default`) for the
downstream policy, plus any deprecated keys/conflicts. Per-proxy views link to the global policy rather than claiming an
independent effective retention. `forge config` owns mutation of the new keys.

## Finding Disposition

| Finding | Disposition              | Downstream work                                                                                                                                              |
| ------- | ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| D015    | Implement with migration | Add the global policy/resolver and single pruner, deprecate four per-proxy keys, expose effective status, and preserve current-month/cap bootstrap behavior. |

Proposed implementation member: `unify_downstream_retention`. Coverage must include identical and conflicting legacy
configs, explicit-global precedence, omitted/default values, current-month age and size protection, cap bootstrap order,
one-call startup behavior, warning/failure output, and user-owned config migration.

## Acceptance Criteria

- One normative owner and effective-retention rule is documented for every downstream shard.
- Existing settings have an explicit compatibility/deprecation or migration disposition.
- Spend/cap bootstrap preservation and current-month behavior remain specified.
- D015 receives an implementation card with configuration and retention-boundary tests.
- No code change is bundled into this decision card.

## Closeout

Global ownership, migration precedence, conflict degradation, status reporting, and preservation rules are approved. The
[`unify_downstream_retention`](../unify_downstream_retention/card.md) shipped the synchronized design, appendix,
runtime-config, and operator documentation in PR #148. Verification: `make pre-commit-md` and `git diff --check`.
