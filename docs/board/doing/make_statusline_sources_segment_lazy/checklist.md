# Make status-line sources segment-lazy checklist

Current focus: publish the independently reviewed registry-owned source plan.

## Activation and reproduction

- [x] Start `fix/make-statusline-sources-segment-lazy` from merged PR #153 at `8f030ef4`.
- [x] Close O004, move D018 from `todo/` to `doing/`, and advance the final bounded Wave 5 cursor.
- [x] Add a marked D018 regression for a `path`/`branch`-only status line.
- [x] Confirm the retained regression fails on `8f030ef4` because both proxy and session discovery run before segment
  resolution.

## Source dependency contract

- [x] Give every proxy/session-consuming segment one registry-owned dependency declaration.
- [x] Resolve the configured/default segment plan before acquiring proxy or session facts.
- [x] Skip both probes for a zero-source layout and acquire each requested source at most once per poll.
- [x] Preserve the default layout, source fail-open behavior, and all formatting/order/palette/glyph semantics.

## Acceptance tests

| Test                     | Fixture                                            | Assertion                                                     |
| ------------------------ | -------------------------------------------------- | ------------------------------------------------------------- |
| Retained D018 regression | configured `path`, `branch`                        | neither source probe runs and output remains compatible       |
| Registry declaration     | every registered segment                           | declared source union is canonical and exhaustively tested    |
| Proxy-only plan          | one proxy-dependent segment                        | proxy discovery runs once; session discovery does not run     |
| Session-only plan        | one session-dependent segment                      | session discovery runs once; proxy discovery does not run     |
| Mixed/default plan       | both source classes; empty configured segment list | each required probe runs once and default output is unchanged |
| Source failure           | unavailable/malformed proxy or session state       | existing fail-open result remains local and byte-compatible   |
| Hot-path instrumentation | repeated zero-source renders                       | proxy/session probe counters remain zero                      |
| CLI integration          | installed status-line command with isolated homes  | configured layout crosses the real CLI boundary               |

## Verification and closeout

- [x] Run focused status-line, runtime-config, and retained-regression tests: 494 passed.
- [x] Run targeted session/proxy integration through `./scripts/test-integration.sh`: 14 passed.
- [x] Synchronize normative design, operator guidance, bundled QA, review ledger, and change log.
- [x] Run the full unit suite (8,929 passed, one skipped, 122 deselected) and 696 marked regressions; build the
  wheel/sdist, verify the shipped registry and bundled QA resources, and pass `make pre-commit`.
- [x] Resolve all 168 local paths/fragments across 14 changed Markdown files and stale-lane references; confirm the QA
  index's 625 checks, measure the change log at 21,412 tokens / 1,449 physical lines, and pass diff checks.
- [x] Receive independent review with no findings before PR publication.
- [ ] Merge, then close the seven-member child epic before admitting later Wave 5 MEDIUM rows.
