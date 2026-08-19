"""Regression for O046: proxy accounting persistence blocked the event loop.

``server._calc_and_log_cost`` appended downstream JSONL inline, while
``CostTracker.record`` and lifespan shutdown could atomic-write spend-cap state on
the same async thread. Slow filesystem I/O therefore stalled unrelated request
completion and heartbeats. The fix in ``proxy/accounting_persistence.py``,
``proxy/server.py``, and ``proxy/cost_tracker.py`` must serialize immutable jobs on
one worker and drain them during controlled shutdown. A queued write's completion,
not its acceptance, controls whether the cap checkpoint remains dirty for retry.
"""

from __future__ import annotations

import asyncio
import threading
import time
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from forge.core.paths import get_forge_home
from forge.core.telemetry import caps, downstream
from forge.proxy import server
from forge.proxy.cost_tracker import CostTracker

pytestmark = pytest.mark.regression


async def _release_after_event_loop_heartbeat(
    *,
    started: threading.Event,
    completed: threading.Event,
    release: threading.Event,
    heartbeat_before_completion: list[bool],
) -> None:
    while not started.is_set():
        await asyncio.sleep(0)
    heartbeat_before_completion.append(not completed.is_set())
    release.set()


def _calc(request_id: str, *, cost_micros: int = 100) -> int | None:
    return server._calc_and_log_cost(
        model="openai/gpt-5.5",
        tier="sonnet",
        input_tokens=10,
        output_tokens=5,
        cached_tokens=0,
        latency_ms=2.0,
        failed=False,
        request_id=request_id,
        reported_cost_micros=cost_micros,
        downstream_event_id=f"ds_{request_id}",
    )


@pytest.mark.asyncio
async def test_slow_downstream_append_does_not_block_completion_and_stays_ordered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = threading.Event()
    completed = threading.Event()
    release = threading.Event()
    heartbeat_before_completion: list[bool] = []
    persisted_evidence: list[tuple[str, str]] = []

    def slow_append(
        _path: object,
        record: dict[str, Any],
        **_kwargs: object,
    ) -> None:
        evidence_kind = "trace" if record.get("request_mode") else "cost"
        persisted_evidence.append((evidence_kind, str(record["request_id"])))
        if len(persisted_evidence) == 1:
            started.set()
            release.wait(timeout=0.5)
            completed.set()

    monkeypatch.setattr(downstream, "append_jsonl_record", slow_append)
    monkeypatch.setattr(server, "cost_tracker", None)
    monkeypatch.setattr(server, "PROXY_ID", "proxy-o046")
    monkeypatch.setattr(
        server,
        "config",
        SimpleNamespace(proxy=SimpleNamespace(preferred_provider="openrouter", backend="openrouter")),
    )

    async with server.lifespan(server.app):
        releaser = asyncio.create_task(
            _release_after_event_loop_heartbeat(
                started=started,
                completed=completed,
                release=release,
                heartbeat_before_completion=heartbeat_before_completion,
            )
        )
        assert _calc("req-o046-first") == 100
        server.record_provider_trace(
            backend_id="openrouter",
            proxy_id="proxy-o046",
            mapped_model="openai/gpt-5.5",
            request_id="req-o046-first",
            forge_run_id=None,
            forge_root_run_id=None,
            provider_session_id=None,
            provider_command=None,
            provider_meta=None,
            request_mode="non_streaming",
            stream_started=True,
            first_chunk_seen=True,
            final_usage_seen=True,
            client_disconnected=False,
            reported_cost_micros=100,
            latency_ms=2.0,
            downstream_event_id="ds_req-o046-first",
            record_sink=server._persist_proxy_downstream_record,
        )
        assert _calc("req-o046-second", cost_micros=200) == 200
        await asyncio.wait_for(releaser, timeout=2.0)

    assert heartbeat_before_completion == [True]
    assert persisted_evidence == [
        ("cost", "req-o046-first"),
        ("trace", "req-o046-first"),
        ("cost", "req-o046-second"),
    ]


@pytest.mark.asyncio
async def test_slow_cap_checkpoint_uses_an_immutable_snapshot_off_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = threading.Event()
    completed = threading.Event()
    release = threading.Event()
    heartbeat_before_completion: list[bool] = []
    persisted_payloads: list[dict[str, Any]] = []

    def slow_atomic_write(_path: object, payload: dict[str, Any], **_kwargs: object) -> None:
        persisted_payloads.append(payload)
        if len(persisted_payloads) == 1:
            started.set()
            release.wait(timeout=0.5)
            completed.set()

    tracker = CostTracker(daily_cap_usd=10.0, monthly_cap_usd=100.0)
    tracker._proxy_id = "proxy-o046"
    tracker._monthly_key = datetime.now(timezone.utc).strftime("%Y-%m")
    tracker._last_cap_persisted_at = 0.0

    monkeypatch.setattr(caps, "atomic_write_json", slow_atomic_write)
    monkeypatch.setattr(server, "cost_tracker", tracker)

    async with server.lifespan(server.app):
        releaser = asyncio.create_task(
            _release_after_event_loop_heartbeat(
                started=started,
                completed=completed,
                release=release,
                heartbeat_before_completion=heartbeat_before_completion,
            )
        )
        tracker.record(100_000)
        tracker.record(200_000)
        assert tracker.monthly_spend_micros() == 300_000
        await asyncio.wait_for(releaser, timeout=2.0)

    assert heartbeat_before_completion == [True]
    assert persisted_payloads[0]["monthly_total_micros"] == 100_000
    assert persisted_payloads[0]["daily_window"] != persisted_payloads[-1]["daily_window"]


