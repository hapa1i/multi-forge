"""Content extraction from JSONL transcripts for search indexing.

Extracts searchable text from Forge transcript artifacts, producing one
SearchDocument per transcript file. Content extraction rules (design.md §5.5):
- User/assistant text messages: fully indexed
- Tool inputs (file paths, commands): truncated to 100 chars
- Tool results: truncated to 500 chars

Uses shared parsing primitives from forge.core.transcript.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from forge.core.state import now_iso
from forge.core.transcript import parse_jsonl_transcript, truncate

from .tokenizer import tokenize

# --- Data classes ---

logger = logging.getLogger(__name__)

# Truncation limits
TOOL_RESULT_TRUNCATE_CHARS = 500
TOOL_ARG_TRUNCATE_CHARS = 100


@dataclass
class SearchDocumentMeta:
    """Metadata-only view of a search document (no content, no tokens).

    Used by the v2 document store for lightweight persistence and by
    search_from_index() for result construction.
    """

    transcript_path: str  # Absolute path (JSON-serializable key)
    session_name: str
    session_id: str
    extracted_at: str  # ISO8601
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for JSON storage."""
        return asdict(self)


@dataclass
class SearchDocument:
    """Extracted content from a single transcript file for search indexing.

    Full extraction output including content and tokens. Used at extraction
    time; callers decompose into metadata, term frequencies, and content
    for the three-store architecture via decompose_document().
    """

    transcript_path: str  # Absolute path (JSON-serializable key)
    session_name: str
    session_id: str
    content: str  # Full extracted text for BM25 indexing
    extracted_at: str  # ISO8601
    metadata: dict[str, Any] = field(default_factory=dict)
    tokens: list[str] | None = None  # Cached tokenization (used at extraction time)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for JSON storage."""
        return asdict(self)


def extract_document(
    transcript_path: Path,
    session_name: str,
    session_id: str,
    worktree_path: str,
) -> SearchDocument:
    """Extract searchable content from a JSONL transcript file.

    Parses each JSONL line and extracts:
    - User/assistant text messages (full)
    - Tool use summaries (name + key args, truncated)
    - Tool results (truncated to 500 chars)

    Args:
        transcript_path: Absolute path to the .jsonl transcript file.
        session_name: Forge session name.
        session_id: Claude session UUID.
        worktree_path: Worktree path where session ran.

    Returns:
        SearchDocument with extracted content and metadata.

    Raises:
        FileNotFoundError: If transcript_path does not exist.
    """
    if not transcript_path.is_file():
        raise FileNotFoundError(str(transcript_path))

    entries = parse_jsonl_transcript(transcript_path)
    parts: list[str] = []
    message_count = 0
    first_ts = ""
    last_ts = ""

    for entry in entries:
        extracted = _extract_entry_text(entry)
        if extracted is None:
            continue

        role, text, timestamp = extracted
        parts.append(f"[{role}] {text}")
        message_count += 1

        if timestamp:
            if not first_ts:
                first_ts = timestamp
            last_ts = timestamp

    content = "\n".join(parts)

    return SearchDocument(
        transcript_path=str(transcript_path),
        session_name=session_name,
        session_id=session_id,
        content=content,
        extracted_at=now_iso(),
        metadata={
            "message_count": message_count,
            "first_timestamp": first_ts,
            "last_timestamp": last_ts,
            "worktree_path": worktree_path,
        },
        tokens=tokenize(content),
    )


def _extract_entry_text(entry: dict[str, Any]) -> tuple[str, str, str] | None:
    """Extract text content from a single transcript entry.

    Returns:
        (role, text, timestamp) tuple, or None if entry is not a valid message.
    """
    message = entry.get("message")
    if not isinstance(message, dict):
        return None

    role = message.get("role")
    if role not in ("user", "assistant"):
        return None

    content = message.get("content")
    if not isinstance(content, list):
        return None

    text_parts: list[str] = []

    for block in content:
        if not isinstance(block, dict):
            continue

        block_type = block.get("type")

        if block_type == "text":
            t = block.get("text")
            if isinstance(t, str) and t:
                text_parts.append(t)

        elif block_type == "tool_use":
            name = block.get("name", "unknown")
            inp = block.get("input", {})
            if isinstance(inp, dict):
                path = inp.get("file_path") or inp.get("path")
                cmd = inp.get("command")
                if path:
                    text_parts.append(f"{name}(path={truncate(str(path), TOOL_ARG_TRUNCATE_CHARS)})")
                elif cmd:
                    text_parts.append(f"{name}(command={truncate(str(cmd), TOOL_ARG_TRUNCATE_CHARS)})")
                else:
                    text_parts.append(f"{name}(...)")
            else:
                text_parts.append(f"{name}(...)")

        elif block_type == "tool_result":
            result = block.get("content", "")
            # Handle non-string tool results (dict/list in some Claude versions)
            if not isinstance(result, str):
                try:
                    result = json.dumps(result, ensure_ascii=False)
                except (TypeError, ValueError):
                    result = str(result)
            if result:
                text_parts.append(f"[result: {truncate(result, TOOL_RESULT_TRUNCATE_CHARS)}]")

    if not text_parts:
        return None

    timestamp = entry.get("timestamp", "")
    if not isinstance(timestamp, str):
        timestamp = ""

    return role, " ".join(text_parts), timestamp


# --- Decomposition (full document → three-store components) ---


def decompose_document(
    doc: SearchDocument,
) -> tuple[SearchDocumentMeta, dict[str, int], int, str]:
    """Decompose a full SearchDocument into components for the three-store architecture.

    Returns:
        (metadata, term_freq, doc_len, content) where:
        - metadata: SearchDocumentMeta for the document store
        - term_freq: term frequency dict for the BM25 index store
        - doc_len: token count for BM25 length normalization
        - content: raw content string for the content store
    """
    tokens = doc.tokens if doc.tokens is not None else tokenize(doc.content)
    tf: dict[str, int] = {}
    for t in tokens:
        tf[t] = tf.get(t, 0) + 1
    meta = SearchDocumentMeta(
        transcript_path=doc.transcript_path,
        session_name=doc.session_name,
        session_id=doc.session_id,
        extracted_at=doc.extracted_at,
        metadata=doc.metadata,
    )
    return meta, tf, len(tokens), doc.content
