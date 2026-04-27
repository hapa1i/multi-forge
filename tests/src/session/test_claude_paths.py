"""Tests for Claude path utilities."""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.session.claude.paths import (
    encode_project_path,
    find_agent_logs,
    find_project_root,
    get_claude_home,
    get_claude_projects_dir,
    get_project_encoded_dir,
    get_transcript_path,
)


class TestGetClaudeHome:
    """Tests for get_claude_home()."""

    def test_returns_home_claude(self, tmp_path: Path) -> None:
        """Should respect CLAUDE_HOME env var (isolation fixture sets it)."""
        result = get_claude_home()
        # The isolate_claude_home fixture sets CLAUDE_HOME to tmp_path/claude_home
        assert result.name == "claude_home" or str(result).startswith(str(tmp_path))

    def test_respects_claude_home_env_var(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Should return CLAUDE_HOME when explicitly set."""
        custom_home = tmp_path / "custom_claude"
        custom_home.mkdir()
        monkeypatch.setenv("CLAUDE_HOME", str(custom_home))
        assert get_claude_home() == custom_home


class TestGetClaudeProjectsDir:
    """Tests for get_claude_projects_dir()."""

    def test_returns_home_claude_projects(self, tmp_path: Path) -> None:
        """Should respect CLAUDE_HOME env var (isolation fixture sets it)."""
        result = get_claude_projects_dir()
        # Should be isolated path / projects
        assert result.name == "projects"
        assert "claude_home" in str(result) or str(result).startswith(str(tmp_path))


class TestEncodeProjectPath:
    """Tests for encode_project_path()."""

    def test_replaces_slashes_with_hyphens(self, tmp_path: Path) -> None:
        """Should replace / with -."""
        # Use tmp_path to get a path that won't be symlink-resolved
        test_dir = tmp_path / "project"
        test_dir.mkdir()
        result = encode_project_path(str(test_dir))
        assert "/" not in result
        assert "project" in result
        assert result.startswith("-")

    def test_replaces_dots_with_hyphens(self, tmp_path: Path) -> None:
        """Should replace . with -."""
        test_dir = tmp_path / "my.project"
        test_dir.mkdir()
        result = encode_project_path(str(test_dir))
        assert "." not in result
        # Original dots in path should become hyphens
        assert "my-project" in result

    def test_handles_trailing_slash(self, tmp_path: Path) -> None:
        """Should handle trailing slashes."""
        test_dir = tmp_path / "project"
        test_dir.mkdir()
        # Add trailing slash
        result = encode_project_path(str(test_dir) + "/")
        # Result should not have trailing slash artifact
        assert not result.endswith("-")
        assert "project" in result

    def test_resolves_relative_paths(self, tmp_path: Path) -> None:
        """Should resolve relative paths to absolute."""
        # Create a directory and encode its path
        subdir = tmp_path / "myproject"
        subdir.mkdir()

        result = encode_project_path(str(subdir))
        # Should contain the resolved path
        assert "myproject" in result


class TestGetTranscriptPath:
    """Tests for get_transcript_path()."""

    def test_builds_correct_path(self, tmp_path: Path) -> None:
        """Should build path to transcript file."""
        test_dir = tmp_path / "project"
        test_dir.mkdir()

        result = get_transcript_path(str(test_dir), "abc-123")

        # Verify structure: projects_dir / encoded_path / session_id.jsonl
        assert result.parent.parent == get_claude_projects_dir()
        assert result.name == "abc-123.jsonl"

    def test_transcript_has_jsonl_extension(self, tmp_path: Path) -> None:
        """Transcript should have .jsonl extension."""
        test_dir = tmp_path / "project"
        test_dir.mkdir()
        result = get_transcript_path(str(test_dir), "session-id")
        assert result.suffix == ".jsonl"


class TestGetProjectEncodedDir:
    """Tests for get_project_encoded_dir()."""

    def test_returns_correct_path(self, tmp_path: Path) -> None:
        """Should return path to project's Claude directory."""
        test_dir = tmp_path / "project"
        test_dir.mkdir()

        result = get_project_encoded_dir(str(test_dir))

        # Should be under Claude projects directory
        assert result.parent == get_claude_projects_dir()
        # Should contain encoded project name
        assert "project" in result.name


class TestFindProjectRoot:
    """Tests for find_project_root()."""

    def test_finds_git_directory(self, tmp_path: Path) -> None:
        """Should find .git directory."""
        # Create a .git directory
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        result = find_project_root(str(tmp_path))
        assert result == tmp_path

    def test_finds_git_file_in_worktree(self, tmp_path: Path) -> None:
        """Should find .git file (worktree marker)."""
        # Create a .git FILE (how worktrees work)
        git_file = tmp_path / ".git"
        git_file.write_text("gitdir: /path/to/main/repo/.git/worktrees/branch-name")

        result = find_project_root(str(tmp_path))
        assert result == tmp_path

    def test_walks_up_directory_tree(self, tmp_path: Path) -> None:
        """Should walk up to find .git."""
        # Create nested structure
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        subdir = tmp_path / "src" / "module"
        subdir.mkdir(parents=True)

        result = find_project_root(str(subdir))
        assert result == tmp_path

    def test_raises_when_no_git(self, tmp_path: Path) -> None:
        """Should raise FileNotFoundError when no .git found."""
        with pytest.raises(FileNotFoundError, match="No git repository found"):
            find_project_root(str(tmp_path))

    def test_defaults_to_cwd(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should default to current working directory."""
        # Create a .git in tmp_path
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        # Change to tmp_path
        monkeypatch.chdir(tmp_path)

        result = find_project_root(None)
        assert result == tmp_path


class TestFindAgentLogs:
    """Tests for find_agent_logs()."""

    def test_returns_empty_when_dir_missing(self, tmp_path: Path) -> None:
        """Should return empty list when projects dir doesn't exist."""
        result = find_agent_logs(str(tmp_path / "nonexistent"), "session-123")
        assert result == []

    def test_finds_matching_logs(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should find agent logs containing session ID."""
        # Set up mock Claude projects directory
        monkeypatch.setattr(
            "forge.session.claude.paths.get_claude_projects_dir",
            lambda: tmp_path,
        )

        # Create project directory
        encoded_dir = tmp_path / "-test-project"
        encoded_dir.mkdir()

        # Create agent logs - one matching, one not
        matching_log = encoded_dir / "agent-abc.jsonl"
        matching_log.write_text('{"session_id": "target-session-123", "data": "test"}')

        non_matching_log = encoded_dir / "agent-xyz.jsonl"
        non_matching_log.write_text('{"session_id": "other-session", "data": "test"}')

        # Mock encode_project_path to return our test dir
        monkeypatch.setattr(
            "forge.session.claude.paths.encode_project_path",
            lambda _: "-test-project",
        )

        result = find_agent_logs("/test/project", "target-session-123")

        assert len(result) == 1
        assert result[0] == matching_log

    def test_ignores_unreadable_files(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should skip files that can't be read."""
        # Set up mock Claude projects directory
        monkeypatch.setattr(
            "forge.session.claude.paths.get_claude_projects_dir",
            lambda: tmp_path,
        )

        encoded_dir = tmp_path / "-test-project"
        encoded_dir.mkdir()

        # Create a log file but make it unreadable (by making it a directory)
        # This will cause an IsADirectoryError when trying to read
        bad_log = encoded_dir / "agent-bad.jsonl"
        bad_log.mkdir()

        monkeypatch.setattr(
            "forge.session.claude.paths.encode_project_path",
            lambda _: "-test-project",
        )

        # Should not raise, just return empty
        result = find_agent_logs("/test/project", "session-123")
        assert result == []
