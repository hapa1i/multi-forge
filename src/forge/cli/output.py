"""Shared Rich console output helpers for the Forge CLI.

Leaf module: imports only ``rich`` and Forge exception leaves
(``forge.session.exceptions``, ``forge.core.state.exceptions``). Never import
``forge.cli.*`` here — CLI command modules import from this module, not the
reverse. This keeps ``output`` circular-safe and prevents Rich markup from
leaking into non-terminal layers (core/proxy/review build plain-text exception
strings, not console output).
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence

from rich.console import Console

from forge.core.state.exceptions import StateCorruptedError
from forge.session.exceptions import ForgeSessionError, SessionExistsError

# Module-level fallback console. Call sites that keep their own
# ``Console(width=...)`` (e.g. for tables) should pass it via ``console=`` so
# their width is preserved; only this fallback is width-less.
console = Console()

# Shared stderr console. Errors/diagnostics that must not pollute stdout (the
# results stream, per cli_style_guidelines.md "Output Streams") pass this via
# ``console=`` -- e.g. failures that previously raised ``click.ClickException``,
# which Click renders to stderr.
err_console = Console(stderr=True)


def _resolve(console_arg: Console | None) -> Console:
    return console_arg if console_arg is not None else console


def print_tip(
    *lines: str,
    commands: Sequence[str] | None = None,
    blank_before: bool = True,
    console: Console | None = None,
) -> None:
    """Print a dim ``Tip:`` block.

    The first line is prefixed ``Tip:``; remaining ``lines`` render as dim
    continuations. ``commands`` render as an indented, copy-pasteable block
    (plain, so they stand out as runnable). ``blank_before`` emits a leading
    blank line for visual separation (the common case after an error or table).
    """
    out = _resolve(console)
    if not lines and not commands:
        return
    if blank_before:
        out.print()
    if lines:
        first, *rest = lines
        out.print(f"[dim]Tip: {first}[/dim]")
        for line in rest:
            out.print(f"[dim]{line}[/dim]")
    for cmd in commands or ():
        out.print(f"  {cmd}")


def print_error(msg: str, *, console: Console | None = None) -> None:
    """Print a red ``Error:`` label followed by the message."""
    _resolve(console).print(f"[red]Error:[/red] {msg}")


def print_error_with_tip(
    error_msg: str,
    *tip_lines: str,
    commands: Sequence[str] | None = None,
    console: Console | None = None,
) -> None:
    """Print an ``Error:`` line then a ``Tip:`` block. Does not exit — the caller controls the exit code."""
    out = _resolve(console)
    print_error(error_msg, console=out)
    print_tip(*tip_lines, commands=commands, console=out)


# Context-free recovery tips, keyed by exception type. Intentionally tiny: only
# exceptions whose recovery is identical regardless of which command raised them
# belong here. Context-sensitive errors (e.g. SessionNotFoundError, whose fix
# differs for start vs delete/show) and errors that already embed a hint in
# their message are tipped at the call site, or not at all — never here.
_SESSION_ERROR_TIPS: dict[type[ForgeSessionError], Callable[[ForgeSessionError], tuple[str, ...]]] = {
    SessionExistsError: lambda e: (
        f"Use a different session name, or run 'forge session delete {getattr(e, 'name', '<name>')}' first.",
    ),
}


def handle_session_error(e: ForgeSessionError, *, console: Console | None = None) -> None:
    """Print a session error (plus a context-free recovery tip, if mapped) and exit 1."""
    out = _resolve(console)
    print_error(str(e), console=out)
    tip_fn = _SESSION_ERROR_TIPS.get(type(e))
    if tip_fn is not None:
        print_tip(*tip_fn(e), console=out)
    sys.exit(1)


def handle_corrupt_state_error(e: StateCorruptedError, *, console: Console | None = None) -> None:
    """Print a corrupt-state error with the uniform reset instruction, then exit 1.

    The single handler for every Forge-owned durable-state corruption (manifests,
    indexes, registries, proxy config). The error names the offending file, so the
    tip covers both a one-file fix and a full reset; ``forge clean`` removes corrupt
    Forge-written state. Wired once at the top-level ``AliasGroup.main`` catch.
    """
    out = console if console is not None else err_console
    print_error(f"Forge state is corrupt: {e}", console=out)
    print_tip(
        "Fix or delete the file named above. For a full reset, delete .forge (project) or "
        "~/.forge (global) and re-run 'forge extension enable'.",
        "'forge clean' can detect and remove corrupt Forge state.",
        console=out,
    )
    sys.exit(1)
