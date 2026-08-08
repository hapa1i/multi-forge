# Unify downstream telemetry retention ownership checklist

Completed in PR #148 (`8b997e6a`).

## Activation and reproduction

- [x] Start `fix/unify-downstream-retention` from merged `main` at `92b981a5`.
- [x] Move the Wave 5 epic and D015 from `todo/` to `doing/`, create checklists, and repoint inbound links.
- [x] Add a marked D015 regression using one shared shard and conflicting audit/provider-trace retention policies.
- [x] Confirm the retained regression reaches startup on `92b981a5`; its assertion records `90d` and `14d` calls plus
  `shard_exists=False` after the stricter second pass deletes the shared shard.

## Global policy and compatibility

- [x] Add runtime-owned `telemetry.downstream.retention_days` and `max_total_mb` with defaults `14` and `512`; preserve
  `0` as the unbounded value for either dimension.
- [x] Resolve explicit global config before legacy values; otherwise accept identical explicitly configured legacy
  pairs, fail closed on conflicts, and use defaults when no legacy value exists.
- [x] Treat omitted legacy fields as omitted rather than manufacturing default conflicts.
- [x] Report deprecated legacy keys and their exact global replacements; normal startup must not rewrite proxy files.
- [x] Warn when `forge proxy set` writes a deprecated retention key and point to its global replacement and migration.
- [x] Provide an explicit user-owned migration path and retain the first-release compatibility window.
- [x] Record the multi-sidecar legacy-consensus limitation; require an explicit global policy for that compatibility
  window instead of silently claiming host-wide consensus from one mounted proxy directory.

## Startup pruning and preservation

- [x] Resolve the effective policy once and call `prune_downstream_records()` once per proxy process.
- [x] Bootstrap spend-cap state before pruning and protect the current UTC calendar month's shards from both age and
  size pruning.
- [x] Keep request-diagnostic retention separate and preserve proxy availability when pruning fails, with an accurate
  warning naming the directory and effective policy.

## Operator surfaces and documentation

- [x] Show configured, effective, and source (`global`, `legacy_consensus`, or `default`) in human and JSON status, plus
  deprecations or conflicting proxy IDs.
- [x] Make per-proxy views point to the global owner instead of claiming an independent effective downstream policy.
- [x] Synchronize normative design, runtime configuration, CLI reference, and operator guidance only with shipped
  behavior.
- [x] Document the root runtime-truth `running`/`degraded` status values and add QA coverage for migration and degraded
  retention status.

## Acceptance tests

| Test                       | Fixture                                                   | Assertion                                                                       |
| -------------------------- | --------------------------------------------------------- | ------------------------------------------------------------------------------- |
| Dual-pruner regression     | one shared shard and disagreeing legacy policies          | one resolved policy controls at most one prune call                             |
| Explicit global precedence | global policy plus disagreeing legacy keys                | global policy wins and all legacy keys are reported deprecated                  |
| Legacy consensus           | multiple proxies with the same explicitly configured pair | consensus is effective and source is `legacy_consensus`                         |
| Legacy conflict            | proxies with distinct explicit pairs                      | pruning is skipped, startup is degraded, and proxy IDs are reported             |
| Defaults and omissions     | no explicit global or legacy values                       | `14` days / `512` MB with source `default`; omissions do not conflict           |
| Cap preservation           | current-month shards plus spend-cap bootstrap             | bootstrap precedes pruning and current-month shards survive age/size passes     |
| Pruner failure             | injected downstream prune error                           | startup remains available and warning does not claim enforcement                |
| Migration                  | explicit migration over user-owned proxy files            | legacy keys move only on request and global configuration is written coherently |

## Verification and closeout

- [x] Run focused configuration, telemetry, proxy startup, status, and migration tests: 1,265 passed; rerun the
  independent-review feedback slice after its changes: 192 passed.
- [x] Run the full unit suite: 8,884 passed, 1 skipped, and 122 integration tests deselected.
- [x] Run the marked regression suite (684 passed) and targeted proxy Docker integration (1 passed).
- [x] Run final `make pre-commit`.
- [x] Resolve Markdown paths/fragments in all 23 changed docs; run stale-lane and `git diff --check` scans.
- [x] Obtain independent review and resolve its required fail-on-base evidence correction and bounded follow-ups.
- [x] Merge, then synchronize the review ledger, change log, card, and epic cursors before activating O002 (PR #148,
  `8b997e6a`).
