# Honor explicitly empty process timezone checklist

Current focus: correct the verified empty-`TZ` regression from `459887fa` without activating Wave 7 order 11.

## Evidence and implementation

- [x] Close Wave 7 order 10 on `main`, push `459887fa`, and branch from that exact closeout.
- [x] Reproduce the empty-`TZ` boundary shift independently on a non-UTC host.
- [x] Verify that an absent `TZ` and invalid non-empty values intentionally retain the host-local fallback.
- [x] Verify that `dateutil.tz.gettz("")` cannot express the required empty-value UTC policy.
- [x] Return `datetime.UTC` for an explicitly empty `TZ` before dependency or filesystem resolution.
- [x] Add deterministic regression coverage for empty, absent, and invalid process-timezone states.
- [x] Confirm activity, audit, cost, and trace consumers retain the shared period API.

## Acceptance tests

| Boundary          | Fixture                                  | Assertion                                                     | Test file                                                 |
| ----------------- | ---------------------------------------- | ------------------------------------------------------------- | --------------------------------------------------------- |
| Empty environment | `TZ=''` on any host                      | local timezone is UTC and exact `today` bounds are UTC        | `tests/regression/test_bug_timezone_environment_forms.py` |
| Fallback policy   | `TZ` absent or invalid non-empty         | `/etc/localtime` remains authoritative                        | `tests/src/core/state/test_timestamps.py`                 |
| Consumer routing  | activity, audit, cost, and trace periods | all continue to call the centralized period-boundary function | focused CLI suites                                        |

## Verification and closeout

- [x] Run focused timestamp, regression, and four-consumer CLI coverage (`114 passed`).
- [x] Run `make test-unit` (`9,214 passed, 1 skipped, 122 deselected`) and `make test-regression` (`907 passed`).
- [x] Run the targeted Docker telemetry integration coverage required for period-filter changes (`6 passed`). A broader
  seven-case invocation exposed the unrelated cancelled-stream trace test failing twice; its provider-lifecycle seam is
  untouched by this branch and the other six cases pass.
- [x] Run full `make pre-commit`, diff checks, and board link/lane verification (343 Markdown files, 880 local links,
  none missing; three active cards; Wave 7 remains 10 done / 0 doing / 25 todo).
- [ ] Open one draft PR for the bounded correction; after merge, close this card before selecting Wave 7 order 11.
