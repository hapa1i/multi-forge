"""Tests for upstream outcome volume rules."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from forge.core.telemetry.upstream import should_record_upstream_outcome


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
