#!/usr/bin/env python3
"""Observe a fixture hook without changing its payload, output, or Forge state."""

import json
import os
import runpy
import sys
import time
from pathlib import Path


def main() -> None:
    started = time.monotonic()
    root = Path(os.environ["PROBE_ROUND_ROOT"])
    if (root / "B5_ROUND").read_text() != "independent-b5-round-v1\n" or (root / "CLOSED").exists():
        raise ValueError("Not an open B5 fixture")
    capture = Path(os.environ.get("PROBE_CAPTURE", str(root / "captures/hook-baseline")))
    if not capture.resolve().is_relative_to(root / "captures"):
        raise ValueError("Capture must belong to the round")
    runtime = runpy.run_path(str(Path(__file__).resolve().parents[1] / "probe-runtime.py"))
    runtime["register_process"]()
    payload = json.load(sys.stdin)
    runtime["append_json"](
        capture / "hooks.jsonl",
        {
            "event": sys.argv[1],
            "at": time.time(),
            "pid": os.getpid(),
            "ppid": os.getppid(),
            "cwd": str(Path.cwd()),
            "payload": payload,
            "forge_identity": {
                key: os.environ.get(key)
                for key in (
                    "FORGE_SESSION",
                    "FORGE_FORGE_ROOT",
                    "FORGE_DEPTH",
                    "FORGE_LAUNCH_ID",
                    "FORGE_COMMAND",
                )
            },
        },
    )
    if os.environ.get("PROBE_BOUNDARY_EVENT"):
        active = runpy.run_path(str(Path(__file__).resolve().parents[1] / "b5-active.py"))
        active["observe"](sys.argv[1], payload, started)


if __name__ == "__main__":
    main()
