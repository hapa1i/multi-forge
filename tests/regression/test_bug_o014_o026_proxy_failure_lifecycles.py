"""Regressions for failed proxy-start ownership and non-200 stream cleanup."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from forge.proxy import passthrough, proxy_orchestrator, responses_passthrough
from forge.proxy.proxies import ProxyEntry, ProxyRegistry, ProxyRegistryStore
from forge.proxy.proxy_orchestrator import ProxyStartError

pytestmark = pytest.mark.regression

_PROVIDER_SECRET = b"provider-body-must-not-escape"


class _Proc:
    returncode = None
    pid = 4242

    def poll(self) -> None:
        return None


class _Stream:
    def __init__(self, *, status_code: int, body: bytes, read_error: bool = False) -> None:
        self.status_code = status_code
        self.headers = {"content-type": "application/json", "retry-after": "7"}
        self.body = body
        self.read_error = read_error
        self.exit_count = 0

    async def __aenter__(self) -> _Stream:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        self.exit_count += 1
        return False

    async def aread(self) -> bytes:
        if self.read_error:
            raise httpx.ReadError("injected non-200 body read failure")
        return self.body


class _Client:
    def __init__(self, stream: _Stream) -> None:
        self._stream = stream
        self.exit_count = 0

    async def __aenter__(self) -> _Client:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        self.exit_count += 1
        return False

    def stream(self, *_args: object, **_kwargs: object) -> _Stream:
        return self._stream


def _failed_restart_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    prior_entry: ProxyEntry | None,
) -> ProxyRegistryStore:
    store = ProxyRegistryStore(tmp_path / "proxies" / "index.json")
    if prior_entry is not None:
        store.write(ProxyRegistry(proxies={prior_entry.proxy_id: prior_entry}))

    monkeypatch.setattr(proxy_orchestrator, "ProxyRegistryStore", lambda *args, **kwargs: store)
    monkeypatch.setattr(proxy_orchestrator, "_validate_template_exists", lambda _template: None)
    monkeypatch.setattr(
        proxy_orchestrator,
        "_load_template_for_proxy",
        lambda _template: SimpleNamespace(proxy=SimpleNamespace(backend_dependency=None, preferred_provider="litellm")),
    )
    monkeypatch.setattr(proxy_orchestrator, "_ensure_template_credentials", lambda _template: None)
    monkeypatch.setattr(proxy_orchestrator, "_is_port_in_use", lambda _port: False)
    monkeypatch.setattr(proxy_orchestrator, "check_proxy_health", lambda **_kwargs: False)
    monkeypatch.setattr(
        proxy_orchestrator,
        "_spawn_proxy_process",
        lambda **_kwargs: (_Proc(), tmp_path / "stderr.log"),
    )
    monkeypatch.setattr(proxy_orchestrator, "_terminate_process", lambda _proc: None)
    monkeypatch.setattr(proxy_orchestrator, "now_iso", lambda: "2026-08-12T00:00:00+00:00")

    def _fail_health(**_kwargs: object) -> None:
        raise ProxyStartError("injected startup failure")

    monkeypatch.setattr(proxy_orchestrator, "_wait_until_healthy", _fail_health)
    return store


def _run_failed_restart(*, proxy_id: str, port: int) -> None:
    with pytest.raises(ProxyStartError, match="injected startup failure"):
        proxy_orchestrator.start_proxy(
            template="litellm-openai",
            proxy_id=proxy_id,
            port=port,
            skip_proxy_file=True,
        )


def test_failed_restart_restores_existing_registry_entry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prior = ProxyEntry(
        proxy_id="existing-proxy",
        template="litellm-openai",
        base_url="http://localhost:8123",
        port=8123,
        pid=None,
        created_at="2026-08-01T00:00:00+00:00",
        last_seen_at="2026-08-02T00:00:00+00:00",
        status="stopped",
    )
    store = _failed_restart_store(tmp_path, monkeypatch, prior_entry=prior)

    _run_failed_restart(proxy_id=prior.proxy_id, port=prior.port)

    assert store.read().proxies[prior.proxy_id] == prior


def test_failed_config_only_restart_retains_stopped_ownership(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = _failed_restart_store(tmp_path, monkeypatch, prior_entry=None)

    _run_failed_restart(proxy_id="config-only", port=8124)

    assert store.read().proxies["config-only"] == ProxyEntry(
        proxy_id="config-only",
        template="litellm-openai",
        base_url="http://localhost:8124",
        port=8124,
        pid=None,
        created_at="2026-08-12T00:00:00+00:00",
        last_seen_at=None,
        status="stopped",
    )


@pytest.mark.asyncio
async def test_anthropic_non_200_read_failure_closes_contexts_and_reports_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = _Stream(status_code=529, body=_PROVIDER_SECRET, read_error=True)
    client = _Client(stream)
    monkeypatch.setattr(passthrough.httpx, "AsyncClient", lambda **_kwargs: client)
    completed: list[tuple[dict[str, int], dict[str, Any] | None, bool]] = []

    response = await passthrough.forward(
        raw_body={"model": "m", "stream": True, "messages": []},
        inbound_headers={},
        base_url="https://api.anthropic.test",
        api_key="K",
        request_id="req-read-failure",
        on_complete=lambda usage, body, failed: completed.append((usage, body, failed)),
    )

    assert response.status_code == 502
    assert _PROVIDER_SECRET not in bytes(response.body)
    assert stream.exit_count == 1
    assert client.exit_count == 1
    assert completed == [({}, None, True)]


@pytest.mark.asyncio
async def test_responses_non_200_read_failure_closes_contexts_and_reports_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = _Stream(status_code=429, body=_PROVIDER_SECRET, read_error=True)
    client = _Client(stream)
    monkeypatch.setattr(responses_passthrough.httpx, "AsyncClient", lambda **_kwargs: client)
    completed: list[tuple[dict[str, int], int | None, bool, str | None]] = []

    response = await responses_passthrough.forward(
        method="POST",
        url_path="/v1/responses",
        body={"model": "m", "input": "hi", "stream": True},
        query_string="",
        inbound_headers={},
        base_url="https://upstream.test",
        api_key="K",
        request_id="req-read-failure",
        on_complete=lambda usage, cost, failed, error: completed.append((usage, cost, failed, error)),
    )

    assert response.status_code == 502
    assert _PROVIDER_SECRET not in bytes(response.body)
    assert stream.exit_count == 1
    assert client.exit_count == 1
    assert completed == [({}, None, True, "upstream_error")]


@pytest.mark.asyncio
async def test_anthropic_ordinary_non_200_still_relays_body(monkeypatch: pytest.MonkeyPatch) -> None:
    body = b'{"type":"error","error":{"type":"overloaded_error"}}'
    stream = _Stream(status_code=529, body=body)
    client = _Client(stream)
    monkeypatch.setattr(passthrough.httpx, "AsyncClient", lambda **_kwargs: client)

    response = await passthrough.forward(
        raw_body={"model": "m", "stream": True, "messages": []},
        inbound_headers={},
        base_url="https://api.anthropic.test",
        api_key="K",
        request_id="req-ordinary-error",
    )

    assert response.status_code == 529
    assert bytes(response.body) == body
    assert stream.exit_count == 1
    assert client.exit_count == 1


@pytest.mark.asyncio
async def test_responses_ordinary_non_200_still_relays_body(monkeypatch: pytest.MonkeyPatch) -> None:
    body = b'{"type":"error","error":{"type":"rate_limit_error"}}'
    stream = _Stream(status_code=429, body=body)
    client = _Client(stream)
    monkeypatch.setattr(responses_passthrough.httpx, "AsyncClient", lambda **_kwargs: client)

    response = await responses_passthrough.forward(
        method="POST",
        url_path="/v1/responses",
        body={"model": "m", "input": "hi", "stream": True},
        query_string="",
        inbound_headers={},
        base_url="https://upstream.test",
        api_key="K",
        request_id="req-ordinary-error",
    )

    assert response.status_code == 429
    assert bytes(response.body) == body
    assert stream.exit_count == 1
    assert client.exit_count == 1
