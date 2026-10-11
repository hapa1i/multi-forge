#!/usr/bin/env python3
"""Kill a fixture-owned Stop hook only after its stub reviewer records dispatch."""

from __future__ import annotations

import argparse
import json
import runpy
import shutil
import signal
import sys
import threading
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
GATE = runpy.run_path(str(SCRIPTS / "b4-gate.py"))
PRODUCT = runpy.run_path(str(SCRIPTS / "b4-product.py"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("label")
    parser.add_argument("--cancel-executor", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    GATE["validate"](root)
    forge = shutil.which("forge")
    assert forge
    capture = root / "captures" / args.label
    done = threading.Event()

    def terminate_hook() -> None:
        while not done.wait(0.1):
            starts, reviewers = capture / "stop-starts.jsonl", capture / "reviewer.jsonl"
            if not starts.exists() or not reviewers.exists():
                continue
            try:
                events = [json.loads(line) for line in reviewers.read_text().splitlines()]
                if not any(row.get("kind") == "dispatch_started" for row in events):
                    continue
                row = json.loads(starts.read_text().splitlines()[-1])
                current = GATE["RUNTIME"]["process_table"]().get(row["pid"])
                if not GATE["RUNTIME"]["same_process"](row, current):
                    continue
            except ValueError:
                continue  # An append may still be in progress.
            target, sig = row, signal.SIGKILL
            if args.cancel_executor:
                table = GATE["RUNTIME"]["process_table"]()
                target = table.get(row["ppid"])
                if target is None:
                    continue
                # The round registry records the wrapper before it execs Codex.
                registry = capture / "run/processes.jsonl"
                registered = [json.loads(line) for line in registry.read_text().splitlines()]
                if not any(
                    r["pid"] == target["pid"] and GATE["RUNTIME"]["same_process"](r, target) for r in registered
                ):
                    raise ValueError("Refuse to cancel an executor absent from this capture's owned process registry")
                sig = signal.SIGTERM
            GATE["RUNTIME"]["signal_owned"]([target], sig)
            (capture / "fault.json").write_text(
                json.dumps(
                    {
                        "fault": "executor TERM" if args.cancel_executor else "Stop owner SIGKILL",
                        "owner": row,
                        "target": target,
                        "at": time.time(),
                        "after_dispatch": True,
                    },
                    indent=2,
                )
            )
            return

    worker = threading.Thread(target=terminate_hook, daemon=True)
    worker.start()
    try:
        code = GATE["execute"](
            root,
            args.label,
            {
                "reviewer": "sleep",
                "sleep_seconds": 90,
                "fault": "executor cancellation" if args.cancel_executor else "Stop owner SIGKILL after dispatch",
            },
            [
                forge,
                "session",
                "resume",
                "b4-executor",
                "--task",
                (
                    "Use apply_patch to create product-cancel.txt containing CANCEL-CONTROL. Leave other files alone and finish."
                    if args.cancel_executor
                    else "Use apply_patch to create product-kill.txt containing KILL-CONTROL. Leave other files alone and finish."
                ),
            ],
            180,
        )
    finally:
        done.set()
        worker.join(timeout=2)
    PRODUCT["retain_product"](root, capture, forge, "b4-executor")
    if not (capture / "fault.json").exists():
        raise ValueError("Fault did not reach a recorded reviewer dispatch")
    return code


if __name__ == "__main__":
    sys.exit(main())
