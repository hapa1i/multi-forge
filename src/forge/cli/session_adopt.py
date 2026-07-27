"""`forge session adopt` -- bind a Forge session to an existing native conversation.

Rendering and exit codes live here; all logic is in
``forge.core.ops.session_adopt`` (design.md section 3.12).

Bare ``forge session adopt`` previews the adoptable conversations in the current
directory; passing a conversation id binds one.
"""

from __future__ import annotations

import sys
from typing import cast

import click
from rich import box
from rich.table import Table

from forge.cli.output import print_error, print_error_with_tip, print_tip
from forge.cli.session import _format_relative_time, console
from forge.cli.session import session as _session_untyped
from forge.core.ops.context import ExecutionContext
from forge.core.ops.session_adopt import (
    MODEL_BASIS_INFERRED,
    MODEL_BASIS_NONE,
    AdoptError,
    adopt_session,
    discover_adoptable,
    plan_adoption,
)
from forge.session import ForgeSessionError, UuidAlreadyBoundError
from forge.session.exceptions import SessionExistsError

session = cast(click.Group, _session_untyped)  # type: ignore[has-type]  # circular re-export


@session.command()
@click.argument("conversation_id", required=False)
@click.option("--name", "-n", help="Forge session name (defaults to the conversation id prefix)")
@click.option("--model", "-m", help="Model to pin for future Forge resumes (overrides transcript inference)")
@click.option("--yes", "-y", is_flag=True, help="Skip the confirmation for a recently-active conversation")
def adopt(conversation_id: str | None, name: str | None, model: str | None, yes: bool) -> None:
    """Adopt a native Claude conversation as a managed Forge session.

    \b
    Examples:
        forge session adopt                       # preview adoptable conversations here
        forge session adopt 470b1a1b-202b-4ead-a3ea-d0dca69243f2
        forge session adopt 470b1a1b-202b-4ead-a3ea-d0dca69243f2 --name my-session --model claude-opus-5

    CONVERSATION_ID is the full transcript UUID, not a prefix. Omit it to list
    the unbound conversations launched from this directory.

    Run this from the directory the native session was launched in: Claude
    stores transcripts under an encoding of that path, and adoption verifies
    the transcript's recorded directory matches before binding it.

    Adoption does not attach hooks, env, or supervision to an already-running
    client; those begin with the next Forge-managed resume or fork.
    """
    ctx = ExecutionContext.from_cwd()

    # Checked here rather than left to the op's AdoptError: the op stays
    # UI-agnostic, and this is the one precondition with a fixed remedy.
    if ctx.forge_root is None:
        print_error_with_tip(
            "Not inside a Forge project.",
            "Enable Forge in this repository first, then adopt from the conversation's directory.",
            commands=["forge extension enable"],
        )
        sys.exit(1)

    if conversation_id is None:
        _preview_candidates(ctx)
        return

    try:
        plan = plan_adoption(ctx, conversation_id, model_override=model)
    except UuidAlreadyBoundError as e:
        print_error_with_tip(
            f"Conversation '{e.session_uuid}' is already adopted by session '{e.owner}'.",
            "Resume the existing session instead of adopting it twice.",
            commands=[f"forge session resume {e.owner}"],
        )
        sys.exit(1)
    except AdoptError as e:
        print_error(str(e))
        sys.exit(1)

    if plan.recently_active and not yes:
        console.print(
            "[yellow]This conversation was active in the last 30 minutes.[/yellow] "
            "Forge cannot tell whether a native client is still attached to it."
        )
        print_tip(
            "Adopting a live conversation and then resuming it would put two clients on one transcript.",
            "Close the other client first if one is running.",
            console=console,
        )
        if not click.confirm("Adopt it anyway?", default=False):
            console.print("[dim]Adoption cancelled.[/dim]")
            return

    # Derive from the plan's normalized id, never the raw argument.
    session_name = name or plan.session_uuid.split("-")[0]

    try:
        result = adopt_session(ctx, plan, name=session_name)
    except UuidAlreadyBoundError as e:
        # Lost a race with a concurrent adopt between the plan and the index write.
        print_error_with_tip(
            f"Conversation '{e.session_uuid}' was adopted by session '{e.owner}' while this command ran.",
            "Nothing was created here.",
            commands=[f"forge session resume {e.owner}"],
        )
        sys.exit(1)
    except SessionExistsError as e:
        print_error_with_tip(
            f"Session '{e.name}' already exists.",
            "Choose a different name.",
            commands=[f"forge session adopt {conversation_id} --name <name>"],
        )
        sys.exit(1)
    except AdoptError as e:
        print_error(str(e))
        sys.exit(1)
    except ForgeSessionError as e:
        print_error(str(e))
        sys.exit(1)

    console.print(f"[green]Adopted[/green] conversation [bold]{result.session_uuid}[/bold] as '{result.name}'")

    if result.model_basis == MODEL_BASIS_INFERRED:
        console.print(f"  Model (inferred from transcript): {result.model}")
    elif result.model_basis == MODEL_BASIS_NONE:
        console.print("  [yellow]Model: unknown[/yellow] -- the transcript has no assistant turn to infer from")
        print_tip(
            "Forge did not pin a model, so a resume uses the current direct default.",
            "Pin one on the adopted session if this conversation should continue on a specific model.",
            commands=[f"forge session resume {result.name} --model <model>"],
            console=console,
        )
    else:
        console.print(f"  Model: {result.model}")

    if not result.indexed:
        print_tip(
            "The transcript was copied but could not be queued for search indexing.",
            "Rebuild the index to make it searchable.",
            commands=["forge search reindex"],
            console=console,
        )

    print_tip(
        "Resume it as a managed session:",
        commands=[f"forge session resume {result.name}"],
        console=console,
    )


def _preview_candidates(ctx: ExecutionContext) -> None:
    """Render the read-only preview shown by bare `forge session adopt`."""
    try:
        scanned_dir, candidates = discover_adoptable(ctx)
    except AdoptError as e:
        print_error(str(e))
        sys.exit(1)

    # Printed in both branches: Claude's encoded directory names are lossy, so
    # "nothing here" is only actionable once you know which directory was read.
    console.print(f"Scanning conversations launched from [bold]{ctx.cwd}[/bold]")
    console.print(f"  [dim]{scanned_dir}[/dim]")

    if not candidates:
        console.print("\nNo unbound conversations found here.")
        print_tip(
            "Adoption is exact-directory: a conversation is listed only where bare 'claude' was launched.",
            "If you started it in a subdirectory, run this again from there.",
            console=console,
        )
        return

    table = Table(box=box.SIMPLE, header_style="bold", padding=(0, 1))
    # The id is the value the user has to copy into the next command, so it never
    # truncates; the message column absorbs the remaining width instead.
    table.add_column("Conversation", no_wrap=True)
    table.add_column("Last active", no_wrap=True)
    table.add_column("Turns", justify="right", no_wrap=True)
    table.add_column("First message", overflow="fold")

    for candidate in candidates:
        table.add_row(
            candidate.session_uuid,
            _format_relative_time(candidate.modified_at),
            str(candidate.user_turns),
            candidate.preview or "[dim](no message yet)[/dim]",
        )

    console.print()
    console.print(table)
    print_tip(
        "Adopt one by conversation id:",
        commands=[f"forge session adopt {candidates[0].session_uuid} --name <name>"],
        console=console,
    )
