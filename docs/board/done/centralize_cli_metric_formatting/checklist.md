# Centralize CLI metric formatting policies checklist

Current focus: complete -- O064 shipped independently in PR #183 and its Wave 7 member is closed.

## Phase 1 -- Characterize and activate

- [x] Close order 5 on `main` at `62055bab`, branch from that exact commit, and activate only order-6 O064.
- [x] Recheck token drift: proxy metrics, cost tables, and status-line segments use uppercase suffixes with tenths;
  activity uses rounded lowercase thousands and uppercase tenths for millions.
- [x] Recheck currency drift: cost detail adapts from two to six decimals, activity detail retains four sub-cent
  decimals while session summaries use fixed cents, status metrics use whole or fractional cents, and spend caps retain
  four decimals below one cent.
- [x] Retain request labels, status-line layout, approximation markers, JSON numeric types/values, and O084 outside this
  member.
- [x] Run the unchanged proxy, cost, activity/usage-summary, and status-line characterization: 600 passed.

## Phase 2 -- Share explicit presentation policies

- [x] Add UI-free numeric primitives whose token and USD policies are mandatory at every call site.
- [x] Route proxy metrics, cost reporting, activity summary, and status-line rendering through the shared authority;
  remove their ad hoc token/currency helpers.
- [x] Add policy-boundary and surface golden tests for every existing suffix, rounding, precision, and sub-cent rule;
  keep JSON outputs byte-compatible.
- [x] Update design ownership without changing CLI documentation or end-user behavior.

## Phase 3 -- Verify and close

- [x] Run the focused proxy, cost, activity/usage-summary, and status-line suites (648 passed) and targeted Docker
  status-line integration (17 passed).
- [x] Run `make test-unit` (9,109 passed, one skipped, 122 deselected), `make test-regression` (898 passed), and
  `make pre-commit`.
- [x] Resolve all 855 local paths across 334 board Markdown files and all three fragments from the eight changed board
  documents; verify the 5-done/1-doing/28-parked Wave 7 graph with valid backlinks; run `git diff --check`.
- [x] After review and merge, record PR #183 (`cd3e50e8`), move this member to `done/`, and admit the independently
  verified residue member without activating it. The Wave 7 graph is six done, zero member doing, and 29 todo cards.
