"""Utility functions for logging and formatting.

Provides proxy request formatting,
and specialized tool usage event logging to JSON Lines file.

Structured JSONL logs are only written when the effective Forge log level is
"debug" (config.yaml log_level=debug or FORGE_DEBUG=1).
"""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from rich.pretty import pretty_repr

from forge.core.logging import get_effective_log_level
from forge.core.paths import get_forge_home

_logger = logging.getLogger(__name__)


def _should_write_structured_logs() -> bool:
    return get_effective_log_level() == "debug"


def _pid_suffix() -> str:
    return str(os.getpid())


class Colors:
    """ANSI color and formatting codes for terminal output styling."""

    CYAN = "\033[96m"
    BLUE = "\033[94m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    MAGENTA = "\033[95m"
    RESET = "\033[0m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"
    DIM = "\033[2m"


def log_request_beautifully(
    method: str,
    path: str,
    original_model: str,
    mapped_model: str,
    num_messages: int,
    num_tools: int,
    status_code: int,
) -> None:
    """Log API requests in a colorized, human-readable format.

    Creates a visually distinctive terminal output for request monitoring with color-coded
    status indicators, model mapping information, and request details.

    Args:
        method: HTTP method (GET, POST, etc.)
        path: Request endpoint path
        original_model: Source model requested (Claude model name)
        mapped_model: Target model used (Gemini model name)
        num_messages: Number of messages in the request
        num_tools: Number of tools in the request
        status_code: HTTP status code of the response
    """
    try:
        original_display = f"{Colors.CYAN}{original_model}{Colors.RESET}"
        endpoint = path.split("?")[0]
        mapped_display_name = mapped_model
        mapped_color = Colors.GREEN  # Green indicates target Gemini model
        mapped_display = f"{mapped_color}{mapped_display_name}{Colors.RESET}"

        tools_str = (
            f"{Colors.MAGENTA}{num_tools} tools{Colors.RESET}"
            if num_tools > 0
            else f"{Colors.DIM}{num_tools} tools{Colors.RESET}"
        )
        messages_str = f"{Colors.BLUE}{num_messages} messages{Colors.RESET}"

        status_color = Colors.GREEN if 200 <= status_code < 300 else Colors.RED
        status_symbol = "✓" if 200 <= status_code < 300 else "✗"
        status_str = f"{status_color}{status_symbol} {status_code}{Colors.RESET}"

        log_line = f"{Colors.BOLD}{method} {endpoint}{Colors.RESET} {status_str}"
        model_line = f"  {original_display} → {mapped_display} ({messages_str}, {tools_str})"

        # Never write ANSI-colored output to file logs.
        # Only emit these lines to an interactive terminal.
        if sys.stderr.isatty():
            print(log_line, file=sys.stderr)
            print(model_line, file=sys.stderr)

        _logger.info(
            "Request processed: %s %s - %s (model=%s->%s, msgs=%s, tools=%s)",
            method,
            endpoint,
            status_code,
            original_model,
            mapped_model,
            num_messages,
            num_tools,
        )
    except Exception as e:
        _logger.error("Error during request summary logging: %s", e)
        _logger.info(
            "%s %s %s | %s -> %s | %s msgs, %s tools",
            method,
            path,
            status_code,
            original_model,
            mapped_model,
            num_messages,
            num_tools,
        )


def smart_format_str(obj: object, max_string: int = 500, max_length: int = 100, indent: int = 2) -> str:
    """Format an object to a string with rich formatting."""
    return pretty_repr(obj, max_string=max_string, max_length=max_length, indent_size=indent)


def format_stream_lifecycle_summary(
    request_id: str,
    *,
    first_chunk_seen: bool,
    final_usage_seen: bool,
    client_disconnected: bool,
    failed: bool,
    error_type: str | None,
    chunk_count: int,
) -> str:
    """Render one compact line summarizing a stream's lifecycle (proxy_log_hygiene).

    Replaces per-chunk debug dumps and the bare per-stream "finished" line with a single
    bounded summary. Metadata only (counts/flags) -- never chunk bodies. Shared by the
    translated converter path and the Anthropic passthrough relay so the two do not drift.
    """
    outcome = "disconnected" if client_disconnected else ("error" if failed else "ok")
    parts = [
        f"[{request_id}] stream {outcome}",
        f"chunks={chunk_count}",
        f"first_chunk={'y' if first_chunk_seen else 'n'}",
        f"final_usage={'y' if final_usage_seen else 'n'}",
    ]
    if error_type:
        parts.append(f"error_type={error_type}")
    return " ".join(parts)


def smart_format_proto_str(obj: object, max_string: int = 500, max_length: int = 100, indent: int = 2) -> str:
    """Format a proto object to a string with rich formatting."""
    formatted_obj = proto_to_dict(obj)
    return smart_format_str(formatted_obj, max_string, max_length, indent)


def proto_to_dict(obj: object) -> dict[str, object] | list[dict[str, object]] | object:
    """Convert proto objects to dictionaries recursively.

    This is used for logging/pretty-printing only.
    """
    to_dict = getattr(obj, "to_dict", None)
    if callable(to_dict):
        result = to_dict()
        return result if isinstance(result, dict) else {"value": result}

    if isinstance(obj, (list, tuple)):
        items = [proto_to_dict(item) for item in obj]
        # best-effort: only keep dicts for this branch
        dict_items = [item for item in items if isinstance(item, dict)]
        return dict_items

    if isinstance(obj, dict):
        return {str(k): proto_to_dict(v) for k, v in obj.items()}

    return obj


# Tool Events Logger for JSONL file
# Create an asyncio Lock to ensure thread-safe writing to the JSONL file
_tool_events_lock = asyncio.Lock()

# Request/Response Logger for JSONL file
_request_response_lock = asyncio.Lock()


async def log_tool_event(
    request_id: str,
    tool_name: str | None,
    status: Literal["attempt", "success", "failure"],
    stage: Literal[
        "openai_request",
        "gemini_request",
        "gemini_response",
        "client_response",
        "client_execution_report",
    ],
    details: dict[str, Any] | None = None,
) -> None:
    """Log tool usage events to a separate JSON Lines file for analysis.

    This function captures structured data about tool usage events at different
    stages of the request/response cycle, writing events to a timestamped tool_events.jsonl
    file in a thread-safe manner.

    Args:
        request_id: The unique identifier for the request
        tool_name: The name of the tool being used (or None for general events)
        status: Whether this is an attempt, success, or failure
        stage: Which part of the process (request to Gemini, response from Gemini, or response to client)
        details: Optional additional information about the event
    """
    if not _should_write_structured_logs():
        return

    try:
        logs_dir = get_forge_home() / "logs" / "tool_events"
        logs_dir.mkdir(exist_ok=True, parents=True)

        datestamp = datetime.now(timezone.utc).strftime("%Y%m%d")
        jsonl_path = logs_dir / f"{datestamp}_proxy.{_pid_suffix()}.jsonl"

        event: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "request_id": request_id,
            "tool_name": tool_name,
            "status": status,
            "stage": stage,
        }

        if details:
            event["details"] = details

        from forge.core.state import open_secure_append

        async with _tool_events_lock:
            with open_secure_append(jsonl_path) as f:
                f.write(json.dumps(event) + "\n")

        _logger.debug(
            "Tool event logged: %s %s for %s (request_id=%s)",
            status,
            stage,
            tool_name or "unknown",
            request_id,
        )
    except Exception as e:
        # Log error but don't fail the request
        _logger.error("Failed to log tool event: %s (request_id=%s)", e, request_id, exc_info=True)


