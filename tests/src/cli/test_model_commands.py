"""CLI tests for the `forge model` namespace."""

from __future__ import annotations

import json

from click.testing import CliRunner

from forge.cli.main import main


def test_model_group_has_backend_and_catalog() -> None:
    result = CliRunner().invoke(main, ["model", "--help"])

    assert result.exit_code == 0
    assert "backend" in result.output
    assert "catalog" in result.output


def test_root_help_lists_model_not_backend() -> None:
    result = CliRunner().invoke(main, ["--help"])

    assert result.exit_code == 0
    assert "model" in result.output
    assert "\n  backend " not in result.output


def test_old_backend_path_is_clean_break() -> None:
    result = CliRunner().invoke(main, ["backend", "list"])

    assert result.exit_code == 2
    assert "No such command 'backend'" in result.output


def test_model_catalog_human_output() -> None:
    result = CliRunner().invoke(main, ["model", "catalog"])

    assert result.exit_code == 0
    assert "Forge Model Catalog" in result.output
    assert "Provider Defaults" in result.output
    assert "gpt-5.5" in result.output


def test_model_catalog_json_shape() -> None:
    result = CliRunner().invoke(main, ["model", "catalog", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["schema_version"] == 1
    assert "gpt-5.5" in payload["models"]
    assert "aliases" in payload
    assert "openai" in payload["defaults"]


def test_model_catalog_errors_use_cli_helper(monkeypatch) -> None:
    from forge.core.models.catalog import ModelCatalogError

    def _boom():
        raise ModelCatalogError("bad catalog")

    monkeypatch.setattr("forge.cli.model.load_model_catalog", _boom)

    result = CliRunner().invoke(main, ["model", "catalog"])

    assert result.exit_code == 1
    # Diagnostics go to stderr (clean stdout for the JSON/results stream).
    assert result.stderr.startswith("Error:")
    assert "bad catalog" in result.stderr
