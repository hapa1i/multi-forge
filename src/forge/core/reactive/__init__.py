"""Shared reactive library for Forge hook handlers and policies.

Provides utilities for subprocess management, caching, structured output
extraction, and LLM-based classification. These are the building blocks
for the semantic supervisor, memory writer, and WorkflowPolicy.

Note: ``proxy.py`` is intentionally NOT re-exported here because it
lazy-imports ``forge.proxy.proxies`` (a top-level component). Consumers
import directly: ``from forge.core.reactive.proxy import lookup_proxy_base_url``.
"""

from .env import (
    FORGE_DEPTH_VAR,
    FORGE_MAX_DEPTH,
    FORGE_PARENT_RUN_ID_VAR,
    FORGE_ROOT_RUN_ID_VAR,
    FORGE_RUN_ID_VAR,
    RunIdentity,
    build_claude_env,
    can_use_bare,
    derive_child_run_identity,
    get_forge_depth,
    get_run_identity,
    mint_run_id,
    new_root_run_identity,
    should_spawn_subprocesses,
)
from .session_runner import SessionResult, run_claude_session
from .structured_output import extract_json_from_response
from .tagger import tag_action
from .throttle import ThrottleCache, compute_cache_key

__all__ = [
    "FORGE_DEPTH_VAR",
    "FORGE_MAX_DEPTH",
    "FORGE_PARENT_RUN_ID_VAR",
    "FORGE_ROOT_RUN_ID_VAR",
    "FORGE_RUN_ID_VAR",
    "RunIdentity",
    "build_claude_env",
    "can_use_bare",
    "derive_child_run_identity",
    "get_forge_depth",
    "get_run_identity",
    "mint_run_id",
    "new_root_run_identity",
    "should_spawn_subprocesses",
    "SessionResult",
    "run_claude_session",
    "extract_json_from_response",
    "tag_action",
    "ThrottleCache",
    "compute_cache_key",
]
