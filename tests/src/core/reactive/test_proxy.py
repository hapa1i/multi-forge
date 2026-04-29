"""Tests for forge.core.reactive.proxy."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from forge.core.reactive.proxy import check_proxy_reachable, lookup_proxy_base_url
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


class TestCheckProxyReachable:
    """Tests for check_proxy_reachable() — resolve + HTTP health check."""

    def test_resolves_and_healthy(self):
        entry = _entry()
        registry = ProxyRegistry(proxies={"my-proxy": entry})
        mock_store = _mock_store_returning(registry)

        with (
            patch("forge.proxy.proxies.ProxyRegistryStore", mock_store),
            patch(
                "forge.proxy.proxy_orchestrator.check_proxy_health",
                return_value=True,
            ) as mock_health,
        ):
            reachable, reason, url = check_proxy_reachable("my-proxy")

        assert reachable is True
        assert reason == ""
        assert url == "http://localhost:8085"
        mock_health.assert_called_once_with(
            base_url="http://localhost:8085",
            expected_template="litellm-openai",
            expected_proxy_id="my-proxy",
            timeout_s=1.0,
        )

    def test_resolve_fails(self):
        registry = ProxyRegistry(proxies={})
        mock_store = _mock_store_returning(registry)

        with patch("forge.proxy.proxies.ProxyRegistryStore", mock_store):
            reachable, reason, url = check_proxy_reachable("nonexistent")

        assert reachable is False
        assert "nonexistent" in reason
        assert url is None

    def test_resolved_but_not_healthy(self):
        entry = _entry()
        registry = ProxyRegistry(proxies={"my-proxy": entry})
        mock_store = _mock_store_returning(registry)

        with (
            patch("forge.proxy.proxies.ProxyRegistryStore", mock_store),
            patch(
                "forge.proxy.proxy_orchestrator.check_proxy_health",
                return_value=False,
            ),
        ):
            reachable, reason, url = check_proxy_reachable("my-proxy")

        assert reachable is False
        assert "not responding" in reason
        assert url == "http://localhost:8085"

    def test_registry_corrupted(self):
        mock_store = MagicMock()
        mock_store.return_value.read.side_effect = RuntimeError("corrupted")

        with patch("forge.proxy.proxies.ProxyRegistryStore", mock_store):
            reachable, reason, url = check_proxy_reachable("any-proxy")

        assert reachable is False
        assert "Registry error" in reason
        assert url is None

    def test_custom_timeout(self):
        entry = _entry()
        registry = ProxyRegistry(proxies={"my-proxy": entry})
        mock_store = _mock_store_returning(registry)

        with (
            patch("forge.proxy.proxies.ProxyRegistryStore", mock_store),
            patch(
                "forge.proxy.proxy_orchestrator.check_proxy_health",
                return_value=True,
            ) as mock_health,
        ):
            check_proxy_reachable("my-proxy", timeout_s=0.5)

        assert mock_health.call_args.kwargs["timeout_s"] == 0.5
