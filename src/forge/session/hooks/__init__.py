"""Hook handlers for Claude Code integration.

This package provides handlers for Claude Code hooks, enabling Forge
to reconcile session state across /compact and /clear operations.
"""

from .models import HookInput, HookResult, HookSource, ResolutionContext
from .session_start import (
    ENV_FORK_NAME,
    ENV_PARENT_SESSION,
    ENV_SESSION,
    handle_session_start,
    parse_hook_input,
    resolve_session_for_hook,
    resolve_session_name,
    resolve_session_store,
)

__all__ = [
    # Models
    "HookInput",
    "HookResult",
    "HookSource",
    "ResolutionContext",
    # Constants
    "ENV_FORK_NAME",
    "ENV_PARENT_SESSION",
    "ENV_SESSION",
    # Functions
    "handle_session_start",
    "parse_hook_input",
    "resolve_session_for_hook",
    "resolve_session_name",
    "resolve_session_store",
]
