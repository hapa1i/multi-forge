"""Explicit lifecycle for the independently authenticated Codex reviewer home."""

from __future__ import annotations

import json
import subprocess

import click

from forge.core.reactive import codex_reviewer_home


@click.group()
def auth() -> None:
    """Manage the dedicated supervisor login."""


@auth.command()
@click.option("--runtime", type=click.Choice(["codex"]), required=True)
@click.option(
    "--confirm-extra-usage-off", is_flag=True, help="Assert that extra usage is disabled on this ChatGPT account"
)
def login(runtime: str, confirm_extra_usage_off: bool) -> None:
    """Log in independently; ordinary Codex credentials are never copied."""
    try:
        result = codex_reviewer_home.auth_login(extra_usage_off=confirm_extra_usage_off)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise click.ClickException(str(exc)) from exc
    if result:
        raise click.ClickException("Dedicated reviewer login did not complete")
    click.echo("Dedicated Codex reviewer login ready. Extra usage off is recorded as your assertion.", err=True)


@auth.command()
@click.option("--runtime", type=click.Choice(["codex"]), required=True)
@click.option("--json", "as_json", is_flag=True)
def status(runtime: str, as_json: bool) -> None:
    """Read local login readiness without inference or exposing credentials."""
    result = codex_reviewer_home.auth_status()
    if as_json:
        click.echo(json.dumps(result))
    else:
        click.echo(f"Codex reviewer: {'ready' if result['ready'] else 'unavailable'}")
        click.echo(f"Home: {result['home']}")
        if result["busy"]:
            click.echo("Reviewer busy; reviews wait within their deadlines.")
        if result["unavailable_reason"]:
            click.echo(result["unavailable_reason"], err=True)


@auth.command()
@click.option("--runtime", type=click.Choice(["codex"]), required=True)
def logout(runtime: str) -> None:
    """Log out the owned reviewer store when no review holds its lease."""
    try:
        codex_reviewer_home.auth_logout()
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo("Dedicated Codex reviewer logged out.", err=True)
