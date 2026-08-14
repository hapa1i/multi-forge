# Wave 7 refactor and deletion checklist

Current focus: execute order 3, O060/O061/O094, from O044 closeout commit `ef9c27c1`. Keep orders 4--34 in `todo/` until
order 3 ships and the epic selects the next member.

- [x] Commit the bounded admission and 34-member sequence on `main` (`095d8eeb`).
- [x] Create `refactor/decouple-lane-runtime-vocabulary` from that commit.
- [x] Move this epic and only `decouple_lane_runtime_vocabulary` to `doing/`; repair every inbound board link.
- [x] Retain O043 runtime classification and registry-vocabulary parity while removing the heavyweight import edge.
- [x] Complete O043's focused, unit, regression, pre-commit, and board-integrity gates.
- [x] Close O043 independently before selecting or activating order 2.
- [x] Create `refactor/share-policy-activation-rules` from `2a08f009`; activate only O044 and retain the other state
  owners and 32 parked members.
- [x] Preserve terminal intent writes and `%policy` override writes while sharing only UI-free activation rules.
- [x] Complete O044's focused, integration, full, pre-commit, and board-integrity gates.
- [x] Close O044 independently before selecting or activating order 3.
- [x] Create `refactor/centralize-time-parsing-and-periods` from `ef9c27c1`; activate only O060/O061/O094 and retain the
  explicit timestamp compatibility policies and 31 parked members.
- [x] Complete order 3's focused, full, pre-commit, and board-integrity gates.
- [ ] Close order 3 independently before selecting or activating order 4.

Orders 4--34 are intentionally parked. This checklist does not authorize parallel implementation or any separately gated
Wave 6 finding.
