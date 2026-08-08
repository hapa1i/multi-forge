# Roll back Codex install transactions

**Epic**: [`epic_installer_transaction_safety`](../epic_installer_transaction_safety/card.md).

**Findings**: D013 and D014 (HIGH) in [`review_combined.md`](../../review_combined.md#design-conformance-findings).

**Lane**: `doing/` -- implementation, verification, and independent review are complete on
`fix/rollback-codex-install-transaction`; merge remains.

## Goal

Restore every surface changed by extension enable or sync when Codex registration fails after mutation or the final
installed-manifest commit fails.

## Design Authority

- [`docs/design_appendix.md` §C.4](../../../design_appendix.md#c4-durable-installproject-files): filesystem mutation
  precedes the atomic tracking commit, and a later failure must restore or report an honest state.
- [`docs/design_appendix.md` §C.6](../../../design_appendix.md#c6-codex-hook-registration-hooks-codex-owned-half): Forge
  owns only its marker-delimited block and must preserve outside TOML and file mode.
- [`coding_standards.md` §5](../../../developer/coding_standards.md#internal-boundaries-module-to-module): unexpected
  internal failures are surfaced through the typed boundary rather than leaking raw implementation exceptions.

## Evidence

Rechecked on `2461e3fa` with real managed-block writes. Injecting `OSError` into the final tracking commit removed the
new extension file but left the Codex block with no installation row. Injecting `OSError` into registration read-back
leaked the raw exception and left both the extension file and block without tracking.

The retained marked regression failed on the execution base `afde43bf` at both fault points for missing and pre-existing
user configs: read-back leaked the raw `OSError`, while tracking failure left the managed block behind.

## Expected Behavior

- Capture the pre-mutation Codex config state before applying a managed-block install or update.
- A failure during Codex apply/read-back or the later tracking commit restores pre-existing config bytes and mode, or
  removes a config created by the failed attempt.
- The existing file and Claude-settings rollback stays in the same failure transaction; no fresh installation row is
  published on failure.
- Rollback failures are actionable and name every incomplete surface without claiming a complete rollback.

## Acceptance Criteria

- Add a marked D013/D014 regression with a docstring naming the missing Codex rollback and unguarded read-back roots.
- Fault injection covers read-back failure and final tracking failure for both a missing config and pre-existing user
  TOML; assertions pin config bytes/mode, extension files, Claude settings, and tracking state.
- Unit tests preserve successful install/update, unavailable Codex, config conflict, manual registration, and
  pre-existing managed-block behavior.
- Run focused installer/Codex-hook tests, the relevant `tests/integration/docker/test_installer.py` Codex lifecycle
  slice, a clean-wheel enable/disable smoke, the regression suite, and `make pre-commit`.

## Compatibility and Exclusions

- Do not turn Codex absence, a planned conflict, or a race reported as the existing best-effort conflict into a fatal
  Claude installation failure.
- Do not remove commands outside the managed block or claim Codex trust/enrollment.
- Do not absorb runtime-disable reconciliation, D012 baseline ownership, or D019 legacy unmerge behavior.
- Keep the installed-manifest schema and successful tracking fields unchanged.

## Verification

The retained regression failed on `afde43bf` in all four original missing/pre-existing-config cases. After
implementation, 74 focused Codex-hook/regression tests and the broader 921-test installer/CLI slice passed (one skip),
as did the 3-test Docker Codex lifecycle slice, all 678 marked regressions, and 8,818 unit tests (one skip, 118
deselected). A wheel built from the branch passed isolated user-scope Claude+Codex enable/status/disable, and final
`make pre-commit` passed.

Independent review on 2026-08-08 found no design violations, reproduced the marked regression on `afde43bf`, and passed
74 focused tests, the 793-test install unit slice, and all 6 Docker Codex installer tests. It identified one stale
preservation comment and one dead rollback-state construction; both were removed before merge.

## Implementation Outcome

Codex managed-block writes now return an exact pre-write bytes/mode snapshot to the installer transaction. Unexpected
apply or read-back `OSError` failures use the same typed rollback boundary as final tracking failures, restoring Claude
settings, newly created extension files, and the Codex config before reporting failure. A config created by the attempt
is removed; a pre-existing config is restored byte-for-byte with its mode.

Rollback first verifies that the current config still matches Forge's applied bytes and mode. A later edit is preserved
and reported as an incomplete path instead of being overwritten. Planned absence/conflicts, manual registration,
idempotent managed blocks, successful tracking fields, and the legacy direct helper's `OSError` boundary are unchanged.
