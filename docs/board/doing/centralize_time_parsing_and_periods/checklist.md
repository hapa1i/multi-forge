# Centralize timestamp, period, and relative-time primitives checklist

Current focus: verification complete on `refactor/centralize-time-parsing-and-periods`; keep order 4 parked until this
member is reviewed, merged, and closed independently.

## Phase 1 -- Characterize and activate

- [x] Close O044 on `main` at `ef9c27c1`, branch from that exact commit, and activate only order-3 O060/O061/O094.
- [x] Recheck the period sites: trace, proxy audit, and telemetry costs duplicate start/end calculations; activity has a
  fourth lower-bound-only copy. Preserve each caller's existing `all` sentinel.
- [x] Recheck all 13 direct `datetime.fromisoformat` sites outside `core.state.timestamps`; retain explicit strict,
  assume-UTC, and invalid-fallback contracts at their call boundaries.
- [x] Recheck relative-time presentation: sessions use full words and `unknown`, while proxy status uses compact units,
  the original value on invalid input, and UTC for naive values.
- [x] Run the unchanged timestamp, trace, audit, cost, activity, session-list, proxy-list, telemetry-reader, throttle,
  and status-line characterization slice: 679 passed.

## Phase 2 -- Shared primitives

- [x] Extend `core.state.timestamps` with one UTC-normalizing ISO parser, an explicitly tolerant wrapper, and tests for
  `Z`, non-UTC offsets, naive values, invalid inputs, and typed non-string data.
- [x] Add one local-calendar period primitive with DST-aware test fixtures; keep `all` handling in the four callers.
- [x] Add named compact and full-word relative-time styles with explicit invalid and naive policies; retain both CLI
  wrappers and their existing output contracts.
- [x] Route every production `datetime.fromisoformat` call through the shared parser or tolerant wrapper without
  changing retention windows, durable formats, or JSON fields.
- [x] Update the normative design timestamp boundary and verify no end-user command documentation changed.

## Phase 3 -- Verify and close

- [x] Run focused timestamp, period, trace, audit, cost, activity, session-list, proxy-list, telemetry-reader, throttle,
  and status-line tests: 721 passed; the targeted provider-trace and cost-visibility integrations pass 7 tests.
- [x] Run the required full unit and regression suites plus `make pre-commit`: unit passes 9,064 with one skip and 122
  deselected; regression passes 898; full pre-commit passes after import and Markdown normalization.
- [x] Resolve board links/fragments and run `git diff --check`: all 854 local path links across 331 board Markdown files
  and all five fragments from the eight changed board documents resolve. The Wave 7 graph is two `done/`, one `doing/`,
  and 31 `todo/` members with valid epic backlinks.
- [ ] After review and merge, record the shipped outcome, move this member to `done/`, and leave order 4 parked until
  the closeout lands.
