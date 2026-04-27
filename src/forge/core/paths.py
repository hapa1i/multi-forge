"""Core path utilities for Forge.

Provides the canonical location of the Forge home directory (~/.forge)
and related path constants. These are cross-cutting concerns used by
session, proxy, install, backend, and workqueue modules.
"""

from __future__ import annotations

import os
from pathlib import Path

# The dotfile directory name used by Forge
FORGE_DIR = ".forge"


def display_path(path: str | Path) -> str:
    """Replace home directory prefix with ``~`` for shorter terminal display."""
    s = str(path)
    home = str(Path.home())
    if s == home:
        return "~"
    if s.startswith(home + "/"):
        return "~" + s[len(home) :]
    return s


def get_forge_home() -> Path:
    """Get the forge home directory (~/.forge).

    Respects FORGE_HOME environment variable for testing/custom paths.

    Note: we expand a leading "~" so values like "~/.forge" work correctly,
    including in tests that monkeypatch HOME.
    """
    if forge_home := os.environ.get("FORGE_HOME"):
        return Path(forge_home).expanduser()
    return Path.home() / FORGE_DIR
