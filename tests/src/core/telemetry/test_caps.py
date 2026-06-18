"""Tests for durable spend-cap state."""

from __future__ import annotations

import json

import pytest

from forge.core.telemetry.caps import (
    CapState,
    cap_state_path,
    load_cap_state,
    write_cap_state,
)


def test_cap_state_round_trips() -> None:
    write_cap_state(
        CapState(
            proxy_id="proxy-a",
            monthly_key="2026-06",
            monthly_total_micros=123,
            daily_window=[(100.0, 50)],
        )
    )

    state = load_cap_state("proxy-a")

    assert state is not None
    assert state.proxy_id == "proxy-a"
    assert state.monthly_key == "2026-06"
    assert state.monthly_total_micros == 123
    assert state.daily_window == [(100.0, 50)]


def test_load_missing_cap_state_returns_none() -> None:
    assert load_cap_state("missing") is None


def test_load_rejects_newer_schema() -> None:
    path = cap_state_path("proxy-a")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"schema_version": 99, "proxy_id": "proxy-a"}))

    with pytest.raises(ValueError, match="Unsupported cap state schema_version"):
        load_cap_state("proxy-a")


def test_load_rejects_proxy_id_mismatch() -> None:
    path = cap_state_path("proxy-a")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"schema_version": 1, "proxy_id": "proxy-b", "daily_window": []}))

    with pytest.raises(ValueError, match="proxy_id mismatch"):
        load_cap_state("proxy-a")
