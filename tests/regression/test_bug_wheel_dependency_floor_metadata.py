"""Regression: security floors must be shipped in distribution metadata.

The uv-only constraint table protects repository environments but is not part of
a built wheel's ``Requires-Dist`` fields. Non-uv installers therefore missed the
patched aiohttp and cryptography floors, while LiteLLM's proxy extra also capped
cryptography below the required version. Optional tooling graphs also need patched
lower bounds even when those packages are absent from wheel metadata.
"""

from __future__ import annotations

import tomllib
from importlib.metadata import requires
from pathlib import Path

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
        ("dnspython", "2.9.0"),
        ("filelock", "4.2.1"),
        ("multidict", "6.9.1"),
        ("oauthlib", "4.0.1"),
        ("pyjwt", "2.15.0"),
        ("urllib3", "2.8.0"),
    ],
)
def test_distribution_metadata_enforces_security_floors(package: str, minimum: str) -> None:
    requirements = _distribution_requirements()
    _assert_minimum(requirements[package], minimum)


def test_provider_check_pyasn1_security_floor() -> None:
    root = Path(__file__).resolve().parents[2]
    project = tomllib.loads((root / "pyproject.toml").read_text())
    constraints = [Requirement(value) for value in project["tool"]["uv"]["constraint-dependencies"]]
    pyasn1 = next(requirement for requirement in constraints if canonicalize_name(requirement.name) == "pyasn1")
    _assert_minimum(pyasn1, "0.6.5")

    lock = tomllib.loads((root / "uv.lock").read_text())
    versions = [Version(package["version"]) for package in lock["package"] if package["name"] == "pyasn1"]
    assert versions and all(version >= Version("0.6.5") for version in versions)
    assert "pyasn1" not in _distribution_requirements()


def test_distribution_metadata_preserves_litellm_runtime_contract() -> None:
    requirements = _distribution_requirements()

    assert "virtualenv" not in requirements
    assert "black" not in requirements
    assert {"boto3", "expression", "redis", "uvloop"} <= requirements.keys()
    assert not requirements["fastapi"].specifier.contains("0.141.1")
    assert not requirements["starlette"].specifier.contains("1.4.1")
    litellm = requirements["litellm"]
    assert litellm.extras == set()
    _assert_minimum(litellm, "1.102.2")
    assert litellm.specifier.contains("1.102.2")
    assert not litellm.specifier.contains("1.102.0")
    assert not litellm.specifier.contains("1.102.1")
    assert not litellm.specifier.contains("1.102.3")
