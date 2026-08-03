# Decide retention ownership for unified downstream telemetry

**Epic**: [`epic_repo_maintenance_round`](../epic_repo_maintenance_round/card.md) (DG3; D015).

**Lane**: `todo/` -- accepted decision work, parked until an execution branch becomes active.

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
- Audit configuration: `docs/design_appendix.md` §A.11.
- Unified provider lifecycle retention: `docs/design_appendix.md` §A.14.
- Startup pruners: `src/forge/proxy/server.py:228,245` at the review baseline.

## Acceptance Criteria

- One normative owner and effective-retention rule is documented for every downstream shard.
- Existing settings have an explicit compatibility/deprecation or migration disposition.
- Spend/cap bootstrap preservation and current-month behavior remain specified.
- D015 receives an implementation card with configuration and retention-boundary tests.
- No code change is bundled into this decision card.
