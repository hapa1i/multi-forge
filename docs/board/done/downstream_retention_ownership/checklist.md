# Downstream retention ownership decision checklist

- [x] Confirm that both settings prune the same physical shard directory.
- [x] Choose the storage owner, configuration authority, and startup pruner.
- [x] Define compatibility for the two existing per-proxy setting groups.
- [x] Preserve current-month and spend-cap bootstrap requirements.
- [x] Specify CLI/status reporting and D015 implementation coverage.
- [x] Assign normative telemetry-design synchronization to `unify_downstream_retention` when behavior ships.
- [x] Create the D015 implementation member with migration and retention-boundary coverage.
- [x] Obtain human approval (2026-08-04).
