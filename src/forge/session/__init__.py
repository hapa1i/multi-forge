"""Forge Session - Named session management for Claude Code.

This module provides the essential public API for session management:

- SessionState: Core data structure for session state (intent + confirmed)
- SessionStore: Read/write .forge/sessions/<name>/forge.session.json
- IndexStore: Read/write ~/.forge/sessions/index.json
- SessionManager: High-level session orchestration

For specialized access, import from submodules directly:

- forge.session.models: All data models (SessionIntent, SessionConfirmed, Worktree, etc.)
- forge.session.effective: Effective config computation (apply_overrides, get_effective_value)
- forge.session.overrides: Override operations (validate_key, parse_value, expand_wildcard)
- forge.session.hooks: Hook integration (handle_session_start, HookResult, etc.)
- forge.session.exceptions: Full exception hierarchy
- forge.session.store: Store constants (MANIFEST_FILENAME, etc.)
- forge.session.index: Index constants (INDEX_DIR, etc.)
- forge.session.validation: Name validation constants (MIN/MAX_NAME_LENGTH)
- forge.session.config: Config constants (VALID_PROXY_TEMPLATES)

Quick Start:
    from forge.session import (
        create_session_state,
        SessionStore,
        IndexStore,
    )

    # Create a new session state
    state = create_session_state(
        "my-session",
        proxy_template="litellm-gemini",
        proxy_base_url="http://localhost:8084",
    )

    # Write state to worktree (per-session directory)
    store = SessionStore("/path/to/worktree", "my-session")
    store.write(state)

    # Add to global index
    index = IndexStore()
    index.add_from_state(state, "/path/to/project")
"""

from __future__ import annotations

# Config
from .active import (
    ActiveSessionEntry,
    ActiveSessionIndex,
    ActiveSessionStore,
    run_with_active_session,
    track_active_session,
)
from .config import (
    DEFAULT_PROXY_BASE_URL,
    DEFAULT_PROXY_TEMPLATE,
    LAUNCH_MODE_HOST,
    LAUNCH_MODE_SIDECAR,
    SIDECAR_RUNTIME_BASE_URL,
)

# Effective config
from .effective import compute_effective_intent

# Exceptions (base + common operational)
from .exceptions import (
    ForgeSessionError,
    InvalidSessionNameError,
    SessionExistsError,
    SessionNotFoundError,
)

# Index
from .index import IndexStore

# Manager
from .manager import SessionManager

# Models
from .models import (
    SCHEMA_VERSION,
    SessionIndexEntry,
    SessionState,
    create_session_state,
)

# Overrides
from .overrides import clear_overrides, delete_override, set_override

# Store
from .store import SessionStore

# Validation
from .validation import validate_name

__all__ = [
    # Core types
    "SessionState",
    "SessionIndexEntry",
    "create_session_state",
    "SCHEMA_VERSION",
    "ActiveSessionEntry",
    "ActiveSessionIndex",
    # Stores
    "SessionStore",
    "IndexStore",
    "ActiveSessionStore",
    # Manager
    "SessionManager",
    # Operations
    "compute_effective_intent",
    "set_override",
    "delete_override",
    "clear_overrides",
    "run_with_active_session",
    "track_active_session",
    "validate_name",
    # Config
    "DEFAULT_PROXY_TEMPLATE",
    "DEFAULT_PROXY_BASE_URL",
    "LAUNCH_MODE_HOST",
    "LAUNCH_MODE_SIDECAR",
    "SIDECAR_RUNTIME_BASE_URL",
    # Exceptions (base + common operational)
    "ForgeSessionError",
    "SessionNotFoundError",
    "SessionExistsError",
    "InvalidSessionNameError",
]
