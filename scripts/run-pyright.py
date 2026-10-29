#!/usr/bin/env python3
"""Run the locked Pyright wheel with an existing Node.js installation."""

from __future__ import annotations

import importlib.metadata
import os
import shutil
import sys
from pathlib import Path


def main() -> int:
    """Invoke bundled JavaScript without the Python wrapper's download fallback."""
    node = shutil.which("node")
    if node is None:
        print(
            "Node.js is required for the Pyright hook. Install a reviewed Node.js release on PATH, "
            "then rerun make pre-commit. This hook does not download Node.js.",
            file=sys.stderr,
        )
        return 2
    try:
        distribution = importlib.metadata.distribution("pyright")
    except importlib.metadata.PackageNotFoundError:
        print("The locked Pyright wheel is missing. Run make deps, then rerun make pre-commit.", file=sys.stderr)
        return 2
    entry = Path(str(distribution.locate_file("pyright/dist/index.js")))
    if not entry.is_file():
        print(
            "The Pyright wheel is missing its bundled JavaScript entry point. "
            "Restore the reviewed environment with make deps; if this persists, review the wheel layout.",
            file=sys.stderr,
        )
        return 2
    try:
        os.execv(node, [node, str(entry), *sys.argv[1:]])
    except OSError as error:
        print(f"Cannot run the installed Node.js executable {node}: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
