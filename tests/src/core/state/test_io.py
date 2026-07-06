"""Tests for core.state.io module."""

import json
import stat
from pathlib import Path
from unittest.mock import patch

import pytest

from forge.core.state import (
    StateCorruptedError,
    StateNotFoundError,
    atomic_write_bytes,
    atomic_write_json,
    atomic_write_text,
    decode_json_object,
    read_json,
)


class TestDecodeJsonObject:
    """The shared JSONL guard every cost/usage/audit reader routes through.

    A valid-but-non-object line must be skipped (None), never crashed on with a
    ``.get`` AttributeError on a list/scalar."""

    def test_decodes_a_json_object(self) -> None:
        assert decode_json_object('{"a": 1}') == {"a": 1}

    def test_strips_and_decodes(self) -> None:
        assert decode_json_object('  {"a": 1}\n') == {"a": 1}

    @pytest.mark.parametrize("line", ["", "   ", "\n"])
    def test_blank_line_is_none(self, line: str) -> None:
        assert decode_json_object(line) is None

    def test_malformed_json_is_none(self) -> None:
        assert decode_json_object("{not json") is None

    @pytest.mark.parametrize("line", ["[]", "1", '"x"', "null", "true", "[1, 2]"])
    def test_valid_but_non_object_is_none(self, line: str) -> None:
        # The whole point: these are valid JSON but not dicts -> skip, don't crash.
        assert decode_json_object(line) is None


class TestAtomicWriteText:
    """Tests for atomic_write_text function."""

    def test_writes_content(self, tmp_path: Path) -> None:
        """atomic_write_text writes the content to the file."""
        target = tmp_path / "test.txt"
        atomic_write_text(target, "hello world")
        assert target.read_text() == "hello world"

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        """atomic_write_text creates parent directories by default."""
        target = tmp_path / "nested" / "deep" / "test.txt"
        atomic_write_text(target, "content")
        assert target.exists()
        assert target.read_text() == "content"

    def test_respects_create_parents_false(self, tmp_path: Path) -> None:
        """atomic_write_text respects create_parents=False."""
        target = tmp_path / "nonexistent" / "test.txt"
        with pytest.raises(FileNotFoundError):
            atomic_write_text(target, "content", create_parents=False)

    def test_overwrites_existing_file(self, tmp_path: Path) -> None:
        """atomic_write_text overwrites existing file content."""
        target = tmp_path / "test.txt"
        target.write_text("original")
        atomic_write_text(target, "updated")
        assert target.read_text() == "updated"

    def test_atomic_overwrite_no_partial_writes(self, tmp_path: Path) -> None:
        """Atomic write ensures no partial content visible during overwrite."""
        target = tmp_path / "test.txt"
        original_content = "original content that should not be corrupted"
        target.write_text(original_content)

        # Simulate a write that would fail mid-way
        with patch("os.replace", side_effect=OSError("simulated failure")):
            with pytest.raises(OSError):
                atomic_write_text(target, "new content")

        # Original content should be preserved
        assert target.read_text() == original_content

    def test_cleans_up_temp_file_on_failure(self, tmp_path: Path) -> None:
        """Temp file is cleaned up if write fails."""
        target = tmp_path / "test.txt"

        with patch("os.replace", side_effect=OSError("simulated failure")):
            with pytest.raises(OSError):
                atomic_write_text(target, "content")

        # No temp files should remain (including hidden dotfiles)
        tmp_files = list(tmp_path.glob(".*.tmp")) + list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0

    def test_uses_utf8_encoding(self, tmp_path: Path) -> None:
        """atomic_write_text uses UTF-8 encoding."""
        target = tmp_path / "test.txt"
        content = "Hello 世界 🌍"
        atomic_write_text(target, content)
        # Read with explicit UTF-8 to verify
        assert target.read_text(encoding="utf-8") == content

    def test_sets_mode_when_requested(self, tmp_path: Path) -> None:
        target = tmp_path / "secure.txt"
        atomic_write_text(target, "secret", mode=0o600)
        assert stat.S_IMODE(target.stat().st_mode) == 0o600


