#!/usr/bin/env python3
"""Run B4 managed start/resume and multi-prompt controls through the owned runtime gate."""

from __future__ import annotations

import argparse
import json
import os
import runpy
import shutil
import subprocess
import sys
from pathlib import Path

from forge.session.store import SessionStore

SCRIPTS = Path(__file__).resolve().parent
GATE = runpy.run_path(str(SCRIPTS / "b4-gate.py"))


def setup_parent(root: Path, forge: str) -> None:
    project = root / "project"
    store = SessionStore(str(project), "b4-parent")
    if store.exists():
        return
    result = subprocess.run(
        [forge, "session", "start", "b4-parent", "--no-launch", "--no-proxy"],
        cwd=project,
        text=True,
        capture_output=True,
        timeout=60,
    )
    (root / "parent-setup.json").write_text(json.dumps(vars(result), default=str, indent=2))
    result.check_returncode()
    transcript = root / "parent.jsonl"
    transcript.write_text(
        json.dumps(
            {
                "requestId": "b4-parent",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "text",
                            "text": "Synthetic B4 fixture. Follow the operator's bounded file task.",
                        }
                    ],
                },
            }
        )
        + "\n"
    )
    store.update(
        timeout_s=5,
        mutate=lambda state: setattr(state.confirmed, "transcript_path", str(transcript)),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("label")
    parser.add_argument("action", choices=("start", "resume", "tui"))
    parser.add_argument("--control", type=Path)
    parser.add_argument("--prompt", default="Do not use tools. Reply exactly READY.")
    parser.add_argument("--prompts-json", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    GATE["validate"](root)
    forge = shutil.which("forge")
    assert forge
    control = json.loads(args.control.read_text()) if args.control else {}
    if args.action == "start":
        setup_parent(root, forge)
        command = [
            forge,
            "session",
            "start",
            "b4-executor",
            "--runtime",
            "codex",
            "--resume-from",
            "b4-parent",
            "--strategy",
            "structured",
            "--task",
            args.prompt,
        ]
    else:
        command = [forge, "session", "resume", "b4-executor"]
        if args.action == "resume":
            command += ["--task", args.prompt]
        else:
            if not args.prompts_json:
                raise ValueError("TUI cases require a saved prompt list and an explicit budget reservation.")
            prompts = json.loads(args.prompts_json.read_text())
            os.environ["PROBE_TURN_RESERVATION"] = str(len(prompts) + int(control.get("mode") == "block"))
            command = [
                sys.executable,
                str(SCRIPTS / "b4-terminal.py"),
                "--close-after-turn",
                "--prompts-json",
                str(args.prompts_json),
                *command,
            ]
    if args.action != "tui" and control.get("mode") == "block":
        os.environ["PROBE_TURN_RESERVATION"] = "2"
    return GATE["execute"](root, args.label, control, command, 260 if args.action == "tui" else 180)


if __name__ == "__main__":
    raise SystemExit(main())
