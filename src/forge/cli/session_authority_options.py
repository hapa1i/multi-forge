"""Leaf helpers for authority-bearing session creation options."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

import click

from forge.session.models import AuthorityIntent


def authority_creation_options(function: Callable[..., Any]) -> Callable[..., Any]:
    """Add the shared authority role/tier flags to a creation command."""
    options = [
        click.option(
            "--authority",
            "authority_role",
            type=click.Choice(["advisory", "producer"]),
            default=None,
            help="Assign artifact authority to the new managed session.",
        ),
        click.option(
            "--authority-tier",
            type=click.Choice(["named_tools", "shell_closed"]),
            default=None,
            help="Advisory enforcement tier (default: shell_closed).",
        ),
    ]
    for option in reversed(options):
        function = option(function)
    return function


def parse_creation_authority(role: str | None, tier: str | None) -> tuple[AuthorityIntent | None, bool]:
    """Validate creation flags and return typed intent plus explicitness."""
    if tier is not None and role is None:
        raise ValueError("--authority-tier requires --authority advisory")
    if role is None:
        return None, False
    if os.environ.get("FORGE_SESSION"):
        raise ValueError("authority-bearing session creation is only available outside a managed session")
    return AuthorityIntent(role=role, tier=tier), True
