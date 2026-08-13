# Harden proxy boundary failures checklist

Current focus: review and merge D054/D055 in draft PR #171 without activating another Wave 6 member.

## Activation and admission

- [x] Merge D030/O008/O015/O035 independently in PR #170 (`acae1b9e`).
- [x] Record its post-merge closeout on `main` at `22071fcd`.
- [x] Verify and admit D054/D055 as a new Wave 6 member without activating the six parked members.
- [x] Start `agent/harden-proxy-boundary-failures` from merged `main` at `22071fcd` and create this checklist.

## Fail-first reproduction

- [x] Prove template and instance loading accept malformed values for all four direct transported fields.
- [x] Prove failed process spawn leaks its stderr descriptor/path and raises raw `OSError` instead of `ProxyStartError`.
- [x] Retain valid-value controls for both config boundaries (`24 failed, 2 passed` on `22071fcd`).

## Implementation

- [x] Validate the four direct fields at shared schema boundaries with field-specific `ValueError` messages.
- [x] Close the stderr descriptor on every spawn outcome, remove the capture after a failed spawn, and preserve the
  cause behind `ProxyStartError`.
- [x] Keep existing valid values, absent-key defaults, and successful-spawn behavior unchanged.

## Verification and closeout

- [x] Run the focused config/orchestrator unit and retained regression slices (`253 passed`; new artifact `26 passed`).
- [x] Run the marked regression (`799 passed`) and full unit (`9001 passed, 1 skipped, 122 deselected`) gates.
- [x] Run targeted Docker proxy integration coverage required for proxy-runtime changes (`2 passed`).
- [x] Run full pre-commit, the explicit new-file hook, and board link/lane/size/diff checks (291 files, 718 relative
  links, zero missing targets, 6 `done` / 1 `doing` / 6 `todo`, and document sizes below their caps).
- [x] Open independent draft PR #171 without activating another Wave 6 member.
