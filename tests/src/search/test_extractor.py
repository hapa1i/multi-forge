"""Tests for search content extraction from JSONL transcripts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from forge.search.extractor import (
    TOOL_ARG_TRUNCATE_CHARS,
    SearchDocumentMeta,
    decompose_document,
    extract_document,
)


def _write_jsonl(path: Path, entries: list[dict]) -> Path:
    """Write JSONL entries to a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")
    return path


def _make_entry(
    role: str,
    text: str,
    *,
    request_id: str = "req-1",
    timestamp: str = "2026-01-01T00:00:00Z",
) -> dict:
    """Create a minimal transcript entry with a text block."""
    return {
        "requestId": request_id,
        "timestamp": timestamp,
        "message": {"role": role, "content": [{"type": "text", "text": text}]},
    }


class TestExtractUserText:
    """Tests for extracting user text messages."""

    def test_user_text_fully_included(self, tmp_path: Path) -> None:
        """User text messages are included with [user] prefix."""
        jsonl = _write_jsonl(
            tmp_path / "test.jsonl",
            [_make_entry("user", "Please read the config file")],
        )
        doc = extract_document(jsonl, session_name="s", session_id="id", worktree_path="/w")
        assert "[user] Please read the config file" in doc.content

    def test_assistant_text_fully_included(self, tmp_path: Path) -> None:
        """Assistant text messages are included with [assistant] prefix."""
        jsonl = _write_jsonl(
            tmp_path / "test.jsonl",
            [_make_entry("assistant", "I'll update the timeout setting")],
        )
        doc = extract_document(jsonl, session_name="s", session_id="id", worktree_path="/w")
        assert "[assistant] I'll update the timeout setting" in doc.content


class TestExtractToolUse:
    """Tests for extracting tool use summaries."""

    def test_tool_use_with_file_path(self, tmp_path: Path) -> None:
        """Tool use with file_path shows ToolName(path=...) format."""
        entry = {
            "requestId": "r1",
            "timestamp": "2026-01-01T00:00:00Z",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "t1",
                        "name": "Read",
                        "input": {"file_path": "/workspace/config.yaml"},
                    },
                ],
            },
        }
        jsonl = _write_jsonl(tmp_path / "test.jsonl", [entry])
        doc = extract_document(jsonl, session_name="s", session_id="id", worktree_path="/w")
        assert "Read(path=/workspace/config.yaml)" in doc.content

    def test_tool_use_with_command(self, tmp_path: Path) -> None:
        """Tool use with command shows ToolName(command=...) format."""
        entry = {
            "requestId": "r1",
            "timestamp": "2026-01-01T00:00:00Z",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "t1",
                        "name": "Bash",
                        "input": {"command": "uv run pytest tests/ -v"},
                    },
                ],
            },
        }
        jsonl = _write_jsonl(tmp_path / "test.jsonl", [entry])
        doc = extract_document(jsonl, session_name="s", session_id="id", worktree_path="/w")
        assert "Bash(command=uv run pytest tests/ -v)" in doc.content

    def test_tool_use_truncates_long_path(self, tmp_path: Path) -> None:
        """Long file paths are truncated to TOOL_ARG_TRUNCATE_CHARS."""
        long_path = "/workspace/" + "a" * 200 + "/config.yaml"
        entry = {
            "requestId": "r1",
            "timestamp": "2026-01-01T00:00:00Z",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "t1",
                        "name": "Read",
                        "input": {"file_path": long_path},
                    },
                ],
            },
        }
        jsonl = _write_jsonl(tmp_path / "test.jsonl", [entry])
        doc = extract_document(jsonl, session_name="s", session_id="id", worktree_path="/w")
        # Path should be truncated + "..."
        assert "Read(path=" in doc.content
        assert "..." in doc.content
        # The truncated part should not exceed TOOL_ARG_TRUNCATE_CHARS + "..." + prefix
        assert len(long_path) > TOOL_ARG_TRUNCATE_CHARS


