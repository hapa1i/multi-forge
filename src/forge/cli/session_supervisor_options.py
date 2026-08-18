"""Shared supervisor option helpers for session start/fork commands."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import click

from forge.core.effort import CLAUDE_EFFORT_LEVELS
from forge.core.llm.types import REASONING_EFFORT_LEVELS
from forge.policy.semantic.supervisor import (
    CHECKER_PROVIDER_CHOICES,
    supervisor_lane_runtimes,
)
from forge.policy.semantic.supervisor import (
    supervisor_option_error as supervisor_option_error,
)


def supervisor_options(f: Callable[..., Any]) -> Callable[..., Any]:
    """Apply the shared supervisor-routing and cascade options."""
    options = [
        click.option(
            "--supervisor-proxy",
            type=str,
            default=None,
            help="Proxy for supervisor routing (requires --supervise)",
        ),
        click.option(
            "--no-supervisor-proxy",
            "supervisor_direct",
            is_flag=True,
            default=False,
            help="Force supervisor to use direct Anthropic routing (requires --supervise)",
        ),
        click.option(
            "--cascade",
            "cascade_flag",
            is_flag=True,
            default=False,
            help="Enable the tier-1 plan check before the frontier supervisor (requires --supervise)",
        ),
        click.option(
            "--checker-model",
            "checker_model",
            default=None,
            help="Tier-1 checker model (prefixed id; requires --supervise)",
        ),
        click.option(
            "--checker-provider",
            "checker_provider",
            type=click.Choice(list(CHECKER_PROVIDER_CHOICES)),
            default=None,
            help="Tier-1 checker provider (requires --supervise)",
        ),
        click.option(
            "--checker-effort",
            "checker_effort",
            type=click.Choice(list(REASONING_EFFORT_LEVELS)),
            default=None,
            help="Tier-1 checker reasoning effort (none/low/medium/high/xhigh; requires --supervise)",
        ),
        click.option(
            "--supervisor-effort",
            "supervisor_effort",
            type=click.Choice(list(CLAUDE_EFFORT_LEVELS)),
            default=None,
            help="Frontier supervisor effort (claude --effort: low/medium/high/xhigh/max; requires --supervise)",
        ),
        click.option(
            "--supervisor-runtime",
            "supervisor_runtime",
            type=click.Choice(list(supervisor_lane_runtimes())),
            default=None,
            help="Supervisor lane runtime (claude_code/codex; requires --supervise)",
        ),
    ]
    for option in reversed(options):
        f = option(f)
    return f
