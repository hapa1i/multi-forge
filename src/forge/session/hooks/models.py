"""Dataclasses for hook input/output."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

# Valid source types from Claude Code hooks
HookSource = Literal["startup", "resume", "compact", "clear"]


@dataclass
class HookInput:
    """Input from Claude Code SessionStart hook.

    Claude Code invokes the hook with JSON on stdin containing these fields.
    """

    session_id: str  # Claude's session UUID
    transcript_path: str  # Path to transcript JSONL file
    source: HookSource  # What triggered the hook


@dataclass
class HookResult:
    """Result returned by the hook handler.

    Always exit 0 and return JSON - don't break Claude on errors.
    """

    success: bool
    session_name: str | None = None
    message: str | None = None
    error: str | None = None
    # Echo input fields for debugging
    received_session_id: str | None = None
    received_transcript_path: str | None = None
    received_source: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSON serialization, excluding None values."""
        result: dict[str, Any] = {"success": self.success}
        if self.session_name is not None:
            result["session_name"] = self.session_name
        if self.message is not None:
            result["message"] = self.message
        if self.error is not None:
            result["error"] = self.error
        if self.received_session_id is not None:
            result["received_session_id"] = self.received_session_id
        if self.received_transcript_path is not None:
            result["received_transcript_path"] = self.received_transcript_path
        if self.received_source is not None:
            result["received_source"] = self.received_source
        return result


@dataclass
class ResolutionContext:
    """Context gathered during session name resolution.

    Tracks which resolution method succeeded and any errors encountered.
    """

    session_name: str | None = None
    forge_root: str | None = None  # Resolved project scope (for scoped subsequent lookups)
    resolution_method: str | None = None  # "fork_env", "session_env", "env_file", "uuid_lookup"
    errors: list[str] = field(default_factory=list)

    @property
    def resolved(self) -> bool:
        """Whether a session name was successfully resolved."""
        return self.session_name is not None
