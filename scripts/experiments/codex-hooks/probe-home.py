#!/usr/bin/env python3
"""Create or validate an owned login home without reading or copying credentials."""

from __future__ import annotations

import argparse
from pathlib import Path

MARKER = ".forge-codex-probe-home"
MARKER_TEXT = "independent-login-v1\n"


def prepare_home(path: Path) -> Path:
    """Refuse real, symlinked, or unowned existing homes before mutation."""
    path = path.absolute()
    if path.resolve() != path or path == Path.home() / ".codex":
        raise ValueError("Use a canonical probe directory, never the host Codex home or a symlink.")
    if path.exists():
        marker = path / MARKER
        if not marker.is_file() or marker.is_symlink() or marker.read_text() != MARKER_TEXT:
            raise ValueError("Existing home is not owned by this probe; choose a new directory.")
    else:
        path.mkdir(parents=True, mode=0o700)
        (path / MARKER).write_text(MARKER_TEXT)
        (path / "config.toml").write_text('cli_auth_credentials_store = "file"\n[features]\nhooks = true\n')
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    try:
        prepare_home(args.path)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
