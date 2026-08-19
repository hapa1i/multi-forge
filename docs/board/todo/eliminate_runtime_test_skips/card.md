# Eliminate runtime test skips

**Epic**: [`epic_wave8_residual_maintenance`](../../doing/epic_wave8_residual_maintenance/card.md).

**Origin**: Verification review of
[`align_stop_verification_contract`](../../done/align_stop_verification_contract/card.md).

**Authority**:
[`testing_guidelines.md` Test Maintenance Policy](../../../developer/testing_guidelines.md#test-maintenance-policy).

**Lane**: `todo/` -- accepted Wave 8 order 6; parked.

**Finding**: O072 (MEDIUM test-policy).

## Goal

Exercise credential-template, installer symlink, and filesystem-case behavior without runtime `pytest.skip()` branches,
so the unit suite passes or fails cleanly on every supported test environment.

## Evidence

- `tests/src/core/auth/test_capabilities.py` calls `pytest.skip()` inside a loop; one absent expected template aborts
  validation of every remaining template.
- `tests/src/install/test_hook_dispatcher.py` and `tests/src/install/test_project_registry.py` contain five conditional
  skips for unavailable symlinks and host filesystem case semantics.
- On the current case-insensitive filesystem, the targeted installer run reports 76 passed and one skip at
  `tests/src/install/test_project_registry.py:59`; the symlink probes run successfully.
- The Stop-verification branch adds no skip or skip-if construct. This is pre-existing debt, not part of D006/U002/U003.

## Acceptance Criteria

- Replace all six runtime skips with deterministic fixtures/parameterization for shipped-template, symlink, and both
  case-sensitive and case-insensitive identity semantics.
- Ensure one absent template cannot abort validation of other credential mappings.
- Preserve project-registry canonicalization, same-directory aliasing, and distinct-root isolation behavior.
- The targeted installer tests pass with zero skips on the supported macOS environment.
- `make test-unit` reports zero skips.
- `make pre-commit` passes.
