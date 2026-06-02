"""Runtime registry: declarative capability matrix for agent runtimes (Phase 4e).

See ``registry`` for the :class:`RuntimeSpec` schema and the :data:`RUNTIMES` table
that answers "can this runtime do X?" without hard-coding Claude Code assumptions.
"""

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
    "InteractiveSupport",
    "PolicyEnforcement",
    "RuntimeSpec",
    "UsageSource",
    "get_runtime",
    "installed_runtimes",
    "list_runtimes",
]
