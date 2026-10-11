#!/usr/bin/env python3
"""Exercise the shipped reviewer watchdog without changing native JSON output."""

from __future__ import annotations

import json
import os
import runpy
import subprocess
import sys
import time
from pathlib import Path

from forge.core.reactive.watchdog import run_guarded


def main() -> int:
    runtime = runpy.run_path(str(Path(__file__).with_name("probe-runtime.py")))
    runtime["register_process"]()
    capture = Path(os.environ["PROBE_CAPTURE"])
    started = time.monotonic()
    seconds = min(
        float(sys.argv[1]),
        float(os.environ.get("PROBE_REVIEW_DEADLINE", "inf")) - started,
    )
    owner = runtime["process_table"]()[os.getpid()]
    (capture / "guard-start.json").write_text(json.dumps({"owner": owner, "seconds": seconds, "at": time.time()}))
    guarded = run_guarded
    if os.environ.get("PROBE_CANCEL_FIRST") == "1":
        guarded = runpy.run_path(str(Path(__file__).with_name("b5-watchdog.py")))["run_guarded"]
    try:
        result = guarded(
            sys.argv[2:],
            input=sys.stdin.read(),
            env=dict(os.environ),
            cwd=os.getcwd(),
            timeout=seconds,
        )
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
        code = result.returncode
    except subprocess.TimeoutExpired:
        code = 124
    (capture / "guard-result.json").write_text(
        json.dumps({"returncode": code, "elapsed_seconds": time.monotonic() - started}) + "\n"
    )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
