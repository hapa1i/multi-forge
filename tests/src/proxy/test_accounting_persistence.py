"""Contract tests for ordered proxy accounting persistence."""

from __future__ import annotations

import logging

import pytest

from forge.core.telemetry.caps import CapState
from forge.core.telemetry.downstream import DownstreamRecord
from forge.proxy import accounting_persistence
from forge.proxy.accounting_persistence import ProxyAccountingPersistence


def _record(request_id: str) -> DownstreamRecord:
    return DownstreamRecord(
        kind="attempt",
        downstream_event_id=f"ds_{request_id}",
        request_id=request_id,
        proxy_id="proxy-o046",
    )


@pytest.mark.asyncio
async def test_failed_downstream_job_warns_and_does_not_stop_later_jobs(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    persisted: list[str] = []

    def write(record: DownstreamRecord) -> None:
        if record.request_id == "first":
            raise OSError("disk unavailable")
        persisted.append(str(record.request_id))

    monkeypatch.setattr(accounting_persistence, "write_downstream_record", write)
    worker = ProxyAccountingPersistence()

    with caplog.at_level(logging.WARNING, logger=accounting_persistence.__name__):
        worker.submit_downstream_record(_record("first"))
        worker.submit_downstream_record(_record("second"))
        await worker.close()

    assert persisted == ["second"]
    assert "Failed to persist downstream accounting for request first: disk unavailable" in caplog.text


@pytest.mark.asyncio
async def test_failed_cap_job_warns_without_failing_shutdown(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def fail(_state: CapState) -> None:
        raise OSError("read-only filesystem")

    monkeypatch.setattr(accounting_persistence, "write_cap_state", fail)
    worker = ProxyAccountingPersistence()

    with caplog.at_level(logging.WARNING, logger=accounting_persistence.__name__):
        outcome = worker.submit_cap_state(
            CapState(
                proxy_id="proxy-o046",
                monthly_key="2026-08",
                monthly_total_micros=42,
                daily_window=[(1.0, 42)],
            )
        )
        await worker.close()

    assert outcome is not None
    assert outcome.result() is False
    assert "Failed to persist spend-cap state for proxy-o046: read-only filesystem" in caplog.text


@pytest.mark.asyncio
async def test_close_is_idempotent_and_rejects_late_jobs_with_a_warning(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    writes: list[str] = []
    monkeypatch.setattr(
        accounting_persistence,
        "write_downstream_record",
        lambda record: writes.append(str(record.request_id)),
    )
    worker = ProxyAccountingPersistence()
    await worker.close()
    await worker.close()

    with caplog.at_level(logging.WARNING, logger=accounting_persistence.__name__):
        worker.submit_downstream_record(_record("late"))

    assert writes == []
    assert "accounting persistence is closed" in caplog.text
