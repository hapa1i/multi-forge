"""Tombstone for the removed ``forge session handoff show`` command.

Replaced by ``forge memory report show`` (the memory writer's report surface).
See coding-standards.md section 5.
"""

from __future__ import annotations

import click


@click.group("handoff", hidden=True)
def handoff_group() -> None:
    """[Removed] Use 'forge memory report show' instead."""


@handoff_group.command(
    "show",
    hidden=True,
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def _tombstone_show(**_: object) -> None:
    # ignore_unknown_options + UNPROCESSED args swallow --latest/--all and a
    # session name so old invocations reach this message instead of Click's
    # generic "No such option" error.
    raise click.ClickException("forge session handoff show has been removed.\n" "Use: forge memory report show")
