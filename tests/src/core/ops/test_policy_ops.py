import ast
from pathlib import Path
from typing import get_args

import pytest

from forge.core.ops import policy as policy_ops
from forge.policy.deterministic.registry import BUNDLES
from forge.policy.types import FailMode


def test_policy_activation_vocabularies_match_policy_authorities() -> None:
    assert policy_ops.POLICY_BUNDLE_NAMES == tuple(BUNDLES)
    assert policy_ops.POLICY_FAIL_MODES == get_args(FailMode)


def test_build_policy_activation_defaults_enable_values() -> None:
    values = policy_ops.build_policy_activation(enabled=True, bundles=["tdd"])

    assert values == policy_ops.PolicyActivationValues(
        enabled=True,
        bundles=("tdd",),
        fail_mode="open",
        bundle_config={},
    )


def test_build_policy_activation_preserves_order_and_builds_permissive_tdd_config() -> None:
    values = policy_ops.build_policy_activation(
        enabled=True,
        bundles=["coding_standards", "tdd"],
        fail_mode="closed",
        permissive=True,
    )

    assert values.bundles == ("coding_standards", "tdd")
    assert values.fail_mode == "closed"
    assert values.bundle_config == {"tdd": {"strict": False}}


def test_build_policy_activation_ignores_permissive_without_tdd() -> None:
    values = policy_ops.build_policy_activation(
        enabled=True,
        bundles=["coding_standards"],
        permissive=True,
    )

    assert values.bundle_config == {}


def test_build_policy_activation_returns_deactivation_values() -> None:
    values = policy_ops.build_policy_activation(enabled=False)

    assert values == policy_ops.PolicyActivationValues(enabled=False)


def test_build_policy_activation_requires_bundle_when_enabling() -> None:
    with pytest.raises(policy_ops.PolicyActivationInputError, match="at least one policy bundle"):
        policy_ops.build_policy_activation(enabled=True)


def test_build_policy_activation_rejects_unknown_bundle() -> None:
    with pytest.raises(policy_ops.PolicyActivationInputError, match="unknown policy bundle"):
        policy_ops.build_policy_activation(enabled=True, bundles=["unknown"])


def test_build_policy_activation_rejects_unknown_fail_mode() -> None:
    with pytest.raises(policy_ops.PolicyActivationInputError, match="fail mode"):
        policy_ops.build_policy_activation(enabled=True, bundles=["tdd"], fail_mode="invalid")


def test_build_policy_activation_rejects_options_when_disabling() -> None:
    with pytest.raises(policy_ops.PolicyActivationInputError, match="deactivation"):
        policy_ops.build_policy_activation(enabled=False, bundles=["tdd"])


def test_policy_ops_is_ui_free() -> None:
    repo_root = Path(__file__).resolve().parents[4]
    tree = ast.parse((repo_root / "src/forge/core/ops/policy.py").read_text(encoding="utf-8"))
    forbidden_imports = {"click", "rich", "sys"}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported = {alias.name.split(".")[0] for alias in node.names}
            assert imported.isdisjoint(forbidden_imports)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert module.split(".")[0] not in forbidden_imports
        elif isinstance(node, ast.Call):
            func = node.func
            assert not (isinstance(func, ast.Name) and func.id == "print")
            assert not (
                isinstance(func, ast.Attribute)
                and func.attr == "exit"
                and isinstance(func.value, ast.Name)
                and func.value.id == "sys"
            )
