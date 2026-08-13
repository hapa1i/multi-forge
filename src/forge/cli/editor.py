"""Shared $EDITOR parsing and launch support for CLI edit surfaces.

Configuration editors share shell-style argv parsing, while ``forge session
resume --review`` and ``forge session transfer edit`` also share the
git-commit-style abort behavior: a non-zero editor exit aborts and leaves the
file untouched.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from rich.console import Console

from forge.cli.output import print_error, print_tip


def resolve_editor_argv() -> list[str]:
    """Return shell-style $EDITOR arguments after validating the executable."""
    editor = os.environ.get("EDITOR", "vim")
    try:
        editor_argv = shlex.split(editor)
    except ValueError as e:
        print_error(f"Invalid $EDITOR value: {e}")
        sys.exit(1)
    if not editor_argv:
        print_error("$EDITOR is empty. Set $EDITOR to an available editor.")
        sys.exit(1)
    if not shutil.which(editor_argv[0]):
        print_error(f"Editor '{editor}' not found. Set $EDITOR to an available editor.")
        sys.exit(1)
    return editor_argv


def open_in_editor(file_path: Path, *, console: Console, abort_tip: str | None = None) -> None:
    """Open ``file_path`` in $EDITOR, aborting on a non-zero editor exit.

    Git-commit-style: a non-zero editor exit prints the optional ``abort_tip``
    and exits with the editor's return code, leaving the file as the user left
    it. Exits 1 when $EDITOR is malformed or empty, or its program is not on
    PATH.
    """
    editor_argv = resolve_editor_argv()

    result = subprocess.run([*editor_argv, str(file_path)])
    if result.returncode != 0:
        console.print(f"[red]Aborted:[/red] editor exited with code {result.returncode}.")
        if abort_tip:
            print_tip(abort_tip, blank_before=False, console=console)
        sys.exit(result.returncode)
