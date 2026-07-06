"""Regression: status-line transcript role aliases were not normalized.

Bug: ``src/forge/cli/status_line.py`` carried a local role resolver that only
recognized ``user``/``assistant``. Older Claude transcript entries can use
``human``/``ai`` in either top-level ``type`` or nested ``message.role`` fields,
so status-line counts silently missed user turns and assistant tool calls.

Root cause / fix: ``src/forge/cli/status_line.py`` now uses the shared
``forge.core.transcript.resolve_entry_role`` primitive instead of a divergent
local copy.
"""

from __future__ import annotations

import json

import pytest

from forge.cli import status_line as sl

pytestmark = pytest.mark.regression


def test_status_line_normalizes_transcript_role_aliases(tmp_path):
    assert sl.resolve_entry_role({"type": "human"}) == "user"
    assert sl.resolve_entry_role({"type": "ai"}) == "assistant"
    assert sl.resolve_entry_role({"message": {"role": "human"}}) == "user"
    assert sl.resolve_entry_role({"message": {"role": "ai"}}) == "assistant"

    transcript = tmp_path / "transcript.jsonl"
    entries = [
        {"type": "human", "text": "older user turn"},
        {"type": "ai", "message": {"content": [{"type": "tool_use", "name": "Read"}]}},
        {"message": {"role": "human", "content": [{"type": "text", "text": "newer user turn"}]}},
        {"message": {"role": "ai", "content": [{"type": "tool_use", "name": "Write"}]}},
    ]
    transcript.write_text("\n".join(json.dumps(entry) for entry in entries), encoding="utf-8")

    stats = sl.scan_transcript(str(transcript))

    assert stats.user_count == 2
    assert stats.tool_count == 2
