"""CLI tests for `forge model backend` recovery tips and exit codes.

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


def _backend_args(*args: str) -> list[str]:
    return ["model", "backend", *args]


def test_create_existing_config_errors_with_tip(runner: CliRunner, tmp_path: Path) -> None:
    """create on an existing config is a hard error (exit 1) with a start tip."""
    cfg = tmp_path / "litellm" / "config.yaml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("model_list: []\n")

    with patch("forge.cli.backend.get_backend_config_path", return_value=cfg):
        result = runner.invoke(main, _backend_args("create", "litellm"))

    assert result.exit_code == 1
    assert "already exists" in result.output
    assert "Tip:" in result.output
    assert "forge model backend start litellm" in result.output


def test_start_missing_config_errors_with_create_tip(runner: CliRunner, tmp_path: Path) -> None:
    missing = tmp_path / "litellm" / "config.yaml"

    with patch("forge.cli.backend.get_backend_config_path", return_value=missing):
        result = runner.invoke(main, _backend_args("start", "litellm", "--port", "4000"))

    assert result.exit_code == 1
    assert "not found" in result.output
    assert "Tip:" in result.output
    assert "forge model backend create litellm" in result.output


def test_list_json_includes_static_sources_and_local_runtime(
    runner: CliRunner,
    forge_home: Path,
) -> None:
    config_path = forge_home / "backends" / "litellm" / "config.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        "model_list:\n"
        "  - model_name: gemini-test\n"
        "    litellm_params:\n"
        "      model: gemini/gemini-test\n"
        "      api_key: os.environ/GEMINI_API_KEY\n"
    )
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

    result = runner.invoke(main, _backend_args("list", "--json"))

    assert result.exit_code == 0
    records = {item["source_id"]: item for item in _json_output(result)}
    assert records["openrouter"]["kind"] == "remote"
    assert records["openrouter"]["endpoint"]["env_var"] == "OPENROUTER_BASE_URL"
    assert records["openrouter"]["runtime_instance"] is None
    assert records["litellm-gemini-local"]["kind"] == "local"
    assert records["litellm-gemini-local"]["runtime_instance"]["backend_id"] == "litellm-4000"
    assert records["litellm-gemini-local"]["health"] == "healthy"
    # A gemini-only config means only one source matches, so the instance is not shared.
    assert records["litellm-gemini-local"]["runtime_instance"]["shared_with"] == []
    assert records["litellm-openai-local"]["runtime_instance"] is None
    assert records["litellm-anthropic-local"]["runtime_instance"] is None

    registry = store.read()
    assert set(registry.backends) == {"litellm-4000"}


def test_list_json_marks_shared_local_runtime_instance(
    runner: CliRunner,
    forge_home: Path,
) -> None:
    """A multi-provider config mirrors the shipped default: one litellm-4000 process
    serves both Gemini and OpenAI, so every local source backed by it (Gemini, OpenAI,
    and the OpenAI-credentialed codex-responses source) matches the single instance and
    the list marks it as shared rather than implying separate backends."""
    config_path = forge_home / "backends" / "litellm" / "config.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        "model_list:\n"
        "  - model_name: gemini-test\n"
        "    litellm_params:\n"
        "      model: gemini/gemini-test\n"
        "      api_key: os.environ/GEMINI_API_KEY\n"
        "  - model_name: gpt-test\n"
        "    litellm_params:\n"
        "      model: openai/gpt-test\n"
        "      api_key: os.environ/OPENAI_API_KEY\n"
    )
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

    result = runner.invoke(main, _backend_args("list", "--json"))

    assert result.exit_code == 0
    records = {item["source_id"]: item for item in _json_output(result)}

    gemini = records["litellm-gemini-local"]["runtime_instance"]
    openai = records["litellm-openai-local"]["runtime_instance"]
    # Both sources are backed by the single running instance.
    assert gemini["backend_id"] == "litellm-4000"
    assert openai["backend_id"] == "litellm-4000"
    # Each row names the sibling sources it shares the instance with (catalog order),
    # never itself. codex-responses-local is an OpenAI-credentialed co-tenant on 4000.
    assert gemini["shared_with"] == ["litellm-openai-local", "codex-responses-local"]
    assert openai["shared_with"] == ["litellm-gemini-local", "codex-responses-local"]
    # anthropic-local is not in the config, so it stays unmatched.
    assert records["litellm-anthropic-local"]["runtime_instance"] is None
    # The shared instance is still a single registry entry, not duplicated.
    assert set(store.read().backends) == {"litellm-4000"}


def test_list_human_marks_shared_runtime_instance(runner: CliRunner, forge_home: Path) -> None:
    """The human table flags a shared instance in the RUNTIME column."""
    config_path = forge_home / "backends" / "litellm" / "config.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        "model_list:\n"
        "  - model_name: gemini-test\n"
        "    litellm_params:\n"
        "      model: gemini/gemini-test\n"
        "      api_key: os.environ/GEMINI_API_KEY\n"
        "  - model_name: gpt-test\n"
        "    litellm_params:\n"
        "      model: openai/gpt-test\n"
        "      api_key: os.environ/OPENAI_API_KEY\n"
    )
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

    result = runner.invoke(main, _backend_args("list"))

    assert result.exit_code == 0
    assert "shared" in result.output


def test_list_human_shows_sources_even_without_runtime(runner: CliRunner, forge_home: Path) -> None:
    result = runner.invoke(main, _backend_args("list"))

    assert result.exit_code == 0
    assert "Forge Backend Sources" in result.output
    assert "openrouter" in result.output
    assert "litellm-remote" in result.output
    assert "No backends found" not in result.output


def test_list_human_shows_unmatched_runtime_without_source_match(
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

    result = runner.invoke(main, _backend_args("list"))

    assert result.exit_code == 0
    assert "Unmatched Runtime Instances" in result.output
    assert "litellm-4000" in result.output

    json_result = runner.invoke(main, _backend_args("list", "--json"))
    assert json_result.exit_code == 0
    records = {item["source_id"]: item for item in _json_output(json_result)}
    assert records["litellm-gemini-local"]["runtime_instance"] is None
    assert records["litellm-openai-local"]["runtime_instance"] is None
    assert records["litellm-anthropic-local"]["runtime_instance"] is None


def test_show_remote_source_details(runner: CliRunner, forge_home: Path) -> None:
    result = runner.invoke(main, _backend_args("show", "openrouter"))

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
    result = runner.invoke(main, _backend_args(verb, "openrouter"))

    assert result.exit_code == 1
    assert "no local lifecycle" in result.output
    assert BackendRegistryStore(forge_home / "backends" / "index.json").read().backends == {}


def test_delete_remote_source_has_intentional_error(runner: CliRunner, forge_home: Path) -> None:
    result = runner.invoke(main, _backend_args("delete", "openrouter", "--yes"))

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
        result = runner.invoke(main, _backend_args("start", "litellm-gemini-local"))

    assert result.exit_code == 1
    assert "not found" in result.output
    assert "forge model backend create litellm" in result.output


def test_test_auth_missing_credential_is_secret_free_json(runner: CliRunner, forge_home: Path) -> None:
    result = runner.invoke(main, _backend_args("test-auth", "openrouter", "--json"))

    assert result.exit_code == 1
    payload = _json_output(result)
    assert payload["auth_status"] == "missing"
    assert payload["missing_required_env_vars"] == ["OPENROUTER_API_KEY"]
    assert payload["probe"]["status"] == "skipped"
    assert "sk-" not in result.output


def test_test_auth_unknown_source_uses_cli_error_helper(runner: CliRunner, forge_home: Path) -> None:
    result = runner.invoke(main, _backend_args("test-auth", "missing-source"))

    assert result.exit_code == 1
    assert result.output.startswith("Error:")
    assert "forge model backend list" in result.output


@pytest.mark.parametrize("verb", ["create", "delete"])
def test_local_only_unknown_adapter_names_valid_choices(
    runner: CliRunner,
    forge_home: Path,
    verb: str,
) -> None:
    result = runner.invoke(
        main,
        _backend_args(verb, "foobar", "--yes") if verb == "delete" else _backend_args(verb, "foobar"),
    )

    assert result.exit_code == 1
    assert "Unknown backend adapter or source 'foobar'" in result.output
    assert "Valid adapters: litellm" in result.output
    assert "forge model backend list" in result.output


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

    result = runner.invoke(main, _backend_args("test-auth", "openrouter", "--json"))

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

    result = runner.invoke(main, _backend_args("test-auth", "openrouter", "--json"))

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

    result = runner.invoke(main, _backend_args("delete", "litellm"))

    assert result.exit_code == 1
    assert "not found" in result.output
    assert "Tip:" in result.output
    assert "forge model backend create litellm" in result.output


_SOURCE_RECORD_KEYS = {
    "backend_id",
    "source_id",
    "kind",
    "provider",
    "endpoint",
    "required_credentials",
    "credentials",
    "auth_status",
    "missing_required_env_vars",
    "health",
    "has_lifecycle",
    "runtime_instance",
}

_REGISTRY_FALLBACK_KEYS = {
    "backend_id",
    "source_id",
    "found",
    "adapter_type",
    "runtime_instance",
    "config_path",
}


def test_show_json_configured_source_emits_source_record(
    runner: CliRunner,
    forge_home: Path,
) -> None:
    """show <source-id> --json dispatches through _source_record (path 1).

    A built-in source like openrouter resolves via _source_for_identifier, so the
    payload carries the full source-record shape, not the registry-fallback shape.
    """
    result = runner.invoke(main, _backend_args("show", "openrouter", "--json"))

    assert result.exit_code == 0
    payload = _json_output(result)
    assert set(payload) == _SOURCE_RECORD_KEYS
    assert payload["backend_id"] == "openrouter"
    assert payload["source_id"] == "openrouter"
    assert payload["kind"] == "remote"
    # Remote source has no local lifecycle, so no runtime instance is matched.
    assert payload["runtime_instance"] is None
    assert payload["has_lifecycle"] is False
    assert isinstance(payload["credentials"], list)
    assert "OPENROUTER_API_KEY" in payload["missing_required_env_vars"]


def test_show_json_registry_only_fallback_when_not_a_source(
    runner: CliRunner,
    forge_home: Path,
) -> None:
    """show <registry-id> --json uses the registry fallback shape (path 2).

    litellm-4000 is a registry backend_id but not a model source, so the command
    falls through to the registry-only branch and reports found=true with a
    populated runtime_instance record.
    """
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

    result = runner.invoke(main, _backend_args("show", "litellm-4000", "--json"))

    assert result.exit_code == 0
    payload = _json_output(result)
    assert set(payload) == _REGISTRY_FALLBACK_KEYS
    assert payload["backend_id"] == "litellm-4000"
    assert payload["source_id"] is None
    assert payload["found"] is True
    assert payload["adapter_type"] == "litellm"
    runtime = payload["runtime_instance"]
    assert runtime is not None
    assert runtime["backend_id"] == "litellm-4000"
    assert runtime["adapter_type"] == "litellm"
    assert runtime["port"] == 4000
    assert runtime["status"] == "healthy"
    assert runtime["alive"] is False


def test_show_json_unknown_id_reports_not_found(
    runner: CliRunner,
    forge_home: Path,
) -> None:
    """show <unknown-id> --json reports found=false with empty runtime/config (path 3)."""
    result = runner.invoke(main, _backend_args("show", "nope-9999", "--json"))

    assert result.exit_code == 0
    payload = _json_output(result)
    assert set(payload) == _REGISTRY_FALLBACK_KEYS
    assert payload["backend_id"] == "nope-9999"
    assert payload["source_id"] is None
    assert payload["found"] is False
    # rsplit("-", 1) on "nope-9999" yields adapter "nope".
    assert payload["adapter_type"] == "nope"
    assert payload["runtime_instance"] is None
    assert payload["config_path"] is None
