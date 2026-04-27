"""Unit tests for strict proxy startup validation (B2.1.3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.proxy.proxy_startup import (
    ProxyStartupContext,
    ProxyStartupValidationError,
    validate_proxy_startup,
)


def _write_registry(*, path: Path, proxy_id: str, template: str, port: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        (
            "{\n"
            '  "version": 1,\n'
            '  "proxies": {\n'
            f'    "{proxy_id}": {{\n'
            f'      "proxy_id": "{proxy_id}",\n'
            f'      "template": "{template}",\n'
            f'      "base_url": "http://localhost:{port}",\n'
            f'      "port": {port}\n'
            "    }\n"
            "  }\n"
            "}\n"
        )
    )


def test_validate_proxy_startup_rejects_unregistered_proxy(
    mock_registry_path: Path,
) -> None:
    with pytest.raises(ProxyStartupValidationError, match=r"unregistered proxy"):
        validate_proxy_startup(ctx=ProxyStartupContext(proxy_id="proxy_missing", template="litellm-openai", port=8085))


def test_validate_proxy_startup_rejects_family_mismatch(
    mock_registry_path: Path,
) -> None:
    _write_registry(
        path=mock_registry_path,
        proxy_id="proxy_1",
        template="litellm-openai",
        port=8085,
    )

    with pytest.raises(ProxyStartupValidationError, match=r"template mismatch"):
        validate_proxy_startup(ctx=ProxyStartupContext(proxy_id="proxy_1", template="litellm-gemini", port=8085))


def test_validate_proxy_startup_rejects_port_mismatch(mock_registry_path: Path) -> None:
    _write_registry(
        path=mock_registry_path,
        proxy_id="proxy_1",
        template="litellm-openai",
        port=8085,
    )

    with pytest.raises(ProxyStartupValidationError, match=r"port mismatch"):
        validate_proxy_startup(ctx=ProxyStartupContext(proxy_id="proxy_1", template="litellm-openai", port=9999))


def test_validate_proxy_startup_allows_matching_registered_proxy(
    mock_registry_path: Path,
) -> None:
    _write_registry(
        path=mock_registry_path,
        proxy_id="proxy_1",
        template="litellm-openai",
        port=8085,
    )

    validate_proxy_startup(ctx=ProxyStartupContext(proxy_id="proxy_1", template="litellm-openai", port=8085))
