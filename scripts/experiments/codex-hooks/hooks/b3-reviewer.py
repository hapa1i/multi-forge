#!/usr/bin/env python3
"""Admission-compatible B3 stub; configurable findings, never provider inference."""

import json
import os
import runpy
import signal
import sys
import time
from pathlib import Path


def main() -> None:
    if sys.argv[1:] == ["--version"]:
        print("2.1.294 (Claude Code fixture; no inference)")
        return
    if "--help" in sys.argv:
        print(
            "--restricted --safe-mode --strict-mcp-config --disable-slash-commands --tools --allowedTools --setting-sources"
        )
        return
    runtime = runpy.run_path(str(Path(__file__).resolve().parents[1] / "probe-runtime.py"))
    runtime["register_process"]()
    control = json.loads(Path(os.environ["PROBE_CONTROL"]).read_text())
    directory = Path(control["capture"])
    directory.mkdir(parents=True, exist_ok=True)

    def record(kind, **fields):
        runtime["append_json"](
            directory / "reviewer.jsonl",
            {"kind": kind, "pid": os.getpid(), "at": time.time(), "synthetic": True, **fields},
        )

    def terminated(sig, frame):
        record("signal", signal=sig)
        raise SystemExit(128 + sig)

    signal.signal(signal.SIGTERM, terminated)
    record("dispatch_started")
    (directory / f"reviewer-{os.getpid()}.prompt.txt").write_text(sys.stdin.read())
    if control.get("reviewer") == "sleep":
        time.sleep(90)
    if control.get("replace_plan"):
        Path(control["plan_path"]).write_text(control["replace_plan"])
    verdict = control.get("verdict", {"verdict": "aligned", "confidence": 1.0, "violations": []})
    record("completed", verdict=verdict)
    print(json.dumps(verdict))


if __name__ == "__main__":
    main()
