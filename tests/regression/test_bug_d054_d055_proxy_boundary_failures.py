"""Regression: reject malformed proxy transport fields and clean up failed spawn captures.

D054: the direct template-to-instance fields were structurally wired but not validated, so malformed values survived
strict loading and failed later in request/session consumers.

D055: ``_spawn_proxy_process`` left its stderr descriptor and path behind when ``Popen`` failed, and the raw
``OSError`` escaped the orchestrator's ``ProxyStartError`` contract.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import forge.proxy.proxy_orchestrator as orchestrator
from forge.config.dataclass_utils import dict_to_dataclass
from forge.config.loader import load_proxy_instance_config_from_dict
from forge.config.schema import ForgeConfig
from forge.proxy.proxy_orchestrator import ProxyStartError

pytestmark = pytest.mark.regression

_VALID_PROXY: dict[str, Any] = {
    "proxy_format": 1,
    "template": "openrouter-anthropic",
    "template_digest": "sha256:test",
    "provider": "openrouter",
    "proxy_endpoint": "http://localhost:8085",
    "port": 8085,
    "upstream_base_url": "https://openrouter.ai/api/v1",
    "tiers": {
        "haiku": "anthropic/claude-haiku-4-5",
        "sonnet": "anthropic/claude-sonnet-4-6",
        "opus": "anthropic/claude-opus-5",
    },
}

_MALFORMED_DIRECT_FIELDS: tuple[tuple[str, object], ...] = (
    ("tool_prefixes_to_ignore", 42),
    ("tool_prefixes_to_ignore", ["mcp__*", 42]),
    ("model_alternatives", 42),
    ("model_alternatives", {1: {"claude-opus-4-8": "anthropic/claude-opus-4.8"}}),
    ("model_alternatives", {"opus": []}),
    ("model_alternatives", {"opus": {1: "anthropic/claude-opus-4.8"}}),
    ("model_alternatives", {"opus": {"claude-opus-4-8": 42}}),
    ("model_alternatives", {"opus": {"": "anthropic/claude-opus-4.8"}}),
    ("model_alternatives", {"opus": {"claude-opus-4-8": ""}}),
    (
        "model_alternatives",
        {
            "opus": {
                "gemini-3.7-flash": "vertex_ai/gemini-3.7-flash-a",
                "vertex_ai/gemini-3.7-flash": "vertex_ai/gemini-3.7-flash-b",
            }
        },
    ),
    ("prompt_caching", 42),
    ("prompt_caching", "sometimes"),
    ("auto_cache_min_tokens", "4096"),
    ("auto_cache_min_tokens", True),
)


def _template_data(field: str, value: object) -> dict[str, Any]:
    proxy: dict[str, Any] = {
        "family": "anthropic",
        "preferred_provider": "openrouter",
        "openrouter": {},
    }
    if field == "tool_prefixes_to_ignore":
        proxy[field] = value
    else:
        proxy["openrouter"][field] = value
    return {"proxy": proxy}


@pytest.mark.parametrize(("field", "value"), _MALFORMED_DIRECT_FIELDS)
def test_d054_template_rejects_malformed_direct_field(field: str, value: object) -> None:
    with pytest.raises(ValueError, match=field):
        dict_to_dataclass(ForgeConfig, _template_data(field, value), strict=True)


@pytest.mark.parametrize(("field", "value"), _MALFORMED_DIRECT_FIELDS)
def test_d054_instance_rejects_malformed_direct_field(field: str, value: object) -> None:
    with pytest.raises(ValueError, match=field):
        load_proxy_instance_config_from_dict({**_VALID_PROXY, field: value})


def test_d054_valid_direct_fields_survive_template_loading() -> None:
    config = dict_to_dataclass(
        ForgeConfig,
        {
            "proxy": {
                "family": "anthropic",
                "preferred_provider": "openrouter",
                "tool_prefixes_to_ignore": ["mcp__*"],
                "openrouter": {
                    "model_alternatives": {"opus": {"claude-opus-4-8": "anthropic/claude-opus-4.8"}},
                    "prompt_caching": "auto_inject",
                    "auto_cache_min_tokens": 4096,
                },
            }
        },
        strict=True,
    )

    assert config.proxy.tool_prefixes_to_ignore == ["mcp__*"]
    assert config.proxy.openrouter.model_alternatives["opus"]["claude-opus-4-8"] == "anthropic/claude-opus-4.8"
    assert config.proxy.openrouter.prompt_caching == "auto_inject"
    assert config.proxy.openrouter.auto_cache_min_tokens == 4096


def test_d054_valid_direct_fields_survive_instance_loading() -> None:
    config = load_proxy_instance_config_from_dict(
        {
            **_VALID_PROXY,
            "tool_prefixes_to_ignore": ["mcp__*"],
            "model_alternatives": {"opus": {"claude-opus-4-8": "anthropic/claude-opus-4.8"}},
            "prompt_caching": "auto_inject",
            "auto_cache_min_tokens": 4096,
        }
    )

    assert config.tool_prefixes_to_ignore == ["mcp__*"]
    assert config.model_alternatives["opus"]["claude-opus-4-8"] == "anthropic/claude-opus-4.8"
    assert config.prompt_caching == "auto_inject"
    assert config.auto_cache_min_tokens == 4096


def test_d054_conflicting_catalog_aliases_report_the_tier_and_identity() -> None:
    alternatives = {
        "opus": {
            "gemini-3.7-flash": "vertex_ai/gemini-3.7-flash-a",
            "vertex_ai/gemini-3.7-flash": "vertex_ai/gemini-3.7-flash-b",
        }
    }

    with pytest.raises(
        ValueError,
        match=r"model_alternatives\.opus: .* both resolve to catalog model 'gemini-3\.7-flash'.*different backend",
    ):
        load_proxy_instance_config_from_dict({**_VALID_PROXY, "model_alternatives": alternatives})


def test_d054_equivalent_catalog_aliases_may_repeat_the_same_backend() -> None:
    backend = "vertex_ai/gemini-3.7-flash"
    config = load_proxy_instance_config_from_dict(
        {
            **_VALID_PROXY,
            "model_alternatives": {
                "opus": {
                    "gemini-3.7-flash": backend,
                    "vertex_ai/gemini-3.7-flash": backend,
                }
            },
        }
    )

    assert config.model_alternatives["opus"] == {
        "gemini-3.7-flash": backend,
        "vertex_ai/gemini-3.7-flash": backend,
    }


def _inject_failed_spawn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, int | Path]:
    created: dict[str, int | Path] = {}
    real_mkstemp = tempfile.mkstemp

    def _tracking_mkstemp(*, suffix: str, prefix: str) -> tuple[int, str]:
        fd, path = real_mkstemp(suffix=suffix, prefix=prefix, dir=tmp_path)
        created.update(fd=fd, path=Path(path))
        return fd, path

    def _fail_popen(*_args: object, **_kwargs: object) -> subprocess.Popen[bytes]:
        raise OSError("injected spawn failure")

    monkeypatch.setattr(orchestrator, "_check_proxy_dependencies", lambda **_kwargs: None)
    monkeypatch.setattr(orchestrator, "os", SimpleNamespace(environ={}, close=os.close))
    monkeypatch.setattr(tempfile, "mkstemp", _tracking_mkstemp)
    monkeypatch.setattr(subprocess, "Popen", _fail_popen)
    return created


def _spawn() -> tuple[subprocess.Popen[bytes], Path]:
    return orchestrator._spawn_proxy_process(
        template="litellm-openai",
        host="127.0.0.1",
        port=8085,
        proxy_id="spawn-failure",
    )


def _cleanup_capture(created: dict[str, int | Path]) -> None:
    fd = created.get("fd")
    if isinstance(fd, int):
        try:
            os.close(fd)
        except OSError:
            pass
    path = created.get("path")
    if isinstance(path, Path):
        path.unlink(missing_ok=True)


def test_d055_failed_spawn_closes_and_removes_stderr_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = _inject_failed_spawn(tmp_path, monkeypatch)

    try:
        # The separate contract test pins the final exception type. Accept either
        # here so the unchanged-base run reaches the independent leak assertions.
        with pytest.raises((OSError, ProxyStartError), match="injected spawn failure"):
            _spawn()
        fd = created["fd"]
        path = created["path"]
        assert isinstance(fd, int)
        assert isinstance(path, Path)
        with pytest.raises(OSError):
            os.fstat(fd)
        assert not path.exists()
    finally:
        _cleanup_capture(created)


def test_d055_failed_spawn_raises_typed_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    created = _inject_failed_spawn(tmp_path, monkeypatch)

    try:
        with pytest.raises(ProxyStartError, match="Failed to start proxy process") as exc_info:
            _spawn()
        assert isinstance(exc_info.value.__cause__, OSError)
    finally:
        _cleanup_capture(created)
