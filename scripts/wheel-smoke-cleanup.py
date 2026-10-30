"""Wait for the isolated wheel smoke's backend before removing its install."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

STOP_TIMEOUT = 10.0
EXIT_TIMEOUT = 10.0


def stop_and_wait(forge_home: Path, forge: Path, port: int) -> None:
    """Stop the recorded backend and verify its complete group has stopped writing."""
    process_id = f"litellm-{port}"
    registry = json.loads((forge_home / "backends" / "index.json").read_text())
    processes = registry.get("processes", {})
    if registry.get("version") != 2 or set(processes) != {process_id}:
        raise ValueError("cannot verify the isolated backend registry")
    process = processes[process_id]
    group_id = process.get("pid")
    if (
        process.get("process_id") != process_id
        or process.get("adapter_type") != "litellm"
        or process.get("port") != port
        or type(group_id) is not int
        or group_id <= 1
    ):
        raise ValueError("cannot verify the isolated backend process group")

    # Stop unregisters immediately; retain its original group id until every worker exits.
    print(f"Stopping wheel smoke backend {process_id} (process group {group_id}).", file=sys.stderr, flush=True)
    stopped = subprocess.run([str(forge), "model", "backend", "stop", process_id], timeout=STOP_TIMEOUT, check=False)
    if stopped.returncode:
        raise RuntimeError(f"backend stop exited with status {stopped.returncode}")

    deadline = time.monotonic() + EXIT_TIMEOUT
    live: list[int] = []
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"process group {group_id} still has live members: {live}")
        snapshot = subprocess.run(
            ["ps", "-axo", "pid=,pgid=,stat="],
            capture_output=True,
            text=True,
            check=True,
            timeout=min(2.0, remaining),
        )
        live = []
        for line in snapshot.stdout.splitlines():
            pid, pgid, status = line.split()
            if int(pgid) == group_id and not status.startswith("Z"):
                live.append(int(pid))
        # Orphan zombies may await PID 1 indefinitely, but cannot write into the venv.
        if not live:
            print(f"Wheel smoke backend process group {group_id} has exited.", file=sys.stderr)
            return
        time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))


def main() -> int:
    try:
        stop_and_wait(Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3]))
    except (OSError, ValueError, TypeError, AttributeError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"Wheel smoke backend cleanup failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
