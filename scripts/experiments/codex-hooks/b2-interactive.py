#!/usr/bin/env python3
"""Capture scripted terminal prompts under the same bounded fixture owner."""

from __future__ import annotations

import argparse
import json
import os
import runpy
import subprocess
import uuid
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("case", choices=("start", "resume", "background", "context"))
    parser.add_argument("--session", default="b2-tui")
    args = parser.parse_args()
    scripts = Path(__file__).resolve().parent
    harness = runpy.run_path(str(scripts / "b2-run.py"))
    round_ = harness["Round"](args.root.resolve())
    capture = round_.root / "captures" / ("97-tui-" + args.case)
    mode = {"start": "system-message", "resume": "stderr", "background": "background", "context": "observe"}[args.case]
    Path(os.environ["PROBE_CONTROL"]).write_text(
        json.dumps(
            {
                "capture": str(capture),
                "mode": mode,
                "nonce": "B2-" + uuid.uuid4().hex,
                "delay": 4,
            }
        )
    )
    os.environ.update(
        TERM="xterm-256color",
        PROBE_CAPTURE_DIR=str(capture),
        PROBE_TURN_RESERVATION="2" if args.case == "background" else "1",
        FORGE_SESSION="",
        FORGE_FORGE_ROOT=str(round_.project),
        LIB_DIR=str(scripts),
        HOOKBIN=str(round_.root / "captures/fixture/hookbin"),
        PROBE_TUI_SESSION=args.session,
    )
    subprocess.run(["/bin/bash", "-c", 'source "$LIB_DIR/lib.sh"; fixture_tee_all'], check=True)
    command = [str(round_.forge), "session"]
    if args.case == "start":
        command += ["start", args.session, "--runtime", "codex"]
    elif args.case == "context":
        command += [
            "start",
            args.session + "-context",
            "--runtime",
            "codex",
            "--resume-from",
            "b2-parent",
            "--strategy",
            "full",
            "--context-delivery",
            "hook",
        ]
    else:
        command += ["resume", args.session]
    command += ["--", "--no-alt-screen"]
    os.chdir(round_.project)
    return harness["RUNTIME"]["bounded_run"](
        [str(round_.forge.with_name("python")), str(scripts / "b2-terminal.py"), args.case, *command],
        capture,
        180,
        5,
        2,
    )


if __name__ == "__main__":
    raise SystemExit(main())
