"""Slices 2 + 3 (proxy_log_hygiene): bounded per-chunk dumps + a compact lifecycle summary.

Slice 2: the per-chunk debug dumps at the SSE seam are bounded (``smart_format_str``) and
guarded by ``logger.isEnabledFor(DEBUG)`` so no formatting cost is paid on the hot loop when
DEBUG is off.

Slice 3: the bare per-stream "conversion finished" INFO line is replaced by one compact
lifecycle summary (chunk count + flags + outcome) -- DEBUG for a clean stream, INFO for an
error or client disconnect. ``format_stream_lifecycle_summary`` is the shared renderer.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncGenerator

import pytest

import forge.proxy.converters as converters
from forge.proxy.converters import convert_openai_to_anthropic_sse
from forge.proxy.data_models import (
    Message,
    MessagesRequest,
    ToolDefinition,
    ToolInputSchema,
)
from forge.proxy.utils import format_stream_lifecycle_summary

_LOGGER_NAME = "forge.proxy.converters"

CARRIER: dict[str, Any] = {"choices": [], "_provider_meta": {"provider": "openrouter"}}


def _request() -> MessagesRequest:
    return MessagesRequest(
        model="claude-3-5-sonnet",
        messages=[Message(role="user", content="hi")],
        max_tokens=256,
        stream=True,
    )


async def _gen(chunks: list[dict[str, Any]]) -> AsyncGenerator[dict[str, Any], None]:
    for c in chunks:
        yield c


async def _gen_then_raise(chunks: list[dict[str, Any]], exc: BaseException) -> AsyncGenerator[dict[str, Any], None]:
    for c in chunks:
        yield c
    raise exc


async def _drain(
    generator: AsyncGenerator[dict[str, Any], None],
    *,
    stream_chunks: bool = False,
    stream_chunk_max_bytes: int = 0,
) -> None:
    async for _sse_text in convert_openai_to_anthropic_sse(
        generator,
        _request(),
        "rid",
        on_complete=None,
        stream_chunks=stream_chunks,
        stream_chunk_max_bytes=stream_chunk_max_bytes,
    ):
        pass


_CLEAN_CHUNKS: list[dict[str, Any]] = [
    CARRIER,
    {"choices": [{"delta": {"content": "Hello"}, "finish_reason": None}]},
    {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 5, "completion_tokens": 2}},
]


# --- Slice 3: the pure summary renderer -------------------------------------------------


def test_summary_renders_clean_outcome() -> None:
    line = format_stream_lifecycle_summary(
        "rid",
        first_chunk_seen=True,
        final_usage_seen=True,
        client_disconnected=False,
        failed=False,
        error_type=None,
        chunk_count=7,
    )
    assert line == "[rid] stream ok chunks=7 first_chunk=y final_usage=y"


def test_summary_renders_disconnect() -> None:
    line = format_stream_lifecycle_summary(
        "rid",
        first_chunk_seen=False,
        final_usage_seen=False,
        client_disconnected=True,
        failed=False,
        error_type=None,
        chunk_count=1,
    )
    assert "stream disconnected" in line and "chunks=1" in line and "first_chunk=n" in line


def test_summary_renders_error_with_type() -> None:
    line = format_stream_lifecycle_summary(
        "rid",
        first_chunk_seen=True,
        final_usage_seen=False,
        client_disconnected=False,
        failed=True,
        error_type="api_error",
        chunk_count=3,
    )
    assert "stream error" in line and "error_type=api_error" in line


def test_summary_never_contains_chunk_bodies() -> None:
    """Metadata only -- the summary must carry counts/flags, never content."""
    line = format_stream_lifecycle_summary(
        "rid",
        first_chunk_seen=True,
        final_usage_seen=True,
        client_disconnected=False,
        failed=False,
        error_type=None,
        chunk_count=2,
    )
    assert "Hello" not in line and "content" not in line


# --- Slice 2: bounded + guarded per-chunk dumps -----------------------------------------


def _spy_format(monkeypatch) -> dict[str, int]:
    calls = {"n": 0}
    real = converters.smart_format_str

    def _spy(obj: object, *a: Any, **k: Any) -> str:
        calls["n"] += 1
        return real(obj, *a, **k)

    monkeypatch.setattr(converters, "smart_format_str", _spy)
    return calls


@pytest.mark.asyncio
async def test_chunk_dump_not_formatted_when_debug_off(monkeypatch, caplog) -> None:
    """Even opted in, with DEBUG off the isEnabledFor guard short-circuits -- no formatting."""
    calls = _spy_format(monkeypatch)
    caplog.set_level(logging.INFO, logger=_LOGGER_NAME)  # above DEBUG -> isEnabledFor(DEBUG) is False

    await _drain(_gen(_CLEAN_CHUNKS), stream_chunks=True)

    assert calls["n"] == 0  # no eager formatting on the hot loop


@pytest.mark.asyncio
async def test_chunk_dump_suppressed_by_default_even_at_debug(monkeypatch, caplog) -> None:
    """stream_chunks defaults off -> per-chunk dumps do NOT appear even at log_level=debug."""
    calls = _spy_format(monkeypatch)
    caplog.set_level(logging.DEBUG, logger=_LOGGER_NAME)

    await _drain(_gen(_CLEAN_CHUNKS), stream_chunks=False)

    assert calls["n"] == 0
    assert [r for r in caplog.records if "Processing adapted OpenAI Chunk" in r.getMessage()] == []


@pytest.mark.asyncio
async def test_huge_chunk_dump_is_truncated_when_opted_in(caplog) -> None:
    huge = "X" * 10000
    chunks: list[dict[str, Any]] = [{"choices": [{"delta": {"content": huge}, "finish_reason": "stop"}]}]
    caplog.set_level(logging.DEBUG, logger=_LOGGER_NAME)

    await _drain(_gen(chunks), stream_chunks=True, stream_chunk_max_bytes=200)

    dumps = [r.getMessage() for r in caplog.records if "Processing adapted OpenAI Chunk" in r.getMessage()]
    assert dumps, "expected a per-chunk debug dump when opted in + DEBUG on"
    # The 10k string is capped by stream_chunk_max_bytes (200); it must not appear whole.
    assert huge not in dumps[0]
    assert len(dumps[0]) < len(huge)


# --- Slice 3: the emitted summary line --------------------------------------------------


@pytest.mark.asyncio
async def test_clean_stream_logs_debug_summary(caplog) -> None:
    caplog.set_level(logging.DEBUG, logger=_LOGGER_NAME)

    await _drain(_gen(_CLEAN_CHUNKS))

    summaries = [r for r in caplog.records if "stream ok" in r.getMessage()]
    assert len(summaries) == 1
    assert summaries[0].levelno == logging.DEBUG
    assert "chunks=3" in summaries[0].getMessage()  # carrier + content + usage chunks
    # A clean stream emits ZERO converter INFO -- start/finish bookends are now DEBUG, and
    # the compact summary is DEBUG. INFO is reserved for error/disconnect.
    assert [r for r in caplog.records if r.levelno == logging.INFO] == []


@pytest.mark.asyncio
async def test_disconnect_logs_info_summary(caplog) -> None:
    caplog.set_level(logging.DEBUG, logger=_LOGGER_NAME)

    with pytest.raises(GeneratorExit):
        await _drain(_gen_then_raise([CARRIER], GeneratorExit()))

    infos = [r for r in caplog.records if r.levelno == logging.INFO and "stream disconnected" in r.getMessage()]
    assert len(infos) == 1
    assert "chunks=1" in infos[0].getMessage()


# --- Claim-A regression: per-delta + malformed-chunk logs are content-free even at DEBUG ---
#
# stream_chunks defaults off, yet the per-delta "Sent text delta" / tool-args logs and the
# malformed-chunk WARNINGs must NOT emit completion/tool-arg text or dump the raw chunk body.
# Full content is only available through the opt-in stream_chunks dump. These assert ABSENCE of
# sentinel content across all records (the specific leak the reviewer found).


@pytest.mark.asyncio
async def test_text_delta_not_logged_as_content_by_default(caplog) -> None:
    chunks: list[dict[str, Any]] = [
        {"choices": [{"delta": {"content": "SECRET_COMPLETION"}, "finish_reason": None}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}},
    ]
    caplog.set_level(logging.DEBUG, logger=_LOGGER_NAME)

    await _drain(_gen(chunks), stream_chunks=False)

    assert all("SECRET_COMPLETION" not in r.getMessage() for r in caplog.records)
    # The metadata-only line still fires (flow visibility), reporting a length, not the text.
    assert any("Sent text delta:" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_tool_args_delta_not_logged_as_content_by_default(caplog) -> None:
    chunks: list[dict[str, Any]] = [
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "search", "arguments": ""},
                            }
                        ]
                    },
                    "finish_reason": None,
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {"tool_calls": [{"index": 0, "function": {"arguments": "SECRET_ARGS"}}]},
                    "finish_reason": None,
                }
            ]
        },
        {
            "choices": [{"delta": {}, "finish_reason": "tool_calls"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        },
    ]
    caplog.set_level(logging.DEBUG, logger=_LOGGER_NAME)

    await _drain(_gen(chunks), stream_chunks=False)

    assert all("SECRET_ARGS" not in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_buffered_tool_close_event_not_logged_as_content(caplog) -> None:
    # "Read" is a buffered tool: its per-delta args are NOT emitted, so the end-of-stream close
    # event (partial_json with the sanitized args) is the first/only place file_path reaches a log.
    chunks: list[dict[str, Any]] = [
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "Read", "arguments": ""},
                            }
                        ]
                    },
                    "finish_reason": None,
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {"tool_calls": [{"index": 0, "function": {"arguments": '{"file_path": "/SECRET_PATH"}'}}]},
                    "finish_reason": None,
                }
            ]
        },
        {
            "choices": [{"delta": {}, "finish_reason": "tool_calls"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        },
    ]
    caplog.set_level(logging.DEBUG, logger=_LOGGER_NAME)

    await _drain(_gen(chunks), stream_chunks=False)

    # The close-event log must report block metadata, never the sanitized partial_json (file path).
    assert all("/SECRET_PATH" not in r.getMessage() for r in caplog.records)
    assert any("Yielding" in r.getMessage() and "tool_use" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_malformed_chunk_warning_dumps_keys_not_body(caplog) -> None:
    # No 'choices' and no usage -> the "missing or invalid 'choices'" WARNING fires. It must log
    # key names only, never the chunk's values (which can carry delta content / tool args).
    chunks: list[dict[str, Any]] = [{"object": "chunk", "payload": "SECRET_CHUNK_VALUE"}]
    caplog.set_level(logging.DEBUG, logger=_LOGGER_NAME)

    await _drain(_gen(chunks), stream_chunks=False)

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING and "invalid 'choices'" in r.getMessage()]
    assert len(warnings) == 1  # the warning still fires -- it just no longer dumps the body
    assert "SECRET_CHUNK_VALUE" not in warnings[0].getMessage()
    assert "payload" in warnings[0].getMessage()  # key names are safe to surface


# --- O037/O038/O042: non-streaming converter diagnostics ------------------------------


def _close_created_coroutine(coroutine: Any) -> None:
    coroutine.close()


def _non_streaming_tool_response(arguments: object) -> dict[str, object]:
    return {
        "id": "chatcmpl-log-hygiene",
        "request_id": "req_log_hygiene",
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_log_hygiene",
                            "type": "function",
                            "function": {"name": "CustomTool", "arguments": arguments},
                        }
                    ],
                },
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }


def test_request_schema_dumps_are_not_formatted_when_debug_is_off(monkeypatch, caplog) -> None:
    calls = _spy_format(monkeypatch)
    monkeypatch.setattr(converters.asyncio, "create_task", _close_created_coroutine)
    caplog.set_level(logging.INFO, logger=_LOGGER_NAME)
    request = MessagesRequest(
        model="claude-sonnet-4-6",
        messages=[Message(role="user", content="SECRET_REQUEST_BODY")],
        max_tokens=64,
        tools=[
            ToolDefinition(
                name="CustomTool",
                description="SECRET_TOOL_DESCRIPTION",
                input_schema=ToolInputSchema(
                    type="object",
                    properties={"value": {"type": "string", "description": "SECRET_SCHEMA"}},
                ),
            )
        ],
    )

    converted = converters.convert_anthropic_to_openai(request, provider="litellm")

    assert calls["n"] == 0
    assert converted["messages"][0]["content"] == "SECRET_REQUEST_BODY"
    assert converted["tools"][0]["function"]["description"] == "SECRET_TOOL_DESCRIPTION"


@pytest.mark.parametrize(
    ("arguments", "error_type"),
    [
        ("invalid-json-SECRET_ARGUMENT", None),
        ({"secret": "SECRET_ARGUMENT"}, "TypeError"),
    ],
)
def test_non_streaming_malformed_arguments_log_shape_and_preserve_fallback(
    arguments, error_type, monkeypatch, caplog
) -> None:
    monkeypatch.setattr(converters.asyncio, "create_task", _close_created_coroutine)
    caplog.set_level(logging.DEBUG, logger=_LOGGER_NAME)

    converted = converters.convert_openai_to_anthropic(_non_streaming_tool_response(arguments))
    records = "\n".join(record.getMessage() for record in caplog.records)

    assert converted is not None
    tool_block = next(block for block in converted.content if block.type == "tool_use")
    assert tool_block.input["raw_arguments"] == arguments
    assert "SECRET_ARGUMENT" not in records
    assert f"value_type={type(arguments).__name__}" in records
    assert "fallback=" in records
    if error_type is None:
        assert "error_type=" not in records
    else:
        assert f"error_type={error_type}" in records


def test_non_function_tool_call_logs_allowlisted_shape_only(caplog) -> None:
    response = {
        "id": "chatcmpl-log-hygiene",
        "request_id": "req_log_hygiene",
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_log_hygiene",
                            "type": "code_interpreter",
                            "payload": "SECRET_TOOL_CALL_VALUE",
                        }
                    ],
                },
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }
    caplog.set_level(logging.DEBUG, logger=_LOGGER_NAME)

    converted = converters.convert_openai_to_anthropic(response)
    records = "\n".join(record.getMessage() for record in caplog.records)

    assert converted is not None
    assert all(block.type != "tool_use" for block in converted.content)
    assert "SECRET_TOOL_CALL_VALUE" not in records
    assert "value_type=dict" in records
    assert "known_keys=id,type" in records
    assert "unknown_keys=1" in records
