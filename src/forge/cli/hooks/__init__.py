"""CLI hook commands for Claude Code integration.

This package was decomposed from a single 2,490-line ``hooks.py`` module (L7).
Each submodule owns a distinct concern:

- ``_group``: Click group definition
- ``commands``: Hook entry points (session-start, plan-write, stop, etc.)
- ``verification``: Ralph-Wiggum verification logic
- ``direct_commands``: ``%`` command dispatcher and handlers
- ``policy``: Policy check helpers
- ``install``: Hook enable/disable
- ``_helpers``: Shared I/O helpers
"""

from __future__ import annotations

# The Click group — imported by cli/main.py
from ._group import hooks
from . import commands as _commands  # noqa: F401  — registers @hooks.command() decorators
from .install import FORGE_HOOK_CONFIG, SETTINGS_FILENAME, enable, disable
from .verification import (
    _get_last_assistant_text_for_verification,
    _run_verification_check,
)

# Register enable/disable as subcommands of the hooks group
hooks.add_command(enable)
hooks.add_command(disable)

__all__ = [
    "hooks",
    "FORGE_HOOK_CONFIG",
    "SETTINGS_FILENAME",
    "_run_verification_check",
    "_get_last_assistant_text_for_verification",
]
