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


def test_cli_rich_tips_go_through_output_helpers() -> None:
    """All Rich-styled CLI tips should live in output.py, not hand-rolled call sites."""
    repo_root = Path(__file__).resolve().parents[3]
    cli_root = repo_root / "src" / "forge" / "cli"

    offenders: list[str] = []
    for path in sorted(cli_root.rglob("*.py")):
        if path.name == "output.py":
            continue
        text = path.read_text(encoding="utf-8")
        if "[dim]Tip:" in text:
            offenders.append(str(path.relative_to(repo_root)))

    assert offenders == []


# Files that still hand-roll `[red]Error:[/red]` instead of routing through
# print_error. Debt ledger tracked by the forge_cli_cleanup card (finding #9);
# shrink as the retrofit lands, never grow. A file cleaned but left here fails
# the stale check below, forcing the ledger to shrink with the fix.
CLI_ERROR_MARKUP_ALLOWLIST = {
    "src/forge/cli/claude.py",
    "src/forge/cli/config_cmd.py",
    "src/forge/cli/editor.py",
    "src/forge/cli/extensions.py",
    "src/forge/cli/gc.py",
    "src/forge/cli/guards.py",
    "src/forge/cli/logs.py",
    "src/forge/cli/memory.py",
    "src/forge/cli/memory_report.py",
    "src/forge/cli/policy.py",
    "src/forge/cli/proxy.py",
    "src/forge/cli/session.py",
    "src/forge/cli/session_codex.py",
    "src/forge/cli/session_fork.py",
    "src/forge/cli/session_lifecycle.py",
    "src/forge/cli/session_manage.py",
    "src/forge/cli/session_model_pin.py",
    "src/forge/cli/workflow.py",
}


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
