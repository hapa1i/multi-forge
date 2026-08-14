# Wave 7 refactor and deletion checklist

Current focus: order 4 shipped independently in PR #181 (`a8cff31f`). Keep orders 5--34 in `todo/` until this closeout
is committed; order 5, O065/O069, is the next eligible member.

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
- [x] Close order 3 independently before selecting or activating order 4.
- [x] Create `refactor/unify-git-root-discovery` from `9817cad3`; activate only O066/O092 and retain the optional/strict
  contracts, distinct Git-subprocess ownership, and 30 parked members.
- [x] Share only parent traversal, remove the definition-only exception, and retain exact strict-wrapper behavior.
- [x] Complete order 4's focused, integration, full, pre-commit, and board-integrity gates.
- [x] Close order 4 independently before selecting or activating order 5.

Orders 5--34 are intentionally parked. This checklist does not authorize parallel implementation or any separately gated
Wave 6 finding.
