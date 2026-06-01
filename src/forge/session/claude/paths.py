"""Path utilities for Claude Code integration.

Claude stores session data at: ~/.claude/projects/<encoded-path>/
- <session_id>.jsonl - Transcript
- agent-<uuid>.jsonl - Agent logs

This module provides utilities for:
- Encoding project paths for Claude's directory structure
- Resolving transcript and agent log paths
- Finding project roots (handles git worktrees)
- Computing Claude's effective project root for a session
"""

from __future__ import annotations

import os
from pathlib import Path

from forge.session.models import SessionState


def get_claude_home() -> Path:
    """Get the Claude home directory (~/.claude).

    Respects CLAUDE_HOME environment variable if set (for testing isolation).
    Note: We expand a leading "~" so values like "~/.claude" work correctly,
    even though that's the default.

    Returns:
        Path to ~/.claude directory (or CLAUDE_HOME override).
    """
    claude_home = os.environ.get("CLAUDE_HOME")
    if claude_home:
        return Path(claude_home).expanduser()
    return Path.home() / ".claude"


def get_claude_projects_dir() -> Path:
    """Get the Claude projects directory (~/.claude/projects).

    Returns:
        Path to ~/.claude/projects directory.
    """
    return get_claude_home() / "projects"


def encode_project_path(project_root: str) -> str:
    """Encode project path for Claude's directory structure.

    Claude stores session data in directories named after the project path,
    with path separators, dots, and underscores replaced by hyphens.

    The underscore mapping is empirically verified against Claude Code 2.1.158
    (e.g. a CWD of ``.../my_project`` is stored under ``...-my-project``); a
    transcript path computed without it points at the wrong directory, breaking
    cleanup, status, and cross-CWD relocation for any underscore-bearing path.

    Only ``/``, ``.``, and ``_`` are characterized against real Claude (case,
    digits, and ``-`` are preserved). Other punctuation/whitespace is a known
    unknown -- do not broaden this rule without a real-Claude characterization
    test (see tests/regression/test_bug_encode_project_path_underscore.py).

    Args:
        project_root: Absolute path to project root.

    Returns:
        Encoded path string (e.g., '/home/user/project' -> '-home-user-project').

    Example:
        >>> encode_project_path("/home/user/my.project_v2")
        '-home-user-my-project-v2'
    """
    normalized = str(Path(project_root).resolve())
    encoded = normalized.replace("/", "-").replace(".", "-").replace("_", "-")

    return encoded


def get_transcript_path(project_root: str, session_id: str) -> Path:
    """Get the path to a session transcript file.

    Args:
        project_root: Absolute path to project root.
        session_id: Claude session UUID.

    Returns:
        Path to the transcript file (may not exist).

    Example:
        >>> get_transcript_path("/home/user/project", "abc-123")
        PosixPath('/home/user/.claude/projects/-home-user-project/abc-123.jsonl')
    """
    encoded_path = encode_project_path(project_root)
    return get_claude_projects_dir() / encoded_path / f"{session_id}.jsonl"


def find_agent_logs(project_root: str, session_id: str) -> list[Path]:
    """Find agent log files containing a specific session ID.

    Agent logs don't use session UUID in filename, only in content.
    This function searches log file contents to find matching logs.

    Args:
        project_root: Absolute path to project root.
        session_id: Claude session UUID to search for.

    Returns:
        List of paths to agent log files containing the session ID.
        Returns empty list if directory doesn't exist or no matches found.
    """
    encoded_path = encode_project_path(project_root)
    project_dir = get_claude_projects_dir() / encoded_path

    if not project_dir.exists():
        return []

    matching_logs: list[Path] = []

    for log_file in project_dir.glob("agent-*.jsonl"):
        try:
            content = log_file.read_text(encoding="utf-8")
            if session_id in content:
                matching_logs.append(log_file)
        except (OSError, UnicodeDecodeError):
            continue

    return matching_logs


def resolve_claude_project_root(state: SessionState) -> str:
    """Claude Code project root for a session.

    Claude Code scopes .claude/ settings, conversations, and transcripts
    to its launch CWD.  This computes the correct CWD for any session
    topology so that hooks, transcripts, and --resume all resolve correctly.

    Rules:
    - Non-worktree sessions: use forge_root (always correct).
    - Nested projects (forge_root inside checkout): use forge_root so
      Claude finds .claude/ at the nested path.
    - Root-level worktrees (forge_root anchored at parent repo): use
      worktree.path because extensions are installed at the checkout root.
    """
    if not state.worktree:
        return state.forge_root or str(Path.cwd())

    worktree_root = Path(state.worktree.path)
    if state.forge_root:
        try:
            Path(state.forge_root).relative_to(worktree_root)
            return state.forge_root  # Nested: forge_root is inside checkout
        except ValueError:
            pass
    return str(worktree_root)  # Root-level: forge_root is at parent repo


def find_project_root(start_path: str | None = None) -> Path:
    """Find the git repository root by walking up the directory tree.

    Handles both regular git repositories (where .git is a directory)
    and git worktrees (where .git is a file pointing to the main repo).

    Args:
        start_path: Starting directory to search from. Defaults to cwd.

    Returns:
        Path to the git repository root.

    Raises:
        FileNotFoundError: If no git repository found.

    Example:
        >>> find_project_root("/home/user/project/src/module")
        PosixPath('/home/user/project')
    """
    if start_path is None:
        current = Path.cwd().resolve()
    else:
        current = Path(start_path).resolve()

    while current != current.parent:
        git_path = current / ".git"

        # In worktrees, .git is a FILE; in main checkout, it's a DIRECTORY
        if git_path.exists():
            return current

        current = current.parent

    if (current / ".git").exists():
        return current

    raise FileNotFoundError(f"No git repository found at or above '{start_path or os.getcwd()}'")


def get_project_encoded_dir(project_root: str) -> Path:
    """Get the Claude projects subdirectory for a project.

    Args:
        project_root: Absolute path to project root.

    Returns:
        Path to the project's Claude data directory.

    Example:
        >>> get_project_encoded_dir("/home/user/project")
        PosixPath('/home/user/.claude/projects/-home-user-project')
    """
    encoded_path = encode_project_path(project_root)
    return get_claude_projects_dir() / encoded_path
