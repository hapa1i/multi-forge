"""Runtime registry: declarative capability matrix for agent runtimes (Phase 4e).

See ``registry`` for the :class:`RuntimeSpec` schema and the :data:`RUNTIMES` table
that answers "can this runtime do X?" without hard-coding Claude Code assumptions.
"""

from .codex_preflight import (
    CodexAuthMethod,
    CodexPreflight,
    CodexPreflightError,
    HookSeam,
    ProxyResponses,
    assert_codex_ready,
    codex_api_key_for_subprocess,
    preflight_codex,
)
from .registry import (
    RUNTIMES,
    InteractiveSupport,
    PolicyEnforcement,
    RuntimeSpec,
    UsageSource,
    get_runtime,
    installed_runtimes,
    list_runtimes,
)

__all__ = [
    "RUNTIMES",
    "CodexAuthMethod",
    "CodexPreflight",
    "CodexPreflightError",
    "HookSeam",
    "InteractiveSupport",
    "PolicyEnforcement",
    "ProxyResponses",
    "RuntimeSpec",
    "UsageSource",
    "assert_codex_ready",
    "codex_api_key_for_subprocess",
    "get_runtime",
    "installed_runtimes",
    "list_runtimes",
    "preflight_codex",
]
