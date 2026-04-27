"""Process utilities for Forge.

Provides PID checking and port-based process discovery. Used by proxy
and backend lifecycle management.
"""

from __future__ import annotations

import os
import subprocess


def is_pid_alive(pid: int) -> bool:
    """Return True if pid appears to refer to a running process.

    Uses the standard POSIX check: ``os.kill(pid, 0)``.

    Notes:
        - If we don't have permission to signal the process
          (``PermissionError``), we treat it as alive.
        - PID reuse is possible but out of scope for stale pruning.
    """
    if pid <= 0:
        return False

    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def find_pid_by_port(port: int) -> int | None:
    """Find the PID of the process listening on the given TCP port.

    Uses ``lsof`` on macOS/Linux. Returns None if no process is found,
    ``lsof`` is unavailable, or the command times out.
    """
    try:
        result = subprocess.run(
            ["lsof", "-ti", f"TCP:{port}", "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None
        # lsof may return multiple PIDs (one per line); take the first
        first_line = result.stdout.strip().splitlines()[0]
        return int(first_line)
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        return None
