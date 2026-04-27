"""Tests for bundle registry with per-bundle config support.

Verifies that get_bundle_policies() and build_engine() correctly handle
the config parameter to control TDD enforcement level (strict vs permissive).
"""

from __future__ import annotations

import pytest

from forge.guard.deterministic.registry import get_bundle_policies
from forge.guard.deterministic.tdd import TDDEnforcementPolicy
from forge.guard.engine import build_engine


class TestGetBundlePoliciesConfig:
    """Test config parameter in get_bundle_policies()."""

    def test_default_returns_strict_tdd(self) -> None:
        """No config -> TDDEnforcementPolicy with strict=True (default)."""
        policies = get_bundle_policies("tdd")
        assert len(policies) == 2
        tdd = policies[0]
        assert isinstance(tdd, TDDEnforcementPolicy)
        assert tdd.strict is True

    def test_strict_config_explicit(self) -> None:
        """config={"strict": True} -> same as default (strict=True)."""
        policies = get_bundle_policies("tdd", config={"strict": True})
        assert len(policies) == 2
        tdd = policies[0]
        assert isinstance(tdd, TDDEnforcementPolicy)
        assert tdd.strict is True

    def test_permissive_config(self) -> None:
        """config={"strict": False} -> TDDEnforcementPolicy with strict=False."""
        policies = get_bundle_policies("tdd", config={"strict": False})
        assert len(policies) == 2
        tdd = policies[0]
        assert isinstance(tdd, TDDEnforcementPolicy)
        assert tdd.strict is False

    def test_config_does_not_affect_other_bundles(self) -> None:
        """config only affects the target bundle, not other bundles."""
        policies = get_bundle_policies("coding_standards", config={"strict": False})
        assert len(policies) == 3
        # Should be coding standards policies, not affected by config
        ids = [p.policy_id for p in policies]
        assert "coding_standards.no-type-checking" in ids
        assert "coding_standards.no-backward-compat" in ids
        assert "coding_standards.no-emoji" in ids

    def test_unknown_bundle_returns_empty(self) -> None:
        """Unknown bundle name returns empty list."""
        policies = get_bundle_policies("nonexistent", config={"strict": True})
        assert policies == []

    def test_permissive_preserves_no_skip_tests(self) -> None:
        """Permissive config only affects TDDEnforcementPolicy, not NoSkipTestsPolicy."""
        policies = get_bundle_policies("tdd", config={"strict": False})
        ids = [p.policy_id for p in policies]
        assert "tdd.tests-before-impl" in ids
        assert "tdd.no-skip-tests" in ids

    def test_non_bool_strict_raises_value_error(self) -> None:
        """config={"strict": "nope"} should raise ValueError."""
        with pytest.raises(ValueError, match="must be bool"):
            get_bundle_policies("tdd", config={"strict": "nope"})


class TestBuildEngineConfig:
    """Test bundle_config parameter in build_engine()."""

    def test_build_engine_default_strict(self) -> None:
        """build_engine without bundle_config -> strict TDD policies."""
        engine = build_engine(["tdd"])
        tdd_policies = [p for p in engine.policies if isinstance(p, TDDEnforcementPolicy)]
        assert len(tdd_policies) == 1
        assert tdd_policies[0].strict is True

    def test_build_engine_permissive(self) -> None:
        """build_engine with bundle_config -> permissive TDD policies."""
        engine = build_engine(["tdd"], bundle_config={"tdd": {"strict": False}})
        tdd_policies = [p for p in engine.policies if isinstance(p, TDDEnforcementPolicy)]
        assert len(tdd_policies) == 1
        assert tdd_policies[0].strict is False

    def test_build_engine_empty_bundles_no_policies(self) -> None:
        """build_engine with empty bundles -> no policies registered."""
        engine = build_engine([])
        assert len(engine.policies) == 0

    def test_build_engine_config_preserves_other_bundles(self) -> None:
        """bundle_config for tdd does not affect coding_standards."""
        engine = build_engine(["tdd", "coding_standards"], bundle_config={"tdd": {"strict": False}})
        ids = [p.policy_id for p in engine.policies]
        assert "tdd.tests-before-impl" in ids
        assert "tdd.no-skip-tests" in ids
        assert "coding_standards.no-type-checking" in ids
        assert "coding_standards.no-backward-compat" in ids
