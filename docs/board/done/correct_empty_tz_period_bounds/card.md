# Honor explicitly empty process timezone

**Epic**: [`epic_repo_maintenance_round`](../epic_repo_maintenance_round/card.md).

**Lane**: `done/` -- shipped in PR #189 (`f0afc0c4`) from `459887fa`.

**Related shipped members**:

- [`centralize_time_parsing_and_periods`](../../done/centralize_time_parsing_and_periods/card.md) (O060/O061/O094 period
  boundary ownership)
- [`correct_post_merge_review_findings`](../../done/correct_post_merge_review_findings/card.md) (valid non-empty `TZ`
  forms)

This is a post-merge edge case in the shipped timezone work, not a reopened or renumbered review-ledger finding. The
Wave 7 finding and member counts remain unchanged.

## Goal

Honor an explicitly empty process `TZ` as UTC while preserving the distinct policies for an unset `TZ`, valid non-empty
forms, and invalid non-empty values.

## Evidence and authority

- Before the fix, on a Berlin host, `TZ=''` made Python's process timezone UTC while `_local_timezone()` skipped the
  empty value and read `/etc/localtime`; a `today` boundary consequently started at `22:00Z` on the previous date
  instead of `00:00Z`.
- `dateutil.tz.gettz("")` also resolves the host local timezone, so merely replacing the truthiness guard with an
  `is not None` check would retain the defect.
- With `TZ` absent, both Python and Forge use the host local timezone. Invalid non-empty values deliberately retain the
  shipped `/etc/localtime` fallback.
- Before period parsing was centralized, `datetime.now().astimezone()` followed the process's empty-`TZ` UTC behavior;
  the divergence originated in the centralization and was not closed by the later valid-form correction.

Authority comes from the platform `tzset(3)` contract, the local-period behavior in
[`docs/design.md`](../../../design.md), and the shipped
[`centralize_time_parsing_and_periods`](../../done/centralize_time_parsing_and_periods/card.md) compatibility boundary.

## Acceptance criteria

- `_local_timezone()` returns `datetime.UTC` for an explicitly empty `TZ` before consulting `dateutil` or
  `/etc/localtime`.
- An absent `TZ` continues to use `/etc/localtime`; IANA, absolute/colon TZif, and POSIX-rule forms retain their shipped
  behavior; invalid non-empty values continue to fall back to `/etc/localtime`.
- A host-independent regression proves both UTC timezone identity and exact empty-`TZ` local-period bounds.
- Activity, audit, cost, and trace period consumers continue to share `local_period_bounds()` without caller-specific
  timezone handling.

## Scope boundaries

- Do not call process-global `tzset`, change stored timestamp formats, alter period ranges, or reinterpret invalid
  non-empty values.
- Do not reopen the completed timezone or post-merge correction cards.
- Keep Wave 7 orders 11--35 parked until this bounded correction merges and closes.

## Implementation outcome

`_local_timezone()` now handles the explicit empty string before dependency or filesystem resolution and returns
`datetime.UTC`. Unset values still read `/etc/localtime`; valid non-empty forms still resolve through `dateutil`; and
invalid non-empty forms retain the host-local fallback. Deterministic tests pin the empty-value identity and exact
period bounds plus the unchanged fallback states.

Verification passes 114 focused tests, 9,214 unit tests with one skip and 122 deselected, 907 regressions, six targeted
Docker telemetry integrations, full pre-commit, and board-integrity checks. A broader extra invocation also reproduced
the unrelated cancelled-stream provider-trace failure twice on an untouched lifecycle seam. PR #189 merged as `f0afc0c4`
with all five GitHub checks passing. No Forge workflow command was used.
