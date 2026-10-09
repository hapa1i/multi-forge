#!/usr/bin/env python3
"""Observe ordinary deadlines, native hook expiry, and controlled interruption."""

from __future__ import annotations

import argparse
import json
import runpy
import signal
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HARNESS = runpy.run_path(str(Path(__file__).with_name("b2-run.py")))
RUNTIME = HARNESS["RUNTIME"]


def rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    result = []
    for line in path.read_text().splitlines():
        try:
            result.append(json.loads(line))
        except ValueError:
            pass
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    round_ = HARNESS["Round"](args.root.resolve())
    for mode in ("ordinary-deadline", "natural-review-expiry", "hook-death", "executor-cancel"):
        name = "95-" + mode
        capture = round_.root / "captures" / name
        prompt = (
            f"Use apply_patch exactly once to add {name}.txt containing PROBE. "
            "If blocked or a hook fails, do not retry. Then reply DONE."
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                round_.run, name, prompt, mode=mode, reviewer="sleep", session="b2-supervised", seconds=130
            )
            if mode in {"hook-death", "executor-cancel"}:
                until = time.monotonic() + 90
                while not future.done() and time.monotonic() < until:
                    entered = [row for row in rows(capture / "reviewer.jsonl") if row["kind"] == "dispatch_started"]
                    if entered:
                        # Give the reviewer's descendant its startup interval.
                        time.sleep(1)
                        if mode == "hook-death":
                            target = next(
                                row["identity"]
                                for row in rows(capture / "hook-entry.jsonl")
                                if row["hook"] == ["codex-policy-check"]
                            )
                            sig = signal.SIGKILL
                        else:
                            # The first registered child is the Python Codex shim;
                            # exec retains its PID/start time when loading Codex.
                            target = rows(capture / "processes.jsonl")[0]
                            sig = signal.SIGINT
                        RUNTIME["signal_owned"]([target], sig)
                        (capture / "injected-signal.json").write_text(
                            json.dumps(
                                {
                                    "at": time.time(),
                                    "target": target,
                                    "signal": sig,
                                    "after_reviewer_entry": entered,
                                },
                                indent=2,
                            )
                            + "\n"
                        )
                        break
                    time.sleep(0.05)
            future.result()
        round_.setup("policy", "supervisor", "status", "--json", session="b2-supervised")
        round_.setup("telemetry", "activity", "b2-supervised", "--json")
        manifest = round_.project / ".forge/sessions/b2-supervised/forge.session.json"
        (capture / "manifest-after.json").write_bytes(manifest.read_bytes())


if __name__ == "__main__":
    main()