# Tool Failure Logger — opt-in via RuntimeConfig.log_tool_failures
_tool_failure_lock = asyncio.Lock()


def _should_log_tool_failures() -> bool:
    from forge.runtime_config import get_runtime_config

    return get_runtime_config().log_tool_failures


_TOOL_FAILURE_SCHEMA_VERSION = 1
_TOOL_INPUT_MAX_STR_LEN = 1024
_TOOL_INPUT_MAX_DEPTH = 8
_ERROR_MAX_LEN = 2000


def _truncate_for_log(value: str | dict | list | None, max_len: int) -> str | dict | list | None:
    """Truncate a top-level string value (used for the error field)."""
    if isinstance(value, str) and len(value) > max_len:
        return value[:max_len] + f"... ({len(value)} chars)"
    return value


def _truncate_recursive(
    value: Any,
    max_str_len: int = _TOOL_INPUT_MAX_STR_LEN,
    max_depth: int = _TOOL_INPUT_MAX_DEPTH,
) -> Any:
    """Recursively cap large string values inside nested dicts/lists.

    Edit/Write tool inputs can carry tens of KB of file content. Without
    this, a single failure can produce a multi-MB JSONL line.
    """
    if max_depth <= 0:
        return "<truncated: max depth exceeded>"
    if isinstance(value, str):
        if len(value) > max_str_len:
            return value[:max_str_len] + f"... ({len(value)} chars)"
        return value
    if isinstance(value, dict):
        return {k: _truncate_recursive(v, max_str_len, max_depth - 1) for k, v in value.items()}
    if isinstance(value, list):
        return [_truncate_recursive(v, max_str_len, max_depth - 1) for v in value]
    return value


