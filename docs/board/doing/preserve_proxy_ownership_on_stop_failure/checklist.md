# Preserve proxy ownership on stop failure checklist

Current focus: independent review is complete; prepare the verified O002 implementation for PR and merge.

## Activation and reproduction

- [x] Start `fix/preserve-proxy-ownership-on-stop-failure` from merged PR #148 at `8b997e6a`.
- [x] Close D015, move O002 from `todo/` to `doing/`, and advance the Wave 5 cursors without activating D016.
- [x] Add a marked O002 regression that injects a required stop failure into both `proxy stop` and `proxy delete`.
- [x] Confirm the retained regression fails on `8b997e6a` because stop exits zero and delete removes ownership, reports
  success, and leaves the simulated process alive.

## Stop outcome contract

- [x] Make an attempted/refused/failed stop a diagnostic failure with a non-zero exit while retaining registry state.
- [x] Preserve successful outcomes for a dead or concurrently vanished managed PID, default adopted detach, and a
  verified adopted kill.
- [x] Keep the shared-port refusal fail-closed unless `--force` is explicit; forced success still updates sibling state.

## Delete ownership transaction

- [x] Determine last/live shared ownership under the registry lock before deciding whether a stop is required.
- [x] For a last reference, complete the required stop before removing the registry row or proxy directory.
- [x] On permission failure, refusal, or identity mismatch, preserve registry/config ownership and omit `Deleted`.
- [x] Preserve explicit `--no-kill`, default adopted detach, already-stopped, and shared-reference deletion semantics.
- [x] Continue independent multi-delete targets, count stop failures, summarize accurately, and exit non-zero if any
  fail.

## Acceptance tests

| Test                       | Fixture                                      | Assertion                                                                    |
| -------------------------- | -------------------------------------------- | ---------------------------------------------------------------------------- |
| Stop failure               | managed live PID; injected permission error  | non-zero exit; registry row and config remain                                |
| Last-reference delete      | managed live PID; injected stop failure      | process survives; registry/config remain; no success claim                   |
| Adopted identity refusal   | `--kill-adopted`; mismatched health identity | non-zero exit; process and ownership remain                                  |
| Intentional survivors      | adopted default, `--no-kill`, shared alias   | deletion succeeds without terminating the process                            |
| Already stopped            | dead PID or no discovered adopted PID        | stale ownership can be deleted successfully                                  |
| Multi-delete aggregation   | one stop failure and one healthy target      | healthy target is deleted; failed target remains; summary names both; exit 1 |
| Process-backed integration | live managed process                         | successful stop/delete removes the intended process and ownership only       |

## Verification and closeout

- [x] Run focused proxy CLI and output-stream tests: 168 passed.
- [x] Run the full unit suite: 8,890 passed, 1 skipped, and 122 integration tests deselected.
- [x] Run the retained O002 regression and the full marked regression suite: 685 passed.
- [x] Run the targeted process-backed proxy integration slice: all 6 proxy-delete cases passed.
- [x] Synchronize lifecycle design/operator/QA docs only where observable behavior changes; the QA index now contains
  614 assertions.
- [x] Build the sdist and wheel and verify the three changed QA resources are packaged.
- [x] Run final `make pre-commit`; resolve all 199 local links/fragments across the 16 changed Markdown files; confirm
  no stale D015/O002 lane references remain; and pass the diff check.
- [x] Resolve independent review: pin the identity-refusal diagnostic to stderr and record the separate pre-lock
  `proxy stop` shared-ownership race without absorbing it into O002.
- [ ] Merge before activating D016.
