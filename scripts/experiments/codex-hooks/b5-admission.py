#!/usr/bin/env python3
"""Offline B5 boundary prototype for the observed 0.162.1 rollout shapes.

This does not authorize inference. Installed admission must also bind trusted hook
identity, effective config, reviewer auth and immutable-copy ownership.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Any

from forge.core.runtime.codex_rollouts import find_rollouts_by_thread_id

MAX_BYTES = 2_000_000
MAX_FILES = 2  # Only a root plus one native fork generation was loaded in this round.
THREAD_ID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")


def select_prefixes(
    home: Path,
    source_id: str,
    *,
    end_bytes: int | None = None,
    stop: dict[str, Any] | None = None,
    max_bytes: int = MAX_BYTES,
) -> list[dict[str, Any]]:
    """Read one observed closure without following ambiguous or unfinished input."""
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    thread = source_id
    ordinal = None
    while True:
        if not THREAD_ID.fullmatch(thread):
            raise ValueError("Unrecognized thread identity")
        if thread in seen:
            raise ValueError("Cyclic native ancestry")
        if len(seen) >= MAX_FILES:
            raise ValueError("Untested ancestry depth")
        seen.add(thread)
        paths = find_rollouts_by_thread_id(thread, home=home)
        if len(paths) != 1:
            raise ValueError("Missing or ambiguous rollout")
        path = paths[0]
        data = _read_prefix(path, home, end_bytes, max_bytes - sum(len(row["data"]) for row in selected))
        rows = [json.loads(line) for line in data.splitlines()]
        if any(not isinstance(row, dict) or not isinstance(row.get("payload"), dict) for row in rows):
            raise ValueError("Malformed native record")
        if ordinal is not None and len(rows) != ordinal:
            raise ValueError("Ancestor byte and ordinal boundaries disagree")
        meta = rows[0]["payload"]
        if rows[0].get("type") != "session_meta" or meta.get("id") != thread or meta.get("session_id") != thread:
            raise ValueError("Native metadata identity mismatch")
        if meta.get("cli_version") != "0.162.1" or meta.get("history_mode") != "paginated":
            raise ValueError("Unproven native history format")
        _check_boundary(rows, stop if not selected else None, path)
        selected.append({"thread_id": thread, "path": path, "data": data, "sha256": hashlib.sha256(data).hexdigest()})
        base = meta.get("history_base")
        if base is None:
            if meta.get("forked_from_id") is not None or meta.get("forked_from_ordinal_exclusive") is not None:
                raise ValueError("Missing native history base")
            return selected
        if not isinstance(base, dict) or set(base) != {"thread_id", "end_ordinal_exclusive", "end_byte_offset"}:
            raise ValueError("Unrecognized native history base")
        parent = base["thread_id"]
        ordinal, end_bytes = base["end_ordinal_exclusive"], base["end_byte_offset"]
        if (
            not isinstance(parent, str)
            or type(ordinal) is not int
            or type(end_bytes) is not int
            or ordinal <= 0
            or end_bytes <= 0
            or meta.get("forked_from_id") != parent
            or meta.get("forked_from_ordinal_exclusive") != ordinal
        ):
            raise ValueError("Inconsistent native ancestry")
        thread = parent


def require_plan(source_ids: set[str], executor_ids: set[str] | None, plan: str, *, trigger: str) -> str:
    """Refuse plan-less shared/unknown and Stop cases before a native start."""
    independence = "unknown" if executor_ids is None else "shared" if source_ids & executor_ids else "separate"
    if (trigger == "stop" or independence != "separate") and not plan.strip():
        raise ValueError("An approved plan is required")
    return independence


def _read_prefix(path: Path, home: Path, end: int | None, remaining: int) -> bytes:
    if remaining <= 0 or (end is not None and (type(end) is not int or end <= 0 or end > remaining)):
        raise ValueError("Native input exceeds byte limit")
    relative = path.relative_to(home)
    if home.is_symlink() or any(
        (home / Path(*relative.parts[:i])).is_symlink() for i in range(1, len(relative.parts) + 1)
    ):
        raise ValueError("Symlinked native input")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("Native input is not a regular file")
        data = stream.read(end if end is not None else remaining + 1)
        after = os.fstat(stream.fileno())
    if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
        raise ValueError("Native input changed while reading")
    if len(data) > remaining or (end is not None and len(data) != end):
        raise ValueError("Native input exceeds limit or ancestor prefix is missing")
    if not data or not data.endswith(b"\n"):
        raise ValueError("Incomplete JSONL boundary")
    return data


def _check_boundary(rows: list[dict[str, Any]], stop: dict[str, Any] | None, path: Path) -> None:
    pending: set[str] = set()
    latest_start = None
    latest_finish = None
    latest_message = None
    for row in rows:
        payload = row["payload"]
        kind = payload.get("type")
        if row.get("type") == "response_item":
            if kind in {"function_call", "custom_tool_call", "function_call_output", "custom_tool_call_output"}:
                call = payload.get("call_id")
                if not isinstance(call, str) or not call:
                    raise ValueError("Missing native call identity")
                if kind.endswith("_output"):
                    if call not in pending:
                        raise ValueError("Unmatched native call output")
                    pending.remove(call)
                elif call in pending:
                    raise ValueError("Duplicate native call")
                else:
                    pending.add(call)
            elif kind == "message" and payload.get("role") == "assistant":
                latest_message = payload
        elif row.get("type") == "event_msg":
            if kind == "task_started":
                latest_start, latest_finish, latest_message = payload.get("turn_id"), None, None
            elif kind == "task_complete":
                latest_finish = payload.get("turn_id")
    if pending:
        raise ValueError("Unfinished native tool exchange")
    if not latest_start:
        raise ValueError("Unknown native turn boundary")
    if stop is None:
        if latest_finish != latest_start:
            raise ValueError("Native turn is not complete")
        return
    text = (
        "".join(item.get("text", "") for item in latest_message.get("content", []) if item.get("type") == "output_text")
        if latest_message
        else None
    )
    if (
        stop.get("hook_event_name") != "Stop"
        or stop.get("session_id") != rows[0]["payload"]["id"]
        or stop.get("turn_id") != latest_start
        or stop.get("transcript_path") != str(path)
        or latest_finish is not None
        or not latest_message
        or latest_message.get("phase") != "final_answer"
        or not text
        or text != stop.get("last_assistant_message")
    ):
        raise ValueError("Stop boundary does not match captured native final answer")
