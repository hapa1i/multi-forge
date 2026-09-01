"""Container contracts for Forge log cleanup."""

from __future__ import annotations

import pytest

from tests.fixtures.docker import ContainerLike

pytestmark = [pytest.mark.integration, pytest.mark.docker_host]

_ZOMBIE_PARENT = """\
import ctypes
import os
import signal
import time
from pathlib import Path

libc = ctypes.CDLL(None)
prctl = libc.prctl
prctl.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
prctl.restype = ctypes.c_int
assert prctl(15, bytes([255]) + b"forge", 0, 0, 0) == 0

child = os.fork()
if child == 0:
    os._exit(0)

Path("/tmp/forge-zombie-child.pid").write_text(str(child), encoding="utf-8")

def reap_and_exit(_signum, _frame):
    os.waitpid(child, 0)
    raise SystemExit(0)

signal.signal(signal.SIGTERM, reap_and_exit)
while True:
    time.sleep(1)
"""


def test_clean_removes_real_zombie_process_shards(
    forge_workspace: ContainerLike,
) -> None:
    written = forge_workspace.write_file("/tmp/forge-zombie-parent.py", _ZOMBIE_PARENT)
    assert written.returncode == 0, written.stderr
    launched = forge_workspace.exec(
        "nohup /forge/.venv/bin/python /tmp/forge-zombie-parent.py "
        ">/tmp/forge-zombie-parent.log 2>&1 </dev/null & echo $!"
    )
    assert launched.returncode == 0, launched.stderr
    parent_pid = int(launched.stdout.strip().splitlines()[-1])

    try:
        observed = forge_workspace.exec(
            "for attempt in $(seq 1 100); do "
            "if test -s /tmp/forge-zombie-child.pid; then "
            "child=$(cat /tmp/forge-zombie-child.pid); "
            "state=$(awk '{print $3}' /proc/$child/stat 2>/dev/null || true); "
            'if test "$state" = Z; then echo $child; exit 0; fi; '
            "fi; sleep 0.05; done; exit 1"
        )
        assert observed.returncode == 0, observed.stderr
        zombie_pid = int(observed.stdout.strip().splitlines()[-1])

        seeded = forge_workspace.exec(
            f"mkdir -p ~/.forge/logs/proxy ~/.forge/logs/requests ~/.forge/logs/tool_events; "
            f"printf stale > ~/.forge/logs/proxy/proxy.{zombie_pid}.log; "
            f"printf stale > ~/.forge/logs/requests/20260830_proxy.{zombie_pid}.jsonl; "
            f"printf stale > ~/.forge/logs/tool_events/20260830_proxy.{zombie_pid}.jsonl"
        )
        assert seeded.returncode == 0, seeded.stderr

        cleaned = forge_workspace.exec("forge logs clean --yes")

        assert cleaned.returncode == 0, cleaned.stderr
        assert "Removed 3 log files" in cleaned.stdout
        remaining = forge_workspace.exec(
            f"test ! -e ~/.forge/logs/proxy/proxy.{zombie_pid}.log; "
            f"test ! -e ~/.forge/logs/requests/20260830_proxy.{zombie_pid}.jsonl; "
            f"test ! -e ~/.forge/logs/tool_events/20260830_proxy.{zombie_pid}.jsonl"
        )
        assert remaining.returncode == 0, remaining.stderr
    finally:
        forge_workspace.exec(
            f"kill -TERM {parent_pid} 2>/dev/null || true; "
            f"rm -f /tmp/forge-zombie-parent.py /tmp/forge-zombie-child.pid /tmp/forge-zombie-parent.log"
        )
