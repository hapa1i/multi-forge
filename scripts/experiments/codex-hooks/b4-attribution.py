#!/usr/bin/env python3
"""Exercise B4 turn attribution and recovery in one bounded native multi-prompt session."""

from __future__ import annotations

import argparse
import json
import os
import runpy
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
GATE = runpy.run_path(str(SCRIPTS / "b4-gate.py"))
PRODUCT = runpy.run_path(str(SCRIPTS / "b4-product.py"))
SESSION = "b4-attribution"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("action", choices=("run", "configure", "manual", "commit", "retain"))
    parser.add_argument("--label", default="03-attribution")
    parser.add_argument("--turn", type=int)
    args = parser.parse_args()
    root = args.root.resolve()
    GATE["validate"](root)
    forge = shutil.which("forge")
    assert forge
    project = root / "project"
    if args.action == "configure":
        PRODUCT["configure"](root, forge, session=SESSION)
        (project / "large-read.txt").write_text("B4 ordinary read fixture.\n" * 300)
        return 0
    if args.action != "run":
        capture = root / "captures" / args.label / f"after-turn-{args.turn}"
        capture.mkdir(exist_ok=False)
        PRODUCT["retain_product"](root, capture, forge, SESSION)
        if args.action == "manual":
            (project / "notes.txt").write_text("Operator-owned notes between turns. Preserve this exact text.\n")
            (project / ".DS_Store").write_bytes(b"\0\0\0\1Bud1")
        elif args.action == "commit":
            subprocess.run(["git", "add", "work.txt"], cwd=project, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "operator saves approved work"],
                cwd=project,
                check=True,
            )
        return 0
    runpy.run_path(str(SCRIPTS / "b4-cases.py"))["setup_parent"](root, forge)
    prompts = [
        "Use apply_patch to create work.txt containing FIRST. Preserve all other files. Then finish.",
        "Do not use any tools. Reply exactly QUESTION-ONLY.",
        "Use apply_patch to append SECOND to work.txt. Preserve all other files. Then finish.",
        "Use exec_command once to run cat large-read.txt with max_output_tokens 5000. Do not edit files. Then finish.",
        "Use apply_patch to append THIRD to work.txt. Preserve all other files. Then finish.",
    ]
    own = [sys.executable, str(Path(__file__).resolve()), str(root)]
    commands = [None] + [
        [*own, action, "--label", args.label, "--turn", str(turn)]
        for turn, action in enumerate(("manual", "commit", "retain", "retain"), 1)
    ]
    prompt_file, command_file, configure_file = (
        root / f"{args.label}-{name}.json" for name in ("prompts", "commands", "configure")
    )
    prompt_file.write_text(json.dumps(prompts))
    command_file.write_text(json.dumps(commands))
    configure_file.write_text(json.dumps([*own, "configure"]))
    # One initial transfer plus five explicit prompts. Trust and enrollment each
    # reserve a separate unit; the hard round ceiling remains eight in the wrapper.
    os.environ["PROBE_TURN_RESERVATION"] = "6"
    code = GATE["execute"](
        root,
        args.label,
        {},
        [
            sys.executable,
            str(SCRIPTS / "b4-terminal.py"),
            "--close-after-turn",
            "--initial-turns",
            "1",
            "--after-initial-command-json",
            str(configure_file),
            "--prompts-json",
            str(prompt_file),
            "--before-prompts-commands-json",
            str(command_file),
            "--",
            forge,
            "session",
            "start",
            SESSION,
            "--runtime",
            "codex",
            "--resume-from",
            "b4-parent",
            "--strategy",
            "structured",
        ],
        260,
    )
    capture = root / "captures" / args.label / "after-turn-5"
    capture.mkdir(exist_ok=False)
    PRODUCT["retain_product"](root, capture, forge, SESSION)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
