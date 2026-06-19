"""Unit tests for the %provider trace direct commands."""

from __future__ import annotations

import contextlib
import io
import json
from typing import Any

import pytest

from forge.cli.hooks.direct_commands import _handle_cmd_provider
from forge.proxy import provider_trace_logger as ptl


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


def _run(argv: list[str]) -> dict[str, Any]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        _handle_cmd_provider({}, argv)
    return json.loads(buf.getvalue())


def test_list_blocks_with_records():
    _record(request_id="req-1")
    out = _run(["trace", "list"])
    assert out["decision"] == "block"
    assert "req-1" in out["reason"]


def test_explain_matches_terminal_narrative():
    _record(request_id="req-1")
    out = _run(["trace", "explain", "req-1"])
    # Same render_explanation_lines contract as the terminal CLI -> byte-identical text.
    from forge.core.ops import explain_provider_trace, render_explanation_lines
    from forge.core.ops.context import ExecutionContext

    exp = explain_provider_trace(ctx=ExecutionContext.from_cwd(), request_id="req-1")
    assert out["reason"] == "\n".join(render_explanation_lines(exp))


def test_list_caps_at_10():
    for i in range(15):
        _record(request_id=f"req-{i:02d}")
    out = _run(["trace", "list"])
    # 1 header line + at most 10 record lines.
    assert len(out["reason"].splitlines()) == 11


def test_explain_missing_is_error_block():
    out = _run(["trace", "explain", "nope"])
    assert out["decision"] == "block"
    assert "No provider trace found" in out["reason"]


def test_unknown_subcommand_usage():
    out = _run(["bogus"])
    assert out["decision"] == "block"
    assert "Usage:" in out["reason"]


def test_show_requires_request_id():
    out = _run(["trace", "show"])
    assert "Usage:" in out["reason"]
