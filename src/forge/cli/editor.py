"""Shared $EDITOR launcher for editable transfer/context files.

Extracted from ``session_lifecycle`` so both ``forge session resume --review``
and ``forge session transfer edit`` use one editor-launch path with the same
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

from forge.cli.output import print_tip


def open_in_editor(file_path: Path, *, console: Console, abort_tip: str | None = None) -> None:
    """Open ``file_path`` in $EDITOR, aborting on a non-zero editor exit.

    Git-commit-style: a non-zero editor exit prints the optional ``abort_tip``
    and exits with the editor's return code, leaving the file as the user left
    it. Exits 1 when $EDITOR is empty or its program is not on PATH.
    """
    editor = os.environ.get("EDITOR", "vim")
    editor_argv = shlex.split(editor)
    if not editor_argv:
        console.print("[red]Error:[/red] $EDITOR is empty. Set $EDITOR to an available editor.")
        sys.exit(1)
    if not shutil.which(editor_argv[0]):
        console.print(f"[red]Error:[/red] Editor '{editor}' not found. Set $EDITOR to an available editor.")
        sys.exit(1)

    result = subprocess.run([*editor_argv, str(file_path)])
    if result.returncode != 0:
        console.print(f"[red]Aborted:[/red] editor exited with code {result.returncode}.")
        if abort_tip:
            print_tip(abort_tip, blank_before=False, console=console)
        sys.exit(result.returncode)