def _truncate_error_for_log(error_content: str | dict | list | None) -> Any:
    """Bound tool error payloads, including Anthropic list/dict content blocks."""
    if isinstance(error_content, str):
        return _truncate_for_log(error_content, _ERROR_MAX_LEN)
    return _truncate_recursive(error_content, max_str_len=_ERROR_MAX_LEN)


async def log_tool_failure(
    *,
    request_id: str,
    mapped_model: str,
    tool_name: str | None,
    tool_use_id: str | None,
    tool_input: dict[str, Any] | None,
    error_content: str | dict | list | None,
) -> None:
    """Log tool failure to dedicated JSONL for addendum refinement.

    Opt-in via log_tool_failures (no debug mode required). Best-effort:
    write failures are logged but never break the LLM response.
    """
    if not _should_log_tool_failures():
        return

    try:
        from forge.core.state import open_secure_append

        logs_dir = get_forge_home() / "logs" / "tool_failures"
        logs_dir.mkdir(exist_ok=True, parents=True)

        datestamp = datetime.now(timezone.utc).strftime("%Y%m%d")
        jsonl_path = logs_dir / f"{datestamp}_failures.{_pid_suffix()}.jsonl"

        record: dict[str, Any] = {
            "schema_version": _TOOL_FAILURE_SCHEMA_VERSION,
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "request_id": request_id,
            "tool_use_id": tool_use_id,
            "model": mapped_model,
            "tool": tool_name,
            "tool_input": _truncate_recursive(tool_input),
            "error": _truncate_error_for_log(error_content),
        }

        async with _tool_failure_lock:
            with open_secure_append(jsonl_path) as f:
                f.write(json.dumps(record, default=str) + "\n")
    except Exception as e:
        _logger.warning("Failed to write tool failure log: %s", e)


def _redact_content(content: object) -> dict[str, object]:
    """Replace message/response content with a redaction marker."""
    if content is None:
        return {"redacted": True, "length": 0}
    if isinstance(content, str):
        return {"redacted": True, "length": len(content)}
    if isinstance(content, list):
        return {
            "redacted": True,
            "items": len(content),
            "block_types": [
                (item.get("type") if isinstance(item, dict) else getattr(item, "type", "unknown")) for item in content
            ],
        }
    if isinstance(content, dict):
        return {"redacted": True, "length": len(str(content))}
    return {"redacted": True, "length": len(str(content))}


def _redact_tools(tools: list) -> list[dict[str, object]]:
    """Keep tool names and structure, redact descriptions."""
    redacted = []
    for tool in tools:
        if isinstance(tool, dict):
            entry: dict[str, object] = {"name": tool.get("name")}
            if "description" in tool:
                entry["description"] = {"redacted": True}
            if "input_schema" in tool:
                entry["input_schema"] = {"redacted": True}
            redacted.append(entry)
        else:
            name = getattr(tool, "name", None)
            redacted.append({"name": name, "redacted": True})
    return redacted


