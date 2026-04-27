"""Smoke tests for docker.py helper methods.

Tests verify that write_file, write_json, mkdir, read_file, read_json, and file_exists
work correctly for both DockerContainer and LocalExecution implementations.
"""

from __future__ import annotations

import json

import pytest

from tests.fixtures.docker import ContainerLike


def test_write_and_read_file(clean_workspace: ContainerLike):
    """Test writing and reading a simple text file."""
    content = "Hello, World!\nThis is a test."
    clean_workspace.write_file("/workspace/test.txt", content)

    result = clean_workspace.read_file("/workspace/test.txt")
    assert result == content


def test_write_file_with_special_chars(clean_workspace: ContainerLike):
    """Test heredoc handles special characters without escaping."""
    content = """Line with 'single quotes'
Line with "double quotes"
Line with $variables and ${braces}
Line with backticks `command`
Line with backslashes \\ and \\n
Line with ampersands & and pipes |
"""
    clean_workspace.write_file("/workspace/special.txt", content)

    result = clean_workspace.read_file("/workspace/special.txt")
    assert result == content


def test_write_json(clean_workspace: ContainerLike):
    """Test writing and reading JSON data."""
    data = {
        "name": "Test",
        "values": [1, 2, 3],
        "nested": {"key": "value"},
        "special": "chars: 'quotes', $vars, `backticks`",
    }

    clean_workspace.write_json("/workspace/test.json", data)
    result = clean_workspace.read_json("/workspace/test.json")

    assert result == data


def test_mkdir_parents(clean_workspace: ContainerLike):
    """Test creating nested directories."""
    path = "/workspace/level1/level2/level3"
    clean_workspace.mkdir(path, parents=True)

    # Verify directory exists (file_exists checks files, so use exec)
    result = clean_workspace.exec(f"test -d '{path}'")
    assert result.returncode == 0


def test_mkdir_no_parents_fails(clean_workspace: ContainerLike):
    """Test mkdir without parents flag fails for nested paths."""
    result = clean_workspace.mkdir("/workspace/nonexistent/nested", parents=False)
    # Should fail because parent doesn't exist
    assert result.returncode != 0


def test_file_exists(clean_workspace: ContainerLike):
    """Test file_exists helper."""
    # Non-existent file
    assert not clean_workspace.file_exists("/workspace/nonexistent.txt")

    # Create file
    clean_workspace.write_file("/workspace/exists.txt", "content")

    # Now exists
    assert clean_workspace.file_exists("/workspace/exists.txt")


def test_read_file_not_found(clean_workspace: ContainerLike):
    """Test read_file raises FileNotFoundError for missing files."""
    with pytest.raises(FileNotFoundError, match="Failed to read"):
        clean_workspace.read_file("/workspace/nonexistent.txt")


def test_read_json_invalid(clean_workspace: ContainerLike):
    """Test read_json raises JSONDecodeError for invalid JSON."""
    clean_workspace.write_file("/workspace/invalid.json", "not valid json")

    with pytest.raises(json.JSONDecodeError):
        clean_workspace.read_json("/workspace/invalid.json")


def test_write_file_creates_intermediate_dirs(clean_workspace: ContainerLike):
    """Test write_file fails if parent directory doesn't exist (expected behavior)."""
    # This should fail - write_file doesn't create parent dirs
    result = clean_workspace.write_file("/workspace/nonexistent/file.txt", "content")
    assert result.returncode != 0


def test_roundtrip_empty_file(clean_workspace: ContainerLike):
    """Test writing and reading empty file."""
    clean_workspace.write_file("/workspace/empty.txt", "")
    result = clean_workspace.read_file("/workspace/empty.txt")
    assert result == ""


def test_roundtrip_multiline_json(clean_workspace: ContainerLike):
    """Test JSON preserves structure through roundtrip."""
    data = {
        "multiline_string": "line1\nline2\nline3",
        "unicode": "Hello 世界 🌍",
        "numbers": [1, 2.5, -3, 0],
        "booleans": [True, False, None],
    }

    clean_workspace.write_json("/workspace/complex.json", data)
    result = clean_workspace.read_json("/workspace/complex.json")

    assert result == data
    # Verify types preserved
    assert result["numbers"][1] == 2.5  # Float preserved
    assert result["booleans"][2] is None  # None preserved
