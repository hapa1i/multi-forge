"""Regression: debug tool-event diagnostics must contain bounded metadata only."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import stat
from collections.abc import Coroutine, Iterator
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from forge.proxy import converters, server
from forge.proxy.data_models import MessagesRequest
from forge.runtime_config import reset_runtime_config

pytestmark = pytest.mark.regression

_SCHEMA_SECRET = "D035_SCHEMA_PAYLOAD_MUST_NOT_REACH_TOOL_EVENTS"
_ERROR_SECRET = "D035_TOOL_RESULT_PAYLOAD_MUST_NOT_REACH_DIAGNOSTICS"
_INPUT_SECRET = "D035_TOOL_INPUT_PAYLOAD_MUST_NOT_REACH_TOOL_EVENTS"


@pytest.fixture(autouse=True)
def _reset_config_singleton() -> Iterator[None]:
    reset_runtime_config()
    yield
    reset_runtime_config()


def _request_with_tool_schema() -> MessagesRequest:
    return MessagesRequest.model_validate(
        {
            "model": "claude-sonnet-4-6",
            "messages": [{"role": "user", "content": "Use the custom tool."}],
            "max_tokens": 128,
            "tools": [
                {
                    "name": "CustomTool",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": _SCHEMA_SECRET,
                            }
                        },
                        "required": ["path"],
                    },
                }
            ],
        }
    )


def _request_with_failed_tool_result() -> MessagesRequest:
    return MessagesRequest.model_validate(
        {
            "model": "claude-sonnet-4-6",
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_d035",
                            "name": "CustomTool",
                            "input": {"path": _INPUT_SECRET},
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_d035",
                            "content": f"Error: {_ERROR_SECRET}",
                            "is_error": True,
                        }
                    ],
                },
            ],
            "max_tokens": 128,
        }
    )


async def _run_scheduled(coroutines: list[Coroutine[Any, Any, None]]) -> None:
    if coroutines:
        await asyncio.gather(*coroutines)


def _read_only_tool_event(forge_home: Path) -> tuple[Path, dict[str, Any]]:
    paths = list((forge_home / "logs" / "tool_events").glob("*_proxy.*.jsonl"))
    assert len(paths) == 1
    records = [json.loads(line) for line in paths[0].read_text(encoding="utf-8").splitlines()]
    assert len(records) == 1
    return paths[0], records[0]


async def _write_sanitized_event(
    forge_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    request_id: str = "req_d035",
    tool_name: str = "Read",
    tool_id: str = "toolu_d035",
    stripped_params: list[str] | None = None,
) -> tuple[Path, dict[str, Any]]:
    monkeypatch.setenv("FORGE_HOME", str(forge_home))
    monkeypatch.setenv("FORGE_DEBUG", "1")
    scheduled: list[Coroutine[Any, Any, None]] = []

    with patch(
        "forge.proxy.converters.asyncio.create_task",
        side_effect=lambda coro: scheduled.append(coro),
    ):
        converters._schedule_tool_args_sanitized_event(
            request_id=request_id,
            tool_name=tool_name,
            stripped_params=stripped_params or ["pages"],
            tool_id=tool_id,
            streaming=False,
        )

    await _run_scheduled(scheduled)
    return _read_only_tool_event(forge_home)


@pytest.mark.asyncio
async def test_schema_event_keeps_counts_but_not_schema_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forge_home = tmp_path / "forge_home"
    monkeypatch.setenv("FORGE_HOME", str(forge_home))
    monkeypatch.setenv("FORGE_DEBUG", "1")
    scheduled: list[Coroutine[Any, Any, None]] = []

    with patch(
        "forge.proxy.converters.asyncio.create_task",
        side_effect=lambda coro: scheduled.append(coro),
    ):
        converters.convert_anthropic_to_openai(_request_with_tool_schema(), provider="openai")

    await _run_scheduled(scheduled)
    _path, record = _read_only_tool_event(forge_home)

    assert _SCHEMA_SECRET not in json.dumps(record)
    assert "details" not in record
    assert record["metadata"] == {
        "event": "schema_observed",
        "schema_field_count": 3,
        "schema_property_count": 1,
        "schema_required_count": 1,
    }


@pytest.mark.asyncio
async def test_client_failure_warning_and_event_keep_shape_not_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    forge_home = tmp_path / "forge_home"
    monkeypatch.setenv("FORGE_HOME", str(forge_home))
    monkeypatch.setenv("FORGE_DEBUG", "1")
    monkeypatch.setattr(
        server.config,
        "proxy",
        SimpleNamespace(get_provider=lambda: SimpleNamespace(error_hints=False)),
    )

    async def ignore_explicit_failure_plane(**_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(server, "log_tool_failure", ignore_explicit_failure_plane)
    scheduled: list[Coroutine[Any, Any, None]] = []
    caplog.set_level(logging.WARNING, logger="forge.proxy.server")

    with patch(
        "forge.proxy.server.asyncio.create_task",
        side_effect=lambda coro: scheduled.append(coro),
    ):
        await server._check_client_tool_failures(
            _request_with_failed_tool_result(),
            request_id="req_d035",
            mapped_model="openai/gpt-5",
        )

    await _run_scheduled(scheduled)
    _path, record = _read_only_tool_event(forge_home)
    warning_text = "\n".join(caplog.messages)

    assert _ERROR_SECRET not in warning_text
    assert _INPUT_SECRET not in warning_text
    assert "content_type=str" in warning_text
    assert "content_length=" in warning_text
    assert _ERROR_SECRET not in json.dumps(record)
    assert _INPUT_SECRET not in json.dumps(record)
    assert "details" not in record
    assert record["metadata"] == {
        "event": "client_tool_failure",
        "tool_id": "toolu_d035",
        "content_type": "str",
        "content_length": len(f"Error: {_ERROR_SECRET}"),
        "tool_name_found": True,
    }


@pytest.mark.asyncio
async def test_tool_event_identifiers_and_parameter_names_are_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    long_value = "x" * 256
    parameter_names = [f"parameter_{index}_{long_value}" for index in range(40)]
    _path, record = await _write_sanitized_event(
        tmp_path / "forge_home",
        monkeypatch,
        request_id=f"req\n{long_value}",
        tool_name=long_value,
        tool_id=long_value,
        stripped_params=parameter_names,
    )

    assert "\n" not in record["request_id"]
    assert len(record["request_id"]) <= 128
    assert len(record["tool_name"]) <= 128
    assert record["request_id_truncated"] is True
    assert record["tool_name_truncated"] is True

    metadata = record["metadata"]
    assert metadata["event"] == "tool_args_sanitized"
    assert len(metadata["tool_id"]) <= 128
    assert metadata["tool_id_truncated"] is True
    assert metadata["stripped_param_count"] == 40
    assert len(metadata["stripped_params"]) == 32
    assert all(len(name) <= 128 for name in metadata["stripped_params"])
    assert metadata["stripped_params_truncated"] is True


@pytest.mark.asyncio
async def test_tool_event_writer_corrects_existing_directory_modes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forge_home = tmp_path / "forge_home"
    logs_dir = forge_home / "logs"
    tool_events_dir = logs_dir / "tool_events"
    tool_events_dir.mkdir(parents=True)
    os.chmod(logs_dir, 0o777)
    os.chmod(tool_events_dir, 0o777)

    await _write_sanitized_event(forge_home, monkeypatch)

    assert stat.S_IMODE(logs_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(tool_events_dir.stat().st_mode) == 0o700


@pytest.mark.asyncio
async def test_tool_event_shard_remains_owner_only_control(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forge_home = tmp_path / "forge_home"
    tool_events_dir = forge_home / "logs" / "tool_events"
    tool_events_dir.mkdir(parents=True)
    expected_shard = tool_events_dir / f"{datetime.now(timezone.utc):%Y%m%d}_proxy.{os.getpid()}.jsonl"
    expected_shard.touch()
    os.chmod(expected_shard, 0o666)

    shard, _record = await _write_sanitized_event(forge_home, monkeypatch)

    assert shard == expected_shard
    assert stat.S_IMODE(shard.stat().st_mode) == 0o600
