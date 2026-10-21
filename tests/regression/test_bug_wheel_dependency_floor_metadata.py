"""Regression: security floors must be shipped in distribution metadata.

The uv-only constraint table protects repository environments but is not part of
a built wheel's ``Requires-Dist`` fields. Non-uv installers therefore missed the
patched aiohttp and cryptography floors, while LiteLLM's proxy extra also capped
cryptography below the required version.
"""

from __future__ import annotations

from importlib.metadata import requires

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

pytestmark = pytest.mark.regression


def _distribution_requirements() -> dict[str, Requirement]:
    raw_requirements = requires("multi-forge")
    assert raw_requirements is not None
    parsed = [Requirement(raw) for raw in raw_requirements]
    return {canonicalize_name(requirement.name): requirement for requirement in parsed}


def _assert_minimum(requirement: Requirement, expected: str) -> None:
    expected_version = Version(expected)
    lower_bounds = [
        Version(specifier.version)
        for specifier in requirement.specifier
        if specifier.operator in {">=", ">", "==", "==="}
    ]
    assert lower_bounds and max(lower_bounds) >= expected_version


@pytest.mark.parametrize(
    ("package", "minimum"),
    [
        ("aiohttp", "3.14.4"),
        ("certifi", "2026.10.19"),
        ("cryptography", "50.0.0"),
        ("multidict", "6.9.1"),
        ("oauthlib", "4.0.0"),
        ("pyjwt", "2.15.0"),
        ("urllib3", "2.8.0"),
    ],
)
def test_distribution_metadata_enforces_security_floors(package: str, minimum: str) -> None:
    requirements = _distribution_requirements()
    _assert_minimum(requirements[package], minimum)


def test_distribution_metadata_preserves_litellm_runtime_contract() -> None:
    requirements = _distribution_requirements()

    assert "virtualenv" not in requirements
    assert {"boto3", "expression", "redis", "uvloop"} <= requirements.keys()
    assert not requirements["fastapi"].specifier.contains("0.141.1")
    assert not requirements["starlette"].specifier.contains("1.4.1")
    litellm = requirements["litellm"]
    assert litellm.extras == set()
    _assert_minimum(litellm, "1.102.0")
    assert litellm.specifier.contains("1.102.0")
    assert not litellm.specifier.contains("1.102.1")