@pytest.mark.asyncio
async def test_failed_queued_cap_checkpoint_stays_dirty_and_retries_on_next_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    persisted_totals: list[int] = []

    def fail_first_atomic_write(_path: object, payload: dict[str, Any], **_kwargs: object) -> None:
        persisted_totals.append(int(payload["monthly_total_micros"]))
        if len(persisted_totals) == 1:
            raise OSError("transient cap-state failure")

    tracker = CostTracker(daily_cap_usd=10.0, monthly_cap_usd=100.0)
    tracker._proxy_id = "proxy-o046"
    tracker._monthly_key = datetime.now(timezone.utc).strftime("%Y-%m")
    tracker._last_cap_persisted_at = 0.0

    monkeypatch.setattr(caps, "atomic_write_json", fail_first_atomic_write)
    monkeypatch.setattr(server, "cost_tracker", tracker)

    async with server.lifespan(server.app):
        tracker.record(100_000)
        outcome = tracker._pending_cap_persist
        assert outcome is not None
        assert await asyncio.wait_for(asyncio.wrap_future(outcome), timeout=2.0) is False

        assert tracker._dirty_cap_records == 1
        tracker.record(200_000)

    assert persisted_totals == [100_000, 300_000]
    assert tracker._dirty_cap_records == 0
    assert not tracker._cap_persist_retry_required


@pytest.mark.asyncio
async def test_lifespan_flush_waits_for_pending_cap_state_without_blocking_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = threading.Event()
    completed = threading.Event()
    release = threading.Event()
    heartbeat_before_completion: list[bool] = []
    persisted_totals: list[int] = []

    def slow_atomic_write(_path: object, payload: dict[str, Any], **_kwargs: object) -> None:
        persisted_totals.append(int(payload["monthly_total_micros"]))
        started.set()
        release.wait(timeout=0.5)
        completed.set()

    tracker = CostTracker(daily_cap_usd=10.0, monthly_cap_usd=100.0)
    tracker._proxy_id = "proxy-o046"
    tracker._monthly_key = datetime.now(timezone.utc).strftime("%Y-%m")
    tracker._last_cap_persisted_at = time.monotonic()

    monkeypatch.setattr(caps, "atomic_write_json", slow_atomic_write)
    monkeypatch.setattr(server, "cost_tracker", tracker)

    releaser = asyncio.create_task(
        _release_after_event_loop_heartbeat(
            started=started,
            completed=completed,
            release=release,
            heartbeat_before_completion=heartbeat_before_completion,
        )
    )
    async with server.lifespan(server.app):
        tracker.record(400_000)
        assert persisted_totals == []

    await asyncio.wait_for(releaser, timeout=2.0)
    assert heartbeat_before_completion == [True]
    assert persisted_totals == [400_000]


@pytest.mark.asyncio
async def test_lifespan_retries_failed_cap_checkpoint_after_worker_drain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    persisted_totals: list[int] = []

    def fail_first_atomic_write(_path: object, payload: dict[str, Any], **_kwargs: object) -> None:
        persisted_totals.append(int(payload["monthly_total_micros"]))
        if len(persisted_totals) == 1:
            raise OSError("transient shutdown checkpoint failure")

    tracker = CostTracker(daily_cap_usd=10.0, monthly_cap_usd=100.0)
    tracker._proxy_id = "proxy-o046"
    tracker._monthly_key = datetime.now(timezone.utc).strftime("%Y-%m")
    tracker._last_cap_persisted_at = time.monotonic()

    monkeypatch.setattr(caps, "atomic_write_json", fail_first_atomic_write)
    monkeypatch.setattr(server, "cost_tracker", tracker)

    async with server.lifespan(server.app):
        tracker.record(400_000)

    assert persisted_totals == [400_000, 400_000]
    assert tracker._dirty_cap_records == 0
    assert not tracker._cap_persist_retry_required


@pytest.mark.asyncio
async def test_drained_cost_and_cap_state_reconstruct_the_same_spend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracker = CostTracker(daily_cap_usd=10.0, monthly_cap_usd=100.0)
    tracker._proxy_id = "proxy-o046"
    tracker._monthly_key = datetime.now(timezone.utc).strftime("%Y-%m")
    tracker._last_cap_persisted_at = 0.0

    monkeypatch.setattr(server, "cost_tracker", tracker)
    monkeypatch.setattr(server, "PROXY_ID", "proxy-o046")
    monkeypatch.setattr(
        server,
        "config",
        SimpleNamespace(proxy=SimpleNamespace(preferred_provider="openrouter", backend="openrouter")),
    )

    async with server.lifespan(server.app):
        assert _calc("req-o046-restart", cost_micros=750_000) == 750_000
        assert tracker.monthly_spend_micros() == 750_000

    restarted = CostTracker(daily_cap_usd=10.0, monthly_cap_usd=100.0)
    restarted.bootstrap_from_logs(
        get_forge_home() / "telemetry" / "downstream",
        proxy_id="proxy-o046",
    )

    assert restarted.daily_spend_micros() == 750_000
    assert restarted.monthly_spend_micros() == 750_000