class TestAtomicWriteBytes:
    """Tests for atomic_write_bytes function."""

    def test_writes_raw_bytes(self, tmp_path: Path) -> None:
        target = tmp_path / "data.bin"
        data = b"\xff\x00raw\nbytes"
        atomic_write_bytes(target, data)
        assert target.read_bytes() == data

    def test_sets_mode_when_requested(self, tmp_path: Path) -> None:
        target = tmp_path / "secure.bin"
        atomic_write_bytes(target, b"secret", mode=0o600)
        assert target.read_bytes() == b"secret"
        assert stat.S_IMODE(target.stat().st_mode) == 0o600


class TestAtomicWriteJson:
    """Tests for atomic_write_json function."""

    def test_writes_valid_json(self, tmp_path: Path) -> None:
        """atomic_write_json writes valid JSON."""
        target = tmp_path / "test.json"
        data = {"key": "value", "number": 42}
        atomic_write_json(target, data)

        with open(target) as f:
            loaded = json.load(f)
        assert loaded == data

    def test_adds_trailing_newline(self, tmp_path: Path) -> None:
        """atomic_write_json adds trailing newline."""
        target = tmp_path / "test.json"
        atomic_write_json(target, {"key": "value"})
        content = target.read_text()
        assert content.endswith("\n")

    def test_uses_specified_indent(self, tmp_path: Path) -> None:
        """atomic_write_json uses specified indentation."""
        target = tmp_path / "test.json"
        data = {"key": "value"}

        atomic_write_json(target, data, indent=4)
        content = target.read_text()
        # 4-space indent should produce "    " before "key"
        assert '    "key"' in content

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        """atomic_write_json creates parent directories."""
        target = tmp_path / "nested" / "test.json"
        atomic_write_json(target, {"key": "value"})
        assert target.exists()

    def test_rejects_non_serializable_types(self, tmp_path: Path) -> None:
        """atomic_write_json raises TypeError for non-serializable values (L3)."""
        target = tmp_path / "test.json"
        from pathlib import Path as P

        data = {"path": P("/some/path")}
        with pytest.raises(TypeError, match="not JSON serializable"):
            atomic_write_json(target, data)

        # File should not be created on failure
        assert not target.exists()


class TestReadJson:
    """Tests for read_json function."""

    def test_reads_valid_json(self, tmp_path: Path) -> None:
        """read_json reads and parses valid JSON."""
        target = tmp_path / "test.json"
        data = {"key": "value", "list": [1, 2, 3]}
        target.write_text(json.dumps(data))

        result = read_json(target)
        assert result == data

    def test_raises_state_not_found_for_missing_file(self, tmp_path: Path) -> None:
        """read_json raises StateNotFoundError for missing file."""
        target = tmp_path / "nonexistent.json"

        with pytest.raises(StateNotFoundError) as exc_info:
            read_json(target)

        assert str(target) in exc_info.value.path

    def test_raises_state_corrupted_for_invalid_json(self, tmp_path: Path) -> None:
        """read_json raises StateCorruptedError for invalid JSON."""
        target = tmp_path / "test.json"
        target.write_text("not valid json {{{")

        with pytest.raises(StateCorruptedError) as exc_info:
            read_json(target)

        assert str(target) in exc_info.value.path
        assert "invalid JSON" in exc_info.value.reason

    def test_raises_state_corrupted_for_non_object_json(self, tmp_path: Path) -> None:
        """read_json raises StateCorruptedError when JSON is not an object."""
        target = tmp_path / "test.json"
        target.write_text(json.dumps([1, 2, 3]))

        with pytest.raises(StateCorruptedError) as exc_info:
            read_json(target)

        assert str(target) in exc_info.value.path
        assert "expected JSON object" in exc_info.value.reason

    def test_uses_utf8_encoding(self, tmp_path: Path) -> None:
        """read_json uses UTF-8 encoding."""
        target = tmp_path / "test.json"
        data = {"message": "Hello 世界 🌍"}
        target.write_text(json.dumps(data), encoding="utf-8")

        result = read_json(target)
        assert result["message"] == "Hello 世界 🌍"


class TestRoundtrip:
    """Tests for write/read roundtrip."""

    def test_atomic_write_then_read(self, tmp_path: Path) -> None:
        """Data survives write/read roundtrip."""
        target = tmp_path / "test.json"
        original = {
            "string": "value",
            "number": 42,
            "float": 3.14,
            "bool": True,
            "null": None,
            "list": [1, 2, 3],
            "nested": {"a": "b"},
        }

        atomic_write_json(target, original)
        loaded = read_json(target)

        assert loaded == original
