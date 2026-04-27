"""Tests for resolve_proxy() and resolve_proxy_optional()."""

from __future__ import annotations

import pytest

from forge.proxy.proxies import (
    AmbiguousProxyError,
    ProxyEntry,
    ProxyNotFoundError,
    ProxyRegistry,
    ProxyResolutionError,
    resolve_proxy,
    resolve_proxy_optional,
)


def _entry(
    proxy_id: str,
    template: str = "litellm-openai",
    status: str = "healthy",
    port: int = 8084,
) -> ProxyEntry:
    return ProxyEntry(
        proxy_id=proxy_id,
        template=template,
        base_url=f"http://localhost:{port}",
        port=port,
        status=status,
    )


def _registry(*entries: ProxyEntry) -> ProxyRegistry:
    return ProxyRegistry(proxies={e.proxy_id: e for e in entries})


# -- resolve_proxy: exact proxy_id match --


class TestResolveProxyById:
    def test_exact_match(self) -> None:
        entry = _entry("amber-lime")
        registry = _registry(entry)

        result = resolve_proxy(registry, "amber-lime")
        assert result is entry

    def test_exact_match_returns_stopped_proxy(self) -> None:
        """Exact proxy_id match returns entry regardless of status."""
        entry = _entry("amber-lime", status="stopped")
        registry = _registry(entry)

        result = resolve_proxy(registry, "amber-lime")
        assert result is entry

    def test_exact_match_takes_priority_over_template(self) -> None:
        """If proxy_id matches, template fallback is never attempted."""
        by_id = _entry("litellm-openai", template="something-else", port=8084)
        by_template = _entry("other-proxy", template="litellm-openai", port=8085)
        registry = _registry(by_id, by_template)

        result = resolve_proxy(registry, "litellm-openai")
        assert result is by_id


# -- resolve_proxy: template fallback --


class TestResolveProxyByTemplate:
    def test_single_active_match(self) -> None:
        entry = _entry("amber-lime", template="litellm-openai")
        registry = _registry(entry)

        result = resolve_proxy(registry, "litellm-openai")
        assert result is entry

    def test_single_active_among_inactive(self) -> None:
        """One active + one stopped with same template: returns the active one."""
        active = _entry("proxy-a", template="litellm-openai", status="healthy", port=8084)
        stopped = _entry("proxy-b", template="litellm-openai", status="stopped", port=8085)
        registry = _registry(active, stopped)

        result = resolve_proxy(registry, "litellm-openai")
        assert result is active

    def test_starting_counts_as_active(self) -> None:
        entry = _entry("proxy-a", template="litellm-openai", status="starting")
        registry = _registry(entry)

        result = resolve_proxy(registry, "litellm-openai")
        assert result is entry

    def test_ambiguous_active_raises(self) -> None:
        a = _entry("proxy-a", template="litellm-openai", status="healthy", port=8084)
        b = _entry("proxy-b", template="litellm-openai", status="healthy", port=8085)
        registry = _registry(a, b)

        with pytest.raises(AmbiguousProxyError) as exc_info:
            resolve_proxy(registry, "litellm-openai")

        err = exc_info.value
        assert err.name == "litellm-openai"
        assert set(err.proxy_ids) == {"proxy-a", "proxy-b"}
        assert "ambiguous" in str(err).lower()

    def test_all_inactive_raises_with_ids(self) -> None:
        a = _entry("proxy-a", template="litellm-openai", status="stopped", port=8084)
        b = _entry("proxy-b", template="litellm-openai", status="configured", port=8085)
        registry = _registry(a, b)

        with pytest.raises(ProxyNotFoundError) as exc_info:
            resolve_proxy(registry, "litellm-openai")

        err = exc_info.value
        assert err.name == "litellm-openai"
        assert set(err.inactive_ids) == {"proxy-a", "proxy-b"}
        assert "none are active" in str(err).lower()

    def test_no_match_at_all_raises(self) -> None:
        registry = _registry(_entry("unrelated", template="litellm-gemini"))

        with pytest.raises(ProxyNotFoundError) as exc_info:
            resolve_proxy(registry, "litellm-openai")

        err = exc_info.value
        assert err.inactive_ids == []
        assert "no proxy found" in str(err).lower()

    def test_empty_registry_raises(self) -> None:
        registry = _registry()

        with pytest.raises(ProxyNotFoundError):
            resolve_proxy(registry, "litellm-openai")


# -- resolve_proxy: status filtering --


class TestResolveProxyStatusFiltering:
    @pytest.mark.parametrize("status", ["healthy", "starting"])
    def test_routable_statuses_match(self, status: str) -> None:
        entry = _entry("proxy-a", template="tpl", status=status)
        registry = _registry(entry)

        assert resolve_proxy(registry, "tpl") is entry

    @pytest.mark.parametrize("status", ["stopped", "configured", "unhealthy", None])
    def test_non_routable_statuses_excluded(self, status: str | None) -> None:
        entry = _entry("proxy-a", template="tpl", status=status)  # type: ignore[arg-type]
        registry = _registry(entry)

        with pytest.raises(ProxyNotFoundError):
            resolve_proxy(registry, "tpl")


# -- resolve_proxy: error hierarchy --


class TestResolveProxyErrors:
    def test_errors_inherit_from_base(self) -> None:
        assert issubclass(ProxyNotFoundError, ProxyResolutionError)
        assert issubclass(AmbiguousProxyError, ProxyResolutionError)

    def test_not_found_message_no_inactive(self) -> None:
        err = ProxyNotFoundError("foo")
        assert "foo" in str(err)
        assert "proxy_id and template" in str(err)

    def test_not_found_message_with_inactive(self) -> None:
        err = ProxyNotFoundError("foo", inactive_ids=["a", "b"])
        assert "foo" in str(err)
        assert "none are active" in str(err)
        assert "a" in str(err)

    def test_ambiguous_message(self) -> None:
        err = AmbiguousProxyError("foo", ["a", "b"])
        assert "foo" in str(err)
        assert "a" in str(err)
        assert "2 active proxies" in str(err)
        assert "proxy_id" in str(err)


# -- resolve_proxy_optional --


class TestResolveProxyOptional:
    def test_returns_entry_on_match(self) -> None:
        entry = _entry("amber-lime")
        registry = _registry(entry)

        assert resolve_proxy_optional(registry, "amber-lime") is entry

    def test_returns_none_on_not_found(self) -> None:
        registry = _registry()

        assert resolve_proxy_optional(registry, "missing") is None

    def test_returns_none_on_ambiguous(self) -> None:
        a = _entry("proxy-a", template="tpl", status="healthy", port=8084)
        b = _entry("proxy-b", template="tpl", status="healthy", port=8085)
        registry = _registry(a, b)

        assert resolve_proxy_optional(registry, "tpl") is None

    def test_template_match_works(self) -> None:
        entry = _entry("proxy-a", template="litellm-openai")
        registry = _registry(entry)

        result = resolve_proxy_optional(registry, "litellm-openai")
        assert result is entry
