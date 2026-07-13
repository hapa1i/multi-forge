"""Tests for `.forge/project.toml` compatibility checks."""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.install.project_compat import (
    ProjectCompatibilityError,
    check_project_compatibility,
    check_project_compatibility_for_hook,
    diagnose_project_compatibility,
    diagnose_project_compatibility_for_hook,
    enforce_project_compatibility,
    format_project_compatibility_recovery,
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


def test_prerelease_running_forge_satisfies_matching_range(tmp_path: Path) -> None:
    _write_project_toml(tmp_path, 'schema_version = 1\nrequired_forge = ">=0.9"\n')

    result = enforce_project_compatibility(tmp_path, running_forge="0.10.0.dev1")

    assert result.compatible is True
    assert result.required_forge == ">=0.9"


def test_incompatible_pin_blocks_command_path(tmp_path: Path) -> None:
    _write_project_toml(tmp_path, 'schema_version = 1\nrequired_forge = ">=9"\n')

    with pytest.raises(ProjectCompatibilityError, match="requires Forge >=9"):
        enforce_project_compatibility(tmp_path, running_forge="1.2.3")


def test_recovery_wording_is_provenance_neutral() -> None:
    recovery = format_project_compatibility_recovery(environment={})

    assert recovery == "Run a Forge version satisfying required_forge, or edit/reset project state."
    assert "global Forge" not in recovery


def test_recovery_wording_adds_dev_relaunch_without_value() -> None:
    recovery = format_project_compatibility_recovery(
        environment={"FORGE_DEV": "/secret/checkout"},
    )

    assert "FORGE_DEV" in recovery
    assert "relaunching the managed session" in recovery
    assert "/secret/checkout" not in recovery


def test_recovery_wording_adds_sidecar_image_hint() -> None:
    recovery = format_project_compatibility_recovery(environment={"FORGE_SIDECAR": "1"})

    assert "sidecar session" in recovery
    assert "image containing a satisfying Forge version" in recovery
    assert "FORGE_SIDECAR" not in recovery


@pytest.mark.parametrize("value", ["", "0"])
def test_recovery_wording_omits_sidecar_hint_when_not_inside_sidecar(value: str) -> None:
    recovery = format_project_compatibility_recovery(environment={"FORGE_SIDECAR": value})

    assert "sidecar session" not in recovery


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


def test_hook_invocation_diagnostic_deduplicates_roots_and_logs_once(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _write_project_toml(tmp_path, 'schema_version = 1\nrequired_forge = ">=9"\n')

    with caplog.at_level("DEBUG", logger="forge.install.project_compat"):
        results = diagnose_project_compatibility_for_hook(
            tmp_path,
            tmp_path,
            operation="test-hook",
            running_forge="1.2.3",
        )

    assert len(results) == 1
    assert results[0].state == "incompatible"
    messages = [record.message for record in caplog.records if "Project compatibility degraded" in record.message]
    assert len(messages) == 1
    assert "test-hook" in messages[0]


def test_hook_invocation_diagnostic_is_silent_for_compatible_root(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _write_project_toml(tmp_path, 'schema_version = 1\nrequired_forge = ">=1"\n')

    with caplog.at_level("DEBUG", logger="forge.install.project_compat"):
        results = diagnose_project_compatibility_for_hook(
            tmp_path,
            operation="test-hook",
            running_forge="1.2.3",
        )

    assert len(results) == 1
    assert results[0].state == "compatible"
    assert not [record for record in caplog.records if "Project compatibility degraded" in record.message]


def test_doctor_surfaces_malformed_project_toml(tmp_path: Path) -> None:
    _write_project_toml(tmp_path, "not = valid = toml\n")

    result = diagnose_project_compatibility(tmp_path)

    assert result.compatible is False
    assert result.state == "malformed"
    assert result.reason is not None
    assert "satisfying required_forge" in result.reason
