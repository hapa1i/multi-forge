"""B5 budget guards are checked offline, before native or paid dispatch is possible."""

from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

from tests.fixtures.codex_probe import load_script


@pytest.fixture
def runtime(monkeypatch):
    monkeypatch.setenv("PROBE_CASE", "G0")
    monkeypatch.setenv("PROBE_MODEL", "synthetic-model")
    monkeypatch.setenv("PROBE_ROLE", "source")
    return load_script("b5-runtime")


def test_concurrent_starts_cannot_overrun_case(runtime, tmp_path):
    authorization = {
        "subscription_extra_usage_off_confirmed": True,
        "api_starts_authorized": 0,
    }

    def attempt(_):
        try:
            runtime.reserve_start(tmp_path, {"sha256": "synthetic"}, "subscription-only", authorization)
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(30)))
    assert sum(results) == 11
    records = [json.loads(line) for line in (tmp_path / "starts.jsonl").read_text().splitlines()]
    assert len(records) == len({record["id"] for record in records}) == 11


@pytest.mark.parametrize("auth_mode", ["subscription-only", "api"])
def test_no_authorization_means_no_reserved_start(runtime, tmp_path, auth_mode):
    authorization = {
        "subscription_extra_usage_off_confirmed": False,
        "api_starts_authorized": 0,
    }
    with pytest.raises(ValueError):
        runtime.reserve_start(tmp_path, {"sha256": "synthetic"}, auth_mode, authorization)
    ledger = tmp_path / "starts.jsonl"
    assert not ledger.exists() or not ledger.read_text()


def test_api_starts_are_inside_total_and_have_separate_ceiling(runtime, tmp_path):
    authorization = {
        "subscription_extra_usage_off_confirmed": True,
        "api_starts_authorized": 2,
    }
    for _ in range(2):
        runtime.reserve_start(tmp_path, {"sha256": "synthetic"}, "api", authorization)
    with pytest.raises(ValueError, match="API slots"):
        runtime.reserve_start(tmp_path, {"sha256": "synthetic"}, "api", authorization)
    for _ in range(9):
        runtime.reserve_start(tmp_path, {"sha256": "synthetic"}, "subscription-only", authorization)
    with pytest.raises(ValueError, match="allocation exhausted"):
        runtime.reserve_start(tmp_path, {"sha256": "synthetic"}, "subscription-only", authorization)


def test_index_recheck_reallocation_preserves_total_and_reviewer_ownership(runtime, tmp_path, monkeypatch):
    assert sum(runtime.CASE_LIMITS.values()) == 60
    assert runtime.CASE_LIMITS["G0"] == 11
    assert runtime.CASE_LIMITS["G14"] == 1
    assert runtime.CASE_LIMITS["P1"] + runtime.CASE_LIMITS["P2"] == 12
    monkeypatch.setenv("PROBE_CASE", "G14")
    with pytest.raises(ValueError, match="selected role"):
        runtime.reserve_start(tmp_path, {"sha256": "synthetic"}, "subscription-only", {})


def test_product_starts_require_gate_decision(runtime, tmp_path, monkeypatch):
    monkeypatch.setenv("PROBE_CASE", "P1")
    authorization = {
        "subscription_extra_usage_off_confirmed": True,
        "api_starts_authorized": 0,
    }
    with pytest.raises(ValueError, match="runtime gate decision"):
        runtime.reserve_start(tmp_path, {"sha256": "synthetic"}, "subscription-only", authorization)
    assert not (tmp_path / "starts.jsonl").exists()


def test_missing_case_refuses_before_ledger(runtime, tmp_path, monkeypatch):
    monkeypatch.delenv("PROBE_CASE")
    with pytest.raises(ValueError, match="allocated PROBE_CASE"):
        runtime.reserve_start(tmp_path, {"sha256": "synthetic"}, "subscription-only", {})
    assert not (tmp_path / "starts.jsonl").exists()


def test_hook_boundary_case_preserves_reviewer_slots(runtime, tmp_path, monkeypatch):
    monkeypatch.setenv("PROBE_CASE", "G12")
    authorization = {
        "subscription_extra_usage_off_confirmed": True,
        "api_starts_authorized": 0,
    }
    for _ in range(2):
        runtime.reserve_start(tmp_path, {"sha256": "synthetic"}, "subscription-only", authorization)
    with pytest.raises(ValueError, match="G12/source allocation exhausted"):
        runtime.reserve_start(tmp_path, {"sha256": "synthetic"}, "subscription-only", authorization)
    monkeypatch.setenv("PROBE_ROLE", "reviewer")
    for _ in range(2):
        runtime.reserve_start(tmp_path, {"sha256": "synthetic"}, "subscription-only", authorization)
    assert len((tmp_path / "starts.jsonl").read_text().splitlines()) == 4


def test_json_observation_preserves_output_and_missing_usage(runtime, capsys):
    payload = '{"type":"turn.completed","usage":{"input_tokens":5}}'
    result = runtime.run_native([sys.executable, "-c", f"print({payload!r})"], {}, json_events=True)
    assert capsys.readouterr().out == payload + "\n"
    assert result["returncode"] == 0
    assert 0 <= result["first_event_seconds"] <= result["elapsed_seconds"]
    assert result["usage_events"] == [{"input_tokens": 5}]
