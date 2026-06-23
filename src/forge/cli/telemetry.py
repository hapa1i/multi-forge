"""Telemetry CLI namespace."""

from __future__ import annotations

import click

from forge.cli.activity import activity_cmd
from forge.cli.proxy_costs import costs_group
from forge.cli.trace import trace


@click.group(no_args_is_help=True, context_settings={"help_option_names": ["-h", "--help"]})
def telemetry() -> None:
    """Inspect Forge telemetry, activity, traces, and costs."""


telemetry.add_command(activity_cmd, name="activity")
telemetry.add_command(trace, name="trace")
telemetry.add_command(costs_group, name="costs")
