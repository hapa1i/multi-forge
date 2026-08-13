# Wave 7 refactor and deletion checklist

Current focus: execute order 1, O043, from preparation commit `095d8eeb`. Keep orders 2--34 in `todo/` until O043 ships
and the epic selects the next member.

- [x] Commit the bounded admission and 34-member sequence on `main` (`095d8eeb`).
- [x] Create `refactor/decouple-lane-runtime-vocabulary` from that commit.
- [x] Move this epic and only `decouple_lane_runtime_vocabulary` to `doing/`; repair every inbound board link.
- [x] Retain O043 runtime classification and registry-vocabulary parity while removing the heavyweight import edge.
- [x] Complete O043's focused, unit, regression, pre-commit, and board-integrity gates.
- [ ] Close O043 independently before selecting or activating order 2.

Orders 2--34 are intentionally parked. This checklist does not authorize parallel implementation or any separately gated
Wave 6 finding.
