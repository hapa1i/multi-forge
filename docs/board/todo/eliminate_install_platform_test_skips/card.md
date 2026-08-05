# Eliminate installer platform-test skips

**Origin**: Verification review of
[`align_stop_verification_contract`](../../done/align_stop_verification_contract/card.md).

**Authority**:
[`testing_guidelines.md` Test Maintenance Policy](../../../developer/testing_guidelines.md#test-maintenance-policy).

**Lane**: `todo/` -- accepted test-hygiene follow-up, parked.

## Goal

Exercise installer symlink and filesystem-case behavior without runtime `pytest.skip()` branches, so the unit suite
passes or fails cleanly on the supported macOS environment.

## Evidence

- `tests/src/install/test_hook_dispatcher.py` and `tests/src/install/test_project_registry.py` contain conditional skips
  for unavailable symlinks and host filesystem case semantics.
- On the current case-insensitive filesystem, the targeted installer run reports 76 passed and one skip at
  `tests/src/install/test_project_registry.py:59`; the symlink probes run successfully.
- The Stop-verification branch adds no skip or skip-if construct. This is pre-existing debt, not part of D006/U002/U003.

## Acceptance Criteria

- Replace the conditional skips with deterministic coverage of symlink availability and both case-sensitive and
  case-insensitive identity semantics.
- Preserve project-registry canonicalization, same-directory aliasing, and distinct-root isolation behavior.
- The targeted installer tests pass with zero skips on the supported macOS environment.
- `make test-unit` reports zero skips unless a separately documented, newly discovered skip remains.
- `make pre-commit` passes.
