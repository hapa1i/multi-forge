# Wave 7 refactor and deletion checklist

Current focus: O043 shipped independently in PR #178 (`30f930b0`). Keep orders 2--34 in `todo/` until this closeout is
committed; order 2, O044, is the next eligible member.

- [x] Commit the bounded admission and 34-member sequence on `main` (`095d8eeb`).
- [x] Create `refactor/decouple-lane-runtime-vocabulary` from that commit.
- [x] Move this epic and only `decouple_lane_runtime_vocabulary` to `doing/`; repair every inbound board link.
- [x] Retain O043 runtime classification and registry-vocabulary parity while removing the heavyweight import edge.
- [x] Complete O043's focused, unit, regression, pre-commit, and board-integrity gates.
- [x] Close O043 independently before selecting or activating order 2.

Orders 2--34 are intentionally parked. This checklist does not authorize parallel implementation or any separately gated
Wave 6 finding.
