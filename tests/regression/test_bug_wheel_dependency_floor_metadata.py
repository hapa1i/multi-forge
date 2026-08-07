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


def test_distribution_metadata_enforces_security_floors() -> None:
    requirements = _distribution_requirements()

    _assert_minimum(requirements["aiohttp"], "3.14.3")
    _assert_minimum(requirements["cryptography"], "50.0.0")
    assert {"expression", "redis", "uvloop"} <= requirements.keys()
    assert not requirements["fastapi"].specifier.contains("0.141.1")
    assert not requirements["starlette"].specifier.contains("1.4.1")
    assert requirements["litellm"].extras == set()
