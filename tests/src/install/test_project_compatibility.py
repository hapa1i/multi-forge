"""Tests for `.forge/project.toml` compatibility checks."""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.install.project_compat import (
    ProjectCompatibilityError,
    check_project_compatibility,
    check_project_compatibility_for_hook,
    diagnose_project_compatibility,
    enforce_project_compatibility,
)


def _write_project_toml(root: Path, body: str) -> Path:
    forge_dir = root / ".forge"
    forge_dir.mkdir(parents=True, exist_ok=True)
    path = forge_dir / "project.toml"
    path.write_text(body, encoding="utf-8")
    return path


def test_missing_file_is_compatible(tmp_path: Path) -> None:
    result = check_project_compatibility(tmp_path, running_forge="1.2.3")

    assert result.state == "missing"
    assert result.compatible is True
    assert result.reason is None


def test_compatible_specifier_is_no_op(tmp_path: Path) -> None:
    _write_project_toml(tmp_path, 'schema_version = 1\nrequired_forge = ">=1,<2"\n')

    result = enforce_project_compatibility(tmp_path, running_forge="1.2.3")

    assert result.compatible is True
    assert result.required_forge == ">=1,<2"


def test_incompatible_pin_blocks_command_path(tmp_path: Path) -> None:
    _write_project_toml(tmp_path, 'schema_version = 1\nrequired_forge = ">=9"\n')

    with pytest.raises(ProjectCompatibilityError, match="requires Forge >=9"):
        enforce_project_compatibility(tmp_path, running_forge="1.2.3")


def test_malformed_file_fails_strict_but_degrades_for_hook(tmp_path: Path) -> None:
    _write_project_toml(tmp_path, "not = valid = toml\n")

    with pytest.raises(ProjectCompatibilityError, match="invalid TOML"):
        check_project_compatibility(tmp_path, running_forge="1.2.3")

    result = check_project_compatibility_for_hook(tmp_path, running_forge="1.2.3")
    assert result.compatible is True
    assert result.state == "malformed"
    assert result.degraded is not None


def test_unknown_schema_version_fails_clear(tmp_path: Path) -> None:
    _write_project_toml(tmp_path, 'schema_version = 2\nrequired_forge = ">=1"\n')

    with pytest.raises(ProjectCompatibilityError, match="unsupported schema_version"):
        check_project_compatibility(tmp_path, running_forge="1.2.3")


def test_hook_path_fails_open_on_incompatible_pin(tmp_path: Path) -> None:
    _write_project_toml(tmp_path, 'schema_version = 1\nrequired_forge = ">=9"\n')

    result = check_project_compatibility_for_hook(tmp_path, running_forge="1.2.3")

    assert result.compatible is True
    assert result.state == "incompatible"
    assert result.degraded is not None


def test_doctor_surfaces_malformed_project_toml(tmp_path: Path) -> None:
    _write_project_toml(tmp_path, "not = valid = toml\n")

    result = diagnose_project_compatibility(tmp_path)

    assert result.compatible is False
    assert result.state == "malformed"
    assert result.reason is not None
