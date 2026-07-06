"""Shared JSONL transcript parsing primitives.

Low-level parsing of Claude Code transcript files. Used by:
- forge.cli.status_line (cheap transcript statistics for the prompt status line)
- forge.search.extractor (content extraction for search indexing)
- forge.session.rewind (turn-boundary detection for rewind resumes)
- forge.session.transfer (context assembly for session resume)

Only parsing primitives live here — extraction/summarization logic stays
in each consumer module since they produce different output formats.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def parse_jsonl_transcript(path: Path) -> list[dict[str, Any]]:
    """Parse a Claude transcript JSONL file, sorted by timestamp.

    Handles both formats:
    - requestId/message.role (newer Claude Code)
    - entry.type (older Claude Code)

    Entries without "message" or "type" keys are silently skipped.
    Malformed lines are skipped with a debug log.

    Returns:
        List of parsed entries sorted by timestamp. Empty list on read errors.
    """
    entries: list[dict[str, Any]] = []

    if not path.is_file():
        return entries

    try:
        with path.open(encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    logger.debug("Skipping malformed JSON at line %d in %s", line_num, path)
                    continue

                if "message" not in entry and "type" not in entry:
                    continue

                entries.append(entry)
    except Exception as e:
        logger.warning("Error reading transcript %s: %s", path, e)
        return []

    entries.sort(key=_get_timestamp)
    return entries


def _get_timestamp(entry: dict[str, Any]) -> str:
    """Extract timestamp from a transcript entry for sorting.

    Checks top-level "timestamp" first, then "message.timestamp".
    """
    ts = entry.get("timestamp", "")
    if not ts and "message" in entry:
        ts = entry.get("message", {}).get("timestamp", "")
    return ts if isinstance(ts, str) else ""


def normalize_transcript_role(raw_role: Any) -> str | None:
    """Normalize transcript role names across Claude transcript formats."""
    if raw_role in ("user", "human"):
        return "user"
    if raw_role in ("assistant", "ai"):
        return "assistant"
    return None


def resolve_entry_role(entry: dict[str, Any]) -> str | None:
    """Resolve an entry role from a Claude transcript entry.

    System boundary: handles both Claude Code transcript formats:
    - Modern: {"message": {"role": "assistant", ...}}
    - Older: {"type": "assistant", ...}
    """
    message = entry.get("message")
    if isinstance(message, dict):
        resolved = normalize_transcript_role(message.get("role"))
        if resolved is not None:
            return resolved

    return normalize_transcript_role(entry.get("type"))


def extract_entry_blocks(entry: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract normalized content blocks from a Claude transcript entry.

    System boundary: handles both modern (message.content) and older
    (entry.content / entry.text) Claude Code transcript formats.
    """
    message = entry.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, list):
            return [block for block in content if isinstance(block, dict)]
        if isinstance(content, str) and content:
            return [{"type": "text", "text": content}]

    content = entry.get("content")
    if isinstance(content, list):
        return [block for block in content if isinstance(block, dict)]
    if isinstance(content, str) and content:
        return [{"type": "text", "text": content}]

    text = entry.get("text")
    if isinstance(text, str) and text:
        return [{"type": "text", "text": text}]

    return []


def group_entries_into_turns(entries: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Group transcript entries into conversational turns.

    Modern Claude transcripts use request IDs to tie user/tool/assistant events
    together. Older or alternate formats may omit request IDs entirely, so we
    fall back to grouping sequentially from each user/human turn.
    """

    grouped_turns: list[list[dict[str, Any]]] = []
    request_groups: dict[str, list[dict[str, Any]]] = {}
    current_fallback_group: list[dict[str, Any]] | None = None

    for entry in entries:
        request_id = entry.get("requestId")
        if isinstance(request_id, str) and request_id:
            current_fallback_group = None
            group = request_groups.get(request_id)
            if group is None:
                group = []
                request_groups[request_id] = group
                grouped_turns.append(group)
            group.append(entry)
            continue

        role = resolve_entry_role(entry)
        if role == "user":
            current_fallback_group = [entry]
            grouped_turns.append(current_fallback_group)
        elif current_fallback_group is not None:
            current_fallback_group.append(entry)
        elif role == "assistant":
            current_fallback_group = [entry]
            grouped_turns.append(current_fallback_group)

    return grouped_turns


def truncate(text: str, max_chars: int) -> str:
    """Truncate text to max_chars, appending '...' if truncated."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "..."
