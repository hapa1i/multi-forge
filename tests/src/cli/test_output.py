"""Unit tests for the shared CLI output helpers (forge.cli.output)."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from rich.console import Console

from forge.cli.output import (
    handle_session_error,
    print_error,
    print_error_with_tip,
    print_tip,
)
from forge.session.exceptions import (
    BranchNotMergedError,
    SessionExistsError,
    SessionNotFoundError,
)


def _console() -> tuple[Console, io.StringIO]:
    """A Console that renders to a buffer as plain text (no ANSI/markup)."""
    buf = io.StringIO()
    return Console(file=buf, force_terminal=False, no_color=True, width=80), buf


def test_print_tip_single_line() -> None:
    c, buf = _console()
    print_tip("Run 'forge proxy list' to see proxies.", console=c)
    assert "Tip: Run 'forge proxy list' to see proxies." in buf.getvalue()


def test_print_tip_blank_before_default() -> None:
    c, buf = _console()
    print_tip("hello", console=c)
    assert buf.getvalue().startswith("\n")


def test_print_tip_no_blank_before() -> None:
    c, buf = _console()
    print_tip("hello", blank_before=False, console=c)
    assert not buf.getvalue().startswith("\n")


def test_print_tip_multiline() -> None:
    c, buf = _console()
    print_tip("first line", "second line", console=c)
    out = buf.getvalue()
    assert "Tip: first line" in out
    assert "second line" in out


def test_print_tip_commands_block_rendered_indented() -> None:
    c, buf = _console()
    print_tip(
        "Start an instance with:",
        commands=["forge model backend start litellm --port 4000"],
        console=c,
    )
    out = buf.getvalue()
    assert "Tip: Start an instance with:" in out
    assert "  forge model backend start litellm --port 4000" in out


def test_print_tip_no_args_is_noop() -> None:
    c, buf = _console()
    print_tip(console=c)
    assert buf.getvalue() == ""


def test_print_error() -> None:
    c, buf = _console()
    print_error("something broke", console=c)
    assert "Error: something broke" in buf.getvalue()


def test_print_error_with_tip_orders_error_then_tip() -> None:
    c, buf = _console()
    print_error_with_tip("bad thing happened", "try the other thing", console=c)
    out = buf.getvalue()
    assert "Error: bad thing happened" in out
    assert "Tip: try the other thing" in out
    assert out.index("Error:") < out.index("Tip:")


def test_handle_session_error_exists_emits_generic_tip_and_exits() -> None:
    c, buf = _console()
    with pytest.raises(SystemExit) as exc:
        handle_session_error(SessionExistsError("my-sess"), console=c)
    assert exc.value.code == 1
    out = buf.getvalue()
    assert "Error: session 'my-sess' already exists" in out
    assert "Tip:" in out
    # Tip interpolates the real name and stays context-free.
    assert "forge session delete my-sess" in out
    # Must NOT suggest resume: meaningless for a fork name collision.
    assert "resume" not in out


def test_handle_session_error_context_sensitive_has_no_generic_tip() -> None:
    """SessionNotFoundError's recovery differs by command, so the map must not tip it."""
    c, buf = _console()
    with pytest.raises(SystemExit) as exc:
        handle_session_error(SessionNotFoundError("ghost"), console=c)
    assert exc.value.code == 1
    out = buf.getvalue()
    assert "Error: session 'ghost' not found" in out
    assert "Tip:" not in out


def test_handle_session_error_self_hinting_error_not_double_tipped() -> None:
    """BranchNotMergedError already embeds '--force' guidance in its message; no extra map tip."""
    c, buf = _console()
    with pytest.raises(SystemExit) as exc:
        handle_session_error(BranchNotMergedError("feature-x"), console=c)
    assert exc.value.code == 1
    out = buf.getvalue()
    assert "Error:" in out
    assert "Tip:" not in out


