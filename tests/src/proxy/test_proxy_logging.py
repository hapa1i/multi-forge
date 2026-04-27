"""Tests for proxy logging gating.

Structured JSONL logs (requests + tool events) must only be written when the
Forge effective log level is "debug".
"""

from __future__ import annotations

import pytest

from forge.proxy.utils import log_request_response, log_tool_event
from forge.runtime_config import reset_runtime_config


@pytest.fixture(autouse=True)
def _reset_config_singleton():
    """Ensure each test gets a fresh RuntimeConfig singleton."""
    reset_runtime_config()
    yield
    reset_runtime_config()


@pytest.mark.asyncio
async def test_structured_proxy_logs_disabled_by_default(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Default log_level=off should produce no JSONL files."""
    monkeypatch.setenv("FORGE_HOME", str(tmp_path / "forge_home"))
    monkeypatch.delenv("FORGE_DEBUG", raising=False)

    await log_request_response(
        request_id="req_1",
        original_model="claude-opus",
        mapped_model="gpt-5.2",
        request_body={"messages": []},
        response_body={"id": "resp_1"},
        status_code=200,
        duration_ms=12.3,
    )

    await log_tool_event(
        request_id="req_1",
        tool_name="bash",
        status="attempt",
        stage="openai_request",
        details={"x": 1},
    )

    assert not (tmp_path / "forge_home" / "logs" / "requests").exists()
    assert not (tmp_path / "forge_home" / "logs" / "tool_events").exists()


@pytest.mark.asyncio
async def test_structured_proxy_logs_write_in_debug(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORGE_HOME", str(tmp_path / "forge_home"))
    monkeypatch.setenv("FORGE_DEBUG", "1")

    await log_request_response(
        request_id="req_1",
        original_model="claude-opus",
        mapped_model="gpt-5.2",
        request_body={"messages": []},
        response_body={"id": "resp_1"},
        status_code=200,
        duration_ms=12.3,
    )

    await log_tool_event(
        request_id="req_1",
        tool_name="bash",
        status="attempt",
        stage="openai_request",
        details={"x": 1},
    )

    requests_dir = tmp_path / "forge_home" / "logs" / "requests"
    tool_events_dir = tmp_path / "forge_home" / "logs" / "tool_events"

    assert requests_dir.is_dir()
    assert tool_events_dir.is_dir()

    request_files = list(requests_dir.glob("*_requests.*.jsonl"))
    tool_files = list(tool_events_dir.glob("*_proxy.*.jsonl"))

    assert len(request_files) == 1
    assert len(tool_files) == 1

    assert '"request_id": "req_1"' in request_files[0].read_text(encoding="utf-8")
    assert '"tool_name": "bash"' in tool_files[0].read_text(encoding="utf-8")
