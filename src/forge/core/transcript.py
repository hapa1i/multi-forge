"""Shared JSONL transcript parsing primitives.

Low-level parsing of Claude Code transcript files. Used by:
- forge.search.extractor (content extraction for search indexing)
- forge.session.handoff (context assembly for session resume)

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


def truncate(text: str, max_chars: int) -> str:
    """Truncate text to max_chars, appending '...' if truncated."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "..."
