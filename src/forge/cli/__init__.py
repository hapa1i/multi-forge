"""Forge CLI - Command line interface for Multi-Forge.

Entry point: `forge` command (installed via pyproject.toml scripts).

Usage:
    forge session start [name]    # Create and start a new session
    forge session resume <name>   # Resume an existing session (reattach or --fresh for context assembly)
    forge session list            # List all sessions
    forge session delete <name>   # Delete a session
"""

from __future__ import annotations

from .main import main

__all__ = ["main"]
