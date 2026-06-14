"""Click group for Forge hook commands."""

from __future__ import annotations

import click


@click.group(name="hook", hidden=True)
@click.pass_context
def hooks(ctx: click.Context) -> None:
    """Hook handlers invoked by agent runtimes.

    Most subcommands are invoked automatically by runtime hooks: Claude Code's
    are configured in .claude/settings.local.json; Codex's (codex-policy-check)
    are registered in a Codex config and require trust enrollment. The 'enable'
    and 'disable' subcommands are user-facing.
    """
    from forge.core.logging import configure_debug_logging

    hook_name = ctx.invoked_subcommand or "hook"
    configure_debug_logging(component=hook_name, subdirectory="hooks")