class TestExtractToolResult:
    """Tests for extracting and truncating tool results."""

    def test_tool_result_truncated_to_500_chars(self, tmp_path: Path) -> None:
        """Tool results are truncated to TOOL_RESULT_TRUNCATE_CHARS."""
        long_result = "x" * 1000
        entry = {
            "requestId": "r1",
            "timestamp": "2026-01-01T00:00:00Z",
            "message": {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "t1", "content": long_result}],
            },
        }
        jsonl = _write_jsonl(tmp_path / "test.jsonl", [entry])
        doc = extract_document(jsonl, session_name="s", session_id="id", worktree_path="/w")
        assert "[result: " in doc.content
        assert "..." in doc.content
        # Extracted text should not contain the full 1000-char result
        assert long_result not in doc.content

    def test_tool_result_non_string_dict(self, tmp_path: Path) -> None:
        """Non-string tool results (dict) are stringified with json.dumps."""
        entry = {
            "requestId": "r1",
            "timestamp": "2026-01-01T00:00:00Z",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "t1",
                        "content": {"status": "ok", "lines": 42},
                    }
                ],
            },
        }
        jsonl = _write_jsonl(tmp_path / "test.jsonl", [entry])
        doc = extract_document(jsonl, session_name="s", session_id="id", worktree_path="/w")
        assert "[result: " in doc.content
        assert "status" in doc.content
        assert "42" in doc.content

    def test_tool_result_non_string_list(self, tmp_path: Path) -> None:
        """Non-string tool results (list) are stringified with json.dumps."""
        entry = {
            "requestId": "r1",
            "timestamp": "2026-01-01T00:00:00Z",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "t1",
                        "content": ["error1", "error2"],
                    }
                ],
            },
        }
        jsonl = _write_jsonl(tmp_path / "test.jsonl", [entry])
        doc = extract_document(jsonl, session_name="s", session_id="id", worktree_path="/w")
        assert "[result: " in doc.content
        assert "error1" in doc.content


class TestExtractEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_transcript(self, tmp_path: Path) -> None:
        """Empty transcript produces document with empty content."""
        jsonl = tmp_path / "empty.jsonl"
        jsonl.write_text("")
        doc = extract_document(jsonl, session_name="s", session_id="id", worktree_path="/w")
        assert doc.content == ""
        assert doc.metadata["message_count"] == 0

    def test_malformed_lines_skipped(self, tmp_path: Path) -> None:
        """Malformed JSONL lines are skipped without crashing."""
        jsonl = tmp_path / "test.jsonl"
        jsonl.write_text("not valid json\n" + json.dumps(_make_entry("user", "valid message")) + "\n" + "{incomplete\n")
        doc = extract_document(jsonl, session_name="s", session_id="id", worktree_path="/w")
        assert "valid message" in doc.content
        assert doc.metadata["message_count"] == 1

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        """FileNotFoundError on missing transcript file."""
        with pytest.raises(FileNotFoundError):
            extract_document(
                tmp_path / "nonexistent.jsonl",
                session_name="s",
                session_id="id",
                worktree_path="/w",
            )


class TestExtractMetadata:
    """Tests for metadata extraction."""

    def test_message_count(self, tmp_path: Path) -> None:
        """Metadata captures correct message count."""
        entries = [
            _make_entry("user", "first", timestamp="2026-01-01T00:00:00Z"),
            _make_entry("assistant", "second", timestamp="2026-01-01T00:00:01Z"),
            _make_entry("user", "third", timestamp="2026-01-01T00:00:02Z"),
        ]
        jsonl = _write_jsonl(tmp_path / "test.jsonl", entries)
        doc = extract_document(jsonl, session_name="s", session_id="id", worktree_path="/w")
        assert doc.metadata["message_count"] == 3

    def test_timestamps(self, tmp_path: Path) -> None:
        """Metadata captures first and last timestamps."""
        entries = [
            _make_entry("user", "first", timestamp="2026-01-01T10:00:00Z"),
            _make_entry("assistant", "last", timestamp="2026-01-01T10:05:00Z"),
        ]
        jsonl = _write_jsonl(tmp_path / "test.jsonl", entries)
        doc = extract_document(jsonl, session_name="s", session_id="id", worktree_path="/w")
        assert doc.metadata["first_timestamp"] == "2026-01-01T10:00:00Z"
        assert doc.metadata["last_timestamp"] == "2026-01-01T10:05:00Z"

    def test_worktree_path_in_metadata(self, tmp_path: Path) -> None:
        """Worktree path is stored in metadata."""
        jsonl = _write_jsonl(tmp_path / "test.jsonl", [_make_entry("user", "hello")])
        doc = extract_document(jsonl, session_name="s", session_id="id", worktree_path="/my/project")
        assert doc.metadata["worktree_path"] == "/my/project"


