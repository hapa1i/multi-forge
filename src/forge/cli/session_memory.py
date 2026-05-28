"""Tombstone for removed ``forge session memory`` commands.

Replaced by ``forge memory`` (top-level). See coding-standards.md section 5.
"""

from __future__ import annotations

import click


@click.group("memory", hidden=True)
def memory_group() -> None:
    """[Removed] Use 'forge memory' instead."""


@memory_group.command("list-docs", hidden=True)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def _tombstone_list(**_: object) -> None:
    raise click.ClickException("forge session memory list-docs has been removed.\n" "Use: forge memory list")


@memory_group.command("add-doc", hidden=True)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def _tombstone_add(**_: object) -> None:
    raise click.ClickException(
        "forge session memory add-doc has been removed.\n"
        "Use: forge memory track <path> --strategy <strategy> (project passport)."
    )


@memory_group.command("remove-doc", hidden=True)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def _tombstone_remove(**_: object) -> None:
    raise click.ClickException(
        "forge session memory remove-doc has been removed.\n" "Use: forge memory passport remove <path>"
    )
