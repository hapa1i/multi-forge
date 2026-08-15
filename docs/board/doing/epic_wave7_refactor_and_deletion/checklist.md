# Wave 7 refactor and deletion checklist

Current focus: orders 1--10 and the bounded
[`correct_post_merge_review_findings`](../../done/correct_post_merge_review_findings/card.md) member are closed through
PR #188. The bounded [`correct_empty_tz_period_bounds`](../../done/correct_empty_tz_period_bounds/card.md) correction
shipped in PR #189; keep orders 11--35 in `todo/`.

- [x] Commit the initial bounded admission and 34-member sequence on `main` (`095d8eeb`).
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
- [x] Create `refactor/centralize-install-path-authority` from `56d32945`; activate only O065/O069 and retain installer
  transaction order, fail-closed boundaries, and 29 parked members.
- [x] Move pure path/ownership policy below installer and runtime removal; remove only the duplicate CLI copies of the
  core-path tests.
- [x] Complete order 5's focused, integration, package, full, pre-commit, and board-integrity gates.
- [x] Close order 5 independently before selecting or activating order 6.
- [x] Create `refactor/centralize-cli-metric-formatting` from `62055bab`; activate only O064 and retain all shipped
  human formatting plus 28 parked members.
- [x] Share only numeric presentation primitives with explicit policies; preserve every human string and JSON number.
- [x] Complete order 6's focused, integration, full, pre-commit, and board-integrity gates.
- [x] Close order 6 independently in PR #183 (`cd3e50e8`) before selecting or activating order 7.
- [x] Admit the mechanically verified O098/session-summary/cap-guard subset as a bounded, non-overlapping order-7
  sequencing exception; retain O084, converter/Gemini candidates, release-gated deletions, and the unnamed tail outside.
- [x] Create `refactor/remove-verified-internal-residue` from `4f167379`; activate only order 7 and retain command,
  output, state-reader, and compatibility behavior plus 28 parked members.
- [x] Ship order 7 independently in PR #184 (`95488c10`) and close its member before selecting order 8.
- [x] Close the corrective member after PR #185 (`8ccbf387`) before selecting or activating order 8.
- [x] Create `refactor/remove-stale-dependencies` from `5bd69ef5`, activate only O071, and retain runtime dependency
  ownership plus 27 parked members.
- [x] Remove only the verified redundant `python-dotenv` dev edge, retain Starlette's live `httpx2` dependency, complete
  package/full/board verification, and ship order 8 in PR #186 (`19dcf9cb`) before selecting order 9.
- [x] Create `refactor/share-proxy-transport-test-fakes` from `549fb0e3`, activate only O099's fake-family subset, and
  retain production transport behavior plus 26 parked members.
- [x] Replace the two mutable fake families with one instance-owned test scaffold, preserve transport-specific defaults,
  and complete focused/full/board verification before selecting order 10.
- [x] Ship order 9 independently in PR #187 (`be321ad2`) and close its member before activating order 10.
- [x] Create `refactor/lock-walkthrough-state-parity` from `3260a6fa`, activate only O073, and retain self-contained
  installed copies plus 25 parked members.
- [x] Guard every non-identity source line, run the full behavioral matrix against both copies, and complete
  runtime-skill/package verification before selecting order 11.
- [x] Ship order 10 independently in PR #188 (`b8e4b32c`) and close its member without activating order 11.
- [x] Branch from the order-10 closeout (`459887fa`) and activate only `correct_empty_tz_period_bounds`; do not change
  Wave 7 finding/member counts.
- [x] Close the empty-`TZ` correction in PR #189 (`f0afc0c4`) with focused, full, telemetry-integration, pre-commit, and
  board verification before selecting order 11.

Orders 11--35 are intentionally parked. This checklist does not authorize parallel implementation or any other
separately gated Wave 6 finding.
