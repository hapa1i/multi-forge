"""Unit tests for the `forge telemetry trace` CLI (table + --json parity)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.proxy import provider_trace_logger as ptl


def _trace_args(*args: str) -> list[str]:
    return ["telemetry", "trace", *args]


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    ptl._warned_newer_schema = False
    yield
    ptl._warned_newer_schema = False


def _record(**kw: Any) -> None:
    params: dict[str, Any] = dict(
        backend_id="openrouter",
        request_mode="streaming",
        request_id="req-1",
        proxy_id="crimson-apricot",
        mapped_model="openai/gpt-5.5",
        forge_run_id="run_abc",
        forge_root_run_id="run_root",
        provider_session_id="forge_sess_abc_supervisor",
        provider_command="supervisor",
        provider_meta={"provider": "openrouter", "selected_provider": "Azure", "provider_generation_id": "gen-xyz"},
        stream_started=True,
        first_chunk_seen=True,
        final_usage_seen=False,
        client_disconnected=True,
        reported_cost_micros=None,
        latency_ms=45000.0,
    )
    params.update(kw)
    ptl.record_provider_trace(**params)


def test_trace_group_orients_to_leaves():
    bare = CliRunner().invoke(main, _trace_args())
    assert bare.exit_code == 2
    assert "Usage:" in bare.output
    helped = CliRunner().invoke(main, _trace_args("--help"))
    assert helped.exit_code == 0
    assert "list" in helped.output and "explain" in helped.output


def test_list_empty():
    result = CliRunner().invoke(main, _trace_args("list", "--period", "all"))
    assert result.exit_code == 0
    assert "No provider traces" in result.output


def test_list_json_is_bare_array():
    _record(request_id="req-1")
    _record(request_id="req-2")
    result = CliRunner().invoke(main, _trace_args("list", "--period", "all", "--json"))
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert isinstance(data, list)  # bare array, NOT the wrapper dict
    assert {r["request_id"] for r in data} == {"req-1", "req-2"}


def test_list_table_shows_record():
    _record(request_id="req-1")
    result = CliRunner().invoke(main, _trace_args("list", "--period", "all"))
    assert result.exit_code == 0
    assert "req-1" in result.output
    assert "disconnect" in result.output


def test_show_json_single_dict():
    _record(request_id="req-1")
    result = CliRunner().invoke(main, _trace_args("show", "req-1", "--json"))
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert isinstance(data, dict)
    assert data["request_id"] == "req-1"
    assert data["provider_generation_id"] == "gen-xyz"


def test_show_missing_exits_1_with_tip():
    result = CliRunner().invoke(main, _trace_args("show", "nope"))
    assert result.exit_code == 1
    # Error + tip go to stderr; stdout stays clean for the JSON/results stream.
    assert "No provider trace found" in result.stderr
    assert "Tip:" in result.stderr


def test_explain_json_whole_dto():
    _record(request_id="req-1")
    result = CliRunner().invoke(main, _trace_args("explain", "req-1", "--json"))
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["request_id"] == "req-1"
    assert data["remote_lookup_performed"] is False


def test_explain_text_incident():
    _record(request_id="req-1")
    result = CliRunner().invoke(main, _trace_args("explain", "req-1"))
    assert result.exit_code == 0
    assert "unavailable, not zero" in result.output
    assert "No remote lookup was performed." in result.output


def test_explain_missing_exits_1():
    result = CliRunner().invoke(main, _trace_args("explain", "nope"))
    assert result.exit_code == 1


def test_no_secret_value_printed():
    _record(request_id="req-1")
    for args in (["list", "--period", "all"], ["show", "req-1"], ["explain", "req-1"]):
        out = CliRunner().invoke(main, _trace_args(*args)).output
        assert "sk-" not in out
        assert "Bearer" not in out
