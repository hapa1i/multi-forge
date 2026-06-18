"""Tests for upstream outcome volume rules."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from forge.core.telemetry.upstream import (
    read_upstream_outcomes,
    record_upstream_operation,
    should_record_upstream_outcome,
)


@dataclass
class _RuntimeConfig:
    upstream_event_volume: str = "non_success"


def test_default_volume_skips_cached_success_and_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("forge.runtime_config.get_runtime_config", lambda: _RuntimeConfig())

    assert should_record_upstream_outcome("success", cached=True) is False
    assert should_record_upstream_outcome("warning", cached=True) is False
    assert should_record_upstream_outcome("fail_open", cached=True) is True


def test_all_volume_records_cached_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("forge.runtime_config.get_runtime_config", lambda: _RuntimeConfig("all"))

    assert should_record_upstream_outcome("success", cached=True) is True
    assert should_record_upstream_outcome("warning", cached=True) is True


def test_record_upstream_operation_fills_ambient_run_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORGE_RUN_ID", "run_child")
    monkeypatch.setenv("FORGE_PARENT_RUN_ID", "run_parent")
    monkeypatch.setenv("FORGE_ROOT_RUN_ID", "run_root")

    record_upstream_operation(
        command="memory-writer",
        operation="memory_writer.run",
        status="error",
        session="planner",
        reason_code="transcript_not_found",
    )

    outcomes = read_upstream_outcomes(session="planner", command="memory-writer")
    assert len(outcomes) == 1
    assert outcomes[0].run_id == "run_child"
    assert outcomes[0].parent_run_id == "run_parent"
    assert outcomes[0].root_run_id == "run_root"
    assert outcomes[0].reason_code == "transcript_not_found"