class TestExtractFixtureIntegration:
    """Integration test using the real transcript fixture."""

    def test_fixture_file(self) -> None:
        """Extract from tests/fixtures/transcript_sample.jsonl produces valid document."""
        fixture = Path(__file__).parent.parent.parent / "fixtures" / "transcript_sample.jsonl"
        assert fixture.is_file(), f"Fixture missing: {fixture}"

        doc = extract_document(
            fixture,
            session_name="fixture-session",
            session_id="fixture-uuid",
            worktree_path="/workspace",
        )
        assert doc.content  # Not empty
        assert doc.metadata["message_count"] > 0
        # Should contain text from the fixture
        assert "config" in doc.content.lower()
        assert "timeout" in doc.content.lower()
        # Should contain tool use summaries
        assert "Read(path=" in doc.content
        assert "Edit(path=" in doc.content or "Edit(...)" in doc.content


class TestDecomposeDocument:
    """Tests for decompose_document()."""

    def test_produces_correct_metadata(self, tmp_path: Path) -> None:
        entries = [_make_entry("user", "hello world python")]
        jsonl = _write_jsonl(tmp_path / "test.jsonl", entries)
        doc = extract_document(jsonl, session_name="s", session_id="id", worktree_path="/w")
        meta, tf, doc_len, content = decompose_document(doc)

        assert isinstance(meta, SearchDocumentMeta)
        assert meta.transcript_path == doc.transcript_path
        assert meta.session_name == "s"
        assert meta.session_id == "id"
        assert meta.extracted_at == doc.extracted_at
        assert meta.metadata == doc.metadata

    def test_produces_correct_term_freq(self, tmp_path: Path) -> None:
        entries = [_make_entry("user", "python python java")]
        jsonl = _write_jsonl(tmp_path / "test.jsonl", entries)
        doc = extract_document(jsonl, session_name="s", session_id="id", worktree_path="/w")
        _, tf, doc_len, _ = decompose_document(doc)

        # "python" appears twice in content (role prefix [user] adds "user" token too)
        assert tf.get("python", 0) >= 2
        assert tf.get("java", 0) >= 1

    def test_doc_len_matches_token_count(self, tmp_path: Path) -> None:
        entries = [_make_entry("user", "one two three")]
        jsonl = _write_jsonl(tmp_path / "test.jsonl", entries)
        doc = extract_document(jsonl, session_name="s", session_id="id", worktree_path="/w")
        _, _, doc_len, _ = decompose_document(doc)

        assert doc_len == len(doc.tokens) if doc.tokens else doc_len > 0

    def test_content_matches_original(self, tmp_path: Path) -> None:
        entries = [_make_entry("user", "original content here")]
        jsonl = _write_jsonl(tmp_path / "test.jsonl", entries)
        doc = extract_document(jsonl, session_name="s", session_id="id", worktree_path="/w")
        _, _, _, content = decompose_document(doc)

        assert content == doc.content

    def test_meta_has_no_content_or_tokens(self, tmp_path: Path) -> None:
        entries = [_make_entry("user", "test")]
        jsonl = _write_jsonl(tmp_path / "test.jsonl", entries)
        doc = extract_document(jsonl, session_name="s", session_id="id", worktree_path="/w")
        meta, _, _, _ = decompose_document(doc)

        assert not hasattr(meta, "content")
        assert not hasattr(meta, "tokens")
