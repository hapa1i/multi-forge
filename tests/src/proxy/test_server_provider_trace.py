"""Server-level wiring for the provider-trace plane (Phase 3).

The request-path write sites (`_on_stream_complete` / non-streaming block) are verified
end-to-end by the proxy integration tests; here we cover the standalone prune wiring that
`_ensure_runtime_state` invokes once per process.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from forge.proxy import provider_trace_logger as ptl
from forge.proxy import server


@pytest.fixture(autouse=True)
def _reset_latch():
    server._provider_traces_pruned = False
    yield
    server._provider_traces_pruned = False


def test_maybe_prune_reads_config_and_runs_once(monkeypatch: pytest.MonkeyPatch):
    calls: list[dict] = []
    monkeypatch.setattr(ptl, "prune_provider_traces", lambda **kw: calls.append(kw))
    monkeypatch.setattr(
        server,
        "config",
        SimpleNamespace(proxy=SimpleNamespace(provider_trace=SimpleNamespace(retention_days=7, max_total_mb=128))),
    )

    server._maybe_prune_provider_traces()
    server._maybe_prune_provider_traces()  # latch: second call is a no-op

    assert calls == [{"retention_days": 7, "max_total_mb": 128}]


def test_maybe_prune_no_config_is_noop(monkeypatch: pytest.MonkeyPatch):
    called = []
    monkeypatch.setattr(ptl, "prune_provider_traces", lambda **kw: called.append(kw))
    monkeypatch.setattr(server, "config", SimpleNamespace(proxy=SimpleNamespace(provider_trace=None)))

    server._maybe_prune_provider_traces()

    assert called == []


def test_maybe_prune_swallows_errors(monkeypatch: pytest.MonkeyPatch):
    def _boom(**kw):
        raise OSError("disk gone")

    monkeypatch.setattr(ptl, "prune_provider_traces", _boom)
    monkeypatch.setattr(
        server,
        "config",
        SimpleNamespace(proxy=SimpleNamespace(provider_trace=SimpleNamespace(retention_days=14, max_total_mb=512))),
    )

    server._maybe_prune_provider_traces()  # best-effort: must not raise
