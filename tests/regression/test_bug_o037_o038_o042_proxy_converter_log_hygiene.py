"""Regression for O037/O038/O042: converter diagnostics exposed caller payloads.

The translated request path logged full messages and schemas at DEBUG, malformed tool
arguments and non-function tool calls were rendered into ordinary warnings/errors, and
suppressed DEBUG records still paid the cost of formatting complete payloads.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

import forge.proxy.converters as converters
from forge.proxy.data_models import (
    Message,
    MessagesRequest,
    ToolDefinition,
    ToolInputSchema,
)

pytestmark = pytest.mark.regression

_LOGGER_NAME = "forge.proxy.converters"
_SYSTEM_CANARY = "O037_SYSTEM_CANARY"
_MESSAGE_CANARY = "O037_MESSAGE_CANARY"
_DESCRIPTION_CANARY = "O037_DESCRIPTION_CANARY"
_SCHEMA_CANARY = "O037_SCHEMA_CANARY"
_STOP_CANARY = "O037_STOP_CANARY"
_ARGUMENT_CANARY = "O038_ARGUMENT_CANARY"
_TOOL_CALL_CANARY = "O038_TOOL_CALL_CANARY"


@pytest.fixture(autouse=True)
def _close_background_coroutines(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep fire-and-forget tool-event writes out of this synchronous regression."""

    def _close(coroutine: Any) -> None:
        coroutine.close()

    monkeypatch.setattr(converters.asyncio, "create_task", _close)


def _request() -> MessagesRequest:
    return MessagesRequest(
        model="claude-sonnet-4-6",
        system=_SYSTEM_CANARY,
        messages=[Message(role="user", content=_MESSAGE_CANARY)],
        max_tokens=64,
        stop_sequences=[_STOP_CANARY],
        tools=[
            ToolDefinition(
                name="CustomTool",
                description=_DESCRIPTION_CANARY,
                input_schema=ToolInputSchema(
                    type="object",
                    properties={"value": {"type": "string", "description": _SCHEMA_CANARY}},
                    required=["value"],
                ),
            )
        ],
    )


def _records(caplog: pytest.LogCaptureFixture) -> str:
    return "\n".join(record.getMessage() for record in caplog.records if record.name == _LOGGER_NAME)


def _tool_response(arguments: object) -> dict[str, object]:
    return {
        "id": "chatcmpl-o038",
        "request_id": "req_o038",
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_o038",
                            "type": "function",
                            "function": {"name": "CustomTool", "arguments": arguments},
                        }
                    ],
                },
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }


def test_request_and_schema_logs_are_metadata_only(monkeypatch: pytest.MonkeyPatch, caplog) -> None:
    calls = 0
    real_format = converters.smart_format_str

    def _spy(value: object, *args: Any, **kwargs: Any) -> str:
        nonlocal calls
        calls += 1
        return real_format(value, *args, **kwargs)

    monkeypatch.setattr(converters, "smart_format_str", _spy)
    caplog.set_level(logging.DEBUG, logger=_LOGGER_NAME)

    converted = converters.convert_anthropic_to_openai(_request(), provider="litellm")
    records = _records(caplog)

    assert converted["system_prompt"] == _SYSTEM_CANARY
    assert converted["messages"][0]["content"] == _SYSTEM_CANARY
    assert converted["messages"][1]["content"] == _MESSAGE_CANARY
    assert converted["stop"] == [_STOP_CANARY]
    assert converted["tools"][0]["function"]["description"] == _DESCRIPTION_CANARY
    assert converted["tools"][0]["function"]["parameters"]["properties"]["value"]["description"] == _SCHEMA_CANARY
    assert calls == 0
    assert "Tool schema received:" in records
    assert "Intermediate OpenAI request prepared:" in records
    for canary in (_SYSTEM_CANARY, _MESSAGE_CANARY, _DESCRIPTION_CANARY, _SCHEMA_CANARY, _STOP_CANARY):
        assert canary not in records


def test_request_and_schema_payloads_are_not_formatted_when_debug_is_suppressed(
    monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    calls = 0

    def _spy(_value: object, *_args: Any, **_kwargs: Any) -> str:
        nonlocal calls
        calls += 1
        return "formatted"

    monkeypatch.setattr(converters, "smart_format_str", _spy)
    caplog.set_level(logging.INFO, logger=_LOGGER_NAME)

    converters.convert_anthropic_to_openai(_request(), provider="litellm")

    assert calls == 0


@pytest.mark.parametrize(
    ("arguments", "error_type"),
    [
        (f"not-json-{_ARGUMENT_CANARY}", None),
        ({"secret": _ARGUMENT_CANARY}, "TypeError"),
    ],
)
def test_malformed_tool_argument_logs_keep_the_client_fallback_but_drop_plaintext(
    arguments: object,
    error_type: str | None,
    caplog,
) -> None:
    caplog.set_level(logging.DEBUG, logger=_LOGGER_NAME)

    converted = converters.convert_openai_to_anthropic(_tool_response(arguments), "claude-sonnet-4-6")
    records = _records(caplog)

    assert converted is not None
    tool_block = next(block for block in converted.content if block.type == "tool_use")
    assert tool_block.input["raw_arguments"] == arguments
    assert _ARGUMENT_CANARY not in records
    assert f"value_type={type(arguments).__name__}" in records
    assert "fallback=" in records
    if error_type is None:
        assert "error_type=" not in records
    else:
        assert f"error_type={error_type}" in records


def test_non_function_tool_call_log_contains_shape_not_caller_values(caplog) -> None:
    response = {
        "id": "chatcmpl-o038-non-function",
        "request_id": "req_o038",
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_o038",
                            "type": "code_interpreter",
                            "payload": {"secret": _TOOL_CALL_CANARY},
                            _TOOL_CALL_CANARY: "value",
                        }
                    ],
                },
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }
    caplog.set_level(logging.DEBUG, logger=_LOGGER_NAME)

    converted = converters.convert_openai_to_anthropic(response, "claude-sonnet-4-6")
    records = _records(caplog)

    assert converted is not None
    assert all(block.type != "tool_use" for block in converted.content)
    assert _TOOL_CALL_CANARY not in records
    assert "value_type=dict" in records
    assert "known_keys=id,type" in records
    assert "unknown_keys=2" in records
