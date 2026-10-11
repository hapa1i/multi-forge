#!/usr/bin/env python3
"""Kill only the owned review hook after a native fork starts a sleeping tool."""

from __future__ import annotations

import argparse
import json
import os
import runpy
import signal
import subprocess
import sys
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
RUNTIME = runpy.run_path(str(SCRIPTS / "probe-runtime.py"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", default="G13-native-owner-death")
    parser.add_argument("--config", action="append", default=[])
    args = parser.parse_args()
    root = Path(os.environ["PROBE_ROUND_ROOT"])
    label = args.label
    capture = root / "captures" / label
    prompt = root / "prompts/native-death.txt"
    prompt.write_text(
        "Run the shell command sleep 30 exactly once and wait for it; this is an authorized lifetime probe. "
        "Then return the inherited planning marker and approved color with checkout_readme empty. "
        "Do not spawn agents or write files.\n"
    )
    command = [
        sys.executable,
        str(SCRIPTS / "b5-fork.py"),
        label,
        "01a12b5c-ce1a-72c2-ad3f-05d75f3fba00",
        str(prompt),
        "--model",
        "gpt-6.1-sol",
        "--isolate",
        "--guarded",
        "--seconds",
        "40",
    ]
    for config in args.config:
        command += ["--config", config]
    child = subprocess.Popen(command)
    injected = False
    until = time.monotonic() + 40
    while child.poll() is None and time.monotonic() < until:
        time.sleep(0.05)
        progress, guard = capture / "native-events.jsonl", capture / "guard-start.json"
        if not progress.exists() or not guard.exists():
            continue
        try:
            events = [json.loads(line) for line in progress.read_text().splitlines()]
            owner = json.loads(guard.read_text())["owner"]
        except ValueError:
            continue
        if not any(
            row.get("type") == "item.started"
            and row.get("item", {}).get("type") == "command_execution"
            and "sleep 30" in row["item"].get("command", "")
            for row in events
        ):
            continue
        # Wait briefly for the native tool's process to exist before killing its owner.
        time.sleep(0.3)
        table = RUNTIME["process_table"]()
        if not RUNTIME["same_process"](owner, table.get(owner["pid"])):
            raise ValueError("The recorded review owner no longer exists.")
        descendants = {owner["pid"]}
        while True:
            expanded = descendants | {pid for pid, row in table.items() if row["ppid"] in descendants}
            if expanded == descendants:
                break
            descendants = expanded
        observed = []
        for pid in sorted(descendants):
            name = subprocess.run(
                ["ps", "-p", str(pid), "-o", "comm="],
                capture_output=True,
                text=True,
                check=False,
            )
            observed.append({**table[pid], "executable": name.stdout.strip()})
        (capture / "owned-processes-before-kill.json").write_text(json.dumps(observed, indent=2))
        RUNTIME["signal_owned"]([owner], signal.SIGKILL)
        (capture / "injected-signal.json").write_text(
            json.dumps(
                {
                    "target": owner,
                    "signal": signal.SIGKILL,
                    "after_native_tool_start": True,
                    "thread_ids": [row["thread_id"] for row in events if row.get("type") == "thread.started"],
                },
                indent=2,
            )
        )
        injected = True
        break
    code = child.wait(timeout=15)
    (capture / "fault-result.json").write_text(json.dumps({"injected": injected, "driver_returncode": code}))
    return 0 if injected else 1


if __name__ == "__main__":
    raise SystemExit(main())
