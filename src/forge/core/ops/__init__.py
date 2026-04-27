"""Command-core operations.

This package contains reusable operations that can be invoked from:

- the Forge CLI (`forge ...`), and
- in-chat direct commands (via `%...` routed through `forge hook user-prompt-submit`).

Ops must be UI-agnostic: no Click usage, no printing, and no hook JSON.
"""

from .context import ExecutionContext
from .gc import (
    CleanError,
    CleanReport,
    CleanResult,
    OrphanCategory,
    collect_clean_report,
    run_clean,
)
from .proxy import (
    ListProxiesItem,
    ListProxiesResult,
    ShowProxyResult,
    list_proxies,
    show_proxy,
)
from .resolution import (
    ResolvedSession,
    resolve_session_repo_wide,
)
from .session import (
    ForgeOpError,
    ListSessionsItem,
    ListSessionsResult,
    ResetOverridesResult,
    ResolveSessionResult,
    SetOverrideResult,
    list_sessions,
    reset_session_overrides,
    resolve_session,
    set_session_override,
)

__all__ = [
    "ExecutionContext",
    "ForgeOpError",
    # GC ops
    "CleanError",
    "CleanReport",
    "CleanResult",
    "OrphanCategory",
    "collect_clean_report",
    "run_clean",
    # Resolution ops
    "ResolvedSession",
    "resolve_session_repo_wide",
    # Session ops
    "ListSessionsItem",
    "ListSessionsResult",
    "list_sessions",
    "ResolveSessionResult",
    "resolve_session",
    "SetOverrideResult",
    "set_session_override",
    "ResetOverridesResult",
    "reset_session_overrides",
    # Proxy ops
    "ListProxiesItem",
    "ListProxiesResult",
    "ShowProxyResult",
    "list_proxies",
    "show_proxy",
]
