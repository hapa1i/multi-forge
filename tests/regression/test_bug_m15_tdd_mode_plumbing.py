"""Regression test for M15: tdd_mode not plumbed into policy engine.

Bug: get_bundle_policies("tdd") always instantiated TDDEnforcementPolicy with
strict=True regardless of session config. Users could not express "permissive"
(warn-only) TDD mode.

Root cause: build_engine() called get_bundle_policies(bundle) without passing
bundle_config. The config parameter was ignored.

Fix: Added bundle_config parameter to build_engine(), threaded config={"strict": ...}
through to get_bundle_policies() which passes it to TDDEnforcementPolicy(strict=...).

Fixed in: src/forge/policy/deterministic/registry.py, src/forge/policy/engine.py
(action plan Step 8a, M15)
"""

import pytest

from forge.policy.deterministic.registry import get_bundle_policies
from forge.policy.deterministic.tdd import TDDEnforcementPolicy
from forge.policy.engine import build_engine

pytestmark = pytest.mark.regression


def _get_tdd_policy(policies: list) -> TDDEnforcementPolicy:
    """Extract and narrow the TDD policy from a policy list."""
    policy = next(p for p in policies if p.policy_id == "tdd.tests-before-impl")
    assert isinstance(policy, TDDEnforcementPolicy)
    return policy


# ---------------------------------------------------------------------------
# Registry-level tests (get_bundle_policies)
# ---------------------------------------------------------------------------


def test_tdd_bundle_default_is_strict() -> None:
    """No config → TDD policy defaults to strict=True (deny violations)."""
    tdd_policy = _get_tdd_policy(get_bundle_policies("tdd"))
    assert tdd_policy.strict is True


def test_tdd_bundle_permissive_mode() -> None:
    """config={"strict": False} → TDD policy warns instead of denying."""
    tdd_policy = _get_tdd_policy(get_bundle_policies("tdd", config={"strict": False}))
    assert tdd_policy.strict is False


def test_tdd_strict_config_explicit() -> None:
    """config={"strict": True} → explicit strict mode works."""
    tdd_policy = _get_tdd_policy(get_bundle_policies("tdd", config={"strict": True}))
    assert tdd_policy.strict is True


def test_tdd_invalid_strict_type_raises() -> None:
    """Non-bool strict value must raise ValueError, not silently coerce."""
    with pytest.raises(ValueError, match="must be bool"):
        get_bundle_policies("tdd", config={"strict": "yes"})


# ---------------------------------------------------------------------------
# Engine-level tests (build_engine plumbing — the actual regression seam)
# ---------------------------------------------------------------------------


def test_build_engine_passes_bundle_config_to_policies() -> None:
    """build_engine() must thread bundle_config through to policy instances.

    This is the actual regression seam: the bug was build_engine() calling
    get_bundle_policies(bundle) without passing config, so tdd_mode was ignored.
    """
    engine = build_engine(["tdd"], bundle_config={"tdd": {"strict": False}})
    tdd_policy = _get_tdd_policy(list(engine.policies))
    assert tdd_policy.strict is False


def test_build_engine_default_config_is_strict() -> None:
    """build_engine() without bundle_config → TDD policy is strict (default)."""
    engine = build_engine(["tdd"])
    tdd_policy = _get_tdd_policy(list(engine.policies))
    assert tdd_policy.strict is True
