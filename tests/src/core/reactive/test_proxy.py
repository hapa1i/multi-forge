"""Tests for forge.core.reactive.proxy."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from forge.core.reactive.proxy import lookup_proxy_base_url
from forge.proxy.proxies import ProxyEntry, ProxyNotFoundError, ProxyRegistry


def _entry(
    proxy_id: str = "my-proxy",
    template: str = "litellm-openai",
    base_url: str = "http://localhost:8085",
    status: str = "healthy",
) -> ProxyEntry:
    return ProxyEntry(
        proxy_id=proxy_id,
        template=template,
        base_url=base_url,
        port=8085,
        status=status,
    )


def _mock_store_returning(registry: ProxyRegistry) -> MagicMock:
    mock_store = MagicMock()
    mock_store.return_value.read.return_value = registry
    return mock_store


class TestLookupProxyBaseUrl:
    def test_none_proxy_id_returns_none(self):
        assert lookup_proxy_base_url(None) is None

    def test_empty_string_proxy_id_returns_none(self):
        assert lookup_proxy_base_url("") is None

    def test_found_by_proxy_id_returns_base_url(self):
        entry = _entry()
        registry = ProxyRegistry(proxies={"my-proxy": entry})
        mock_store = _mock_store_returning(registry)

        result = _lookup_with_mock_store(mock_store)
        assert result == "http://localhost:8085"

    def test_found_by_template_name_returns_base_url(self):
        entry = _entry(proxy_id="amber-lime", template="litellm-openai")
        registry = ProxyRegistry(proxies={"amber-lime": entry})
        mock_store = _mock_store_returning(registry)

        result = _lookup_with_mock_store(mock_store, "litellm-openai")
        assert result == "http://localhost:8085"

    def test_template_match_raises_on_inactive(self):
        """Configured proxy name that resolves only to inactive entries raises."""
        entry = _entry(proxy_id="amber-lime", template="litellm-openai", status="stopped")
        registry = ProxyRegistry(proxies={"amber-lime": entry})
        mock_store = _mock_store_returning(registry)

        with pytest.raises(ProxyNotFoundError):
            _lookup_with_mock_store(mock_store, "litellm-openai")

    def test_missing_proxy_raises(self):
        """Configured proxy name that doesn't exist raises."""
        registry = ProxyRegistry(proxies={})
        mock_store = _mock_store_returning(registry)

        with pytest.raises(ProxyNotFoundError):
            _lookup_with_mock_store(mock_store, "nonexistent")

    def test_registry_read_error_propagates(self):
        """Registry read failures propagate to the caller."""
        mock_store = MagicMock()
        mock_store.return_value.read.side_effect = FileNotFoundError("no registry")

        with pytest.raises(FileNotFoundError):
            _lookup_with_mock_store(mock_store, "any-proxy")


def _lookup_with_mock_store(mock_store: MagicMock, proxy: str = "my-proxy") -> str | None:
    """Helper to patch ProxyRegistryStore at the lazy import site."""
    with patch(
        "forge.proxy.proxies.ProxyRegistryStore",
        mock_store,
    ):
        return lookup_proxy_base_url(proxy)
