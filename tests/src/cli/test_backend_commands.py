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
    BackendRegistry,
    BackendRegistryStore,
    ManagedBackendProcess,
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


def _normalized_output(result: Any) -> str:
    return " ".join(result.output.split())


def _backend_args(*args: str) -> list[str]:
    return ["model", "backend", *args]


def _managed_process(
    process_id: str = "litellm-4000",
    *,
    adapter_type: str = "litellm",
    port: int = 4000,
    pid: int | None = None,
) -> ManagedBackendProcess:
    return ManagedBackendProcess(
        process_id=process_id,
        adapter_type=adapter_type,
        port=port,
        pid=pid,
        status="healthy",
    )


def _write_backend_registry(forge_home: Path, *instances: ManagedBackendProcess) -> BackendRegistryStore:
    store = BackendRegistryStore(forge_home / "backends" / "index.json")
    store.write(BackendRegistry(processes={instance.process_id: instance for instance in instances}))
    return store


def _write_litellm_config(forge_home: Path) -> Path:
    config_path = forge_home / "backends" / "litellm" / "config.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("model_list: []\n")
    return config_path


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


def test_list_json_includes_static_sources_and_managed_process(
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
            processes={
                "litellm-4000": ManagedBackendProcess(
                    process_id="litellm-4000",
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
    payload = _json_output(result)
    assert all({"backend_id", "source_id", "runtime_instance"}.isdisjoint(item) for item in payload)
    records = {item["backend_instance_id"]: item for item in payload}
    assert records["openrouter"]["kind"] == "remote"
    assert records["openrouter"]["endpoint"]["env_var"] == "OPENROUTER_BASE_URL"
    assert records["openrouter"]["managed_process"] is None
    assert records["litellm-gemini-local"]["kind"] == "local"
    gemini_process = records["litellm-gemini-local"]["managed_process"]
    assert gemini_process["process_id"] == "litellm-4000"
    assert "backend_id" not in gemini_process
    assert records["litellm-gemini-local"]["health"] == "healthy"
    # A gemini-only config means only one source matches, so the instance is not shared.
    assert records["litellm-gemini-local"]["managed_process"]["shared_with"] == []
    assert records["litellm-openai-local"]["managed_process"] is None
    assert records["litellm-anthropic-local"]["managed_process"] is None

    registry = store.read()
    assert set(registry.processes) == {"litellm-4000"}


def test_list_json_marks_shared_managed_process(
    runner: CliRunner,
    forge_home: Path,
) -> None:
    """A multi-provider config mirrors the shipped default: one litellm-4000 process
    serves both Gemini and OpenAI, so every local source backed by it (Gemini, OpenAI,
    and the OpenAI-credentialed codex-responses source) matches the single process and
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
            processes={
                "litellm-4000": ManagedBackendProcess(
                    process_id="litellm-4000",
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
    records = {item["backend_instance_id"]: item for item in _json_output(result)}

    gemini = records["litellm-gemini-local"]["managed_process"]
    openai = records["litellm-openai-local"]["managed_process"]
    # Both sources are backed by the single running process.
    assert gemini["process_id"] == "litellm-4000"
    assert openai["process_id"] == "litellm-4000"
    # Each row names the sibling sources it shares the process with (catalog order),
    # never itself. codex-responses-local is an OpenAI-credentialed co-tenant on 4000.
    assert gemini["shared_with"] == ["litellm-openai-local", "codex-responses-local"]
    assert openai["shared_with"] == ["litellm-gemini-local", "codex-responses-local"]
    # anthropic-local is not in the config, so it stays unmatched.
    assert records["litellm-anthropic-local"]["managed_process"] is None
    # The shared process is still a single registry entry, not duplicated.
    assert set(store.read().processes) == {"litellm-4000"}


def test_list_human_marks_shared_managed_process(runner: CliRunner, forge_home: Path) -> None:
    """The human table flags a shared managed process in the PROCESS column."""
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
            processes={
                "litellm-4000": ManagedBackendProcess(
                    process_id="litellm-4000",
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


def test_list_human_shows_backends_even_without_instances(runner: CliRunner, forge_home: Path) -> None:
    result = runner.invoke(main, _backend_args("list"))

    assert result.exit_code == 0
    assert "Forge Model Backends" in result.output
    assert "openrouter" in result.output
    assert "litellm-remote" in result.output
    assert "No backends found" not in result.output


def test_list_human_shows_unmatched_managed_process_without_backend_match(
    runner: CliRunner,
    forge_home: Path,
) -> None:
    store = BackendRegistryStore(forge_home / "backends" / "index.json")
    store.write(
        BackendRegistry(
            processes={
                "litellm-4000": ManagedBackendProcess(
                    process_id="litellm-4000",
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
    assert "Unmatched Managed Processes" in result.output
    assert "litellm-4000" in result.output

    json_result = runner.invoke(main, _backend_args("list", "--json"))
    assert json_result.exit_code == 0
    records = {item["backend_instance_id"]: item for item in _json_output(json_result)}
    assert records["litellm-gemini-local"]["managed_process"] is None
    assert records["litellm-openai-local"]["managed_process"] is None
    assert records["litellm-anthropic-local"]["managed_process"] is None


def test_show_remote_source_details(runner: CliRunner, forge_home: Path) -> None:
    result = runner.invoke(main, _backend_args("show", "openrouter"))

    assert result.exit_code == 0
    assert "Backend:" in result.output
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
    assert BackendRegistryStore(forge_home / "backends" / "index.json").read().processes == {}


def test_delete_remote_source_has_intentional_error(runner: CliRunner, forge_home: Path) -> None:
    result = runner.invoke(main, _backend_args("delete", "openrouter", "--yes"))

    assert result.exit_code == 1
    assert "remote" in result.output
    assert "no local config" in result.output
    assert BackendRegistryStore(forge_home / "backends" / "index.json").read().processes == {}


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


def test_stop_process_id_stops_process_and_keeps_config(
    runner: CliRunner,
    forge_home: Path,
) -> None:
    config_path = _write_litellm_config(forge_home)
    store = _write_backend_registry(forge_home, _managed_process(pid=12345))

    with patch("forge.backend.adapters.litellm.os.kill") as kill:
        result = runner.invoke(main, _backend_args("stop", "litellm-4000"))

    assert result.exit_code == 0
    assert "Stopped" in result.output
    assert "litellm-4000" in result.output
    kill.assert_called_once_with(12345, 15)
    assert store.read().processes == {}
    assert config_path.exists()


def test_stop_multiple_process_ids_continues_after_failure(
    runner: CliRunner,
    forge_home: Path,
) -> None:
    store = _write_backend_registry(forge_home, _managed_process(pid=12345))

    with patch("forge.backend.adapters.litellm.os.kill"):
        result = runner.invoke(main, _backend_args("stop", "litellm-4000", "missing-9999"))

    assert result.exit_code == 1
    assert "Stopped" in result.output
    assert "Unknown managed process 'missing-9999'" in result.output
    assert "1 stopped, 1 failed" in result.output
    assert store.read().processes == {}


def test_stop_all_yes_stops_every_process_and_keeps_configs(
    runner: CliRunner,
    forge_home: Path,
) -> None:
    config_path = _write_litellm_config(forge_home)
    store = _write_backend_registry(
        forge_home,
        _managed_process(pid=12345),
        _managed_process("litellm-4001", port=4001, pid=12346),
    )

    with patch("forge.backend.adapters.litellm.os.kill") as kill:
        result = runner.invoke(main, _backend_args("stop", "--all", "--yes"))

    assert result.exit_code == 0
    assert "About to stop" in result.output
    assert "litellm-4000" in result.output
    assert "litellm-4001" in result.output
    assert "2 stopped" in result.output
    assert kill.call_count == 2
    assert store.read().processes == {}
    assert config_path.exists()


def test_stop_all_unregisters_pidless_process(
    runner: CliRunner,
    forge_home: Path,
) -> None:
    store = _write_backend_registry(forge_home, _managed_process(pid=None))

    with patch("forge.backend.adapters.litellm.os.kill") as kill:
        result = runner.invoke(main, _backend_args("stop", "--all", "--yes"))

    assert result.exit_code == 0
    assert "no process was killed" in result.output
    kill.assert_not_called()
    assert store.read().processes == {}


def test_stop_all_empty_registry_is_noop(runner: CliRunner, forge_home: Path) -> None:
    result = runner.invoke(main, _backend_args("stop", "--all"))

    assert result.exit_code == 0
    assert "No managed processes to stop" in result.output


def test_stop_all_conflicts_with_explicit_targets(runner: CliRunner, forge_home: Path) -> None:
    _write_backend_registry(forge_home, _managed_process())

    result = runner.invoke(main, _backend_args("stop", "litellm-4000", "--all"))

    assert result.exit_code == 1
    assert "Cannot combine --all with explicit managed process IDs" in result.output


def test_stop_requires_target_or_all(runner: CliRunner, forge_home: Path) -> None:
    result = runner.invoke(main, _backend_args("stop"))

    assert result.exit_code == 1
    assert "Provide managed process ID(s) or use --all" in result.output
    assert "forge model backend list" in result.output


def test_stop_rejects_local_source_without_stopping_shared_process(
    runner: CliRunner,
    forge_home: Path,
) -> None:
    store = _write_backend_registry(forge_home, _managed_process(pid=12345))

    with patch("forge.backend.adapters.litellm.os.kill") as kill:
        result = runner.invoke(main, _backend_args("stop", "litellm-openai-local"))

    assert result.exit_code == 1
    assert "not a managed process id" in result.output
    assert "forge model backend list" in result.output
    kill.assert_not_called()
    assert set(store.read().processes) == {"litellm-4000"}


def test_stop_rejects_bare_adapter_without_legacy_port_resolution(
    runner: CliRunner,
    forge_home: Path,
) -> None:
    store = _write_backend_registry(forge_home, _managed_process(pid=12345))

    with patch("forge.backend.adapters.litellm.os.kill") as kill:
        result = runner.invoke(main, _backend_args("stop", "litellm"))

    assert result.exit_code == 1
    assert "Backend adapter 'litellm' is not a managed process id" in result.output
    assert "forge model backend list" in result.output
    kill.assert_not_called()
    assert set(store.read().processes) == {"litellm-4000"}


def test_stop_port_option_is_clean_break(runner: CliRunner, forge_home: Path) -> None:
    result = runner.invoke(main, _backend_args("stop", "litellm", "--port", "4000"))

    assert result.exit_code == 2
    assert "No such option" in result.output
    assert "--port" in result.output


def test_start_process_id_stays_config_oriented(runner: CliRunner, forge_home: Path) -> None:
    store = _write_backend_registry(forge_home, _managed_process())

    result = runner.invoke(main, _backend_args("start", "litellm-4000"))

    assert result.exit_code == 1
    assert "Unknown backend or adapter 'litellm-4000'" in result.output
    assert set(store.read().processes) == {"litellm-4000"}


def test_test_auth_missing_credential_is_secret_free_json(runner: CliRunner, forge_home: Path) -> None:
    result = runner.invoke(main, _backend_args("test-auth", "openrouter", "--json"))

    assert result.exit_code == 1
    payload = _json_output(result)
    assert "backend_id" not in payload
    assert "source_id" not in payload
    assert payload["backend_instance_id"] == "openrouter"
    assert payload["auth_status"] == "missing"
    assert payload["missing_required_env_vars"] == ["OPENROUTER_API_KEY"]
    assert payload["probe"]["status"] == "skipped"
    assert "sk-" not in result.output


def test_test_auth_unique_backend_kind_shorthand_resolves(
    runner: CliRunner,
    forge_home: Path,
) -> None:
    result = runner.invoke(main, _backend_args("test-auth", "openai", "--json"))

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["backend_instance_id"] == "chatgpt"
    assert payload["probe"]["status"] == "skipped"


def test_test_auth_ambiguous_backend_kind_fails_loudly(
    runner: CliRunner,
    forge_home: Path,
) -> None:
    result = runner.invoke(main, _backend_args("test-auth", "anthropic", "--json"))

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Ambiguous backend instance shorthand 'anthropic'" in result.stderr
    assert "Use a concrete backend instance id" in result.stderr


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
    assert "Unknown backend or adapter 'foobar'" in result.output
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


def test_delete_process_id_points_to_stop(
    runner: CliRunner,
    forge_home: Path,
) -> None:
    _write_backend_registry(forge_home, _managed_process())

    result = runner.invoke(main, _backend_args("delete", "litellm-4000"))

    assert result.exit_code == 1
    assert "managed process id" in result.output
    assert "forge model backend stop litellm-4000" in result.output


def test_delete_port_option_is_clean_break(runner: CliRunner, forge_home: Path) -> None:
    result = runner.invoke(main, _backend_args("delete", "litellm", "--port", "4000"))

    assert result.exit_code == 2
    assert "No such option" in result.output
    assert "--port" in result.output


def test_delete_adapter_config_stops_matching_processes_first(
    runner: CliRunner,
    forge_home: Path,
) -> None:
    config_path = _write_litellm_config(forge_home)
    store = _write_backend_registry(
        forge_home,
        _managed_process(pid=12345),
        _managed_process("litellm-4001", port=4001, pid=12346),
    )

    with patch("forge.backend.adapters.litellm.os.kill") as kill:
        result = runner.invoke(main, _backend_args("delete", "litellm", "--yes"))

    assert result.exit_code == 0
    assert "Stopped managed processes: litellm-4000, litellm-4001" in result.output
    assert "Deleted" in result.output
    assert kill.call_count == 2
    assert store.read().processes == {}
    assert not config_path.parent.exists()


def test_backend_group_help_defines_id_spaces(runner: CliRunner) -> None:
    result = runner.invoke(main, _backend_args("--help"))

    assert result.exit_code == 0
    assert "Backend: openrouter" in result.output
    assert "Managed process: litellm-4000" in result.output
    assert "Adapter: litellm" in result.output


def test_backend_leaf_help_examples_are_valid_id_spaces(runner: CliRunner) -> None:
    show_help = runner.invoke(main, _backend_args("show", "--help"))
    test_auth_help = runner.invoke(main, _backend_args("test-auth", "--help"))
    reconcile_help = runner.invoke(main, _backend_args("reconcile", "--help"))
    start_help = runner.invoke(main, _backend_args("start", "--help"))
    stop_help = runner.invoke(main, _backend_args("stop", "--help"))
    delete_help = runner.invoke(main, _backend_args("delete", "--help"))

    assert show_help.exit_code == 0
    assert "BACKEND_OR_PROCESS" in show_help.output
    assert "forge model backend show openrouter" in show_help.output
    assert "forge model backend show litellm-4000" in show_help.output
    assert test_auth_help.exit_code == 0
    assert "BACKEND" in test_auth_help.output
    assert "SOURCE_ID" not in test_auth_help.output
    assert "forge model backend test-auth openrouter" in test_auth_help.output
    assert reconcile_help.exit_code == 0
    assert "BACKEND" in reconcile_help.output
    assert "SOURCE_ID" not in reconcile_help.output
    assert "forge model backend reconcile openrouter --request-id" in reconcile_help.output
    reconcile_text = _normalized_output(reconcile_help)
    assert "forge model backend list" in reconcile_text
    assert "backends" in reconcile_text
    assert start_help.exit_code == 0
    assert "BACKEND_OR_ADAPTER" in start_help.output
    assert "forge model backend start litellm-openai-local" in start_help.output
    assert "forge model backend start litellm --port 4000" in start_help.output
    assert "backend names use their default port unless overridden" in start_help.output
    assert stop_help.exit_code == 0
    assert "PROCESS_ID..." in stop_help.output
    assert "RUNTIME_ID..." not in stop_help.output
    assert "forge model backend list" in stop_help.output
    assert "--port" not in stop_help.output
    assert delete_help.exit_code == 0
    assert "--port" not in delete_help.output


def test_backend_help_does_not_label_processes_as_runtime(runner: CliRunner) -> None:
    help_commands = [
        _backend_args("--help"),
        _backend_args("list", "--help"),
        _backend_args("show", "--help"),
        _backend_args("start", "--help"),
        _backend_args("stop", "--help"),
        _backend_args("delete", "--help"),
    ]

    for args in help_commands:
        result = runner.invoke(main, args)
        assert result.exit_code == 0
        help_text = result.output.lower()
        assert "runtime instance" not in help_text
        assert "runtime id" not in help_text


_SOURCE_RECORD_KEYS = {
    "backend_instance_id",
    "kind",
    "provider",
    "endpoint",
    "required_credentials",
    "credentials",
    "auth_status",
    "missing_required_env_vars",
    "health",
    "has_lifecycle",
    "managed_process",
}

_REGISTRY_FALLBACK_KEYS = {
    "managed_process_id",
    "found",
    "adapter_type",
    "managed_process",
    "config_path",
}


def test_show_json_configured_backend_emits_source_record(
    runner: CliRunner,
    forge_home: Path,
) -> None:
    """show <backend> --json dispatches through _source_record (path 1).

    A built-in backend like openrouter resolves via _source_for_identifier, so the
    payload carries the full source-record shape, not the registry-fallback shape.
    """
    result = runner.invoke(main, _backend_args("show", "openrouter", "--json"))

    assert result.exit_code == 0
    payload = _json_output(result)
    assert set(payload) == _SOURCE_RECORD_KEYS
    assert payload["backend_instance_id"] == "openrouter"
    assert payload["kind"] == "remote"
    # Remote backend has no local lifecycle, so no managed process is matched.
    assert payload["managed_process"] is None
    assert payload["has_lifecycle"] is False
    assert isinstance(payload["credentials"], list)
    assert "OPENROUTER_API_KEY" in payload["missing_required_env_vars"]


def test_show_json_unique_backend_kind_shorthand_uses_source_record(
    runner: CliRunner,
    forge_home: Path,
) -> None:
    result = runner.invoke(main, _backend_args("show", "openai", "--json"))

    assert result.exit_code == 0
    payload = _json_output(result)
    assert set(payload) == _SOURCE_RECORD_KEYS
    assert payload["backend_instance_id"] == "chatgpt"
    assert payload["endpoint"]["kind"] == "runtime_native"


def test_show_json_ambiguous_backend_kind_fails_loudly(
    runner: CliRunner,
    forge_home: Path,
) -> None:
    result = runner.invoke(main, _backend_args("show", "anthropic", "--json"))

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Ambiguous backend instance shorthand 'anthropic'" in result.stderr
    assert "Use a concrete backend instance id" in result.stderr


def test_show_json_registry_only_fallback_when_not_a_source(
    runner: CliRunner,
    forge_home: Path,
) -> None:
    """show <process-id> --json uses the registry fallback shape (path 2).

    litellm-4000 is a registry process_id but not a model source, so the command
    falls through to the registry-only branch and reports found=true with a
    populated managed_process record.
    """
    store = BackendRegistryStore(forge_home / "backends" / "index.json")
    store.write(
        BackendRegistry(
            processes={
                "litellm-4000": ManagedBackendProcess(
                    process_id="litellm-4000",
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
    assert payload["managed_process_id"] == "litellm-4000"
    assert payload["found"] is True
    assert payload["adapter_type"] == "litellm"
    process = payload["managed_process"]
    assert process is not None
    assert process["process_id"] == "litellm-4000"
    assert process["adapter_type"] == "litellm"
    assert process["port"] == 4000
    assert process["status"] == "healthy"
    assert process["alive"] is False


def test_show_json_unknown_id_reports_not_found(
    runner: CliRunner,
    forge_home: Path,
) -> None:
    """show <unknown-id> --json reports found=false with empty process/config (path 3)."""
    result = runner.invoke(main, _backend_args("show", "nope-9999", "--json"))

    assert result.exit_code == 0
    payload = _json_output(result)
    assert set(payload) == _REGISTRY_FALLBACK_KEYS
    assert payload["managed_process_id"] == "nope-9999"
    assert payload["found"] is False
    # rsplit("-", 1) on "nope-9999" yields adapter "nope".
    assert payload["adapter_type"] == "nope"
    assert payload["managed_process"] is None
    assert payload["config_path"] is None


def test_list_json_renders_runtime_native_source_as_runtime_owned(
    runner: CliRunner,
    forge_home: Path,
) -> None:
    """A runtime_native source (chatgpt) renders honestly: openai provider, runtime_native
    endpoint, auth_status=runtime_native, and runtime-owned health -- never a misleading
    'configured'/'unprobed' from the empty credential set."""
    result = runner.invoke(main, _backend_args("list", "--json"))

    assert result.exit_code == 0
    records = {item["backend_instance_id"]: item for item in _json_output(result)}
    chatgpt = records["chatgpt"]
    assert chatgpt["provider"] == "openai"
    assert chatgpt["kind"] == "remote"
    assert chatgpt["endpoint"]["kind"] == "runtime_native"
    assert chatgpt["auth_status"] == "runtime_native"
    assert chatgpt["health"] == "runtime-owned"
    assert chatgpt["required_credentials"] == []
    assert chatgpt["managed_process"] is None


def test_test_auth_runtime_native_source_is_skipped_not_failed(
    runner: CliRunner,
    forge_home: Path,
) -> None:
    """`test-auth chatgpt` reports runtime-native auth as skipped (verify via codex preflight)
    and exits 0 -- a subscription backend is not a missing-credential failure."""
    result = runner.invoke(main, _backend_args("test-auth", "chatgpt", "--json"))

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["provider"] == "openai"
    assert payload["auth_status"] == "runtime_native"
    assert payload["missing_required_env_vars"] == []
    assert payload["probe"]["status"] == "skipped"
    assert "forge runtime preflight codex" in payload["probe"]["detail"]


def test_list_json_renders_claude_max_as_runtime_owned(
    runner: CliRunner,
    forge_home: Path,
) -> None:
    """claude-max renders like chatgpt: anthropic provider, runtime_native endpoint,
    auth_status=runtime_native, runtime-owned health, no Forge credential."""
    result = runner.invoke(main, _backend_args("list", "--json"))

    assert result.exit_code == 0
    records = {item["backend_instance_id"]: item for item in _json_output(result)}
    claude_max = records["claude-max"]
    assert claude_max["provider"] == "anthropic"
    assert claude_max["kind"] == "remote"
    assert claude_max["endpoint"]["kind"] == "runtime_native"
    assert claude_max["auth_status"] == "runtime_native"
    assert claude_max["health"] == "runtime-owned"
    assert claude_max["required_credentials"] == []
    assert claude_max["managed_process"] is None


def test_test_auth_claude_max_skipped_with_claude_hint_not_codex(
    runner: CliRunner,
    forge_home: Path,
) -> None:
    """`test-auth claude-max` skips (runtime-owned) and points at the Claude login,
    never the codex preflight -- the hint derives from reachable_via."""
    result = runner.invoke(main, _backend_args("test-auth", "claude-max", "--json"))

    assert result.exit_code == 0
    payload = _json_output(result)
    assert payload["provider"] == "anthropic"
    assert payload["auth_status"] == "runtime_native"
    assert payload["missing_required_env_vars"] == []
    assert payload["probe"]["status"] == "skipped"
    detail = payload["probe"]["detail"]
    assert "codex" not in detail
    assert "claude" in detail.lower()
