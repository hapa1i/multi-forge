"""Regression: inert user-owned config gets one warning before later rejection."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

import pytest
import yaml

import forge.proxy.proxy_orchestrator as orchestrator
from forge.config import load_config
from forge.config import schema as schema_module
from forge.config.loader import (
    _proxy_instance_to_forge_config,
    load_proxy_instance_config_from_dict,
)
from forge.config.schema import ForgeConfig
from forge.session.store import MANIFEST_FILENAME, get_manifest_path

pytestmark = pytest.mark.regression


@pytest.fixture(autouse=True)
def _reset_deprecation_warnings() -> Iterator[None]:
    schema_module._warned_deprecated_config_fields.clear()
    yield
    schema_module._warned_deprecated_config_fields.clear()


def _valid_proxy(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "proxy_format": 1,
        "template": "litellm-openai",
        "template_digest": "sha256:test",
        "provider": "litellm",
        "proxy_endpoint": "http://localhost:8089",
        "port": 8089,
        "upstream_base_url": "http://localhost:4000",
        "tiers": {"haiku": "h", "sonnet": "s", "opus": "o"},
    }
    data.update(overrides)
    return data


def test_omitted_compatibility_fields_are_silent(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="forge.config.schema"):
        ForgeConfig.from_dict({"proxy": {"litellm": {}}, "session": {}})
        load_proxy_instance_config_from_dict(_valid_proxy(provider_settings={"error_hints": True}))

    assert "Deprecated config key" not in caplog.text


def test_explicit_provider_fields_warn_even_at_old_defaults(caplog: pytest.LogCaptureFixture) -> None:
    data = {
        "proxy": {
            "litellm": {
                "enable_preamble": False,
                "openai_api_mode": "auto",
            }
        }
    }

    with caplog.at_level(logging.WARNING, logger="forge.config.schema"):
        config = ForgeConfig.from_dict(data)

    assert config.proxy.litellm.enable_preamble is False
    assert config.proxy.litellm.openai_api_mode == "auto"
    assert "proxy.litellm.enable_preamble" in caplog.text
    assert "proxy.litellm.openai_api_mode" in caplog.text
    assert "has no effect" in caplog.text
    assert "Remove it" in caplog.text


def test_custom_template_boundary_warns_and_remains_readable(
    tmp_path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    template_dir = tmp_path / "templates"
    template_dir.mkdir()
    (template_dir / "legacy.yaml").write_text(
        "proxy:\n"
        "  family: openai\n"
        "  preferred_provider: openrouter\n"
        "  backend: openrouter\n"
        "  default_port: 8096\n"
        "  openrouter:\n"
        "    enable_preamble: false\n"
        "    openai_api_mode: auto\n"
        "    tiers:\n"
        "      haiku: openai/gpt-5.4-mini\n"
        "      sonnet: openai/gpt-5.6-sol\n"
        "      opus: openai/gpt-5.6-sol\n",
        encoding="utf-8",
    )

    with caplog.at_level(logging.WARNING, logger="forge.config.schema"):
        config = load_config(template="legacy")

    assert config.proxy.openrouter.enable_preamble is False
    assert config.proxy.openrouter.openai_api_mode == "auto"
    assert "proxy.openrouter.enable_preamble" in caplog.text
    assert "proxy.openrouter.openai_api_mode" in caplog.text


def test_explicit_manifest_filename_warns_but_cannot_change_path(tmp_path, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="forge.config.schema"):
        config = ForgeConfig.from_dict({"session": {"manifest_filename": "custom.json"}})

    assert config.session.manifest_filename == "custom.json"
    assert "session.manifest_filename" in caplog.text
    assert "MANIFEST_FILENAME" in caplog.text
    assert get_manifest_path(tmp_path, "example").name == MANIFEST_FILENAME == "forge.session.json"


def test_legacy_proxy_mode_loads_once_without_runtime_transport_effect(
    caplog: pytest.LogCaptureFixture,
) -> None:
    raw = _valid_proxy(provider_settings={"openai_api_mode": "responses", "error_hints": True})

    with caplog.at_level(logging.WARNING, logger="forge.config.schema"):
        first = load_proxy_instance_config_from_dict(raw)
        second = load_proxy_instance_config_from_dict(raw)

    assert first.provider_settings["openai_api_mode"] == "responses"
    assert second.provider_settings["openai_api_mode"] == "responses"
    assert caplog.text.count("provider_settings.openai_api_mode") == 1

    runtime = _proxy_instance_to_forge_config(first)
    assert runtime.proxy.litellm.openai_api_mode == "auto"
    assert runtime.proxy.litellm.error_hints is True


def test_proxy_creation_does_not_reemit_deprecated_mode(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    template_config = orchestrator.load_config(template="litellm-openai")
    template_config.proxy.litellm.openai_api_mode = "responses"
    template_config.proxy.litellm.error_hints = True
    monkeypatch.setattr(orchestrator, "load_config", lambda *_args, **_kwargs: template_config)

    written = orchestrator.create_proxy_file(
        proxy_id="compatibility-test",
        template="litellm-openai",
        base_url="http://localhost:8089",
        port=8089,
        upstream_base_url="http://localhost:4000",
    )
    data = yaml.safe_load(written.read_text(encoding="utf-8"))

    assert data["provider_settings"] == {"error_hints": True}
