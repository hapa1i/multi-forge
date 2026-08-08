"""Server wiring for the single downstream-retention owner (D015)."""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest

import forge.proxy.server as server
from forge.core.state import PruneJsonlShardsResult
from forge.core.telemetry.downstream_retention import (
    DownstreamRetentionPolicy,
    DownstreamRetentionResolution,
    RetentionConflict,
    RetentionConflictValue,
)


@pytest.fixture(autouse=True)
def _reset_retention_state() -> Iterator[None]:
    server._downstream_pruned = False
    server._downstream_retention_resolution = None
    server._downstream_prune_error = None
    yield
    server._downstream_pruned = False
    server._downstream_retention_resolution = None
    server._downstream_prune_error = None


def _resolution(*, days: int = 14, size: int = 512) -> DownstreamRetentionResolution:
    return DownstreamRetentionResolution(
        configured=None,
        effective=DownstreamRetentionPolicy(days, size),
        source="default",
    )


def test_maybe_prune_resolves_global_policy_and_runs_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from forge.core.telemetry import downstream, downstream_retention

    calls: list[dict[str, int]] = []

    def record_prune(**kwargs: int) -> PruneJsonlShardsResult:
        calls.append(kwargs)
        return PruneJsonlShardsResult()

    monkeypatch.setattr(
        downstream_retention,
        "resolve_downstream_retention",
        lambda: _resolution(days=7, size=128),
    )
    monkeypatch.setattr(downstream, "prune_downstream_records", record_prune)

    server._maybe_prune_downstream_records()
    server._maybe_prune_downstream_records()

    assert calls == [{"retention_days": 7, "max_total_mb": 128}]
    assert server._downstream_prune_error is None


def test_maybe_prune_skips_conflicting_legacy_policy(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from forge.core.telemetry import downstream, downstream_retention

    resolution = DownstreamRetentionResolution(
        configured=None,
        effective=None,
        source=None,
        conflicts=(
            RetentionConflict(
                "retention_days",
                (
                    RetentionConflictValue(14, ("alpha",), ("audit.retention_days",)),
                    RetentionConflictValue(90, ("beta",), ("provider_trace.retention_days",)),
                ),
            ),
        ),
    )
    calls: list[dict[str, int]] = []

    def record_prune(**kwargs: int) -> PruneJsonlShardsResult:
        calls.append(kwargs)
        return PruneJsonlShardsResult()

    monkeypatch.setattr(downstream_retention, "resolve_downstream_retention", lambda: resolution)
    monkeypatch.setattr(downstream, "prune_downstream_records", record_prune)

    with caplog.at_level(logging.WARNING):
        server._maybe_prune_downstream_records()

    assert calls == []
    assert "Conflicting proxy IDs: alpha, beta" in caplog.text
    assert "automatic pruning was skipped" in caplog.text


def test_maybe_prune_reports_partial_enforcement(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from forge.core.telemetry import downstream, downstream_retention

    monkeypatch.setattr(downstream_retention, "resolve_downstream_retention", lambda: _resolution())
    monkeypatch.setattr(
        downstream,
        "prune_downstream_records",
        lambda **kwargs: PruneJsonlShardsResult(errors=("could not remove old shard",)),
    )

    with caplog.at_level(logging.WARNING):
        server._maybe_prune_downstream_records()

    assert server._downstream_prune_error == "could not remove old shard"
    assert "only partially enforced" in caplog.text
    assert "retention_days=14, max_total_mb=512" in caplog.text


def test_status_section_marks_prune_failure_degraded() -> None:
    server._downstream_retention_resolution = _resolution()
    server._downstream_prune_error = "could not remove old shard"

    section, degraded = server._downstream_retention_status_section()

    assert degraded is True
    assert section["degraded"] is True
    assert section["pruning_enabled"] is True
    assert section["prune_error"] == "could not remove old shard"


def test_maybe_prune_resolution_failure_is_best_effort(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from forge.core.telemetry import downstream_retention

    def fail_resolution() -> DownstreamRetentionResolution:
        raise OSError("injected resolver fault")

    monkeypatch.setattr(downstream_retention, "resolve_downstream_retention", fail_resolution)

    with caplog.at_level(logging.WARNING):
        server._maybe_prune_downstream_records()

    assert server._downstream_prune_error == "could not resolve policy: injected resolver fault"
    assert "telemetry/downstream" in caplog.text
    assert "automatic pruning was skipped" in caplog.text


def test_runtime_state_bootstraps_caps_before_downstream_pruning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        server,
        "_initialize_cost_tracker_from_config",
        lambda: calls.append("cost-bootstrap"),
    )
    monkeypatch.setattr(
        server,
        "_maybe_prune_downstream_records",
        lambda: calls.append("downstream-prune"),
    )
    monkeypatch.setattr(server, "_maybe_prune_request_logs", lambda: calls.append("request-log-prune"))
    monkeypatch.setattr(server, "PROXY_ID", None)

    server._ensure_runtime_state()

    assert calls == ["cost-bootstrap", "downstream-prune", "request-log-prune"]