def _redact_body_for_log(body: dict[str, object] | None) -> dict[str, object] | None:
    """Replace sensitive content in request/response bodies with redaction markers.

    Preserves structural metadata (model, role, token counts, status)
    while removing all message text, system prompts, tool descriptions,
    user/org metadata, and tool output.
    """
    if body is None:
        return None

    _SAFE_KEYS = {
        "model",
        "temperature",
        "max_tokens",
        "top_p",
        "stream",
        "reasoning_effort",
        "verbosity",
        "usage",
        "id",
        "type",
        "role",
        "stop_reason",
    }

    redacted: dict[str, object] = {k: v for k, v in body.items() if k in _SAFE_KEYS}

    # stop_sequences is caller-supplied text (can embed proprietary delimiters) -- structure only, never verbatim.
    if "stop_sequences" in body and isinstance(body["stop_sequences"], list):
        redacted["stop_sequences"] = {"redacted": True, "count": len(body["stop_sequences"])}

    if "messages" in body and isinstance(body["messages"], list):
        redacted["messages"] = [
            {
                "role": msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", "unknown"),
                "content": _redact_content(
                    msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", None)
                ),
            }
            for msg in body["messages"]
        ]

    if "system" in body:
        redacted["system"] = _redact_content(body["system"])

    if "tools" in body and isinstance(body["tools"], list):
        redacted["tools"] = _redact_tools(body["tools"])

    if "content" in body and isinstance(body["content"], list):
        redacted["content"] = [
            {
                "type": block.get("type") if isinstance(block, dict) else getattr(block, "type", "unknown"),
                "content": _redact_content(
                    block.get("text", block.get("content"))
                    if isinstance(block, dict)
                    else getattr(block, "text", getattr(block, "content", None))
                ),
            }
            for block in body["content"]
        ]

    return redacted


# Header-name substrings that always trigger redaction even if not explicitly
# listed — catches vendor-prefixed credential headers (e.g. x-acme-secret).
_SUBSTRING_REDACT_MARKERS = ("authorization", "api-key", "apikey", "token", "secret", "cookie", "password")


def redact_headers(headers: dict[str, str] | None, redact: set[str] | None = None) -> dict[str, object]:
    """Redact sensitive headers case-insensitively, preserving the rest verbatim.

    Sensitive values become ``{"redacted": True, "length": N}`` — the same marker
    shape as ``_redact_content``. Non-sensitive header names/values are kept because
    they are the drift signal (``anthropic-version``, ``anthropic-beta`` flags).
    ``redact`` is the explicit denylist (union of defaults + ``AuditConfig.redact_headers``);
    a substring fallback also catches credential-bearing names not in the list.
    """
    if not headers:
        return {}
    redact_lc = {h.lower() for h in (redact or set())}
    out: dict[str, object] = {}
    for key, value in headers.items():
        key_lc = key.lower()
        if key_lc in redact_lc or any(marker in key_lc for marker in _SUBSTRING_REDACT_MARKERS):
            out[key] = {"redacted": True, "length": len(value) if isinstance(value, str) else 0}
        else:
            out[key] = value
    return out


def _active_request_log_shard(logs_dir: Path, datestamp: str, pid: str, max_file_mb: int) -> Path:
    """Pick the request-log shard to append to, rolling to a numbered shard once the active one
    reaches ``max_file_mb`` (0 = unbounded, single shard). seq 0 keeps the historical name."""

    def _shard(seq: int) -> Path:
        suffix = "" if seq == 0 else f".{seq}"
        return logs_dir / f"{datestamp}_requests.{pid}{suffix}.jsonl"

    if max_file_mb <= 0:
        return _shard(0)
    cap = max_file_mb * 1024 * 1024
    seq = 0
    while True:
        shard = _shard(seq)
        try:
            if not shard.exists() or shard.stat().st_size < cap:
                return shard
        except OSError:
            return shard
        seq += 1


def prune_request_logs(*, retention_days: int, max_total_mb: int) -> None:
    """Bound the request-diagnostics shards under ``~/.forge/logs/requests/`` (proxy_log_hygiene).

    Per-proxy budget enforced at proxy startup; the global ``log_retention_days`` sweep remains a
    coarse floor over all of ``logs/``. Best-effort (shared pruner swallows errors)."""
    from forge.core.state import prune_jsonl_shards

    prune_jsonl_shards(
        get_forge_home() / "logs" / "requests",
        retention_days=retention_days,
        max_total_mb=max_total_mb,
        pattern="*_requests.*.jsonl",
    )


def request_logging_enabled(request_log: object | None) -> bool:
    """Whether request JSONL diagnostics should be written (proxy_log_hygiene).

    Duck-typed on the per-proxy ``RequestLogConfig`` so callers need not import it:
    ``auto`` (default) preserves the historical coupling to ``log_level=debug``; ``on`` writes
    regardless of log level; ``off`` disables. A ``None`` config is treated as ``auto``.
    """
    enabled = getattr(request_log, "enabled", "auto")
    if enabled == "off":
        return False
    if enabled == "on":
        return True
    return _should_write_structured_logs()  # "auto"


