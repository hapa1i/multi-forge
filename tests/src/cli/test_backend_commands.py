"""CLI tests for `forge backend` recovery tips and exit codes.

Covers the §3 behavior change (create-on-existing is now a hard error) and the
not-found recovery tips on start/delete.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from forge.backend.registry import (
    BackendInstance,
    BackendRegistry,
    BackendRegistryStore,
)
from forge.cli import backend as backend_cli
from forge.cli.main import main
from forge.core.auth.credentials_file import save_profile


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def forge_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    for key in (
        "OPENROUTER_API_KEY",
        "OPENROUTER_BASE_URL",
        "LITELLM_API_KEY",
        "LITELLM_BASE_URL",
        "GEMINI_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    return tmp_path


def _json_output(result: Any) -> Any:
    return json.loads(result.output)


def test_create_existing_config_errors_with_tip(runner: CliRunner, tmp_path: Path) -> None:
    """create on an existing config is a hard error (exit 1) with a start tip."""
    cfg = tmp_path / "litellm" / "config.yaml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("model_list: []\n")

    with patch("forge.cli.backend.get_backend_config_path", return_value=cfg):
        result = runner.invoke(main, ["backend", "create", "litellm"])

    assert result.exit_code == 1
    assert "already exists" in result.output
    assert "Tip:" in result.output
    assert "forge backend start litellm" in result.output


def test_start_missing_config_errors_with_create_tip(runner: CliRunner, tmp_path: Path) -> None:
    missing = tmp_path / "litellm" / "config.yaml"

    with patch("forge.cli.backend.get_backend_config_path", return_value=missing):
        result = runner.invoke(main, ["backend", "start", "litellm", "--port", "4000"])

    assert result.exit_code == 1
    assert "not found" in result.output
    assert "Tip:" in result.output
    assert "forge backend create litellm" in result.output


def test_list_json_includes_static_sources_and_local_runtime(
    runner: CliRunner,
    forge_home: Path,
) -> None:
    store = BackendRegistryStore(forge_home / "backends" / "index.json")
    store.write(
        BackendRegistry(
            backends={
                "litellm-4000": BackendInstance(
                    backend_id="litellm-4000",
                    adapter_type="litellm",
                    port=4000,
                    pid=None,
                    status="healthy",
                )
            }
        )
    )

    result = runner.invoke(main, ["backend", "list", "--json"])

    assert result.exit_code == 0
    records = {item["source_id"]: item for item in _json_output(result)}
    assert records["openrouter"]["kind"] == "remote"
    assert records["openrouter"]["endpoint"]["env_var"] == "OPENROUTER_BASE_URL"
    assert records["openrouter"]["runtime_instance"] is None
    assert records["litellm-gemini-local"]["kind"] == "local"
    assert records["litellm-gemini-local"]["runtime_instance"]["backend_id"] == "litellm-4000"
    assert records["litellm-gemini-local"]["health"] == "healthy"

    registry = store.read()
    assert set(registry.backends) == {"litellm-4000"}


def test_list_human_shows_sources_even_without_runtime(runner: CliRunner, forge_home: Path) -> None:
    result = runner.invoke(main, ["backend", "list"])

    assert result.exit_code == 0
    assert "Forge Backend Sources" in result.output
    assert "openrouter" in result.output
    assert "litellm-remote" in result.output
    assert "No backends found" not in result.output


def test_show_remote_source_details(runner: CliRunner, forge_home: Path) -> None:
    result = runner.invoke(main, ["backend", "show", "openrouter"])

    assert result.exit_code == 0
    assert "Backend source:" in result.output
    assert "openrouter" in result.output
    assert "Kind:" in result.output
    assert "remote" in result.output
    assert "Lifecycle:" in result.output
    assert "none" in result.output


@pytest.mark.parametrize("verb", ["start", "stop"])
def test_remote_source_lifecycle_errors_before_registry_mutation(
    runner: CliRunner,
    forge_home: Path,
    verb: str,
) -> None:
    result = runner.invoke(main, ["backend", verb, "openrouter"])

    assert result.exit_code == 1
    assert "no local lifecycle" in result.output
    assert BackendRegistryStore(forge_home / "backends" / "index.json").read().backends == {}


def test_delete_remote_source_has_intentional_error(runner: CliRunner, forge_home: Path) -> None:
    result = runner.invoke(main, ["backend", "delete", "openrouter", "--yes"])

    assert result.exit_code == 1
    assert "remote" in result.output
    assert "no local config" in result.output
    assert BackendRegistryStore(forge_home / "backends" / "index.json").read().backends == {}


def test_local_source_start_uses_default_lifecycle_port(
    runner: CliRunner,
    forge_home: Path,
    tmp_path: Path,
) -> None:
    missing = tmp_path / "litellm" / "config.yaml"

    with patch("forge.cli.backend.get_backend_config_path", return_value=missing):
        result = runner.invoke(main, ["backend", "start", "litellm-gemini-local"])

    assert result.exit_code == 1
    assert "not found" in result.output
    assert "forge backend create litellm" in result.output


def test_test_auth_missing_credential_is_secret_free_json(runner: CliRunner, forge_home: Path) -> None:
    result = runner.invoke(main, ["backend", "test-auth", "openrouter", "--json"])

    assert result.exit_code == 1
    payload = _json_output(result)
    assert payload["auth_status"] == "missing"
    assert payload["missing_required_env_vars"] == ["OPENROUTER_API_KEY"]
    assert payload["probe"]["status"] == "skipped"
    assert "sk-" not in result.output


def test_test_auth_env_provenance_does_not_echo_secret(
    runner: CliRunner,
    forge_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "sk-openrouter-secret"
    monkeypatch.setenv("OPENROUTER_API_KEY", secret)
    monkeypatch.setattr(
        backend_cli,
        "_probe_model_source",
        lambda *_args, **_kwargs: backend_cli._ProbeResult(status="passed", detail="ok", http_status=200),
    )

    result = runner.invoke(main, ["backend", "test-auth", "openrouter", "--json"])

    assert result.exit_code == 0
    payload = _json_output(result)
    api_key = next(
        env_var
        for credential in payload["credentials"]
        for env_var in credential["env_vars"]
        if env_var["name"] == "OPENROUTER_API_KEY"
    )
    assert api_key["configured"] is True
    assert api_key["provenance"] == "env"
    assert secret not in result.output


def test_test_auth_credential_file_provenance_does_not_echo_secret(
    runner: CliRunner,
    forge_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "sk-openrouter-file-secret"
    save_profile("default", {"OPENROUTER_API_KEY": secret})
    monkeypatch.setattr(
        backend_cli,
        "_probe_model_source",
        lambda *_args, **_kwargs: backend_cli._ProbeResult(status="passed", detail="ok", http_status=200),
    )

    result = runner.invoke(main, ["backend", "test-auth", "openrouter", "--json"])

    assert result.exit_code == 0
    payload = _json_output(result)
    api_key = next(
        env_var
        for credential in payload["credentials"]
        for env_var in credential["env_vars"]
        if env_var["name"] == "OPENROUTER_API_KEY"
    )
    assert api_key["configured"] is True
    assert api_key["provenance"] == "credential_file"
    assert secret not in result.output


def test_delete_missing_config_errors_with_create_tip(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # delete (no --port) checks get_forge_home()/backends/<adapter>; point it at an empty dir.
    monkeypatch.setattr("forge.cli.backend.get_forge_home", lambda: tmp_path)

    result = runner.invoke(main, ["backend", "delete", "litellm"])

    assert result.exit_code == 1
    assert "not found" in result.output
    assert "Tip:" in result.output
    assert "forge backend create litellm" in result.output
