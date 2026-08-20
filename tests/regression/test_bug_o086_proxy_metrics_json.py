"""O086 regressions for byte-safe, shape-stable proxy metrics JSON."""

from __future__ import annotations

import json
from typing import Any

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.cli.proxy import _ProxyInfo
from forge.proxy.proxies import ProxyEntry, ProxyRegistry, ProxyRegistryStore

pytestmark = pytest.mark.regression


def _entry(proxy_id: str, port: int) -> ProxyEntry:
    return ProxyEntry(
        proxy_id=proxy_id,
        template="test-template",
        base_url=f"http://localhost:{port}",
        port=port,
        status="healthy",
    )


def _write_registry(*entries: ProxyEntry) -> None:
    ProxyRegistryStore().write(ProxyRegistry(proxies={entry.proxy_id: entry for entry in entries}))


def _patch_metrics(monkeypatch: pytest.MonkeyPatch, metrics_by_url: dict[str, dict[str, Any] | None]) -> None:
    def fetch(base_url: str) -> _ProxyInfo | None:
        metrics = metrics_by_url[base_url]
        return _ProxyInfo(metrics=metrics, template="test-template") if metrics is not None else None

    monkeypatch.setattr("forge.cli.proxy._fetch_proxy_info", fetch)


def test_explicit_metrics_json_preserves_long_whitespace_rich_value(monkeypatch: pytest.MonkeyPatch) -> None:
    proxy = _entry("proxy-one", 8085)
    _write_registry(proxy)
    value = "prefix " + "word " * 60 + "[bold]literal[/bold]"
    _patch_metrics(monkeypatch, {proxy.base_url: {"total_requests": 1, "diagnostic": value}})

    result = CliRunner().invoke(main, ["proxy", "metrics", proxy.proxy_id, "--json"])

    assert result.exit_code == 0, result.output
    assert result.stderr == ""
    assert json.loads(result.stdout)["diagnostic"] == value


def test_explicit_metrics_json_preserves_markup_looking_string(monkeypatch: pytest.MonkeyPatch) -> None:
    proxy = _entry("proxy-one", 8085)
    _write_registry(proxy)
    value = "[bold magenta]literal[/bold magenta]"
    _patch_metrics(monkeypatch, {proxy.base_url: {"diagnostic": value}})

    result = CliRunner().invoke(main, ["proxy", "metrics", proxy.proxy_id, "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {"diagnostic": value}


def test_bare_metrics_json_with_zero_proxies_is_empty_mapping() -> None:
    result = CliRunner().invoke(main, ["proxy", "metrics", "--json"])

    assert result.exit_code == 0, result.output
    assert result.stderr == ""
    assert json.loads(result.stdout) == {}


def test_bare_metrics_json_with_one_proxy_keeps_proxy_id_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    proxy = _entry("proxy-one", 8085)
    metrics = {"total_requests": 1}
    _write_registry(proxy)
    _patch_metrics(monkeypatch, {proxy.base_url: metrics})

    result = CliRunner().invoke(main, ["proxy", "metrics", "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {proxy.proxy_id: metrics}


def test_bare_metrics_json_with_many_proxies_marks_unreachable_null(monkeypatch: pytest.MonkeyPatch) -> None:
    reachable = _entry("proxy-a", 8085)
    unreachable = _entry("proxy-b", 8086)
    metrics = {"total_requests": 2}
    _write_registry(reachable, unreachable)
    _patch_metrics(monkeypatch, {reachable.base_url: metrics, unreachable.base_url: None})

    result = CliRunner().invoke(main, ["proxy", "metrics", "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {reachable.proxy_id: metrics, unreachable.proxy_id: None}


def test_explicit_metrics_json_remains_raw_object(monkeypatch: pytest.MonkeyPatch) -> None:
    proxy = _entry("proxy-one", 8085)
    metrics = {"total_requests": 3}
    _write_registry(proxy)
    _patch_metrics(monkeypatch, {proxy.base_url: metrics})

    result = CliRunner().invoke(main, ["proxy", "metrics", proxy.proxy_id, "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == metrics