async def log_request_response(
    request_id: str,
    original_model: str,
    mapped_model: str,
    request_body: dict[str, object],
    response_body: dict[str, object] | None,
    status_code: int,
    duration_ms: float,
    error: str | None = None,
    num_messages: int | None = None,
    num_tools: int | None = None,
    tool_names: list[str] | None = None,
    has_system: bool = False,
    temperature: float | None = None,
    max_tokens: int | None = None,
    streaming: bool = False,
    request_log: object | None = None,
) -> None:
    """Log sanitized request/response metadata to JSONL for debugging.

    Gated by the per-proxy ``RequestLogConfig`` (``request_log``): ``enabled`` decides whether
    to write, and ``body_capture``/``response_capture`` choose metadata-only vs redacted-structure
    bodies. There is no plaintext mode -- bodies are always redacted (audit policy). On failure
    (status >= 400) a summary is also logged at INFO; these logs are not replay fixtures.

    Args:
        request_id: Unique request identifier
        original_model: Original model name requested
        mapped_model: Actual model used after mapping
        request_body: Request payload (redacted before write; omitted in metadata mode)
        response_body: Response payload (redacted before write; None for streaming)
        status_code: HTTP status code
        duration_ms: Request duration in milliseconds
        error: Error message if request failed
        num_messages: Number of messages in request
        num_tools: Number of tools in request
        tool_names: List of tool names in request
        has_system: Whether request has system message
        temperature: Temperature parameter
        max_tokens: Max tokens parameter
        streaming: Whether request is streaming
        request_log: Per-proxy RequestLogConfig (None -> historical auto behavior)
    """
    if not request_logging_enabled(request_log):
        return

    body_capture = getattr(request_log, "body_capture", "metadata")
    response_capture = getattr(request_log, "response_capture", "metadata")
    max_file_mb = getattr(request_log, "max_file_mb", 0)

    try:
        logs_dir = get_forge_home() / "logs" / "requests"
        logs_dir.mkdir(exist_ok=True, parents=True)

        datestamp = datetime.now(timezone.utc).strftime("%Y%m%d")
        jsonl_path = _active_request_log_shard(logs_dir, datestamp, _pid_suffix(), max_file_mb)

        event: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "request_id": request_id,
            "original_model": original_model,
            "mapped_model": mapped_model,
            "num_messages": num_messages,
            "num_tools": num_tools,
            "tool_names": tool_names,
            "has_system": has_system,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "streaming": streaming,
            "status_code": status_code,
            "duration_ms": duration_ms,
            "error": error,
        }

        is_failure = status_code >= 400

        # metadata mode (default) omits bodies entirely; redacted mode includes the
        # sanitized structure (never plaintext -- audit redacted-body policy).
        if body_capture == "redacted":
            event["request_body"] = _redact_body_for_log(request_body)
        if response_capture == "redacted":
            event["response_body"] = _redact_body_for_log(response_body)

        from forge.core.state import open_secure_append

        async with _request_response_lock:
            with open_secure_append(jsonl_path) as f:
                f.write(json.dumps(event, default=str) + "\n")

        if is_failure:
            _logger.info(
                "[%s] Request/Response logged (FAILURE): status=%s, model=%s->%s, "
                "messages=%s, tools=%s, duration=%sms, error=%s",
                request_id,
                status_code,
                original_model,
                mapped_model,
                num_messages,
                num_tools,
                duration_ms,
                error,
            )
            _logger.info(
                "[%s] Failed request details: tools=%s, temp=%s, max_tokens=%s",
                request_id,
                tool_names,
                temperature,
                max_tokens,
            )
        else:
            _logger.debug(
                "[%s] Request/Response logged: status=%s, model=%s->%s, " "messages=%s, tools=%s, duration=%sms",
                request_id,
                status_code,
                original_model,
                mapped_model,
                num_messages,
                num_tools,
                duration_ms,
            )

    except Exception as e:
        _logger.error(
            "Failed to log request/response: %s (request_id=%s)",
            e,
            request_id,
            exc_info=True,
        )
