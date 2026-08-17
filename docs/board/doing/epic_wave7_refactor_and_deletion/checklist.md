# Wave 7 refactor and deletion checklist

Current focus: order 21 is active on `refactor/retire-test-only-settings-helpers` from `5664258b`; keep orders 22--35 in
`todo/`.

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
- [x] Close PR #189 on pushed `main` at `cc03a4e6`, create `refactor/remove-obsolete-proxy-abstractions`, and activate
  only order 11.
- [x] Reverify O047/O048 and the admitted O092 factory subset against current source, resources, entry points,
  extensions, docs, tests, and concrete implementations.
- [x] Delete only the unreachable proxy surfaces after moving useful failure-metrics coverage to a reachable path;
  complete focused/full/integration/board verification while keeping order 12 parked.
- [x] Ship order 11 independently in PR #190 (`ca2f289b`) and close its member before activating order 12.
- [x] Close order 11 on pushed `main` at `c99be7a3`, create `refactor/migrate-inert-config-fields`, and activate only
  order 12.
- [x] Reverify and ship O049's first-release config warning transition with clean-wheel proof in PR #191 (`e0be9a60`)
  before selecting order 13.
- [x] Close order 12 on pushed `main` at `9a334b18`, create `refactor/migrate-memory-intent-generated-file`, and
  activate only order 13.
- [x] Migrate and delete only `MemoryIntent.generated_file` with strict-read and no-rewrite coverage before selecting
  order 14.
- [x] Ship order 13 independently in PR #192 (`b7a8ad9e`) and close its member without activating order 14.
- [x] Close order 13 on pushed `main` at `74b364d2`, create `refactor/replace-unsafe-index-test-fixtures`, and activate
  only order 14 after reverifying 180 executable calls across 48 test files.
- [x] Replace ordinary unsafe index setup with invariant-preserving shared builders while retaining explicit invalid and
  race fixtures; complete focused/full/integration/board verification before selecting order 15.
- [x] Ship order 14 independently in PR #193 (`56dfc27b`) and close its member without activating order 15.
- [x] Close order 14 on pushed `main` at `0e8e1cbb`, create `refactor/retire-unsafe-index-mutators`, and activate only
  order 15 after reverifying the residual direct contracts and stale references.
- [x] Delete the three unsafe public index mutators, their direct-only tests, and live stale references while preserving
  the transaction implementation and all invariant coverage.
- [x] Ship order 15 independently in PR #194 (`ae7519fc`) and close its member before activating order 16.
- [x] Close order 15 on pushed `main` at `358b39d6`, create `refactor/replace-legacy-tier-inference`, and activate only
  order 16 after reverifying its factory, routing, cache, and retry seams.
- [x] Remove the nonexistent tier environment shim while preserving explicit request-tier and named-default routing;
  complete focused/full/integration/board verification before selecting order 17.
- [x] Ship order 16 independently in PR #195 (`aca65c7f`) and close its member before activating order 17.
- [x] Close order 16 on pushed `main` at `2ec0f92d`, create `refactor/remove-dead-session-context-retry`, and activate
  only order 17 after reverifying its name, UUID, manifest-fallback, and error-classification paths.
- [x] Remove only the duplicate unscoped name retry while preserving state errors, ambiguity, and fallback ordering.
- [x] Complete order 17's focused, full, regression, Docker session, pre-commit, design-size, and board-integrity gates.
- [x] Ship order 17 independently in PR #196 (`bc4f3a0c`) and close its member before activating order 18.
- [x] Close order 17 on pushed `main` at `f2fcc688`, create `refactor/remove-dead-session-helpers`, and activate only
  order 18 after reverifying its collector parameter, no-op helper, and relaunch-name argument.
- [x] Remove only the three verified session residues while preserving live shadow discovery, relaunch lineage, and
  project-scoped generated-name collision handling.
- [x] Complete order 18's focused, full, regression, Docker session, pre-commit, design-size, and board-integrity gates.
- [x] Ship order 18 independently in PR #197 (`86a83a1d`) and close its member before activating order 19.
- [x] Close order 18 on pushed `main` at `2745e5ed`, create `refactor/deprecate-supervisor-verdict-wrapper`, and
  activate only order 19 after correcting and reverifying its compatibility contract.
- [x] Retain O092's supervisor verdict wrapper for its warning release, emit one caller-attributed deprecation, and move
  internal consumers to the status-bearing parser while keeping orders 20--35 parked.
- [x] Complete order 19's focused, semantic-policy, full-unit, regression, pre-commit, design-size, and board-integrity
  gates without a Forge workflow.
- [x] Ship order 19 independently in PR #198 (`7fd701b5`) and close its member without activating order 20.
- [x] Close order 19 on pushed `main` at `93957659`, create `refactor/wire-transcript-reindex-guard`, and activate only
  order 20 after correcting its metadata-fingerprint contract.
- [x] Wire O092's existing `mtime`/size guard at the startup-queue index boundary, fail open to full indexing when its
  bookkeeping cannot be read, and make explicit full rebuild replace that state consistently with the search stores.
- [x] Complete order 20's focused, full, regression, Docker Stop/artifact, pre-commit, design-size, and board-integrity
  gates without a Forge workflow.
- [x] Ship order 20 independently in PR #199 (`7b3ac2df`) and close its member before activating order 21.
- [x] Close order 20 on pushed `main` at `5664258b`, create `refactor/retire-test-only-settings-helpers`, and activate
  only order 21 after reverifying its three internal settings surfaces.
- [x] Delete only the test-only/zero-caller settings helpers while preserving reachable backup, rollback, and conflict
  coverage.
- [x] Complete order 21's focused, full, regression, Docker installer, clean-wheel, pre-commit, design-size, and
  board-integrity gates without a Forge workflow.
- [ ] Ship order 21 independently and close its member before activating order 22.

Orders 22--35 are intentionally parked. This checklist does not authorize parallel implementation or any other
separately gated Wave 6 finding.
