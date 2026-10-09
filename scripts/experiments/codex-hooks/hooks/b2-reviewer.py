#!/usr/bin/env python3
"""Admission-capable, no-inference Claude reviewer for the B2 fixture."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def main() -> None:
    if sys.argv[1:] == ["--version"]:
        print("2.1.291 (Claude Code fixture; no inference)")
        return
    if "--help" in sys.argv:
        print(
            "--restricted --safe-mode --strict-mcp-config --disable-slash-commands --tools --allowedTools --setting-sources"
        )
        return
    control = json.loads(Path(os.environ["PROBE_CONTROL"]).read_text())
    capture = Path(control["capture"])
    capture.mkdir(parents=True, exist_ok=True)

    def record(kind: str, **fields: object) -> None:
        event = {
            "kind": kind,
            "at": time.time(),
            "pid": os.getpid(),
            "pgid": os.getpgrp(),
            "run_id": os.environ.get("FORGE_RUN_ID"),
            "parent_run_id": os.environ.get("FORGE_PARENT_RUN_ID"),
            "synthetic": True,
            **fields,
        }
        with (capture / "reviewer.jsonl").open("a") as stream:
            stream.write(json.dumps(event) + "\n")

    def interrupted(sig: int, _frame: object) -> None:
        record("signal", signal=sig)
        raise SystemExit(128 + sig)

    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    record("dispatch_started")
    prompt = sys.stdin.read()
    (capture / f"reviewer-{os.getpid()}.prompt.txt").write_text(prompt)
    if control.get("reviewer") == "sleep":
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(180)"])
        record("descendant", child_pid=child.pid)
        time.sleep(180)
    record("completed")
    print(json.dumps({"verdict": "aligned", "confidence": 0.99, "violations": []}))


if __name__ == "__main__":
    main()
