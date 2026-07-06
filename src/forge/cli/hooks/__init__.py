"""CLI hook commands for Claude Code integration.

This package was decomposed from a single 2,490-line ``hooks.py`` module (L7).
Each submodule owns a distinct concern:

- ``_group``: Click group definition
- ``commands``: Hook entry points (session-start, plan-write, stop, etc.)
- ``verification``: Ralph-Wiggum verification logic
- ``direct_commands``: ``%`` command dispatcher and handlers
- ``policy``: Policy check helpers
- ``_helpers``: Shared I/O helpers
"""

from __future__ import annotations

# The Click group — imported by cli/main.py
from ._group import hooks
from . import commands as _commands  # noqa: F401  — registers @hooks.command() decorators
from .verification import (
    _get_last_assistant_text_for_verification,
    _run_verification_check,
)

__all__ = [
    "hooks",
    "_run_verification_check",
    "_get_last_assistant_text_for_verification",
]
