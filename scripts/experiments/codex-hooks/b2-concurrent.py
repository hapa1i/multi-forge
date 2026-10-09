#!/usr/bin/env python3
"""One deliberate concurrent-source case; both children use the same private login."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
import uuid
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("thread")
    args = parser.parse_args()
    capture = Path(json.loads(Path(os.environ["PROBE_CONTROL"]).read_text())["capture"])
    original = next(Path(os.environ["CODEX_HOME"]).glob(f"sessions/*/*/*/*{args.thread}.jsonl"))
    before = original.read_bytes()
    active = "ACTIVE-" + uuid.uuid4().hex
    fork_tag = "FORK-" + uuid.uuid4().hex
    source_command = [
        "codex",
        "exec",
        "--json",
        "--sandbox",
        "read-only",
        "resume",
        args.thread,
        f"Concurrent probe marker {active}. Run sleep 12 with exec_command, wait for completion, "
        "then reply SOURCE-FINISHED. Do not write files.",
    ]
    fork_command = [
        "codex",
        "exec",
        "--json",
        "--sandbox",
        "read-only",
        "fork",
        "--ephemeral",
        "--output-schema",
        str(args.root / "fork-schema.json"),
        "-o",
        str(capture / "fork-last.txt"),
        args.thread,
        f"{fork_tag}: Do not use tools. Return the inherited planning sentinel in sentinel "
        "and the ACTIVE- marker from the most recent user request in checkout, or NONE if absent. "
        "Set write_result to not_attempted and plan to the controlling approved plan.",
    ]
    with (capture / "source-stream.jsonl").open("w") as out, (capture / "source-stderr").open("w") as err:
        source = subprocess.Popen(source_command, stdout=out, stderr=err, stdin=subprocess.DEVNULL)
        try:
            until = time.monotonic() + 45
            observed = False
            while source.poll() is None and time.monotonic() < until:
                for path in capture.glob("PreToolUse-*.stdin.json"):
                    payload = json.loads(path.read_text())
                    if (
                        payload.get("session_id") == args.thread
                        and payload.get("tool_name") in {"Bash", "exec_command"}
                        and "sleep 12" in str(payload.get("tool_input", {}))
                    ):
                        observed = True
                if observed:
                    break
                time.sleep(0.05)
            snapshot = original.read_bytes()
            active_at_fork = source.poll() is None and observed
            fork = subprocess.run(fork_command, capture_output=True, text=True, timeout=90, stdin=subprocess.DEVNULL)
            (capture / "fork-stream.jsonl").write_text(fork.stdout)
            (capture / "fork-stderr").write_text(fork.stderr)
            source.wait(timeout=45)
        finally:
            if source.poll() is None:
                source.terminate()
                source.wait(timeout=5)
    final = original.read_bytes()
    facts = {
        "source_command": source_command,
        "fork_command": fork_command,
        "source_exit": source.returncode,
        "fork_exit": fork.returncode,
        "active_at_fork": active_at_fork,
        "active_marker": active,
        "fork_marker": fork_tag,
        "initial_prefix_preserved": final.startswith(before),
        "fork_start_prefix_preserved": final.startswith(snapshot),
        "source_contains_fork_prompt": fork_tag.encode() in final,
        "before_sha256": hashlib.sha256(before).hexdigest(),
        "at_fork_sha256": hashlib.sha256(snapshot).hexdigest(),
        "final_sha256": hashlib.sha256(final).hexdigest(),
    }
    (capture / "concurrent-facts.json").write_text(json.dumps(facts, indent=2) + "\n")
    print(json.dumps(facts))


if __name__ == "__main__":
    main()
