"""Claude Code integration utilities.

This module provides utilities for:
- Path encoding and transcript path resolution
- Claude binary invocation
- Session data cleanup (transcripts, agent logs)
- Cross-CWD transcript relocation (native-relocate spike)
"""

from __future__ import annotations

from .cleanup import (
    CleanupResult,
    cleanup_session,
    delete_session_data,
)
from .invoke import (
    build_claude_args,
    find_claude_binary,
    invoke_claude,
    is_claude_available,
)
from .paths import (
    encode_project_path,
    find_agent_logs,
    find_project_root,
    get_claude_home,
    get_claude_projects_dir,
    get_project_encoded_dir,
    get_transcript_path,
)
from .relocate import (
    RelocateConflictError,
    RelocateResult,
    RelocateSourceMissingError,
    relocate_transcript,
)

__all__ = [
    # Cleanup
    "CleanupResult",
    "cleanup_session",
    "delete_session_data",
    # Invoke
    "build_claude_args",
    "invoke_claude",
    "find_claude_binary",
    "is_claude_available",
    # Paths
    "encode_project_path",
    "find_agent_logs",
    "find_project_root",
    "get_claude_home",
    "get_claude_projects_dir",
    "get_project_encoded_dir",
    "get_transcript_path",
    # Relocate
    "RelocateConflictError",
    "RelocateResult",
    "RelocateSourceMissingError",
    "relocate_transcript",
]