# The only legitimate literal "Tip:" outside output.py: assistant-facing JSON
# payloads in direct_commands.py, returned to Claude as text (never printed as
# terminal recovery output), so they don't route through print_tip. Pinned to the
# exact payload sentences in that one file -- not the whole file -- so a new
# "Tip:" anywhere, including elsewhere in direct_commands.py, is still an offender.
CLI_TIP_PAYLOAD_FILE = "src/forge/cli/hooks/direct_commands.py"
CLI_TIP_PAYLOAD_ALLOWLIST = {
    "Tip: Use /copy to copy assistant responses (built-in).",
    "Tip: Use 'forge session start' for managed sessions,",
    "Tip: This session supervises:",
}


def test_cli_rich_tips_go_through_output_helpers() -> None:
    """Hand-rolled "Tip:" belongs in print_tip/print_error_with_tip, not call sites.

    Scans the literal "Tip:" -- a superset of the Rich "[dim]Tip:" markup that
    also catches plain ``click.echo("Tip: ...")`` and ClickException-embedded
    ``"\\nTip: ..."`` -- since the user-facing prefix lives only in output.py.
    Every match must be one of the three pinned assistant-facing payloads in
    direct_commands.py; any other "Tip:" line is an offender, and a payload that
    disappears must be pruned (mirrors the CLI_ERROR_MARKUP_ALLOWLIST ledger).
    """
    repo_root = Path(__file__).resolve().parents[3]
    cli_root = repo_root / "src" / "forge" / "cli"

    offenders: set[tuple[str, str]] = set()
    matched: set[str] = set()
    for path in sorted(cli_root.rglob("*.py")):
        if path.name == "output.py":
            continue
        rel = path.relative_to(repo_root).as_posix()
        for line in path.read_text(encoding="utf-8").splitlines():
            if "Tip:" not in line:
                continue
            payload = next(
                (p for p in CLI_TIP_PAYLOAD_ALLOWLIST if rel == CLI_TIP_PAYLOAD_FILE and p in line),
                None,
            )
            if payload is not None:
                matched.add(payload)
            else:
                offenders.add((rel, line.strip()))

    stale = CLI_TIP_PAYLOAD_ALLOWLIST - matched
    assert not offenders, f"route hand-rolled 'Tip:' through forge.cli.output: {sorted(offenders)}"
    assert not stale, f"payload gone -- prune from CLI_TIP_PAYLOAD_ALLOWLIST: {sorted(stale)}"


# Drained empty by forge_cli_cleanup Slice 11 (finding #9): every hand-rolled
# `[red]Error:[/red]` now routes through print_error. Kept as a locked, never-grow
# ledger -- a new offender makes `new` (below) non-empty and fails the test.
CLI_ERROR_MARKUP_ALLOWLIST: set[str] = set()


def test_cli_rich_errors_go_through_print_error() -> None:
    """Hand-rolled `[red]Error:[/red]` belongs in print_error, not at call sites.

    Extends the recovery-output rule from tips to errors (cli_style_guidelines.md
    "Error ownership"). The allowlist is the current debt; new offenders fail.
    """
    repo_root = Path(__file__).resolve().parents[3]
    cli_root = repo_root / "src" / "forge" / "cli"

    offenders: set[str] = set()
    for path in sorted(cli_root.rglob("*.py")):
        if path.name == "output.py":
            continue
        if "[red]Error:[/red]" in path.read_text(encoding="utf-8"):
            offenders.add(path.relative_to(repo_root).as_posix())

    new = offenders - CLI_ERROR_MARKUP_ALLOWLIST
    fixed = CLI_ERROR_MARKUP_ALLOWLIST - offenders
    assert not new, f"route hand-rolled [red]Error:[/red] through print_error: {sorted(new)}"
    assert not fixed, f"cleaned -- remove from CLI_ERROR_MARKUP_ALLOWLIST: {sorted(fixed)}"
