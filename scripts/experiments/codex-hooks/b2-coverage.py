#!/usr/bin/env python3
"""Catch-all tool observations and repeated current-dispatcher replay timings."""

from __future__ import annotations

import argparse
import json
import os
import runpy
import subprocess
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
HARNESS = runpy.run_path(str(SCRIPTS / "b2-run.py"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    round_ = HARNESS["Round"](args.root.resolve())
    python = str(round_.forge.with_name("python"))
    mcp_log = round_.root / "captures/mcp-requests.jsonl"
    extra = (
        "--enable",
        "multi_agent",
        "-c",
        f"mcp_servers.b2.command={json.dumps(python)}",
        "-c",
        "mcp_servers.b2.args=" + json.dumps([str(SCRIPTS / "hooks/b2-mcp.py"), str(mcp_log)]),
    )
    prompt = (
        "This is an authorized tool-coverage probe. Call update_plan twice, first with two pending steps then "
        "with step one completed and step two in_progress. Call the disposable b2 MCP echo tool once with B2-MCP. "
        "Use exec_command to run sleep 3; printf B2-SHELL with yield_time_ms=1000, then write_stdin until it ends. "
        "Spawn exactly one agent instructed to reply B2-CHILD with no tools, wait for it, then close it. "
        "Do not delegate anything else. Add coverage.txt containing OK with one apply_patch. Mark the plan completed. "
        "If a named tool is unavailable, report that without a substitute. Reply DONE."
    )
    round_.run("93-tools-off", prompt, extra=extra, reservation=2)
    round_.run(
        "93-tools-on",
        "Call update_plan with one completed step. Run printf B2-ON through exec_command. "
        "Then use apply_patch once to add coverage_on.txt containing OK. Reply DONE.",
        session="b2-supervised",
    )

    timing = round_.root / "captures/93-dispatch-timings"
    timing.mkdir()
    control = {"capture": str(timing), "mode": "observe", "reviewer": "fast"}
    Path(os.environ["PROBE_CONTROL"]).write_text(json.dumps(control))
    payloads = [
        json.loads(path.read_text()) for path in (round_.root / "captures/93-tools-off").glob("PreToolUse-*.stdin.json")
    ]
    tools = {payload["tool_name"]: payload for payload in payloads}
    command = [str(Path(os.environ["FORGE_HOME"]) / "bin/forge-hook"), "codex-policy-check"]
    for session in ("b2-plain", "b2-supervised"):
        for name, original in tools.items():
            for sample in range(5):
                payload = json.loads(json.dumps(original))
                # Two identical calls expose the cache; subsequent patches use
                # different content to require distinct semantic cache keys.
                if name == "apply_patch":
                    payload["tool_input"]["command"] = (
                        "*** Begin Patch\n*** Add File: latency_b2.txt\n+"
                        + ("CACHED" if sample < 2 else f"SAMPLE-{sample}")
                        + "\n*** End Patch"
                    )
                env = dict(os.environ, FORGE_SESSION=session, FORGE_FORGE_ROOT=str(round_.project))
                before = time.perf_counter()
                result = subprocess.run(
                    command,
                    input=json.dumps(payload),
                    text=True,
                    env=env,
                    cwd=round_.project,
                    capture_output=True,
                    timeout=60,
                )
                HARNESS["RUNTIME"]["append_json"](
                    timing / "samples.jsonl",
                    {
                        "command": command,
                        "session": session,
                        "tool": name,
                        "sample": sample,
                        "seconds": time.perf_counter() - before,
                        "returncode": result.returncode,
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                        "payload": payload,
                        "measurement": "dispatcher replay wall time; instrumentation included; no executor/model turn",
                    },
                )


if __name__ == "__main__":
    main()
