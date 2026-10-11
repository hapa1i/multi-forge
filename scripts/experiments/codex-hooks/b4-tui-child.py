#!/usr/bin/env python3
"""Transfer into a fresh Codex child, then configure its idle TUI for Stop review."""

from __future__ import annotations

import argparse
import json
import os
import runpy
import shutil
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
GATE = runpy.run_path(str(SCRIPTS / "b4-gate.py"))
PRODUCT = runpy.run_path(str(SCRIPTS / "b4-product.py"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("label")
    parser.add_argument("--session", default="b4-tui-child")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    GATE["validate"](root)
    forge = shutil.which("forge")
    assert forge
    prompt = root / (args.label + "-prompt.txt")
    prompt.write_text(
        "Use apply_patch to create product-tui.txt containing CHILD-CONTROL. Preserve other files and finish."
    )
    configure = root / (args.label + "-configure.json")
    configure.write_text(
        json.dumps(
            [
                sys.executable,
                str(SCRIPTS / "b4-product.py"),
                str(root),
                "configure",
                "--session",
                args.session,
                "--require-fresh",
            ]
        )
    )
    os.environ["PROBE_TURN_RESERVATION"] = "1" if args.resume else "2"
    launch = (
        [forge, "session", "resume", args.session]
        if args.resume
        else [
            forge,
            "session",
            "start",
            args.session,
            "--runtime",
            "codex",
            "--resume-from",
            "b4-parent",
            "--strategy",
            "structured",
        ]
    )
    code = GATE["execute"](
        root,
        args.label,
        {},
        [
            sys.executable,
            str(SCRIPTS / "b4-terminal.py"),
            "--close-after-turn",
            "--initial-turns",
            "0" if args.resume else "1",
            "--after-initial-command-json",
            str(configure),
            "--prompt-file",
            str(prompt),
            "--",
            *launch,
        ],
        260,
    )
    capture = root / "captures" / args.label
    PRODUCT["retain_product"](root, capture, forge, args.session)
    fresh = root / (args.session + "-fresh-policy.json")
    if fresh.exists():
        shutil.copy2(fresh, capture / "fresh-policy.json")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
